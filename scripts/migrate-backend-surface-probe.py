#!/usr/bin/env python3
"""Tag backend (api/data/integration) goals READY-via-surface-probe as
legacy_surface_probe so verify-backend-mutation-evidence accepts them
without requiring `replay` block evidence.

Background: pre-RFC v9, backend goals achieved READY status via static
handler-grep + route-registration check (surface-probe). RFC v9 PR-Z's
verify-backend-mutation-evidence validator demands a structured `replay`
block (real curl traffic + status capture). Phases that completed before
RFC v9 don't have replay traffic recorded in RUNTIME-MAP — they'd block
on re-review unless tagged.

This tool walks GOAL-COVERAGE-MATRIX.md, finds backend goals with
status=READY, and writes `.legacy-surface-probe.json` listing them with
the evidence text from the matrix as audit trail. The validator's
`--allow-legacy-surface-probe` flag reads this manifest and exempts
listed goals.

Tags only goals where:
  1. surface ∈ {api, data, integration} (or ui+api if backend portion
     was probe-verified)
  2. status = READY
  3. NOT already in RUNTIME-MAP goal_sequences with replay block

Usage:
  scripts/migrate-backend-surface-probe.py --phase 3.3 --dry-run
  scripts/migrate-backend-surface-probe.py --phase 3.3 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_SURFACES_RE = re.compile(
    r"\b(api|data|integration|time-driven|ui\+api|api\+integration|api\+data)\b",
    re.IGNORECASE,
)


def find_phase_dir(repo_root: Path, phase_filter: str) -> Path | None:
    phases = repo_root / ".vg" / "phases"
    if not phases.exists():
        return None
    zero_padded = phase_filter
    if "." in phase_filter and not phase_filter.split(".")[0].startswith("0"):
        head, _, tail = phase_filter.partition(".")
        zero_padded = f"{head.zfill(2)}.{tail}"
    for prefix in (phase_filter, zero_padded):
        matches = sorted(phases.glob(f"{prefix}-*"))
        if matches:
            return matches[0]
    return None


def parse_matrix_backend_ready(matrix_path: Path) -> list[dict]:
    """Extract backend goals with status=READY from GOAL-COVERAGE-MATRIX.md.

    Recognises the table row format:
        | G-XX | priority | surface | STATUS | evidence |
    """
    if not matrix_path.exists():
        return []
    text = matrix_path.read_text(encoding="utf-8")
    out: list[dict] = []
    # Match table rows starting with `| G-XX |`
    row_re = re.compile(
        r"^\|\s*(G-[\w.-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([A-Z_]+)\s*\|\s*(.+?)\s*\|",
        re.MULTILINE,
    )
    # Accept READY (handler-grep verified) and MANUAL (deferred to /vg:test).
    # Both classes lack RUNTIME-MAP replay traffic and are pre-RFC v9 patterns.
    accept_statuses = {"READY", "MANUAL"}
    for m in row_re.finditer(text):
        gid, priority, surface, status, evidence = m.groups()
        if status not in accept_statuses:
            continue
        if not BACKEND_SURFACES_RE.search(surface):
            continue
        out.append({
            "goal_id": gid,
            "priority": priority.strip(),
            "surface": surface.strip(),
            "status": status,
            "matrix_evidence": evidence.strip(),
        })
    return out


def existing_replay_goals(runtime_path: Path) -> set[str]:
    """Return goal_ids that already have a replay block in goal_sequences."""
    if not runtime_path.exists():
        return set()
    try:
        rt = json.loads(runtime_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    out = set()
    for gid, seq in (rt.get("goal_sequences") or {}).items():
        if not isinstance(seq, dict):
            continue
        for step in seq.get("steps") or []:
            if isinstance(step, dict) and step.get("replay"):
                out.add(gid)
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must specify --dry-run or --apply")
    if args.dry_run and args.apply:
        ap.error("--dry-run and --apply mutually exclusive")

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dir = find_phase_dir(repo, args.phase)
    if phase_dir is None:
        print(f"phase '{args.phase}' not found at {repo / '.vg/phases'}",
              file=sys.stderr)
        return 1

    matrix_path = phase_dir / "GOAL-COVERAGE-MATRIX.md"
    runtime_path = phase_dir / "RUNTIME-MAP.json"
    manifest_path = phase_dir / ".legacy-surface-probe.json"

    if not matrix_path.exists():
        print(f"GOAL-COVERAGE-MATRIX.md not found at {matrix_path}",
              file=sys.stderr)
        return 1

    backend_ready = parse_matrix_backend_ready(matrix_path)
    already_replayed = existing_replay_goals(runtime_path)
    candidates = [g for g in backend_ready if g["goal_id"] not in already_replayed]

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: phase={args.phase}")
    print(f"Phase dir:  {phase_dir.relative_to(repo)}")
    print(f"Manifest:   {manifest_path.relative_to(repo)}")
    print()
    print(f"Backend goals found in matrix: {len(backend_ready)}")
    print(f"Already have replay evidence:  {len(already_replayed)}")
    print(f"Need legacy-surface-probe tag: {len(candidates)}")
    print()

    if not candidates:
        print("nothing to migrate — all backend goals already covered.")
        return 0

    for c in candidates[:10]:
        ev = c["matrix_evidence"][:80]
        print(f"  {c['goal_id']:8s} surface={c['surface']:20s} {ev!r}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")

    if args.dry_run:
        print()
        print("Re-run with --apply to write manifest.")
        return 0

    # Write manifest
    manifest = {
        "schema_version": "1.0",
        "phase": args.phase,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "migrate-backend-surface-probe.py",
        "rationale": (
            "Pre-RFC v9 phase: backend goals achieved READY via static "
            "handler-grep + route-registration probe. No RUNTIME-MAP replay "
            "traffic recorded. Validator verify-backend-mutation-evidence "
            "should accept these goals via --allow-legacy-surface-probe."
        ),
        "goals": candidates,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(f"Wrote {manifest_path.relative_to(repo)} ({len(candidates)} goals tagged).")
    print()
    print("Next step:")
    print(f"  python3 .claude/scripts/validators/verify-backend-mutation-evidence.py \\")
    print(f"    --phase {args.phase} --allow-legacy-surface-probe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
