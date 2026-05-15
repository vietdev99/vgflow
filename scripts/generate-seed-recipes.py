#!/usr/bin/env python3
"""Batch 51: derive SEED-RECIPE.md per phase from LIFECYCLE-SPECS.

Test specs without seed contract drift at runtime — empty_state test
runs on env with 15 rows, pagination_edge on env with 5 rows, etc.

This generator reads LIFECYCLE-SPECS.json (Batches 36-37) +
state_observations from scan-*.json (Batch 41) and emits per-variant
seed recipes. AI subagent fills concrete SQL/API in a follow-up pass.

Output: ${PHASE_DIR}/SEED-RECIPE.md with one recipe per variant_id.

Schema per recipe:
  - variant_id: G-NN-{kind}{idx}
  - requires_state: human-readable precondition
  - seed_action: <PLACEHOLDER> for AI to fill (SQL/API/CLI)
  - cleanup: <PLACEHOLDER> for AI to fill
  - idempotent: bool (whether re-run is safe)

Usage:
  generate-seed-recipes.py --phase 7
  generate-seed-recipes.py --phase 7 --force
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Map edge_case.kind / negative_spec.kind → seed pattern hint.
KIND_TO_RECIPE = {
    # Edge cases (Batch 37)
    "boundary":          {"req": "field value at min/max boundary",
                          "seed": "<INSERT row with field = boundary value>",
                          "cleanup": "<DELETE seeded row>",
                          "idempotent": True},
    "empty_string":      {"req": "field with empty string for optional field",
                          "seed": "<INSERT row with optional field = ''>",
                          "cleanup": "<DELETE seeded row>",
                          "idempotent": True},
    "unicode_special":   {"req": "field with unicode/emoji/RTL/special chars",
                          "seed": "<INSERT row with field = '包含中文 🎉 العربية'>",
                          "cleanup": "<DELETE seeded row>",
                          "idempotent": True},
    "large_payload":     {"req": "row at max payload size",
                          "seed": "<INSERT row with field = repeat('a', MAX_LENGTH)>",
                          "cleanup": "<DELETE seeded row>",
                          "idempotent": True},
    "filter_combination":{"req": ">=2 rows matching different filter combinations",
                          "seed": "<INSERT 5 rows with varied status+owner combos>",
                          "cleanup": "<DELETE WHERE name LIKE 'seed-filter-%'>",
                          "idempotent": True},
    "pagination_edge":   {"req": ">=31 rows visible to test user (>=2 pages at default page_size=30)",
                          "seed": "<INSERT 35 rows: e.g. INSERT INTO {table} SELECT generate_series(1,35), ...>",
                          "cleanup": "<DELETE WHERE name LIKE 'seed-pag-%'>",
                          "idempotent": True},
    # Negative specs (Batch 37)
    "unauthorized_401":  {"req": "unauthenticated session (no auth cookie/token)",
                          "seed": "page.context().clearCookies()",
                          "cleanup": "none (test re-authenticates via global-setup)",
                          "idempotent": True},
    "forbidden_403":     {"req": "authenticated user lacking required permission",
                          "seed": "<login as role without permission>",
                          "cleanup": "<logout + restore default test role>",
                          "idempotent": True},
    "validation_422":    {"req": "request payload with required field missing/malformed",
                          "seed": "in-test: POST with field={} or field=null",
                          "cleanup": "<DELETE any partial mutation> (usually none if 422 = no write)",
                          "idempotent": True},
    "not_found_404":     {"req": "id that doesn't exist or was deleted",
                          "seed": "use id='99999999-fake-id-probe'",
                          "cleanup": "none",
                          "idempotent": True},
    "rate_limit_429":    {"req": "burst rate above limiter threshold",
                          "seed": "in-test: rapid loop of requests beyond burst_limit",
                          "cleanup": "wait Retry-After seconds before next test",
                          "idempotent": False},
}


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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30]


def _variant_id(goal_id: str, kind: str, idx: int) -> str:
    """Match derive-edge-cases-from-lifecycle.py (Batch 48) format."""
    letter = (kind[:1].lower() or "x")
    return f"{goal_id}-{letter}{idx}"


def _render_recipe_md(phase: str, recipes: list[dict]) -> str:
    lines = [
        f"# SEED-RECIPE — Phase {phase}",
        "",
        f"_Auto-derived by Batch 51 (generate-seed-recipes.py)._",
        f"_Source: LIFECYCLE-SPECS.json edge_cases[] + negative_specs[]._",
        "",
        f"## Purpose",
        "",
        "Each test spec variant (edge case + negative path) requires specific",
        "data state BEFORE running. Without seed contract, specs drift at runtime",
        "— empty_state expects 0 rows but env has 15, pagination_edge expects",
        ">=31 but env has 5, etc.",
        "",
        f"## Recipes ({len(recipes)} variants)",
        "",
        "Codegen subagent MUST read each recipe and wrap matching `test.each(variant)`",
        "with `beforeEach: runSeedRecipe(variant.id)` + `afterEach: cleanup(variant.id)`.",
        "",
        "AI follow-up pass fills `<PLACEHOLDER>` values with project-specific",
        "SQL/API/CLI based on CONTEXT.md, API-CONTRACTS.md, and observed schema.",
        "",
    ]
    for rec in recipes:
        lines.append(f"### {rec['variant_id']}")
        lines.append("")
        lines.append(f"- **goal**: {rec['goal_id']} — {rec.get('goal_title', '')}")
        lines.append(f"- **kind**: `{rec['kind']}` ({rec.get('source', '?')})")
        lines.append(f"- **requires_state**: {rec['requires_state']}")
        lines.append(f"- **idempotent**: {rec['idempotent']}")
        lines.append("")
        lines.append("```yaml")
        lines.append(f"variant_id: {rec['variant_id']}")
        lines.append(f"goal_id: {rec['goal_id']}")
        lines.append(f"kind: {rec['kind']}")
        lines.append(f"requires_state: \"{rec['requires_state']}\"")
        lines.append(f"seed_action: |")
        lines.append(f"  {rec['seed_action']}")
        lines.append(f"cleanup: |")
        lines.append(f"  {rec['cleanup']}")
        lines.append(f"idempotent: {str(rec['idempotent']).lower()}")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def derive_recipes(lifecycle: dict) -> list[dict]:
    """For each goal in LIFECYCLE-SPECS, expand edge_cases + negative_specs."""
    recipes: list[dict] = []
    goals = lifecycle.get("goals") or {}
    for gid, gspec in sorted(goals.items()):
        if not isinstance(gspec, dict):
            continue
        title = gspec.get("title", "")
        # Edge cases (Batch 37)
        for idx, ec in enumerate(gspec.get("edge_cases") or [], 1):
            if not isinstance(ec, dict):
                continue
            kind = ec.get("kind") or "unknown"
            template = KIND_TO_RECIPE.get(kind, {
                "req": ec.get("expected", "(see edge_cases[].expected)"),
                "seed": "<PLACEHOLDER — describe how to reach state>",
                "cleanup": "<PLACEHOLDER>",
                "idempotent": True,
            })
            recipes.append({
                "variant_id": _variant_id(gid, kind, idx),
                "goal_id": gid,
                "goal_title": title,
                "kind": kind,
                "source": "edge_cases",
                "requires_state": template["req"],
                "seed_action": template["seed"],
                "cleanup": template["cleanup"],
                "idempotent": template["idempotent"],
            })
        # Negative specs (Batch 37)
        for idx, neg in enumerate(gspec.get("negative_specs") or [], 1):
            if not isinstance(neg, dict):
                continue
            kind = neg.get("kind") or "unknown"
            template = KIND_TO_RECIPE.get(kind, {
                "req": neg.get("setup", "(see negative_specs[].setup)"),
                "seed": "<PLACEHOLDER>",
                "cleanup": "<PLACEHOLDER>",
                "idempotent": True,
            })
            # Use 'n' prefix for negative variants to distinguish from edge
            variant_id = f"{gid}-n{idx}"
            recipes.append({
                "variant_id": variant_id,
                "goal_id": gid,
                "goal_title": title,
                "kind": kind,
                "source": "negative_specs",
                "requires_state": template["req"],
                "seed_action": template["seed"],
                "cleanup": template["cleanup"],
                "idempotent": template["idempotent"],
            })
    return recipes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    lifecycle_path = phase_dir / "LIFECYCLE-SPECS.json"
    if not lifecycle_path.is_file():
        print(f"⛔ Batch 51: LIFECYCLE-SPECS.json missing at {lifecycle_path}", file=sys.stderr)
        return 1
    try:
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ Batch 51: malformed LIFECYCLE-SPECS.json: {e}", file=sys.stderr)
        return 1

    out_path = phase_dir / "SEED-RECIPE.md"
    if out_path.is_file() and not args.force:
        print(f"ℹ Batch 51: {out_path} exists (use --force to overwrite)")
        return 0

    recipes = derive_recipes(lifecycle)
    if not recipes:
        print(f"ℹ Batch 51: no edge_cases/negative_specs in LIFECYCLE-SPECS — nothing to seed")
        return 0

    body = _render_recipe_md(args.phase, recipes)
    if args.dry_run:
        print(body)
    else:
        out_path.write_text(body, encoding="utf-8")
    print(f"✓ Batch 51: wrote {len(recipes)} seed recipes to {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
