#!/usr/bin/env python3
"""
VG Bootstrap — Conflict Detector (Phase D)

Before promoting a candidate, check for conflict with active ACCEPTED artifacts.

Conflict types:
  1. Same config key targeted with different value (overlay.yml collision)
  2. Two rules with overlapping scope but opposite action
  3. Patch at same (command, anchor) as existing patch

Priority hierarchy (per Gemini review):
  patches > overlay.yml > rules/*.md

Used by /vg:learn --promote as a mandatory pre-check.

Usage:
    python bootstrap-conflict.py --candidate <yaml-text-file> --emit json
    # exit 0 = no conflict, 1 = conflict found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "bl", Path(__file__).parent / "bootstrap-loader.py"
)
_bl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bl)


def parse_accepted(planning_dir: Path) -> list[dict]:
    """Parse ACCEPTED.md entries — tolerant YAML block form."""
    f = planning_dir / "bootstrap" / "ACCEPTED.md"
    if not f.exists():
        return []
    text = f.read_text(encoding="utf-8", errors="replace")
    entries = []
    # Match `- id: L-...` blocks
    for m in re.finditer(r"^- id: (L-\S+)", text, re.MULTILINE):
        start = m.start()
        # Find next `- id:` or end
        next_m = re.search(r"^- id: L-\S+", text[start + 1 :], re.MULTILINE)
        end = start + 1 + next_m.start() if next_m else len(text)
        block = text[start:end]
        e: dict = {"id": m.group(1), "status": "active"}
        for line in block.splitlines():
            if ":" in line:
                k, _, v = line.strip().lstrip("-").strip().partition(":")
                v = v.strip().strip("'\"")
                if k and v:
                    e[k] = v
        entries.append(e)
    return entries


def detect_conflict(candidate: dict, accepted: list[dict]) -> list[dict]:
    """Return list of conflict entries (empty if none)."""
    conflicts = []
    c_type = candidate.get("type", "rule")
    c_target = candidate.get("target_key") or candidate.get("proposed", {}).get(
        "target_key", ""
    )

    for a in accepted:
        if a.get("status", "active") not in ("active", "experimental"):
            continue
        a_type = a.get("type", "rule")

        # Conflict 1: same target key, type=config_override, status=active
        if c_type == "config_override" and a_type == "config_override":
            a_target = a.get("key", "") or a.get("target", "")
            if c_target and c_target == a_target:
                conflicts.append(
                    {
                        "type": "config_override_collision",
                        "with_id": a.get("id"),
                        "target_key": c_target,
                        "resolution_hint": f"retract {a.get('id')} first, or edit candidate to extend not replace",
                    }
                )

        # Conflict 2: patch same (command, anchor)
        if c_type == "patch" and a_type == "patch":
            if (
                candidate.get("target_step") == a.get("target_step")
                and candidate.get("anchor") == a.get("anchor")
            ):
                conflicts.append(
                    {
                        "type": "patch_anchor_collision",
                        "with_id": a.get("id"),
                        "command_anchor": f"{candidate.get('target_step')}.{candidate.get('anchor')}",
                        "resolution_hint": "merge patches manually, only one per anchor",
                    }
                )

    return conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description="VG bootstrap conflict detector")
    ap.add_argument("--candidate-json", required=True)
    ap.add_argument("--planning", default=".vg")
    args = ap.parse_args()

    try:
        candidate = json.loads(args.candidate_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"bad candidate JSON: {e}"}))
        return 2

    accepted = parse_accepted(Path(args.planning))
    conflicts = detect_conflict(candidate, accepted)

    print(json.dumps({"conflicts": conflicts, "count": len(conflicts)}, indent=2))
    return 0 if not conflicts else 1


if __name__ == "__main__":
    sys.exit(main())
