#!/usr/bin/env python3
"""
Validator: verify-phase-ui-flag.py — Phase 15 D-12c

Enforces explicit `phase_has_ui_changes: true|false` in CONTEXT.md frontmatter
of every phase. Closes silent-skip gap where UI-MAP requirements pass through
unchecked because the phase never declared whether it touches UI.

Logic:
  1. Find CONTEXT.md for phase. Missing → BLOCK.
  2. Parse frontmatter. Missing `phase_has_ui_changes` key → BLOCK.
  3. If true: forward consistency — downstream blueprint MUST require UI-MAP.
     This validator only flags the declaration; T3.3 verify-uimap-schema.py
     enforces the UI-MAP existence at blueprint phase.
  4. If false: backward consistency — assert no UI files (*.tsx/.vue/.jsx/.svelte)
     appear in PLAN.md `<file-path>` entries. Contradiction → BLOCK.

Usage:  verify-phase-ui-flag.py --phase 7.14.3
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

UI_FILE_RE = re.compile(r"\.(tsx|vue|jsx|svelte)\b", re.IGNORECASE)
FILE_PATH_TAG_RE = re.compile(r"<file-path>(.*?)</file-path>", re.IGNORECASE | re.DOTALL)


def _read_frontmatter(md_path: Path) -> dict:
    if not md_path.exists():
        return {}
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    body = m.group(1)
    out: dict = {}
    # Lightweight YAML scalar parse — only top-level key: value pairs needed
    for line in body.splitlines():
        m2 = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*(.+?)\s*$", line)
        if m2:
            val = m2.group(2).strip().strip("\"'")
            if val.lower() == "true":
                out[m2.group(1)] = True
            elif val.lower() == "false":
                out[m2.group(1)] = False
            else:
                out[m2.group(1)] = val
    return out


def _ui_file_paths_in_plan(plan_path: Path) -> list[str]:
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    paths: list[str] = []
    for m in FILE_PATH_TAG_RE.finditer(text):
        path = m.group(1).strip()
        if UI_FILE_RE.search(path):
            paths.append(path)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="phase-ui-flag")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(
                type="missing_file",
                message=f"Phase directory not found for phase={args.phase}",
                fix_hint="Run /vg:add-phase first or verify phase id matches ROADMAP.md.",
            ))
            emit_and_exit(out)

        context_path = phase_dir / "CONTEXT.md"
        if not context_path.exists():
            out.add(Evidence(
                type="missing_file",
                message="CONTEXT.md not found",
                file=str(context_path),
                fix_hint="Run /vg:scope to generate CONTEXT.md before downstream validators.",
            ))
            emit_and_exit(out)

        fm = _read_frontmatter(context_path)
        if "phase_has_ui_changes" not in fm:
            out.add(Evidence(
                type="schema_violation",
                message="CONTEXT.md frontmatter missing required key 'phase_has_ui_changes'",
                file=str(context_path),
                expected="phase_has_ui_changes: true | false",
                fix_hint=(
                    "Add to CONTEXT.md frontmatter (between the --- delimiters):\n"
                    "  phase_has_ui_changes: true   # phase touches UI files (*.tsx/.vue/.jsx/.svelte)\n"
                    "  phase_has_ui_changes: false  # phase is API/infra/docs only"
                ),
            ))
            emit_and_exit(out)

        flag = fm["phase_has_ui_changes"]
        if not isinstance(flag, bool):
            out.add(Evidence(
                type="schema_violation",
                message=f"phase_has_ui_changes must be boolean true|false (got {flag!r})",
                file=str(context_path),
                actual=flag,
                expected="true | false",
            ))
            emit_and_exit(out)

        # Backward consistency: false declared → no UI files in PLAN
        if flag is False:
            # PLAN.md or PLAN-*.md may exist
            plan_candidates = list(phase_dir.glob("PLAN*.md"))
            for plan_path in plan_candidates:
                ui_paths = _ui_file_paths_in_plan(plan_path)
                if ui_paths:
                    out.add(Evidence(
                        type="semantic_check_failed",
                        message=(
                            f"phase_has_ui_changes: false but PLAN contains "
                            f"{len(ui_paths)} UI file path(s)"
                        ),
                        file=str(plan_path),
                        actual=ui_paths[:5],
                        expected="no *.tsx/*.vue/*.jsx/*.svelte in <file-path> tags",
                        fix_hint=(
                            "Either flip phase_has_ui_changes to true (and add UI-MAP.md) "
                            "OR remove UI files from PLAN.md."
                        ),
                    ))
                    emit_and_exit(out)

        # PASS — flag present + consistent
        out.evidence.append(Evidence(
            type="info",
            message=f"phase_has_ui_changes: {str(flag).lower()} (consistent with PLAN)",
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
