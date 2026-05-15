#!/usr/bin/env python3
"""Batch 48 F7: derive EDGE-CASES/G-NN.md from LIFECYCLE-SPECS.json.

Codex F7: blueprint owns EDGE-CASES generation. If blueprint was skipped
or run as legacy (pre-Batch 37), EDGE-CASES/ directory missing → codegen
falls back to single-path specs → edge case coverage absent.

Fix: test-spec auto-derives EDGE-CASES/G-NN.md from LIFECYCLE-SPECS
edge_cases[] (Batch 37 first-class field). One file per goal with
variants flattened to per-variant_id rows.

Usage:
  derive-edge-cases-from-lifecycle.py --phase 7
  derive-edge-cases-from-lifecycle.py --phase 7 --force   # overwrite existing
  derive-edge-cases-from-lifecycle.py --phase 7 --dry-run

Exit codes:
  0 — wrote N files (or all already existed)
  1 — LIFECYCLE-SPECS.json missing/invalid
  2 — no edge_cases data to derive
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30]


def _render_edge_case_md(goal_id: str, goal_spec: dict) -> str:
    title = goal_spec.get("title") or goal_id
    edge_cases = goal_spec.get("edge_cases") or []
    if not edge_cases:
        return ""

    lines = [
        f"# EDGE-CASES — {goal_id}: {title}",
        "",
        f"_Auto-derived from LIFECYCLE-SPECS.json by Batch 48 (F7 closure)._",
        f"_Source: `LIFECYCLE-SPECS.json.goals[{goal_id}].edge_cases[]`._",
        "",
        "## Variants (test.each rows)",
        "",
    ]

    for idx, ec in enumerate(edge_cases, 1):
        if not isinstance(ec, dict):
            continue
        kind = ec.get("kind") or "unknown"
        label = ec.get("label") or kind
        # variant_id format: {goal_id}-{letter}{number} per existing scheme
        # Use first letter of kind + index
        letter = (kind[:1].lower() or "x")
        variant_id = f"{goal_id}-{letter}{idx}"
        input_hint = ec.get("input_hint") or "(no input hint)"
        expected = ec.get("expected") or "(no expected outcome)"
        lines.append(f"### {variant_id} — {label}")
        lines.append("")
        lines.append(f"- **kind**: `{kind}`")
        lines.append(f"- **input_hint**: {input_hint}")
        lines.append(f"- **expected**: {expected}")
        lines.append("")
        lines.append("```yaml")
        lines.append(f"variant_id: {variant_id}")
        lines.append(f"kind: {kind}")
        lines.append(f"label: \"{label}\"")
        lines.append(f"input_hint: \"{input_hint}\"")
        lines.append(f"expected: \"{expected}\"")
        lines.append("priority: important")
        lines.append("```")
        lines.append("")

    lines.append("## Codegen contract")
    lines.append("")
    lines.append(f"Generated spec MUST emit one `test.each([variants])` row per variant_id above.")
    lines.append(f"Each test name MUST cite variant_id (e.g. `test('${goal_id}-b1 — min boundary', ...)`).")
    lines.append(f"verify-edge-coverage gate (delegation.md F.2.5) checks this binding.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--force", action="store_true", help="overwrite existing EDGE-CASES/*.md")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    lifecycle_path = phase_dir / "LIFECYCLE-SPECS.json"
    if not lifecycle_path.is_file():
        print(f"⛔ Batch 48 F7: LIFECYCLE-SPECS.json missing at {lifecycle_path}", file=sys.stderr)
        print(f"   Run /vg:test-spec ${args.phase} first (deep-specs gen).", file=sys.stderr)
        return 1

    try:
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ Batch 48 F7: malformed LIFECYCLE-SPECS.json: {e}", file=sys.stderr)
        return 1

    goals = lifecycle.get("goals") or {}
    if not goals:
        print(f"ℹ Batch 48 F7: no goals in LIFECYCLE-SPECS — nothing to derive", file=sys.stderr)
        return 2

    edge_dir = phase_dir / "EDGE-CASES"
    edge_dir.mkdir(exist_ok=True)

    written = 0
    skipped = 0
    no_edge = 0

    for gid, gspec in sorted(goals.items()):
        if not isinstance(gspec, dict):
            continue
        if not gspec.get("edge_cases"):
            no_edge += 1
            continue
        out_path = edge_dir / f"{gid}.md"
        if out_path.is_file() and not args.force:
            skipped += 1
            continue
        body = _render_edge_case_md(gid, gspec)
        if not body:
            no_edge += 1
            continue
        if args.dry_run:
            print(f"  would write: {out_path.relative_to(phase_dir)}")
        else:
            out_path.write_text(body, encoding="utf-8")
        written += 1

    summary = f"Batch 48 F7: derived {written} EDGE-CASES files"
    if skipped:
        summary += f", {skipped} skipped (exists; use --force)"
    if no_edge:
        summary += f", {no_edge} goals had no edge_cases"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
