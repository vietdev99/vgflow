#!/usr/bin/env python3
"""
verify-goal-coverage-phase.py — phase-level goal coverage audit.

Complements verify-goal-test-binding.py (which checks per-task commit-bound
tests). This check runs AT END of /vg:build (step 10) or /vg:review entry,
after ALL waves complete, to catch goals that got declared but never tested.

## Why (Phase 10 audit finding)

Per-task binding passes when each commit modifies a test file. But a goal
can still lack coverage if:
- Task was re-done via (recovered) commit bypassing wave-start tag
- Test file touched covers a DIFFERENT goal than declared
- Test uses a TS-XX marker number that doesn't match any G-XX

This script does a final sweep: every G-XX in TEST-GOALS.md must have at
least one test file anywhere in repo with matching TS-XX marker.

## Exit codes
  0 — all automated goals have matching TS-XX
  2 — BLOCK: automated goals missing coverage
  1 — script error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


GOAL_ID_PAT = re.compile(
    r"(?m)^(?:#{1,4}\s*(?:Goal\s+)?|\|\s*|\s*-\s*\*\*)(G-\d+)",
)
VERIFICATION_PAT = re.compile(
    r"verification\W+(\w+)",
    re.IGNORECASE,
)
TS_IN_TEST_PAT = re.compile(r"\bTS-(\d+)\b")


def parse_goals(test_goals_md: Path) -> dict[str, str]:
    """Return { 'G-01': 'automated' | 'deferred' | 'manual' }."""
    if not test_goals_md.exists():
        return {}
    txt = test_goals_md.read_text(encoding="utf-8", errors="ignore")
    goals: dict[str, str] = {}
    # Find each G-XX + look ahead ~10 lines for verification annotation
    starts = [(m.group(1), m.start()) for m in GOAL_ID_PAT.finditer(txt)]
    for i, (gid, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(txt)
        block = txt[start:end]
        m = VERIFICATION_PAT.search(block)
        verification = m.group(1).lower() if m else "automated"
        # Normalize
        if verification in ("deferred", "manual", "na", "n/a"):
            verification = "deferred"
        else:
            verification = "automated"
        # Only overwrite if first occurrence (some goals listed in both table + section)
        if gid not in goals:
            goals[gid] = verification
    return goals


def scan_test_markers(repo_root: Path) -> dict[str, list[str]]:
    """Return { 'TS-01': [rel_path, ...] } aggregating all TS markers in test files."""
    patterns = [
        "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx",
        "*.test.js", "*.spec.js",
        "*.test.py", "*.spec.py",
        "*.test.go", "*.spec.rs",
        "*_test.dart",
        "*.maestro.yaml", "*.maestro.yml",
    ]
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"] + patterns,
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return {}

    ts_map: dict[str, list[str]] = defaultdict(list)
    for line in out.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel or "node_modules/" in rel:
            continue
        p = repo_root / rel
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in TS_IN_TEST_PAT.finditer(content):
            ts_id = f"TS-{m.group(1).zfill(2)}"
            if rel not in ts_map[ts_id]:
                ts_map[ts_id].append(rel)
    return dict(ts_map)


def verify(phase_dir: Path, repo_root: Path, strict: bool = True) -> tuple[int, dict]:
    goals = parse_goals(phase_dir / "TEST-GOALS.md")
    ts_map = scan_test_markers(repo_root)

    bound: dict[str, list[str]] = {}
    unbound_auto: list[str] = []
    unbound_deferred: list[str] = []

    for gid, verification in sorted(goals.items()):
        # Canonical binding: G-NN → TS-NN (same number)
        ts_candidate = f"TS-{gid.removeprefix('G-').zfill(2)}"
        files = ts_map.get(ts_candidate, [])
        if files:
            bound[gid] = files
        elif verification == "deferred":
            unbound_deferred.append(gid)
        else:
            unbound_auto.append(gid)

    # Orphan TS markers (tests for goals not declared)
    orphans = sorted(
        ts for ts in ts_map
        if f"G-{ts.removeprefix('TS-').zfill(2)}" not in goals
    )

    summary = {
        "goals_total": len(goals),
        "bound": len(bound),
        "unbound_automated": len(unbound_auto),
        "unbound_deferred": len(unbound_deferred),
        "orphan_ts_markers": len(orphans),
        "details": {
            "bound": {g: bound[g] for g in sorted(bound)},
            "unbound_automated": unbound_auto,
            "unbound_deferred": unbound_deferred,
            "orphans": orphans,
        },
    }

    exit_code = 2 if (strict and unbound_auto) else 0
    return exit_code, summary


def print_report(summary: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(summary, indent=2))
        return

    total = summary["goals_total"]
    print(f"# Phase Goal Coverage Audit\n")
    print(f"**Goals total:** {total}")
    print(f"**Bound (TS-XX found):** {summary['bound']}")
    print(f"**Unbound automated:** {summary['unbound_automated']}")
    print(f"**Unbound deferred:** {summary['unbound_deferred']}")
    print(f"**Orphan TS markers:** {summary['orphan_ts_markers']}")
    print()

    if summary["details"]["bound"]:
        print("## ✓ Bound\n")
        for g, files in summary["details"]["bound"].items():
            shown = ", ".join(files[:2])
            extra = f" (+{len(files) - 2})" if len(files) > 2 else ""
            print(f"- {g} → {shown}{extra}")
        print()

    if summary["details"]["unbound_automated"]:
        print("## ⛔ Unbound automated (BLOCK)\n")
        for g in summary["details"]["unbound_automated"]:
            ts = f"TS-{g.removeprefix('G-').zfill(2)}"
            print(f"- {g} → no test file contains `{ts}` marker")
        print()

    if summary["details"]["unbound_deferred"]:
        print("## ⚠ Deferred (advisory)\n")
        for g in summary["details"]["unbound_deferred"]:
            print(f"- {g} — marked deferred/manual, binding not required")
        print()

    if summary["details"]["orphans"]:
        print("## ℹ Orphan TS markers\n")
        for ts in summary["details"]["orphans"][:15]:
            print(f"- {ts} (no matching G-XX declared)")
        if summary["orphan_ts_markers"] > 15:
            print(f"- ... +{summary['orphan_ts_markers'] - 15} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--advisory", action="store_true",
                    help="Do not exit 2 on unbound — print warnings only")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    repo_root = Path(args.repo_root).resolve()

    if not (phase_dir / "TEST-GOALS.md").is_file():
        print(f"\033[38;5;208mTEST-GOALS.md not found in {phase_dir}\033[0m", file=sys.stderr)
        return 1

    rc, summary = verify(phase_dir, repo_root, strict=not args.advisory)
    print_report(summary, as_json=args.json)

    if rc == 2:
        print(
            f"\n⛔ BLOCK: {summary['unbound_automated']} automated goal(s) lack TS-XX binding.\n"
            f"   Fix options:\n"
            f"   1. Add `it('TS-NN ...', ...)` in a test file for each unbound goal.\n"
            f"   2. Mark goal `verification: deferred` in TEST-GOALS.md if truly not automatable.\n",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
