#!/usr/bin/env python3
"""Verify scanner output meets RCRURD step-depth threshold per goal class.

Closes Phase 3.2 dogfood gap: scanners stop after 4-5 steps even on
mutation/crud-roundtrip goals that need 6-14 steps. AI rationalizes
"modal opened" as completion, marks goal passed, moves on.

This validator counts goal_sequences[gid].steps[] length and compares
against goal_class threshold (per scanner-report-contract Section 2.X).

Goal class thresholds:
  readonly: ≥3 (navigate → snapshot → assert)
  mutation: ≥6 (pre-snapshot → submit → wait → refresh → re-read → diff)
  approval: ≥8 (read pending → drawer → approve → confirm → submit → wait → refresh → assert)
  wizard: ≥10 (multi-step form transitions)
  crud-roundtrip: ≥14 (Read empty → C(4) → Read populated → U(4) → Read updated → D(3) → Read empty)
  webhook: ≥4 (trigger → wait → query downstream → assert)

Severity: BLOCK at /vg:review Phase 4.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import (  # noqa: E402
    parse_goals_with_frontmatter,
    infer_goal_class,
    min_steps_for_goal,
    GOAL_CLASS_MIN_STEPS,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify RCRURD step depth per goal class")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--allow-shallow-scans",
        action="store_true",
        help="Override: allow goals with insufficient steps. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="rcrurd-depth")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not goals_path.exists() or not runtime_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError as e:
            out.add(Evidence(type="runtime_map_invalid", message=f"Parse failed: {e}"))
            emit_and_exit(out)

        sequences = runtime.get("goal_sequences") or {}
        if not isinstance(sequences, dict):
            emit_and_exit(out)

        violations = 0
        for goal in goals:
            gid = goal["id"]
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                continue  # Caller (matrix-evidence-link) handles missing sequences

            result = str(seq.get("result", "")).lower()
            if result not in {"passed", "pass", "ready", "yes"}:
                continue  # Goal already not passing — nothing to falsify

            cls = infer_goal_class(goal)
            min_steps = GOAL_CLASS_MIN_STEPS.get(cls, 3)
            actual_steps = len(seq.get("steps") or [])

            if actual_steps < min_steps:
                violations += 1
                out.add(
                    Evidence(
                        type="rcrurd_steps_insufficient",
                        message=(
                            f"{gid}: marked passed but goal_sequences.steps has only "
                            f"{actual_steps} entries. goal_class='{cls}' requires ≥{min_steps}."
                        ),
                        file=str(runtime_path),
                        expected=f"≥{min_steps} steps for goal_class={cls}",
                        actual=f"{actual_steps} steps",
                        fix_hint=(
                            f"Re-run /vg:review with scanner directed to complete RCRURD "
                            f"lifecycle. Sandbox = disposable_seed_data; mutate freely. "
                            f"See scanner-report-contract.md 'RCRURD Lifecycle Protocol'."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_shallow_scans),
                )

        if violations and (args.severity == "warn" or args.allow_shallow_scans):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} shallow scan(s) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
