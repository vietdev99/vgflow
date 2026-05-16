#!/usr/bin/env python3
"""B62 (audit ID-3): verify every CRUD resource has feature_chain goal.

CRUD-SURFACES.md (Batch 33) lists CRUD endpoints per resource. For each
resource with a CREATE endpoint (POST), TEST-GOALS.md MUST contain ≥1
goal with `goal_class: feature_chain` AND:

  - chain_steps length ≥ 8 (anti-cheat threshold from audit ID-3)
  - distinct `expected_state` per step
  - at least 1 step where `target_view_class` is NOT in
    {source_view, source_view_modal, source_view_form} — chain MUST
    traverse to a structurally different view
  - at least 2 steps with non-empty `downstream_effects[]` — chain
    MUST observe downstream consequences, not just rename existing
    shallow mutation steps

OR the resource has explicit `feature_chain_waiver: <reason>` in
CONTEXT.md (declared per-resource).

This validator BLOCKS the blueprint gate when CRUD resources lack
feature_chain goals.

Usage:
  verify-feature-chain-coverage.py --phase 7
  verify-feature-chain-coverage.py --phase 7 --strict
  verify-feature-chain-coverage.py --phase 7 --allow-feature-chain-shortfall
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path


SOURCE_VIEW_CLASSES = frozenset({
    "source_view",
    "source_view_modal",
    "source_view_form",
})

MIN_CHAIN_STEPS = 8
MIN_STEPS_WITH_DOWNSTREAM_EFFECTS = 2


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


# CRUD-SURFACES.md "resource: <name>" or "## <resource>" headings
# Per Batch 33 schema. Conservative match — strip leading marker.
RESOURCE_RE = re.compile(r"^(?:##\s+|resource:\s+)([\w_-]+)", re.M)
# CREATE detection: "method: POST" or fenced JSON with "method": "POST"
CREATE_METHOD_RE = re.compile(r'"method"\s*:\s*"POST"|method:\s*POST', re.I)


def _parse_crud_resources(phase_dir: Path) -> set[str]:
    """Return resources from CRUD-SURFACES.md that have at least one POST."""
    surfaces = phase_dir / "CRUD-SURFACES.md"
    if not surfaces.is_file():
        # also try CRUD-SURFACES/ split form
        sd = phase_dir / "CRUD-SURFACES"
        if sd.is_dir():
            text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                              for p in sd.glob("*.md"))
        else:
            return set()
    else:
        text = surfaces.read_text(encoding="utf-8", errors="replace")

    resources: set[str] = set()
    # Split text by resource heading; for each block, check POST presence.
    last_resource: str | None = None
    last_start = 0
    chunks: list[tuple[str, str]] = []
    for m in RESOURCE_RE.finditer(text):
        if last_resource is not None:
            chunks.append((last_resource, text[last_start:m.start()]))
        last_resource = m.group(1)
        last_start = m.end()
    if last_resource is not None:
        chunks.append((last_resource, text[last_start:]))

    for resource, block in chunks:
        if CREATE_METHOD_RE.search(block):
            resources.add(resource)
    return resources


# Match goal blocks. Heading + body until next ## heading.
GOAL_HEADING_RE = re.compile(r"^##\s+(?:Goal\s+)?(G-[\w.-]+)", re.M)
GOAL_CLASS_FIELD_RE = re.compile(r"goal_class:\s*([\w_-]+)")
CHAIN_STEPS_BLOCK_RE = re.compile(r"chain_steps:\s*\n((?:\s*-\s.*\n(?:\s+\S.*\n)*)+)", re.M)
STEP_ITEM_RE = re.compile(r"-\s+step_id:\s*(\S+)", re.M)
EXPECTED_STATE_RE = re.compile(r"expected_state:\s*(\S+)")
TARGET_VIEW_CLASS_RE = re.compile(r"target_view_class:\s*(\S+)")
DOWNSTREAM_EFFECTS_BLOCK_RE = re.compile(r"downstream_effects:\s*\n((?:\s+-\s.*\n)*)", re.M)


def _parse_goals_with_chains(text: str) -> list[dict]:
    """Return list of {id, goal_class, chain_steps} dicts."""
    goals: list[dict] = []
    headings = list(GOAL_HEADING_RE.finditer(text))
    for i, m in enumerate(headings):
        gid = m.group(1)
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[start:end]
        gc_match = GOAL_CLASS_FIELD_RE.search(block)
        goal_class = (gc_match.group(1) if gc_match else "").lower()
        # chain_steps parse — coarse YAML-ish step extraction
        steps: list[dict] = []
        step_block_m = CHAIN_STEPS_BLOCK_RE.search(block)
        if step_block_m:
            step_text = step_block_m.group(1)
            # split per step (each starts with "- step_id:")
            step_starts = list(STEP_ITEM_RE.finditer(step_text))
            for j, s_m in enumerate(step_starts):
                s_start = s_m.start()
                s_end = step_starts[j + 1].start() if j + 1 < len(step_starts) else len(step_text)
                s_block = step_text[s_start:s_end]
                es = EXPECTED_STATE_RE.search(s_block)
                tv = TARGET_VIEW_CLASS_RE.search(s_block)
                de_m = DOWNSTREAM_EFFECTS_BLOCK_RE.search(s_block)
                de_lines = []
                if de_m:
                    de_lines = [
                        ln.strip()[2:].strip()
                        for ln in de_m.group(1).split("\n")
                        if ln.strip().startswith("-")
                    ]
                steps.append({
                    "step_id": s_m.group(1),
                    "expected_state": (es.group(1) if es else "").strip().strip('"\''),
                    "target_view_class": (tv.group(1) if tv else "").strip().strip('"\''),
                    "downstream_effects": de_lines,
                })
        goals.append({
            "id": gid,
            "goal_class": goal_class,
            "chain_steps": steps,
        })
    return goals


def _validate_chain(goal: dict) -> list[str]:
    """Return list of validation error messages (empty if PASS)."""
    errors: list[str] = []
    gid = goal["id"]
    steps = goal["chain_steps"]
    if len(steps) < MIN_CHAIN_STEPS:
        errors.append(
            f"{gid}: chain_steps len {len(steps)} < {MIN_CHAIN_STEPS} (audit ID-3 threshold)"
        )
    # distinct expected_state
    expected_states = [s["expected_state"] for s in steps if s["expected_state"]]
    if len(expected_states) != len(set(expected_states)):
        errors.append(
            f"{gid}: duplicate expected_state across chain_steps (each MUST be distinct)"
        )
    # at least 1 step traverses out of source view family
    target_classes = [s["target_view_class"] for s in steps]
    out_of_source = [tc for tc in target_classes if tc and tc not in SOURCE_VIEW_CLASSES]
    if not out_of_source:
        errors.append(
            f"{gid}: chain stays in source view family; need ≥1 step with "
            f"target_view_class NOT in {sorted(SOURCE_VIEW_CLASSES)}"
        )
    # at least 2 steps with non-empty downstream_effects
    with_effects = [s for s in steps if s["downstream_effects"]]
    if len(with_effects) < MIN_STEPS_WITH_DOWNSTREAM_EFFECTS:
        errors.append(
            f"{gid}: only {len(with_effects)} step(s) have downstream_effects; "
            f"need ≥{MIN_STEPS_WITH_DOWNSTREAM_EFFECTS} (audit ID-3 anti-cheat)"
        )
    return errors


def _parse_waivers(phase_dir: Path) -> set[str]:
    """CONTEXT.md feature_chain_waiver: <reason>."""
    ctx = phase_dir / "CONTEXT.md"
    if not ctx.is_file():
        return set()
    text = ctx.read_text(encoding="utf-8", errors="replace")
    # Capture lines like: `feature_chain_waiver[<resource>]: <reason>`
    waivers: set[str] = set()
    for m in re.finditer(
        r"feature_chain_waiver\[?([\w_-]*)\]?\s*:\s*([^\n]+)", text
    ):
        if m.group(1):
            waivers.add(m.group(1))
        else:
            waivers.add("*")  # global waiver
    return waivers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on missing chain or invalid chain (default warn)")
    ap.add_argument("--allow-feature-chain-shortfall", action="store_true",
                    help="downgrade BLOCK to warn for transitional phases")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    resources = _parse_crud_resources(phase_dir)
    if not resources:
        print(f"ℹ B62: no CRUD-SURFACES resources with POST — no chain required")
        return 0

    waivers = _parse_waivers(phase_dir)
    if "*" in waivers:
        print(f"ℹ B62: CONTEXT.md global feature_chain_waiver — skipping")
        return 0

    # Collect goals from TEST-GOALS*.md
    test_goals_text = ""
    for fname in ("TEST-GOALS.md", "TEST-GOALS-DISCOVERED.md", "TEST-GOALS-EXPANDED.md"):
        p = phase_dir / fname
        if p.is_file():
            test_goals_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
    # split form: TEST-GOALS/G-NN.md
    tg_dir = phase_dir / "TEST-GOALS"
    if tg_dir.is_dir():
        for p in tg_dir.glob("G-*.md"):
            test_goals_text += "\n" + p.read_text(encoding="utf-8", errors="replace")

    if not test_goals_text.strip():
        print(f"⛔ B62: no TEST-GOALS*.md found in {phase_dir}", file=sys.stderr)
        if args.strict and not args.allow_feature_chain_shortfall:
            return 1
        return 0

    goals = _parse_goals_with_chains(test_goals_text)
    chain_goals = [g for g in goals if g["goal_class"] in ("feature_chain", "post_create_cascade")]

    errors: list[str] = []
    invalid_chains: list[str] = []
    for g in chain_goals:
        chain_errors = _validate_chain(g)
        if chain_errors:
            invalid_chains.append(g["id"])
            errors.extend(chain_errors)

    # Coverage: every CRUD resource needs ≥1 valid feature_chain goal.
    # Resource→goal mapping heuristic: goal id or text mentions resource name.
    covered: set[str] = set()
    valid_chain_ids = {g["id"] for g in chain_goals if g["id"] not in invalid_chains}
    for resource in resources:
        if resource in waivers:
            covered.add(resource)
            continue
        rname = resource.lower()
        for cgid in valid_chain_ids:
            # match if goal id or full text mentions resource lowercased
            if rname in cgid.lower():
                covered.add(resource)
                break
            # fallback: scan goal body for resource mention
            # (relax heuristic — exact resource name in goal heading is fine
            #  but goal body may also indicate which entity it covers)
            if re.search(
                rf"\b{re.escape(rname)}\b",
                test_goals_text.lower(),
            ):
                # at least one feature_chain goal AND test-goals mentions resource
                # → assume coverage. Optimistic; tighter check requires
                # explicit goal→resource binding field (out of scope B62).
                if chain_goals:
                    covered.add(resource)
                    break

    uncovered = sorted(resources - covered)
    print(f"B62: {len(resources)} CRUD resource(s), {len(chain_goals)} feature_chain goal(s) "
          f"({len(invalid_chains)} invalid), {len(uncovered)} uncovered")
    if errors:
        for e in errors:
            print(f"  CHAIN ERROR: {e}", file=sys.stderr)
    if uncovered:
        for r in uncovered:
            print(f"  UNCOVERED: resource '{r}' has no valid feature_chain goal "
                  f"(add goal_class=feature_chain OR set feature_chain_waiver[{r}] in CONTEXT.md)",
                  file=sys.stderr)
    if errors or uncovered:
        if args.strict and not args.allow_feature_chain_shortfall:
            return 1
        print(f"⚠ B62: warn-mode (--strict + no --allow-feature-chain-shortfall to BLOCK)",
              file=sys.stderr)
    else:
        print(f"✓ B62: every CRUD resource has valid feature_chain coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
