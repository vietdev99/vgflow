#!/usr/bin/env python3
"""Batch 51: verify every variant_id has SEED-RECIPE entry.

LIFECYCLE-SPECS edge_cases[] + negative_specs[] declare variant_ids.
SEED-RECIPE.md must have matching entry per variant. Without recipe,
codegen subagent can't wrap test.each with beforeEach/afterEach → tests
run on undefined state → drift.

Pipeline gate (after generate-seed-recipes.py):
- Enumerate variant_ids from LIFECYCLE-SPECS
- Parse SEED-RECIPE.md for ```yaml fences with variant_id
- FAIL if any variant lacks recipe
- --strict default; --allow-uncovered=ID1,ID2 legacy escape

Also flags <PLACEHOLDER> values not yet AI-filled (warn only).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


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


def _enumerate_variants(lifecycle: dict) -> list[str]:
    """Return variant_ids in same format as generator."""
    out: list[str] = []
    for gid, gspec in (lifecycle.get("goals") or {}).items():
        if not isinstance(gspec, dict):
            continue
        for idx, ec in enumerate(gspec.get("edge_cases") or [], 1):
            if isinstance(ec, dict):
                kind = ec.get("kind") or "unknown"
                letter = (kind[:1].lower() or "x")
                out.append(f"{gid}-{letter}{idx}")
        for idx, neg in enumerate(gspec.get("negative_specs") or [], 1):
            if isinstance(neg, dict):
                out.append(f"{gid}-n{idx}")
    return out


VARIANT_IN_RECIPE_RE = re.compile(r"variant_id:\s*([\w.-]+)")
PLACEHOLDER_RE = re.compile(r"<PLACEHOLDER")


def _recipe_variant_ids(text: str) -> set[str]:
    return set(VARIANT_IN_RECIPE_RE.findall(text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="FAIL if any variant uncovered (default mode in test-spec)")
    ap.add_argument("--allow-uncovered", help="comma-separated variant_ids OK to skip")
    ap.add_argument("--allow-placeholders", action="store_true",
                    help="don't warn on <PLACEHOLDER> values (AI hasn't filled yet)")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    lifecycle_path = phase_dir / "LIFECYCLE-SPECS.json"
    recipe_path = phase_dir / "SEED-RECIPE.md"

    if not lifecycle_path.is_file():
        print(f"⛔ LIFECYCLE-SPECS.json missing at {lifecycle_path}", file=sys.stderr)
        return 1
    try:
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ malformed LIFECYCLE-SPECS.json: {e}", file=sys.stderr)
        return 1

    variants = _enumerate_variants(lifecycle)
    if not variants:
        print(f"ℹ no variants in LIFECYCLE-SPECS — no recipes required")
        return 0

    if not recipe_path.is_file():
        print(f"⛔ Batch 51: SEED-RECIPE.md missing at {recipe_path}", file=sys.stderr)
        print(f"   Run: scripts/generate-seed-recipes.py --phase {args.phase}", file=sys.stderr)
        return 1

    text = recipe_path.read_text(encoding="utf-8")
    covered = _recipe_variant_ids(text)
    allowed: set[str] = set()
    if args.allow_uncovered:
        allowed = {s.strip() for s in args.allow_uncovered.split(",") if s.strip()}

    missing = [v for v in variants if v not in covered and v not in allowed]
    placeholder_count = len(PLACEHOLDER_RE.findall(text))

    print(f"Batch 51: {len(variants)} variants, {len(covered)} covered by recipe, "
          f"{len(missing)} missing")
    if placeholder_count > 0 and not args.allow_placeholders:
        print(f"⚠ Batch 51: {placeholder_count} <PLACEHOLDER> values not yet AI-filled",
              file=sys.stderr)

    if missing:
        for v in missing:
            print(f"  missing recipe: {v}", file=sys.stderr)
        if args.strict:
            return 1
        print(f"⚠ Batch 51: {len(missing)} uncovered variants (warn; --strict to BLOCK)",
              file=sys.stderr)
    else:
        print(f"✓ Batch 51: all {len(variants)} variants have seed recipes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
