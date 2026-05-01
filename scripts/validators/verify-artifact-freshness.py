#!/usr/bin/env python3
"""
verify-artifact-freshness.py — Phase K of v2.5.2 hardening.

Problem closed:
  v2.5.1 verified artifact EXISTS via glob_min_count. This validator
  verifies it was CREATED BY THE CURRENT RUN — i.e., stale file from
  prior run doesn't satisfy the gate.

Two checks:
  1. Freshness: `.vg/runs/{run_id}/evidence-manifest.json` has entry for
     path, AND entry.creator_run_id == run_id, AND recomputed sha256
     matches entry.sha256 (file wasn't externally modified after emit).
  2. Provenance (optional per-contract field): each source_input in
     manifest entry has sha256 matching current disk state.

Fresh-fail modes:
  ARTIFACT_MISSING    — file doesn't exist on disk
  MANIFEST_MISSING    — no manifest file for this run
  NO_ENTRY            — manifest exists but no entry for this artifact
  RUN_ID_MISMATCH     — entry exists but creator_run_id != current run
  HASH_MISMATCH       — entry.sha256 doesn't match recomputed sha256
                         (file mutated after emit, or different file)
  PROVENANCE_DRIFT    — source_input's current sha256 differs from entry

Exit codes:
  0 = all artifacts fresh + provenance intact
  1 = freshness/provenance failure
  2 = config error (bad args)

Usage:
  verify-artifact-freshness.py --run-id <UUID> --path <rel-path>
  verify-artifact-freshness.py --run-id <UUID> --paths a.md,b.md,c.md
  verify-artifact-freshness.py --run-id <UUID> --paths a.md --check-provenance
  verify-artifact-freshness.py --json          # machine-readable
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _sha256(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
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


def _manifest_path(repo_root: Path, run_id: str) -> Path:
    return repo_root / ".vg" / "runs" / run_id / "evidence-manifest.json"


def _load_manifest(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _check_artifact(path_str: str, run_id: str, repo_root: Path,
                    manifest: Optional[dict],
                    check_provenance: bool) -> dict:
    """Return dict: {path, verdict, reason, details}."""
    # Expand env vars
    resolved = path_str
    phase_dir = os.environ.get("PHASE_DIR")
    phase_number = os.environ.get("PHASE_NUMBER")
    if phase_dir:
        resolved = resolved.replace("${PHASE_DIR}", phase_dir) \
                           .replace("$PHASE_DIR", phase_dir)
    if phase_number:
        resolved = resolved.replace("${PHASE_NUMBER}", phase_number) \
                           .replace("$PHASE_NUMBER", phase_number)
    artifact_path = Path(resolved)
    if not artifact_path.is_absolute():
        artifact_path = repo_root / artifact_path
    artifact_path = artifact_path.resolve()

    try:
        rel_path = artifact_path.relative_to(repo_root).as_posix()
    except ValueError:
        rel_path = str(artifact_path)

    result = {
        "path": rel_path,
        "verdict": "OK",
        "reason": None,
        "details": {},
    }

    # 1. Artifact must exist on disk
    current_hash = _sha256(artifact_path)
    if current_hash is None:
        result["verdict"] = "ARTIFACT_MISSING"
        result["reason"] = f"File not on disk: {rel_path}"
        return result
    result["details"]["current_sha256"] = current_hash

    # 2. Manifest must exist
    if manifest is None:
        result["verdict"] = "MANIFEST_MISSING"
        result["reason"] = (
            f"No .vg/runs/{run_id}/evidence-manifest.json — run never "
            f"called emit-evidence-manifest.py"
        )
        return result

    # 3. Entry for this path must exist
    entries = manifest.get("entries", [])
    entry = next((e for e in entries if e.get("path") == rel_path), None)
    if entry is None:
        result["verdict"] = "NO_ENTRY"
        result["reason"] = (
            f"Manifest has {len(entries)} entries but none for {rel_path}"
        )
        return result
    result["details"]["entry"] = {
        "creator_run_id": entry.get("creator_run_id"),
        "sha256": entry.get("sha256"),
        "created_at": entry.get("created_at"),
        "producer": entry.get("producer"),
    }

    # 4. creator_run_id must match current run
    creator = entry.get("creator_run_id")
    if creator != run_id:
        result["verdict"] = "RUN_ID_MISMATCH"
        result["reason"] = (
            f"Entry creator_run_id={creator!r} but current run_id={run_id!r}. "
            f"This artifact was produced by a different run — stale evidence."
        )
        return result

    # 5. Recomputed sha256 must match entry (file not mutated after emit)
    entry_hash = entry.get("sha256")
    if entry_hash != current_hash:
        result["verdict"] = "HASH_MISMATCH"
        result["reason"] = (
            f"Entry sha256={entry_hash!r} but file currently hashes "
            f"{current_hash!r} — file mutated after emit-evidence-manifest "
            f"call or emit was called with wrong content."
        )
        return result

    # 6. Optional: provenance chain — source_inputs must still hash the same
    if check_provenance:
        drift = []
        for src in entry.get("source_inputs", []):
            src_path_str = src.get("path", "")
            expected_hash = src.get("sha256")
            src_path = Path(src_path_str)
            if not src_path.is_absolute():
                src_path = repo_root / src_path
            current_src_hash = _sha256(src_path)
            if expected_hash and current_src_hash != expected_hash:
                drift.append({
                    "path": src_path_str,
                    "expected_sha256": expected_hash,
                    "current_sha256": current_src_hash,
                })
        if drift:
            result["verdict"] = "PROVENANCE_DRIFT"
            result["reason"] = (
                f"{len(drift)} source input(s) mutated since artifact created"
            )
            result["details"]["drift"] = drift
            return result

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-id", default=None,
                    help="run_id to verify against (default: reads "
                         ".vg/current-run.json)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--path", help="single artifact path")
    group.add_argument("--paths",
                       help="comma-separated artifact paths")
    ap.add_argument("--check-provenance", action="store_true",
                    help="also verify source_inputs sha256 match")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output on pass")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()

    # Resolve run_id with multi-session safety: prefer per-session active-run
    # file (.vg/active-runs/{session_id}.json) over the global current-run.json
    # snapshot when CLAUDE_SESSION_ID is set. Without this guard, a concurrent
    # session's run-start will have overwritten the global pointer and we'd
    # validate the wrong run_id.
    run_id = args.run_id
    if not run_id:
        sid = (
            os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or ""
        )
        safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_") or ""
        # 1. Per-session
        if safe_sid:
            per = repo_root / ".vg" / "active-runs" / f"{safe_sid}.json"
            if per.exists():
                try:
                    run_id = json.loads(per.read_text(encoding="utf-8")).get("run_id")
                except (json.JSONDecodeError, OSError):
                    pass
        # 2. Legacy snapshot — trust only when session matches or is absent
        if not run_id:
            current = repo_root / ".vg" / "current-run.json"
            if current.exists():
                try:
                    snap = json.loads(current.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    snap = None
                if snap:
                    legacy_sid = snap.get("session_id") or ""
                    compatible = (
                        not sid
                        or not legacy_sid
                        or legacy_sid == sid
                        or legacy_sid == "unknown"
                    )
                    if compatible:
                        run_id = snap.get("run_id")
    if not run_id:
        print(
            "⛔ No --run-id and no per-session/legacy run pointer "
            "(.vg/active-runs/{session_id}.json or .vg/current-run.json).",
            file=sys.stderr,
        )
        return 2

    paths = [args.path] if args.path else [
        p.strip() for p in args.paths.split(",") if p.strip()
    ]

    manifest = _load_manifest(_manifest_path(repo_root, run_id))

    results = []
    for p in paths:
        results.append(_check_artifact(
            p, run_id, repo_root, manifest, args.check_provenance,
        ))

    failures = [r for r in results if r["verdict"] != "OK"]

    if args.json:
        # v2.6.1 (2026-04-26): top-level verdict for orchestrator schema.
        # Without it, dispatch reads out.get("verdict", "PASS") → silent PASS
        # despite internal failures. Closes AUDIT.md D1 schema drift S2.
        print(json.dumps({
            "validator": "verify-artifact-freshness",
            "verdict": "BLOCK" if failures else "PASS",
            "run_id": run_id,
            "checked": len(results),
            "failures": len(failures),
            "results": results,
        }, indent=2))
    else:
        if failures:
            print(f"⛔ Artifact freshness: {len(failures)}/{len(results)} failed\n")
            for r in failures:
                print(f"  [{r['verdict']}] {r['path']}")
                if r.get("reason"):
                    print(f"    {r['reason']}")
            print("\nFix options:")
            print("  (a) Re-run the command — evidence should be re-emitted")
            print("  (b) Explicitly emit: python .claude/scripts/emit-evidence-manifest.py --path <X>")
            print(f"  (c) --allow-artifact-freshness-gap flag (logs override-debt)")
        elif not args.quiet:
            print(f"✓ Artifact freshness OK — {len(results)} check(s) passed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
