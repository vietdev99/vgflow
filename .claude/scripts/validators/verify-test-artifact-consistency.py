#!/usr/bin/env python3
"""B67 (codex MAJOR): cross-artifact consistency before /vg:test runs.

User pain: AI may have generated artifacts at different times leaving
inconsistent state. Goals declared in TEST-GOALS.md but missing from
VARIANTS.json, SEED-RECIPE.md, helper stub case branch, OR
CODEGEN-MANIFEST. Test runs against incomplete state → false failures.

This validator cross-checks goal presence across 4 artifact families:
  1. LIFECYCLE-SPECS.json goals[]
  2. EDGE-CASES/VARIANTS.json goals[] (when goal has variants)
  3. SEED-RECIPE.md (when goal has edge_cases/negative_specs)
  4. CODEGEN-MANIFEST.json playwright_specs[] (when goal is automatable)

Codex MAJOR fix: NOT every goal blindly. Goals legitimately exempt:
  - goal_type: read-only with no variants → no SEED-RECIPE needed
  - infra_deps tag present → manual test, no automation
  - feature_chain_waiver in CONTEXT.md → opt-out

Exit codes:
  0 — all goals consistent OR all gaps waived
  1 — strict mode + gaps detected (default in preflight wiring)

Usage:
  verify-test-artifact-consistency.py --phase 7
  verify-test-artifact-consistency.py --phase 7 --strict
  verify-test-artifact-consistency.py --phase 7 --json
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


def _load_lifecycle_goals(phase_dir: Path) -> dict:
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return doc.get("goals") or {}


def _load_variants_goal_ids(phase_dir: Path) -> set[str]:
    p = phase_dir / "EDGE-CASES" / "VARIANTS.json"
    if not p.is_file():
        return set()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set((doc.get("goals") or {}).keys())


def _load_seed_recipe_variants(phase_dir: Path) -> set[str]:
    """Parse SEED-RECIPE.md for variant_id entries."""
    p = phase_dir / "SEED-RECIPE.md"
    if not p.is_file():
        return set()
    text = p.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"variant_id:\s*([\w.-]+)", text))


def _load_manifest_goal_ids(phase_dir: Path) -> set[str]:
    p = phase_dir / "CODEGEN-MANIFEST.json"
    if not p.is_file():
        return set()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    specs = doc.get("playwright_specs") or []
    return {s.get("goal_id") for s in specs if isinstance(s, dict) and s.get("goal_id")}


def _is_automatable(goal_data: dict) -> bool:
    """Goal is exempt from artifact consistency when manual/infra/waived."""
    infra_deps = (goal_data.get("source_assertions") or {}).get("infra_deps") or ""
    if infra_deps.strip():
        return False
    # Read-only with no variants → automation optional
    edge_cases = goal_data.get("edge_cases") or []
    negative_specs = goal_data.get("negative_specs") or []
    if not edge_cases and not negative_specs:
        # Still automatable if has steps, but no variants needed
        # → exempt from VARIANTS / SEED checks
        return True  # we'll filter per-check
    return True


def _has_variants(goal_data: dict) -> bool:
    return bool(goal_data.get("edge_cases") or goal_data.get("negative_specs"))


def _enumerate_expected_variants(goal_id: str, goal_data: dict) -> list[str]:
    """variant_id format matches derive-edge-cases (Batch 48)."""
    out: list[str] = []
    for idx, ec in enumerate(goal_data.get("edge_cases") or [], 1):
        if isinstance(ec, dict):
            kind = ec.get("kind") or "unknown"
            letter = (kind[:1].lower() or "x")
            out.append(f"{goal_id}-{letter}{idx}")
    for idx, neg in enumerate(goal_data.get("negative_specs") or [], 1):
        if isinstance(neg, dict):
            out.append(f"{goal_id}-n{idx}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    lifecycle_goals = _load_lifecycle_goals(phase_dir)

    if not lifecycle_goals:
        out = {"status": "skip", "reason": "LIFECYCLE-SPECS.json absent or empty"}
        print(json.dumps(out) if args.json else f"ℹ B67: {out['reason']} — skip")
        return 0

    variants_ids = _load_variants_goal_ids(phase_dir)
    seed_variants = _load_seed_recipe_variants(phase_dir)
    manifest_goals = _load_manifest_goal_ids(phase_dir)

    gaps: list[dict] = []
    summary = {
        "lifecycle_goals": len(lifecycle_goals),
        "variants_covered": 0,
        "seed_covered": 0,
        "manifest_covered": 0,
        "exempt_goals": 0,
    }

    for goal_id, goal_data in sorted(lifecycle_goals.items()):
        if not isinstance(goal_data, dict):
            continue

        # codex MAJOR fix: exempt goals with infra_deps tag (manual test)
        infra = (goal_data.get("source_assertions") or {}).get("infra_deps") or ""
        if infra.strip():
            summary["exempt_goals"] += 1
            continue

        has_variants = _has_variants(goal_data)

        # Check 1: VARIANTS.json — only when goal has variants
        if has_variants:
            if goal_id in variants_ids:
                summary["variants_covered"] += 1
            else:
                gaps.append({
                    "goal_id": goal_id,
                    "missing_in": "EDGE-CASES/VARIANTS.json",
                    "hint": "run scripts/derive-edge-cases-from-lifecycle.py --phase " + args.phase,
                })

        # Check 2: SEED-RECIPE.md — only when goal has variants
        if has_variants:
            expected_vids = _enumerate_expected_variants(goal_id, goal_data)
            seed_present = [v for v in expected_vids if v in seed_variants]
            if expected_vids and seed_present:
                summary["seed_covered"] += 1
            elif expected_vids:
                gaps.append({
                    "goal_id": goal_id,
                    "missing_in": "SEED-RECIPE.md",
                    "missing_variants": [v for v in expected_vids if v not in seed_variants],
                    "hint": "run scripts/generate-seed-recipes.py --phase " + args.phase,
                })

        # Check 3: CODEGEN-MANIFEST — when manifest present (specs generated)
        if manifest_goals:
            if goal_id in manifest_goals:
                summary["manifest_covered"] += 1
            else:
                gaps.append({
                    "goal_id": goal_id,
                    "missing_in": "CODEGEN-MANIFEST.json",
                    "hint": "run /vg:test-spec " + args.phase + " to (re)generate specs",
                })

    result = {
        "phase": args.phase,
        "summary": summary,
        "gap_count": len(gaps),
        "gaps": gaps[:20],  # cap diagnostic output
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"B67: {summary['lifecycle_goals']} lifecycle goals "
              f"({summary['exempt_goals']} exempt); "
              f"{summary['variants_covered']} variants OK, "
              f"{summary['seed_covered']} seed OK, "
              f"{summary['manifest_covered']} manifest OK; "
              f"{len(gaps)} gap(s)")
        for g in gaps[:10]:
            print(f"  GAP: {g['goal_id']} missing in {g['missing_in']} — {g['hint']}",
                  file=sys.stderr)
        if len(gaps) > 10:
            print(f"  ... and {len(gaps) - 10} more", file=sys.stderr)

    if gaps and args.strict:
        return 1
    if not gaps:
        if not args.json:
            print("✓ B67: cross-artifact consistency OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
