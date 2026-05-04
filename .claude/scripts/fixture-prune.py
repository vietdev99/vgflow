#!/usr/bin/env python3
"""Prune sandbox fixture cache + expired leases (RFC v9 PR-F follow-up).

Two cleanup operations:
1. Reap expired leases — fixture rows where expires_at < now. The lease
   holder either crashed or finished without releasing.
2. Reap orphan cache entries — goals no longer in TEST-GOALS.md (e.g.,
   user removed a goal but FIXTURES-CACHE.json kept the entry).

Designed to run periodically (cron, weekly), at /vg:review entry, or on
demand with `/vg:fixture-prune {phase}`.

Usage:
  scripts/fixture-prune.py --phase 3.2 --dry-run
  scripts/fixture-prune.py --phase 3.2 --apply
  scripts/fixture-prune.py --all-phases --apply --skip-orphans  # leases only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.fixture_cache import (  # noqa: E402
    cache_path,
    load,
    reap_expired_leases,
    reap_orphans,
)


def find_phase_dirs(repo: Path, phase_filter: str | None) -> list[Path]:
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists():
        return []
    if phase_filter:
        zero_padded = phase_filter
        if "." in phase_filter and not phase_filter.split(".")[0].startswith("0"):
            head, _, tail = phase_filter.partition(".")
            zero_padded = f"{head.zfill(2)}.{tail}"
        for prefix in (phase_filter, zero_padded):
            matches = sorted(phases_dir.glob(f"{prefix}-*"))
            if matches:
                return matches
        return []
    return sorted([p for p in phases_dir.iterdir() if p.is_dir()])


def parse_known_goals(phase_dir: Path) -> set[str]:
    test_goals = phase_dir / "TEST-GOALS.md"
    if not test_goals.exists():
        return set()
    text = test_goals.read_text(encoding="utf-8")
    return set(re.findall(r"^##\s+Goal\s+(G-[\w.-]+)", text, re.MULTILINE))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", help="Single phase (e.g., 3.2)")
    ap.add_argument("--all-phases", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-orphans", action="store_true",
                    help="Reap expired leases only; leave orphan cache entries")
    ap.add_argument("--skip-leases", action="store_true",
                    help="Reap orphans only; leave lease ownership untouched")
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must specify --dry-run or --apply")
    if args.dry_run and args.apply:
        ap.error("--dry-run and --apply mutually exclusive")
    if args.skip_orphans and args.skip_leases:
        ap.error("can't skip both — pick at least one cleanup")
    if not args.phase and not args.all_phases:
        ap.error("must specify --phase or --all-phases")

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dirs = find_phase_dirs(repo, args.phase if not args.all_phases else None)
    if not phase_dirs:
        print(f"No phases found at {repo / '.vg/phases'}", file=sys.stderr)
        return 1

    grand_leases = 0
    grand_orphans = 0
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: scanning {len(phase_dirs)} phase(s)")

    for phase_dir in phase_dirs:
        cp = cache_path(phase_dir)
        if not cp.exists():
            continue
        data = load(phase_dir)
        entries = data.get("entries") or {}

        # Count what would be reaped (without mutating)
        expired_count = 0
        orphan_count = 0
        from datetime import datetime, timezone
        now_t = datetime.now(timezone.utc).timestamp()
        for gid, entry in entries.items():
            lease = entry.get("lease") or {}
            try:
                ex_t = datetime.fromisoformat(
                    lease["expires_at"].replace("Z", "+00:00"),
                ).timestamp()
                if ex_t < now_t:
                    expired_count += 1
            except (KeyError, ValueError):
                pass
        known = parse_known_goals(phase_dir)
        if known:
            orphan_count = sum(1 for gid in entries if gid not in known)

        if expired_count == 0 and orphan_count == 0:
            continue

        print(f"  {phase_dir.name:50s} expired_leases={expired_count:3d} orphans={orphan_count:3d}")

        if args.apply:
            if not args.skip_leases:
                grand_leases += reap_expired_leases(phase_dir)
            if not args.skip_orphans and known:
                grand_orphans += reap_orphans(phase_dir, known)

    print()
    if args.apply:
        print(f"Reaped: {grand_leases} expired leases, {grand_orphans} orphan entries")
    else:
        print("Re-run with --apply to commit cleanup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
