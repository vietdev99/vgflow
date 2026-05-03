#!/usr/bin/env python3
"""Verify every CONTEXT.md D-XX maps to ≥1 goal in TEST-GOALS.md.

Closes Phase 3.2 dogfood gap: decisions exist in CONTEXT but no goal verifies
them → code may implement decision but no automated verification.

Severity: BLOCK at /vg:blueprint plan-checker.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import parse_goals_with_frontmatter  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify D-XX → goals coverage")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--allow-uncovered-decisions",
        action="store_true",
    )
    args = parser.parse_args()

    out = Output(validator="decisions-to-goals")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        context_path = phase_dir / "CONTEXT.md"
        goals_path = phase_dir / "TEST-GOALS.md"
        if not context_path.exists() or not goals_path.exists():
            emit_and_exit(out)

        context_text = _read(context_path)
        decision_ids = sorted(set(re.findall(r"^#{2,4}\s*(D-\d+)", context_text, re.MULTILINE)))
        if not decision_ids:
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))

        # Build coverage map: decision → list of goals citing it
        coverage: dict[str, list[str]] = {did: [] for did in decision_ids}
        for goal in goals:
            cited = set()
            # Frontmatter decisions field
            for d in goal["decisions"]:
                local = d.split(".")[-1]  # "P3.D-46" → "D-46"
                if local in coverage:
                    cited.add(local)
            # Title parenthetical (e.g. "G-12: Foo (P3.D-46)")
            for m in re.finditer(r"\bD-\d+\b", goal["title"]):
                if m.group(0) in coverage:
                    cited.add(m.group(0))
            for d in cited:
                coverage[d].append(goal["id"])

        violations = 0
        for did, gids in coverage.items():
            if not gids:
                violations += 1
                out.add(
                    Evidence(
                        type="decision_uncovered_by_goal",
                        message=f"{did}: not cited by any goal in TEST-GOALS.md",
                        file=str(context_path),
                        fix_hint=(
                            f"Add a goal verifying {did} OR add 'decisions: [{did}]' to "
                            f"existing goal that implicitly covers it."
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
                    message=f"{violations} decision(s) without goal coverage, WARN mode.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
