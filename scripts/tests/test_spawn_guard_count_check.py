import json, os, subprocess, tempfile
from pathlib import Path


GUARD = Path(__file__).resolve().parents[1] / "vg-agent-spawn-guard.py"


def _setup_run(tmp_path, run_id, expected_tasks, capsule_tasks=None):
    """Stage active-run + wave-spawn-plan + capsule files for each task.

    R2 round-2 (Important-1) — guard enforces capsule existence; tests
    materialize a stub capsule per expected task so happy-path spawns
    pass the new check. Pass capsule_tasks=[] to skip capsule creation
    when the test wants to assert the missing-capsule deny path.
    """
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    (tmp_path / f".vg/runs/{run_id}/.wave-spawn-plan.json").write_text(
        json.dumps({"wave_id": 3, "expected": expected_tasks})
    )
    if capsule_tasks is None:
        capsule_tasks = expected_tasks
    capsule_dir = tmp_path / ".task-capsules"
    capsule_dir.mkdir(parents=True, exist_ok=True)
    for tid in capsule_tasks:
        (capsule_dir / f"{tid}.capsule.json").write_text("{}")


def _spawn(tmp_path, subagent_type, prompt_extra="", capsule_path=None):
    """Invoke guard with given Agent tool input, return (rc, stderr).

    capsule_path defaults to the canonical .task-capsules/task-04.capsule.json
    so existing tests stay green; pass an explicit value (or empty
    string) to exercise capsule-gate behavior.
    """
    if capsule_path is None:
        capsule_path = ".task-capsules/task-04.capsule.json"
    capsule_line = (
        f"capsule_path={capsule_path}\n" if capsule_path else ""
    )
    payload = {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": subagent_type,
            "prompt": f"task_id=task-04\n{capsule_line}{prompt_extra}",
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


def test_spawn_deny_writes_block_file_with_compact_stderr(tmp_path, monkeypatch):
    """R2 round-2 Important-3 — deny path writes .vg/blocks/<run_id>/<gate>.md
    AND emits a 3-line compact stderr summary (not the full multi-paragraph
    reason). Mirrors the pattern in vg-pre-tool-use-agent.sh + vg-stop.sh.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "run-block-file"
    _setup_run(tmp_path, run_id, expected_tasks=["task-04"])
    # Force task_id-not-in-remaining deny to exercise the block-file path.
    rc, stderr = _spawn(
        tmp_path, "vg-build-task-executor", "task_id=task-99",
    )
    assert rc != 0
    block_dir = tmp_path / ".vg" / "blocks" / run_id
    files = sorted(block_dir.glob("*.md")) if block_dir.exists() else []
    assert files, f"expected .vg/blocks/{run_id}/<gate>.md to exist; found nothing"
    block_text = files[0].read_text()
    assert "Block diagnostic" in block_text
    assert "Required fix" in block_text
    # Compact stderr: 3 lines max + colored title + "Read ... for full diagnostic"
    err_lines = [l for l in stderr.splitlines() if l.strip()]
    assert len(err_lines) <= 4, f"stderr should be compact ≤4 lines, got {len(err_lines)}: {err_lines}"
    assert any("Read" in l and ".vg/blocks" in l for l in err_lines), \
        f"stderr must point at block file; lines={err_lines}"


def test_spawn_capsule_missing_blocks(tmp_path, monkeypatch):
    """R2 round-2 Important-1 — capsule absent on disk → spawn DENIED.

    build.md HARD-GATE promises this; previously only subagent_type +
    task_id were checked.
    """
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-cap-1", expected_tasks=["task-04"], capsule_tasks=[])
    rc, stderr = _spawn(
        tmp_path, "vg-build-task-executor",
        capsule_path=".task-capsules/task-04.capsule.json",
    )
    assert rc != 0
    assert "capsule" in stderr.lower()


def test_spawn_capsule_path_missing_in_prompt_blocks(tmp_path, monkeypatch):
    """No capsule_path in rendered prompt → DENIED with concrete fix hint."""
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, "run-cap-2", expected_tasks=["task-04"])
    rc, stderr = _spawn(
        tmp_path, "vg-build-task-executor", capsule_path="",  # omit
    )
    assert rc != 0
    assert "capsule_path" in stderr.lower() or "capsule" in stderr.lower()


def test_spawn_count_resets_when_wave_rolls_forward(tmp_path, monkeypatch):
    """R2 round-2 E1 critical-1 regression — when waves-overview overwrites
    .wave-spawn-plan.json for wave 2 but wave 1's .spawn-count.json still
    sits with remaining=[], the next spawn must NOT be denied against the
    stale empty queue. Guard must rebuild count from the new plan when
    wave_id (or expected[]) shifts.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "run-rollforward"
    _setup_run(tmp_path, run_id, expected_tasks=["task-04"])  # wave 2 plan

    # Write a stale count from wave 1 — exhausted queue.
    count_path = tmp_path / f".vg/runs/{run_id}/.spawn-count.json"
    count_path.write_text(
        json.dumps({
            "wave_id": 1,
            "expected": ["task-01", "task-02"],
            "spawned": ["task-01", "task-02"],
            "remaining": [],
        })
    )
    # Plan wave_id=3 (test fixture) differs from stale count wave_id=1.
    rc, stderr = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc == 0, f"guard should allow after wave_id roll-forward; stderr={stderr!r}"
    rebuilt = json.loads(count_path.read_text())
    assert rebuilt["wave_id"] == 3
    assert rebuilt["spawned"] == ["task-04"]
    assert rebuilt["remaining"] == []


def test_spawn_count_fails_closed_when_wave_plan_missing(tmp_path, monkeypatch):
    """R2 round-3 (Important-1 / C5-E1) — vg-build-task-executor spawn must
    DENY when .wave-spawn-plan.json is absent for an active VG run.
    Previously the guard returned None (allow), letting blind executors
    through. The entry build.md HARD-GATE promises this guard enforces
    wave-plan attribution; missing plan = no enforcement = fail-closed.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "run-no-plan"
    # Stage active run, but NOT the wave-spawn-plan.
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    rc, stderr = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc != 0, "spawn must be denied when wave-spawn-plan missing"
    assert "wave-spawn-plan" in stderr.lower() or "plan-missing" in stderr.lower()


def test_spawn_count_fails_closed_when_wave_plan_unparseable(tmp_path, monkeypatch):
    """R2 round-3 — corrupt .wave-spawn-plan.json → spawn DENIED."""
    monkeypatch.chdir(tmp_path)
    run_id = "run-bad-plan"
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build", "session_id": "test-session"})
    )
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    (tmp_path / f".vg/runs/{run_id}/.wave-spawn-plan.json").write_text("{not-json")
    rc, stderr = _spawn(tmp_path, "vg-build-task-executor", "task_id=task-04")
    assert rc != 0, "spawn must be denied when wave-spawn-plan unparseable"
    assert "unparseable" in stderr.lower() or "plan-unparseable" in stderr.lower()
