#!/usr/bin/env python3
"""
evaluate-test-requirements.py — Phase R of v2.5.2 hardening.

Problem closed:
  v2.5.1 had verify-goal-coverage-phase.py that checked every automated
  goal has a TS-XX marker in some test file. But it did NOT assess
  whether the test *meaningfully exercises* the goal, or whether the
  test follows the testing baseline declared in FOUNDATION.md section 7.
  Still soft.

This validator evaluates test requirement completeness:
  1. Parse TEST-GOALS.md for goals with `priority: critical|important`
  2. Parse FOUNDATION.md §7 for test baseline (runner, E2E framework,
     coverage threshold)
  3. Find test files referencing each goal via TS-XX markers
  4. Evaluate each test against baseline:
     - Uses declared runner (vitest/pytest/go-test/...)
     - Has assertion count >= min_assertions (default 2)
     - For priority=critical: has E2E variant if goal mentions user-flow
  5. Report per-goal evaluation — not a hard gate at this layer,
     but surfaces gaps that /vg:accept can decide on

Exit codes:
  0 = all evaluated goals meet requirements
  1 = gaps found (can be warn-only via --warn-only)
  2 = config error

Usage:
  evaluate-test-requirements.py --phase-dir <path>
  evaluate-test-requirements.py --phase-dir X --foundation <path> --warn-only
  evaluate-test-requirements.py --phase-dir X --min-assertions 3 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _parse_test_goals(path: Path) -> list[dict]:
    """
    Parse TEST-GOALS.md — list of goals with id/priority/ts_id/ description.

    Expected per goal:
        ### G-01 — Login user authenticates
        **Priority:** critical
        **TS:** TS-14
        **Description:** user with valid creds receives session token
        **Verification:** automated | deferred | manual

    Returns list of dicts.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    goals = []

    blocks = re.split(r"\n(?=###\s+G-\d+)", text)
    for block in blocks:
        m = re.match(r"###\s+(G-\d+)\s*[—\-–]\s*(.+?)(?:\n|$)", block)
        if not m:
            continue

        goal_id = m.group(1)
        title = m.group(2).strip()

        prio_m = re.search(r"\*\*Priority:\*\*\s*(\w+)", block, re.IGNORECASE)
        ts_m = re.search(r"\*\*TS:\*\*\s*(TS-\d+)", block, re.IGNORECASE)
        verif_m = re.search(r"\*\*Verification:\*\*\s*(\w+)", block, re.IGNORECASE)
        desc_m = re.search(r"\*\*Description:\*\*\s*(.+?)(?:\n\*\*|\n###|\Z)",
                           block, re.DOTALL | re.IGNORECASE)

        goals.append({
            "id": goal_id,
            "title": title,
            "priority": (prio_m.group(1) if prio_m else "nice").lower(),
            "ts_id": ts_m.group(1) if ts_m else None,
            "verification": (verif_m.group(1) if verif_m else "automated").lower(),
            "description": (desc_m.group(1).strip() if desc_m else ""),
        })

    return goals


def _parse_foundation_test_baseline(path: Path) -> dict:
    """
    Parse FOUNDATION.md §7 (Testing baseline) — returns {runner, e2e_framework,
    coverage_threshold, mock_strategy}.
    """
    out = {
        "runner": None,
        "e2e_framework": None,
        "coverage_threshold": None,
        "mock_strategy": None,
    }
    if not path.exists():
        return out

    text = path.read_text(encoding="utf-8", errors="replace")
    # Section 7 is "## 7. ..." or "### 7 "
    section_m = re.search(
        r"(?:^|\n)#{2,3}\s*(?:7\.?|Testing)\s+[^\n]*\n(.*?)(?:\n#{2,3}\s|\Z)",
        text, re.DOTALL | re.IGNORECASE)
    if not section_m:
        return out
    section = section_m.group(1)

    runner_m = re.search(r"\*\*Runner:\*\*\s*([^\n]+)", section, re.IGNORECASE)
    e2e_m = re.search(r"\*\*E2E[^:]*:\*\*\s*([^\n]+)", section, re.IGNORECASE)
    cov_m = re.search(r"\*\*Coverage[^:]*:\*\*\s*(\d+)\s*%?", section, re.IGNORECASE)
    mock_m = re.search(r"\*\*Mock[^:]*:\*\*\s*([^\n]+)", section, re.IGNORECASE)

    if runner_m:
        out["runner"] = runner_m.group(1).strip().lower().split()[0]
    if e2e_m:
        out["e2e_framework"] = e2e_m.group(1).strip().lower().split()[0]
    if cov_m:
        out["coverage_threshold"] = int(cov_m.group(1))
    if mock_m:
        out["mock_strategy"] = mock_m.group(1).strip()

    return out


def _find_tests_with_marker(ts_id: str, repo_root: Path) -> list[Path]:
    """Grep test files for TS-<N> marker."""
    found = []
    test_globs = [
        "apps/**/test/**/*.py", "apps/**/tests/**/*.py",
        "apps/**/*.spec.ts", "apps/**/*.spec.tsx", "apps/**/*.test.ts",
        "apps/**/e2e/**/*.ts", "apps/**/e2e/**/*.spec.ts",
        "packages/**/test*.py", "packages/**/*.test.ts",
        "tests/**/*.py", "tests/**/*.ts",
    ]
    for pattern in test_globs:
        for path in repo_root.glob(pattern):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                if ts_id in text:
                    found.append(path)
            except OSError:
                continue
    return found


def _count_assertions(path: Path) -> int:
    """Heuristic: count `expect(`, `assert `, `.toBe`, `assertEquals` etc."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    patterns = [
        r"\bexpect\s*\(", r"\bassert\b[\s(]",
        r"\.toBe\b", r"\.toEqual\b", r"\.toHaveBeenCalled",
        r"\bassertEquals\b", r"\bassertTrue\b",
        r"\.should\.", r"\.to\.equal\b",
    ]
    count = 0
    for p in patterns:
        count += len(re.findall(p, text))
    return count


def _is_e2e_path(path: Path) -> bool:
    s = str(path).replace("\\", "/").lower()
    return "/e2e/" in s or s.endswith(".e2e.ts") or s.endswith(".e2e.tsx")


def main() -> int:
    # allow_abbrev=False prevents argparse prefix-match: --phase silently
    # mapping to --phase-dir (defense-in-depth, harness fix 2026-04-26).
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 allow_abbrev=False)
    ap.add_argument("--phase-dir",
                    help="Phase directory path (e.g. .vg/phases/7.14.3-...)")
    ap.add_argument("--phase",
                    help="phase id (e.g. 7.14.3); resolved via find_phase_dir")
    ap.add_argument("--foundation",
                    default="FOUNDATION.md",
                    help="Path to FOUNDATION.md (searched at repo root)")
    ap.add_argument("--min-assertions", type=int, default=2)
    ap.add_argument("--warn-only", action="store_true",
                    help="Gaps warn but exit 0 (default: exit 1 on gaps)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.phase_dir:
        phase_dir = Path(args.phase_dir)
    elif args.phase:
        sys.path.insert(0, str(Path(__file__).parent))
        from _common import find_phase_dir as _find_phase_dir
        resolved = _find_phase_dir(args.phase)
        phase_dir = Path(resolved) if resolved else Path(args.phase)
    else:
        ap.error("must provide --phase or --phase-dir")
        return 2  # unreachable

    if not phase_dir.is_absolute():
        phase_dir = REPO_ROOT / phase_dir
    if not phase_dir.exists():
        print(f"⛔ phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    test_goals_path = phase_dir / "TEST-GOALS.md"
    goals = _parse_test_goals(test_goals_path)

    foundation_path = REPO_ROOT / args.foundation
    if not foundation_path.exists():
        foundation_path = REPO_ROOT / ".vg" / "FOUNDATION.md"
    baseline = _parse_foundation_test_baseline(foundation_path)

    per_goal: list[dict] = []
    gaps: list[dict] = []

    for goal in goals:
        if goal.get("verification") != "automated":
            continue  # manual/deferred — skip
        if goal["priority"] not in ("critical", "important"):
            continue
        ts = goal.get("ts_id")
        if not ts:
            gap = {
                "goal_id": goal["id"],
                "reason": "no TS-XX marker declared",
                "priority": goal["priority"],
            }
            gaps.append(gap)
            per_goal.append({**goal, **gap})
            continue

        test_files = _find_tests_with_marker(ts, REPO_ROOT)
        if not test_files:
            gap = {
                "goal_id": goal["id"],
                "reason": f"no test file references {ts}",
                "priority": goal["priority"],
                "ts_id": ts,
            }
            gaps.append(gap)
            per_goal.append({**goal, **gap})
            continue

        total_assertions = sum(_count_assertions(p) for p in test_files)
        has_e2e = any(_is_e2e_path(p) for p in test_files)

        record = {
            "goal_id": goal["id"],
            "priority": goal["priority"],
            "ts_id": ts,
            "test_files": [str(p.relative_to(REPO_ROOT))
                           for p in test_files],
            "total_assertions": total_assertions,
            "has_e2e_variant": has_e2e,
            "ok": True,
            "issues": [],
        }

        if total_assertions < args.min_assertions:
            record["ok"] = False
            record["issues"].append(
                f"only {total_assertions} assertion(s), required "
                f"{args.min_assertions}"
            )

        if goal["priority"] == "critical" and not has_e2e and \
                re.search(r"\b(flow|user|login|purchase|submit)\b",
                          goal.get("description", ""), re.IGNORECASE):
            record["ok"] = False
            record["issues"].append(
                "critical user-flow goal lacks E2E variant"
            )

        if not record["ok"]:
            gaps.append({**goal, "reason": "; ".join(record["issues"])})
        per_goal.append(record)

    result = {
        "phase_dir": str(phase_dir),
        "baseline": baseline,
        "goals_evaluated": len(per_goal),
        "gaps_count": len(gaps),
        "gaps": gaps,
        "per_goal": per_goal,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if gaps:
            print(f"⚠ Test requirements: {len(gaps)}/{len(per_goal)} "
                  "goals have gaps\n")
            for g in gaps:
                print(f"  [{g.get('priority', 'unknown')}] {g.get('goal_id')}: "
                      f"{g.get('reason')}")
        elif not args.quiet:
            print(f"✓ Test requirements OK — {len(per_goal)} goal(s) evaluated, "
                  "all pass baseline")

    if gaps and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
