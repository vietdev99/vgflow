#!/usr/bin/env python3
"""Batch 56: verify EDGE-CASES/VARIANTS.json schema + coverage.

VARIANTS.json is the machine-readable source-of-truth that codegen
imports for test.each(variants). Schema invariants:

  1. File exists at PHASE_DIR/EDGE-CASES/VARIANTS.json
  2. Top-level: { phase, schema_version, source, goals }
  3. goals: { goal_id: [variant, ...] }
  4. Each variant has required fields:
       variant_id, goal_id, kind, label, source, priority
  5. Every variant_id in LIFECYCLE-SPECS edge_cases/negative_specs
     appears in VARIANTS.json (no drift between derive + lifecycle)
  6. variant_id matches expected format ({goal_id}-{letter}{idx} or
     {goal_id}-n{idx})

Usage:
  verify-variants-json.py --phase 7
  verify-variants-json.py --phase 7 --strict
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = ("variant_id", "goal_id", "kind", "label", "source", "priority")
VARIANT_RE = re.compile(r"^G-[\w.-]+-[a-z]\d+$|^G-[\w.-]+-n\d+$")


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


def _enumerate_lifecycle_variants(lifecycle: dict) -> list[str]:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    variants_path = phase_dir / "EDGE-CASES" / "VARIANTS.json"
    lifecycle_path = phase_dir / "LIFECYCLE-SPECS.json"

    if not lifecycle_path.is_file():
        print(f"ℹ Batch 56: LIFECYCLE-SPECS.json missing — skipping (no variants required)")
        return 0
    try:
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ Batch 56: malformed LIFECYCLE-SPECS.json: {e}", file=sys.stderr)
        return 1

    expected = _enumerate_lifecycle_variants(lifecycle)
    if not expected:
        print(f"ℹ Batch 56: no variants in LIFECYCLE-SPECS — VARIANTS.json optional")
        return 0

    if not variants_path.is_file():
        print(f"⛔ Batch 56: VARIANTS.json missing at {variants_path}", file=sys.stderr)
        print(f"   Run: scripts/derive-edge-cases-from-lifecycle.py --phase {args.phase} --force",
              file=sys.stderr)
        return 1

    try:
        doc = json.loads(variants_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ Batch 56: malformed VARIANTS.json: {e}", file=sys.stderr)
        return 1

    errors: list[str] = []
    if not isinstance(doc.get("goals"), dict):
        errors.append("top-level 'goals' must be object")
    for k in ("phase", "schema_version", "source"):
        if k not in doc:
            errors.append(f"top-level missing required field: {k}")

    seen: set[str] = set()
    for gid, variants in (doc.get("goals") or {}).items():
        if not isinstance(variants, list):
            errors.append(f"goals.{gid}: must be list")
            continue
        for v in variants:
            if not isinstance(v, dict):
                errors.append(f"goals.{gid}: non-dict variant")
                continue
            for f in REQUIRED_FIELDS:
                if f not in v:
                    errors.append(f"goals.{gid} variant missing field: {f}")
            vid = v.get("variant_id", "")
            if vid:
                seen.add(vid)
                if not VARIANT_RE.match(vid):
                    errors.append(f"variant_id format invalid: {vid}")

    missing = [v for v in expected if v not in seen]
    if missing:
        for v in missing[:10]:
            errors.append(f"variant_id in LIFECYCLE but not in VARIANTS.json: {v}")
        if len(missing) > 10:
            errors.append(f"... and {len(missing) - 10} more")

    if errors:
        print(f"⛔ Batch 56: {len(errors)} VARIANTS.json validation errors", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        if args.strict:
            return 1
        print(f"⚠ Batch 56: warn-only (use --strict to BLOCK)", file=sys.stderr)
        return 0

    print(f"✓ Batch 56: VARIANTS.json OK — {len(seen)} variants across {len(doc.get('goals') or {})} goals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
