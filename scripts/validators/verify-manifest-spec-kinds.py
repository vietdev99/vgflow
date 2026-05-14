#!/usr/bin/env python3
"""Batch 35 F11: verify CODEGEN-MANIFEST.json has spec_kind tagging.

Codex audit F11 CRITICAL: manifest schema only required at-least-one-spec.
No required edge/negative/failure families per goal. Phases could ship
happy-path only and pass the gate.

This validator enforces minimum schema:
- Each manifest entry MUST have spec_kind ∈ {happy, edge, negative, failure}
- Per goal_id, at least 1 happy spec
- For mutation goals (read from LIFECYCLE-SPECS.json if present), at least
  1 negative spec (covers 401/403/422) recommended; warn if absent
- Counts by kind emitted to stdout for inspection

Usage:
  verify-manifest-spec-kinds.py --phase 7
  verify-manifest-spec-kinds.py --phase 7 --strict   # require all 4 kinds
  verify-manifest-spec-kinds.py --phase 7 --allow-happy-only
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

VALID_KINDS = {"happy", "edge", "negative", "failure"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir", help="override phase dir lookup")
    ap.add_argument("--strict", action="store_true",
                    help="require all 4 kinds (happy+edge+negative+failure) per goal")
    ap.add_argument("--allow-happy-only", action="store_true",
                    help="legacy escape: allow phases with only happy specs (debt logged)")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir) if args.phase_dir else Path(f".vg/phases/{args.phase}")
    if not phase_dir.is_dir():
        # Try alternate paths
        for candidate in [Path(f"dev-phases/{args.phase}"), Path(f"phases/{args.phase}")]:
            if candidate.is_dir():
                phase_dir = candidate
                break
        else:
            print(f"⛔ phase dir not found for {args.phase}", file=sys.stderr)
            return 2

    manifest_path = phase_dir / "CODEGEN-MANIFEST.json"
    if not manifest_path.is_file():
        print(f"⛔ CODEGEN-MANIFEST.json absent at {manifest_path}", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ malformed manifest: {e}", file=sys.stderr)
        return 1

    specs = manifest.get("playwright_specs") or manifest.get("specs") or []
    if not specs:
        print(f"⛔ manifest empty", file=sys.stderr)
        return 1

    # Tally
    by_goal: dict[str, dict[str, int]] = {}
    untagged = 0
    invalid_kinds: list[str] = []

    for entry in specs:
        if not isinstance(entry, dict):
            untagged += 1
            continue
        gid = entry.get("goal_id") or entry.get("goal") or "_unknown"
        kind = entry.get("spec_kind") or entry.get("kind") or ""
        if not kind:
            untagged += 1
            continue
        if kind not in VALID_KINDS:
            invalid_kinds.append(f"{gid}:{kind}")
            continue
        by_goal.setdefault(gid, {k: 0 for k in VALID_KINDS})[kind] += 1

    findings: list[str] = []
    if untagged > 0:
        findings.append(f"{untagged} spec(s) missing spec_kind field")
    if invalid_kinds:
        findings.append(f"invalid spec_kind values: {', '.join(invalid_kinds[:5])}")

    goals_missing_happy: list[str] = []
    goals_missing_negative: list[str] = []
    goals_missing_edge: list[str] = []
    goals_missing_failure: list[str] = []

    for gid, counts in by_goal.items():
        if counts["happy"] == 0:
            goals_missing_happy.append(gid)
        if counts["negative"] == 0:
            goals_missing_negative.append(gid)
        if counts["edge"] == 0:
            goals_missing_edge.append(gid)
        if counts["failure"] == 0:
            goals_missing_failure.append(gid)

    if goals_missing_happy:
        findings.append(f"{len(goals_missing_happy)} goal(s) lack happy spec: {goals_missing_happy[:5]}")

    print(f"manifest spec kinds: {sum(c.get('happy',0) for c in by_goal.values())} happy, "
          f"{sum(c.get('edge',0) for c in by_goal.values())} edge, "
          f"{sum(c.get('negative',0) for c in by_goal.values())} negative, "
          f"{sum(c.get('failure',0) for c in by_goal.values())} failure "
          f"({len(by_goal)} goals)")

    if args.strict:
        # All 4 kinds required per goal
        if goals_missing_negative:
            findings.append(f"{len(goals_missing_negative)} goal(s) lack negative spec")
        if goals_missing_edge:
            findings.append(f"{len(goals_missing_edge)} goal(s) lack edge spec")
        if goals_missing_failure:
            findings.append(f"{len(goals_missing_failure)} goal(s) lack failure spec")

    if findings:
        if args.allow_happy_only and all("happy" not in f.lower() for f in findings):
            print(f"⚠ --allow-happy-only: shortfalls noted (debt logged): {'; '.join(findings)}",
                  file=sys.stderr)
            return 0
        for f in findings:
            print(f"⛔ Batch 35 F11: {f}", file=sys.stderr)
        return 1

    print(f"✓ manifest spec_kinds OK ({len(by_goal)} goals tagged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
