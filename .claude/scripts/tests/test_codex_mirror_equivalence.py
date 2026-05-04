"""Codex mirror equivalence smoke tests.

The source repository now owns both the Claude command surface and generated
Codex skill mirror. The verifier must compare workflow bodies after removing
frontmatter/adapter noise and must work in synthetic source-repo layouts.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify-codex-mirror-equivalence.py"
SYNC_CMD = REPO_ROOT / "commands" / "vg" / "sync.md"
SYNC_MIRROR = REPO_ROOT / "codex-skills" / "vg-sync" / "SKILL.md"


def test_verifier_script_exists():
    assert VERIFIER.exists(), f"Verifier missing at {VERIFIER}"
    text = VERIFIER.read_text(encoding="utf-8")
    assert "strip_frontmatter" in text
    assert "strip_mirror_adapter" in text
    assert "</codex_skill_adapter>" in text


def test_verifier_baseline_passes():
    result = subprocess.run(
        [sys.executable, str(VERIFIER)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "Codex mirror drift detected on baseline:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "functionally equivalent" in result.stdout


def test_sync_command_advertises_verify_flag():
    text = SYNC_CMD.read_text(encoding="utf-8")
    assert "--verify" in text
    assert "argument-hint:" in text
    hint_line = next(
        line for line in text.splitlines() if line.startswith("argument-hint:")
    )
    assert "--verify" in hint_line


def test_sync_mirror_advertises_verify_flag():
    text = SYNC_MIRROR.read_text(encoding="utf-8")
    assert "--verify" in text
    assert "verify-codex-mirror-equivalence.py" in text


def test_verifier_drift_detected_on_synthetic_source_repo(tmp_path):
    cmd_dir = tmp_path / "commands" / "vg"
    cmd_dir.mkdir(parents=True)
    skill_dir = tmp_path / "codex-skills" / "vg-fake"
    skill_dir.mkdir(parents=True)

    (cmd_dir / "fake.md").write_text(
        "---\nname: vg:fake\n---\n\n<rules>\nR1. one rule\n</rules>\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\nname: vg-fake\n---\n\n<codex_skill_adapter>\nadapter\n"
        "</codex_skill_adapter>\n\n<rules>\nR1. DRIFTED rule\n</rules>\n",
        encoding="utf-8",
    )

    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    fake_verifier = fake_scripts / "verify-codex-mirror-equivalence.py"
    shutil.copy2(VERIFIER, fake_verifier)

    result = subprocess.run(
        [sys.executable, str(fake_verifier)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1, result.stdout
    assert "vg-fake" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
