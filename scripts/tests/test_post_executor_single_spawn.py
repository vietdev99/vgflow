"""R6 Task 3: vg-build-post-executor must be hook-enforced as single-spawn-per-run."""
import json, subprocess
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "scripts" / "vg-agent-spawn-guard.py"


def _setup_run(tmp_path, run_id="run-post-1"):
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    return run_id


def _spawn_post_executor(tmp_path):
    payload = {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": "vg-build-post-executor",
            "prompt": "phase=4 verify L2/L3/L5/L6",
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


def test_first_post_executor_spawn_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_id = _setup_run(tmp_path)
    rc, _ = _spawn_post_executor(tmp_path)
    assert rc == 0, "First post-executor spawn must be allowed"
    counter = tmp_path / f".vg/runs/{run_id}/.post-executor-spawns.json"
    assert counter.exists(), "Guard must persist counter on first allow"
    data = json.loads(counter.read_text())
    assert data["count"] == 1


def test_second_post_executor_spawn_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_id = _setup_run(tmp_path)
    # Pre-populate counter as if first spawn already happened
    counter = tmp_path / f".vg/runs/{run_id}/.post-executor-spawns.json"
    counter.write_text(json.dumps({"count": 1, "first_spawn_ts": "2026-05-05T00:00:00Z"}))
    rc, stderr = _spawn_post_executor(tmp_path)
    assert rc != 0, "Second post-executor spawn must be denied"
    assert "post-executor" in stderr.lower() or "overspawn" in stderr.lower() or "already" in stderr.lower()


def test_post_executor_outside_vg_run_passes(tmp_path, monkeypatch):
    """No active VG run -> guard is silent (do not block)."""
    monkeypatch.chdir(tmp_path)
    rc, _ = _spawn_post_executor(tmp_path)
    assert rc == 0, "Outside VG run, guard must let post-executor through"


def test_post_executor_other_subagent_unaffected(tmp_path, monkeypatch):
    """Spawning a different subagent (e.g., general-purpose) doesn't touch post-executor counter."""
    monkeypatch.chdir(tmp_path)
    run_id = _setup_run(tmp_path)
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "general-purpose", "prompt": "any"},
        "session_id": "test-session",
    }
    proc = subprocess.run(
        ["python3", str(GUARD)],
        input=json.dumps(payload), cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    counter = tmp_path / f".vg/runs/{run_id}/.post-executor-spawns.json"
    assert not counter.exists(), "Unrelated subagent must not create post-executor counter"
