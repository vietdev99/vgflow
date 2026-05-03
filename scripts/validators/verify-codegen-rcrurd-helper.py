#!/usr/bin/env python3
"""verify-codegen-rcrurd-helper.py — Task 24 codegen-side AST gate.

Per Codex GPT-5.5 review 2026-05-03: regex check is brittle. Better cut:
require generated tests to call a known helper, AND verify each mutation
goal's spec imports/calls that helper.

This gate uses a pragmatic AST-lite check: for each TEST-GOAL with
`goal_type: mutation`, locate the matching `<goal_id>.spec.ts` (by stem
match) and verify it contains BOTH:
  1. `import ... expectReadAfterWrite ... from ...` (helper imported)
  2. `expectReadAfterWrite(...)` call site

This is stronger than mutation-layers.py's regex (which only checks
'reload' + 'API call' presence) because it requires the SPECIFIC helper
that consumes the structured invariant from Task 22.

Future upgrade (P3): full TypeScript AST via ts-morph subprocess — verify
the actual invariant object passed matches Task 22's parsed shape for
that goal. Today's gate is import+call presence.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


IMPORT_RE = re.compile(
    r"import\s+(?:\{[^}]*\bexpectReadAfterWrite\b[^}]*\}|\*\s+as\s+\w+)\s+from\s+['\"][^'\"]+['\"]",
    re.MULTILINE,
)
CALL_RE = re.compile(r"\bexpectReadAfterWrite\s*\(", re.MULTILINE)
GOAL_TYPE_RE = re.compile(r"\*\*goal_type:\*\*\s*(\S+)", re.MULTILINE)


def _is_mutation_goal(goal_path: Path) -> bool:
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return False
    m = GOAL_TYPE_RE.search(text)
    return bool(m and m.group(1).lower() == "mutation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specs-dir", required=True)
    parser.add_argument("--goals-dir", required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()

    specs_dir = Path(args.specs_dir)
    goals_dir = Path(args.goals_dir)
    if not specs_dir.exists():
        print(f"ERROR: specs-dir missing: {specs_dir}", file=sys.stderr)
        return 2
    if not goals_dir.exists():
        print(f"ERROR: goals-dir missing: {goals_dir}", file=sys.stderr)
        return 2

    specs_by_stem: dict[str, Path] = {}
    for spec in specs_dir.rglob("*.spec.ts"):
        specs_by_stem[spec.stem.replace(".spec", "")] = spec

    failures: list[str] = []
    checked = 0
    for goal in sorted(goals_dir.glob("G-*.md")):
        if not _is_mutation_goal(goal):
            continue
        checked += 1
        goal_id = goal.stem
        spec = specs_by_stem.get(goal_id)
        if spec is None:
            failures.append(f"{goal_id}: mutation goal but no matching spec found "
                           f"(looked for {goal_id}.spec.ts in {specs_dir})")
            continue
        try:
            text = spec.read_text(encoding="utf-8")
        except OSError as e:
            failures.append(f"{goal_id}: cannot read spec {spec}: {e}")
            continue
        if not IMPORT_RE.search(text):
            failures.append(f"{goal_id}: spec {spec.name} does not import expectReadAfterWrite")
            continue
        if not CALL_RE.search(text):
            failures.append(f"{goal_id}: spec {spec.name} does not call expectReadAfterWrite()")

    if failures:
        print(f"⛔ codegen RCRURD gate: {len(failures)} mutation goal(s) failed "
              f"(checked {checked}):", file=sys.stderr)
        for f in failures:
            print(f"   - {f}", file=sys.stderr)
        return 1

    print(f"✓ codegen RCRURD gate: {checked} mutation goal(s) all use expectReadAfterWrite()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
