"""Tasks 28-32 diagnostic-v2 libraries — core contract tests.

Hook wiring tests (events.db integration) deferred to follow-up; this file
validates the pure-logic surface so the libraries land green and downstream
tasks can import them.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


# -------- Task 28: block_dedupe --------

def test_block_dedupe_returns_closed_when_no_db(tmp_path: Path) -> None:
    from block_dedupe import has_open_block
    is_open, count = has_open_block("run-x", "gate-y", repo_root=tmp_path)
    assert is_open is False
    assert count == 0


def test_block_dedupe_detects_open_after_fired(tmp_path: Path) -> None:
    from block_dedupe import has_open_block
    db = tmp_path / ".vg" / "events.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT, event_type TEXT,
                              ts TEXT, payload_json TEXT)
    """)
    conn.execute("INSERT INTO events (run_id, event_type, ts, payload_json) VALUES (?, ?, ?, ?)",
                 ("run-1", "vg.block.fired", "2026-05-04T10:00:00Z",
                  '{"gate":"Stop-runtime-contract"}'))
    conn.commit()
    conn.close()
    is_open, count = has_open_block("run-1", "Stop-runtime-contract", repo_root=tmp_path)
    assert is_open is True
    assert count == 1


def test_block_dedupe_closes_after_handled(tmp_path: Path) -> None:
    from block_dedupe import has_open_block
    db = tmp_path / ".vg" / "events.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT, event_type TEXT,
                              ts TEXT, payload_json TEXT)
    """)
    conn.execute("INSERT INTO events (run_id, event_type, ts, payload_json) VALUES (?, ?, ?, ?)",
                 ("run-2", "vg.block.fired", "2026-05-04T10:00:00Z", '{"gate":"g"}'))
    conn.execute("INSERT INTO events (run_id, event_type, ts, payload_json) VALUES (?, ?, ?, ?)",
                 ("run-2", "vg.block.handled", "2026-05-04T10:01:00Z", '{"gate":"g"}'))
    conn.commit()
    conn.close()
    is_open, count = has_open_block("run-2", "g", repo_root=tmp_path)
    assert is_open is False
    assert count == 1  # still records that 1 fire happened


# -------- Task 29: block_severity --------

def test_severity_default_is_error() -> None:
    from block_severity import normalize, DEFAULT_SEVERITY
    assert normalize(None) == DEFAULT_SEVERITY
    assert normalize("") == DEFAULT_SEVERITY
    assert normalize("nonsense") == DEFAULT_SEVERITY


def test_severity_lowercase_preserved() -> None:
    from block_severity import normalize
    assert normalize("WARN") == "warn"
    assert normalize("  Error  ") == "error"
    assert normalize("Critical") == "critical"


def test_severity_warn_does_not_exit() -> None:
    from block_severity import behavior
    b = behavior("warn")
    assert b.exits_stop_hook is False
    assert b.requires_handled is False


def test_severity_error_default_exits() -> None:
    from block_severity import behavior
    b = behavior(None)  # default
    assert b.severity == "error"
    assert b.exits_stop_hook is True
    assert b.requires_handled is True


def test_severity_critical_forces_user_question() -> None:
    from block_severity import behavior
    b = behavior("critical")
    assert b.forces_user_question is True


def test_severity_escalate_critical_on_refire() -> None:
    from block_severity import should_escalate
    assert should_escalate("critical", 2) is True
    assert should_escalate("critical", 1) is False
    assert should_escalate("error", 5) is False
    assert should_escalate("warn", 5) is False


# -------- Task 30: block_context --------

def test_context_resolve_with_only_hook_name() -> None:
    from block_context import resolve
    out = resolve(hook_name="/path/to/vg-pre-tool-use-bash.sh")
    assert out["hook_source"] == "vg-pre-tool-use-bash.sh"
    assert "command" not in out


def test_context_resolve_no_db_returns_empty(tmp_path: Path) -> None:
    from block_context import resolve
    out = resolve(run_id="ghost", repo_root=tmp_path)
    assert out == {}


def test_context_resolves_command_skill_path(tmp_path: Path) -> None:
    from block_context import resolve
    db = tmp_path / ".vg" / "events.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, command TEXT, phase TEXT)
    """)
    conn.execute("INSERT INTO runs (run_id, command, phase) VALUES (?, ?, ?)",
                 ("r-1", "vg:build", "9.9.9"))
    conn.execute("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT, event_type TEXT,
                              ts TEXT, payload_json TEXT)
    """)
    conn.execute("INSERT INTO events (run_id, event_type, ts, payload_json) VALUES (?, ?, ?, ?)",
                 ("r-1", "build.step_active", "2026-05-04T10:00:00Z",
                  '{"step":"5_post_execution"}'))
    conn.commit()
    conn.close()
    out = resolve(run_id="r-1", repo_root=tmp_path)
    assert out["command"] == "vg:build"
    assert out["phase"] == "9.9.9"
    assert out["step"] == "5_post_execution"
    # Step-specific override beats top-level command skill
    assert out["skill_path"] == "commands/vg/_shared/build/post-execution-overview.md"


# -------- Task 32: block_correlate --------

def test_correlate_handles_missing_db(tmp_path: Path) -> None:
    from block_correlate import correlate
    md = correlate(repo_root=tmp_path, window_spec="24h")
    assert "# Block Correlation Report" in md
    assert "events.db not found" in md


def test_correlate_parse_window() -> None:
    from block_correlate import _parse_window
    from datetime import timedelta
    assert _parse_window("24h") == timedelta(hours=24)
    assert _parse_window("7d") == timedelta(days=7)
    assert _parse_window("90m") == timedelta(minutes=90)
    assert _parse_window("garbage") == timedelta(hours=24)
    assert _parse_window("") == timedelta(hours=24)


def test_correlate_recurring_section(tmp_path: Path) -> None:
    """3 runs of same gate within window → 1 RECURRING finding."""
    from block_correlate import correlate
    db = tmp_path / ".vg" / "events.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT, event_type TEXT,
                              ts TEXT, payload_json TEXT, command TEXT)
    """)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for run in ("a", "b", "c"):
        conn.execute("INSERT INTO events (run_id, event_type, ts, payload_json) VALUES (?, ?, ?, ?)",
                     (run, "vg.block.fired", now, '{"gate":"slow-gate"}'))
    conn.commit()
    conn.close()
    md = correlate(repo_root=tmp_path, window_spec="24h", min_runs=3)
    assert "slow-gate" in md
    assert "RECURRING" in md
    assert "× 3 fires in 3 runs" in md
