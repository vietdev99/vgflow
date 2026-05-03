#!/usr/bin/env python3
"""
Validator: phase-exists.py

Purpose: verify the phase directory + PIPELINE-STATE.json exist before any
downstream validator runs. Cheap precondition check — if this fails, every
other validator would fail too, better to stop early with clear error.

Usage: phase-exists.py --phase <N>
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"


def resolve_phase_dir(phase: str) -> Path | None:
    """Deprecated shim — delegates to shared find_phase_dir helper
    (OHOK v2 follow-up 2026-04-22 fix: decimal phase zero-pad + bare-dir).
    """
    return find_phase_dir(phase)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="phase-exists")
    with timer(out):
        phase_dir = resolve_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(
                type="missing_file",
                message=f"No phase directory found for phase={args.phase}",
                expected=f"{PHASES_DIR}/{args.phase}-*/",
                fix_hint=(
                    f"Create the phase dir first (e.g. via /vg:add-phase) or "
                    f"check that '{args.phase}' matches ROADMAP.md numbering."
                ),
            ))
            emit_and_exit(out)

        # SPECS.md — mandatory per-phase anchor
        specs = phase_dir / "SPECS.md"
        if not specs.exists():
            out.add(Evidence(
                type="missing_file",
                message="SPECS.md missing",
                file=str(specs),
                fix_hint="Run /vg:specs to generate SPECS.md for this phase.",
            ))
        elif specs.stat().st_size < 100:
            out.warn(Evidence(
                type="empty_file",
                message=f"SPECS.md is {specs.stat().st_size} bytes — likely stub",
                file=str(specs),
            ))

        # PIPELINE-STATE.json — may or may not exist depending on which phase
        # (early commands create it; warn if missing but don't block).
        state = phase_dir / "PIPELINE-STATE.json"
        if not state.exists():
            out.warn(Evidence(
                type="missing_file",
                message="PIPELINE-STATE.json missing (may be created by scope/blueprint)",
                file=str(state),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
