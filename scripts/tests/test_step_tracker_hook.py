"""
test_step_tracker_hook.py — v2.7 Phase F coverage for vg-step-tracker.py
PostToolUse Bash hook (Layer 2 marker tracking).

Pins:
1. Touch marker pattern detected (start + done variants).
2. mark_step helper detected.
3. orchestrator mark-step subcommand detected.
4. Non-marker bash commands → no-op (return 0, no state change).
5. session-context updated: current_step + step_history append.
6. step_history dedup: same step touched twice → single entry.
7. Telemetry dedup: same (step, kind) emitted once per session.
8. Missing session-context → no-op (no active /vg:* run).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "vg-step-tracker.py"


def _load_hook(repo_root: Path):
    os.environ["VG_REPO_ROOT"] = str(repo_root)
    spec = importlib.util.spec_from_file_location("st_test", HOOK_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    """Restore VG_REPO_ROOT env var after each test to prevent pollution
    bleed into other test files (e.g. test_tasklist_visibility.py which
    reads env-derived paths). Harness fix 2026-04-26."""
    original = os.environ.get("VG_REPO_ROOT")
    yield
    if original is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original


def _setup_repo(tmp_path: Path, *, ctx: dict | None = None) -> Path:
    vg = tmp_path / ".vg"
    vg.mkdir(parents=True)
    if ctx is not None:
        (vg / ".session-context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )
    return tmp_path


def _drive(mod, hook_input: dict, capsys, monkeypatch) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
    # Stub out telemetry subprocess to avoid invoking real orchestrator.
    monkeypatch.setattr(mod, "_emit_telemetry",
                        lambda evt, payload: None)
    return mod.main()


# ---------------------------------------------------------------------------
# Pattern detection (pure-function tests, no I/O)
# ---------------------------------------------------------------------------


def test_detect_touch_done(tmp_path):
    mod = _load_hook(tmp_path)
    cmd = "touch ${PHASE_DIR}/.step-markers/8_execute_waves.done"
    assert mod._detect_step_transition(cmd) == ("8_execute_waves", "done")


def test_detect_touch_start_with_namespace(tmp_path):
    mod = _load_hook(tmp_path)
    cmd = 'touch "/foo/.step-markers/blueprint/2a_plan.start"'
    assert mod._detect_step_transition(cmd) == ("2a_plan", "start")


def test_detect_mark_step_helper(tmp_path):
    mod = _load_hook(tmp_path)
    cmd = 'mark_step "${PHASE_NUMBER}" "5d_codegen" "${PHASE_DIR}"'
    assert mod._detect_step_transition(cmd) == ("5d_codegen", "mark")


def test_detect_orchestrator_mark_step(tmp_path):
    mod = _load_hook(tmp_path)
    cmd = "python .claude/scripts/vg-orchestrator mark-step build 8_execute_waves"
    assert mod._detect_step_transition(cmd) == ("8_execute_waves", "mark")


def test_detect_no_match(tmp_path):
    mod = _load_hook(tmp_path)
    assert mod._detect_step_transition("echo hello") is None
    assert mod._detect_step_transition("ls -la") is None
    assert mod._detect_step_transition("") is None


# ---------------------------------------------------------------------------
# State updates (with session-context)
# ---------------------------------------------------------------------------


def test_no_active_run_noop(tmp_path, capsys, monkeypatch):
    """No session-context.json → hook returns 0 silently."""
    repo = _setup_repo(tmp_path, ctx=None)
    mod = _load_hook(repo)
    rc = _drive(mod, {
        "tool_name": "Bash",
        "tool_input": {"command": "touch /foo/.step-markers/8.done"},
    }, capsys, monkeypatch)
    assert rc == 0
    # No session-context written
    assert not (repo / ".vg" / ".session-context.json").exists()


def test_marker_done_updates_state(tmp_path, capsys, monkeypatch):
    initial = {
        "run_id": "abc-123", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": None, "step_history": [], "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)
    rc = _drive(mod, {
        "tool_name": "Bash",
        "tool_input": {"command": "touch /x/.step-markers/8_execute_waves.done"},
    }, capsys, monkeypatch)
    assert rc == 0
    ctx = json.loads(
        (repo / ".vg" / ".session-context.json").read_text(encoding="utf-8")
    )
    assert ctx["current_step"] == "8_execute_waves"
    assert len(ctx["step_history"]) == 1
    assert ctx["step_history"][0]["step"] == "8_execute_waves"
    assert ctx["step_history"][0]["transition"] == "done"


def test_history_dedup(tmp_path, capsys, monkeypatch):
    """Touching same step twice → single history entry."""
    initial = {
        "run_id": "abc", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": None, "step_history": [], "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)

    for _ in range(3):
        _drive(mod, {
            "tool_name": "Bash",
            "tool_input": {"command": "touch /x/.step-markers/8.done"},
        }, capsys, monkeypatch)

    ctx = json.loads(
        (repo / ".vg" / ".session-context.json").read_text(encoding="utf-8")
    )
    assert ctx["current_step"] == "8"
    assert len(ctx["step_history"]) == 1, \
        f"expected 1 history entry, got {len(ctx['step_history'])}"


def test_telemetry_dedup(tmp_path, capsys, monkeypatch):
    """Same (step, kind) → telemetry emitted once."""
    initial = {
        "run_id": "abc", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": None, "step_history": [], "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)

    emit_calls = []
    monkeypatch.setattr(mod, "_emit_telemetry",
                        lambda evt, payload: emit_calls.append((evt, payload["step"])))

    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({
                            "tool_name": "Bash",
                            "tool_input": {"command": "touch /x/.step-markers/8.done"},
                        })))
    mod.main()
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({
                            "tool_name": "Bash",
                            "tool_input": {"command": "touch /x/.step-markers/8.done"},
                        })))
    mod.main()
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO(json.dumps({
                            "tool_name": "Bash",
                            "tool_input": {"command": "touch /x/.step-markers/8.done"},
                        })))
    mod.main()

    assert len(emit_calls) == 1, \
        f"expected 1 telemetry emission, got {len(emit_calls)}"


def test_history_preserves_order(tmp_path, capsys, monkeypatch):
    initial = {
        "run_id": "abc", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": None, "step_history": [], "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)

    for step in ["1_load_config", "2a_plan", "8_execute_waves"]:
        _drive(mod, {
            "tool_name": "Bash",
            "tool_input": {"command": f"touch /x/.step-markers/{step}.done"},
        }, capsys, monkeypatch)

    ctx = json.loads(
        (repo / ".vg" / ".session-context.json").read_text(encoding="utf-8")
    )
    assert ctx["current_step"] == "8_execute_waves"
    history_steps = [h["step"] for h in ctx["step_history"]]
    assert history_steps == ["1_load_config", "2a_plan", "8_execute_waves"]


def test_non_bash_tool_skipped(tmp_path, capsys, monkeypatch):
    initial = {
        "run_id": "abc", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": None, "step_history": [], "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)
    rc = _drive(mod, {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x.md"},
    }, capsys, monkeypatch)
    assert rc == 0
    ctx = json.loads(
        (repo / ".vg" / ".session-context.json").read_text(encoding="utf-8")
    )
    assert ctx["current_step"] is None  # unchanged


def test_unparseable_command_noop(tmp_path, capsys, monkeypatch):
    initial = {
        "run_id": "abc", "command": "vg:build", "phase": "7.14.3",
        "started_at": "2026-04-26T14:00:00Z",
        "current_step": "previous_step", "step_history": [],
        "telemetry_emitted": [],
    }
    repo = _setup_repo(tmp_path, ctx=initial)
    mod = _load_hook(repo)
    rc = _drive(mod, {
        "tool_name": "Bash",
        "tool_input": {"command": "echo just normal command"},
    }, capsys, monkeypatch)
    assert rc == 0
    ctx = json.loads(
        (repo / ".vg" / ".session-context.json").read_text(encoding="utf-8")
    )
    assert ctx["current_step"] == "previous_step"  # unchanged
