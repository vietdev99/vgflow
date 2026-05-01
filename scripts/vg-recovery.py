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
    print("⛔ recovery_paths.py not found. Re-sync vgflow.", file=sys.stderr)
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
            print(f"⚠ [{v_type}] no recovery paths registered — generic fallback only:")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery path picker for VG BLOCKs")
    parser.add_argument("--phase", help="Filter by phase (latest if omitted)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    run = find_latest_run(args.phase)
    if not run:
        print("ℹ No runs found in events.db. Nothing to recover.", file=sys.stderr)
        return 1

    command = run["command"]
    phase = run["phase"]
    run_id = run["run_id"]

    violations = detect_violations_for_run(run_id)

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
