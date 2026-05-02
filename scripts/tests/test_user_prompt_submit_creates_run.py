import json, os, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-user-prompt-submit.sh"


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


def test_user_prompt_blocks_conflicting_active_run(tmp_path, monkeypatch):
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
    assert result.returncode == 2
    assert "active run" in result.stderr.lower() or "vg:build" in result.stderr
