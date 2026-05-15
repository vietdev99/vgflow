#!/usr/bin/env python3
"""Batch 52: verify every variant_id in spec body has seed binding.

Codegen subagent should wrap test.each(variant) with beforeEach/afterEach
calling runSeedRecipe/cleanup per Batch 51 SEED-RECIPE.md contract.

This validator scans spec files for variant_id occurrences and checks
each has nearby `runSeedRecipe(` and `cleanup(` calls. Without binding,
test.each runs on undefined state.

Usage:
  verify-spec-seed-binding.py --phase 7
  verify-spec-seed-binding.py --phase 7 --strict
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


VARIANT_RE = re.compile(r"vg-edge-case:\s*(G-[\w.-]+)|test\.each\s*\([^)]*\)\s*\(\s*['\"]?\$\{?(G-[\w.-]+)")
SEED_BIND_RE = re.compile(r"runSeedRecipe\s*\(|/\*\s*seed\s*\*/|//\s*seed recipe", re.I)
CLEANUP_BIND_RE = re.compile(r"\bcleanup\s*\(|/\*\s*cleanup\s*\*/", re.I)


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


def _spec_files(phase_dir: Path) -> list[Path]:
    manifest = phase_dir / "CODEGEN-MANIFEST.json"
    if manifest.is_file():
        try:
            d = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            d = {}
        out: list[Path] = []
        for entry in d.get("playwright_specs") or d.get("specs") or []:
            p = entry.get("path") if isinstance(entry, dict) else str(entry)
            if not p:
                continue
            cand = Path(p) if Path(p).is_absolute() else Path.cwd() / p
            if cand.is_file():
                out.append(cand)
        if out:
            return out
    return list(Path("tests").rglob("*.spec.ts")) + list(Path("apps").rglob("*.spec.ts"))


def _expected_variants(phase_dir: Path) -> list[str]:
    """From LIFECYCLE-SPECS — same logic as generate-seed-recipes.py."""
    lifecycle = phase_dir / "LIFECYCLE-SPECS.json"
    if not lifecycle.is_file():
        return []
    try:
        data = json.loads(lifecycle.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out: list[str] = []
    for gid, gspec in (data.get("goals") or {}).items():
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
    ap.add_argument("--allow-unbound", help="comma list of variant_ids allowed without seed binding")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    expected = _expected_variants(phase_dir)
    if not expected:
        print(f"ℹ Batch 52: no variants in LIFECYCLE-SPECS — nothing to verify")
        return 0

    specs = _spec_files(phase_dir)
    if not specs:
        print(f"⛔ Batch 52: no spec files found", file=sys.stderr)
        return 1

    allowed: set[str] = set()
    if args.allow_unbound:
        allowed = {s.strip() for s in args.allow_unbound.split(",") if s.strip()}

    # Build map variant_id → list of (file, snippet)
    found: dict[str, list[tuple[Path, str]]] = {}
    bound: dict[str, bool] = {}

    for sf in specs:
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Find each variant_id occurrence
        for vid in expected:
            for m in re.finditer(rf"\b{re.escape(vid)}\b", text):
                # Window ±300 chars around occurrence
                start = max(0, m.start() - 300)
                end = min(len(text), m.end() + 600)
                snippet = text[start:end]
                found.setdefault(vid, []).append((sf, snippet))
                if SEED_BIND_RE.search(snippet) and CLEANUP_BIND_RE.search(snippet):
                    bound[vid] = True
                else:
                    bound.setdefault(vid, False)

    missing_from_spec: list[str] = []
    unbound: list[str] = []
    for vid in expected:
        if vid in allowed:
            continue
        if vid not in found:
            missing_from_spec.append(vid)
        elif not bound.get(vid, False):
            unbound.append(vid)

    total_bound = sum(1 for v in bound.values() if v)
    print(f"Batch 52: {len(expected)} variants, {len(found)} in spec, "
          f"{total_bound} with seed+cleanup binding")

    if missing_from_spec:
        for v in missing_from_spec:
            print(f"  variant absent from any spec: {v}", file=sys.stderr)
    if unbound:
        for v in unbound:
            print(f"  variant in spec without seed+cleanup binding: {v}", file=sys.stderr)

    if missing_from_spec or unbound:
        if args.strict:
            return 1
        print(f"⚠ Batch 52: shortfall (warn; --strict to BLOCK)", file=sys.stderr)
    else:
        print(f"✓ Batch 52: all {len(expected)} variants bound to seed recipe in spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
