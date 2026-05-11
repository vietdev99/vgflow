from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vg_uninstall  # type: ignore  # noqa: E402


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "VERSION").exists() and (parent / ".git").exists():
            return parent
    return here.parents[2]


def _write_settings(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(echo:*)"]},
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python "${CLAUDE_PROJECT_DIR}/.claude/scripts/vg-entry-hook.py"',
                                },
                                {"type": "command", "command": "echo user-hook"},
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-run-bash-hook.py" "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-stop.sh"',
                                }
                            ]
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def test_prune_hooks_removes_legacy_and_runner_hooks_preserves_user(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.local.json"
    _write_settings(settings)

    changed = vg_uninstall.prune_hooks_file(settings, apply=True)

    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entries in data["hooks"].values()
        for entry in entries
        for hook in entry.get("hooks", [])
    ]
    assert commands == ["echo user-hook"]
    assert data["permissions"]["allow"] == ["Bash(echo:*)"]


def test_uninstall_dry_run_does_not_remove_files(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "commands" / "vg").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "vg" / "build.md").write_text("x", encoding="utf-8")
    _write_settings(tmp_path / ".claude" / "settings.json")

    rc = vg_uninstall.cmd_run(
        type(
            "Args",
            (),
            {"root": str(tmp_path), "apply": False, "purge_state": False},
        )()
    )

    assert rc == 0
    assert (tmp_path / ".claude" / "commands" / "vg" / "build.md").exists()
    assert "vg-entry-hook.py" in (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")


def test_uninstall_apply_moves_vg_surfaces_to_backup(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "commands" / "vg").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "vg" / "build.md").write_text("x", encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "api-contract").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "api-contract" / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "custom-skill").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "custom-skill" / "SKILL.md").write_text("keep", encoding="utf-8")
    (tmp_path / ".codex" / "skills" / "vg-build").mkdir(parents=True)
    (tmp_path / ".codex" / "skills" / "vg-build" / "SKILL.md").write_text("x", encoding="utf-8")
    _write_settings(tmp_path / ".claude" / "settings.local.json")

    rc = vg_uninstall.cmd_run(
        type(
            "Args",
            (),
            {"root": str(tmp_path), "apply": True, "purge_state": False},
        )()
    )

    assert rc == 0
    assert not (tmp_path / ".claude" / "commands" / "vg").exists()
    assert not (tmp_path / ".claude" / "skills" / "api-contract").exists()
    assert (tmp_path / ".claude" / "skills" / "custom-skill" / "SKILL.md").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".codex" / "skills" / "vg-build").exists()
    backups = list((tmp_path / ".vgflow-uninstall-backup").glob("*"))
    assert backups, "expected backup directory"
    assert list(backups[0].rglob("build.md"))


def test_uninstall_does_not_touch_global_codex_config(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    global_config = home / ".codex" / "config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text("[agents.vgflow-test]\ncommand = \"x\"\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()

    rc = vg_uninstall.cmd_run(
        type(
            "Args",
            (),
            {"root": str(project), "apply": True, "purge_state": False},
        )()
    )

    assert rc == 0
    assert global_config.read_text(encoding="utf-8") == "[agents.vgflow-test]\ncommand = \"x\"\n"


def test_command_and_mirror_exist() -> None:
    root = _find_repo_root()
    assert (root / "commands" / "vg" / "uninstall.md").is_file()
    assert (root / ".claude" / "commands" / "vg" / "uninstall.md").is_file()
    assert (root / "codex-skills" / "vg-uninstall" / "SKILL.md").is_file()
    assert not (root / ".codex" / "skills" / "vg-uninstall" / "SKILL.md").exists()
    assert (root / ".claude" / "scripts" / "vg_uninstall.py").read_bytes() == (
        root / "scripts" / "vg_uninstall.py"
    ).read_bytes()
