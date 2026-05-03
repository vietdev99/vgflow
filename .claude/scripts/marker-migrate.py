#!/usr/bin/env python3
"""
marker-migrate.py — OHOK Batch 5b (E1) — one-time migration of legacy markers.

Before Batch 5b: `.step-markers/*.done` files were empty (produced by `touch`).
After:  each marker contains `v1|{phase}|{step}|{git_sha}|{iso_ts}|{run_id}`.

This script rewrites existing empty markers with synthetic content so post-5b
contract validators don't BLOCK legitimate pre-5b phases. Run once per project:

    python3 .claude/scripts/marker-migrate.py --planning .vg
    python3 .claude/scripts/marker-migrate.py --planning .vg --dry-run

Strategy per marker:
- phase: extracted from path (e.g. .vg/phases/13-foo/.step-markers/build.done → "13")
- step:  marker filename stem (build.done → "build")
- git_sha: current HEAD (best guess; caveat: not ancestor of the step's actual commit)
- iso_ts: current time (documented as migration timestamp)
- run_id: "legacy-migration-{date}"

Non-destructive: skips markers that already have content (idempotent).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "v1"


def _git_head(repo: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip() or "nogit"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "nogit"


def _extract_phase(marker_path: Path, planning_root: Path) -> str:
    """Extract phase number from marker path.

    Expected layout: ${planning}/phases/{phase}-{slug}/.step-markers/{step}.done
    Returns 'unknown' if layout doesn't match.
    """
    try:
        rel = marker_path.relative_to(planning_root)
    except ValueError:
        return "unknown"
    parts = rel.parts
    # parts = ("phases", "{phase}-{slug}", ".step-markers", "{step}.done")
    if len(parts) >= 2 and parts[0] == "phases":
        phase_dir_name = parts[1]
        m = re.match(r"^([0-9]+(?:\.[0-9]+)*)-", phase_dir_name)
        if m:
            return m.group(1)
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--planning", default=".vg",
                    help="planning root (default .vg)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report changes without writing")
    ap.add_argument("--run-id",
                    default=f"legacy-migration-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    help="run_id field value")
    args = ap.parse_args()

    planning = Path(args.planning).resolve()
    if not planning.exists():
        print(f"ERROR: planning dir missing: {planning}", file=sys.stderr)
        return 1

    repo = Path.cwd()
    git_sha = _git_head(repo)
    iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    markers = list(planning.glob("phases/*/.step-markers/*.done"))
    migrated = 0
    already_content = 0
    skipped_unknown = 0

    for mp in markers:
        # Skip if already has content
        try:
            existing = mp.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            existing = ""
        if existing:
            already_content += 1
            continue

        phase = _extract_phase(mp, planning)
        if phase == "unknown":
            skipped_unknown += 1
            continue

        step = mp.stem  # filename without .done
        content = f"{SCHEMA}|{phase}|{step}|{git_sha}|{iso_ts}|{args.run_id}\n"

        if args.dry_run:
            print(f"DRY-RUN: {mp} → {content.rstrip()}")
        else:
            try:
                mp.write_text(content, encoding="utf-8")
            except OSError as e:
                print(f"ERROR writing {mp}: {e}", file=sys.stderr)
                continue
        migrated += 1

    print(f"Summary: {migrated} migrated, {already_content} already had content, "
          f"{skipped_unknown} skipped (unknown phase), "
          f"total scanned={len(markers)}")
    if args.dry_run:
        print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
