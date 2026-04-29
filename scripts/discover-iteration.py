#!/usr/bin/env python3
"""
discover-iteration.py — v2.35.0 iterative re-discovery hook.

After Phase 2b-3 (collect+merge), reads `scan-*.json` for each scanned
view and extracts `sub_views_discovered[]`. Compares against
`nav-discovery.json` views — any new view not yet scanned gets queued
for an additional round.

Cap: max 2 iterations, max +5 new views per iteration. Prevents
runaway discovery while still catching links Haiku finds at runtime
that the initial sidebar scan missed.

Outputs:
  - `nav-discovery.json` updated with discovered_iteration field per view
  - `iteration-queue.json` with views to scan in next iteration

Usage:
  discover-iteration.py --phase-dir <path>
  discover-iteration.py --phase-dir <path> --max-iterations 2 --max-new 5
  discover-iteration.py --phase-dir <path> --check  # no mutations, report what would queue

Exit codes:
  0 — iteration queued (or no new views to scan)
  1 — config / IO error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def collect_sub_views(phase_dir: Path) -> set[str]:
    seen: set[str] = set()
    for scan_file in phase_dir.glob("scan-*.json"):
        data = load_json(scan_file)
        for sv in data.get("sub_views_discovered", []) or []:
            if isinstance(sv, str):
                seen.add(sv)
            elif isinstance(sv, dict) and sv.get("url"):
                seen.add(sv["url"])
    return seen


def already_scanned(phase_dir: Path) -> set[str]:
    seen: set[str] = set()
    for scan_file in phase_dir.glob("scan-*.json"):
        data = load_json(scan_file)
        v = data.get("view")
        if v:
            seen.add(v)
    return seen


def known_views(nav_path: Path) -> set[str]:
    nav = load_json(nav_path)
    out: set[str] = set()
    views = nav.get("views") or {}
    if isinstance(views, dict):
        out.update(views.keys())
    elif isinstance(views, list):
        for v in views:
            if isinstance(v, str):
                out.add(v)
            elif isinstance(v, dict) and v.get("url"):
                out.add(v["url"])
    return out


def current_iteration(phase_dir: Path) -> int:
    state_path = phase_dir / "iteration-state.json"
    if not state_path.is_file():
        return 0
    return int(load_json(state_path).get("iteration", 0))


def write_state(phase_dir: Path, iteration: int) -> None:
    state_path = phase_dir / "iteration-state.json"
    state_path.write_text(json.dumps({"iteration": iteration}, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--max-iterations", type=int, default=2)
    ap.add_argument("--max-new", type=int, default=5)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 1

    iter_now = current_iteration(phase_dir)
    nav_path = phase_dir / "nav-discovery.json"

    sub_views = collect_sub_views(phase_dir)
    scanned = already_scanned(phase_dir)
    known = known_views(nav_path)

    candidates = sub_views - scanned - known
    candidates_sorted = sorted(candidates)
    queue = candidates_sorted[: args.max_new]

    payload = {
        "phase_dir": str(phase_dir),
        "current_iteration": iter_now,
        "max_iterations": args.max_iterations,
        "sub_views_total": len(sub_views),
        "already_scanned": len(scanned),
        "known_in_nav": len(known),
        "candidates": candidates_sorted,
        "queue": queue,
        "iteration_queued": False,
        "reason_capped": None,
    }

    if iter_now >= args.max_iterations:
        payload["reason_capped"] = f"max_iterations={args.max_iterations} reached"
    elif not queue:
        payload["reason_capped"] = "no_new_views"
    else:
        payload["iteration_queued"] = True

    if not args.check and payload["iteration_queued"]:
        queue_path = phase_dir / "iteration-queue.json"
        queue_path.write_text(json.dumps({
            "iteration": iter_now + 1,
            "views_to_scan": queue,
        }, indent=2), encoding="utf-8")

        nav = load_json(nav_path)
        if "views" in nav and isinstance(nav["views"], dict):
            for url in queue:
                nav["views"].setdefault(url, {
                    "url": url,
                    "visible_to": [],
                    "denied_for": [],
                    "discovery_role_evidence": {},
                    "discovered_iteration": iter_now + 1,
                    "discovered_via": "sub_views_discovered",
                })
            nav_path.write_text(json.dumps(nav, indent=2), encoding="utf-8")

        write_state(phase_dir, iter_now + 1)

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if payload["iteration_queued"]:
            print(f"✓ Queued iteration {iter_now + 1}: {len(queue)} new view(s)")
            for v in queue:
                print(f"   {v}")
        else:
            print(f"  No iteration queued ({payload['reason_capped']})")
            print(f"  Stats: sub_views={len(sub_views)} scanned={len(scanned)} known={len(known)} candidates={len(candidates_sorted)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
