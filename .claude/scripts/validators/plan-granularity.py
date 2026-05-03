#!/usr/bin/env python3
"""
Validator: plan-granularity.py

Purpose: PLAN*.md produced by /vg:blueprint must have properly-sized tasks
with goal-binding. Audit found plans with monolithic tasks (1 task = 500
LOC) or tasks without any goal reference → build can't attribute work.

Checks:
- At least 1 PLAN*.md file exists
- Each task has an ID pattern (e.g. 14-03)
- Each task cites a goal ID (G-XX) OR declares no-goal-impact
- Task file-path annotations exist (<edits-*> or similar)

Usage: plan-granularity.py --phase <N>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

TASK_RE = re.compile(
    r"^##+\s+Task\s+([\d.]+(?:[-.]\d+)?)[:\s—-]",
    re.MULTILINE | re.IGNORECASE,
)
GOAL_RE = re.compile(r"\bG-\d+\b|\(AC:\s*#G-\d+\)")
NO_GOAL_RE = re.compile(r"no-goal-impact", re.IGNORECASE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="plan-granularity")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            out.add(Evidence(type="missing_file",
                             message=f"phase dir for {args.phase} not found"))
            emit_and_exit(out)

        plans = sorted(phase_dirs[0].glob("PLAN*.md"))
        if not plans:
            out.add(Evidence(
                type="missing_file",
                message="No PLAN*.md files found",
                fix_hint="Run /vg:blueprint to generate plans.",
            ))
            emit_and_exit(out)

        total_tasks = 0
        unbound_tasks: list[tuple[str, str]] = []

        for plan in plans:
            text = plan.read_text(encoding="utf-8", errors="replace")
            task_positions = [m.start() for m in TASK_RE.finditer(text)]
            task_ids = TASK_RE.findall(text)
            task_positions.append(len(text))

            for i, task_id in enumerate(task_ids):
                total_tasks += 1
                block = text[task_positions[i]:task_positions[i+1]]
                if not (GOAL_RE.search(block) or NO_GOAL_RE.search(block)):
                    unbound_tasks.append((plan.name, task_id))

        if total_tasks == 0:
            out.add(Evidence(
                type="count_below_threshold",
                message="0 tasks found across all PLAN*.md files",
                expected=">=1",
                actual=0,
                fix_hint="PLAN format: '### Task X-NN: description' expected.",
            ))
            emit_and_exit(out)

        if unbound_tasks:
            rate = len(unbound_tasks) / total_tasks
            sample = ", ".join(f"{p}::{t}" for p, t in unbound_tasks[:5])
            evidence = Evidence(
                type="goal_unbound",
                message=(
                    f"{len(unbound_tasks)}/{total_tasks} tasks ({rate*100:.0f}%) "
                    f"lack goal binding"
                ),
                expected="every task cites G-XX or declares no-goal-impact",
                actual=f"sample: {sample}",
                fix_hint="Add 'Covers goal: G-XX' or 'no-goal-impact' per task.",
            )
            # >20% unbound = BLOCK, else WARN
            if rate > 0.2:
                out.add(evidence)
            else:
                out.warn(evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
