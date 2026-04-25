#!/usr/bin/env python3
"""_patch-phase-arg.py — one-shot script to add `--phase` arg to validators
that don't accept it. Used by harness v2.6 to enable orchestrator dispatch.

Orchestrator's _run_validators in vg-orchestrator/__main__.py spawns each
validator with `--phase <N>`. Validators that don't accept --phase choke
with argparse error (rc=2). This script inserts `ap.add_argument("--phase", ...)`
before `args = ap.parse_args()` line if not already present.

Idempotent: skips files that already have --phase.

Usage: python3 _patch-phase-arg.py [validator-file ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

PHASE_ARG_LINE = '    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")\n'

THIS_DIR = Path(__file__).resolve().parent


def patch(file_path: Path) -> str:
    text = file_path.read_text(encoding="utf-8")
    if '"--phase"' in text or "'--phase'" in text:
        return "skip-already-has-phase"
    if "args = ap.parse_args()" not in text:
        return "skip-no-parse-args-line"
    # Find line with `args = ap.parse_args()` and insert phase arg before it
    lines = text.splitlines(keepends=True)
    out_lines: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and "args = ap.parse_args()" in line:
            out_lines.append(PHASE_ARG_LINE)
            inserted = True
        out_lines.append(line)
    if not inserted:
        return "skip-no-anchor"
    file_path.write_text("".join(out_lines), encoding="utf-8")
    return "patched"


def main() -> int:
    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:]]
    else:
        # Default: patch all validators in same dir
        targets = [p for p in THIS_DIR.glob("verify-*.py")]

    ok = 0
    skipped = 0
    for fp in targets:
        if not fp.exists():
            print(f"  ✗ {fp.name}: not found")
            continue
        result = patch(fp)
        if result == "patched":
            ok += 1
            print(f"  ✓ {fp.name}: patched")
        else:
            skipped += 1
            print(f"  - {fp.name}: {result}")

    print(f"\nResult: {ok} patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
