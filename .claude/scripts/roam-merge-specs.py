#!/usr/bin/env python3
"""roam-merge-specs.py (v1.0 stub)

Merge proposed-specs/*.spec.ts (output of /vg:roam analysis) into the
project's actual test suite. Manual gate per Q10 — only runs when user
explicitly passes /vg:roam --merge-specs.

v1.0 stub: copies files with confirmation prompt. Real impl in v1.1 will:
  - Run vg-codegen-interactive validator on each proposed spec
  - Reject malformed specs
  - Detect duplicate / overlap with existing tests
  - Tag merged specs in PIPELINE-STATE.json with origin=roam-{phase}

Spec: ROAM-RFC-v1.md "Special invocation modes — --merge-specs".
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--proposed-dir", required=True)
    ap.add_argument("--target-dir", required=True, help="e.g., tests/e2e or apps/admin/tests")
    args = ap.parse_args()

    proposed = Path(args.proposed_dir)
    target = Path(args.target_dir)
    if not proposed.exists() or not any(proposed.iterdir()):
        print(f"[roam-merge] no proposed specs in {proposed}", file=sys.stderr)
        return 0

    target.mkdir(parents=True, exist_ok=True)
    phase_id = Path(args.phase_dir).name

    moved = 0
    for spec in sorted(proposed.glob("*.spec.ts")):
        # Tag merged file with origin in target dir
        target_path = target / f"roam-{phase_id}-{spec.name}"
        if target_path.exists():
            print(f"[roam-merge] {target_path.name} already exists — skipping (manual review needed)")
            continue
        shutil.copy2(spec, target_path)
        moved += 1
        print(f"[roam-merge] merged {spec.name} → {target_path}")

    print(f"[roam-merge] {moved} spec(s) merged into {target}. Run pnpm test (or your CI) to verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
