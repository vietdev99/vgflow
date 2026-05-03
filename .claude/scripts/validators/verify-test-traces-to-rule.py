#!/usr/bin/env python3
"""Verify generated .spec.ts files cite goal_id + business_rule + assertion.

Closes Phase 3.2 dogfood gap: test codegen produces tests that pass green
without verifying the actual business rule. Test header should cite parent
goal + rule. Test body should reference rule constant.

Required test header format:
  // Goal: G-XX | Rule: BR-NN | Assertion: <verbatim quote>

Severity: BLOCK at /vg:test post-codegen.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import (  # noqa: E402
    parse_goals_with_frontmatter,
    text_similarity,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def find_spec_files(phase_dir: Path) -> list[Path]:
    """Locate .spec.ts files for this phase.

    Convention: tests live under apps/*/e2e/<phase>/*.spec.ts or
    apps/web/e2e/generated/<phase>/*.spec.ts.
    """
    repo_root = Path.cwd()
    candidates: list[Path] = []
    patterns = [
        f"apps/**/e2e/{phase_dir.name}/*.spec.ts",
        f"apps/**/e2e/generated/{phase_dir.name}/*.spec.ts",
        f"apps/**/e2e/**/{phase_dir.name.split('-')[0]}*.spec.ts",
    ]
    for pat in patterns:
        candidates.extend(repo_root.glob(pat))
    # Dedupe
    return list(dict.fromkeys(candidates))


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify .spec.ts traces goal+rule")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--allow-test-untraced", action="store_true")
    args = parser.parse_args()

    out = Output(validator="test-traces-to-rule")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        spec_files = find_spec_files(phase_dir)
        if not spec_files:
            # No tests yet — /vg:test hasn't run. Not a violation here.
            emit_and_exit(out)

        # Build goal_id → expected text map
        goal_map = {g["id"]: g for g in goals}
        violations = 0

        for spec in spec_files:
            text = _read(spec)
            # Find which goal(s) this test claims to cover
            cited_goals = set(re.findall(r"\bG-\d+\b", text[:2000]))  # header zone
            if not cited_goals:
                violations += 1
                out.add(
                    Evidence(
                        type="spec_no_goal_cited",
                        message=f"{spec.name}: no Goal G-XX citation in first 2KB (header)",
                        file=str(spec),
                        fix_hint="Add `// Goal: G-XX | Rule: BR-NN | Assertion: <quote>` header",
                    ),
                    escalate=(args.severity == "block" and not args.allow_test_untraced),
                )
                continue

            for gid in cited_goals:
                goal = goal_map.get(gid)
                if not goal:
                    continue
                # Check business_rules cited
                if goal.get("business_rules"):
                    cited_rules = re.findall(r"\bBR-[\w]+\b", text[:2000])
                    expected_rules = set(goal["business_rules"])
                    if not (set(cited_rules) & expected_rules):
                        violations += 1
                        out.add(
                            Evidence(
                                type="spec_no_rule_cited",
                                message=(
                                    f"{spec.name} cites {gid} but doesn't cite expected "
                                    f"business_rules {expected_rules}"
                                ),
                                file=str(spec),
                                fix_hint=f"Add `// Rule: {next(iter(expected_rules))}` to header",
                            ),
                            escalate=(args.severity == "block" and not args.allow_test_untraced),
                        )

                # Check expected_assertion text similarity to spec content
                if goal.get("expected_assertion"):
                    sim = text_similarity(goal["expected_assertion"], text[:5000])
                    if sim < 0.3:
                        violations += 1
                        out.add(
                            Evidence(
                                type="spec_assertion_drift",
                                message=(
                                    f"{spec.name} cites {gid} but content similarity "
                                    f"{sim:.2f} vs expected_assertion is low"
                                ),
                                file=str(spec),
                                expected=goal["expected_assertion"][:120],
                                fix_hint="Test body should verify expected_assertion semantics",
                            ),
                            escalate=False,  # Soft warning — body similarity is weak signal
                        )

        if violations and (args.severity == "warn" or args.allow_test_untraced):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} test trace gap(s) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
