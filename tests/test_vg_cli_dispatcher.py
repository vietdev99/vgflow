"""v2.80.0 Stage 4 — vg CLI dispatcher install/uninstall/sync wire-up.

Smoke tests for `bin/vg-cli-dispatcher.sh` install/uninstall:
- install --global: --mode global hook paths + .vg/.install-target=global
- install --project: --mode project hook paths + .vg/.install-target=project
- uninstall: removes VG hook entries, backs up settings.json, removes marker

Source plan: docs/plans/2026-05-09-vg-global-install-implementation.md Stage 4
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = REPO_ROOT / "bin" / "vg-cli-dispatcher.sh"


pytestmark = [
    pytest.mark.skipif(not shutil.which("bash"), reason="bash not available"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="WSL path mapping fragile on Windows; CI Linux validates",
    ),
]


def _run_dispatcher(args: list[str], cwd: Path, fake_home: Path) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["VG_HOME"] = str(REPO_ROOT)
    r = subprocess.run(
        ["bash", str(DISPATCHER), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    return proj, fake_home


def test_install_global_writes_marker_and_global_paths(tmp_path):
    proj, fake_home = _make_project(tmp_path)
    (proj / ".claude" / "commands" / "vg").mkdir(parents=True)
    (proj / ".claude" / "commands" / "vg" / "build.md").write_text("stale", encoding="utf-8")
    (proj / ".claude" / "skills" / "api-contract").mkdir(parents=True)
    (proj / ".claude" / "skills" / "api-contract" / "SKILL.md").write_text("stale", encoding="utf-8")
    (proj / ".claude" / "skills" / "custom-skill").mkdir(parents=True)
    (proj / ".claude" / "skills" / "custom-skill" / "SKILL.md").write_text("keep", encoding="utf-8")
    (proj / ".codex" / "skills" / "vg-update").mkdir(parents=True)
    (proj / ".codex" / "skills" / "vg-update" / "SKILL.md").write_text("stale", encoding="utf-8")

    rc, out, err = _run_dispatcher(["install", "--global"], proj, fake_home)
    assert rc == 0, f"err={err}"
    settings = fake_home / ".claude" / "settings.json"
    assert settings.exists()
    cmd = json.loads(settings.read_text(encoding="utf-8"))["hooks"][
        "UserPromptSubmit"
    ][0]["hooks"][0]["command"]
    assert "$HOME/.vgflow/scripts/hooks/" in cmd
    marker = proj / ".vg" / ".install-target"
    assert marker.exists() and marker.read_text(encoding="utf-8").strip() == "global"
    assert (fake_home / ".vgflow").is_symlink()
    assert (fake_home / ".codex" / "skills" / "vg-update" / "SKILL.md").exists()
    assert not (proj / ".claude" / "commands" / "vg").exists()
    assert not (proj / ".claude" / "skills" / "api-contract").exists()
    assert not (proj / ".codex" / "skills" / "vg-update").exists()
    assert (proj / ".claude" / "skills" / "custom-skill" / "SKILL.md").read_text(encoding="utf-8") == "keep"


def test_install_project_writes_marker_and_project_paths(tmp_path):
    proj, fake_home = _make_project(tmp_path)
    rc, out, err = _run_dispatcher(["install", "--project"], proj, fake_home)
    assert rc == 0, f"err={err}"
    settings = proj / ".claude" / "settings.json"
    assert settings.exists()
    cmd = json.loads(settings.read_text(encoding="utf-8"))["hooks"][
        "UserPromptSubmit"
    ][0]["hooks"][0]["command"]
    assert "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/" in cmd
    marker = proj / ".vg" / ".install-target"
    assert marker.exists() and marker.read_text(encoding="utf-8").strip() == "project"


def test_uninstall_project_removes_hooks_and_marker(tmp_path):
    proj, fake_home = _make_project(tmp_path)
    # Install first
    _run_dispatcher(["install", "--project"], proj, fake_home)
    (proj / ".claude" / "commands" / "vg").mkdir(parents=True)
    (proj / ".claude" / "commands" / "vg" / "build.md").write_text("stale", encoding="utf-8")
    (proj / ".codex" / "skills" / "vg-build").mkdir(parents=True)
    (proj / ".codex" / "skills" / "vg-build" / "SKILL.md").write_text("stale", encoding="utf-8")
    settings = proj / ".claude" / "settings.json"
    before = json.loads(settings.read_text(encoding="utf-8"))
    assert any(
        "vg-" in (h.get("command") or "")
        for entries in before["hooks"].values()
        for entry in entries
        for h in (entry.get("hooks") or [])
    ), "VG hooks should exist after install"
    # Uninstall
    rc, out, err = _run_dispatcher(["uninstall", "--project"], proj, fake_home)
    assert rc == 0, f"err={err}"
    after = json.loads(settings.read_text(encoding="utf-8"))
    assert not any(
        "vg-" in (h.get("command") or "")
        for entries in (after.get("hooks") or {}).values()
        for entry in entries
        for h in (entry.get("hooks") or [])
    ), "all VG hooks should be removed"
    assert not (proj / ".vg" / ".install-target").exists(), (
        "project marker should be removed"
    )
    assert not (proj / ".claude" / "commands" / "vg").exists()
    assert not (proj / ".codex" / "skills" / "vg-build").exists()
    # Backup file must exist
    backups = list((proj / ".claude").glob("settings.json.bak.*"))
    assert len(backups) == 1, f"expected 1 backup; got {backups}"


def test_uninstall_no_settings_is_noop(tmp_path):
    proj, fake_home = _make_project(tmp_path)
    rc, out, err = _run_dispatcher(["uninstall", "--global"], proj, fake_home)
    assert rc == 0
    assert "nothing to uninstall" in out


def test_install_marker_skipped_when_not_in_git_repo(tmp_path):
    """If cwd has no .git AND no pre-existing marker, marker is NOT written
    (avoids littering random dirs with stray .vg/ folders)."""
    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    plain = tmp_path / "noplace"
    plain.mkdir()
    rc, out, err = _run_dispatcher(["install", "--global"], plain, fake_home)
    assert rc == 0, f"err={err}"
    assert not (plain / ".vg" / ".install-target").exists(), (
        "marker should NOT be written outside a git repo"
    )


def test_version_command(tmp_path):
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    rc, out, err = _run_dispatcher(["version"], tmp_path, fake_home)
    assert rc == 0
    # Version should be the 2.x.x string from VERSION file
    assert out.strip().startswith("2.") or out.strip().startswith("3.")


def test_help_command(tmp_path):
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    rc, out, err = _run_dispatcher(["help"], tmp_path, fake_home)
    assert rc == 0
    assert "vgflow" in out.lower() and "install" in out.lower()
