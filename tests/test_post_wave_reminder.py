"""v2.61.0 L2: PostToolUse hook auto-reminder when wave Agent returns + post-step marker missing."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-post-tool-use-agent.sh"


def _bash_exe() -> str:
    """Return a bash that can read Windows paths.
    On Windows, Python subprocess may auto-resolve to WSL bash which cannot
    see D:\\ as /d/. Prefer Git-Bash from `Program Files\\Git\\usr\\bin\\bash.exe`."""
    if sys.platform.startswith("win"):
        for candidate in (
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        ):
            if Path(candidate).exists():
                return candidate
    return "bash"


def _setup_active_run(tmp_path: Path, run_id: str, command: str, phase: str, session_id: str = "test-sess"):
    active_dir = tmp_path / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / f"{session_id}.json").write_text(
        json.dumps({"run_id": run_id, "command": command, "phase": phase}),
        encoding="utf-8",
    )


def _set_final_wave(tmp_path: Path, run_id: str, value: str = "true"):
    runs_dir = tmp_path / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / ".is-final-wave").write_text(value, encoding="utf-8")


def _touch_marker(tmp_path: Path, phase: str, cmd: str, step: str):
    marker_dir = tmp_path / ".vg" / "phases" / phase / ".step-markers" / cmd
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{step}.done").write_text("", encoding="utf-8")


def _run_hook(tmp_path: Path, payload: dict, session_id: str = "test-sess"):
    env = {**os.environ, "CLAUDE_HOOK_SESSION_ID": session_id}
    return subprocess.run(
        [_bash_exe(), str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        env=env, cwd=str(tmp_path),
    )


def test_no_active_run_silent(tmp_path):
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-build-task-executor"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" not in r.stderr


def test_non_wave_subagent_silent(tmp_path):
    _setup_active_run(tmp_path, "rid-001", "vg:build", "7.14")
    _set_final_wave(tmp_path, "rid-001", "true")
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-design-scanner"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" not in r.stderr


def test_wave_subagent_partial_wave_silent(tmp_path):
    """Partial wave (--wave N where N < max): is-final-wave=false → no reminder."""
    _setup_active_run(tmp_path, "rid-002", "vg:build", "7.14")
    _set_final_wave(tmp_path, "rid-002", "false")
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-build-task-executor"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" not in r.stderr


def test_wave_subagent_final_wave_marker_missing_emits(tmp_path):
    """Final wave + post-step marker missing → emit reminder."""
    _setup_active_run(tmp_path, "rid-003", "vg:build", "7.14")
    _set_final_wave(tmp_path, "rid-003", "true")
    # NO marker touched
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-build-task-executor"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" in r.stderr, (
        "must emit reminder when final wave + post-step marker missing"
    )
    assert "vg:build" in r.stderr
    assert "9_post_execution" in r.stderr or "STEP 5" in r.stderr


def test_wave_subagent_marker_present_silent(tmp_path):
    """Marker already touched → no reminder (work done)."""
    _setup_active_run(tmp_path, "rid-004", "vg:build", "7.14")
    _set_final_wave(tmp_path, "rid-004", "true")
    _touch_marker(tmp_path, "7.14", "build", "9_post_execution")
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-build-task-executor"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" not in r.stderr


def test_test_codegen_subagent_emits(tmp_path):
    """Test command wave executor also triggers reminder."""
    _setup_active_run(tmp_path, "rid-005", "vg:test", "7.14")
    # No is-final-wave file — assume final for test (no per-wave concept)
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-test-codegen"},
        "tool_response": {},
    }
    r = _run_hook(tmp_path, payload)
    assert r.returncode == 0
    assert "POST-WAVE REMINDER" in r.stderr
    assert "vg:test" in r.stderr


def test_hook_never_blocks_on_error(tmp_path):
    """Malformed input → exit 0 silently (never block)."""
    r = subprocess.run(
        [_bash_exe(), str(HOOK)],
        input="not-json{{{", capture_output=True, text=True,
        cwd=str(tmp_path), env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "x"},
    )
    assert r.returncode == 0


def test_hook_mirror_byte_identical():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-post-tool-use-agent.sh"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-post-tool-use-agent.sh"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()
