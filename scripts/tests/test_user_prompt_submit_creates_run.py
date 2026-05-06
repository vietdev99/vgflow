import json, os, shutil, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-user-prompt-submit.sh"
REPO_ROOT = Path(__file__).resolve().parents[2]

def _install_continuation_scripts(root: Path) -> None:
    target = root / ".claude" / "scripts"
    (target / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "scripts" / "build-continuation.py", target / "build-continuation.py")
    shutil.copyfile(REPO_ROOT / "scripts" / "lib" / "build_continuation.py", target / "lib" / "build_continuation.py")


def test_user_prompt_creates_active_run_for_vg_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg").mkdir()
    payload = json.dumps({"prompt": "/vg:blueprint 2"})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0, result.stderr
    run_file = tmp_path / ".vg/active-runs/sess-test.json"
    assert run_file.exists()
    state = json.loads(run_file.read_text())
    assert state["command"] == "vg:blueprint"
    assert state["phase"] == "2"


def test_user_prompt_no_op_for_non_vg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg").mkdir()
    payload = json.dumps({"prompt": "explain this code"})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0
    run_file = tmp_path / ".vg/active-runs/sess-test.json"
    assert not run_file.exists()

def test_user_prompt_continue_uses_build_continuation_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _install_continuation_scripts(tmp_path)
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)
    (phase_dir / ".build-continuation.json").write_text(json.dumps({
        "schema": "vg.build-continuation.v1",
        "status": "pending",
        "command": "vg:build",
        "phase": "4.2",
        "phase_dir": str(phase_dir),
        "current_wave": 1,
        "next_wave": 2,
        "max_wave": 3,
        "canonical_command": "/vg:build 4.2 --wave 2 --resume",
    }), encoding="utf-8")

    payload = json.dumps({"prompt": "tiếp tục"})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0
    assert "Canonical command: /vg:build 4.2 --wave 2 --resume" in result.stderr
    assert "vg-build-continuation" in result.stderr


def test_user_prompt_blocks_conflicting_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg/active-runs").mkdir(parents=True)
    Path(".vg/active-runs/sess-test.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:build", "phase": "2",
    }))
    payload = json.dumps({"prompt": "/vg:blueprint 2"})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 2
    assert "active run" in result.stderr.lower() or "vg:build" in result.stderr


def test_user_prompt_allows_unrelated_phase_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg/active-runs").mkdir(parents=True)
    Path(".vg/active-runs/sess-test.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:build", "phase": "2",
    }))
    payload = json.dumps({"prompt": "/vg:blueprint 3"})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-test"},
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(Path(".vg/active-runs/sess-test.json").read_text())
    assert state["command"] == "vg:blueprint"
    assert state["phase"] == "3"
