#!/usr/bin/env python3
"""
verify-no-legacy-manifest-creation.py — v2.5.2.1 Fix 3.

Closes CrossAI round 3 consensus finding:
  `bootstrap-legacy-artifacts.py` (also shipped in this fix) writes
  manifest entries with `creator_run_id: "legacy-bootstrap"`. This is
  the grandfather marker — acceptable for phases ≤ cutover (default 17).
  But Phase 18+ runs creating NEW legacy-bootstrap entries would mean
  AI is forging the grandfather marker itself.

This validator blocks legacy-bootstrap entries from being created AFTER
the cutover phase. Fires from orchestrator preflight + Phase K validators.

Check:
  For every entry in `.vg/runs/legacy-bootstrap/evidence-manifest.json`:
    - `phase` field ≤ cutover_phase → OK (grandfathered)
    - `phase` field > cutover_phase → FAIL (new forge surface)

  Also detects if a NEW run (run_id != legacy-bootstrap) has emitted
  entries with `grandfathered: true` flag (drift from bootstrap
  convention).

Exit codes:
  0 = no legacy-bootstrap entries past cutover
  1 = violation (phase > cutover_phase flagged as legacy OR grandfather
      flag set on non-bootstrap run)
  2 = config error

Usage:
  verify-no-legacy-manifest-creation.py --cutover-phase 17
  verify-no-legacy-manifest-creation.py --manifest .vg/runs/legacy-bootstrap/evidence-manifest.json
  verify-no-legacy-manifest-creation.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DEFAULT_MANIFEST = REPO_ROOT / ".vg" / "runs" / "legacy-bootstrap" / \
                   "evidence-manifest.json"


def _parse_phase_number(phase_ref: str | None) -> float | None:
    """Extract numeric phase from string like '7.14-dsp-advertiser-ui' → 7.14.

    Supports: '7', '7.1', '07.14', '7.14-name', '07.14-something-else'.
    Returns None if no numeric prefix.
    """
    if not phase_ref:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)", phase_ref.strip())
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _scan_manifest_for_violations(manifest: dict, cutover: float
                                  ) -> list[dict]:
    """Return list of violating entries."""
    violations = []
    for entry in manifest.get("entries", []):
        phase_ref = entry.get("phase") or ""
        phase_num = _parse_phase_number(phase_ref)
        if phase_num is None:
            # Can't tell — mark as suspicious but don't fail hard
            violations.append({
                "path": entry.get("path"),
                "phase": phase_ref,
                "reason": "phase field missing/unparseable in legacy-bootstrap entry",
                "severity": "warn",
            })
            continue
        if phase_num > cutover:
            violations.append({
                "path": entry.get("path"),
                "phase": phase_ref,
                "phase_num": phase_num,
                "reason": (f"phase {phase_num} > cutover {cutover} — "
                           "AI may have forged legacy-bootstrap marker "
                           "for a post-cutover phase"),
                "severity": "block",
            })
    return violations


def _scan_other_runs_for_grandfather_drift() -> list[dict]:
    """Walk all runs/ dirs (excluding legacy-bootstrap) and flag entries
    with `grandfathered: true` or `creator_run_id: legacy-bootstrap`."""
    runs_dir = REPO_ROOT / ".vg" / "runs"
    if not runs_dir.exists():
        return []
    violations = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir() or run_dir.name == "legacy-bootstrap":
            continue
        manifest_file = run_dir / "evidence-manifest.json"
        if not manifest_file.exists():
            continue
        try:
            m = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in m.get("entries", []):
            if entry.get("creator_run_id") == "legacy-bootstrap" or \
               entry.get("grandfathered") is True:
                violations.append({
                    "run_id": run_dir.name,
                    "path": entry.get("path"),
                    "reason": "non-bootstrap run emitted grandfathered entry "
                              "(only bootstrap-legacy-artifacts.py may set this)",
                    "severity": "block",
                })
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--cutover-phase", type=float, default=17.0,
                    help="phases > this float → no legacy-bootstrap allowed")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    violations: list[dict] = []

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"⛔ manifest unreadable: {e}", file=sys.stderr)
            return 2
        violations.extend(_scan_manifest_for_violations(manifest, args.cutover_phase))

    violations.extend(_scan_other_runs_for_grandfather_drift())

    blocking = [v for v in violations if v.get("severity") == "block"]
    report = {
        "manifest": str(manifest_path),
        "cutover_phase": args.cutover_phase,
        "violations": violations,
        "blocking_count": len(blocking),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if violations:
            print(f"{'⛔' if blocking else '⚠'} Legacy-manifest creation check: "
                  f"{len(violations)} violation(s), {len(blocking)} blocking\n")
            for v in violations:
                print(f"  [{v['severity']}] {v.get('path', v.get('run_id'))}: "
                      f"{v['reason']}")
        elif not args.quiet:
            print(f"✓ No legacy-bootstrap violations (cutover={args.cutover_phase})")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
