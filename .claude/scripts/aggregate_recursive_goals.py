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
import re
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


def render_goal_md(g: dict, key: str) -> str:
    # Level-3 heading: nests under the level-2 auto-emitted section,
    # and is visually distinct from manual level-2 sections.
    return (
        f"### G-RECURSE-{key}\n"
        f"- source: review.recursive_probe\n"
        f"- depth: {g.get('depth', 1)}\n"
        f"- lens: {g.get('lens', '')}\n"
        f"- view: {g.get('view', '')}\n"
        f"- element_class: {g.get('element_class') or 'unknown'}\n"
        f"- selector_hash: {g.get('selector_hash') or 'unknown'}\n"
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
    # v2.40 Task 26h — per-tool subdir layout: runs/{gemini,codex,claude}/.
    # Backward-compat: also pick up legacy goals-*.partial.yaml at runs/ root.
    partials = list(runs_dir.glob("goals-*.partial.yaml"))
    partials.extend(runs_dir.glob("*/goals-*.partial.yaml"))
    for partial in sorted(set(partials)):
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
            if k not in seen:
                seen[k] = g  # no mutation: canonical key passed downstream as param

    cap = MODE_CAPS[args.mode]
    deduped_pairs = list(seen.items())
    main_pairs = deduped_pairs[:cap]
    overflow_pairs = deduped_pairs[cap:]

    output = Path(args.output) if args.output else (phase_dir / "TEST-GOALS-DISCOVERED.md")
    overflow_path = Path(args.overflow) if args.overflow else (phase_dir / "recursive-goals-overflow.json")

    section_header = "## Auto-emitted recursive probe goals"
    end_marker = "<!-- end: auto-emitted recursive probe goals -->"
    if main_pairs:
        rendered = "\n".join(render_goal_md(g, k) for k, g in main_pairs)
        new_section = f"\n\n{section_header}\n\n{rendered}\n{end_marker}\n"
    else:
        new_section = f"\n\n{section_header}\n\n{end_marker}\n"

    existing = output.read_text(encoding="utf-8") if output.is_file() else ""
    if section_header not in existing:
        output.write_text(existing + new_section, encoding="utf-8")
    else:
        # Replace only the auto-emitted section, bounded by:
        #   start: `## Auto-emitted recursive probe goals`
        #   end: `<!-- end: auto-emitted recursive probe goals -->` (if present)
        # If the end marker is absent (legacy file pre-marker), fall back to the
        # next level-2 heading that is NOT a script-emitted G-RECURSE entry.
        before, _, after = existing.partition(section_header)
        if end_marker in after:
            _, _, trailing = after.partition(end_marker)
        else:
            # Legacy fallback: skip past any contiguous old G-RECURSE entries
            # (whether emitted as level-2 in v2.40.0-rc1 or level-3 thereafter)
            # by locating the next level-2 heading whose title is not G-RECURSE-.
            m = re.search(r"\n## (?!#)(?!G-RECURSE-)", after)
            trailing = after[m.start():] if m else ""
        output.write_text(before.rstrip() + new_section + trailing, encoding="utf-8")

    overflow_payload = {
        "mode": args.mode,
        "cap": cap,
        "total": len(deduped_pairs),
        "in_main": len(main_pairs),
        "goals": [g for _, g in overflow_pairs],
    }
    overflow_path.write_text(json.dumps(overflow_payload, indent=2), encoding="utf-8")

    print(
        f"Aggregated {len(deduped_pairs)} unique goals: "
        f"{len(main_pairs)} -> main, {len(overflow_pairs)} -> overflow"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
