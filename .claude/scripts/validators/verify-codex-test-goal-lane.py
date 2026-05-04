#!/usr/bin/env python3
"""Verify Codex co-author proposal/delta artifacts for TEST-GOALS."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--phase-dir", help="Override phase directory")
    parser.add_argument("--allow-skip", action="store_true")
    args = parser.parse_args()

    out = Output(validator="codex-test-goal-lane")
    with timer(out):
        phase_dir = Path(args.phase_dir) if args.phase_dir else find_phase_dir(args.phase)
        if not phase_dir:
            out.warn(Evidence(type="info", message=f"Phase dir not found for {args.phase}; skipping"))
            emit_and_exit(out)

        skip_marker = phase_dir / ".step-markers" / "2b5a_codex_test_goal_lane.skipped"
        if skip_marker.exists() or args.allow_skip:
            out.warn(Evidence(
                type="codex_lane_skipped",
                message="Codex test-goal co-author lane was explicitly skipped",
                file=str(skip_marker) if skip_marker.exists() else None,
                fix_hint="Use only for tiny phases or when Codex CLI is unavailable; log override debt.",
            ))
            emit_and_exit(out)

        proposal = phase_dir / "TEST-GOALS.codex-proposal.md"
        delta = phase_dir / "TEST-GOALS.codex-delta.md"
        if not proposal.exists() or proposal.stat().st_size < 40:
            out.add(Evidence(
                type="proposal_missing",
                message="TEST-GOALS.codex-proposal.md missing or too small",
                file=str(proposal),
                fix_hint="Run blueprint step 2b5a with codex-spawn planner lane.",
            ))
        if not delta.exists() or delta.stat().st_size < 80:
            out.add(Evidence(
                type="delta_missing",
                message="TEST-GOALS.codex-delta.md missing or too small",
                file=str(delta),
                fix_hint="Run scripts/test-goal-delta.py after Codex proposal.",
            ))
            emit_and_exit(out)

        text = delta.read_text(encoding="utf-8", errors="replace")
        if "Status: PASS" not in text:
            out.add(Evidence(
                type="delta_unresolved",
                message="Codex proposal delta is not reconciled into final TEST-GOALS.md",
                file=str(delta),
                fix_hint=(
                    "Update TEST-GOALS.md with the missing coverage or rerun "
                    "with --skip-codex-test-goal-lane and override debt."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
