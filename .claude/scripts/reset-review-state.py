#!/usr/bin/env python3
"""Clear review-generated state so /vg:review --force reruns from scratch."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


FILE_GLOBS = (
    "api-docs-check.txt",
    "api-contract-precheck.txt",
    "nav-discovery.json",
    "scan-*.json",
    "scan-manifest.json",
    "view-assignments.json",
    "view-assignments-retry.json",
    ".re-scan-goals.txt",
    ".matrix-staleness.json",
    ".surface-probe-results.json",
    ".recursive-probe-skipped.yaml",
    "TEST-GOALS-DISCOVERED.md",
    "recursive-goals-overflow.json",
    "RUNTIME-MAP.json",
    "RUNTIME-MAP.md",
    "GOAL-COVERAGE-MATRIX.md",
    "element-counts.json",
    "crossai/review-check.xml",
    ".step-markers/review/*.done",
)

DIR_GLOBS = (
    "scans",
    "recursive-prompts",
    "runs",
)


def _remove_path(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def reset_review_state(phase_dir: Path) -> dict:
    removed: list[str] = []

    for pattern in FILE_GLOBS:
        for match in sorted(phase_dir.glob(pattern)):
            if _remove_path(match):
                removed.append(match.relative_to(phase_dir).as_posix())

    for pattern in DIR_GLOBS:
        for match in sorted(phase_dir.glob(pattern)):
            if _remove_path(match):
                removed.append(match.relative_to(phase_dir).as_posix() + "/")

    return {
        "phase_dir": str(phase_dir),
        "removed": removed,
        "removed_count": len(removed),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True, help="Absolute or repo-relative phase dir")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).expanduser().resolve()
    if not phase_dir.exists():
        print(json.dumps({
            "phase_dir": str(phase_dir),
            "error": "phase_dir_missing",
        }))
        return 1

    result = reset_review_state(phase_dir)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
