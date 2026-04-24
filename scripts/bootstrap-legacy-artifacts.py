#!/usr/bin/env python3
"""
bootstrap-legacy-artifacts.py — v2.5.2.1 Fix 3.

Closes CrossAI round 3 consensus finding (Codex + Claude major):
  Phase K ships `verify-artifact-freshness.py` which requires every
  must_write artifact to have a manifest entry with `creator_run_id ==
  current run_id`. Grandfathered phases 0-16 have NO manifest entries.
  When cutover hits phase 17+, projects are forced into
  `--allow-legacy-manifest-accept` flag whose env-approver path is
  exactly the Fix 1 forge surface. Two weak gates compound.

This script walks `.vg/phases/*/` directories, discovers must_write
artifacts (PLAN.md, API-CONTRACTS.md, SPECS.md, CONTEXT.md, SUMMARY*.md,
RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md, UAT.md,
crossai/*.xml) and writes placeholder manifest entries with:
  - sha256: computed from disk
  - creator_run_id: "legacy-bootstrap" (grandfather marker)
  - producer: "bootstrap-legacy-artifacts.py"
  - created_at: now (ISO UTC)
  - source_inputs: []  (provenance chain cannot be reconstructed)
  - grandfathered: true

`verify-artifact-freshness.py` (Phase K) accepts `legacy-bootstrap` for
phases ≤ cutover_phase; Phase 18+ runs creating entries with
`creator_run_id: "legacy-bootstrap"` trigger
`verify-no-legacy-manifest-creation.py` block (new validator).

Usage:
  bootstrap-legacy-artifacts.py                    # dry-run
  bootstrap-legacy-artifacts.py --apply            # write entries
  bootstrap-legacy-artifacts.py --phase 7.14       # single phase
  bootstrap-legacy-artifacts.py --apply --json     # machine output

Exit codes:
  0 = clean (all artifacts cataloged OR apply succeeded)
  1 = dry-run detected orphan artifacts
  2 = config error
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

# Artifact patterns that Phase K cares about (from must_write contracts
# across v2.5.2 skills). Keep in sync with runtime_contract must_write blocks.
ARTIFACT_PATTERNS = [
    "SPECS.md",
    "CONTEXT.md",
    "PLAN*.md",
    "API-CONTRACTS.md",
    "TEST-GOALS.md",
    "RUNTIME-MAP.json",
    "GOAL-COVERAGE-MATRIX.md",
    "SUMMARY*.md",
    "SANDBOX-TEST.md",
    "UAT.md",
    "FOUNDATION.md",
    "ROADMAP.md",
    "crossai/result-*.xml",
    "crossai/*.xml",
]

LEGACY_RUN_ID = "legacy-bootstrap"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    """Hex sha256, line-ending normalized for cross-platform parity."""
    try:
        data = path.read_bytes()
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _discover_phase_artifacts(phase_dir: Path) -> list[Path]:
    """Return all matching artifact paths under a phase dir."""
    found: list[Path] = []
    for pattern in ARTIFACT_PATTERNS:
        for match in phase_dir.glob(pattern):
            if match.is_file():
                found.append(match)
    return sorted(set(found))


def _load_manifest(run_dir: Path) -> dict:
    manifest_file = run_dir / "evidence-manifest.json"
    if not manifest_file.exists():
        return {"run_id": run_dir.name, "entries": []}
    try:
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"run_id": run_dir.name, "entries": []}


def _save_manifest(run_dir: Path, manifest: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _entry_exists(manifest: dict, rel_path: str) -> bool:
    return any(e.get("path") == rel_path for e in manifest.get("entries", []))


def bootstrap_one_phase(phase_dir: Path, apply: bool) -> dict:
    """Build entries for one phase. Return stats dict."""
    legacy_run_dir = REPO_ROOT / ".vg" / "runs" / LEGACY_RUN_ID
    manifest = _load_manifest(legacy_run_dir)

    phase_name = phase_dir.name
    artifacts = _discover_phase_artifacts(phase_dir)
    new_entries: list[dict] = []

    for art in artifacts:
        rel = art.relative_to(REPO_ROOT).as_posix()
        if _entry_exists(manifest, rel):
            continue
        sha = _sha256(art)
        if sha is None:
            continue
        entry = {
            "path": rel,
            "sha256": sha,
            "size_bytes": art.stat().st_size,
            "creator_run_id": LEGACY_RUN_ID,
            "producer": "bootstrap-legacy-artifacts.py",
            "created_at": _now_iso(),
            "source_inputs": [],
            "grandfathered": True,
            "phase": phase_name,
        }
        new_entries.append(entry)

    if apply and new_entries:
        manifest["entries"].extend(new_entries)
        manifest["updated_at"] = _now_iso()
        _save_manifest(legacy_run_dir, manifest)

    return {
        "phase": phase_name,
        "artifacts_found": len(artifacts),
        "new_entries": len(new_entries),
        "entries_sample": [e["path"] for e in new_entries[:3]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write manifest entries (default: dry-run)")
    ap.add_argument("--phase",
                    help="bootstrap only this phase number (e.g. '7.14'); "
                         "otherwise walk all phases")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not PHASES_DIR.exists():
        print(f"⛔ .vg/phases/ not found at {PHASES_DIR}", file=sys.stderr)
        return 2

    if args.phase:
        matches = [p for p in PHASES_DIR.iterdir()
                   if p.is_dir() and fnmatch.fnmatch(p.name, f"{args.phase}*")]
        if not matches:
            print(f"⛔ no phase dir matches '{args.phase}*'", file=sys.stderr)
            return 2
    else:
        matches = sorted(p for p in PHASES_DIR.iterdir() if p.is_dir())

    reports = [bootstrap_one_phase(p, args.apply) for p in matches]
    total_new = sum(r["new_entries"] for r in reports)
    total_found = sum(r["artifacts_found"] for r in reports)

    summary = {
        "phases_scanned": len(reports),
        "artifacts_found": total_found,
        "new_manifest_entries": total_new,
        "legacy_run_id": LEGACY_RUN_ID,
        "mode": "apply" if args.apply else "dry-run",
        "per_phase": reports,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        icon = "✓" if (args.apply or total_new == 0) else "⚠"
        print(f"{icon} Bootstrap: {len(reports)} phase(s), "
              f"{total_found} artifacts, {total_new} new entries "
              f"({'written' if args.apply else 'would write, dry-run'})")
        if total_new and not args.quiet:
            for r in reports:
                if r["new_entries"]:
                    print(f"  [{r['phase']}] {r['new_entries']} entries — "
                          f"{', '.join(r['entries_sample'])}")

    if args.apply or total_new == 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
