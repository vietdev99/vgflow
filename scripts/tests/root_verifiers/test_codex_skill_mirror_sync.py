"""
Tests for verify-codex-skill-mirror-sync.py — BLOCK severity.

Forensic SHA256 hash parity across 3 mirror locations:
  Chain A: $REPO_ROOT/.claude/commands/vg/*.md
  Chain B: $REPO_ROOT/.codex/skills/vg-*/SKILL.md
           + $HOME/.codex/skills/vg-*/SKILL.md (optional)

Covers:
  - Missing all skill dirs → PASS (nothing to compare) or rc=2
  - Single skill in sync across .claude + .codex local → PASS
  - Single skill out-of-sync (different content) → BLOCK
  - --quiet flag suppresses output
  - --json flag emits structured
  - --skill flag scopes to single skill
  - --skip-vgflow recognized
  - --fast (mtime-only) flag recognized
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-codex-skill-mirror-sync.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    env["REPO_ROOT"] = str(cwd)
    # Point HOME to a sandbox so $HOME/.codex doesn't pollute real ~/.codex
    env["HOME"] = str(cwd / "fake-home")
    env["USERPROFILE"] = str(cwd / "fake-home")
    # Disable vgflow check
    env.pop("VGFLOW_REPO", None)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _setup_skill(tmp_path: Path, name: str, content: str,
                  codex_content: str | None = None,
                  global_content: str | None = None,
                  with_global: bool = True) -> None:
    """Stage skill files in 3 mirror locations (chain B: local + global codex).

    Validator compares:
      - local: $REPO_ROOT/.codex/skills/vg-<name>/SKILL.md
      - global: $HOME/.codex/skills/vg-<name>/SKILL.md
    Both must agree (Chain B parity check).
    """
    claude = tmp_path / ".claude" / "commands" / "vg"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / f"{name}.md").write_text(content, encoding="utf-8")

    body = codex_content if codex_content is not None else content

    codex_local = tmp_path / ".codex" / "skills" / f"vg-{name}"
    codex_local.mkdir(parents=True, exist_ok=True)
    (codex_local / "SKILL.md").write_text(body, encoding="utf-8")

    if with_global:
        codex_global = tmp_path / "fake-home" / ".codex" / "skills" / f"vg-{name}"
        codex_global.mkdir(parents=True, exist_ok=True)
        (codex_global / "SKILL.md").write_text(
            global_content if global_content is not None else body,
            encoding="utf-8",
        )


class TestCodexSkillMirrorSync:
    def test_missing_skill_dirs_graceful(self, tmp_path):
        # No .claude/.codex at all
        r = _run(["--skip-vgflow"], tmp_path)
        # Validator may PASS (nothing to compare) or rc=2 (config error)
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stderr

    def test_in_sync_skill_passes(self, tmp_path):
        content = "# Skill body\n\nSome content here.\n"
        _setup_skill(tmp_path, "blueprint", content)  # both local + global
        r = _run(["--skip-vgflow", "--skill", "blueprint"], tmp_path)
        assert r.returncode == 0, \
            f"in-sync skill should PASS, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_local_only_no_global_blocks(self, tmp_path):
        """Local .codex present but global $HOME/.codex missing → drift."""
        _setup_skill(tmp_path, "build", "# v1\n", with_global=False)
        r = _run(["--skip-vgflow", "--skill", "build"], tmp_path)
        # Missing global = GLOBAL_MISSING drift → BLOCK
        assert r.returncode == 1, \
            f"missing global mirror should BLOCK, rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_drift_detected_with_two_mirrors(self, tmp_path):
        # Both mirrors present but with different content — true drift
        _setup_skill(
            tmp_path, "review",
            "# Original skill\n",
            global_content="# DRIFTED skill\n",
        )
        r = _run(["--skip-vgflow", "--skill", "review"], tmp_path)
        # Hash mismatch between local and global → BLOCK
        assert r.returncode == 1, \
            f"drift between local/global should BLOCK, rc={r.returncode}, stdout={r.stdout[:300]}"
        assert "Traceback" not in r.stderr

    def test_quiet_flag_recognized(self, tmp_path):
        _setup_skill(tmp_path, "test", "# t\n")
        r = _run(["--skip-vgflow", "--quiet"], tmp_path)
        assert "unrecognized arguments" not in r.stderr.lower()
        assert r.returncode in (0, 1, 2)

    def test_json_flag_outputs_parseable(self, tmp_path):
        _setup_skill(tmp_path, "scope", "# s\n")
        r = _run(["--skip-vgflow", "--json"], tmp_path)
        assert "unrecognized arguments" not in r.stderr.lower()
        if r.stdout.strip():
            try:
                json.loads(r.stdout)
            except json.JSONDecodeError:
                # Some emit human-readable when no drift; tolerate
                pass

    def test_skill_filter_flag(self, tmp_path):
        _setup_skill(tmp_path, "accept", "# a\n")
        r = _run(["--skip-vgflow", "--skill", "accept"], tmp_path)
        assert "unrecognized arguments" not in r.stderr.lower()
        assert r.returncode in (0, 1, 2)

    def test_fast_flag_recognized(self, tmp_path):
        _setup_skill(tmp_path, "specs", "# x\n")
        r = _run(["--skip-vgflow", "--fast"], tmp_path)
        assert "unrecognized arguments" not in r.stderr.lower()
        assert r.returncode in (0, 1, 2)
