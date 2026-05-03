#!/usr/bin/env python3
"""Verify every CONTEXT.md D-XX maps to ≥1 task in PLAN.md.

Closes Phase 3.2 dogfood gap: AI may write CONTEXT decisions but skip
implementing them in PLAN. Validator cross-checks coverage.

Convention: tasks in PLAN.md should cite decisions via:
  - "Per CONTEXT.md D-46" in task description
  - "**Decisions:**: [D-46]" frontmatter
  - "(D-46)" inline reference

Severity: BLOCK at /vg:blueprint plan-checker.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify D-XX → tasks coverage")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--allow-uncovered-decisions",
        action="store_true",
        help="Override: allow D-XX without task. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="decisions-to-tasks")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        context_path = phase_dir / "CONTEXT.md"
        if not context_path.exists():
            emit_and_exit(out)

        context_text = _read(context_path)
        decision_ids = re.findall(r"^#{2,4}\s*(D-\d+)", context_text, re.MULTILINE)
        decision_ids = sorted(set(decision_ids))

        if not decision_ids:
            emit_and_exit(out)

        # Aggregate text from PLAN.md + PLAN-*.md (multi-file plans)
        plan_files = list(phase_dir.glob("PLAN*.md"))
        plan_text = "\n".join(_read(p) for p in plan_files)
        if not plan_text:
            out.add(
                Evidence(
                    type="no_plan_files",
                    message="CONTEXT.md has decisions but no PLAN*.md files found",
                    file=str(phase_dir),
                ),
                escalate=(args.severity == "block"),
            )
            emit_and_exit(out)

        violations = 0
        for did in decision_ids:
            # Look for D-XX reference in plan text
            pattern = re.compile(rf"\b{re.escape(did)}\b")
            if not pattern.search(plan_text):
                violations += 1
                out.add(
                    Evidence(
                        type="decision_uncovered_by_task",
                        message=f"{did}: not referenced in any PLAN*.md task",
                        file=str(context_path),
                        fix_hint=(
                            f"Add task implementing {did} OR cite '{did}' in existing task body. "
                            f"Format: 'Per CONTEXT.md {did}' OR 'Decisions: [{did}]'."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_uncovered_decisions),
                )

        if violations and (args.severity == "warn" or args.allow_uncovered_decisions):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} decision(s) without task coverage, WARN mode.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
