import json, os, subprocess
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1].parent / "scripts/hooks/install-hooks.sh"


def test_install_creates_hooks_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    result = subprocess.run(
        ["bash", str(INSTALLER), "--target", str(tmp_path / ".claude/settings.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert "hooks" in settings
    assert "PreToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]
    assert "UserPromptSubmit" in settings["hooks"]
    assert "SessionStart" in settings["hooks"]
    assert "PostToolUse" in settings["hooks"]


def test_install_idempotent_no_duplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    target = str(tmp_path / ".claude/settings.json")
    for _ in range(3):
        subprocess.run(
            ["bash", str(INSTALLER), "--target", target],
            check=True, capture_output=True,
        )
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    pre = settings["hooks"]["PreToolUse"]
    bash_entries = [m for m in pre if m.get("matcher") == "Bash"]
    assert len(bash_entries) == 1, f"expected 1 Bash entry, got {len(bash_entries)}"


def test_install_preserves_existing_user_hooks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".claude").mkdir()
    target = tmp_path / ".claude/settings.json"
    target.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {"matcher": "WebFetch", "hooks": [{"type": "command", "command": "echo user-hook"}]},
            ],
        },
    }))
    subprocess.run(
        ["bash", str(INSTALLER), "--target", str(target)],
        check=True, capture_output=True,
    )
    settings = json.loads(target.read_text())
    matchers = [m.get("matcher") for m in settings["hooks"]["PreToolUse"]]
    assert "WebFetch" in matchers  # user hook preserved
    assert "Bash" in matchers  # VG hook added
