#!/usr/bin/env python3
"""
emit-evidence-manifest.py — Phase K of v2.5.2 hardening.

Problem closed:
  v2.5.1 `glob_min_count: 1` verifies artifact EXISTS but not that the
  current run created it. Stale `crossai/result-codex.xml` from run A can
  satisfy run B's must_write check → same forge surface as marker-touched-
  without-work, one abstraction layer down.

This script writes an evidence manifest entry per artifact, so
verify-artifact-freshness.py can later prove:
  1. Artifact sha256 matches what was recorded at write time
  2. Artifact's creator_run_id == current run's run_id
  3. Upstream source inputs still hash the same (provenance chain)

Manifest location: `.vg/runs/{run_id}/evidence-manifest.json`

Usage from skill bash:
  python .claude/scripts/emit-evidence-manifest.py \\
    --path "${PHASE_DIR}/PLAN.md" \\
    --source-inputs "${PHASE_DIR}/SPECS.md,${PHASE_DIR}/CONTEXT.md"

  python .claude/scripts/emit-evidence-manifest.py \\
    --path "${PHASE_DIR}/crossai/result-codex.xml"   (no inputs needed)

Exit codes:
  0 = manifest entry written
  1 = artifact missing or unreadable
  2 = run_id resolution failed (no .vg/current-run.json)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _sha256(path: Path) -> Optional[str]:
    """Hex sha256 of file bytes, line-ending normalized for cross-platform parity."""
    try:
        data = path.read_bytes()
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError):
        return None


def _file_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except (FileNotFoundError, PermissionError):
        return None


def _resolve_repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        )
        return Path(out.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def _load_current_run(repo_root: Path) -> Optional[dict]:
    """Read .vg/current-run.json for run_id of the in-progress run."""
    for name in ("current-run.json", "current_run.json"):
        p = repo_root / ".vg" / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _manifest_path(repo_root: Path, run_id: str) -> Path:
    return repo_root / ".vg" / "runs" / run_id / "evidence-manifest.json"


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "entries" not in data:
            data["entries"] = []
        return data
    except json.JSONDecodeError:
        return {"version": 1, "entries": []}


def _save_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _resolve_path_with_phase_vars(raw: str, repo_root: Path) -> Path:
    """Expand ${PHASE_DIR}, ${PHASE_NUMBER}, $PHASE_DIR, etc."""
    path = raw
    phase_dir = os.environ.get("PHASE_DIR")
    phase_number = os.environ.get("PHASE_NUMBER")
    if phase_dir:
        path = path.replace("${PHASE_DIR}", phase_dir)
        path = path.replace("$PHASE_DIR", phase_dir)
    if phase_number:
        path = path.replace("${PHASE_NUMBER}", phase_number)
        path = path.replace("$PHASE_NUMBER", phase_number)
    result = Path(path)
    if not result.is_absolute():
        result = repo_root / result
    return result.resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", required=True,
                    help="artifact file path (absolute OR relative to repo root; "
                         "supports ${PHASE_DIR}, ${PHASE_NUMBER})")
    ap.add_argument("--run-id", default=None,
                    help="explicit run_id override; default reads .vg/current-run.json")
    ap.add_argument("--source-inputs", default="",
                    help="comma-separated list of upstream input paths "
                         "(e.g. 'PHASE_DIR/SPECS.md,PHASE_DIR/CONTEXT.md')")
    ap.add_argument("--producer", default=None,
                    help="producing command+step (default: reads from "
                         "current-run.json command field)")
    ap.add_argument("--quiet", action="store_true",
                    help="no output on success")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()

    # Resolve run_id
    run_id = args.run_id
    current = _load_current_run(repo_root)
    producer = args.producer
    if not run_id:
        if not current:
            print(
                "\033[38;5;208mNo --run-id and .vg/current-run.json missing. \033[0m"
                "Cannot resolve run_id.",
                file=sys.stderr,
            )
            return 2
        run_id = current.get("run_id")
        if not run_id:
            print(
                "⛔ .vg/current-run.json has no 'run_id' field.",
                file=sys.stderr,
            )
            return 2
    if not producer and current:
        producer = f"{current.get('command', '?')}"

    # Hash the artifact
    artifact_path = _resolve_path_with_phase_vars(args.path, repo_root)
    artifact_hash = _sha256(artifact_path)
    if artifact_hash is None:
        print(
            f"\033[38;5;208mCannot read artifact: {artifact_path} \033[0m"
            f"(does it exist? was it written yet?)",
            file=sys.stderr,
        )
        return 1

    # Resolve relative path for manifest entry (portable across machines)
    try:
        rel_path = artifact_path.relative_to(repo_root).as_posix()
    except ValueError:
        rel_path = str(artifact_path)

    # Hash upstream source inputs (provenance chain)
    source_inputs = []
    if args.source_inputs:
        for raw in args.source_inputs.split(","):
            raw = raw.strip()
            if not raw:
                continue
            src_path = _resolve_path_with_phase_vars(raw, repo_root)
            src_hash = _sha256(src_path)
            try:
                src_rel = src_path.relative_to(repo_root).as_posix()
            except ValueError:
                src_rel = str(src_path)
            source_inputs.append({
                "path": src_rel,
                "sha256": src_hash,  # None if missing — caller can still decide
                "exists": src_hash is not None,
            })

    # Build entry
    entry = {
        "path": rel_path,
        "sha256": artifact_hash,
        "size_bytes": _file_size(artifact_path),
        "creator_run_id": run_id,
        "producer": producer,
        "created_at": _now_iso(),
        "source_inputs": source_inputs,
    }

    # Load existing manifest + append (dedupe by path — last write wins)
    manifest_path = _manifest_path(repo_root, run_id)
    data = _load_manifest(manifest_path)
    existing_entries = [e for e in data["entries"] if e.get("path") != rel_path]
    existing_entries.append(entry)
    data["entries"] = existing_entries
    data["updated_at"] = _now_iso()
    data["run_id"] = run_id  # redundant but handy for standalone manifest inspection

    _save_manifest(manifest_path, data)

    if not args.quiet:
        print(
            f"✓ Evidence manifest entry: {rel_path}\n"
            f"  run_id: {run_id[:12]}..., sha256: {artifact_hash[:12]}..., "
            f"size: {entry['size_bytes']} bytes"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
