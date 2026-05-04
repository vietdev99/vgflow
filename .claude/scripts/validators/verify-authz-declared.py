#!/usr/bin/env python3
"""
Validator: verify-authz-declared.py

B8.3 (OHOK D2 — static half): every endpoint in API-CONTRACTS.md MUST
declare its authorization requirement. Without explicit declaration,
AI executor may default to no-auth or inherit vague "Required" without
role/ownership specificity.

Runtime cross-role boundary test (publisher1 can't read publisher2's
data) is deferred to a later batch because it needs live API + multi-
user test fixtures. This validator closes the PROVENANCE gap: contract
must state authz intent so downstream gates have ground truth.

Check per endpoint (`## METHOD /path` header):
  - Must have `**Auth:**` line within next 10 lines
  - Classify: `public` | `authenticated` | `role:<name>` | `owner_only`
  - `authenticated` on mutation endpoints (POST/PUT/PATCH/DELETE) to a
    user-scoped resource → WARN advising `owner_only` explicit check

Usage:
  verify-authz-declared.py --phase <N>

Exit codes:
  0 PASS or WARN (declarations present; advisories for generic cases)
  1 BLOCK (one or more endpoints missing auth declaration entirely)
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

# Parse `## METHOD /path` header
HEADER_RE = re.compile(
    r"^##\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Parse `**Auth:** <value>` line
AUTH_LINE_RE = re.compile(
    r"^\*\*Auth\s*:\*\*\s*(.+)$", re.MULTILINE,
)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Classify auth line text
CLASS_PUBLIC = re.compile(r"\bpublic\b", re.IGNORECASE)
CLASS_AUTH = re.compile(r"\b(authenticated|required|login|signed[- ]?in)\b",
                        re.IGNORECASE)
CLASS_OWNER = re.compile(r"\b(owner[_ ]?only|own|owner[_ ]?check|self[_ ]?only)\b",
                         re.IGNORECASE)
CLASS_ROLE = re.compile(
    r"\b(role\s*[:=]\s*\w+|admin|superuser|staff|moderator|publisher|advertiser)\b",
    re.IGNORECASE,
)


def _classify_auth(auth_text: str) -> str:
    """Return public | authenticated | role | owner_only | unclear."""
    if CLASS_PUBLIC.search(auth_text):
        return "public"
    if CLASS_OWNER.search(auth_text):
        return "owner_only"
    if CLASS_ROLE.search(auth_text):
        return "role"
    if CLASS_AUTH.search(auth_text):
        return "authenticated"
    return "unclear"


def _scan_endpoints(contract_text: str) -> list[dict]:
    """Parse endpoints with their auth declarations. Returns list of
    {method, path, auth_text, classification, line_num}."""
    endpoints: list[dict] = []
    # Split into sections by `## METHOD /path` boundaries
    lines = contract_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEADER_RE.match(line)
        if m:
            method = m.group(1).upper()
            path = m.group(2).strip().rstrip("/")
            # Look up to 15 lines ahead for **Auth:** line (before next ## header)
            auth_text: str | None = None
            look_end = min(i + 16, len(lines))
            for j in range(i + 1, look_end):
                if HEADER_RE.match(lines[j]):
                    break  # next endpoint — stop scanning
                am = AUTH_LINE_RE.match(lines[j])
                if am:
                    auth_text = am.group(1).strip()
                    break
            endpoints.append({
                "method": method,
                "path": path,
                "auth_text": auth_text,
                "classification": _classify_auth(auth_text) if auth_text else None,
                "line_num": i + 1,
            })
        i += 1
    return endpoints


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-authz-declared")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        contracts_path = phase_dir / "API-CONTRACTS.md"
        if not contracts_path.exists():
            emit_and_exit(out)

        try:
            text = contracts_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            emit_and_exit(out)

        endpoints = _scan_endpoints(text)
        if not endpoints:
            # verify-contract-runtime handles the "0 endpoints" case
            emit_and_exit(out)

        missing_auth: list[dict] = []
        unclear_auth: list[dict] = []
        mutation_generic: list[dict] = []  # mutation + authenticated (not owner/role)
        ok: list[dict] = []

        for ep in endpoints:
            if ep["auth_text"] is None:
                missing_auth.append(ep)
                continue
            cls = ep["classification"]
            if cls == "unclear":
                unclear_auth.append(ep)
            elif (ep["method"] in MUTATION_METHODS
                  and cls == "authenticated"):
                mutation_generic.append(ep)
            else:
                ok.append(ep)

        if missing_auth:
            sample = missing_auth[:10]
            actual = "; ".join(
                f"{ep['method']} {ep['path']} (line {ep['line_num']})"
                for ep in sample
            )
            out.add(Evidence(
                type="missing_auth_declaration",
                message=t(
                    "authz_declared.missing_auth.message",
                    count=len(missing_auth), total=len(endpoints),
                ),
                actual=actual,
                fix_hint=t("authz_declared.missing_auth.fix_hint"),
            ))

        if unclear_auth:
            sample = unclear_auth[:5]
            actual = "; ".join(
                f"{ep['method']} {ep['path']}: '{ep['auth_text'][:60]}'"
                for ep in sample
            )
            # Unclear text blocks by default — author must clarify.
            out.add(Evidence(
                type="unclear_auth_declaration",
                message=t(
                    "authz_declared.unclear_auth.message",
                    count=len(unclear_auth),
                ),
                actual=actual,
                fix_hint=t("authz_declared.unclear_auth.fix_hint"),
            ))

        if mutation_generic:
            sample = mutation_generic[:5]
            actual = "; ".join(
                f"{ep['method']} {ep['path']}: '{ep['auth_text'][:60]}'"
                for ep in sample
            )
            # Mutation + generic authenticated = advisory, not block.
            # WARN so authors see it + audit logs capture, but runs
            # continue because "authenticated only" may be intentional
            # on tenant-less endpoints (settings, account, etc.).
            out.warn(Evidence(
                type="mutation_generic_auth",
                message=t(
                    "authz_declared.mutation_generic.message",
                    count=len(mutation_generic),
                ),
                actual=actual,
                fix_hint=t("authz_declared.mutation_generic.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
