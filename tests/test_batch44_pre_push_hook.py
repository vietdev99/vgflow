"""tests/test_batch44_pre_push_hook.py — Batch 44.

Pre-push hook prevents codex mirror drift hotfixes (v4.33.0/v4.34.0
incident pattern).
"""
from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "git-hooks" / "pre-push"
INSTALLER = REPO / "scripts" / "git-hooks" / "install.sh"


def test_pre_push_hook_exists():
    assert HOOK.is_file()
    body = HOOK.read_text(encoding="utf-8")
    assert "verify-codex-mirror-equivalence.py" in body, (
        "Batch 44: pre-push hook must invoke codex mirror validator"
    )
    assert "refs/tags/v" in body, "must detect tag pushes"


def test_pre_push_hook_allows_bypass():
    body = HOOK.read_text(encoding="utf-8")
    assert "VG_SKIP_CODEX_GUARD" in body, "must support emergency bypass env"


def test_pre_push_skips_branch_only_push():
    """If no tag ref in stdin, hook must exit 0."""
    body = HOOK.read_text(encoding="utf-8")
    assert "tag_push=0" in body and "exit 0" in body, (
        "must skip when no tag in push refs"
    )


def test_installer_exists():
    assert INSTALLER.is_file()
    body = INSTALLER.read_text(encoding="utf-8")
    assert "pre-push" in body and "chmod +x" in body
    assert ".git/hooks" in body


def test_installer_runs_idempotently(tmp_path):
    """install.sh works on synthetic repo."""
    # Create fake git repo
    fake_repo = tmp_path / "fake-repo"
    fake_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fake_repo, check=True)
    # Copy hooks dir
    hooks_src = fake_repo / "scripts" / "git-hooks"
    hooks_src.mkdir(parents=True)
    (hooks_src / "pre-push").write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    (hooks_src / "install.sh").write_text(INSTALLER.read_text(encoding="utf-8"), encoding="utf-8")
    # Run installer twice — second run must succeed without error
    for _ in range(2):
        r = subprocess.run(
            ["bash", str(hooks_src / "install.sh")],
            cwd=fake_repo, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"installer failed: {r.stderr}"
    # Verify hook installed
    installed = fake_repo / ".git" / "hooks" / "pre-push"
    assert installed.is_file()
    assert "verify-codex-mirror-equivalence.py" in installed.read_text(encoding="utf-8")
