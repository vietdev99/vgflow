"""Codex hook install must be global-only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "codex-hooks-install.py"
HOOK_LIB = REPO_ROOT / "scripts" / "codex-hooks" / "vg_codex_hook_lib.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_hooks_installer_writes_global_hooks_and_feature_flag(tmp_path):
    codex_home = tmp_path / "home" / ".codex"
    vg_home = tmp_path / "home" / ".vgflow"
    (vg_home / "scripts" / "codex-hooks").mkdir(parents=True)
    for name in (
        "vg-user-prompt-submit.py",
        "vg-pre-tool-use-bash.py",
        "vg-pre-tool-use-apply-patch.py",
        "vg-post-tool-use-bash.py",
        "vg-stop.py",
    ):
        (vg_home / "scripts" / "codex-hooks" / name).write_text("# stub\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--codex-home",
            str(codex_home),
            "--vg-home",
            str(vg_home),
        ],
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
    assert str(vg_home / "scripts" / "codex-hooks" / "vg-user-prompt-submit.py") in commands
    assert str(vg_home / "scripts" / "codex-hooks" / "vg-stop.py") in commands
    assert ".claude/scripts" not in commands

    config = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert "[features]" in config
    assert "codex_hooks = true" in config

    check = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--codex-home",
            str(codex_home),
            "--vg-home",
            str(vg_home),
            "--check",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert check.returncode == 0


def test_codex_hook_lib_resolves_global_vg_home_when_project_pruned(tmp_path, monkeypatch):
    module = _load(HOOK_LIB, "vg_codex_hook_lib_test")
    project = tmp_path / "project"
    vg_home = tmp_path / ".vgflow"
    target = vg_home / "scripts" / "vg-entry-hook.py"
    project.mkdir()
    target.parent.mkdir(parents=True)
    target.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("VG_HOME", str(vg_home))

    found = module.first_existing(project, (".claude/scripts/vg-entry-hook.py", "scripts/vg-entry-hook.py"))
    assert found == target


def test_codex_hooks_merge_replaces_project_local_legacy_hooks(tmp_path):
    module = _load(INSTALLER, "codex_hooks_install_test")
    vg_home = tmp_path / ".vgflow"
    existing = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "^Bash$",
                    "hooks": [
                        {"type": "command", "command": "python3 custom.py"},
                        {
                            "type": "command",
                            "command": "python3 /repo/.claude/scripts/codex-hooks/vg-post-tool-use-bash.py",
                        },
                    ],
                }
            ]
        }
    }

    merged = module.merge_hooks(existing, module.desired_hooks(vg_home))
    commands = [
        hook["command"]
        for group in merged["hooks"]["PostToolUse"]
        for hook in group["hooks"]
    ]
    assert "python3 custom.py" in commands
    assert sum("vg-post-tool-use-bash.py" in command for command in commands) == 1
    assert any(str(vg_home / "scripts" / "codex-hooks") in command for command in commands)
