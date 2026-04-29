#!/usr/bin/env python3
"""
verify-crud-runs-coverage.py — v2.35.0 closes #51 invariant 3.

Hard invariant: for every (resource × role) declared in CRUD-SURFACES.md
where `kit: crud-roundtrip`, a corresponding run artifact exists at
`runs/{resource}-{role}.json` with `coverage.attempted >= 1` and every
non-skipped step has `evidence_ref` populated.

Catches AI gaming the verdict gate by writing empty run artifacts.

Usage:
  verify-crud-runs-coverage.py --phase-dir <path>
  verify-crud-runs-coverage.py --phase-dir <path> --severity warn

Exit codes:
  0 — all expected runs present + populated (or severity=warn)
  1 — gap found (severity=block)
  2 — config error (CRUD-SURFACES missing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_crud_surfaces(phase_dir: Path) -> dict:
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    surfaces = load_crud_surfaces(phase_dir)
    resources = surfaces.get("resources") or []
    if not resources:
        if not args.quiet:
            print(f"  (no resources in CRUD-SURFACES.md — passing)")
        return 0

    expected: list[tuple[str, str]] = []
    for resource in resources:
        if resource.get("kit") != "crud-roundtrip":
            continue
        roles = (resource.get("base") or {}).get("roles") or []
        for role in roles:
            expected.append((resource.get("name"), role))

    if not expected:
        if not args.quiet:
            print(f"  (no resources declare kit: crud-roundtrip — passing)")
        return 0

    runs_dir = phase_dir / "runs"
    gaps: list[dict] = []

    for resource_name, role in expected:
        run_path = runs_dir / f"{resource_name}-{role}.json"
        if not run_path.is_file():
            gaps.append({
                "resource": resource_name,
                "role": role,
                "reason": "run_artifact_missing",
                "expected_path": str(run_path),
            })
            continue

        run = load_json(run_path)
        coverage = run.get("coverage") or {}
        if int(coverage.get("attempted", 0)) < 1:
            gaps.append({
                "resource": resource_name,
                "role": role,
                "reason": "coverage_attempted_zero",
                "path": str(run_path),
            })
            continue

        steps = run.get("steps") or []
        for idx, step in enumerate(steps):
            if step.get("status") == "skipped":
                continue
            if not step.get("evidence_ref"):
                gaps.append({
                    "resource": resource_name,
                    "role": role,
                    "reason": "step_missing_evidence_ref",
                    "step_index": idx,
                    "step_name": step.get("name"),
                    "path": str(run_path),
                })
                break

    payload = {
        "phase_dir": str(phase_dir),
        "expected_runs": len(expected),
        "gaps": gaps,
        "gate_pass": len(gaps) == 0,
        "severity": args.severity,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not gaps:
            print(f"✓ CRUD runs coverage OK ({len(expected)} (resource × role) pairs, all populated)")
        else:
            tag = "⛔" if args.severity == "block" else "⚠ "
            print(f"{tag} CRUD runs coverage: {len(gaps)} gap(s)")
            for g in gaps:
                print(f"   {g['resource']} × {g['role']}: {g['reason']}")

    if gaps and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
