#!/usr/bin/env python3
"""aggregate_recursive_goals.py — single-writer goal aggregator for Phase 2b-2.5.

Reads runs/goals-*.partial.yaml (written by recursive workers in parallel),
dedupes via canonical key, writes:
- TEST-GOALS-DISCOVERED.md (capped per mode: light=50, deep=150, exhaustive=400)
- recursive-goals-overflow.json (excess goals beyond cap)

Canonical key (sha256[:12]):
    sha256(view | selector_hash | action_semantic | lens | resource | assertion_type)[:12]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

MODE_CAPS = {"light": 50, "deep": 150, "exhaustive": 400}


def canonical_key(g: dict) -> str:
    """Compute canonical sha256[:12] key. Field order matches spec exactly."""
    parts = [
        g.get("view", "") or "",
        g.get("selector_hash", "") or g.get("stable_selector", "") or "",
        g.get("action_semantic", "") or "",
        g.get("lens", "") or "",
        g.get("resource", "") or "",
        g.get("assertion_type", "") or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def render_goal_md(g: dict) -> str:
    return (
        f"## G-RECURSE-{g['_canonical']}\n"
        f"- source: review.recursive_probe\n"
        f"- depth: {g.get('depth', 1)}\n"
        f"- lens: {g.get('lens', '')}\n"
        f"- view: {g.get('view', '')}\n"
        f"- element_class: {g.get('element_class')}\n"
        f"- selector_hash: {g.get('selector_hash')}\n"
        f"- resource: {g.get('resource', '')}\n"
        f"- parent_goal_id: {g.get('parent_goal_id', 'null')}\n"
        f"- priority: {g.get('priority', 'medium')}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Single-writer aggregator for recursive probe goal partials."
    )
    ap.add_argument("--phase-dir", required=True,
                    help="Phase directory containing runs/ subdir with goals-*.partial.yaml")
    ap.add_argument("--mode", choices=list(MODE_CAPS), default="light",
                    help="Recursive mode (controls per-mode cap)")
    ap.add_argument("--output", default=None,
                    help="Path to TEST-GOALS-DISCOVERED.md (append-merge). "
                         "Defaults to <phase-dir>/TEST-GOALS-DISCOVERED.md")
    ap.add_argument("--overflow", default=None,
                    help="Path to overflow JSON. "
                         "Defaults to <phase-dir>/recursive-goals-overflow.json")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    runs_dir = phase_dir / "runs"
    if not runs_dir.is_dir():
        print(f"runs/ missing: {runs_dir}", file=sys.stderr)
        return 1

    seen: dict[str, dict] = {}
    for partial in sorted(runs_dir.glob("goals-*.partial.yaml")):
        try:
            entries = yaml.safe_load(partial.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            print(f"warning: malformed {partial}: {e}", file=sys.stderr)
            continue
        if not isinstance(entries, list):
            print(f"warning: {partial} is not a list (got {type(entries).__name__}); skipping",
                  file=sys.stderr)
            continue
        for g in entries:
            if not isinstance(g, dict):
                continue
            k = canonical_key(g)
            g["_canonical"] = k
            if k not in seen:
                seen[k] = g

    cap = MODE_CAPS[args.mode]
    deduped = list(seen.values())
    main_goals = deduped[:cap]
    overflow_goals = deduped[cap:]

    output = Path(args.output) if args.output else (phase_dir / "TEST-GOALS-DISCOVERED.md")
    overflow_path = Path(args.overflow) if args.overflow else (phase_dir / "recursive-goals-overflow.json")

    section_header = "## Auto-emitted recursive probe goals"
    rendered = "\n".join(render_goal_md(g) for g in main_goals)
    new_section = f"\n\n{section_header}\n\n{rendered}" if rendered else f"\n\n{section_header}\n"

    existing = output.read_text(encoding="utf-8") if output.is_file() else ""
    if section_header not in existing:
        output.write_text(existing + new_section, encoding="utf-8")
    else:
        # Replace existing auto-emitted section, preserving any prior manual content.
        before, _, _ = existing.partition(section_header)
        output.write_text(before.rstrip() + new_section, encoding="utf-8")

    overflow_payload = {
        "mode": args.mode,
        "cap": cap,
        "total": len(deduped),
        "in_main": len(main_goals),
        "goals": [
            {k: v for k, v in g.items() if k != "_canonical"}
            for g in overflow_goals
        ],
    }
    overflow_path.write_text(json.dumps(overflow_payload, indent=2), encoding="utf-8")

    print(
        f"Aggregated {len(deduped)} unique goals: "
        f"{len(main_goals)} -> main, {len(overflow_goals)} -> overflow"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
