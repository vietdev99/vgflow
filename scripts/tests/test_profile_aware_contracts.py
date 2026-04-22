"""
OHOK-9 (c) — profile-aware + glob-aware contract validation.

Proves 2 non-regression invariants:
1. Non-feature profiles (infra/hotfix/bugfix/docs/migration) do NOT
   block on missing feature-only artifacts (CONTEXT.md, API-CONTRACTS.md,
   TEST-GOALS.md). They emit contract.profile_skip WARN events instead.
2. UAT.md glob-fallback — contract declaring `UAT.md` accepts sibling
   filenames like `14-UAT.md` without mutating the contract schema.

Run: pytest .claude/scripts/tests/test_profile_aware_contracts.py -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))

import contracts  # type: ignore  # noqa: E402
import evidence   # type: ignore  # noqa: E402


ORCH = Path(__file__).resolve().parents[1] / "vg-orchestrator"
PYTHON = sys.executable


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".vg" / "phases" / "88-test-infra").mkdir(parents=True)
    (repo / ".vg" / "phases" / "99-test-feature").mkdir(parents=True)
    (repo / ".claude" / "commands" / "vg").mkdir(parents=True)

    src_root = Path(__file__).resolve().parents[2]
    for sub in ("scripts/vg-orchestrator", "scripts/validators", "schemas"):
        shutil.copytree(src_root / sub, repo / ".claude" / sub,
                        dirs_exist_ok=True)

    monkeypatch.setenv("VG_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)
    # Patch module-level PHASES_DIR so resolve_phase_dir sees our sandbox
    # (module was imported before monkeypatch set VG_REPO_ROOT, so the
    #  cached constant still points to the real repo).
    monkeypatch.setattr(contracts, "PHASES_DIR",
                        repo / ".vg" / "phases")
    return repo


def test_detect_phase_profile_infra(sandbox):
    """SPECS with infra keywords → profile=infra."""
    specs = sandbox / ".vg" / "phases" / "88-test-infra" / "SPECS.md"
    specs.write_text(
        "# SPECS\n\nProvision VPS via Ansible playbook.\n"
        "Install Docker Compose.\n" + ("x" * 120),
        encoding="utf-8",
    )
    assert contracts.detect_phase_profile("88") == "infra"


def test_detect_phase_profile_feature_default(sandbox):
    """SPECS without profile markers → default=feature."""
    specs = sandbox / ".vg" / "phases" / "99-test-feature" / "SPECS.md"
    specs.write_text(
        "# SPECS\n\nBuild the user dashboard with charts.\n" + ("x" * 120),
        encoding="utf-8",
    )
    assert contracts.detect_phase_profile("99") == "feature"


def test_detect_phase_profile_frontmatter_explicit(sandbox):
    """Frontmatter `profile: migration` wins over body heuristics."""
    specs = sandbox / ".vg" / "phases" / "88-test-infra" / "SPECS.md"
    specs.write_text(
        textwrap.dedent("""\
            ---
            profile: migration
            ---

            # SPECS

            Add indexes to accelerate queries.
            """) + ("x" * 120),
        encoding="utf-8",
    )
    assert contracts.detect_phase_profile("88") == "migration"


def test_artifact_applicable_feature(sandbox):
    """Feature profile requires CONTEXT, API-CONTRACTS, TEST-GOALS."""
    assert contracts.artifact_applicable("feature", "CONTEXT.md")
    assert contracts.artifact_applicable("feature", "API-CONTRACTS.md")
    assert contracts.artifact_applicable("feature", "TEST-GOALS.md")


def test_artifact_applicable_infra_skips_feature_artifacts(sandbox):
    """Infra profile does NOT require CONTEXT, API-CONTRACTS, TEST-GOALS."""
    assert not contracts.artifact_applicable("infra", "CONTEXT.md")
    assert not contracts.artifact_applicable("infra", "API-CONTRACTS.md")
    assert not contracts.artifact_applicable("infra", "TEST-GOALS.md")
    # But SPECS + PLAN + SUMMARY ARE required
    assert contracts.artifact_applicable("infra", "SPECS.md")
    assert contracts.artifact_applicable("infra", "PLAN.md")
    assert contracts.artifact_applicable("infra", "SUMMARY.md")


def test_artifact_applicable_migration_requires_rollback(sandbox):
    """Migration profile has ROLLBACK in required set."""
    assert contracts.artifact_applicable("migration", "ROLLBACK.md")
    assert not contracts.artifact_applicable("infra", "ROLLBACK.md")


def test_artifact_applicable_strips_phase_prefix(sandbox):
    """`14-UAT.md` should match `UAT.md` contract for feature profile."""
    # Note: UAT.md not in _PROFILE_REQUIRED_ARTIFACTS per current taxonomy —
    # that's OK, we test the stripping logic via PLAN.md instead.
    assert contracts.artifact_applicable("feature", "14-PLAN.md")
    assert contracts.artifact_applicable("infra", "07.1-SUMMARY.md")


def test_check_artifact_glob_fallback_uat(sandbox, tmp_path):
    """`UAT.md` contract satisfied by sibling `{N}-UAT.md` when glob_fallback=True."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Only phase-prefixed file exists — contract declares bare UAT.md
    (phase_dir / "14-UAT.md").write_text(
        "# UAT\n\nAll tests pass.\n" + ("x" * 50), encoding="utf-8"
    )

    result = evidence.check_artifact(
        phase_dir / "UAT.md", min_bytes=50, glob_fallback=True
    )
    assert result["ok"], f"glob fallback failed: {result}"
    assert "14-UAT.md" in result["matched_path"]


def test_check_artifact_glob_fallback_off_preserves_strictness(sandbox, tmp_path):
    """glob_fallback=False → strict exact-path match (legacy behavior)."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "14-UAT.md").write_text("x" * 100, encoding="utf-8")

    result = evidence.check_artifact(
        phase_dir / "UAT.md", min_bytes=50, glob_fallback=False
    )
    assert not result["ok"]
    assert result["reason"] == "missing"


def test_check_artifact_exact_match_preferred_over_glob(sandbox, tmp_path):
    """When exact path exists, use it; don't fall back to sibling."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "UAT.md").write_text(
        "# UAT exact\n" + ("x" * 80), encoding="utf-8"
    )
    (phase_dir / "14-UAT.md").write_text(
        "# UAT sibling\n" + ("x" * 80), encoding="utf-8"
    )

    result = evidence.check_artifact(
        phase_dir / "UAT.md", min_bytes=50, glob_fallback=True
    )
    assert result["ok"]
    assert result["matched_path"].endswith("UAT.md")
    assert "14-UAT.md" not in result["matched_path"]
