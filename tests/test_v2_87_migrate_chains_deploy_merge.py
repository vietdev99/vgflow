"""v2.87.0 — vg-migrate-v3.sh chains merge-deploy-states.py at step 2.5.

Verifies post-migration projects automatically get .vg/deploy/STATE.json
populated from legacy per-phase data, no manual step required.
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
MIGRATE_SH = REPO_ROOT / "scripts" / "migrate" / "vg-migrate-v3.sh"


_BASH_SKIP = [
    pytest.mark.skipif(not shutil.which("bash"), reason="bash missing"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="WSL path mapping fragile; CI Linux validates",
    ),
]


# ── Content-only static checks (run on all platforms) ──


def test_migrate_v3_has_step_2_5_merge_block():
    body = MIGRATE_SH.read_text(encoding="utf-8")
    assert "[2.5]" in body, "step 2.5 must be present"
    assert "merge-deploy-states.py" in body, "must reference merge helper"


def test_migrate_v3_step_2_5_handles_rc_2_as_no_op():
    """rc=2 from merge helper = no per-phase state found = legitimate no-op."""
    body = MIGRATE_SH.read_text(encoding="utf-8")
    assert 'MERGE_RC' in body
    assert 'no per-phase' in body.lower() or 'nothing to merge' in body.lower()


def test_migrate_v3_step_2_5_probes_multiple_locations():
    body = MIGRATE_SH.read_text(encoding="utf-8")
    for needle in (
        ".claude/scripts/migrate/merge-deploy-states.py",
        "${HOME}/.vgflow/scripts/migrate/merge-deploy-states.py",
        "${VG_HOME:-}/scripts/migrate/merge-deploy-states.py",
    ):
        assert needle in body, f"step 2.5 must probe path: {needle}"


def test_migrate_v3_step_2_5_uses_backup_flag():
    body = MIGRATE_SH.read_text(encoding="utf-8")
    assert "--backup" in body, "step 2.5 must call merge helper with --backup"


def test_migrate_v3_mirror_byte_identity():
    canonical = MIGRATE_SH.read_bytes()
    mirror = (
        REPO_ROOT / ".claude" / "scripts" / "migrate" / "vg-migrate-v3.sh"
    ).read_bytes()
    assert canonical == mirror


# ── Functional tests (Linux-only via WSL fragility) ──


def _make_legacy_with_deploy_state(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@x.dev"], cwd=str(proj), check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=str(proj), check=True
    )
    (proj / "ROADMAP.md").write_text("# r\n", encoding="utf-8")
    (proj / "FOUNDATION.md").write_text("# f\n", encoding="utf-8")
    (proj / "vg.config.md").write_text("# c\n", encoding="utf-8")
    (proj / ".claude").mkdir()
    (proj / ".claude" / "VGFLOW-VERSION").write_text("2.75.2", encoding="utf-8")
    (proj / ".claude" / "settings.json").write_text('{"hooks":{}}', encoding="utf-8")
    # Per-phase deploy state across 2 phases
    p5 = proj / ".vg" / "phases" / "5"
    p5.mkdir(parents=True)
    (p5 / "DEPLOY-STATE.json").write_text(
        json.dumps(
            {
                "deployed": {
                    "prod": {
                        "sha": "abc1234",
                        "deployed_at": "2026-05-10T10:00:00Z",
                    }
                },
                "preferred_env_for": "prod",
            }
        ),
        encoding="utf-8",
    )
    p6 = proj / ".vg" / "phases" / "6"
    p6.mkdir(parents=True)
    (p6 / "DEPLOY-STATE.json").write_text(
        json.dumps(
            {
                "deployed": {
                    "staging": {
                        "sha": "def5678",
                        "deployed_at": "2026-05-10T11:00:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "legacy"], cwd=str(proj), check=True
    )
    return proj


@pytest.mark.skipif(not shutil.which("bash"), reason="bash missing")
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="WSL path mapping fragile; CI Linux validates",
)
def test_full_migration_writes_project_state(tmp_path):
    proj = _make_legacy_with_deploy_state(tmp_path)
    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "VG_HOME": str(REPO_ROOT)})
    r = subprocess.run(
        ["bash", str(MIGRATE_SH), "--target=global", "--yes"],
        cwd=str(proj),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"err={r.stderr}\nout={r.stdout}"

    state_file = proj / ".vg" / "deploy" / "STATE.json"
    assert state_file.exists(), (
        "post-migration project must have .vg/deploy/STATE.json"
    )
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(state["envs"].keys()) == {"prod", "staging"}
    assert state["envs"]["prod"]["sha"] == "abc1234"
    assert state["envs"]["staging"]["sha"] == "def5678"
    assert state["preferred_env_for_phase"]["5"] == "prod"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash missing")
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="WSL path mapping fragile; CI Linux validates",
)
def test_full_migration_no_per_phase_state_skips_gracefully(tmp_path):
    """Project without any DEPLOY-STATE.json — migration skips step 2.5 without erroring."""
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@x.dev"], cwd=str(proj), check=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(proj), check=True)
    (proj / "ROADMAP.md").write_text("# r", encoding="utf-8")
    (proj / ".claude").mkdir()
    (proj / ".claude" / "VGFLOW-VERSION").write_text("2.75.2", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "legacy"], cwd=str(proj), check=True
    )

    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "VG_HOME": str(REPO_ROOT)})
    r = subprocess.run(
        ["bash", str(MIGRATE_SH), "--target=global", "--yes"],
        cwd=str(proj),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"err={r.stderr}\nout={r.stdout}"
    # No STATE.json (nothing to merge) — that's fine, migration succeeded
    assert not (proj / ".vg" / "deploy" / "STATE.json").exists()
    # Output mentions the no-op
    assert "no per-phase" in (r.stdout + r.stderr).lower() or \
           "nothing to merge" in (r.stdout + r.stderr).lower()
