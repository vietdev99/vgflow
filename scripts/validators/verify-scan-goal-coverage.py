#!/usr/bin/env python3
"""Batch 58: verify every scan signal has matching TEST-GOAL.

enrich-test-goals.py (Phase 2c review) emits G-AUTO-* stubs from
scan-*.json. But:
  1. Human writes TEST-GOALS.md from scratch (skip enrich) → scan
     signals never become goals.
  2. Human edits TEST-GOALS-DISCOVERED.md, deletes G-AUTO-*-filter-X
     stub thinking it's noise → filter X loses goal coverage → no
     spec → silent gap on deploy.
  3. Scanner adds new signal kind (Batch 40-43) without enrich
     enumerating it → drift.

This validator enumerates scan signals per phase and verifies each
has a matching goal (G-* or G-AUTO-*) in TEST-GOALS.md OR
TEST-GOALS-DISCOVERED.md OR LIFECYCLE-SPECS.json goals dict.

Signals checked:
  - filters[].name        → goal id ends with `-filter-{slug}` OR
                            interactive_controls.filters[].name matches
  - sort_headers[].column → goal id ends with `-sort-{slug}`
  - pagination.present    → any goal id ends with `-pagination-*`
  - search[].placeholder  → any goal id ends with `-search-*`
  - state_observations.empty_state.observed → any goal id ends with `-empty-state`
  - state_observations.error_state_4xx.observed → any goal id matches `-error-state-4xx` or `-error-state` (legacy)
  - state_observations.error_state_5xx.observed → any goal id matches `-error-state-5xx` or `-error-state`
  - state_observations.loading_state.observed → any goal id ends with `-loading-state`
  - accessibility_findings → any goal id starts with `-a11y-`

Usage:
  verify-scan-goal-coverage.py --phase 7
  verify-scan-goal-coverage.py --phase 7 --strict
  verify-scan-goal-coverage.py --phase 7 --threshold 1  # warn if >=N gaps
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


GOAL_ID_RE = re.compile(r"\b(G-(?:AUTO-)?[\w.-]+)\b")


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


def _load_goals(phase_dir: Path) -> dict:
    """Aggregate goals from TEST-GOALS.md + TEST-GOALS-DISCOVERED.md +
    LIFECYCLE-SPECS.json.goals.

    Returns: { goal_ids: set, interactive_filter_names: set,
              raw_text: str }
    """
    raw = ""
    goal_ids: set[str] = set()
    filter_names: set[str] = set()
    for fname in ("TEST-GOALS.md", "TEST-GOALS-DISCOVERED.md", "TEST-GOALS-EXPANDED.md"):
        p = phase_dir / fname
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            raw += "\n" + text
            for m in GOAL_ID_RE.findall(text):
                goal_ids.add(m)
            # parse interactive_controls.filters[].name from YAML-ish frontmatter
            for fm in re.finditer(r"name:\s*['\"]?([^'\"\n]+)['\"]?", text):
                filter_names.add(fm.group(1).strip())

    lp = phase_dir / "LIFECYCLE-SPECS.json"
    if lp.is_file():
        try:
            doc = json.loads(lp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            doc = {}
        for gid in (doc.get("goals") or {}):
            goal_ids.add(gid)
            raw += f"\n{gid}"

    return {
        "goal_ids": goal_ids,
        "filter_names": filter_names,
        "raw_text": raw,
    }


def _check_filters(scans: list[dict], goals: dict) -> list[str]:
    gaps: list[str] = []
    for scan in scans:
        view = scan.get("view") or "?"
        for f in scan.get("filters") or []:
            if not isinstance(f, dict):
                continue
            name = (f.get("name") or "").strip()
            if not name:
                continue
            slug = _slug(name)
            # Match: goal id contains `-filter-{slug}` OR name in interactive_controls
            id_match = any(f"-filter-{slug}" in g.lower() for g in goals["goal_ids"])
            name_match = name in goals["filter_names"] or name.lower() in {n.lower() for n in goals["filter_names"]}
            if not id_match and not name_match:
                gaps.append(f"filter '{name}' on {view} has no matching goal")
    return gaps


def _check_sort(scans: list[dict], goals: dict) -> list[str]:
    gaps: list[str] = []
    for scan in scans:
        view = scan.get("view") or "?"
        for s in scan.get("sort_headers") or []:
            if not isinstance(s, dict):
                continue
            col = (s.get("column") or "").strip()
            if not col:
                continue
            slug = _slug(col)
            if not any(f"-sort-{slug}" in g.lower() for g in goals["goal_ids"]):
                gaps.append(f"sort column '{col}' on {view} has no matching goal")
    return gaps


def _check_pagination(scans: list[dict], goals: dict) -> list[str]:
    has_pag = any(
        isinstance(s.get("pagination"), dict) and s["pagination"].get("present")
        for s in scans
    )
    if has_pag and not any(re.search(r"-pagination(-|$)", g.lower()) for g in goals["goal_ids"]):
        return ["pagination present in scan but no -pagination-* goal"]
    return []


def _check_search(scans: list[dict], goals: dict) -> list[str]:
    has_search = any(scan.get("search") for scan in scans)
    if has_search and not any(re.search(r"-search(-|$)", g.lower()) for g in goals["goal_ids"]):
        return ["search present in scan but no -search-* goal"]
    return []


def _check_states(scans: list[dict], goals: dict) -> list[str]:
    gaps: list[str] = []
    has_empty = False
    has_4xx = False
    has_5xx = False
    has_loading = False
    for scan in scans:
        st = scan.get("state_observations") or {}
        if isinstance(st, dict):
            if (st.get("empty_state") or {}).get("observed"):
                has_empty = True
            if (st.get("error_state_4xx") or {}).get("observed"):
                has_4xx = True
            if (st.get("error_state_5xx") or {}).get("observed"):
                has_5xx = True
            if (st.get("loading_state") or {}).get("observed"):
                has_loading = True
    if has_empty and not any("-empty-state" in g.lower() for g in goals["goal_ids"]):
        gaps.append("empty_state observed but no -empty-state goal")
    if has_4xx and not any(
        ("-error-state-4xx" in g.lower() or "-error-state" in g.lower()) for g in goals["goal_ids"]
    ):
        gaps.append("error_state_4xx observed but no -error-state-4xx (or -error-state) goal")
    if has_5xx and not any(
        ("-error-state-5xx" in g.lower() or "-error-state" in g.lower()) for g in goals["goal_ids"]
    ):
        gaps.append("error_state_5xx observed but no -error-state-5xx (or -error-state) goal")
    if has_loading and not any("-loading-state" in g.lower() for g in goals["goal_ids"]):
        gaps.append("loading_state observed but no -loading-state goal")
    return gaps


def _check_a11y(scans: list[dict], goals: dict) -> list[str]:
    has_a11y = any(scan.get("accessibility_findings") for scan in scans)
    if has_a11y and not any("-a11y-" in g.lower() for g in goals["goal_ids"]):
        return ["accessibility_findings present but no -a11y-* goal"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--phase-dir")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any uncovered scan signal")
    ap.add_argument("--threshold", type=int, default=0,
                    help="warn-mode: only fail when >=N gaps (default 0 = all)")
    args = ap.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)

    scans: list[dict] = []
    for scan_file in sorted(phase_dir.glob("scan-*.json")):
        try:
            scans.append(json.loads(scan_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    if not scans:
        print(f"ℹ Batch 58: no scan-*.json in {phase_dir} — skipping")
        return 0

    goals = _load_goals(phase_dir)
    if not goals["goal_ids"]:
        print(f"⛔ Batch 58: no TEST-GOALS / LIFECYCLE-SPECS found — cannot validate coverage",
              file=sys.stderr)
        return 1 if args.strict else 0

    all_gaps: list[str] = []
    all_gaps += _check_filters(scans, goals)
    all_gaps += _check_sort(scans, goals)
    all_gaps += _check_pagination(scans, goals)
    all_gaps += _check_search(scans, goals)
    all_gaps += _check_states(scans, goals)
    all_gaps += _check_a11y(scans, goals)

    print(f"Batch 58: {len(scans)} scan(s), {len(goals['goal_ids'])} goal(s); "
          f"{len(all_gaps)} uncovered signal(s)")
    if all_gaps:
        for g in all_gaps:
            print(f"  GAP: {g}", file=sys.stderr)
        if args.strict and len(all_gaps) > args.threshold:
            return 1
        print(f"⚠ Batch 58: warn-mode (use --strict + --threshold N to BLOCK)",
              file=sys.stderr)
    else:
        print(f"✓ Batch 58: all scan signals covered by goals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
