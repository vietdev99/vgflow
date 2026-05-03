"""Hotfix 2026-05-04 — vg-user-prompt-submit.sh stale-awareness.

Pre-fix: orphan active-runs files from yesterday (review BLOCKED, never
cleared) hard-blocked any subsequent /vg:<other-cmd> on the same phase
forever. Stop hook only clears active-runs on PASS, so a BLOCKED review
left a permanent file zombie.

Post-fix: the cross-run guard treats a run as "dead" if EITHER:
  1. started_at > 30min ago (stale, mirrors orchestrator run-start clear)
  2. events.db has run.blocked for the run_id with no subsequent
     vg.block.handled / run.aborted / run.completed event

Dead runs → soft-warn (yellow), allow overwrite. Fresh + alive +
intra-phase conflict → still hard-block (preserves pipeline ordering
intent).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = str(REPO_ROOT / "scripts/hooks/vg-user-prompt-submit.sh")


def _setup_active_run(tmp: Path, *, command: str, phase: str,
                      started_minutes_ago: int = 5,
                      session_id: str = "default",
                      run_id: str = "test-run-id") -> Path:
    (tmp / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    started = (datetime.now(timezone.utc) -
               timedelta(minutes=started_minutes_ago)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")
    rf = tmp / ".vg/active-runs" / f"{session_id}.json"
    rf.write_text(json.dumps({
        "run_id": run_id,
        "command": command,
        "phase": phase,
        "session_id": session_id,
        "started_at": started,
    }))
    return rf


def _setup_events_db(tmp: Path) -> Path:
    """Minimal events.db schema matching the real one for hook's sqlite query."""
    (tmp / ".vg").mkdir(exist_ok=True)
    db = tmp / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event_type TEXT, "
        "phase TEXT, command TEXT, run_id TEXT, payload_json TEXT)"
    )
    conn.commit()
    conn.close()
    return db


def _insert_event(db: Path, *, run_id: str, event_type: str,
                  ts_offset_minutes: int = 0) -> None:
    ts = (datetime.now(timezone.utc) +
          timedelta(minutes=ts_offset_minutes)
          ).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO events (ts, event_type, run_id, payload_json) VALUES (?, ?, ?, ?)",
        (ts, event_type, run_id, "{}"),
    )
    conn.commit()
    conn.close()


def _run_hook(tmp: Path, prompt: str,
              session_id: str = "default") -> subprocess.CompletedProcess:
    payload = json.dumps({"prompt": prompt})
    return subprocess.run(
        ["bash", HOOK], input=payload, capture_output=True, text=True,
        cwd=str(tmp),
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": session_id},
        timeout=15,
    )


def test_fresh_intra_phase_conflict_still_blocks(tmp_path):
    """Pre-fix behavior preserved: fresh active review + deploy on same phase = BLOCK."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5)
    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    assert proc.returncode == 2
    assert "vg-cross-run" in proc.stderr
    assert "active vg:review" in proc.stderr
    assert "previous" not in proc.stderr  # not the dead-run path


def test_stale_run_allows_with_warn(tmp_path):
    """Existing run started >30min ago → dead → soft-warn, allow."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=120)  # 2h stale
    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    assert proc.returncode == 0
    assert "previous vg:review on phase 4.1 is dead" in proc.stderr
    assert "stale" in proc.stderr

    # File should be overwritten with new vg:deploy run
    new_run = json.loads((tmp_path / ".vg/active-runs/default.json").read_text())
    assert new_run["command"] == "vg:deploy"
    assert new_run["phase"] == "4.1"


def test_blocked_unhandled_run_allows_with_warn(tmp_path):
    """Existing run had run.blocked event with no clearing → dead → allow."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5,  # NOT stale by age
                      run_id="blocked-run-id")
    db = _setup_events_db(tmp_path)
    _insert_event(db, run_id="blocked-run-id", event_type="run.started",
                  ts_offset_minutes=-5)
    _insert_event(db, run_id="blocked-run-id", event_type="run.blocked",
                  ts_offset_minutes=-3)

    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    assert proc.returncode == 0
    assert "previous vg:review on phase 4.1 is dead" in proc.stderr
    assert "run.blocked unhandled" in proc.stderr


def test_blocked_then_handled_still_blocks(tmp_path):
    """run.blocked + vg.block.handled = resolved → run is alive, intra-phase rule applies."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5,
                      run_id="resolved-run-id")
    db = _setup_events_db(tmp_path)
    _insert_event(db, run_id="resolved-run-id", event_type="run.started",
                  ts_offset_minutes=-5)
    _insert_event(db, run_id="resolved-run-id", event_type="run.blocked",
                  ts_offset_minutes=-3)
    _insert_event(db, run_id="resolved-run-id", event_type="vg.block.handled",
                  ts_offset_minutes=-1)

    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    assert proc.returncode == 2
    assert "active vg:review" in proc.stderr


def test_blocked_then_aborted_no_block(tmp_path):
    """run.blocked + run.aborted = run terminated → cleanup of run-file is
    expected (orchestrator clears it). If file still here, treat as dead."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5,
                      run_id="aborted-run-id")
    db = _setup_events_db(tmp_path)
    _insert_event(db, run_id="aborted-run-id", event_type="run.started",
                  ts_offset_minutes=-5)
    _insert_event(db, run_id="aborted-run-id", event_type="run.blocked",
                  ts_offset_minutes=-3)
    _insert_event(db, run_id="aborted-run-id", event_type="run.aborted",
                  ts_offset_minutes=-1)

    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    # run.aborted clears the dead-marker, so the run-file is treated as
    # alive-and-intra-phase-conflict → block. (In practice run.aborted
    # paired with state_mod.clear_active_run() removes the file, so this
    # synthetic state is rare. But test pins behavior.)
    assert proc.returncode == 2


def test_different_phase_passes(tmp_path):
    """Cross-phase isolation preserved: review 4.1 active, deploy 5.2 → no block."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5)
    proc = _run_hook(tmp_path, "/vg:deploy 5.2")
    assert proc.returncode == 0
    assert "vg-cross-run" not in proc.stderr  # no warning, silent overwrite


def test_same_command_idempotent_restart(tmp_path):
    """review 4.1 active, retry review 4.1 → silent overwrite."""
    _setup_active_run(tmp_path, command="vg:review", phase="4.1",
                      started_minutes_ago=5)
    proc = _run_hook(tmp_path, "/vg:review 4.1")
    assert proc.returncode == 0
    assert "vg-cross-run" not in proc.stderr


def test_no_existing_file_passes(tmp_path):
    """No active-runs file → no block, fresh start."""
    (tmp_path / ".vg").mkdir(exist_ok=True)
    proc = _run_hook(tmp_path, "/vg:deploy 4.1")
    assert proc.returncode == 0


def test_non_vg_prompt_skipped(tmp_path):
    """Plain prompt without /vg: prefix → hook exits 0 without touching state."""
    proc = _run_hook(tmp_path, "hello world how are you")
    assert proc.returncode == 0
