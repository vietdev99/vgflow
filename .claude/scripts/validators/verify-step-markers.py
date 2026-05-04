#!/usr/bin/env python3
"""
Validator: verify-step-markers.py

Harness v2.6 (2026-04-25): closes the universal "Profile enforcement"
rule from VG skill files:

  Rule 7/8/10/11 (varies per skill): "every <step> MUST, as FINAL action:
   touch ${PHASE_DIR}/.step-markers/{STEP_NAME}.done"

Why it exists: VG skills (vg:scope, vg:blueprint, vg:build, vg:review,
vg:test, vg:accept) declare ordered steps via `<step name="...">`
markers. AI may silently skip a step if processing the skill's body
takes too long or the step's prose is unclear. The marker file is
deterministic forensic evidence — if `.step-markers/{step}.done` is
missing, the step did NOT run, regardless of what the AI claims.

Existing validators (commit-attribution, runtime-evidence) check OUTPUT
artifacts but not step COMPLETION sequence. This validator closes that
gap.

What it checks:

  1. Parse skill files (.codex/skills/vg-*/SKILL.md OR .claude/commands/
     vg/*.md) to extract `<step name="...">` declarations per command.

  2. Read `.vg/phases/<phase>/.step-markers/*.done` files for the phase
     under review.

  3. Compare expected steps (from skill) vs actual markers (from disk).
     Missing marker = step skipped silently. BLOCK.

  4. Profile-aware filtering: skill steps may carry profile="..." attribute
     declaring which platform profiles they apply to (e.g. browser steps
     are web-only). Skip steps whose profile attribute excludes current
     phase profile.

Severity: BLOCK (deterministic evidence — missing marker proves step
                 did NOT run).

Usage:
  verify-step-markers.py --phase 7.14
  verify-step-markers.py --phase 7.14 --command vg:build (filter to one)

Exit codes:
  0  PASS (all expected markers present)
  1  BLOCK (one or more markers missing)
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

STEP_RE = re.compile(
    r'<step\s+name=["\']([^"\']+)["\'](?:\s+profile=["\']([^"\']*)["\'])?\s*>',
    re.IGNORECASE,
)


def _find_skill_file(command: str) -> Path | None:
    """Find the skill file for a /vg:* command. Tries both
    .codex/skills/{name}/SKILL.md and .claude/commands/vg/{name}.md."""
    name = command.replace("vg:", "")
    candidates = [
        REPO_ROOT / ".codex" / "skills" / f"vg-{name}" / "SKILL.md",
        REPO_ROOT / ".claude" / "commands" / "vg" / f"{name}.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _extract_steps(skill_path: Path, profile: str) -> list[str]:
    """Extract step names from skill file, filtered by phase profile."""
    try:
        text = skill_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    steps: list[str] = []
    for m in STEP_RE.finditer(text):
        step_name = m.group(1).strip()
        step_profile = m.group(2) or ""
        # Profile filter: empty = applies to all; comma-separated list = match
        if step_profile:
            allowed = [p.strip() for p in step_profile.split(",") if p.strip()]
            if profile not in allowed and "all" not in allowed and "*" not in allowed:
                continue
        steps.append(step_name)
    return steps


def _markers_present(phase_dir: Path) -> set[str]:
    markers_dir = phase_dir / ".step-markers"
    if not markers_dir.exists():
        return set()
    return {f.stem for f in markers_dir.glob("*.done")}


def _phase_profile(phase_dir: Path) -> str:
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return "feature"
    try:
        text = specs.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "feature"
    m = re.search(r"^profile:\s*(\w+)", text, re.MULTILINE)
    if m:
        return m.group(1).lower()
    return "feature"


def _last_run_command(phase_dir: Path) -> str | None:
    """Best-effort detection of which command last ran for this phase
    by inspecting PIPELINE-STATE.json `pipeline_step` field."""
    pipeline = phase_dir / "PIPELINE-STATE.json"
    if not pipeline.exists():
        return None
    try:
        import json as _json
        data = _json.loads(pipeline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    step = data.get("pipeline_step") or data.get("status")
    if step:
        return f"vg:{step}" if not step.startswith("vg:") else step
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--command", default=None,
                    help="Limit check to one /vg:* command (default: auto-detect "
                         "from PIPELINE-STATE.json or check all completed commands)")
    ap.add_argument("--strict", action="store_true",
                    help="Reserved — currently unused (BLOCK is default)")
    args = ap.parse_args()

    out = Output(validator="verify-step-markers")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        profile = _phase_profile(phase_dir)
        markers_present = _markers_present(phase_dir)

        # Determine which command(s) to check
        if args.command:
            commands_to_check = [args.command]
        else:
            last_cmd = _last_run_command(phase_dir)
            if last_cmd:
                commands_to_check = [last_cmd]
            else:
                # Fallback: check all 6 commands
                commands_to_check = ["vg:scope", "vg:blueprint", "vg:build",
                                     "vg:review", "vg:test", "vg:accept"]

        # Skip when no markers at all — phase hasn't run yet (PASS, not BLOCK)
        if not markers_present:
            emit_and_exit(out)

        missing_per_command: dict[str, list[str]] = {}
        for cmd in commands_to_check:
            skill = _find_skill_file(cmd)
            if not skill:
                continue
            expected = _extract_steps(skill, profile)
            if not expected:
                continue

            # Check which expected steps are missing markers
            missing = [s for s in expected if s not in markers_present]

            # Heuristic: if NONE of the command's steps have markers, the
            # command never ran for this phase — skip (no false positives
            # for unran commands).
            present_count = sum(1 for s in expected if s in markers_present)
            if present_count == 0:
                continue  # command not run yet for this phase
            if present_count < len(expected) and missing:
                missing_per_command[cmd] = missing

        for cmd, missing in missing_per_command.items():
            out.add(Evidence(
                type="step_markers_missing",
                message=f"{cmd}: {len(missing)} expected step marker(s) missing — step(s) silently skipped",
                actual=f"Missing: {missing[:8]}",
                expected=f"All <step name='...'> declarations in skill file MUST write {phase_dir.name}/.step-markers/<step>.done as FINAL action",
                fix_hint=(
                    f"Re-run /{cmd} {args.phase} to complete missing steps. "
                    f"If steps were intentionally skipped, ensure skill body's "
                    f"final action `touch \"${{PHASE_DIR}}/.step-markers/{{step}}.done\"` "
                    f"is reached. Per universal Rule 7-11 in skill files: "
                    f"'every <step> MUST, as FINAL action, write marker'."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
