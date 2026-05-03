#!/usr/bin/env python3
"""
Validator: review-skip-guard.py

Purpose: Block /vg:review when it sets RUNTIME-MAP.discovery_mode to
`skipped_no_browser` (or any `skipped_*` variant) BUT the phase declares
critical UI goals in TEST-GOALS.md. This is the exact anti-pattern the phase
14 dogfood run exposed on 2026-04-22:
  - RUNTIME-MAP.json discovery_mode=skipped_no_browser
    skip_reason="Phase 14 requires 4-port dev stack"
  - TEST-GOALS.md has 8 critical UI goals
  - Playwright spec executable on single-port (4/5 tests)
  - Review exits PASS with evidence from unit tests only
  - Actual browser run on next day: 4/5 FAIL (G-02 returns 400 not 403)

Enforcement: if critical UI goals exist AND discovery was skipped, validator
returns BLOCK. Override path: add `--skip-review-browser` flag to run-start
with `--override-reason ≥50 chars` (which Day 2 gate validates) + rationalization-
guard approval (skill-level).

Skip (PASS):
- No RUNTIME-MAP.json → review not executed yet (not our gate)
- discovery_mode != skipped_* → browser discovery actually happened
- No critical UI goals in TEST-GOALS.md → non-UI phase, skip acceptable
- All critical UI goals marked MANUAL via user confirmation in
  GOAL-COVERAGE-MATRIX.md → explicit promotion, not silent skip

Checks (BLOCK):
- RUNTIME-MAP.json exists with discovery_mode starting "skipped_"
- TEST-GOALS.md has ≥1 goal with priority=critical AND surface=ui|web|frontend
- Those goals NOT marked MANUAL in GOAL-COVERAGE-MATRIX.md

Usage: review-skip-guard.py --phase <N>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

# TEST-GOALS.md parsing:
# Goals look like:
#   ### G-01: <title>
#   - priority: critical
#   - surface: ui
# OR table rows:
#   | G-01 | critical | ui | READY | ... |
GOAL_HEADER_RE = re.compile(
    r"^###\s+(?:Goal\s+)?G-(\d+)[:\s]", re.MULTILINE,
)
GOAL_TABLE_ROW_RE = re.compile(
    r"^\|\s*G-(\d+)\s*\|\s*([a-z_-]+)\s*\|\s*([a-z_-]+)\s*\|",
    re.MULTILINE | re.IGNORECASE,
)
# Accept both `- priority: critical` AND `**Priority:** critical` (case-insensitive).
# Note the colon is INSIDE the bold markers: `**Priority:**`, not `**Priority**:`.
PRIORITY_FRONTMATTER_RE = re.compile(
    r"^\s*(?:-\s*priority:|\*\*priority:\*\*)\s*([a-z_-]+)",
    re.MULTILINE | re.IGNORECASE,
)
SURFACE_FRONTMATTER_RE = re.compile(
    r"^\s*(?:-\s*surface:|\*\*surface:\*\*)\s*([a-z_,\s-]+?)\s*(?:$|\*\*|<)",
    re.MULTILINE | re.IGNORECASE,
)

# Goal-Coverage-Matrix parsing:
#   | G-01 | critical | ui | MANUAL | ... |
#   | G-02 | critical | ui | READY  | ... |
COVERAGE_ROW_RE = re.compile(
    r"^\|\s*G-(\d+)\s*\|[^|]+\|[^|]+\|\s*([A-Z_]+)\s*\|",
    re.MULTILINE,
)

UI_SURFACE_VALUES = {"ui", "web", "frontend", "dashboard", "admin-portal"}
CRITICAL_PRIORITY_VALUES = {"critical", "p0", "blocker"}


def parse_critical_ui_goals(test_goals_path: Path) -> list[dict]:
    """Extract goals with priority=critical AND surface in UI set."""
    if not test_goals_path.exists():
        return []
    text = test_goals_path.read_text(encoding="utf-8", errors="replace")
    goals: list[dict] = []

    # Strategy 1: frontmatter-style ### G-XX blocks with - priority/surface fields
    # Split into blocks per goal header
    header_matches = list(GOAL_HEADER_RE.finditer(text))
    if header_matches:
        for i, m in enumerate(header_matches):
            goal_id = f"G-{m.group(1).zfill(2)}"
            block_start = m.end()
            block_end = (header_matches[i + 1].start()
                         if i + 1 < len(header_matches) else len(text))
            block = text[block_start:block_end]
            prio_m = PRIORITY_FRONTMATTER_RE.search(block)
            surf_m = SURFACE_FRONTMATTER_RE.search(block)
            priority = (prio_m.group(1).lower() if prio_m else "").strip()
            surface = (surf_m.group(1).lower() if surf_m else "").strip()
            # Surface might be comma-separated
            surfaces = {s.strip() for s in surface.split(",")}
            if priority in CRITICAL_PRIORITY_VALUES and \
               (surfaces & UI_SURFACE_VALUES):
                goals.append({"id": goal_id, "priority": priority,
                              "surface": ",".join(surfaces)})

    # Strategy 2: markdown table rows | G-XX | priority | surface | ...
    for m in GOAL_TABLE_ROW_RE.finditer(text):
        goal_id = f"G-{m.group(1).zfill(2)}"
        priority = m.group(2).lower()
        surface = m.group(3).lower()
        if priority in CRITICAL_PRIORITY_VALUES and \
           surface in UI_SURFACE_VALUES:
            # Avoid dupes from strategy 1
            if not any(g["id"] == goal_id for g in goals):
                goals.append({"id": goal_id, "priority": priority,
                              "surface": surface})

    return goals


def parse_goal_statuses(coverage_path: Path) -> dict[str, str]:
    """Return {goal_id: status} from GOAL-COVERAGE-MATRIX.md."""
    if not coverage_path.exists():
        return {}
    text = coverage_path.read_text(encoding="utf-8", errors="replace")
    statuses: dict[str, str] = {}
    for m in COVERAGE_ROW_RE.finditer(text):
        goal_id = f"G-{m.group(1).zfill(2)}"
        status = m.group(2).upper()
        statuses[goal_id] = status
    return statuses


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="review-skip-guard")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            emit_and_exit(out)

        phase_dir = phase_dirs[0]
        runtime_map = phase_dir / "RUNTIME-MAP.json"
        test_goals = phase_dir / "TEST-GOALS.md"
        coverage = phase_dir / "GOAL-COVERAGE-MATRIX.md"

        # No RUNTIME-MAP → review not executed → not our gate yet (PASS)
        if not runtime_map.exists():
            emit_and_exit(out)

        try:
            rt = json.loads(runtime_map.read_text(encoding="utf-8"))
        except Exception as e:
            out.warn(Evidence(
                type="parse_error",
                message=f"RUNTIME-MAP.json unreadable: {e}",
                file=str(runtime_map),
                fix_hint="Fix JSON syntax or delete file to force re-discovery.",
            ))
            emit_and_exit(out)

        mode = str(rt.get("discovery_mode", "")).lower()
        skip_reason = str(rt.get("skip_reason", "")).strip()

        # Browser discovery happened → PASS
        if not mode.startswith("skipped"):
            emit_and_exit(out)

        # Discovery skipped — check if critical UI goals exist
        critical_ui = parse_critical_ui_goals(test_goals)
        if not critical_ui:
            # No critical UI goals → skip acceptable (non-UI phase)
            emit_and_exit(out)

        # Check GOAL-COVERAGE-MATRIX — goals marked MANUAL via user confirmation
        # are explicit promotions, not silent skip
        statuses = parse_goal_statuses(coverage)
        unconfirmed = [
            g for g in critical_ui
            if statuses.get(g["id"], "UNKNOWN") not in {"MANUAL", "DEFERRED"}
        ]

        if not unconfirmed:
            # All critical UI goals explicitly promoted to MANUAL/DEFERRED
            # → user signed off, not a silent skip.
            emit_and_exit(out)

        # BLOCK — critical UI goals without browser evidence AND without
        # explicit MANUAL promotion
        sample = unconfirmed[:5]
        evidence_str = "; ".join(
            f"{g['id']}(priority={g['priority']},surface={g['surface']},"
            f"status={statuses.get(g['id'], 'NOT_IN_MATRIX')})"
            for g in sample
        )

        out.add(Evidence(
            type="skipped_with_critical_goals",
            message=(
                f"Review skipped browser discovery (mode={mode}) but phase has "
                f"{len(unconfirmed)} critical UI goal(s) without explicit MANUAL "
                f"promotion. Skip reason: {skip_reason[:120]!r}"
            ),
            file=str(runtime_map),
            expected="browser discovery completed OR critical UI goals promoted to MANUAL",
            actual=evidence_str + (f" (+{len(unconfirmed) - 5} more)"
                                   if len(unconfirmed) > 5 else ""),
            fix_hint=(
                "Pick ONE: "
                "(a) Run /vg:review <phase> with dev stack up to actually discover. "
                "(b) /vg:amend <phase> to promote each critical UI goal to "
                "verification: manual with user-visible justification. "
                "(c) --skip-review-browser --override-reason '<50+ char justification>' "
                "— requires rationalization-guard PASS/FLAG (Day 1 gate)."
            ),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
