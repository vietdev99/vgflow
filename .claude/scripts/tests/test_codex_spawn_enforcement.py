"""Tests for Codex spawn evidence and Bash guard enforcement."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDER = REPO_ROOT / "scripts" / "codex-spawn-record.py"
GUARD = REPO_ROOT / "scripts" / "codex-hooks" / "vg-codex-spawn-guard.py"


def _seed_active_run(root: Path, run_id: str, command: str = "vg:build") -> None:
    (root / ".vg").mkdir(parents=True, exist_ok=True)
    (root / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": run_id, "command": command, "phase": "1"}),
        encoding="utf-8",
    )


def _seed_wave_plan(root: Path, run_id: str, expected: list[str]) -> None:
    run_dir = root / ".vg" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / ".wave-spawn-plan.json").write_text(
        json.dumps({"wave_id": 3, "expected": expected}),
        encoding="utf-8",
    )


def _run_guard(root: Path, command: str, session_id: str = "sess-1") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    payload = {
        "session_id": session_id,
        "cwd": str(root),
        "tool_name": "Bash",
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": command},
    }
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def test_codex_spawn_record_preflight_and_record_updates_wave_spawn_count(tmp_path):
    root = tmp_path / "project"
    run_id = "run-codex"
    _seed_active_run(root, run_id)
    _seed_wave_plan(root, run_id, ["task-04"])
    capsule = root / ".task-capsules" / "task-04.capsule.json"
    capsule.parent.mkdir(parents=True)
    capsule.write_text("{}", encoding="utf-8")
    prompt = root / "prompt.md"
    prompt.write_text(
        'task_id: task-04\n<task_context_capsule path=".task-capsules/task-04.capsule.json">\n',
        encoding="utf-8",
    )
    out = root / "out.json"
    out.write_text('{"ok": true}', encoding="utf-8")
    stdout_log = root / "out.stdout.log"
    stderr_log = root / "out.stderr.log"
    stdout_log.write_text("", encoding="utf-8")
    stderr_log.write_text("", encoding="utf-8")

    preflight = subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "preflight",
            "--repo-root",
            str(root),
            "--role",
            "vg-build-task-executor",
            "--prompt-file",
            str(prompt),
            "--task-id",
            "task-04",
            "--wave-id",
            "3",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert preflight.returncode == 0, preflight.stderr

    record = subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "record",
            "--repo-root",
            str(root),
            "--role",
            "vg-build-task-executor",
            "--prompt-file",
            str(prompt),
            "--task-id",
            "task-04",
            "--wave-id",
            "3",
            "--out-file",
            str(out),
            "--stdout-log",
            str(stdout_log),
            "--stderr-log",
            str(stderr_log),
            "--exit-code",
            "0",
            "--tier",
            "executor",
            "--sandbox",
            "workspace-write",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert record.returncode == 0, record.stderr
    count = json.loads((root / ".vg" / "runs" / run_id / ".spawn-count.json").read_text())
    assert count["spawned"] == ["task-04"]
    assert count["remaining"] == []
    manifest = root / ".vg" / "runs" / run_id / ".codex-spawn-manifest.jsonl"
    assert "vg-build-task-executor" in manifest.read_text(encoding="utf-8")


def test_codex_spawn_record_blocks_build_task_without_wave_plan(tmp_path):
    root = tmp_path / "project"
    _seed_active_run(root, "run-missing-plan")
    prompt = root / "prompt.md"
    prompt.write_text("task_id: task-04\ncapsule_path=.task-capsules/task-04.capsule.json\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "preflight",
            "--repo-root",
            str(root),
            "--role",
            "vg-build-task-executor",
            "--prompt-file",
            str(prompt),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 2
    assert "missing wave plan" in result.stderr


def test_codex_bash_guard_blocks_wave_complete_when_spawn_count_missing(tmp_path):
    root = tmp_path / "project"
    run_id = "run-wave"
    _seed_active_run(root, run_id, command="vg:build")
    _seed_wave_plan(root, run_id, ["task-01", "task-02"])
    result = _run_guard(root, "python3 .claude/scripts/vg-orchestrator wave-complete 3")
    assert result.returncode == 2
    assert "spawn-count missing" in result.stderr


def test_codex_bash_guard_blocks_heavy_step_marker_without_spawn_evidence(tmp_path):
    root = tmp_path / "project"
    _seed_active_run(root, "run-test", command="vg:test")
    result = _run_guard(root, "python3 .claude/scripts/vg-orchestrator mark-step test 5d_codegen")
    assert result.returncode == 2
    assert "vg-test-codegen" in result.stderr


def test_codex_bash_guard_allows_heavy_step_marker_with_spawn_evidence(tmp_path):
    root = tmp_path / "project"
    run_id = "run-test-ok"
    _seed_active_run(root, run_id, command="vg:test")
    run_dir = root / ".vg" / "runs" / run_id
    spawn_dir = run_dir / "codex-spawns"
    spawn_dir.mkdir(parents=True)
    out = root / "out.json"
    out.write_text('{"spec_files":["a.spec.ts"],"bindings_satisfied":true}', encoding="utf-8")
    record = {
        "role": "vg-test-codegen",
        "spawn_id": "vg-test-codegen",
        "exit_code": 0,
        "out_file": str(out),
        "out_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    (spawn_dir / "vg-test-codegen--vg-test-codegen.json").write_text(
        json.dumps(record),
        encoding="utf-8",
    )
    (run_dir / ".codex-spawn-manifest.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = _run_guard(root, "python3 .claude/scripts/vg-orchestrator mark-step test 5d_codegen")
    assert result.returncode == 0, result.stderr


def test_codex_bash_guard_blocks_direct_spawn_evidence_write(tmp_path):
    root = tmp_path / "project"
    _seed_active_run(root, "run-forge", command="vg:test")
    command = "printf '{}' > .vg/runs/run-forge/.codex-spawn-manifest.jsonl"
    result = _run_guard(root, command)
    assert result.returncode == 2
    assert "direct Bash write" in result.stderr


def test_codex_bash_guard_allows_read_only_spawn_evidence_inspection(tmp_path):
    root = tmp_path / "project"
    run_id = "run-inspect"
    _seed_active_run(root, run_id, command="vg:test")
    run_dir = root / ".vg" / "runs" / run_id
    spawn_dir = run_dir / "codex-spawns"
    spawn_dir.mkdir(parents=True)
    record_path = spawn_dir / "vg-test-codegen--smoke.json"
    record_path.write_text('{"role":"vg-test-codegen"}', encoding="utf-8")
    (run_dir / ".codex-spawn-manifest.jsonl").write_text(
        '{"role":"vg-test-codegen"}\n',
        encoding="utf-8",
    )

    manifest_read = _run_guard(root, "sed -n '1,20p' .vg/runs/run-inspect/.codex-spawn-manifest.jsonl")
    assert manifest_read.returncode == 0, manifest_read.stderr

    record_read = _run_guard(root, "python3 -m json.tool .vg/runs/run-inspect/codex-spawns/vg-test-codegen--smoke.json")
    assert record_read.returncode == 0, record_read.stderr
