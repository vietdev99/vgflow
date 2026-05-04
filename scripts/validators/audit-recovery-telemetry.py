#!/usr/bin/env python3
"""audit-recovery-telemetry — static validator that runs in CI.

Walks every Python file that imports `subprocess` AND mentions
`migrate-state` OR `vg-recovery` in the same file, and asserts that
each `subprocess.run([...migrate-state...])` call site has a sibling
`emit_recovery(...)` call within ±20 lines (proxy for "in same code path").

Goal: prevent silent regression where a future PR adds a new auto-fire
path without paired telemetry. Empirical cost of letting that slip:
Codex GPT-5.5 round 6 found the existing `marker_drift_recovered` was
referenced in code comments but never emitted across hundreds of runs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

AUTO_FIRE_TARGETS = [
    "migrate-state",
    "vg-recovery.py",
]

EMIT_PATTERN = re.compile(r"emit_recovery\s*\(", re.MULTILINE)


def find_violations() -> list[tuple[str, int, str]]:
    """Return list of (file, line, snippet) for unpaired auto-fire calls."""
    violations: list[tuple[str, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        path_str = str(py).replace("\\", "/")
        if "recovery_telemetry.py" in path_str:
            continue
        if "/tests/" in path_str:
            continue
        if "/.worktrees/" in path_str:
            continue
        if "/.claude/" in path_str:
            # Mirror tree — source of truth lives at repo top-level
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(t in text for t in AUTO_FIRE_TARGETS):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "subprocess.run" not in line:
                continue
            window = "\n".join(lines[i:i + 6])
            if not any(t in window for t in AUTO_FIRE_TARGETS):
                continue
            start = max(0, i - 20)
            end = min(len(lines), i + 20)
            ctx = "\n".join(lines[start:end])
            if not EMIT_PATTERN.search(ctx):
                violations.append((str(py.relative_to(REPO_ROOT)), i + 1,
                                   line.strip()[:120]))
    return violations


def main() -> int:
    v = find_violations()
    if not v:
        print("audit-recovery-telemetry: PASS (every auto-fire path has paired emit_recovery)")
        return 0
    print(f"audit-recovery-telemetry: FAIL — {len(v)} unpaired auto-fire call(s):", file=sys.stderr)
    for f, ln, snip in v:
        print(f"  {f}:{ln}  {snip}", file=sys.stderr)
    print("\nFix: wrap the subprocess.run call with emit_recovery('<kind>', 'attempted'/...)",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
