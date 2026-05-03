#!/usr/bin/env python3
"""WARN if flat blueprint artifact > 30 KB AND split subdir missing.

Exit 0 always — advisory, not block. Goal: surface re-blueprint
opportunities for legacy phases without breaking the build.

WIRING (deferred to follow-up commit, post-preflight.md ship):
  In commands/vg/_shared/build/preflight.md prerequisite block:
    python3 scripts/validators/verify-blueprint-split-size.py \\
      --phase-dir "${PHASE_DIR}" || true
  Use `|| true` because validator exits 0 either way — wired for stderr
  surfacing only.
"""
import argparse
import sys
from pathlib import Path

THRESHOLD_BYTES = 30 * 1024  # 30 KB ≈ 7K tokens — empirical AI-skim boundary
ARTIFACTS = [
    ("API-CONTRACTS.md", "API-CONTRACTS"),
    ("PLAN.md", "PLAN"),
    ("TEST-GOALS.md", "TEST-GOALS"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    args = ap.parse_args()
    pdir = Path(args.phase_dir)
    for flat_name, split_name in ARTIFACTS:
        flat = pdir / flat_name
        split = pdir / split_name
        if flat.exists() and flat.stat().st_size > THRESHOLD_BYTES and not split.exists():
            sys.stderr.write(
                f"WARN: {flat} is {flat.stat().st_size // 1024} KB but split files missing.\n"
                f"      Re-run /vg:blueprint to regenerate split layout — "
                f"AI consumers will skim this file at current size.\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
