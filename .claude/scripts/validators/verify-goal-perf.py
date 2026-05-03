#!/usr/bin/env python3
"""
Validator: verify-goal-perf.py

Phase B.2 v2.5 (2026-04-23): goal-level performance budget declaration check.

Reads TEST-GOALS.md frontmatter per goal, validates `perf_budget` section
covers required fields based on endpoint type (mutation/list/single) and
goal surface (ui/api/data).

Severity matrix (enforced):
- Mutation endpoint (POST/PUT/PATCH/DELETE) + perf_budget empty
  → HARD BLOCK (perf_mutation_missing_budget)
- GET list endpoint (plural path, no /{id}) + p95_ms empty
  → HARD BLOCK (perf_list_missing_p95)
- Single-record GET (/{id}) + perf_budget empty
  → WARN (perf_single_missing_budget)
- surface=ui + bundle_kb_fe_route empty
  → WARN (perf_ui_missing_bundle)
- Mutation OR list endpoint + n_plus_one_max empty
  → WARN (perf_nplus1_missing)

Usage:
  verify-goal-perf.py --phase <N>

Exit codes:
  0 PASS or WARN (advisory only)
  1 BLOCK (perf declaration missing for mutation or list endpoint)
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

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL | re.MULTILINE)

# Goal trigger embeds endpoint: "POST /api/v1/..." etc.
TRIGGER_ENDPOINT_RE = re.compile(
    r"""\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s"'`]+)""",
    re.IGNORECASE,
)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Single-record path indicators: ends with /{id}, /:id, or similar.
SINGLE_RECORD_RE = re.compile(r"/(\{[^}]+\}|:[a-zA-Z_][a-zA-Z0-9_]*)$")

# List path: ends with a plural noun segment (e.g. /sites, /ad-units, /campaigns)
# or the literal /list suffix. Excludes single-record paths (handled separately).
LIST_PATH_RE = re.compile(r"/([a-zA-Z][a-zA-Z0-9-]*s|list)$", re.IGNORECASE)


def _parse_goal_blocks(text: str) -> list[dict]:
    """Split TEST-GOALS.md into per-goal frontmatter sections.

    Returns list of {id, frontmatter, start_offset}.
    """
    goals: list[dict] = []
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
    """Extract nested key (e.g. perf_budget.p95_ms)."""
    parent_block = _yaml_field(block, parent)
    if not parent_block:
        return None
    m = re.search(
        rf"^\s*{re.escape(child)}:\s*(.+?)(?=\n\s*[a-zA-Z_]+:|\Z)",
        parent_block, re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _extract_endpoint_from_goal(frontmatter: str) -> tuple[str, str] | None:
    """Find 'METHOD /path' in trigger or main_steps."""
    trigger = _yaml_field(frontmatter, "trigger") or ""
    main_steps = _yaml_field(frontmatter, "main_steps") or ""
    combined = trigger + "\n" + main_steps
    m = TRIGGER_ENDPOINT_RE.search(combined)
    if m:
        return (m.group(1).upper(), m.group(2).strip().rstrip("/"))
    return None


def _is_single_record(path: str) -> bool:
    """Path ends with /{id} or /:id pattern → single record GET."""
    return bool(SINGLE_RECORD_RE.search(path))


def _is_list_endpoint(path: str) -> bool:
    """Path ends with plural noun or /list — but NOT a single-record path."""
    if _is_single_record(path):
        return False
    return bool(LIST_PATH_RE.search(path))


_PERF_FIELDS = (
    "p50_ms", "p95_ms", "p99_ms",
    "n_plus_one_max", "bundle_kb_fe_route", "cache_strategy",
)


def _perf_budget_empty(fm: str) -> bool:
    """True if perf_budget section is absent OR all meaningful fields empty."""
    section = _yaml_field(fm, "perf_budget")
    if not section or not section.strip():
        return True
    for field in _PERF_FIELDS:
        val = _yaml_nested_field(fm, "perf_budget", field)
        if val and val.strip():
            return False
    return True


def _perf_field_empty(fm: str, field: str) -> bool:
    """True if perf_budget.<field> is absent/empty."""
    val = _yaml_nested_field(fm, "perf_budget", field)
    return not (val and val.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-goal-perf")
    with timer(out):
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

        mutation_missing: list[dict] = []   # HARD BLOCK
        list_missing_p95: list[dict] = []   # HARD BLOCK
        single_missing: list[dict] = []     # WARN
        ui_missing_bundle: list[dict] = []  # WARN
        nplus1_missing: list[dict] = []     # WARN

        for goal in goals:
            fm = goal["frontmatter"]
            gid = goal["id"]
            title = (_yaml_field(fm, "title") or "").strip("\"' \n")
            surface = (_yaml_field(fm, "surface") or "").strip("\"' \n").lower()

            endpoint = _extract_endpoint_from_goal(fm)
            method = endpoint[0] if endpoint else None
            path = endpoint[1] if endpoint else None

            is_mutation = method in MUTATION_METHODS if method else False
            is_list = bool(path) and method == "GET" and _is_list_endpoint(path)
            is_single = bool(path) and method == "GET" and _is_single_record(path)

            budget_empty = _perf_budget_empty(fm)
            p95_empty = _perf_field_empty(fm, "p95_ms")
            bundle_empty = _perf_field_empty(fm, "bundle_kb_fe_route")
            nplus1_empty = _perf_field_empty(fm, "n_plus_one_max")

            # ─── BLOCK 1: Mutation + perf_budget empty ───
            if is_mutation and budget_empty:
                mutation_missing.append({
                    "goal": gid, "method": method, "path": path,
                    "title": title[:60],
                })

            # ─── BLOCK 2: GET list endpoint + p95_ms empty ───
            if is_list and p95_empty:
                list_missing_p95.append({
                    "goal": gid, "method": method, "path": path,
                    "title": title[:60],
                })

            # ─── WARN 3: Single-record GET + perf_budget empty ───
            if is_single and budget_empty:
                single_missing.append({
                    "goal": gid, "method": method, "path": path,
                    "title": title[:60],
                })

            # ─── WARN 4: surface=ui + bundle_kb_fe_route empty ───
            if surface == "ui" and bundle_empty:
                ui_missing_bundle.append({
                    "goal": gid, "title": title[:60],
                    "surface": surface,
                })

            # ─── WARN 5: mutation or list + n_plus_one_max empty ───
            # Skip if mutation already flagged BLOCK for empty budget (redundant).
            if nplus1_empty and (is_mutation or is_list) and not budget_empty:
                nplus1_missing.append({
                    "goal": gid, "method": method, "path": path,
                    "title": title[:60],
                })
            elif nplus1_empty and is_list and budget_empty:
                # list-empty already BLOCKed via p95 rule; still flag n+1 explicitly
                # so fix-hint covers both. Non-redundant with BLOCK 2.
                nplus1_missing.append({
                    "goal": gid, "method": method, "path": path,
                    "title": title[:60],
                })

        # Emit evidence

        if mutation_missing:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']}): {g['title']}"
                for g in mutation_missing[:5]
            )
            out.add(Evidence(
                type="perf_mutation_missing_budget",
                message=t(
                    "goal_perf.mutation_missing.message",
                    count=len(mutation_missing),
                ),
                actual=sample,
                fix_hint=t("goal_perf.mutation_missing.fix_hint"),
            ))

        if list_missing_p95:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']}): {g['title']}"
                for g in list_missing_p95[:5]
            )
            out.add(Evidence(
                type="perf_list_missing_p95",
                message=t(
                    "goal_perf.list_missing_p95.message",
                    count=len(list_missing_p95),
                ),
                actual=sample,
                fix_hint=t("goal_perf.list_missing_p95.fix_hint"),
            ))

        if single_missing:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']}): {g['title']}"
                for g in single_missing[:5]
            )
            out.warn(Evidence(
                type="perf_single_missing_budget",
                message=t(
                    "goal_perf.single_missing.message",
                    count=len(single_missing),
                ),
                actual=sample,
                fix_hint=t("goal_perf.single_missing.fix_hint"),
            ))

        if ui_missing_bundle:
            sample = "; ".join(
                f"{g['goal']}: {g['title']}"
                for g in ui_missing_bundle[:5]
            )
            out.warn(Evidence(
                type="perf_ui_missing_bundle",
                message=t(
                    "goal_perf.ui_missing_bundle.message",
                    count=len(ui_missing_bundle),
                ),
                actual=sample,
                fix_hint=t("goal_perf.ui_missing_bundle.fix_hint"),
            ))

        if nplus1_missing:
            sample = "; ".join(
                f"{g['goal']} ({g['method']} {g['path']})"
                for g in nplus1_missing[:5]
            )
            out.warn(Evidence(
                type="perf_nplus1_missing",
                message=t(
                    "goal_perf.nplus1_missing.message",
                    count=len(nplus1_missing),
                ),
                actual=sample,
                fix_hint=t("goal_perf.nplus1_missing.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
