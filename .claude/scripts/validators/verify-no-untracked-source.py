#!/usr/bin/env python3
"""verify-no-untracked-source.py — catch untracked source files at end of /vg:build.

v2.46.0 (Issue #77) — closes the silent build-passes-locally-but-fails-on-deploy
gap. Symptom from PrintwayV3 Phase 3.5 Wave 8:

  - Build executor created `apps/api/src/workers/queues/receipt-generation.queue.ts`
    (~400 LOC) and `apps/api/src/workers/receipt-generation.worker.ts` (~520 LOC).
  - Forgot `git add` for both files.
  - Local typecheck PASSED (files ARE in fs, just not staged).
  - 3 import sites compiled to `.js` references at commit time.
  - Sandbox `git pull` → only sees committed files → `pnpm turbo run build`
    failed with TS2307 "Cannot find module" for all 3 import sites.
  - Local error: NONE. Sandbox error: 3× module-not-found.

Root cause: `vg_commit_with_files` stages a literal file list; if executor
omits a file from the list, the file stays untracked while typecheck still
passes against the working tree.

This validator runs at end of /vg:build (after all waves complete, before
sandbox push). It walks the working tree, finds files matching known source
extensions, asks git which are untracked, and BLOCKS if any source-extension
file is untracked.

Exit codes:
  0 — clean (no untracked source files)
  1 — BLOCK (untracked source files detected)
  2 — config / git error

Usage:
  verify-no-untracked-source.py [--phase-dir <path>] [--exclude-pattern <re>...]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Source extensions to flag — extend as needed.
SOURCE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".rb", ".go", ".rs", ".java", ".kt", ".swift",
    ".sql", ".graphql", ".prisma",
}

# Default exclude patterns — paths that legitimately contain untracked files.
DEFAULT_EXCLUDES = [
    r"\.test\.(?:ts|tsx|js|jsx|py)$",   # tests are sometimes scaffolded ahead
    r"\.spec\.(?:ts|tsx|js|jsx)$",
    r"node_modules/",
    r"dist/",
    r"build/",
    r"__pycache__/",
    r"\.next/",
    r"coverage/",
    r"\.pytest_cache/",
    # VG bootstrap install dirs (operator-owned, not phase source)
    r"^\.claude/",
    r"^\.codex/",
    r"^\.vg/",
]


def list_untracked_files() -> list[str]:
    """Return paths of untracked files (one per line) via git status --porcelain."""
    r = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        sys.stderr.write(f"git status failed: {r.stderr}\n")
        sys.exit(2)
    out: list[str] = []
    for line in r.stdout.splitlines():
        # Porcelain format: XY <path>; untracked = "?? <path>"
        if line.startswith("?? "):
            out.append(line[3:].strip())
    return out


def is_source_file(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in SOURCE_EXTENSIONS


def matches_any(path: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(path) for p in patterns)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", default=None,
                    help="Phase dir (informational; gate runs against repo working tree).")
    ap.add_argument("--exclude-pattern", action="append", default=[],
                    help="Additional regex(es) to exclude (in addition to defaults).")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    excludes = [re.compile(p) for p in DEFAULT_EXCLUDES + args.exclude_pattern]

    untracked = list_untracked_files()
    flagged = [
        p for p in untracked
        if is_source_file(p) and not matches_any(p, excludes)
    ]

    if not flagged:
        if not args.quiet:
            print("✓ verify-no-untracked-source: no untracked source files")
        return 0

    sys.stderr.write("\n")
    sys.stderr.write("━━━ ⛔ verify-no-untracked-source — BLOCK ━━━\n")
    sys.stderr.write(
        f"{len(flagged)} source file(s) in working tree are untracked. Local "
        "typecheck may PASS while sandbox/CI build will FAIL with "
        "'Cannot find module' for any import targeting these files.\n\n"
    )
    sys.stderr.write("Untracked source files:\n")
    for p in flagged:
        sys.stderr.write(f"  ?? {p}\n")
    sys.stderr.write(
        "\nFix:\n"
        "  1. Verify each file SHOULD be in git (not a build artifact).\n"
        "  2. Add via the wave's commit queue — e.g. `vg_commit_with_files`.\n"
        "  3. If the file is intentionally untracked, add it to .gitignore\n"
        "     OR pass `--exclude-pattern '<regex>'` to this validator.\n"
    )
    sys.stderr.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    sys.stderr.flush()
    return 1


if __name__ == "__main__":
    sys.exit(main())
