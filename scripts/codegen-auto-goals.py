#!/usr/bin/env python3
"""
codegen-auto-goals.py — v2.34.0 sister to enrich-test-goals.py.

Reads TEST-GOALS-DISCOVERED.md (review-grade auto-goals from runtime
discovery) and emits skeleton Playwright specs:

  ${GENERATED_TESTS_DIR}/auto-{goal-id-slug}.spec.ts

Skeleton specs are intentionally minimal — review-grade stubs that the
test reviewer iterates on. No LLM call (auto-goals don't need deep
codegen; they document what reviewer-Haiku already observed). The file
header references the source goal ID + RUNTIME-MAP scan for
traceability.

Usage:
  codegen-auto-goals.py --phase-dir <path> --out-dir <path>
  codegen-auto-goals.py --phase-dir <path> --out-dir <path> --json
  codegen-auto-goals.py --phase-dir <path> --out-dir <path> --dry-run

Exit codes:
  0 — N specs written (or no auto-goals → 0 specs, exit 0)
  1 — config error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path


def parse_auto_goals(discovered_path: Path) -> list[dict]:
    """Parse TEST-GOALS-DISCOVERED.md for G-AUTO-* goal blocks."""
    if not discovered_path.is_file():
        return []
    text = discovered_path.read_text(encoding="utf-8", errors="replace")

    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore

    goals: list[dict] = []
    if yaml is not None:
        blocks: list[str] = []
        cur: list[str] = []
        in_block = False
        for line in text.splitlines():
            if line.strip() == "---":
                if in_block:
                    blocks.append("\n".join(cur))
                    cur = []
                    in_block = False
                else:
                    in_block = True
                continue
            if in_block:
                cur.append(line)
        for blob in blocks:
            try:
                data = yaml.safe_load(blob) or {}
            except Exception:
                continue
            if isinstance(data, dict) and str(data.get("id", "")).startswith("G-AUTO-"):
                goals.append(data)
    return goals


def goal_to_spec(goal: dict) -> str:
    gid = goal.get("id", "G-AUTO-unknown")
    title = goal.get("title", "")
    priority = goal.get("priority", "important")
    surface = goal.get("surface", "ui")
    source = goal.get("source", "review.runtime_discovery")
    evidence = goal.get("evidence") or {}
    trigger = goal.get("trigger", "")
    main_steps = goal.get("main_steps") or []
    alternate_flows = goal.get("alternate_flows") or []
    postcondition = goal.get("postcondition") or []

    view = evidence.get("view", "/")
    endpoint = evidence.get("endpoint")
    scan_ref = evidence.get("scan_ref")

    desc_safe = title.replace("'", "\\'")
    trigger_safe = trigger.replace("'", "\\'")

    lines: list[str] = []
    lines.append("// AUTO-GENERATED SKELETON — review-grade stub from runtime discovery (v2.34.0+)")
    lines.append(f"// Source: TEST-GOALS-DISCOVERED.md / {source}")
    lines.append(f"// Goal: {gid}")
    lines.append(f"// Title: {title}")
    lines.append(f"// Priority: {priority} | Surface: {surface}")
    if scan_ref:
        lines.append(f"// Scan ref: {scan_ref} on view {view}")
    if endpoint:
        lines.append(f"// Observed endpoint: {endpoint}")
    lines.append("//")
    lines.append("// REVIEWER NOTES:")
    lines.append("// - This is a SKELETON. Flesh out selectors + assertions before treating as regression coverage.")
    lines.append("// - Promote useful auto-goals to TEST-GOALS.md (manual ID) on next /vg:blueprint pass.")
    lines.append("// - Reject false-positives by adding to interactive_controls.exclude in source goal.")
    lines.append("")
    lines.append("import { test, expect } from '@playwright/test';")
    lines.append("")
    lines.append(f"test.describe('{gid} — {desc_safe}', () => {{")
    lines.append(f"  test('{trigger_safe}', async ({{ page }}) => {{")
    lines.append(f"    // Trigger: {trigger}")
    lines.append(f"    await page.goto('{view}');")
    lines.append("")

    if main_steps:
        for step in main_steps:
            for sk, sv in step.items():
                sv_safe = str(sv).replace("'", "\\'")
                lines.append(f"    // {sk}: {sv_safe}")
                lines.append(f"    // TODO: implement step")
                lines.append("")

    if endpoint:
        lines.append("    // Endpoint observation — assert mutation succeeds + persists")
        m = re.match(r"(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", endpoint)
        if m:
            method = m.group(1)
            url = m.group(2).replace("'", "\\'")
            lines.append(f"    // expect API call: {method} {url}")
            lines.append("")

    if alternate_flows:
        lines.append("    // Alternate flows to cover (separate test() blocks recommended):")
        for af in alternate_flows:
            af_name = af.get("name", "")
            af_trigger = af.get("trigger", "").replace("'", "\\'")
            af_expected = af.get("expected", "").replace("'", "\\'")
            lines.append(f"    //   - {af_name}: {af_trigger} → {af_expected}")
        lines.append("")

    if postcondition:
        lines.append("    // Postconditions to assert after success:")
        for pc in postcondition:
            pc_safe = pc.replace("'", "\\'")
            lines.append(f"    //   - {pc_safe}")
        lines.append("")

    lines.append("    // FAIL until reviewer implements")
    lines.append(f"    test.fail();")
    lines.append("  });")
    lines.append("});")
    lines.append("")

    return "\n".join(lines)


def slug(gid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "-", gid.lower()).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--out-dir", required=True,
                    help="GENERATED_TESTS_DIR — usually apps/web/e2e/generated/{phase}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    discovered = phase_dir / "TEST-GOALS-DISCOVERED.md"

    goals = parse_auto_goals(discovered)
    if not goals:
        if args.json:
            print(json.dumps({"specs_written": 0, "reason": "no auto-goals found"}, indent=2))
        elif not args.quiet:
            print(f"  (no TEST-GOALS-DISCOVERED.md auto-goals found at {discovered} — skipping auto codegen)")
        return 0

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for goal in goals:
        gid = goal.get("id", "")
        if not gid.startswith("G-AUTO-"):
            continue
        spec_filename = f"auto-{slug(gid)}.spec.ts"
        spec_path = out_dir / spec_filename
        body = goal_to_spec(goal)
        if args.dry_run:
            written.append(spec_filename)
            continue
        try:
            tmp = spec_path.with_suffix(".ts.tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(spec_path)
            written.append(spec_filename)
        except OSError as e:
            print(f"  ⚠ failed to write {spec_filename}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "specs_written": len(written),
            "auto_goals_processed": len(goals),
            "out_dir": str(out_dir),
            "filenames": written[:20],
        }, indent=2))
    elif not args.quiet:
        print(f"  ✓ Auto-codegen: {len(written)} skeleton spec(s) written to {out_dir}")
        if args.dry_run:
            print("    (dry-run — no files written)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
