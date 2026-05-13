#!/usr/bin/env python3
"""verify-task-complexity.py — Rule 2 (simplicity gate) Batch 13

Reads PLAN.md per-task complexity_budget field (e.g. max_loc_delta=200).
Reads .task-diff-stats.json (written by build close pre-validator).
Surfaces OVERRUN when actual delta exceeds budget.

Advisory by default (exit 0). --strict promotes to non-zero exit.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


BUDGET_RE = re.compile(
    r"\*\*complexity_budget:\*\*\s*([^\n]+)",
    re.IGNORECASE,
)


def _parse_budget(text: str, task_id: str) -> dict[str, int]:
    """Find task block in PLAN.md, extract complexity_budget key=value pairs."""
    # Find task section
    task_re = re.compile(rf"##\s+Task\s+{re.escape(task_id)}\b(.+?)(?=##\s+Task\s+|\Z)", re.S | re.I)
    m = task_re.search(text)
    if not m:
        return {}
    block = m.group(1)
    bm = BUDGET_RE.search(block)
    if not bm:
        return {}
    pairs = bm.group(1)
    out: dict[str, int] = {}
    for kv in re.finditer(r"(\w+)\s*=\s*(\d+)", pairs):
        out[kv.group(1)] = int(kv.group(2))
    return out


def _read_actual(stats_path: Path, task_id: str) -> dict[str, int]:
    if not stats_path.is_file():
        return {}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data.get(task_id, {}) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Escalate overrun to non-zero exit (default: advisory)")
    args = ap.parse_args()

    plan_path = args.phase_dir / "PLAN.md"
    if not plan_path.is_file():
        print(f"WARNING Rule 2: PLAN.md missing at {plan_path} -- skip complexity gate")
        return 0

    budget = _parse_budget(plan_path.read_text(encoding="utf-8"), args.task_id)
    if not budget:
        print(f"INFO Rule 2: no complexity_budget for {args.task_id} -- skip")
        return 0

    actual = _read_actual(args.phase_dir / ".task-diff-stats.json", args.task_id)
    if not actual:
        print(f"WARNING Rule 2: no diff stats for {args.task_id} -- skip")
        return 0

    overruns: list[str] = []
    for key, max_val in budget.items():
        # max_X budget vs X actual (normalize key name)
        actual_key = key.replace("max_", "")
        actual_val = actual.get(actual_key, 0)
        if actual_val > max_val:
            overruns.append(
                f"  {actual_key}: {actual_val} > budget {max_val} (OVERRUN by {actual_val - max_val})"
            )

    if overruns:
        print(f"WARNING Rule 2: task {args.task_id} complexity OVERRUN:")
        for o in overruns:
            print(o)
        print("   Re-evaluate: is this task over-complicated? Senior engineer test failed.")
        return 1 if args.strict else 0

    print(f"OK Rule 2: task {args.task_id} within complexity budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
