import json, os, subprocess, tempfile
from pathlib import Path


GUARD = Path(__file__).resolve().parents[1] / "vg-agent-spawn-guard.py"


def _setup_run(tmp_path, run_id, expected_tasks):
    """Stage active-run + wave-spawn-plan + empty spawn-count files."""
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    (tmp_path / f".vg/runs/{run_id}/.wave-spawn-plan.json").write_text(
        json.dumps({"wave_id": 3, "expected": expected_tasks})
    )


def _spawn(tmp_path, subagent_type, prompt_extra=""):
    """Invoke guard with given Agent tool input, return (rc, stderr)."""
    payload = {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": subagent_type,
            "prompt": f"task_id=task-04\n{prompt_extra}",
        },
        "session_id": "test-session",
    }
    proc = subprocess.run(
        ["python3", str(GUARD)],
        input=json.dumps(payload),
        cwd=tmp_path,
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stderr


def test_spawn_count_allows_first_n_spawns(tmp_path, monkeypatch):
    """Wave plan expects 5 → first 5 spawns of vg-build-task-executor allowed."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-1", expected_tasks=["task-01", "task-02", "task-03", "task-04", "task-05"])
    rc, _ = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc == 0


def test_spawn_count_denies_unexpected_task(tmp_path, monkeypatch):
    """Wave plan expects task-04 → spawning task-99 (not in plan) blocked."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-2", expected_tasks=["task-01", "task-02", "task-03", "task-04", "task-05"])
    rc, stderr = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-99")
    assert rc != 0
    assert "task-99" in stderr or "not in remaining" in stderr.lower()


def test_spawn_count_preserves_existing_gsd_block(tmp_path, monkeypatch):
    """Regression: gsd-* still denied (pre-existing logic)."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-3", expected_tasks=["task-01"])
    rc, stderr = _spawn(tmp_path, "gsd-executor", "task_id=task-01")
    assert rc != 0
    assert "gsd" in stderr.lower() or "forbidden" in stderr.lower()


def test_spawn_count_no_active_run_allows(tmp_path, monkeypatch):
    """No active VG run → spawn allowed (guard only enforces during active run)."""
    monkeypatch.chdir(tmp_path)
    rc, _ = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc == 0
