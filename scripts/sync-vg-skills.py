#!/usr/bin/env python3
"""
sync-vg-skills.py — Python orchestrator for RTB → vgflow-repo → .codex mirrors.

Wraps the existing vgflow-repo/sync.sh bash script with:
  - Pre-flight validation via verify-codex-skill-mirror-sync.py
  - Version bump coordination (RTB .claude/VGFLOW-VERSION + vgflow-repo VGFLOW-VERSION)
  - Optional tag creation in vgflow-repo
  - Post-sync re-verification (all 4 locations hash-parity)
  - Telemetry emission (sync.started, sync.completed, sync.failed)
  - Release gate integration (calls sync-vg-skills.py --release to tag + push)

Does NOT replace sync.sh — delegates the actual file copying. Adds
structure, audit trail, and fail-fast gates around it.

Usage:
  sync-vg-skills.py --check           # dry-run, detect drift without fixing
  sync-vg-skills.py                   # apply full sync
  sync-vg-skills.py --release VER     # sync + bump VGFLOW-VERSION + tag + push
  sync-vg-skills.py --skip-global     # don't deploy to ~/.codex/skills
  sync-vg-skills.py --json            # machine-readable output

Exit codes:
  0 = success (synced or no-op)
  1 = drift detected in --check mode
  2 = path/config error
  3 = sync.sh failed
  4 = post-sync verification failed (sync bug!)
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


def _resolve_vgflow_repo(repo_root: Path) -> Optional[Path]:
    env = os.environ.get("VGFLOW_REPO")
    if env:
        p = Path(env).resolve()
        return p if (p / "sync.sh").exists() else None
    for candidate in (
        repo_root.parent / "vgflow-repo",
        Path.home() / "Workspace" / "Messi" / "Code" / "vgflow-repo",
    ):
        if (candidate / "sync.sh").exists():
            return candidate.resolve()
    return None


def _emit_event(event_type: str, payload: dict) -> None:
    """Best-effort telemetry emit via vg-orchestrator CLI."""
    repo_root = _resolve_repo_root()
    orch = repo_root / ".claude" / "scripts" / "vg-orchestrator"
    if not orch.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(orch), "emit-event", event_type,
             "--payload", json.dumps(payload)],
            capture_output=True, timeout=5, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # telemetry is best-effort, don't block sync


def _run_validator(repo_root: Path, vgflow_repo: Optional[Path],
                   args: list[str]) -> tuple[int, dict]:
    """Call verify-codex-skill-mirror-sync.py --json, return (exit, parsed)."""
    validator = (
        repo_root / ".claude" / "scripts" / "validators"
        / "verify-codex-skill-mirror-sync.py"
    )
    if not validator.exists():
        return 2, {"error": f"validator not found: {validator}"}

    cmd = [sys.executable, str(validator), "--json", *args]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if vgflow_repo:
        env["VGFLOW_REPO"] = str(vgflow_repo)
    env["REPO_ROOT"] = str(repo_root)

    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
        env=env, encoding="utf-8", errors="replace",
    )
    try:
        data = json.loads(r.stdout) if r.stdout else {}
    except json.JSONDecodeError:
        data = {"raw_stdout": r.stdout, "raw_stderr": r.stderr}
    return r.returncode, data


def _run_sync_sh(repo_root: Path, vgflow_repo: Path,
                 check_mode: bool = False,
                 skip_global: bool = False) -> tuple[int, str]:
    """Invoke vgflow-repo/sync.sh with correct DEV_ROOT + flags."""
    args = ["bash", str(vgflow_repo / "sync.sh")]
    if check_mode:
        args.append("--check")
    if skip_global:
        args.append("--no-global")

    env = os.environ.copy()
    env["DEV_ROOT"] = str(repo_root)

    r = subprocess.run(
        args, capture_output=True, text=True, timeout=300,
        env=env, encoding="utf-8", errors="replace",
    )
    return r.returncode, r.stdout + r.stderr


def _bump_version(repo_root: Path, vgflow_repo: Path, new_version: str) -> dict:
    """Write VGFLOW-VERSION in both locations."""
    rtb_version = repo_root / ".claude" / "VGFLOW-VERSION"
    vgflow_version = vgflow_repo / "VGFLOW-VERSION"
    result = {"rtb_version_file": str(rtb_version),
              "vgflow_version_file": str(vgflow_version)}
    rtb_version.write_text(new_version + "\n", encoding="utf-8")
    vgflow_version.write_text(new_version + "\n", encoding="utf-8")
    result["version"] = new_version
    return result


def _tag_and_push_vgflow(vgflow_repo: Path, tag_name: str,
                         message: str, dry_run: bool = False) -> dict:
    """Create annotated tag in vgflow-repo + push if not dry-run."""
    result = {"tag": tag_name, "dry_run": dry_run}
    if dry_run:
        result["action"] = "would tag + push"
        return result

    # Commit whatever's pending first
    subprocess.run(
        ["git", "add", "-A"], cwd=str(vgflow_repo), check=False,
    )
    commit = subprocess.run(
        ["git", "commit", "-m", f"release {tag_name} — {message}"],
        cwd=str(vgflow_repo), capture_output=True, text=True,
    )
    result["commit_output"] = commit.stdout or commit.stderr

    tag = subprocess.run(
        ["git", "tag", "-a", tag_name, "-m", f"{tag_name} — {message}"],
        cwd=str(vgflow_repo), capture_output=True, text=True,
    )
    result["tag_output"] = tag.stdout or tag.stderr

    push = subprocess.run(
        ["git", "push", "origin", "main", "--follow-tags"],
        cwd=str(vgflow_repo), capture_output=True, text=True, timeout=120,
    )
    result["push_output"] = push.stdout + push.stderr
    result["push_exit"] = push.returncode
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="dry-run: detect drift, don't modify anything")
    ap.add_argument("--release", default=None, metavar="VERSION",
                    help="sync + bump version + tag + push (e.g. '2.5.2')")
    ap.add_argument("--skip-global", action="store_true",
                    help="don't deploy to ~/.codex/skills")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON for programmatic consumers")
    ap.add_argument("--dry-run-release", action="store_true",
                    help="with --release: prepare but don't push")
    args = ap.parse_args()

    report = {"mode": "check" if args.check else "apply"}

    repo_root = _resolve_repo_root()
    vgflow_repo = _resolve_vgflow_repo(repo_root)
    report["repo_root"] = str(repo_root)
    report["vgflow_repo"] = str(vgflow_repo) if vgflow_repo else None

    if not vgflow_repo:
        report["error"] = (
            "vgflow-repo not found — set VGFLOW_REPO env or clone to "
            "sibling directory"
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"⛔ {report['error']}", file=sys.stderr)
        return 2

    _emit_event("sync.started", {
        "mode": report["mode"],
        "release_version": args.release,
        "skip_global": args.skip_global,
    })

    # --- 1. Pre-flight validator ---
    pre_rc, pre_data = _run_validator(
        repo_root, vgflow_repo,
        ["--skip-vgflow"] if args.skip_global else [],
    )
    report["preflight"] = {
        "exit_code": pre_rc,
        "drift_count": pre_data.get("drift_count", 0),
    }
    if args.check:
        report["summary"] = (
            f"drift detected ({pre_data.get('drift_count', 0)} items)"
            if pre_rc != 0 else "in sync"
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(report["summary"])
        return pre_rc

    # --- 2. Run sync.sh ---
    sync_rc, sync_out = _run_sync_sh(
        repo_root, vgflow_repo, check_mode=False,
        skip_global=args.skip_global,
    )
    report["sync_sh"] = {
        "exit_code": sync_rc,
        "output_tail": "\n".join(sync_out.splitlines()[-15:]),
    }
    if sync_rc != 0:
        _emit_event("sync.failed", {
            "reason": "sync.sh non-zero exit",
            "exit_code": sync_rc,
        })
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"⛔ sync.sh failed (exit {sync_rc})", file=sys.stderr)
            print(sync_out[-1000:])
        return 3

    # --- 3. Post-sync verification ---
    post_rc, post_data = _run_validator(
        repo_root, vgflow_repo,
        ["--skip-vgflow"] if args.skip_global else [],
    )
    report["postflight"] = {
        "exit_code": post_rc,
        "drift_count": post_data.get("drift_count", 0),
    }
    if post_rc != 0:
        _emit_event("sync.failed", {
            "reason": "post-sync verify still shows drift",
            "drift_count": post_data.get("drift_count", 0),
        })
        report["error"] = "sync.sh reported success but drift remains"
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"⛔ Post-sync verify FAILED — "
                  f"{post_data.get('drift_count', 0)} items still drifting")
        return 4

    # --- 4. Release flow (optional) ---
    if args.release:
        report["version_bump"] = _bump_version(
            repo_root, vgflow_repo, args.release,
        )
        # Re-run sync once more to propagate VERSION bump through mirrors
        _run_sync_sh(repo_root, vgflow_repo, skip_global=args.skip_global)
        report["tag_push"] = _tag_and_push_vgflow(
            vgflow_repo,
            f"v{args.release}",
            f"v{args.release} release",
            dry_run=args.dry_run_release,
        )

    _emit_event("sync.completed", {
        "drift_count_before": pre_data.get("drift_count", 0),
        "drift_count_after": 0,
        "release_version": args.release,
    })

    report["summary"] = "sync + verify OK"
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        pre_drift = pre_data.get("drift_count", 0)
        print(f"✓ Sync complete — {pre_drift} item(s) corrected, 0 remaining drift")
        if args.release:
            print(f"  Version: {args.release}")
            if args.dry_run_release:
                print("  (dry-run: tag + push skipped)")
            else:
                print(f"  Tagged + pushed v{args.release}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
