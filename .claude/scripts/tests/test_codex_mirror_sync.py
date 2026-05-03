"""
Tests for verify-codex-skill-mirror-sync.py — Phase 0 of v2.5.2.

Covers:
  - Hash parity across 3 locations (RTB source, .codex local, ~/.codex global)
  - Line-ending normalization (CRLF/LF equivalence on Windows)
  - Missing file detection per location
  - vgflow-repo upstream inclusion (optional)
  - Skill discovery from .claude/commands/vg/ glob
  - --skill arg filters to single skill
  - --json output parseable
  - --quiet suppresses clean output
  - Chain A vs Chain B separation (Claude path vs Codex path)
  - Exit code 1 on drift, 0 on sync

The validator is CRITICAL trust-parity infrastructure — stale Codex mirrors
let Codex agents forge evidence against old contract. These tests ensure
the validator catches all classes of drift.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / \
    "verify-codex-skill-mirror-sync.py"


def _run(args: list[str], env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke validator as subprocess with UTF-8 + optional env overrides."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
    )


def _setup_fake_tree(tmp_path: Path, contents: dict[str, str | bytes]) -> Path:
    """Create fake repo layout under tmp_path matching expected VG structure.

    contents = {
        ".claude/commands/vg/blueprint.md": "content...",
        ".codex/skills/vg-blueprint/SKILL.md": "content...",
        ...
    }

    Also creates a git repo (so validator's `git rev-parse --show-toplevel`
    works when REPO_ROOT env not set).
    """
    for rel, body in contents.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")

    # Minimal git init so `git rev-parse --show-toplevel` returns tmp_path
    # (validator falls back to cwd otherwise, but git gives stable root)
    subprocess.run(
        ["git", "init", "-q"], cwd=str(tmp_path), check=False,
    )
    return tmp_path


# ─── Hash parity tests ─────────────────────────────────────────────────

class TestHashParity:
    def test_identical_content_passes(self, tmp_path):
        """All 3 locations same content → PASS, exit 0."""
        content = "# /vg:blueprint\n\nExample skill body.\n"
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": content,
            ".codex/skills/vg-blueprint/SKILL.md": content,
        })
        # Global location under fake HOME
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text(content, encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--quiet",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            # Windows uses USERPROFILE for Path.home()
            "USERPROFILE": str(home),
        })
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    def test_drift_between_local_and_global(self, tmp_path):
        """Local .codex differs from global → exit 1."""
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "source content",
            ".codex/skills/vg-blueprint/SKILL.md": "version-A",
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("version-B-DIFFERENT", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 1
        assert "drift" in r.stdout.lower() or "CODEX_MIRROR_DRIFT" in r.stdout

    def test_crlf_vs_lf_not_flagged_as_drift(self, tmp_path):
        """Same content with CRLF vs LF endings → normalized, PASS."""
        home = tmp_path / "home"
        home.mkdir()
        lf_content = "# heading\nline 1\nline 2\n"
        crlf_content = "# heading\r\nline 1\r\nline 2\r\n"
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": lf_content,
            ".codex/skills/vg-blueprint/SKILL.md": crlf_content.encode("utf-8"),
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_bytes(lf_content.encode("utf-8"))

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--quiet",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 0, (
            f"CRLF/LF should normalize to same hash.\n"
            f"stdout={r.stdout}\nstderr={r.stderr}"
        )


# ─── Missing file detection ────────────────────────────────────────────

class TestMissingFiles:
    def test_local_codex_missing_detected(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "source",
            # NO .codex/skills/vg-blueprint/SKILL.md
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("source", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        # Chain B fails (local missing, global exists but sole one available)
        # With only 1 location, in_sync is False per len(hashes) >= 2 guard
        assert r.returncode == 1
        assert "LOCAL_MISSING" in r.stdout

    def test_rtb_source_missing_detected(self, tmp_path):
        """RTB source missing but mirror present → drift."""
        home = tmp_path / "home"
        home.mkdir()
        vgflow = tmp_path / "vgflow-repo"
        (vgflow / "commands" / "vg").mkdir(parents=True)
        (vgflow / "commands" / "vg" / "blueprint.md").write_text(
            "mirror content", encoding="utf-8")
        # Make sync.sh exist so vgflow discovery works
        (vgflow / "sync.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        _setup_fake_tree(tmp_path, {
            ".codex/skills/vg-blueprint/SKILL.md": "codex",
        })
        # RTB source NOT created
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("codex", encoding="utf-8")

        r = _run([
            "--skill", "blueprint",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "VGFLOW_REPO": str(vgflow),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 1
        assert "RTB_MISSING" in r.stdout


# ─── Vgflow-repo integration ───────────────────────────────────────────

class TestVgflowIntegration:
    def test_skip_vgflow_flag_honored(self, tmp_path):
        """--skip-vgflow: don't attempt vgflow-repo lookup."""
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "same",
            ".codex/skills/vg-blueprint/SKILL.md": "same",
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("same", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--json",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["vgflow_repo"] is None

    def test_vgflow_upstream_drift_detected(self, tmp_path):
        """RTB source differs from vgflow-repo mirror → Chain A drift."""
        home = tmp_path / "home"
        home.mkdir()
        vgflow = tmp_path / "vgflow-repo"
        (vgflow / "commands" / "vg").mkdir(parents=True)
        (vgflow / "commands" / "vg" / "blueprint.md").write_text(
            "OLD v2.4 content", encoding="utf-8")
        (vgflow / "sync.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        # Make codex-skills chain B OK to isolate drift to chain A
        (vgflow / "codex-skills" / "vg-blueprint").mkdir(parents=True)
        (vgflow / "codex-skills" / "vg-blueprint" / "SKILL.md").write_text(
            "codex", encoding="utf-8")

        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "NEW v2.5.2 content",
            ".codex/skills/vg-blueprint/SKILL.md": "codex",
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("codex", encoding="utf-8")

        r = _run([
            "--skill", "blueprint",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "VGFLOW_REPO": str(vgflow),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 1
        assert "RTB_vs_VGFLOW_DRIFT" in r.stdout


# ─── CLI contract ─────────────────────────────────────────────────────

class TestCLIContract:
    def test_json_output_parseable(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "same",
            ".codex/skills/vg-blueprint/SKILL.md": "same",
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("same", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--json",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        data = json.loads(r.stdout)
        assert data["skills_checked"] == 1
        assert data["drift_count"] == 0
        assert len(data["results"]) == 2  # chain A + chain B

    def test_quiet_suppresses_clean_output(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "same",
            ".codex/skills/vg-blueprint/SKILL.md": "same",
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("same", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--quiet",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        assert r.returncode == 0
        assert r.stdout.strip() == ""

    def test_skill_filter_limits_scope(self, tmp_path):
        """--skill X: only check that skill, don't discover others."""
        home = tmp_path / "home"
        home.mkdir()
        _setup_fake_tree(tmp_path, {
            ".claude/commands/vg/blueprint.md": "same",
            ".claude/commands/vg/build.md": "WRONG",  # deliberately broken
            ".codex/skills/vg-blueprint/SKILL.md": "same",
            # build codex skill MISSING — would fail if checked
        })
        global_path = home / ".codex" / "skills" / "vg-blueprint" / "SKILL.md"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("same", encoding="utf-8")

        r = _run([
            "--skill", "blueprint", "--skip-vgflow", "--quiet",
        ], env_overrides={
            "REPO_ROOT": str(tmp_path),
            "HOME": str(home),
            "USERPROFILE": str(home),
        })
        # Should succeed — build skill not checked since --skill=blueprint
        assert r.returncode == 0


# ─── Real-repo integration (sanity check) ──────────────────────────────

class TestRealRepoSanity:
    def test_real_repo_passes_after_sync(self):
        """Run validator against current source-truth repo."""
        r = _run(["--quiet"])
        assert r.returncode == 0, (
            f"Real repo drift detected — run /vg:sync to fix.\n"
            f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
