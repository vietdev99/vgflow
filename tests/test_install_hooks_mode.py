"""v2.78.0 Stage 3.1 — install-hooks.sh --mode global|project flag.

For v3.0.0 global install: hooks point at ~/.vgflow/scripts/hooks/<name>
instead of ${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/<name>.

Default mode = project (backwards compatible).

Source plan: docs/plans/2026-05-09-vg-global-install-implementation.md Stage 3.1
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
INSTALL_SH = REPO_ROOT / "scripts" / "hooks" / "install-hooks.sh"


pytestmark = [
    pytest.mark.skipif(not shutil.which("bash"), reason="bash not available"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="WSL path mapping fragile on Windows; CI Linux validates",
    ),
]


def _run_install(target: Path, mode: str | None = None) -> tuple[int, str, str]:
    cmd = ["bash", str(INSTALL_SH), "--target", str(target)]
    if mode is not None:
        cmd += ["--mode", mode]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _hook_cmd(target: Path, event: str, idx: int = 0) -> str:
    settings = json.loads(target.read_text(encoding="utf-8"))
    entry = settings["hooks"][event][idx]
    return entry["hooks"][0]["command"]


def test_default_mode_emits_claude_project_dir(tmp_path):
    target = tmp_path / "settings.json"
    rc, out, err = _run_install(target)
    assert rc == 0, f"err={err}"
    cmd = _hook_cmd(target, "UserPromptSubmit")
    assert "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/" in cmd
    assert "$HOME/.vgflow" not in cmd


def test_project_mode_explicit_matches_default(tmp_path):
    target = tmp_path / "settings.json"
    rc, out, err = _run_install(target, mode="project")
    assert rc == 0, f"err={err}"
    cmd = _hook_cmd(target, "UserPromptSubmit")
    assert "${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/" in cmd


def test_global_mode_emits_home_vgflow(tmp_path):
    target = tmp_path / "settings.json"
    rc, out, err = _run_install(target, mode="global")
    assert rc == 0, f"err={err}"
    cmd = _hook_cmd(target, "UserPromptSubmit")
    assert "$HOME/.vgflow/scripts/hooks/" in cmd
    assert "${CLAUDE_PROJECT_DIR}" not in cmd


def test_invalid_mode_errors(tmp_path):
    target = tmp_path / "settings.json"
    rc, out, err = _run_install(target, mode="bogus")
    assert rc != 0
    assert "mode" in (out + err).lower()


def test_global_mode_all_events_use_home_path(tmp_path):
    """All hook events emit $HOME/.vgflow path under global mode."""
    target = tmp_path / "settings.json"
    rc, _, _ = _run_install(target, mode="global")
    assert rc == 0
    for event in ("UserPromptSubmit", "SessionStart", "Stop"):
        cmd = _hook_cmd(target, event)
        assert "$HOME/.vgflow/scripts/hooks/" in cmd, (
            f"event {event} should use $HOME/.vgflow path: {cmd}"
        )


def test_idempotent_re_install(tmp_path):
    """Running twice produces same JSON (no duplicate hook entries)."""
    target = tmp_path / "settings.json"
    rc1, _, _ = _run_install(target, mode="global")
    text1 = target.read_text(encoding="utf-8")
    rc2, _, _ = _run_install(target, mode="global")
    text2 = target.read_text(encoding="utf-8")
    assert rc1 == 0 and rc2 == 0
    assert text1 == text2
