#!/usr/bin/env python3
"""
Validator: task-goal-binding.py

Purpose: Enforce BMAD-style (AC: #G-XX) notation — every task in PLAN.md
must reference at least one goal OR explicitly declare no-goal-impact.
Without this, code can ship with no link to requirements.

Usage: task-goal-binding.py --phase <N>
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
    r"^##+\s+Task\s+([\d.]+(?:[-.]\d+)?)", re.MULTILINE | re.IGNORECASE,
)
GOAL_RE = re.compile(r"\(AC:\s*#?G-\d+\)|\bCovers\s+goal:\s*G-\d+|\bG-\d+\b")
NO_IMPACT_RE = re.compile(r"no-goal-impact|no\s+goal\s+impact", re.IGNORECASE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="task-goal-binding")
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
                message="No PLAN*.md files",
                fix_hint="Run /vg:blueprint first.",
            ))
            emit_and_exit(out)

        unbound = []
        total = 0
        for plan in plans:
            text = plan.read_text(encoding="utf-8", errors="replace")
            task_starts = [m.start() for m in TASK_RE.finditer(text)]
            task_ids = TASK_RE.findall(text)
            task_starts.append(len(text))

            for i, tid in enumerate(task_ids):
                total += 1
                block = text[task_starts[i]:task_starts[i+1]]
                if GOAL_RE.search(block):
                    continue
                if NO_IMPACT_RE.search(block):
                    continue
                unbound.append(f"{plan.name}::{tid}")

        if total == 0:
            out.warn(Evidence(
                type="count_below_threshold",
                message="0 tasks found across PLANs",
            ))
            emit_and_exit(out)

        if unbound:
            rate = len(unbound) / total
            evidence = Evidence(
                type="goal_unbound",
                message=f"{len(unbound)}/{total} tasks lack goal binding ({rate*100:.0f}%)",
                actual=", ".join(unbound[:10]),
                fix_hint=(
                    "Add one of: '(AC: #G-XX)' in title, 'Covers goal: G-XX' "
                    "in body, or explicit 'no-goal-impact' declaration."
                ),
            )
            # Zero tolerance — any unbound task blocks
            out.add(evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
