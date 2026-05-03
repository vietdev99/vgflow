"""
Phase F v2.5 (2026-04-23) — .build-progress.json schema extension tests.

Validates:
  - vg_build_progress_commit_task accepts verification fields
    (typecheck, test_summary, wave_verify, run_id) as optional args
  - Entry in tasks_committed[] includes these fields when supplied
  - vg_build_progress_is_task_fully_verified returns yes/no correctly
  - Backward compat: calling without verification args still works
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER    = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "build-progress.sh"


def _run_helper(cmds: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Source the helper then run inline bash commands."""
    env = os.environ.copy()
    # Use bare "python" (Git Bash's PATH) — sys.executable has backslashes + spaces
    # that bash fails to parse. "python" resolves via env PATH inside Git Bash.
    env["PYTHON_BIN"] = "python"
    if env_overrides:
        env.update(env_overrides)
    # Use Git Bash on Windows (WSL bash fails subprocess invocation)
    bash_candidates = [
        "C:/Program Files/Git/bin/bash.exe",  # Windows Git Bash (preferred)
        "/bin/bash",                           # Linux
        "/usr/local/bin/bash",                 # macOS Homebrew
    ]
    bash = None
    for b in bash_candidates:
        if Path(b).exists():
            bash = b
            break
    if not bash:
        pytest.skip("no bash available for helper test")
    wrapped = f'source "{HELPER}"\n{cmds}'
    return subprocess.run(
        [bash, "-c", wrapped],
        capture_output=True, text=True, timeout=15, env=env,
    )


@pytest.fixture
def phase_dir(tmp_path):
    d = tmp_path / "phase-10"
    d.mkdir()
    # Return as POSIX string — Git Bash treats backslashes as escapes
    return d.as_posix()


def test_helper_file_exists():
    assert HELPER.exists()


def test_extended_function_is_fully_verified_declared():
    """vg_build_progress_is_task_fully_verified must be defined in helper."""
    text = HELPER.read_text(encoding="utf-8")
    assert "vg_build_progress_is_task_fully_verified()" in text


def test_commit_task_accepts_verification_args_signature():
    """Verify signature includes typecheck/test/wave_verify/run_id positional args."""
    text = HELPER.read_text(encoding="utf-8")
    # Look for the new parameters in commit_task body
    commit_block = text[text.find("vg_build_progress_commit_task()"):]
    commit_block = commit_block[:commit_block.find("\nvg_build_progress_fail_task")]
    assert "typecheck_status" in commit_block
    assert "test_summary" in commit_block
    assert "wave_verify_status" in commit_block
    assert "run_id" in commit_block


def test_commit_basic_no_verification(phase_dir):
    """Basic commit without verification fields — backward compat."""
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15 16 >/dev/null\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc1234"\n'
        f'cat "{phase_dir}/.build-progress.json"'
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    entry = next(t for t in data["tasks_committed"] if t["task"] == 15)
    assert entry["commit"] == "abc1234"
    # Verification fields absent
    assert "typecheck" not in entry
    assert "test_summary" not in entry
    assert "wave_verify" not in entry


def test_commit_with_all_verification_fields(phase_dir):
    """Commit with typecheck + test_summary + wave_verify + run_id."""
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15 >/dev/null\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc1234" '
        f'"PASS" \'{{"passed":12,"failed":0}}\' "PASS" "run-uuid-abc"\n'
        f'cat "{phase_dir}/.build-progress.json"'
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    entry = next(t for t in data["tasks_committed"] if t["task"] == 15)
    assert entry["commit"] == "abc1234"
    assert entry["typecheck"] == "PASS"
    assert entry["test_summary"]["passed"] == 12
    assert entry["test_summary"]["failed"] == 0
    assert entry["wave_verify"] == "PASS"
    assert entry["run_id"] == "run-uuid-abc"


def test_is_fully_verified_yes_when_typecheck_pass_and_wave_verify_pass(phase_dir):
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc" "PASS" "" "PASS" "rid"\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 15'
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("yes")


def test_is_fully_verified_no_when_typecheck_fail(phase_dir):
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc" "FAIL" "" "PASS" "rid"\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 15'
    )
    assert r.returncode == 0
    assert r.stdout.strip().endswith("no")


def test_is_fully_verified_no_when_wave_verify_fail(phase_dir):
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc" "PASS" "" "FAIL" "rid"\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 15'
    )
    assert r.returncode == 0
    assert r.stdout.strip().endswith("no")


def test_is_fully_verified_yes_wave_verify_skip(phase_dir):
    """wave_verify=SKIP (e.g. docs-only task) + typecheck=PASS still counts as verified."""
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc" "PASS" "" "SKIP" "rid"\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 15'
    )
    assert r.returncode == 0
    assert r.stdout.strip().endswith("yes")


def test_is_fully_verified_no_when_no_verification_fields(phase_dir):
    """Old-style commit (no verification fields) → not fully verified."""
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_commit_task "{phase_dir}" 15 "abc"\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 15'
    )
    assert r.returncode == 0
    assert r.stdout.strip().endswith("no")


def test_is_fully_verified_no_for_unknown_task(phase_dir):
    r = _run_helper(
        f'vg_build_progress_init "{phase_dir}" 1 "tag1" 15\n'
        f'vg_build_progress_is_task_fully_verified "{phase_dir}" 99'
    )
    assert r.returncode == 0
    assert r.stdout.strip().endswith("no")
