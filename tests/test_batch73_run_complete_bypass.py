"""tests/test_batch73_run_complete_bypass.py — B73 issue #189 fix.

Issue #189: PreToolUse-tasklist hook blocks `vg-orchestrator run-complete`
when the tasklist contract was re-emitted mid-run (contract hash changes)
but the evidence file wasn't refreshed (stale checksum). Build commits
fine, build.completed event fires, but run-complete is permanently
blocked → active-runs orphaned.

Fix: bypass evidence/checksum verification for `run-complete` action when
events.db has any `*.completed` event for this run_id.

Tests:
  1. cmd_text matches run-complete + events.db has build.completed → exit 0
  2. cmd_text matches run-complete + events.db has test.completed → exit 0
  3. cmd_text matches run-complete + events.db EMPTY → falls through to gate
  4. cmd_text matches step-active (NOT run-complete) → no bypass
  5. cmd_text matches mark-step → no bypass
  6. events.db file missing → falls through to gate
  7. Text presence: hook references issue #189 + B73 marker
  8. Bypass log message present on stderr when triggered
  9. Mirror parity
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"
HOOK_MIRROR = REPO / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


def _seed_run(tmp_path: Path, sid: str, rid: str,
              command: str = "vg:build",
              completed_events: list[str] | None = None) -> dict:
    """Build synthetic .vg/ layout: active-runs, run dir, events.db."""
    project = tmp_path
    (project / ".vg" / "active-runs").mkdir(parents=True, exist_ok=True)
    (project / ".vg" / "active-runs" / f"{sid}.json").write_text(
        json.dumps({
            "session_id": sid,
            "run_id": rid,
            "command": command,
            "phase": "T",
        }),
        encoding="utf-8",
    )
    (project / ".vg" / "runs" / rid).mkdir(parents=True, exist_ok=True)

    # events.db with optional completed event(s).
    db_path = project / ".vg" / "events.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            event_type TEXT,
            payload TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for ev_type in (completed_events or []):
        cur.execute(
            "INSERT INTO events (run_id, event_type, payload) VALUES (?, ?, ?)",
            (rid, ev_type, "{}"),
        )
    conn.commit()
    conn.close()

    return {"project": project, "session_id": sid, "run_id": rid}


def _run_hook(project: Path, sid: str, cmd_text: str) -> subprocess.CompletedProcess:
    """Invoke pre-tool-use hook with PreToolUse JSON on stdin."""
    stdin_obj = {
        "session_id": sid,
        "tool_name": "Bash",
        "tool_input": {"command": cmd_text},
    }
    env = {**os.environ,
           "VG_REPO_ROOT": str(project),
           "VG_HOME": str(REPO / ".claude"),
           "CLAUDE_HOOK_SESSION_ID": sid,
           "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(stdin_obj),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(project),
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Text presence — fix block present in hook.
# ---------------------------------------------------------------------------


def test_b73_hook_has_issue_189_reference():
    body = HOOK.read_text(encoding="utf-8")
    assert "issue #189" in body or "Issue #189" in body
    assert "B73 v4.63.5" in body


def test_b73_hook_checks_events_db_for_completed():
    body = HOOK.read_text(encoding="utf-8")
    assert "events.db" in body
    assert "event_type LIKE '%.completed'" in body
    assert "run-complete" in body


def test_b73_hook_emits_bypass_log_to_stderr():
    body = HOOK.read_text(encoding="utf-8")
    assert "VG run-complete bypass" in body


# ---------------------------------------------------------------------------
# Behavior — bypass fires only on run-complete + completion event.
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path):
    return tmp_path


def test_b73_run_complete_with_build_completed_bypasses(project: Path):
    """The exact issue #189 scenario: run-complete + build.completed → bypass."""
    seed = _seed_run(project, "sid-1", "rid-1",
                     command="vg:build",
                     completed_events=["build.completed"])
    result = _run_hook(project, "sid-1",
                       "python3 ~/.vgflow/scripts/vg-orchestrator run-complete")
    assert result.returncode == 0, (
        f"expected exit 0 (bypass), got {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "bypass" in result.stderr.lower() or "issue #189" in result.stderr.lower()


def test_b73_run_complete_with_test_completed_also_bypasses(project: Path):
    """Pattern is *.completed — test.completed should also trigger bypass."""
    _seed_run(project, "sid-2", "rid-2",
              command="vg:test",
              completed_events=["test.completed"])
    result = _run_hook(project, "sid-2",
                       "vg-orchestrator run-complete")
    assert result.returncode == 0, (
        f"expected exit 0 (bypass on test.completed), got {result.returncode}\n"
        f"stderr={result.stderr!r}"
    )


def test_b73_run_complete_without_completed_event_falls_through(project: Path):
    """No *.completed event → no bypass; hook continues to evidence gate."""
    _seed_run(project, "sid-3", "rid-3",
              command="vg:build",
              completed_events=[])  # no completed events
    result = _run_hook(project, "sid-3",
                       "vg-orchestrator run-complete")
    # Without contract + evidence files, evidence gate fires → exit 2 (block).
    assert result.returncode == 2, (
        f"expected exit 2 (gate fired), got {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_b73_step_active_not_affected_by_bypass(project: Path):
    """Bypass only applies to run-complete. step-active still gated normally."""
    _seed_run(project, "sid-4", "rid-4",
              command="vg:build",
              completed_events=["build.completed"])  # completed present
    result = _run_hook(project, "sid-4",
                       "vg-orchestrator step-active 5_some_step")
    # step-active still gated by evidence (no contract → emit_block).
    assert result.returncode == 2, (
        f"step-active should still be gated even with build.completed event;"
        f" got rc={result.returncode}\nstderr={result.stderr!r}"
    )


def test_b73_mark_step_not_affected_by_bypass(project: Path):
    """mark-step also still gated."""
    _seed_run(project, "sid-5", "rid-5",
              command="vg:build",
              completed_events=["build.completed"])
    result = _run_hook(project, "sid-5",
                       "vg-orchestrator mark-step build 5_step")
    assert result.returncode == 2


def test_b73_events_db_missing_falls_through(project: Path):
    """If events.db doesn't exist (fresh project), no bypass; falls to gate."""
    # Seed run but don't create events.db.
    (project / ".vg" / "active-runs").mkdir(parents=True, exist_ok=True)
    (project / ".vg" / "active-runs" / "sid-6.json").write_text(
        json.dumps({"session_id": "sid-6", "run_id": "rid-6", "command": "vg:build"}),
        encoding="utf-8",
    )
    (project / ".vg" / "runs" / "rid-6").mkdir(parents=True, exist_ok=True)
    # Note: NO events.db
    result = _run_hook(project, "sid-6", "vg-orchestrator run-complete")
    # No events.db → no bypass → gate fires.
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Mirror parity.
# ---------------------------------------------------------------------------


def test_b73_hook_mirror_byte_identical():
    assert HOOK.read_bytes() == HOOK_MIRROR.read_bytes()
