import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

CONSOLIDATE = ".claude/scripts/bootstrap-consolidate.py"


def _run_check_gate(state_dir: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_BOOTSTRAP_STATE_DIR"] = str(state_dir)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, CONSOLIDATE, "--check-gate", "--json"],
        capture_output=True, text=True, env=env,
    )


def _write_state(state_dir: Path, last_run_ts: float, sessions_since_last: int):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps({"last_run_ts": last_run_ts, "sessions_since_last": sessions_since_last}),
        encoding="utf-8",
    )


def test_first_run_no_state_passes_gate(tmp_path):
    """No state.json -> never run before -> gate OPEN."""
    result = _run_check_gate(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is True
    assert "first run" in payload["reason"].lower() or "no state" in payload["reason"].lower()


def test_under_24h_blocks_gate(tmp_path):
    """Last run 1 hour ago -> gate CLOSED (need 24h+)."""
    one_hour_ago = time.time() - 3600
    _write_state(tmp_path, one_hour_ago, 100)  # plenty of sessions
    result = _run_check_gate(tmp_path)
    assert result.returncode != 0  # rc=1 = gate closed
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is False
    assert "24h" in payload["reason"].lower() or "hour" in payload["reason"].lower()


def test_under_5_sessions_blocks_gate(tmp_path):
    """Last run 26h ago but only 3 sessions -> gate CLOSED (need >5)."""
    over_24h_ago = time.time() - 26 * 3600
    _write_state(tmp_path, over_24h_ago, 3)
    result = _run_check_gate(tmp_path)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is False
    assert "session" in payload["reason"].lower()


def test_both_gates_passed_opens(tmp_path):
    """26h ago + 6 sessions -> gate OPEN."""
    over_24h_ago = time.time() - 26 * 3600
    _write_state(tmp_path, over_24h_ago, 6)
    result = _run_check_gate(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is True


def test_lock_file_present_blocks(tmp_path):
    """Existing .consolidation.lock -> gate CLOSED with lock-message."""
    over_24h_ago = time.time() - 26 * 3600
    _write_state(tmp_path, over_24h_ago, 10)
    (tmp_path / ".consolidation.lock").write_text("pid=12345", encoding="utf-8")
    result = _run_check_gate(tmp_path)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is False
    assert "lock" in payload["reason"].lower()


def test_acquire_lock_writes_lockfile(tmp_path):
    """--acquire-lock subcommand creates lock file with PID."""
    over_24h_ago = time.time() - 26 * 3600
    _write_state(tmp_path, over_24h_ago, 10)
    env = os.environ.copy()
    env["VG_BOOTSTRAP_STATE_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, CONSOLIDATE, "--acquire-lock"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    lock_file = tmp_path / ".consolidation.lock"
    assert lock_file.exists()
    assert "pid=" in lock_file.read_text(encoding="utf-8").lower()


def test_release_lock_removes_lockfile(tmp_path):
    """--release-lock removes the lock file."""
    (tmp_path / ".consolidation.lock").write_text("pid=12345", encoding="utf-8")
    env = os.environ.copy()
    env["VG_BOOTSTRAP_STATE_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, CONSOLIDATE, "--release-lock"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".consolidation.lock").exists()


def test_custom_thresholds_via_env(tmp_path):
    """VG_DREAMS_GATE_HOURS + VG_DREAMS_GATE_SESSIONS override defaults."""
    half_hour_ago = time.time() - 1800
    _write_state(tmp_path, half_hour_ago, 2)
    # Lower thresholds: 0.1 hours + 1 session -> gate should open
    env = os.environ.copy()
    env["VG_BOOTSTRAP_STATE_DIR"] = str(tmp_path)
    env["VG_DREAMS_GATE_HOURS"] = "0.1"
    env["VG_DREAMS_GATE_SESSIONS"] = "1"
    result = subprocess.run(
        [sys.executable, CONSOLIDATE, "--check-gate", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["gate_open"] is True
