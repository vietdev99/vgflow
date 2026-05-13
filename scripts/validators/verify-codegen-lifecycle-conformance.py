#!/usr/bin/env python3
"""verify-codegen-lifecycle-conformance.py -- G11 Batch 3

Post-codegen gate: every step in LIFECYCLE-SPECS.json for a goal must be
referenced in the corresponding generated *.spec.ts file. Detects codegen
silently dropping lifecycle stages.

Usage:
  verify-codegen-lifecycle-conformance.py --phase <N> --phase-dir <dir> --spec-dir <dir>

Exit codes:
  0  OK or advisory issues only (default)
  1  BLOCK when --strict flag is passed and issues found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="G11: post-codegen lifecycle conformance gate"
    )
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--spec-dir", required=True, type=Path)
    ap.add_argument("--strict", action="store_true",
                    help="Exit non-zero if conformance issues found (default: advisory)")
    args = ap.parse_args()

    lifecycle_path = args.phase_dir / "LIFECYCLE-SPECS.json"
    if not lifecycle_path.is_file():
        print(
            f"WARN G11: LIFECYCLE-SPECS.json missing at {lifecycle_path} -- skip conformance check"
        )
        return 0

    spec_index: dict[str, str] = {}  # goal_id -> spec text
    if args.spec_dir.is_dir():
        for f in args.spec_dir.glob("*.spec.ts"):
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(r"\b(G-\d+)\b", txt[:2000]):
                gid = m.group(1)
                spec_index[gid] = spec_index.get(gid, "") + "\n" + txt

    issues: list[dict] = []
    try:
        spec = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARN G11: failed to parse LIFECYCLE-SPECS.json: {exc}")
        return 0

    for gid, goal in (spec.get("goals") or {}).items():
        if not isinstance(goal, dict):
            continue
        steps = goal.get("steps") or []
        if not steps:
            continue
        spec_text = spec_index.get(gid, "")
        if not spec_text:
            issues.append({"code": "G11", "goal": gid, "issue": "no generated spec found"})
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            stage = step.get("name") or step.get("stage")
            if not stage:
                continue
            # Heuristic: spec should reference stage name OR endpoint path
            stage_ref = stage in spec_text
            ep = step.get("endpoint") or {}
            ep_ref = bool(ep.get("path") and ep["path"] in spec_text)
            if not stage_ref and not ep_ref:
                issues.append({
                    "code": "G11",
                    "goal": gid,
                    "stage": stage,
                    "issue": (
                        f"generated spec for {gid} does not reference stage '{stage}'"
                        + (f" or its endpoint {ep.get('path')}" if ep.get("path") else "")
                    ),
                })

    if issues:
        print("WARN G11 codegen-lifecycle conformance issues:")
        for i in issues:
            print(f"  - {i}")
        if args.strict:
            return 1
        return 0

    print(f"G11: codegen conformance OK for phase {args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
