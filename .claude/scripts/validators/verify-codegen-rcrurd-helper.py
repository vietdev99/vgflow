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

R8-A (codex audit 2026-05-05): when a goal's invariant declares
`lifecycle: rcrurdr` (full 7-phase Read empty → Create → Read populated →
Update → Read updated → Delete → Read empty), the spec MUST import +
call the more capable `expectLifecycleRoundtrip()` helper which iterates
`lifecycle_phases[]`. The simpler `expectReadAfterWrite()` only verifies
write+1-read so can't close the loop on full-lifecycle goals.

Severity matrix:
  - rcrurdr goal + spec uses expectLifecycleRoundtrip → PASS
  - rcrurdr goal + spec uses only expectReadAfterWrite → BLOCK
  - non-rcrurdr (rcrurd / partial / unset) goal + expectReadAfterWrite → PASS (back-compat)
  - non-rcrurdr goal + expectLifecycleRoundtrip → PASS (helper falls back internally)

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
PAGE_CALL_RE = re.compile(r"\bexpectReadAfterWrite\s*\(\s*page\b", re.MULTILINE)
GOAL_TYPE_RE = re.compile(r"\*\*goal_type:\*\*\s*(\S+)", re.MULTILINE)

# R8-A: full-lifecycle helper (iterates lifecycle_phases[])
LIFECYCLE_IMPORT_RE = re.compile(
    r"import\s+(?:\{[^}]*\bexpectLifecycleRoundtrip\b[^}]*\}|\*\s+as\s+\w+)\s+from\s+['\"][^'\"]+['\"]",
    re.MULTILINE,
)
LIFECYCLE_CALL_RE = re.compile(r"\bexpectLifecycleRoundtrip\s*\(", re.MULTILINE)
LIFECYCLE_PAGE_CALL_RE = re.compile(r"\bexpectLifecycleRoundtrip\s*\(\s*page\b", re.MULTILINE)


def _is_mutation_goal(goal_path: Path) -> bool:
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return False
    m = GOAL_TYPE_RE.search(text)
    return bool(m and m.group(1).lower() == "mutation")


def _load_invariant(goal_path: Path):
    """Return parsed RCRURDInvariant or None on any failure (graceful)."""
    import sys as _sys
    repo = Path(__file__).resolve().parents[2]
    _sys.path.insert(0, str(repo / "scripts" / "lib"))
    try:
        from rcrurd_invariant import extract_from_test_goal_md  # type: ignore
    except ImportError:
        return None
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return extract_from_test_goal_md(text)
    except Exception:
        return None


def _goal_has_ui_assert(goal_path: Path) -> bool:
    """Return True if the YAML invariant in the goal has a ui_assert block (Task 25)."""
    inv = _load_invariant(goal_path)
    return bool(inv and inv.ui_assert)


def _goal_requires_full_lifecycle(goal_path: Path) -> bool:
    """R8-A: True when invariant declares lifecycle: rcrurdr.

    Goals with `lifecycle: rcrurdr` carry a `lifecycle_phases[]` list of
    7 phases (RCRURDR full-lifecycle). The simpler `expectReadAfterWrite`
    only handles a single write+read step and CANNOT close the loop on
    update / delete / cleanup phases. Such goals must use
    `expectLifecycleRoundtrip()` which iterates the phase list.
    """
    inv = _load_invariant(goal_path)
    if inv is None:
        return False
    return getattr(inv, "lifecycle", "rcrurd") == "rcrurdr"


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
    rcrurdr_checked = 0
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

        # R8-A: detect full-lifecycle goals first — these require the
        # capable helper, NOT the simpler one.
        requires_full_lifecycle = _goal_requires_full_lifecycle(goal)
        has_lifecycle_import = bool(LIFECYCLE_IMPORT_RE.search(text))
        has_lifecycle_call = bool(LIFECYCLE_CALL_RE.search(text))
        has_simple_import = bool(IMPORT_RE.search(text))
        has_simple_call = bool(CALL_RE.search(text))

        if requires_full_lifecycle:
            rcrurdr_checked += 1
            if not has_lifecycle_import:
                failures.append(
                    f"{goal_id}: invariant declares lifecycle: rcrurdr but spec "
                    f"{spec.name} does not import expectLifecycleRoundtrip "
                    f"(R8-A — full 7-phase lifecycle requires the capable helper, "
                    f"not expectReadAfterWrite which only verifies write+1-read)"
                )
                continue
            if not has_lifecycle_call:
                failures.append(
                    f"{goal_id}: invariant declares lifecycle: rcrurdr but spec "
                    f"{spec.name} does not call expectLifecycleRoundtrip() "
                    f"(R8-A — needed to iterate lifecycle_phases[])"
                )
                continue
            # ui_assert page check — apply to the lifecycle helper too
            if _goal_has_ui_assert(goal):
                if not LIFECYCLE_PAGE_CALL_RE.search(text):
                    failures.append(
                        f"{goal_id}: invariant has ui_assert but spec {spec.name} doesn't pass "
                        f"`page` to expectLifecycleRoundtrip(...) — R9 ui_render_truth_mismatch needs DOM access"
                    )
            continue

        # Non-rcrurdr path (rcrurd / partial / unset) — back-compat: either
        # helper is acceptable. Prefer expectReadAfterWrite as canonical.
        if not has_simple_import and not has_lifecycle_import:
            failures.append(f"{goal_id}: spec {spec.name} does not import expectReadAfterWrite")
            continue
        if not has_simple_call and not has_lifecycle_call:
            failures.append(f"{goal_id}: spec {spec.name} does not call expectReadAfterWrite()")
            continue
        # Task 25 R9: when goal invariant has ui_assert, spec MUST pass page
        # as the first argument (not just the request context).
        if _goal_has_ui_assert(goal):
            page_ok = bool(PAGE_CALL_RE.search(text)) or bool(LIFECYCLE_PAGE_CALL_RE.search(text))
            if not page_ok:
                failures.append(
                    f"{goal_id}: invariant has ui_assert but spec {spec.name} doesn't pass "
                    f"`page` to expectReadAfterWrite(...) — R9 ui_render_truth_mismatch needs DOM access"
                )

    if failures:
        print(f"⛔ codegen RCRURD gate: {len(failures)} mutation goal(s) failed "
              f"(checked {checked}, rcrurdr_full_lifecycle={rcrurdr_checked}):", file=sys.stderr)
        for f in failures:
            print(f"   - {f}", file=sys.stderr)
        return 1

    print(
        f"✓ codegen RCRURD gate: {checked} mutation goal(s) all use the correct helper "
        f"(rcrurdr_full_lifecycle={rcrurdr_checked} verified via expectLifecycleRoundtrip)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
