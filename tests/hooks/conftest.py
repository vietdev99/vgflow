"""Shared fixtures for VG hook tests.

Each fixture creates an isolated temp dir, sets CLAUDE_HOOK_SESSION_ID,
and resolves absolute paths to the hook scripts under test. Hooks are
invoked via subprocess so we exercise the real shebang and trap
behavior.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DIR = REPO_ROOT / "scripts" / "hooks"


HOOK_SCRIPTS = {
    "bash": HOOK_DIR / "vg-pre-tool-use-bash.sh",
    "write": HOOK_DIR / "vg-pre-tool-use-write.sh",
    "agent": HOOK_DIR / "vg-pre-tool-use-agent.sh",
    "post-todowrite": HOOK_DIR / "vg-post-tool-use-todowrite.sh",
    "stop": HOOK_DIR / "vg-stop.sh",
    "user-prompt-submit": HOOK_DIR / "vg-user-prompt-submit.sh",
    "session-start": HOOK_DIR / "vg-session-start.sh",
}


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Empty workspace with no .vg/ directory. Caller cd's into it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_HOOK_SESSION_ID", "test-session")
    return tmp_path


@pytest.fixture
def vg_active_run(tmp_workspace):
    """Workspace WITH an active VG run state file."""
    run_dir = tmp_workspace / ".vg" / "active-runs"
    run_dir.mkdir(parents=True)
    (run_dir / "test-session.json").write_text(
        '{"run_id": "run-test-001", "command": "vg:test", "phase": "P1"}'
    )
    return tmp_workspace


def run_hook(name: str, stdin: str = "", env_extra: dict | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke a hook script via bash subprocess.

    Returns CompletedProcess with returncode, stdout, stderr captured.
    Does NOT raise on non-zero exit (callers assert).
    """
    script = HOOK_SCRIPTS[name]
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=10,
    )
