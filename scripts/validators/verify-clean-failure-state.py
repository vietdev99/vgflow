#!/usr/bin/env python3
"""
verify-clean-failure-state.py — Phase O of v2.5.2 hardening.

After a failed run, ensure the repo is in a clean state:
  - No stale repo lockfile referencing this run
  - No files under .vg/runs/<run_id>/tmp/ or .inflight/
  - Evidence manifest entries for this run either
        (a) map to committed blobs in git (HEAD has them), OR
        (b) have been rolled back (journal replay succeeded)

Exit codes:
  0 = clean
  1 = dirty (findings present)
  2 = config error (bad args / unreadable files)

Usage:
  verify-clean-failure-state.py --run-id <uuid>
  verify-clean-failure-state.py --check-current   # reads .vg/current-run.json
  verify-clean-failure-state.py --run-id <uuid> --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _resolve_repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT") or os.environ.get("REPO_ROOT")
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
    path = repo_root / ".vg" / "current-run.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _check_lock(repo_root: Path, run_id: str) -> list[dict]:
    """Return findings list. Empty = clean."""
    lockfile = repo_root / ".vg" / ".repo-lock.json"
    if not lockfile.exists():
        return []
    try:
        data = json.loads(lockfile.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [{"kind": "LOCK_UNPARSEABLE", "detail": str(e)}]
    token = data.get("lock_token")
    # A leftover lock belonging to this run is dirty; a lock from a
    # different run is out-of-scope but still notable.
    if token == run_id or data.get("run_id") == run_id:
        return [{
            "kind": "STALE_LOCK_THIS_RUN",
            "detail": f"lockfile still held by run {run_id[:12]}",
            "lockfile": str(lockfile),
        }]
    return []


def _check_inflight(repo_root: Path, run_id: str) -> list[dict]:
    """Find any tmp/.inflight files under this run dir."""
    run_dir = repo_root / ".vg" / "runs" / run_id
    if not run_dir.exists():
        return []
    findings: list[dict] = []
    for sub in ("tmp", ".inflight"):
        target = run_dir / sub
        if not target.exists():
            continue
        leftovers = [p for p in target.rglob("*") if p.is_file()]
        if leftovers:
            findings.append({
                "kind": "INFLIGHT_LEFTOVER",
                "detail": (
                    f"{len(leftovers)} file(s) in {sub}/ — partial "
                    f"writes not cleaned up"
                ),
                "dir": str(target),
                "count": len(leftovers),
            })
    return findings


def _git_tracks_path(repo_root: Path, rel_path: str) -> bool:
    """Return True if git HEAD has the given relative path."""
    try:
        r = subprocess.run(
            ["git", "ls-tree", "HEAD", "--", rel_path],
            capture_output=True, text=True, cwd=str(repo_root), timeout=5,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _check_manifest_orphans(repo_root: Path, run_id: str) -> list[dict]:
    """Manifest entries must either be git-tracked OR rolled back.

    Rolled-back entries are detected by a rollback marker file in
    .vg/runs/<run_id>/rollback.json (presence = rollback happened).
    """
    manifest = repo_root / ".vg" / "runs" / run_id / "evidence-manifest.json"
    if not manifest.exists():
        # No manifest → nothing to orphan
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [{"kind": "MANIFEST_UNPARSEABLE", "detail": str(e)}]

    rollback_marker = repo_root / ".vg" / "runs" / run_id / "rollback.json"
    rolled_back_paths: set[str] = set()
    if rollback_marker.exists():
        try:
            rb = json.loads(rollback_marker.read_text(encoding="utf-8"))
            for entry in rb.get("entries", []):
                rolled_back_paths.add(entry.get("path", ""))
        except (json.JSONDecodeError, OSError):
            pass

    findings: list[dict] = []
    for entry in data.get("entries", []):
        path = entry.get("path", "")
        if not path:
            continue
        # Skip planning artifacts — manifest design allows .vg/ uncommitted
        abs_path = repo_root / path
        if path in rolled_back_paths:
            continue
        if _git_tracks_path(repo_root, path):
            continue
        if not abs_path.exists():
            # Already removed but not tracked → orphan
            findings.append({
                "kind": "ORPHAN_MISSING",
                "detail": f"manifest entry {path} gone + not rolled back",
                "path": path,
            })
            continue
        # File exists, not tracked, not rolled back — orphan by git standards.
        # For .vg/** files this is expected (audit-only), skip.
        if path.startswith(".vg/") or path.startswith(".planning/"):
            continue
        findings.append({
            "kind": "ORPHAN_UNTRACKED",
            "detail": (
                f"manifest entry {path} not in git, not rolled back — "
                f"half-written artifact"
            ),
            "path": path,
        })
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--run-id", help="Run UUID to verify")
    grp.add_argument("--check-current", action="store_true",
                     help="Read run_id from .vg/current-run.json")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON output")
    args = parser.parse_args()

    repo_root = _resolve_repo_root()

    if args.check_current:
        current = _load_current_run(repo_root)
        if not current:
            msg = "no current-run.json — nothing to verify"
            if args.json:
                print(json.dumps({"ok": True, "reason": msg}))
            else:
                print(msg)
            return 0
        run_id = current.get("run_id", "")
    else:
        run_id = args.run_id

    if not run_id:
        print("⛔ empty run_id", file=sys.stderr)
        return 2

    findings: list[dict] = []
    findings += _check_lock(repo_root, run_id)
    findings += _check_inflight(repo_root, run_id)
    findings += _check_manifest_orphans(repo_root, run_id)

    out = {
        "ok": len(findings) == 0,
        "run_id": run_id,
        "finding_count": len(findings),
        "findings": findings,
    }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        if out["ok"]:
            print(f"✓ clean-failure-state OK for run {run_id[:12]}")
        else:
            print(f"⛔ {len(findings)} cleanliness finding(s) for "
                  f"run {run_id[:12]}:")
            for f in findings:
                print(f"  - {f['kind']}: {f.get('detail', '')}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
