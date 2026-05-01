#!/usr/bin/env python3
"""Mark mutation steps lacking structured provenance as legacy_pre_provenance.

RFC v9 D10 migration tool. Walks every .vg/phases/*/RUNTIME-MAP.json and tags
mutation steps (submit-intent click + 2xx network) that lack `step.evidence`
with `step.provenance_status: legacy_pre_provenance`. The provenance validator
treats this tag as informational (cannot trigger matrix promotion) but allows
the phase to ship without re-scanning.

Workflow:
1. Run pre-flight (--dry-run) — see how many steps would be tagged.
2. Run with --apply — atomic rewrite with .bak backup.
3. Configure review.provenance.enforcement: block in vg.config.md.
4. /vg:review {phase} runs cleanly — legacy steps skipped, new steps enforced.
5. Optional: /vg:fixture-backfill {phase} (PR-A.5) generates real recipes
   from the tagged steps so they can be re-scanned with scanner-source
   evidence on the next /vg:review.

Usage:
  scripts/migrate-legacy-provenance.py --dry-run                        # all phases
  scripts/migrate-legacy-provenance.py --phase 3.2 --dry-run            # one phase
  scripts/migrate-legacy-provenance.py --apply                          # commit changes
  scripts/migrate-legacy-provenance.py --apply --no-backup              # skip .bak

Exit:
  0 → success
  1 → I/O or parse error
  2 → unsupported flags
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Mirror provenance validator's mutation detection (kept inline so this
# migration script has no validator dependency).
MUTATION_ACTIONS = {"click", "submit", "tap", "press"}
SUBMIT_VERBS = (
    "submit", "approve", "confirm", "save", "create", "update", "delete",
    "reject", "send", "duyệt", "xác nhận", "gửi", "tạo", "cập nhật",
    "xóa", "từ chối",
)


def is_mutation_step(step: dict) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("do") or step.get("action") or "").lower()
    if action not in MUTATION_ACTIONS:
        return False
    target = " ".join(
        str(step.get(k, "")) for k in ("target", "label", "selector", "name")
    ).lower()
    return any(v in target for v in SUBMIT_VERBS)


def has_2xx_mutation_network(step: dict) -> bool:
    def walk(value):
        if isinstance(value, dict):
            net = value.get("network")
            entries = []
            if isinstance(net, list):
                entries = net
            elif isinstance(net, dict):
                entries = [net]
            for e in entries:
                if not isinstance(e, dict):
                    continue
                method = str(e.get("method") or "").upper()
                status = e.get("status", e.get("status_code"))
                try:
                    code = int(status)
                except (TypeError, ValueError):
                    continue
                if method in {"POST", "PUT", "PATCH", "DELETE"} and 200 <= code < 300:
                    return True
            for v in value.values():
                if walk(v):
                    return True
        elif isinstance(value, list):
            for v in value:
                if walk(v):
                    return True
        return False
    return walk(step)


def find_phases(repo_root: Path, phase_filter: str | None) -> list[Path]:
    phases_dir = repo_root / ".vg" / "phases"
    if not phases_dir.exists():
        return []
    if phase_filter:
        # Mirror find_phase_dir prefix logic: "3.2" matches "03.2-*", "3.2-*", etc.
        zero_padded = phase_filter
        if "." in phase_filter and not phase_filter.split(".")[0].startswith("0"):
            head, _, tail = phase_filter.partition(".")
            zero_padded = f"{head.zfill(2)}.{tail}"
        candidates = []
        for prefix in (phase_filter, zero_padded):
            candidates += sorted(phases_dir.glob(f"{prefix}-*"))
            candidates += sorted(phases_dir.glob(prefix))
        # Dedupe preserving order
        seen = set()
        return [p for p in candidates if not (p in seen or seen.add(p))]
    return sorted([p for p in phases_dir.iterdir() if p.is_dir()])


def process_runtime_map(
    runtime_path: Path,
    apply_changes: bool,
    backup: bool,
) -> dict:
    """Returns stats dict with phase-level counts."""
    stats = {
        "phase": runtime_path.parent.name,
        "total_mutation_steps": 0,
        "already_tagged_legacy": 0,
        "newly_tagged": 0,
        "has_evidence": 0,
        "no_2xx_skipped": 0,
        "errors": [],
    }
    try:
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        stats["errors"].append(f"parse: {e}")
        return stats

    sequences = runtime.get("goal_sequences") or {}
    if not isinstance(sequences, dict):
        return stats

    changed = False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for gid, seq in sequences.items():
        if not isinstance(seq, dict):
            continue
        steps = seq.get("steps") or []
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            if not is_mutation_step(step):
                continue
            if not has_2xx_mutation_network(step):
                stats["no_2xx_skipped"] += 1
                continue
            stats["total_mutation_steps"] += 1
            if step.get("evidence") is not None:
                stats["has_evidence"] += 1
                continue
            if step.get("provenance_status") == "legacy_pre_provenance":
                stats["already_tagged_legacy"] += 1
                continue
            stats["newly_tagged"] += 1
            if apply_changes:
                step["provenance_status"] = "legacy_pre_provenance"
                step["provenance_migrated_at"] = now
                changed = True

    if apply_changes and changed:
        if backup:
            bak = runtime_path.with_suffix(runtime_path.suffix + ".bak")
            bak.write_text(runtime_path.read_text(encoding="utf-8"), encoding="utf-8")
        # Atomic rewrite via temp file + rename
        tmp = runtime_path.with_suffix(runtime_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(runtime, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(runtime_path)

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tag pre-RFC-v9 mutation steps as legacy_pre_provenance",
    )
    ap.add_argument("--phase", help="Single phase (e.g., '3.2'). Default: all phases.")
    ap.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    ap.add_argument("--apply", action="store_true", help="Commit changes")
    ap.add_argument("--no-backup", action="store_true",
                    help="Skip writing .bak alongside RUNTIME-MAP.json")
    ap.add_argument("--repo-root", default=None,
                    help="Override VG_REPO_ROOT / cwd")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must specify --dry-run or --apply")
    if args.dry_run and args.apply:
        ap.error("--dry-run and --apply are mutually exclusive")

    import os
    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

    phases = find_phases(repo, args.phase)
    if not phases:
        print(f"No phases found at {repo / '.vg/phases'} (filter={args.phase or 'none'})",
              file=sys.stderr)
        return 1

    apply_changes = args.apply
    backup = not args.no_backup

    print(f"{'APPLY' if apply_changes else 'DRY-RUN'}: scanning {len(phases)} phase(s)")
    print(f"Repo:   {repo}")
    print(f"Backup: {'yes (.bak)' if backup and apply_changes else 'no'}")
    print()

    grand_totals = {
        "total_mutation_steps": 0,
        "already_tagged_legacy": 0,
        "newly_tagged": 0,
        "has_evidence": 0,
        "no_2xx_skipped": 0,
        "errors": 0,
        "phases_touched": 0,
    }

    for phase_dir in phases:
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not runtime_path.exists():
            continue
        stats = process_runtime_map(runtime_path, apply_changes, backup)
        if stats["errors"]:
            for e in stats["errors"]:
                print(f"  [error] {phase_dir.name}: {e}", file=sys.stderr)
            grand_totals["errors"] += 1
            continue
        if stats["total_mutation_steps"] == 0:
            continue
        grand_totals["phases_touched"] += 1
        print(
            f"{phase_dir.name:50s} "
            f"mutations={stats['total_mutation_steps']:3d} "
            f"evidence={stats['has_evidence']:3d} "
            f"already-legacy={stats['already_tagged_legacy']:3d} "
            f"newly-tagged={stats['newly_tagged']:3d}"
        )
        for k in ("total_mutation_steps", "already_tagged_legacy",
                  "newly_tagged", "has_evidence", "no_2xx_skipped"):
            grand_totals[k] += stats[k]

    print()
    print("─" * 60)
    print(f"Phases touched: {grand_totals['phases_touched']}")
    print(f"Mutation steps: {grand_totals['total_mutation_steps']} total")
    print(f"  Already-tagged legacy:   {grand_totals['already_tagged_legacy']}")
    print(f"  Has structured evidence: {grand_totals['has_evidence']}")
    print(f"  Newly tagged legacy:     {grand_totals['newly_tagged']}")
    print(f"  Errors:                  {grand_totals['errors']}")

    if not apply_changes and grand_totals["newly_tagged"] > 0:
        print()
        print("Re-run with --apply to commit. Add --no-backup to skip .bak files.")

    return 0 if grand_totals["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
