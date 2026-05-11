"""Tests for global Codex hook installation."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "codex-hooks-install.py"


def _installer_module():
    spec = importlib.util.spec_from_file_location("codex_hooks_install", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_hooks_installer_writes_hooks_and_feature_flag(tmp_path):
    root = tmp_path / "vgflow"
    codex_home = tmp_path / "home" / ".codex"
    (root / "scripts" / "codex-hooks").mkdir(parents=True)
    for rel in (
        "scripts/vg-entry-hook.py",
        "scripts/codex-hooks/vg-user-prompt-submit.py",
        "scripts/codex-hooks/vg-pre-tool-use-bash.py",
        "scripts/codex-hooks/vg-pre-tool-use-apply-patch.py",
        "scripts/codex-hooks/vg-post-tool-use-bash.py",
        "scripts/codex-hooks/vg-stop.py",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(INSTALLER), "--codex-home", str(codex_home), "--vg-home", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr

    hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    commands = "\n".join(
        hook.get("command", "")
        for groups in hooks["hooks"].values()
        for group in groups
        for hook in group.get("hooks", [])
    )
    assert "codex-hooks/vg-user-prompt-submit.py" in commands
    assert "vg-entry-hook.py" not in commands
    assert "codex-hooks/vg-pre-tool-use-bash.py" in commands
    assert "codex-hooks/vg-pre-tool-use-apply-patch.py" in commands
    assert "codex-hooks/vg-post-tool-use-bash.py" in commands
    assert "codex-hooks/vg-stop.py" in commands
    assert "^Bash$" in json.dumps(hooks)
    assert "^(apply_patch|Edit|Write)$" in json.dumps(hooks)

    assert ".claude/scripts" not in commands

    config = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert "[features]" in config
    assert "codex_hooks = true" in config

    check = subprocess.run(
        [sys.executable, str(INSTALLER), "--codex-home", str(codex_home), "--vg-home", str(root), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert check.returncode == 0


def test_codex_hooks_merge_preserves_custom_hooks_and_replaces_vg_owned_hooks():
    module = _installer_module()
    root = Path("/home/user/.vgflow")
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "^Bash$",
                    "hooks": [
                        {"type": "command", "command": "python3 custom.py"},
                        {
                            "type": "command",
                            "command": "python3 /repo/.claude/scripts/codex-hooks/vg-pre-tool-use-bash.py",
                        },
                    ],
                }
            ]
        }
    }

    merged = module.merge_hooks(existing, module.desired_hooks(root))
    commands = [
        hook["command"]
        for group in merged["hooks"]["PreToolUse"]
        for hook in group["hooks"]
    ]
    assert "python3 custom.py" in commands
    assert sum("vg-pre-tool-use-bash.py" in command for command in commands) == 1

def test_codex_hooks_installer_replaces_legacy_user_prompt_submit_hook():
    module = _installer_module()
    root = Path("/home/user/.vgflow")
    existing = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /repo/.claude/scripts/vg-entry-hook.py",
                        }
                    ]
                }
            ]
        }
    }

    merged = module.merge_hooks(existing, module.desired_hooks(root))
    commands = [
        hook["command"]
        for group in merged["hooks"]["UserPromptSubmit"]
        for hook in group["hooks"]
    ]
    assert sum("vg-user-prompt-submit.py" in command for command in commands) == 1
    assert not any(command.endswith("vg-entry-hook.py") for command in commands)


def test_codex_hooks_feature_merge_updates_existing_features_section():
    module = _installer_module()
    text = 'model = "gpt-5.4"\n\n[features]\nfoo = true\ncodex_hooks = false # old\n\n[agents.x]\n'
    merged = module.ensure_codex_hooks_feature_text(text)
    assert "foo = true" in merged
    assert "codex_hooks = true # old" in merged
    assert "[agents.x]" in merged
