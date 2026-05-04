#!/usr/bin/env python3
"""
Validator: not-scanned-replay.py

B11.1 (v2.4 hardening, 2026-04-23): cross-step telemetry feedback.

Review pipeline has a hard rule "NOT_SCANNED không được defer sang
/vg:test" — if review exits with goals still in NOT_SCANNED state,
something went wrong (user override, review crash, --retry-failed
didn't cover it). Test pipeline shouldn't silently inherit that gap.

This validator reads `GOAL-COVERAGE-MATRIX.md` at test entry and:
  - Counts NOT_SCANNED / FAILED rows
  - Extracts start_view + reason from each row (for actionable error)
  - If any remain → BLOCK with exact fix command per goal

Why NOT auto-replay Haiku here: replay requires MCP Playwright server
active + browser state + sidebar discovery already done. That's review
phase territory. Cleaner to surface + block than fake auto-fix.

Usage:
  not-scanned-replay.py --phase <N>

Exit codes:
  0 PASS (no NOT_SCANNED/FAILED goals; review properly closed)
  1 BLOCK (unresolved intermediate goals — user must /vg:review --retry-failed)
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

# Matrix row format:
# | G-01 | description | critical | READY | start_view | sequence ref |
# Status column is 4th pipe-separated cell.
ROW_RE = re.compile(
    r"^\|\s*(G-\d+)\s*\|([^|]+)\|([^|]+)\|\s*(NOT_SCANNED|FAILED)\s*\|([^|]*)\|",
    re.MULTILINE,
)


def _parse_matrix(text: str) -> list[dict]:
    """Return list of {goal, desc, priority, status, start_view}."""
    rows: list[dict] = []
    for m in ROW_RE.finditer(text):
        goal, desc, priority, status, start_view = m.groups()
        rows.append({
            "goal": goal.strip(),
            "desc": desc.strip()[:80],
            "priority": priority.strip(),
            "status": status.strip(),
            "start_view": start_view.strip() or "<unknown>",
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="not-scanned-replay")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
        if not matrix.exists():
            # No matrix yet — review hasn't run, test shouldn't proceed.
            # Let goal-coverage validator handle that case (different gate).
            emit_and_exit(out)

        try:
            text = matrix.read_text(encoding="utf-8", errors="replace")
        except OSError:
            emit_and_exit(out)

        bad_rows = _parse_matrix(text)
        if not bad_rows:
            emit_and_exit(out)  # PASS — all goals resolved properly

        # Count by status + priority for nuanced message
        by_status: dict[str, list[dict]] = {"NOT_SCANNED": [], "FAILED": []}
        for r in bad_rows:
            by_status.setdefault(r["status"], []).append(r)

        sample = "; ".join(
            f"{r['goal']} ({r['priority']}, start_view={r['start_view']}): "
            f"{r['desc'][:40]}"
            for r in bad_rows[:10]
        )

        out.add(Evidence(
            type="intermediate_goals_remain",
            message=t(
                "not_scanned_replay.remain.message",
                not_scanned=len(by_status["NOT_SCANNED"]),
                failed=len(by_status["FAILED"]),
            ),
            actual=sample,
            fix_hint=t("not_scanned_replay.remain.fix_hint"),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
