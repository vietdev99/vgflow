"""Regression — session-start exits 0 even when vg-meta-skill.md missing.

Pre-R5.5: `exit 1` killed the SessionStart hook chain for any user who
did not have VG installed. Post-R5.5: writes a warning to
`.vg/.session-start-warn.log` and exits 0.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from .conftest import HOOK_DIR, REPO_ROOT, run_hook


def test_session_start_exits_zero_when_meta_skill_missing(
    tmp_workspace, monkeypatch
):
    """Point CLAUDE_PLUGIN_ROOT to a dir with no vg-meta-skill.md."""
    fake_root = tmp_workspace / "fake-plugin-root"
    fake_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(fake_root))
    monkeypatch.setenv("CLAUDE_HOOK_EVENT", "startup")

    result = run_hook("session-start", stdin="")

    assert result.returncode == 0, (
        f"session-start should degrade gracefully; "
        f"rc={result.returncode}, stderr={result.stderr!r}"
    )
    assert "ERROR" not in result.stderr, (
        f"stderr leaked ERROR token: {result.stderr!r}"
    )

    warn_log = tmp_workspace / ".vg" / ".session-start-warn.log"
    assert warn_log.exists(), "warning log not written"
    log_content = warn_log.read_text()
    assert "meta-skill missing" in log_content
    assert "test-session" in log_content


def test_session_start_succeeds_when_meta_skill_present(
    tmp_workspace, monkeypatch
):
    """Sanity check — happy path still works."""
    fake_root = tmp_workspace / "fake-plugin-root"
    fake_root.mkdir()
    (fake_root / "vg-meta-skill.md").write_text("# stub meta-skill\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(fake_root))
    monkeypatch.setenv("CLAUDE_HOOK_EVENT", "startup")

    result = run_hook("session-start", stdin="")

    assert result.returncode == 0, (
        f"happy path failed; stderr={result.stderr!r}"
    )
