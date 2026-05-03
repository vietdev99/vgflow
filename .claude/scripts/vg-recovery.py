#!/usr/bin/env python3
"""Interactive recovery picker for /vg:doctor recovery.

Reads last BLOCK output from orchestrator (events.db + current-run state),
extracts violation types, looks up recovery paths, prints actionable menu.

Usage:
    python3 vg-recovery.py              # Show recovery paths for current/last run
    python3 vg-recovery.py --phase 3.2  # Specific phase
    python3 vg-recovery.py --json       # Machine-readable output
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
EVENTS_DB = REPO_ROOT / ".vg" / "events.db"
ACTIVE_RUNS_DIR = REPO_ROOT / ".vg" / "active-runs"

# Add orchestrator dir to path so we can import recovery_paths
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"))
try:
    from recovery_paths import get_recovery_paths
except ImportError:
    print("\033[38;5;208mrecovery_paths.py not found. Re-sync vgflow.\033[0m", file=sys.stderr)
    sys.exit(1)


def find_latest_run(phase: str | None = None) -> dict | None:
    """Return latest run row, optionally filtered by phase."""
    if not EVENTS_DB.exists():
        return None
    conn = sqlite3.connect(EVENTS_DB)
    conn.row_factory = sqlite3.Row
    if phase:
        rows = conn.execute(
            "SELECT * FROM runs WHERE phase=? ORDER BY started_at DESC LIMIT 1",
            (phase,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchall()
    conn.close()
    return dict(rows[0]) if rows else None


def detect_violations_for_run(run_id: str) -> list[str]:
    """Detect violation types via 3 sources (most → least reliable):
    1. .vg/hook-verifier.log — most recent BLOCK message
    2. events.db — review.*_blocked telemetry events
    3. Probe orchestrator run-complete in dry-run if run still active
    """
    violations: list[str] = []

    # Source 1: parse latest BLOCK message in hook-verifier.log
    log_path = REPO_ROOT / ".vg" / "hook-verifier.log"
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
        # Find latest BLOCK section (after last "BLOCKED:" line)
        if "BLOCKED:" in text:
            idx = text.rfind("BLOCKED:")
            block_chunk = text[idx:idx + 5000]
            # Match [validator:NAME] or [type] tags
            import re
            tags = re.findall(r'^\s*\[([a-zA-Z][\w:-]+)\]\s*$', block_chunk, re.MULTILINE)
            for t in tags:
                if t and t not in {"BLOCKED"}:
                    violations.append(t)

    # Source 2: events.db blocked events
    if EVENTS_DB.exists():
        try:
            conn = sqlite3.connect(EVENTS_DB)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT event_type FROM events
                   WHERE run_id=? AND event_type LIKE '%_blocked'""",
                (run_id,),
            ).fetchall()
            for row in rows:
                et = row["event_type"]
                if et.endswith("_blocked"):
                    short = et.split(".", 1)[-1].replace("_blocked", "").replace("_", "-")
                    violations.append(f"validator:{short}")
            conn.close()
        except Exception:
            pass

    # Dedupe + return
    return sorted(set(violations))


def render_menu(violations: list[str], command: str, phase: str) -> None:
    """Print human-readable recovery menu for each violation."""
    if not violations:
        print("ℹ No active violations detected. Run /vg:doctor stack for general health check.")
        return

    print()
    print("━━━ Recovery paths for current BLOCK ━━━")
    print()
    for v_type in violations:
        paths = get_recovery_paths(v_type, command, phase)
        if not paths:
            print(f"\033[33m[{v_type}] no recovery paths registered — generic fallback only:\033[0m")
            print("  - Run skill to completion (let validators see real evidence)")
            print("  - Or: vg-orchestrator override --flag <f> --reason <text>")
            print("  - Or: vg-orchestrator run-abort --reason <text>")
            print()
            continue

        print(f"━ [{v_type}] {len(paths)} path(s) available:")
        for i, p in enumerate(paths, 1):
            star = " ★" if i == 1 else "  "
            print(f"   {star} [{i}] {p.get('label', p.get('id', '?'))}")
            print(f"        $ {p.get('command', '')}")
            cost = p.get("cost", "")
            when = p.get("when", "")
            effect = p.get("effect", "")
            if effect:
                print(f"        → effect: {effect}")
            if cost or when:
                print(f"        cost={cost} | when={when}")
        print()
    print("Run the chosen command directly. (Interactive picker TBD — paste command into shell.)")


def execute_auto_recovery(
    violations: list[str],
    command: str,
    phase: str,
    max_iterations: int = 3,
) -> tuple[bool, list[dict]]:
    """Auto-execute first auto_executable path per violation.

    Closes "BLOCK = stop" anti-pattern: AI must autonomously try to fix
    before giving up. Only runs SAFE paths (override flags + log debt) —
    NEVER auto-runs token-expensive --retry-failed or destructive edits.

    Returns (overall_success, action_log).
    """
    import subprocess

    actions: list[dict] = []
    for v_type in violations:
        paths = get_recovery_paths(v_type, command, phase)
        # Pick first auto_executable=True path
        auto_path = next((p for p in paths if p.get("auto_executable")), None)
        if not auto_path:
            actions.append({
                "violation": v_type,
                "status": "no_auto_path",
                "message": f"No auto_executable path for {v_type}; user must pick manually",
            })
            continue

        cmd = auto_path.get("auto_command") or auto_path.get("command")
        if not cmd:
            actions.append({
                "violation": v_type,
                "status": "no_command",
                "path_id": auto_path.get("id"),
            })
            continue

        # Execute (only if it looks like a shell command — not a workflow instruction)
        if cmd.startswith("/vg:") or cmd.startswith("Edit ") or cmd.startswith("Change "):
            actions.append({
                "violation": v_type,
                "status": "skipped_workflow_instruction",
                "command": cmd,
                "reason": "Auto-executor only runs shell commands; workflow instructions need user",
            })
            continue

        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60,
                cwd=str(REPO_ROOT),
            )
            actions.append({
                "violation": v_type,
                "status": "executed",
                "path_id": auto_path.get("id"),
                "command": cmd,
                "exit_code": r.returncode,
                "stdout": (r.stdout or "")[:300],
                "stderr": (r.stderr or "")[:300],
            })
        except subprocess.TimeoutExpired:
            actions.append({
                "violation": v_type,
                "status": "timeout",
                "command": cmd,
            })

    # Determine overall success: at least 1 executed AND none failed
    executed = [a for a in actions if a.get("status") == "executed"]
    failed = [a for a in executed if a.get("exit_code", 0) != 0]
    success = bool(executed) and not failed
    return success, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery path picker for VG BLOCKs")
    parser.add_argument("--phase", help="Filter by phase (latest if omitted)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-execute first auto_executable path per violation (closes BLOCK=stop pattern)",
    )
    args = parser.parse_args()

    run = find_latest_run(args.phase)
    if not run:
        print("ℹ No runs found in events.db. Nothing to recover.", file=sys.stderr)
        return 1

    command = run["command"]
    phase = run["phase"]
    run_id = run["run_id"]

    violations = detect_violations_for_run(run_id)

    if args.auto:
        if not violations:
            if args.json:
                print(json.dumps({"status": "no_violations"}))
            else:
                print("ℹ No active violations. Nothing to auto-recover.")
            return 0
        success, actions = execute_auto_recovery(violations, command, phase)
        if args.json:
            print(json.dumps({
                "auto_recovery": "success" if success else "partial_or_fail",
                "actions": actions,
            }, indent=2))
        else:
            print(f"━━━ Auto-recovery {'SUCCESS' if success else 'PARTIAL/FAIL'} ━━━")
            for a in actions:
                status = a.get("status", "?")
                v = a.get("violation", "?")
                if status == "executed":
                    rc = a.get("exit_code", "?")
                    icon = "✓" if rc == 0 else "✗"
                    print(f"  {icon} [{v}] {a.get('path_id')} → exit={rc}")
                    if a.get("stderr"):
                        print(f"      stderr: {a['stderr'][:120]}")
                elif status == "no_auto_path":
                    print(f"  \033[33m[{v}] no auto_executable path — manual fix needed\033[0m")
                elif status == "skipped_workflow_instruction":
                    print(f"  ⏭ [{v}] {a.get('path_id', '?')} skipped (workflow, not shell)")
                else:
                    print(f"  ? [{v}] {status}")
            if not success:
                print("\nFalling through to manual recovery menu:")
                render_menu(violations, command, phase)
        return 0 if success else 2

    if args.json:
        result = {
            "run_id": run_id,
            "command": command,
            "phase": phase,
            "violations": violations,
            "recovery_paths": {
                v: get_recovery_paths(v, command, phase) for v in violations
            },
        }
        print(json.dumps(result, indent=2))
        return 0

    print(f"Latest run: /{command} {phase} (run_id={run_id[:8]})")
    print(f"Outcome: {run.get('outcome', 'in-progress')}")
    render_menu(violations, command, phase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
