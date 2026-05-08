#!/usr/bin/env python3
"""Bootstrap consolidation engine - Anthropic Auto Dream 4-phase pattern.

Task 5.1: gate + lock foundation. Subsequent tasks 5.2-5.5 add 4 phases:
  Phase 1 - Orient (read memory directory state)
  Phase 2 - Gather (narrow grep events.db + transcripts)
  Phase 3 - Consolidate (in-place merge per Anthropic Dreams pattern)
  Phase 4 - Prune & Index (rebuild MEMORY.md <= 200 lines)

Task 5.6 wires /vg:learn --consolidate skill mode.

Trigger gate (per design Section 13.1):
  - 24+ hours since last consolidation (default; override VG_DREAMS_GATE_HOURS)
  - >5 sessions since last consolidation (default; override VG_DREAMS_GATE_SESSIONS)
  - No existing .consolidation.lock (else refuse - concurrent dream prevention)

State tracked: .vg/bootstrap/state.json with last_run_ts + sessions_since_last.

Subcommands:
  --check-gate [--json]   Print gate decision (rc=0 open / rc=1 closed)
  --acquire-lock          Create .consolidation.lock with PID
  --release-lock          Remove .consolidation.lock
  --update-state          Update state.json after consolidation (5.4 will use)
  --increment-sessions    Increment sessions_since_last counter
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


DEFAULT_GATE_HOURS = 24.0
DEFAULT_GATE_SESSIONS = 5


def _state_dir() -> Path:
    """Resolve bootstrap state directory.

    Priority:
      1. VG_BOOTSTRAP_STATE_DIR env (tests + explicit override)
      2. <cwd>/.vg/bootstrap/ (production default)
    """
    env = os.environ.get("VG_BOOTSTRAP_STATE_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd() / ".vg" / "bootstrap"


def _read_state(state_dir: Path) -> dict | None:
    state_file = state_dir / "state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_gate(state_dir: Path) -> tuple[bool, str]:
    """Return (gate_open, reason)."""
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        return False, f"lock file present at {lock_file} - concurrent dream blocked"

    state = _read_state(state_dir)
    if state is None:
        return True, "first run - no state.json, gate open"

    last_run = state.get("last_run_ts", 0)
    sessions_since = state.get("sessions_since_last", 0)

    gate_hours = float(os.environ.get("VG_DREAMS_GATE_HOURS", DEFAULT_GATE_HOURS))
    gate_sessions = int(os.environ.get("VG_DREAMS_GATE_SESSIONS", DEFAULT_GATE_SESSIONS))

    elapsed = time.time() - last_run
    if elapsed < gate_hours * 3600:
        elapsed_h = elapsed / 3600
        # Strip trailing .0 so integer thresholds render as "24h" not "24.0h"
        gate_h_str = f"{gate_hours:g}h"
        return False, f"<{gate_h_str} since last run ({elapsed_h:.1f}h elapsed)"

    if sessions_since <= gate_sessions:
        return False, f"<={gate_sessions} sessions since last run ({sessions_since} counted)"

    return True, "both gates passed (24h+ elapsed + sessions threshold met)"


def acquire_lock(state_dir: Path) -> bool:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        return False
    lock_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    return True


def release_lock(state_dir: Path) -> bool:
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        lock_file.unlink()
        return True
    return False


def update_state(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    new_state = {
        "last_run_ts": time.time(),
        "sessions_since_last": 0,
    }
    state_file.write_text(json.dumps(new_state, indent=2), encoding="utf-8")


def increment_sessions(state_dir: Path):
    state = _read_state(state_dir) or {"last_run_ts": 0, "sessions_since_last": 0}
    state["sessions_since_last"] = state.get("sessions_since_last", 0) + 1
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap consolidation gate (Task 5.1)")
    parser.add_argument("--check-gate", action="store_true", help="Check trigger gate")
    parser.add_argument("--acquire-lock", action="store_true", help="Acquire .consolidation.lock")
    parser.add_argument("--release-lock", action="store_true", help="Release .consolidation.lock")
    parser.add_argument("--update-state", action="store_true",
                        help="Update state.json after successful consolidation")
    parser.add_argument("--increment-sessions", action="store_true",
                        help="Increment sessions_since_last counter")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv[1:])

    state_dir = _state_dir()

    if args.check_gate:
        gate_open, reason = check_gate(state_dir)
        payload = {"gate_open": gate_open, "reason": reason, "state_dir": str(state_dir)}
        if args.json:
            print(json.dumps(payload))
        else:
            print(f"gate_open={gate_open} reason={reason}")
        return 0 if gate_open else 1

    if args.acquire_lock:
        ok = acquire_lock(state_dir)
        if not ok:
            print("acquire_lock: lock already present", file=sys.stderr)
            return 1
        return 0

    if args.release_lock:
        ok = release_lock(state_dir)
        if not ok:
            print("release_lock: no lock file present", file=sys.stderr)
            return 1
        return 0

    if args.update_state:
        update_state(state_dir)
        return 0

    if args.increment_sessions:
        increment_sessions(state_dir)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
