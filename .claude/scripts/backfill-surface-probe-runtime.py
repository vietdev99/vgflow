#!/usr/bin/env python3
"""Backfill RUNTIME-MAP.json goal_sequences[] from .surface-probe-results.json.

Closes Issue #85 (matrix-evidence-link surface-probe schema gap):
verify-matrix-evidence-link.py only reads RUNTIME-MAP goal_sequences[]
to verify matrix Status. Backend goals (surface ∈ {api, data,
integration, time-driven}) get probed via surface-probe.sh during
Phase 4a and their results land in `.surface-probe-results.json` —
NOT in RUNTIME-MAP. Without this backfill, matrix Status=READY for a
backend goal looks "ungrounded" to the validator and BLOCKs review.

Fix path chosen: option (a) — single-file ground truth. Workflow writes
a synthetic goal_sequences[gid] entry for each probed non-UI goal so
RUNTIME-MAP remains the single ground truth for matrix-evidence-link
without changing the validator's read surface.

Synthetic entry shape (per goal):
  {
    "synthetic": true,
    "source": "surface_probe",
    "surface": "<api|data|integration|time-driven>",
    "result": "<passed|blocked|infra_pending|deferred-structural>",
    "evidence_ref": ".surface-probe-results.json#G-XX",
    "evidence_text": "<one-line probe evidence>",
    "steps": [
      {
        "do": "probe",
        "target": "surface-probe:<surface>",
        "evidence": {"source": "surface_probe", "evidence_ref": "...#G-XX"}
      }
    ]
  }

Mapping table (surface-probe STATUS → goal_sequence result):
  READY          → "passed"
  BLOCKED        → "blocked"
  INFRA_PENDING  → "infra_pending"   (matrix uses INFRA_PENDING anyway → no contradiction)
  UNREACHABLE    → "unreachable"     (matrix uses UNREACHABLE anyway → no contradiction)
  SKIPPED        → no synthetic entry (fall through to NOT_SCANNED branch as today)

Idempotent: re-running overwrites synthetic entries by gid. Real entries
(no `synthetic: true` flag) are NEVER overwritten — if a goal somehow
got both a real browser sequence and a probe result, the real sequence wins.

Usage:
  python3 scripts/backfill-surface-probe-runtime.py --phase-dir .vg/phases/03.2-foo
  python3 scripts/backfill-surface-probe-runtime.py --phase 3.2  --apply
  python3 scripts/backfill-surface-probe-runtime.py --phase 3.2  --dry-run

Exit codes:
  0  Backfill written (or dry-run completed) — count printed to stdout
  1  Phase dir / probe results / runtime map missing
  2  JSON parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


STATUS_TO_RESULT = {
    "READY": "passed",
    "BLOCKED": "blocked",
    "INFRA_PENDING": "infra_pending",
    "UNREACHABLE": "unreachable",
}


def find_phase_dir(repo_root: Path, phase_filter: str) -> Path | None:
    phases = repo_root / ".vg" / "phases"
    if not phases.exists():
        return None
    candidates = [phase_filter]
    if "." in phase_filter:
        head, _, tail = phase_filter.partition(".")
        if not head.startswith("0") and head.isdigit() and len(head) == 1:
            candidates.append(f"0{head}.{tail}")
    elif phase_filter.isdigit() and len(phase_filter) == 1:
        candidates.append(f"0{phase_filter}")
    for prefix in candidates:
        matches = sorted(phases.glob(f"{prefix}-*"))
        if matches:
            return matches[0]
    return None


def load_probe_results(probe_path: Path) -> dict:
    if not probe_path.exists():
        return {}
    text = probe_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return {}
    data = json.loads(text)
    return data.get("results") or {}


def load_runtime_map(rmap_path: Path) -> dict:
    if not rmap_path.exists():
        return {}
    text = rmap_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return {}
    return json.loads(text)


def synthetic_entry(gid: str, surface: str, status: str, evidence_text: str) -> dict:
    result = STATUS_TO_RESULT.get(status.upper())
    if not result:
        return {}
    evidence_ref = f".surface-probe-results.json#{gid}"
    return {
        "synthetic": True,
        "source": "surface_probe",
        "surface": surface,
        "result": result,
        "evidence_ref": evidence_ref,
        "evidence_text": (evidence_text or "")[:500],
        "steps": [
            {
                "do": "probe",
                "target": f"surface-probe:{surface}",
                "evidence": {
                    "source": "surface_probe",
                    "evidence_ref": evidence_ref,
                    "evidence_text": (evidence_text or "")[:500],
                },
            }
        ],
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_synthetic(rmap: dict, probe_results: dict) -> tuple[dict, int, int]:
    """Merge synthetic entries into rmap. Returns (rmap, written, skipped)."""
    if not isinstance(rmap, dict):
        rmap = {}
    sequences = rmap.setdefault("goal_sequences", {})
    if not isinstance(sequences, dict):
        return rmap, 0, 0
    written = 0
    skipped = 0
    for gid, probe in probe_results.items():
        if not isinstance(probe, dict):
            continue
        status = str(probe.get("status") or "").upper()
        if status not in STATUS_TO_RESULT:
            skipped += 1
            continue
        existing = sequences.get(gid)
        if isinstance(existing, dict) and not existing.get("synthetic"):
            skipped += 1
            continue
        surface = str(probe.get("surface") or "").lower()
        evidence_text = str(probe.get("evidence") or "")
        sequences[gid] = synthetic_entry(gid, surface, status, evidence_text)
        written += 1
    return rmap, written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase-dir")
    g.add_argument("--phase")
    ap.add_argument(
        "--repo-root",
        default=".",
        help="Repo root (defaults to cwd; resolved against this for --phase lookup)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without modifying RUNTIME-MAP.json",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Default behavior; included for symmetry with migrate-backend-surface-probe.py",
    )
    args = ap.parse_args()

    if args.phase_dir:
        phase_dir = Path(args.phase_dir).resolve()
    else:
        phase_dir = find_phase_dir(Path(args.repo_root).resolve(), args.phase)

    if phase_dir is None or not phase_dir.is_dir():
        print(f"⛔ phase dir not found (phase={args.phase or args.phase_dir})", file=sys.stderr)
        return 1

    probe_path = phase_dir / ".surface-probe-results.json"
    rmap_path = phase_dir / "RUNTIME-MAP.json"

    if not probe_path.exists():
        # Not an error: phases without backend goals never wrote a probe results
        # file. Emit a no-op summary and exit clean so the caller pipeline doesn't
        # treat absence as failure.
        print(
            f"ℹ no .surface-probe-results.json at {phase_dir.name} — no backfill needed"
        )
        return 0

    if not rmap_path.exists():
        print(f"⛔ RUNTIME-MAP.json missing at {phase_dir}", file=sys.stderr)
        return 1

    try:
        probe_results = load_probe_results(probe_path)
    except json.JSONDecodeError as exc:
        print(f"⛔ probe results parse error: {exc}", file=sys.stderr)
        return 2
    try:
        rmap = load_runtime_map(rmap_path)
    except json.JSONDecodeError as exc:
        print(f"⛔ RUNTIME-MAP.json parse error: {exc}", file=sys.stderr)
        return 2

    if not probe_results:
        print(f"ℹ probe results empty at {phase_dir.name} — no backfill needed")
        return 0

    new_rmap, written, skipped = merge_synthetic(rmap, probe_results)

    if args.dry_run:
        print(
            f"DRY-RUN {phase_dir.name}: would backfill {written} synthetic "
            f"goal_sequences entries; {skipped} skipped (real entry / unmappable status)"
        )
        return 0

    if written == 0:
        print(
            f"ℹ {phase_dir.name}: 0 synthetic entries written ({skipped} skipped) — "
            f"RUNTIME-MAP.json unchanged"
        )
        return 0

    rmap_path.write_text(
        json.dumps(new_rmap, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"✓ {phase_dir.name}: backfilled {written} synthetic goal_sequences "
        f"entries from {probe_path.name} ({skipped} skipped)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
