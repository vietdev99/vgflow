#!/usr/bin/env python3
"""Verify TEST-GOALS.md frontmatter completeness (blueprint gate).

Each goal MUST cite spec_ref + decisions + business_rules + expected_assertion
+ goal_class to be considered traceable. Closes the "AI bịa goal" gap from
Phase 3.2 dogfood: AI invents goals not tied to SPECS/CONTEXT/DISCUSSION-LOG.

Migration: --severity warn flag downgrades BLOCK to WARN for pre-2026-05-01
phases. After backfill, re-run with default block severity.

Per scanner-report-contract Section 1: this validator runs at /vg:blueprint
plan-checker step. Blocks blueprint exit if any goal lacks traceability.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import (  # noqa: E402
    parse_goals_with_frontmatter,
    find_section_anchor,
    infer_goal_class,
    GOAL_CLASS_MIN_STEPS,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify TEST-GOALS frontmatter has full traceability fields"
    )
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--severity",
        choices=["block", "warn"],
        default="block",
        help="block (default) BLOCKs blueprint; warn for migration phases",
    )
    parser.add_argument(
        "--allow-traceability-gaps",
        action="store_true",
        help="Override: allow missing fields. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="goal-traceability")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(
                type="phase_not_found",
                message=f"Phase directory not found for {args.phase}",
            ))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        if not goals_path.exists():
            # No goals = no traceability to verify
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        violations = 0

        for goal in goals:
            gid = goal["id"]
            issues: list[str] = []

            # Required: spec_ref
            if not goal["spec_ref"]:
                issues.append("missing spec_ref (which SPECS.md section drives this goal?)")

            # Required: expected_assertion (verbatim business rule statement)
            if not goal["expected_assertion"] or len(goal["expected_assertion"].strip()) < 20:
                issues.append(
                    "missing or too-short expected_assertion (need verbatim business "
                    "rule statement that scanner/test must verify, ≥20 chars)"
                )

            # Required: goal_class (drives min_steps threshold)
            if not goal["goal_class"]:
                inferred = infer_goal_class(goal)
                issues.append(
                    f"missing goal_class field (inferred '{inferred}' from title/surface, "
                    f"but explicit declaration required for downstream validators)"
                )
            elif goal["goal_class"] not in GOAL_CLASS_MIN_STEPS:
                issues.append(
                    f"invalid goal_class='{goal['goal_class']}' "
                    f"(must be one of: {', '.join(sorted(GOAL_CLASS_MIN_STEPS))})"
                )

            # Conditional: business_rules required for non-trivial mutations
            cls = infer_goal_class(goal)
            if cls in {"mutation", "approval", "crud-roundtrip", "wizard", "webhook"}:
                if not goal["business_rules"]:
                    issues.append(
                        f"goal_class={cls} but no business_rules cited. "
                        f"Mutation/approval goals must reference DISCUSSION-LOG BR-NN entries."
                    )

            # Conditional: decisions required if any decision cited in title
            # (e.g., "G-12: Foo (P3.D-46)" implies decisions: [P3.D-46])
            import re
            title_decisions = re.findall(r"\b(P?\d*\.?D-\d+)\b", goal["title"])
            if title_decisions and not goal["decisions"]:
                issues.append(
                    f"title references decisions {title_decisions} but decisions: field empty. "
                    f"Add decisions: [{', '.join(title_decisions)}] to frontmatter."
                )

            # Conditional: api_contracts for surface=api or mutation goals
            if goal["surface"] == "api" and not goal["api_contracts"]:
                issues.append(
                    "surface=api but no api_contracts cited. List endpoints from API-CONTRACTS.md."
                )

            # Conditional: flow_ref for surface=ui multi-step goals
            if goal["surface"] in {"ui", "ui-mobile"} and cls in {"wizard", "crud-roundtrip", "approval"}:
                if not goal["flow_ref"]:
                    issues.append(
                        f"surface=ui + goal_class={cls} → flow_ref required. "
                        f"Cite FLOW-SPEC.md anchor."
                    )

            # Cross-check: spec_ref resolves to an actual SPECS.md heading
            if goal["spec_ref"]:
                from _traceability import find_section_anchor
                # Check both repo root and phase dir
                phase_relative = phase_dir / "SPECS.md"
                repo_root = Path.cwd()
                if "#" in goal["spec_ref"]:
                    file_part, anchor = goal["spec_ref"].split("#", 1)
                    # Try phase-local SPECS.md first
                    if phase_relative.exists():
                        text = phase_relative.read_text(encoding="utf-8", errors="replace")
                        anchor_norm = anchor.lower().replace("_", "-").replace(" ", "-")
                        found = False
                        for line in text.splitlines():
                            if line.startswith("#"):
                                heading = line.lstrip("#").strip()
                                heading_slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
                                if heading_slug == anchor_norm or anchor_norm in heading_slug:
                                    found = True
                                    break
                        if not found:
                            issues.append(
                                f"spec_ref='{goal['spec_ref']}' anchor not found as heading in {phase_relative}"
                            )

            if issues:
                violations += 1
                for issue in issues:
                    out.add(
                        Evidence(
                            type="goal_traceability_gap",
                            message=f"{gid}: {issue}",
                            file=str(goals_path),
                            fix_hint=(
                                "See commands/vg/_shared/templates/TEST-GOAL-enriched-template.md "
                                "section 'v2.46 Phase 6 enrichment' for required fields."
                            ),
                        ),
                        escalate=(args.severity == "block" and not args.allow_traceability_gaps),
                    )

        if violations and (args.severity == "warn" or args.allow_traceability_gaps):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=(
                        f"{violations} goal(s) lack traceability fields, downgraded to WARN "
                        f"(severity={args.severity}, allow_gaps={args.allow_traceability_gaps}). "
                        f"Migration mode — backfill spec_ref/decisions/business_rules/expected_assertion "
                        f"in TEST-GOALS.md before next milestone."
                    ),
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
