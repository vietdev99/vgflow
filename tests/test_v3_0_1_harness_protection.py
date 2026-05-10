"""v3.0.1 — VGFlow harness file protection.

Two layers:
1. PreToolUse-Write hook (Claude side): blocks Write/Edit on harness paths
   in dependent projects. Allows in vgflow source repo (package.json
   name=vgflow) or VG_HARNESS_DEV=1 override.
2. install-pre-commit-harness-guard.sh: per-project git pre-commit hook
   that catches Codex (no PreToolUse hooks) + any AI bypassing Claude
   PreToolUse. Same allow logic.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-write.sh"
INSTALLER = REPO_ROOT / "scripts" / "hooks" / "install-pre-commit-harness-guard.sh"


_BASH_SKIP = [
    pytest.mark.skipif(not shutil.which("bash"), reason="bash missing"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="WSL path mapping fragile on Windows; CI Linux validates",
    ),
]


# ── content checks (run on all platforms — file-content scans only) ──


def test_hook_has_evidence_pattern_array():
    body = HOOK.read_text(encoding="utf-8")
    assert "evidence_patterns=(" in body
    assert ".vg/runs/" in body
    assert ".vg/events.db" in body or "events\\.db" in body


def test_hook_has_harness_pattern_array():
    body = HOOK.read_text(encoding="utf-8")
    assert "harness_patterns=(" in body
    for pat in (".claude/commands/vg/", ".claude/skills/vg-", ".claude/scripts/", ".codex/skills/"):
        assert pat in body, f"hook must include harness pattern: {pat}"


def test_hook_detects_vgflow_source_repo():
    body = HOOK.read_text(encoding="utf-8")
    assert "is_vgflow_source_repo" in body
    assert '"name"' in body and '"vgflow"' in body, (
        "hook must probe package.json for name=vgflow"
    )


def test_hook_supports_vg_harness_dev_override():
    body = HOOK.read_text(encoding="utf-8")
    assert "VG_HARNESS_DEV" in body


def test_hook_blocks_global_vgflow_paths():
    body = HOOK.read_text(encoding="utf-8")
    assert "home_vgflow_pattern" in body
    assert ".vgflow/(commands" in body or ".vgflow/" in body


def test_hook_mirror_byte_identity():
    canonical = HOOK.read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-write.sh").read_bytes()
    assert canonical == mirror


def test_installer_exists_and_executable():
    assert INSTALLER.exists()
    body = INSTALLER.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "VG_HARNESS_DEV" in body
    assert "harness-guard" in body


def test_installer_refuses_in_vgflow_source_repo():
    body = INSTALLER.read_text(encoding="utf-8")
    assert "skipping install" in body
    assert '"name"' in body and '"vgflow"' in body


def test_installer_mirror_byte_identity():
    canonical = INSTALLER.read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "hooks" / "install-pre-commit-harness-guard.sh").read_bytes()
    assert canonical == mirror


# ── functional tests (Linux-only — bash invocation needs WSL/Linux) ──
# Per-test decorator instead of pytestmark (which is module-level).
_skipif_no_bash = pytest.mark.skipif(
    not shutil.which("bash") or sys.platform == "win32",
    reason="bash missing or WSL path mapping fragile; CI Linux validates",
)


def _run_hook(file_path: str, cwd: Path, env_extra: dict | None = None) -> int:
    payload = f'{{"tool_input":{{"file_path":{file_path!r}}}}}'
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    return r.returncode


@_skipif_no_bash
def test_hook_blocks_harness_write_in_foreign_project(tmp_path):
    rc = _run_hook(".claude/commands/vg/build.md", tmp_path)
    assert rc == 2, "harness write must block (rc=2) in foreign project"


@_skipif_no_bash
def test_hook_allows_regular_file_write(tmp_path):
    rc = _run_hook("src/index.ts", tmp_path)
    assert rc == 0, "regular file must pass (rc=0)"


@_skipif_no_bash
def test_hook_allows_harness_write_in_vgflow_source_repo(tmp_path):
    """Cwd has package.json with name=vgflow → harness edits allowed."""
    (tmp_path / "package.json").write_text(
        '{"name": "vgflow", "version": "3.0.1"}', encoding="utf-8"
    )
    rc = _run_hook(".claude/commands/vg/build.md", tmp_path)
    assert rc == 0, "vgflow source repo must allow harness edits"


@_skipif_no_bash
def test_hook_allows_harness_write_with_vg_harness_dev_override(tmp_path):
    rc = _run_hook(
        ".claude/commands/vg/build.md",
        tmp_path,
        env_extra={"VG_HARNESS_DEV": "1"},
    )
    assert rc == 0


@_skipif_no_bash
def test_hook_blocks_global_vgflow_path(tmp_path):
    rc = _run_hook("/home/user/.vgflow/scripts/x.py", tmp_path)
    assert rc == 2


@_skipif_no_bash
def test_hook_blocks_codex_skills_path(tmp_path):
    rc = _run_hook(".codex/skills/vg-build/SKILL.md", tmp_path)
    assert rc == 2


@_skipif_no_bash
def test_hook_evidence_protection_still_works(tmp_path):
    """Evidence pattern protection from v2.x must remain intact."""
    rc = _run_hook(".vg/events.db", tmp_path)
    assert rc == 2


@_skipif_no_bash
def test_pre_commit_installer_blocks_in_dependent_project(tmp_path):
    """Smoke: install hook in fresh git repo, attempt to commit harness file."""
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@x.dev"], cwd=str(proj), check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=str(proj), check=True
    )
    subprocess.run(
        ["bash", str(INSTALLER), str(proj)],
        check=True,
        capture_output=True,
    )
    (proj / ".claude" / "commands" / "vg").mkdir(parents=True)
    (proj / ".claude" / "commands" / "vg" / "foo.md").write_text(
        "harness edit", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=str(proj), check=True)
    r = subprocess.run(
        ["git", "commit", "-m", "edit harness"],
        cwd=str(proj),
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0, "commit should be rejected"
    assert "harness-guard" in (r.stdout + r.stderr).lower()


@_skipif_no_bash
def test_pre_commit_installer_skips_vgflow_source_repo(tmp_path):
    proj = tmp_path / "vgflow-src"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(proj), check=True)
    (proj / "package.json").write_text(
        '{"name": "vgflow", "version": "3.0.1"}', encoding="utf-8"
    )
    r = subprocess.run(
        ["bash", str(INSTALLER), str(proj)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "skipping" in r.stdout.lower()
    # And no pre-commit hook installed
    assert not (proj / ".git" / "hooks" / "pre-commit").exists()
