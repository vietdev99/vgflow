#!/usr/bin/env python3
"""
Validator: verify-goal-security.py

Phase B v2.5 (2026-04-23): goal-level security declaration check.

Reads TEST-GOALS.md frontmatter + API-CONTRACTS.md endpoints, validates
each goal's `security_checks` section covers required OWASP categories
based on endpoint type + project risk profile.

Severity matrix (enforced):
- critical_goal_domain (auth/payment/billing) + owasp_top10_2021 empty
  → HARD BLOCK
- Mutation endpoint (POST/PUT/PATCH/DELETE) + csrf empty + cookie auth
  → HARD BLOCK
- Mutation endpoint + rate_limit empty → HARD BLOCK
- auth_model mismatch với API-CONTRACTS Block 1 Auth line → HARD BLOCK
- Read-only GET + security_checks empty → WARN + override debt

Usage:
  verify-goal-security.py --phase <N>

Exit codes:
  0 PASS or WARN (advisory only)
  1 BLOCK (security declaration missing for critical/mutation endpoint)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Goal header in TEST-GOALS.md — `## G-XX: title` or frontmatter blocks
GOAL_HEADER_RE = re.compile(r"^##\s+(G-\d+)[:\s]", re.MULTILINE)
# Frontmatter block between `---\n...\n---`
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL | re.MULTILINE)

# API-CONTRACTS endpoint header: `## METHOD /path` or `### METHOD /path`
ENDPOINT_HEADER_RE = re.compile(
    r"^#{2,3}\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)",
    re.MULTILINE | re.IGNORECASE,
)
# Auth line in endpoint block: **Auth:** <value>
AUTH_LINE_RE = re.compile(r"^\*\*Auth\s*:\*\*\s*(.+)$", re.MULTILINE)

# Goal trigger that embeds endpoint: "POST /api/v1/..." or "Click ..." → extract
# Path excludes quote chars to avoid including trailing `"` from YAML string value.
TRIGGER_ENDPOINT_RE = re.compile(
    r"""\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s"'`]+)""",
    re.IGNORECASE,
)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _read_config() -> dict:
    """Read config for critical_goal_domains + project risk profile."""
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    defaults = {
        "critical_goal_domains": ["auth", "payment", "billing", "admin"],
        "project_risk_profile": "moderate",  # critical | moderate | low
        "cookie_auth": True,  # assume cookie unless explicit
    }
    if not cfg.exists():
        return defaults
    text = cfg.read_text(encoding="utf-8", errors="replace")

    m = re.search(
        r"^\s*critical_goal_domains:\s*\[([^\]]+)\]", text, re.MULTILINE,
    )
    if m:
        items = [x.strip().strip("'\"") for x in m.group(1).split(",")]
        defaults["critical_goal_domains"] = [x for x in items if x]

    m = re.search(
        r"^\s*project_risk_profile:\s*['\"]?(critical|moderate|low)['\"]?",
        text, re.MULTILINE,
    )
    if m:
        defaults["project_risk_profile"] = m.group(1)
    return defaults


def _parse_goal_blocks(text: str) -> list[dict]:
    """Split TEST-GOALS.md into per-goal sections.

    Each goal has either:
      - A frontmatter block (---\n...\n---) with `id: G-XX`
      - Or a `## G-XX: title` header followed by prose

    Returns list of {id, raw_frontmatter, body_text}.
    """
    goals: list[dict] = []

    # Strategy: iterate through `---` blocks that contain `id: G-`
    for m in FRONTMATTER_RE.finditer(text):
        fm_text = m.group(1)
        id_match = re.search(r"^id:\s*(G-\d+)", fm_text, re.MULTILINE)
        if id_match:
            goals.append({
                "id": id_match.group(1),
                "frontmatter": fm_text,
                "start_offset": m.start(),
            })

    return goals


def _yaml_field(block: str, key: str) -> str | None:
    """Extract top-level key from frontmatter-like YAML (simple regex)."""
    m = re.search(
        rf"^{re.escape(key)}:\s*(.+?)(?=\n[a-zA-Z_]+:|\n---|\Z)",
        block, re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _yaml_nested_field(block: str, parent: str, child: str) -> str | None:
    """Extract nested key e.g. security_checks.rate_limit.

    Note: _yaml_field strips leading whitespace, so first child can appear
    at column 0. Allow `^\\s*` (zero or more) instead of `^\\s+`.
    """
    parent_block = _yaml_field(block, parent)
    if not parent_block:
        return None
    m = re.search(
        rf"^\s*{re.escape(child)}:\s*(.+?)(?=\n\s*[a-zA-Z_]+:|\Z)",
        parent_block, re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _yaml_nested_list_present(block: str, parent: str, child: str) -> bool:
    """Check if nested list has ≥1 item (e.g. owasp_top10_2021)."""
    nested = _yaml_nested_field(block, parent, child)
    if not nested:
        return False
    # Strip surrounding whitespace + check for list items
    return bool(re.search(r"^\s*-\s+\S", nested, re.MULTILINE))


def _parse_api_contracts(text: str) -> dict[str, dict]:
    """Parse API-CONTRACTS.md endpoints with auth lines.

    Returns dict keyed by (METHOD, path) → {auth_raw, auth_classified}.
    """
    endpoints: dict[str, dict] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = ENDPOINT_HEADER_RE.match(line)
        if m:
            method = m.group(1).upper()
            path = m.group(2).strip().rstrip("/")
            auth_raw = None
            # Look up to 20 lines ahead for Auth line (before next endpoint)
            for j in range(i + 1, min(i + 21, len(lines))):
                if ENDPOINT_HEADER_RE.match(lines[j]):
                    break
                am = AUTH_LINE_RE.match(lines[j])
                if am:
                    auth_raw = am.group(1).strip()
                    break
            endpoints[f"{method} {path}"] = {
                "method": method, "path": path,
                "auth_raw": auth_raw,
                "auth_classified": _classify_auth(auth_raw) if auth_raw else None,
            }
        i += 1
    return endpoints


def _classify_auth(auth_text: str) -> str:
    if re.search(r"\bpublic\b", auth_text, re.IGNORECASE):
        return "public"
    if re.search(r"\bowner[_ ]?only\b|\bown\b|\bself[_ ]?only\b",
                 auth_text, re.IGNORECASE):
        return "owner_only"
    if re.search(r"\brole\s*[:=]|\badmin\b|\bpublisher\b|\badvertiser\b|\bmoderator\b",
                 auth_text, re.IGNORECASE):
        return "role"
    if re.search(r"\bauthenticated\b|\brequired\b|\blogin\b",
                 auth_text, re.IGNORECASE):
        return "authenticated"
    return "unclear"


def _domain_from_path_or_title(path: str, title: str, domains: list[str]) -> str | None:
    """Check if endpoint path or goal title belongs to critical domain."""
    target = (path + " " + title).lower()
    for d in domains:
        if re.search(rf"\b{re.escape(d.lower())}\b", target):
            return d
    return None


def _extract_endpoint_from_goal(frontmatter: str) -> tuple[str, str] | None:
    """Find 'METHOD /path' in trigger or main_steps."""
    trigger = _yaml_field(frontmatter, "trigger") or ""
    main_steps = _yaml_field(frontmatter, "main_steps") or ""
    combined = trigger + "\n" + main_steps
    m = TRIGGER_ENDPOINT_RE.search(combined)
    if m:
        return (m.group(1).upper(), m.group(2).strip().rstrip("/"))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-goal-security")
    with timer(out):
        cfg = _read_config()
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        goals_text = goals_path.read_text(encoding="utf-8", errors="replace")
        goals = _parse_goal_blocks(goals_text)
        if not goals:
            emit_and_exit(out)

        # API contracts optional — if missing, skip cross-ref checks
        contracts_path = phase_dir / "API-CONTRACTS.md"
        endpoints = {}
        if contracts_path.exists():
            try:
                endpoints = _parse_api_contracts(
                    contracts_path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                pass

        missing_critical: list[dict] = []      # HARD BLOCK
        missing_mutation_csrf: list[dict] = [] # HARD BLOCK
        missing_mutation_rate: list[dict] = [] # HARD BLOCK
        auth_mismatch: list[dict] = []         # HARD BLOCK
        missing_readonly: list[dict] = []      # WARN

        for goal in goals:
            fm = goal["frontmatter"]
            gid = goal["id"]
            priority = (_yaml_field(fm, "priority") or "").strip()
            title = (_yaml_field(fm, "title") or "").strip("\"' \n")

            has_security_section = _yaml_field(fm, "security_checks") is not None
            owasp_populated = _yaml_nested_list_present(
                fm, "security_checks", "owasp_top10_2021",
            )
            csrf_value = _yaml_nested_field(fm, "security_checks", "csrf")
            rate_value = _yaml_nested_field(fm, "security_checks", "rate_limit")
            auth_model = _yaml_nested_field(fm, "security_checks", "auth_model")

            # Extract endpoint reference (if any)
            endpoint = _extract_endpoint_from_goal(fm)
            method = endpoint[0] if endpoint else None
            path = endpoint[1] if endpoint else None

            # Check if critical domain
            critical_domain = _domain_from_path_or_title(
                path or "", title, cfg["critical_goal_domains"],
            )

            # ─── BLOCK 1: critical_goal_domain missing OWASP section ───
            if critical_domain and not owasp_populated:
                missing_critical.append({
                    "goal": gid, "title": title[:60],
                    "domain": critical_domain,
                    "path": path or "N/A",
                })

            # ─── BLOCK 2+3: mutation endpoint missing csrf/rate_limit ───
            if method in MUTATION_METHODS:
                if cfg["cookie_auth"] and not (csrf_value and csrf_value.strip()):
                    missing_mutation_csrf.append({
                        "goal": gid, "method": method, "path": path,
                        "title": title[:60],
                    })
                if not (rate_value and rate_value.strip()):
                    missing_mutation_rate.append({
                        "goal": gid, "method": method, "path": path,
                        "title": title[:60],
                    })

            # ─── BLOCK 4: auth_model mismatch với API-CONTRACTS ───
            if endpoint and auth_model:
                key = f"{method} {path}"
                contract = endpoints.get(key)
                if contract and contract["auth_classified"]:
                    expected = contract["auth_classified"]
                    actual = auth_model.strip().strip("\"' ")
                    # Normalize: "role:admin" → "role", "owner_only" same
                    actual_norm = "role" if actual.startswith("role:") else actual
                    if expected != "unclear" and expected != actual_norm:
                        auth_mismatch.append({
                            "goal": gid,
                            "contract_auth": contract["auth_raw"],
                            "goal_auth_model": actual,
                            "endpoint": key,
                        })

            # ─── WARN: read-only GET without security section ───
            if method == "GET" and priority != "critical" and not has_security_section:
                missing_readonly.append({
                    "goal": gid, "title": title[:60], "path": path or "N/A",
                })

        # Emit evidence

        if missing_critical:
            sample = "; ".join(
                f"{g['goal']} ({g['domain']}: {g['path']}): {g['title']}"
                for g in missing_critical[:5]
            )
            out.add(Evidence(
                type="security_critical_domain_missing_owasp",
                message=t(
                    "goal_security.critical_missing.message",
                    count=len(missing_critical),
                ),
                actual=sample,
                fix_hint=t("goal_security.critical_missing.fix_hint"),
            ))

        if missing_mutation_csrf:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']})"
                for g in missing_mutation_csrf[:5]
            )
            out.add(Evidence(
                type="security_mutation_missing_csrf",
                message=t(
                    "goal_security.mutation_csrf.message",
                    count=len(missing_mutation_csrf),
                ),
                actual=sample,
                fix_hint=t("goal_security.mutation_csrf.fix_hint"),
            ))

        if missing_mutation_rate:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']})"
                for g in missing_mutation_rate[:5]
            )
            out.add(Evidence(
                type="security_mutation_missing_rate_limit",
                message=t(
                    "goal_security.mutation_rate.message",
                    count=len(missing_mutation_rate),
                ),
                actual=sample,
                fix_hint=t("goal_security.mutation_rate.fix_hint"),
            ))

        if auth_mismatch:
            sample = "; ".join(
                f"{g['goal']} ({g['endpoint']}): goal='{g['goal_auth_model']}' "
                f"vs contract='{g['contract_auth']}'"
                for g in auth_mismatch[:5]
            )
            out.add(Evidence(
                type="security_auth_model_mismatch",
                message=t(
                    "goal_security.auth_mismatch.message",
                    count=len(auth_mismatch),
                ),
                actual=sample,
                fix_hint=t("goal_security.auth_mismatch.fix_hint"),
            ))

        if missing_readonly:
            sample = "; ".join(
                f"{g['goal']} ({g['path']}): {g['title']}"
                for g in missing_readonly[:5]
            )
            out.warn(Evidence(
                type="security_readonly_missing_section",
                message=t(
                    "goal_security.readonly_missing.message",
                    count=len(missing_readonly),
                ),
                actual=sample,
                fix_hint=t("goal_security.readonly_missing.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
