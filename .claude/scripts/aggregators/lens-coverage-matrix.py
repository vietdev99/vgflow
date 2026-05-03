#!/usr/bin/env python3
"""lens-coverage-matrix.py — render LENS-COVERAGE-MATRIX.md (Task 26).

7 status enum (Codex round 5):
  PASS                — artifact present, all checks pass
  FAIL                — artifact present, finding_fact entries
  INCONCLUSIVE        — artifact present, status=inconclusive in steps[]
  N/A                 — applicability_status=N/A in dispatch plan
  SKIPPED_BY_POLICY   — applicability_status=SKIPPED_BY_POLICY (with reason)
  SKIPPED_BY_OVERRIDE — applicability_status=SKIPPED_BY_OVERRIDE
  MISSING             — applicable but artifact missing (gate BLOCKs)

Output: human-readable matrix + per-cell footnote linking artifact path
+ applicability reason for skips.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

GLYPH = {
    "PASS": "✓",
    "FAIL": "✗",
    "INCONCLUSIVE": "?",
    "N/A": "—",
    "SKIPPED_BY_POLICY": "⊘",
    "SKIPPED_BY_OVERRIDE": "⊘*",
    "MISSING": "⛔",
}


def _classify_artifact(artifact: dict | None) -> str:
    if artifact is None:
        return "MISSING"
    findings = artifact.get("finding_fact") or artifact.get("findings", [])
    if findings:
        return "FAIL"
    steps = artifact.get("steps", [])
    if any(s.get("status") == "inconclusive" for s in steps):
        return "INCONCLUSIVE"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch-plan", required=True)
    parser.add_argument("--runs-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = json.loads(Path(args.dispatch_plan).read_text(encoding="utf-8"))
    runs_dir_parent = Path(args.runs_dir).parent

    by_lens: dict[str, dict[str, dict]] = defaultdict(dict)
    goals: set[str] = set()
    for d in plan["dispatches"]:
        lens = d["lens"]
        goal = d["goal_id"]
        goals.add(goal)
        status = d["applicability_status"]
        if status == "APPLICABLE":
            artifact = None
            if d.get("expected_artifact_path"):
                p = runs_dir_parent / d["expected_artifact_path"]
                if p.exists():
                    try:
                        artifact = json.loads(p.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        artifact = None
            cell_status = _classify_artifact(artifact)
        elif status == "N/A":
            cell_status = "N/A"
        elif status == "SKIPPED_BY_POLICY":
            cell_status = "SKIPPED_BY_POLICY"
        else:
            cell_status = "SKIPPED_BY_OVERRIDE"
        by_lens[lens][goal] = {
            "status": cell_status,
            "reason": d.get("applicability_reason", ""),
            "artifact_path": d.get("expected_artifact_path", ""),
        }

    sorted_goals = sorted(goals)
    sorted_lenses = sorted(by_lens)

    out = []
    out.append(f"# Lens Coverage Matrix — {plan['phase']}")
    out.append("")
    out.append(f"**Plan hash:** `{plan['plan_hash'][:16]}...`")
    out.append(f"**Commit:** `{plan['commit_sha'][:12]}`")
    out.append(f"**Emitted:** {plan.get('emitted_at', '?')}")
    out.append("")
    out.append("Legend: ✓ PASS | ✗ FAIL | ? INCONCLUSIVE | — N/A | ⊘ POLICY-SKIP | ⊘* OVERRIDE-SKIP | ⛔ MISSING")
    out.append("")

    header = "| Lens \\ Goal | " + " | ".join(sorted_goals) + " |"
    sep = "|---|" + "|".join(["---"] * len(sorted_goals)) + "|"
    out.append(header)
    out.append(sep)

    footnotes: list[str] = []
    for lens in sorted_lenses:
        row = [lens]
        for goal in sorted_goals:
            cell = by_lens[lens].get(goal)
            if not cell:
                row.append("")
                continue
            glyph = GLYPH.get(cell["status"], "?")
            row.append(glyph)
            if cell["status"] in ("FAIL", "MISSING", "SKIPPED_BY_POLICY", "SKIPPED_BY_OVERRIDE", "INCONCLUSIVE"):
                fn_id = f"{lens}.{goal}"
                footnotes.append(f"- **{fn_id}** ({cell['status']}): "
                                 f"{cell['reason']}; artifact={cell['artifact_path'] or 'n/a'}")
        out.append("| " + " | ".join(row) + " |")

    if footnotes:
        out.append("")
        out.append("## Footnotes")
        out.append("")
        out.extend(footnotes)

    Path(args.output).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"✓ Wrote {args.output} ({len(sorted_lenses)} lenses × {len(sorted_goals)} goals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
