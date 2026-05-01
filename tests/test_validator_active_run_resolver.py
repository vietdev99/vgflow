"""Tests for _common.read_active_run_id — the multi-session run_id resolver
introduced to close the .vg/current-run.json overwrite race.

Exercises all 4 resolution tiers + the foreign-session fall-through.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validators"))

import _common  # noqa: E402


def _setup_repo(tmp_path: Path) -> Path:
    """Create a minimal .vg/ tree under tmp_path."""
    vg = tmp_path / ".vg"
    vg.mkdir(parents=True, exist_ok=True)
    (vg / "active-runs").mkdir(exist_ok=True)
    return tmp_path


def _clear_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


def test_returns_none_when_repo_empty(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    _clear_session_env(monkeypatch)
    assert _common.read_active_run_id(repo_root=tmp_path) is None


def test_legacy_snapshot_with_no_session_field_is_trusted(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    _clear_session_env(monkeypatch)
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-legacy"}), encoding="utf-8"
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-legacy"


def test_legacy_snapshot_with_matching_session_is_trusted(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-mine", "session_id": "session-A"}),
        encoding="utf-8",
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-mine"


def test_legacy_snapshot_from_foreign_session_falls_through(tmp_path, monkeypatch):
    """The bug this resolver fixes: foreign session overwrote the global
    pointer — pre-fix validators read the wrong run_id.
    """
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    # Foreign session B's run_id is in legacy snapshot
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-foreign", "session_id": "session-B"}),
        encoding="utf-8",
    )
    # No per-session file, no DB → resolver returns None (NOT rid-foreign)
    assert _common.read_active_run_id(repo_root=tmp_path) is None


def test_per_session_file_beats_legacy_snapshot(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    (tmp_path / ".vg" / "active-runs" / "session-A.json").write_text(
        json.dumps({"run_id": "rid-mine", "command": "vg:build"}),
        encoding="utf-8",
    )
    # Even with a foreign legacy snapshot, per-session wins
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-foreign", "session_id": "session-B"}),
        encoding="utf-8",
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-mine"


def test_unknown_sentinel_in_legacy_is_trusted(tmp_path, monkeypatch):
    """Subshells without CLAUDE_SESSION_ID write 'unknown' — Stop hook
    must still see the run via legacy fallback.
    """
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-orphan", "session_id": "unknown"}),
        encoding="utf-8",
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-orphan"


def test_session_id_with_non_alphanumeric_is_normalized(tmp_path, monkeypatch):
    """Filename safety: session ids with /, ., :, etc. must be sanitized
    before being used as a filename component.
    """
    _setup_repo(tmp_path)
    # Real Claude session ids look like UUIDs (alphanumeric + dash) but
    # tests cover hostile input too. Underscore + dash are allowed; dots and
    # slashes get stripped.
    monkeypatch.setenv("CLAUDE_SESSION_ID", "abc.def/ghi-jkl_mno")
    safe_sid = "abcdefghi-jkl_mno"  # dots + slashes stripped
    (tmp_path / ".vg" / "active-runs" / f"{safe_sid}.json").write_text(
        json.dumps({"run_id": "rid-sanitized"}), encoding="utf-8"
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-sanitized"


def test_empty_run_id_in_per_session_falls_through(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    # Per-session file exists but no run_id field
    (tmp_path / ".vg" / "active-runs" / "session-A.json").write_text(
        json.dumps({"command": "vg:build"}), encoding="utf-8"
    )
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-legacy", "session_id": "session-A"}),
        encoding="utf-8",
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-legacy"


def test_corrupt_json_falls_through(tmp_path, monkeypatch):
    _setup_repo(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "session-A")
    (tmp_path / ".vg" / "active-runs" / "session-A.json").write_text(
        "not-json{", encoding="utf-8"
    )
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "rid-legacy", "session_id": "session-A"}),
        encoding="utf-8",
    )
    assert _common.read_active_run_id(repo_root=tmp_path) == "rid-legacy"
