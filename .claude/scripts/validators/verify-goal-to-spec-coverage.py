#!/usr/bin/env python3
"""Batch 39: verify every TEST-GOALS goal has >=1 spec in CODEGEN-MANIFEST.

User complaint: "test cũng không bám theo test specs" — phases ship with
goals lacking corresponding specs. Codegen subagent may skip goals
silently (no error, no spec).

Pipeline gate:
1. Enumerate goals from TEST-GOALS/ or TEST-GOALS.md
2. For each goal_id, check manifest playwright_specs[] has >=1 entry
   with matching goal_id field
3. FAIL listing uncovered goals
4. --strict mode required (default in pipeline)
5. --allow-uncovered comma-list for legacy debt

Usage:
  verify-goal-to-spec-coverage.py --phase 7 --strict
  verify-goal-to-spec-coverage.py --phase 7 --allow-uncovered=G-05,G-12
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

GOAL_ID_RE = re.compile(r"^#+\s*(?:Goal\s+)?(G-[\w.-]+)", re.MULTILINE)
GOAL_FRONTMATTER_RE = re.compile(r"^id:\s*(G-[\w.-]+)", re.MULTILINE)


def _find_phase_dir(phase: str, override: str | None = None) -> Path:
    if override:
        return Path(override)
    for root in (Path(".vg/phases"), Path("dev-phases"), Path("phases")):
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if p.is_dir() and (p.name == phase or p.name.startswith(f"{phase}-")):
                return p
    raise SystemExit(f"phase dir not found for {phase}")


def _parse_goal_ids(phase_dir: Path) -> set[str]:
    """Enumerate all goal IDs in phase TEST-GOALS."""
    ids: set[str] = set()
    # Per-goal split files
    split_dir = phase_dir / "TEST-GOALS"
    if split_dir.is_dir():
        for p in sorted(split_dir.glob("G-*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            for m in GOAL_ID_RE.finditer(text):
                ids.add(m.group(1))
            for m in GOAL_FRONTMATTER_RE.finditer(text):
                ids.add(m.group(1))
    # Flat file
    flat = phase_dir / "TEST-GOALS.md"
    if flat.is_file():
        text = flat.read_text(encoding="utf-8", errors="replace")
        for m in GOAL_ID_RE.finditer(text):
            ids.add(m.group(1))
    return ids


def _covered_goals(phase_dir: Path) -> set[str]:
    """Goals covered by manifest entries (via goal_id field or path stem)."""
    manifest = phase_dir / "CODEGEN-MANIFEST.json"
    if not manifest.is_file():
        return set()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    covered: set[str] = set()
    specs = data.get("playwright_specs") or data.get("specs") or []
    # Path-heuristic regex: G-NN(.NN)? — digits only after dash, optional .NN.
    # Avoid matching "G-01-foo" → "G-01-foo" — we want just "G-01".
    gid_re = re.compile(r"\b(G-\d+(?:\.\d+)*)\b")
    for entry in specs:
        if isinstance(entry, dict):
            gid = entry.get("goal_id") or entry.get("goal")
            if gid:
                covered.add(gid)
            path = entry.get("path", "")
            m = gid_re.search(str(path))
            if m:
                covered.add(m.group(1))
        elif isinstance(entry, str):
            m = gid_re.search(entry)
            if m:
                covered.add(m.group(1))
    return covered


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="FAIL if any goal uncovered (default: warn)")
    ap.add_argument("--allow-uncovered",
                    help="comma-separated goal IDs allowed uncovered")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    goals = _parse_goal_ids(phase_dir)
    if not goals:
        print(f"ℹ Batch 39: no goals found in {phase_dir} — nothing to verify")
        return 0

    covered = _covered_goals(phase_dir)
    allowed = set()
    if args.allow_uncovered:
        allowed = {s.strip() for s in args.allow_uncovered.split(",") if s.strip()}

    uncovered = sorted(goals - covered - allowed)

    print(f"Batch 39: {len(goals)} goals, {len(covered)} covered by manifest, "
          f"{len(uncovered)} uncovered")

    if uncovered:
        for g in uncovered:
            print(f"  uncovered goal: {g}", file=sys.stderr)
        if args.strict:
            print(f"⛔ Batch 39 --strict: {len(uncovered)} goal(s) uncovered", file=sys.stderr)
            return 1
        print(f"⚠ Batch 39: {len(uncovered)} uncovered (warn; use --strict to BLOCK)",
              file=sys.stderr)
    else:
        print(f"✓ Batch 39: all {len(goals)} goals covered by manifest specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
