"""
harness-v2.7-fixup-N10 — codex mirror equivalence smoke test.

Audit finding (crossai-build-audit/sonnet.out, N10):
  Codex mirror files (.codex/skills/vg-<name>/SKILL.md) prepend an adapter
  block but otherwise track .claude/commands/vg/<name>.md. The regular
  sync.sh --check line-level diff reports thousands of differing lines
  because of the ~80-line offset. Real functional drift is invisible.

Fix: verify-codex-mirror-equivalence.py hashes post-adapter mirror content
against post-frontmatter source content. /vg:sync --verify wires it in.

This test pins:
  1. The verifier script exists and is executable.
  2. Running it with the current repo state exits 0 (baseline must be clean
     — fail-loud on accidental mirror divergence).
  3. The argument-hint of /vg:sync exposes --verify (so users discover it).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPO_ROOT / ".claude" / "scripts" / "verify-codex-mirror-equivalence.py"
SYNC_CMD = REPO_ROOT / ".claude" / "commands" / "vg" / "sync.md"
SYNC_MIRROR = REPO_ROOT / ".codex" / "skills" / "vg-sync" / "SKILL.md"


def test_verifier_script_exists():
    assert VERIFIER.exists(), f"Verifier missing at {VERIFIER}"
    text = VERIFIER.read_text(encoding="utf-8")
    assert "strip_source_frontmatter" in text
    assert "strip_mirror_adapter" in text
    assert "</codex_skill_adapter>" in text


def test_verifier_baseline_passes():
    """Current repo state must have zero mirror drift. If this fails, run
    /vg:sync to regenerate mirrors then commit them.
    """
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
    assert "All mirrors functionally equivalent" in result.stdout


def test_sync_command_advertises_verify_flag():
    text = SYNC_CMD.read_text(encoding="utf-8")
    assert "--verify" in text, "/vg:sync source command must list --verify"
    assert "argument-hint:" in text
    # The flag must appear in the documented argument-hint, not just prose.
    hint_line = next(
        line for line in text.splitlines() if line.startswith("argument-hint:")
    )
    assert "--verify" in hint_line, (
        f"--verify missing from argument-hint: {hint_line}"
    )


def test_sync_mirror_advertises_verify_flag():
    text = SYNC_MIRROR.read_text(encoding="utf-8")
    assert "--verify" in text, (
        ".codex/skills/vg-sync/SKILL.md mirror must mention --verify"
    )
    assert "verify-codex-mirror-equivalence.py" in text, (
        "Mirror should reference the verifier script path so Codex agents "
        "execute the same gate as Claude Code"
    )


def test_verifier_drift_detected_on_synthetic_change(tmp_path):
    """Sanity: if a mirror's post-adapter content diverges, verifier exits 1.

    Builds a tiny synthetic source/mirror pair under tmp_path that mimics the
    real repo layout, points the script at it via env override, and confirms
    the drift is surfaced.
    """
    cmd_dir = tmp_path / ".claude" / "commands" / "vg"
    cmd_dir.mkdir(parents=True)
    skill_dir = tmp_path / ".codex" / "skills" / "vg-fake"
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

    # Run a copy of the verifier rooted at tmp_path so its
    # parents[2] resolution lands on our synthetic repo.
    fake_root = tmp_path
    fake_scripts = fake_root / ".claude" / "scripts"
    fake_scripts.mkdir(parents=True, exist_ok=True)
    fake_verifier = fake_scripts / "verify-codex-mirror-equivalence.py"
    fake_verifier.write_text(
        VERIFIER.read_text(encoding="utf-8"), encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, str(fake_verifier)],
        capture_output=True,
        text=True,
        cwd=fake_root,
    )
    assert result.returncode == 1, (
        f"Expected drift exit 1, got {result.returncode}\n{result.stdout}"
    )
    assert "vg-fake" in result.stdout, "Drift skill name should appear"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
