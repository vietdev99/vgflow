import os
import re
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def test_install_refreshes_global_claude_commands(tmp_path):
    home = tmp_path / "home"
    vg_home = tmp_path / "vgflow"
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()

    _copy(REPO / "bin" / "vg-cli-dispatcher.sh", vg_home / "bin" / "vg-cli-dispatcher.sh")
    _copy(REPO / "bin" / "vg.js", vg_home / "bin" / "vg.js")
    _copy(REPO / "scripts" / "hooks" / "install-hooks.sh", vg_home / "scripts" / "hooks" / "install-hooks.sh")
    _copy(REPO / "commands" / "vg" / "review.md", vg_home / "commands" / "vg" / "review.md")
    _copy(REPO / "commands" / "vg" / "test-spec.md", vg_home / "commands" / "vg" / "test-spec.md")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["VG_HOME"] = str(vg_home)
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
    subprocess.run(
        ["bash", str(vg_home / "bin" / "vg-cli-dispatcher.sh"), "install", "--global"],
        cwd=project,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    claude_vg = home / ".claude" / "commands" / "vg"
    assert (claude_vg / "review.md").is_file()
    assert (claude_vg / "test-spec.md").is_file()
    assert (home / ".vgflow" / "commands" / "vg" / "review.md").is_file()
    assert os.access(home / ".local" / "bin" / "vg", os.X_OK)
    assert (project / ".vg" / ".install-target").read_text().strip() == "global"

    doctor = subprocess.run(
        ["bash", str(vg_home / "bin" / "vg-cli-dispatcher.sh"), "doctor"],
        cwd=project,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert "Claude commands: 2 file(s) in ~/.claude/commands/vg" in doctor.stdout


def test_install_and_update_call_claude_command_refresh():
    body = (REPO / "bin" / "vg-cli-dispatcher.sh").read_text(encoding="utf-8")
    install_block = re.search(r"  install\)(.*?)\n  sync\|update\)", body, re.S).group(1)
    update_block = re.search(r"  sync\|update\)(.*?)\n  doctor\)", body, re.S).group(1)

    assert "refresh_global_cli_link" in install_block
    assert "refresh_global_claude_commands" in install_block
    assert "refresh_global_cli_link" in update_block
    assert "refresh_global_claude_commands" in update_block
