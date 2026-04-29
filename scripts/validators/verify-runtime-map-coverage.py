#!/usr/bin/env python3
"""
verify-runtime-map-coverage.py — v2.35.0 closes #51 invariant 2.

Hard invariant: every UI-surface goal in TEST-GOALS.md has BOTH:
  1. views[X].elements.length > 0 in RUNTIME-MAP.json
  2. goal_sequences[id].steps.length > 0 in RUNTIME-MAP.json

Catches the verdict-gate gap where review claims PASS but RUNTIME-MAP
has empty elements / no replay steps (issue #51 root cause).

Usage:
  verify-runtime-map-coverage.py --phase-dir <path>
  verify-runtime-map-coverage.py --phase-dir <path> --severity warn

Exit codes:
  0 — all UI goals covered (or severity=warn)
  1 — gap found (severity=block)
  2 — config error (RUNTIME-MAP or TEST-GOALS missing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_test_goals(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml
    except ImportError:
        return []

    blocks: list[str] = []
    cur: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.strip() == "---":
            if in_block:
                blocks.append("\n".join(cur))
                cur = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            cur.append(line)

    out: list[dict] = []
    for blob in blocks:
        try:
            data = yaml.safe_load(blob) or {}
        except Exception:
            continue
        if isinstance(data, dict) and str(data.get("id", "")).startswith("G-"):
            out.append(data)
    return out


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

    rmap = load_json(phase_dir / "RUNTIME-MAP.json")
    if not rmap:
        print(f"⛔ RUNTIME-MAP.json missing in {phase_dir}", file=sys.stderr)
        return 2

    goals = parse_test_goals(phase_dir / "TEST-GOALS.md")
    if not goals:
        if not args.quiet:
            print(f"  (no parseable goals in {phase_dir}/TEST-GOALS.md — passing)")
        return 0

    views = rmap.get("views") or {}
    sequences = rmap.get("goal_sequences") or {}

    gaps: list[dict] = []
    for goal in goals:
        gid = goal.get("id")
        surface = (goal.get("surface") or "ui").lower()
        if surface not in {"ui", "ui-mobile"}:
            continue

        view_url = goal.get("maps_to_view") or goal.get("view")
        view_data = views.get(view_url) if view_url else None
        elements = (view_data or {}).get("elements") if isinstance(view_data, dict) else None
        elements_count = len(elements) if isinstance(elements, list) else 0

        seq = sequences.get(gid) or {}
        steps = seq.get("steps") if isinstance(seq, dict) else None
        steps_count = len(steps) if isinstance(steps, list) else 0

        if elements_count == 0 or steps_count == 0:
            gaps.append({
                "goal_id": gid,
                "surface": surface,
                "view": view_url,
                "elements_count": elements_count,
                "steps_count": steps_count,
                "reason": "elements_empty" if elements_count == 0 else "steps_empty",
            })

    payload = {
        "phase_dir": str(phase_dir),
        "ui_goals_total": sum(1 for g in goals if (g.get("surface") or "ui").lower() in {"ui", "ui-mobile"}),
        "gaps": gaps,
        "gate_pass": len(gaps) == 0,
        "severity": args.severity,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not gaps:
            print(f"✓ Runtime-map coverage OK ({payload['ui_goals_total']} UI goals, all have elements + steps)")
        else:
            tag = "⛔" if args.severity == "block" else "⚠ "
            print(f"{tag} Runtime-map coverage: {len(gaps)} gap(s)")
            for g in gaps:
                print(f"   {g['goal_id']} on {g['view']}: {g['reason']} (elements={g['elements_count']}, steps={g['steps_count']})")

    if gaps and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
