"""R6 Task 15: Build DAG enforcement beyond same-file conflicts."""
import json
import subprocess
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "scripts" / "vg-agent-spawn-guard.py"


def _setup_run(tmp_path, expected_tasks, dag_edges=None):
    """Stage active-run + wave-spawn-plan with optional dag_edges."""
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({
            "run_id": "run-dag",
            "command": "vg:build",
            "session_id": "test-session",
            "phase_dir": str(tmp_path / "phase"),
        })
    )
    (tmp_path / ".vg/runs/run-dag").mkdir(parents=True, exist_ok=True)
    plan = {"wave_id": 1, "expected": expected_tasks}
    if dag_edges:
        plan["dag_edges"] = dag_edges
    (tmp_path / ".vg/runs/run-dag/.wave-spawn-plan.json").write_text(json.dumps(plan))
    # Capsule files (existing pattern — guard enforces capsule existence)
    capsule_dir = tmp_path / ".task-capsules"
    capsule_dir.mkdir(parents=True, exist_ok=True)
    for tid in expected_tasks:
        (capsule_dir / f"{tid}.capsule.json").write_text("{}")
    # Phase dir + fingerprints dir
    (tmp_path / "phase/.fingerprints").mkdir(parents=True, exist_ok=True)


def _spawn_task(tmp_path, task_id, capsule_path=None):
    capsule_path = capsule_path or f".task-capsules/{task_id}.capsule.json"
    payload = {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": "vg-build-task-executor",
            "prompt": f"task_id={task_id}\ncapsule_path={capsule_path}\n",
        },
        "session_id": "test-session",
    }
    proc = subprocess.run(
        ["python3", str(GUARD)],
        input=json.dumps(payload),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


def test_dag_no_deps_allows_any_order(tmp_path, monkeypatch):
    """When task has no depends_on, any spawn order allowed."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, expected_tasks=["task-01", "task-02"])  # no dag_edges
    rc, _ = _spawn_task(tmp_path, "task-01")
    assert rc == 0
    rc, _ = _spawn_task(tmp_path, "task-02")
    assert rc == 0


def test_dag_blocks_spawn_when_upstream_missing_fingerprint(tmp_path, monkeypatch):
    """task-04 depends on task-01,task-03. Spawning task-04 before fingerprints -> deny."""
    monkeypatch.chdir(tmp_path)
    _setup_run(
        tmp_path,
        expected_tasks=["task-01", "task-03", "task-04"],
        dag_edges={"task-04": ["task-01", "task-03"]},
    )
    rc, stderr = _spawn_task(tmp_path, "task-04")
    assert rc != 0
    assert "DAG" in stderr or "depends_on" in stderr or "upstream" in stderr.lower()


def test_dag_allows_spawn_when_upstream_fingerprints_present(tmp_path, monkeypatch):
    """task-04 depends on task-01,task-03. Both fingerprints present -> allow."""
    monkeypatch.chdir(tmp_path)
    _setup_run(
        tmp_path,
        expected_tasks=["task-01", "task-03", "task-04"],
        dag_edges={"task-04": ["task-01", "task-03"]},
    )
    # Stage fingerprints (= upstream committed)
    (tmp_path / "phase/.fingerprints/task-01.fingerprint.md").write_text("done")
    (tmp_path / "phase/.fingerprints/task-03.fingerprint.md").write_text("done")
    rc, _ = _spawn_task(tmp_path, "task-04")
    assert rc == 0


def test_dag_partial_upstream_still_blocks(tmp_path, monkeypatch):
    """task-04 depends on task-01,task-03. Only task-01 done -> still BLOCK (waiting for task-03)."""
    monkeypatch.chdir(tmp_path)
    _setup_run(
        tmp_path,
        expected_tasks=["task-01", "task-03", "task-04"],
        dag_edges={"task-04": ["task-01", "task-03"]},
    )
    (tmp_path / "phase/.fingerprints/task-01.fingerprint.md").write_text("done")
    # task-03 still missing
    rc, stderr = _spawn_task(tmp_path, "task-04")
    assert rc != 0
    assert "task-03" in stderr or "DAG" in stderr or "upstream" in stderr.lower()


def test_dag_upstream_task_not_subject_to_dag_check(tmp_path, monkeypatch):
    """task-01 has no upstream — always spawnable regardless of other tasks' fingerprints."""
    monkeypatch.chdir(tmp_path)
    _setup_run(
        tmp_path,
        expected_tasks=["task-01", "task-04"],
        dag_edges={"task-04": ["task-01"]},
    )
    rc, _ = _spawn_task(tmp_path, "task-01")
    assert rc == 0


def test_waves_overview_parses_depends_on():
    """waves-overview.md Step 6 must collect depends_on and emit dag_edges."""
    ref = Path(__file__).resolve().parents[2] / "commands/vg/_shared/build/waves-overview.md"
    body = ref.read_text()
    assert "depends_on" in body
    assert "dag_edges" in body
