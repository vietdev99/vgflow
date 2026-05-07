"""Regression — bash hooks never fall back to literal "default" session id.

Issue #113: when CLAUDE_HOOK_SESSION_ID env was unset, every hook
resolved session_id to "default" and routed state writes to the shared
.vg/active-runs/default.json slot. Parallel Claude Code sessions then
clobbered each other's run state.

Fix: scripts/hooks/_lib.sh exposes vg_resolve_session_id which:
  1. Reads env vars (CLAUDE_HOOK_SESSION_ID, CLAUDE_SESSION_ID, etc).
  2. Falls back to .vg/.session-context.json (auto-migrating legacy
     "default" to a per-run synthetic id).
  3. Returns "unknown" instead of "default" when nothing else available.

Plus: prompt-submit's slash branch synthesizes session-unknown-<rid_prefix>
when resolved sid is "unknown", so two parallel env-unset sessions land
on distinct files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import HOOK_DIR, REPO_ROOT, _bash_exe, _bash_path

LIB_PATH = HOOK_DIR / "_lib.sh"


def _resolve(workspace: Path, env_extra: dict | None = None) -> str:
    """Source _lib.sh in a clean shell and return vg_resolve_session_id output."""
    env = os.environ.copy()
    # Clear all session env vars to test the fallback path.
    for var in (
        "CLAUDE_HOOK_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CODEX_SESSION_ID",
    ):
        env.pop(var, None)
    if env_extra:
        env.update(env_extra)
    cmd = f'. "{_bash_path(LIB_PATH)}" && vg_resolve_session_id'
    result = subprocess.run(
        [_bash_exe(), "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        cwd=workspace,
        timeout=10,
    )
    assert result.returncode == 0, f"helper failed: {result.stderr!r}"
    return result.stdout.strip()


def test_resolve_returns_env_when_set(tmp_path):
    sid = _resolve(tmp_path, env_extra={"CLAUDE_HOOK_SESSION_ID": "abc-123"})
    assert sid == "abc-123"


def test_resolve_returns_unknown_when_no_env_no_context(tmp_path):
    """No env, no session-context.json → 'unknown', NEVER 'default'."""
    sid = _resolve(tmp_path)
    assert sid == "unknown", f"expected 'unknown' fallback, got {sid!r}"
    assert sid != "default"


def test_resolve_uses_context_session_id(tmp_path):
    """Valid (non-default) session-context.json wins when env unset."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / ".session-context.json").write_text(
        json.dumps({"session_id": "ctx-sid-99", "run_id": "rid-1"})
    )
    sid = _resolve(tmp_path)
    assert sid == "ctx-sid-99"


def test_resolve_migrates_legacy_default_in_context(tmp_path):
    """Legacy 'default' sentinel auto-migrates to session-unknown-<rid>."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    ctx_path = vg_dir / ".session-context.json"
    ctx_path.write_text(json.dumps({
        "session_id": "default",
        "run_id": "abcdef12-3456-7890-1234-567890abcdef",
        "command": "vg:test",
        "phase": "1.0",
    }))

    sid = _resolve(tmp_path)
    assert sid == "session-unknown-abcdef12", f"got {sid!r}"

    migrated = json.loads(ctx_path.read_text())
    assert migrated["session_id"] == "session-unknown-abcdef12"


def test_resolve_renames_orphan_default_active_run(tmp_path):
    """Migration also renames orphan default.json to session-keyed file."""
    vg_dir = tmp_path / ".vg"
    runs_dir = vg_dir / "active-runs"
    runs_dir.mkdir(parents=True)
    rid = "deadbeef-1111-2222-3333-444455556666"
    (vg_dir / ".session-context.json").write_text(json.dumps({
        "session_id": "default",
        "run_id": rid,
    }))
    legacy = runs_dir / "default.json"
    legacy.write_text(json.dumps({
        "run_id": rid,
        "command": "vg:test",
        "phase": "1.0",
        "session_id": "default",
    }))

    sid = _resolve(tmp_path)
    expected_sid = f"session-unknown-{rid[:8]}"
    assert sid == expected_sid

    new_path = runs_dir / f"{expected_sid}.json"
    assert new_path.exists(), "session-keyed file should exist after migration"
    assert not legacy.exists(), "legacy default.json should be renamed away"


def test_resolve_default_with_no_run_id_falls_back_to_unknown(tmp_path):
    """Edge: 'default' in context but no run_id → can't synthesize, return unknown."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / ".session-context.json").write_text(json.dumps({
        "session_id": "default",
    }))
    sid = _resolve(tmp_path)
    assert sid == "unknown"


def test_sweep_orphan_default_archives_when_twin_matches(tmp_path):
    """vg_sweep_orphan_default: default.json archived when sibling has same run_id."""
    runs = tmp_path / ".vg" / "active-runs"
    runs.mkdir(parents=True)
    rid = "9d5314b4-0d19-44db-8882-9b980d1bf31d"
    sid = "real-session-xyz"
    (runs / "default.json").write_text(json.dumps({
        "run_id": rid, "session_id": sid, "command": "vg:build",
    }))
    (runs / f"{sid}.json").write_text(json.dumps({
        "run_id": rid, "session_id": sid, "command": "vg:build",
        "tasklist_projected": True,
    }))

    cmd = f'. "{_bash_path(LIB_PATH)}" && vg_sweep_orphan_default'
    result = subprocess.run(
        [_bash_exe(), "-c", cmd],
        capture_output=True, text=True, cwd=tmp_path, timeout=10,
    )
    assert result.returncode == 0, result.stderr

    assert not (runs / "default.json").exists(), \
        "orphan default.json should be archived"
    assert (runs / f"{sid}.json").exists(), "live sibling preserved"
    baks = list(runs.glob("default.json.orphan-bak-*"))
    assert len(baks) == 1, f"expected one orphan-bak, got {baks}"


def test_sweep_preserves_default_when_no_twin(tmp_path):
    """vg_sweep_orphan_default: no sibling → no archive (cautious)."""
    runs = tmp_path / ".vg" / "active-runs"
    runs.mkdir(parents=True)
    (runs / "default.json").write_text(json.dumps({
        "run_id": "abc", "session_id": "lonely-sid",
    }))

    cmd = f'. "{_bash_path(LIB_PATH)}" && vg_sweep_orphan_default'
    subprocess.run(
        [_bash_exe(), "-c", cmd],
        capture_output=True, text=True, cwd=tmp_path, timeout=10,
    )
    assert (runs / "default.json").exists(), \
        "default.json must be preserved when no sibling exists"


def test_sweep_preserves_default_when_twin_run_id_diverges(tmp_path):
    """vg_sweep_orphan_default: sibling exists but different run_id → preserve."""
    runs = tmp_path / ".vg" / "active-runs"
    runs.mkdir(parents=True)
    sid = "real-session-xyz"
    (runs / "default.json").write_text(json.dumps({
        "run_id": "RID-A", "session_id": sid,
    }))
    (runs / f"{sid}.json").write_text(json.dumps({
        "run_id": "RID-B", "session_id": sid,
    }))

    cmd = f'. "{_bash_path(LIB_PATH)}" && vg_sweep_orphan_default'
    subprocess.run(
        [_bash_exe(), "-c", cmd],
        capture_output=True, text=True, cwd=tmp_path, timeout=10,
    )
    assert (runs / "default.json").exists(), \
        "divergent run_id → preserve default.json (cautious)"


def test_python_resolver_matches_bash_when_hook_env_set(tmp_path, monkeypatch):
    """Regression: python state._session_id_from_env honours CLAUDE_HOOK_SESSION_ID
    so trace writes from bash hooks land on the same run_id slot as state writes
    from python (run-start, mark-step, tasklist-projected). Pre-fix the bash
    resolver checked CLAUDE_HOOK_SESSION_ID first while python skipped it; the
    mismatch caused tasklist-projected evidence and TaskCreate trace to land in
    different run dirs, failing the run-complete contract validator with
    'evidence missing'.
    """
    import importlib.util
    import sys

    orchestrator_dir = REPO_ROOT / "scripts" / "vg-orchestrator"
    monkeypatch.syspath_prepend(str(orchestrator_dir))
    spec = importlib.util.spec_from_file_location(
        "vg_state_parity", orchestrator_dir / "state.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_state_parity"] = mod
    spec.loader.exec_module(mod)

    # Clear all session env vars, then set ONLY CLAUDE_HOOK_SESSION_ID.
    for v in (
        "CLAUDE_HOOK_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CODEX_SESSION_ID",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CLAUDE_HOOK_SESSION_ID", "hook-only-sid-42")

    py_sid = mod._session_id_from_env()
    bash_sid = _resolve(tmp_path, env_extra={"CLAUDE_HOOK_SESSION_ID": "hook-only-sid-42"})
    assert py_sid == "hook-only-sid-42", f"python skipped CLAUDE_HOOK_SESSION_ID: {py_sid!r}"
    assert bash_sid == "hook-only-sid-42"
    assert py_sid == bash_sid, "python+bash resolvers must agree on session_id"


def test_python_resolver_prefers_hook_env_over_session_env(monkeypatch):
    """When BOTH CLAUDE_HOOK_SESSION_ID and CLAUDE_SESSION_ID are set, hook env
    wins — matches bash priority order. Edge case: Claude Code populates
    CLAUDE_SESSION_ID from a stale prior session while CLAUDE_HOOK_SESSION_ID
    reflects the live hook fire. Hook env is canonical inside hook context.
    """
    import importlib.util
    import sys

    orchestrator_dir = REPO_ROOT / "scripts" / "vg-orchestrator"
    monkeypatch.syspath_prepend(str(orchestrator_dir))
    spec = importlib.util.spec_from_file_location(
        "vg_state_priority", orchestrator_dir / "state.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_state_priority"] = mod
    spec.loader.exec_module(mod)

    monkeypatch.setenv("CLAUDE_HOOK_SESSION_ID", "hook-sid-WIN")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-sid-LOSE")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "code-sid-LOSE")
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-sid-LOSE")

    assert mod._session_id_from_env() == "hook-sid-WIN"


def test_state_safe_filename_treats_default_as_unknown(monkeypatch):
    """Python state._safe_session_filename folds 'default' into 'unknown'."""
    import importlib.util
    import sys
    orchestrator_dir = REPO_ROOT / "scripts" / "vg-orchestrator"
    monkeypatch.syspath_prepend(str(orchestrator_dir))
    spec = importlib.util.spec_from_file_location(
        "vg_state", orchestrator_dir / "state.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_state"] = mod
    spec.loader.exec_module(mod)

    assert mod._safe_session_filename("default") == "unknown"
    assert mod._safe_session_filename("real-sid-99") == "real-sid-99"
    assert mod._safe_session_filename("") == "unknown"
    assert mod._safe_session_filename(None) == "unknown"  # type: ignore[arg-type]
    assert mod._is_unknown_orphan_session("default") is True
    assert mod._is_unknown_orphan_session("session-unknown-abcd") is True
    assert mod._is_unknown_orphan_session("real-sid-99") is False
