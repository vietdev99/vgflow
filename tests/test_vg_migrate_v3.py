"""v2.83.0 Stage 8 — vg-migrate-v3.sh smoke tests."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SH = REPO_ROOT / "scripts" / "migrate" / "vg-migrate-v3.sh"


pytestmark = [
    pytest.mark.skipif(not shutil.which("bash"), reason="bash missing"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="WSL path mapping fragile; CI Linux validates",
    ),
]


def _run(args: list[str], cwd: Path, env: dict | None = None) -> tuple[int, str, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    r = subprocess.run(
        ["bash", str(MIGRATE_SH), *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


def _make_legacy_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@x.dev"], cwd=str(proj), check=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(proj), check=True)
    (proj / "ROADMAP.md").write_text("# legacy roadmap\n", encoding="utf-8")
    (proj / "FOUNDATION.md").write_text("# legacy foundation\n", encoding="utf-8")
    (proj / "vg.config.md").write_text("# legacy config\n", encoding="utf-8")
    (proj / ".claude").mkdir()
    (proj / ".claude" / "VGFLOW-VERSION").write_text("2.75.2", encoding="utf-8")
    (proj / ".claude" / "settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init legacy"], cwd=str(proj), check=True
    )
    return proj


def test_requires_target_arg(tmp_path):
    proj = _make_legacy_project(tmp_path)
    rc, out, err = _run([], proj)
    assert rc == 1
    assert "target=global|project required" in (out + err).lower() \
        or "--target=global|project" in (out + err)


def test_rejects_invalid_target(tmp_path):
    proj = _make_legacy_project(tmp_path)
    rc, out, err = _run(["--target=bogus"], proj)
    assert rc == 1


def test_dry_run_does_not_mutate(tmp_path):
    proj = _make_legacy_project(tmp_path)
    before_roadmap = (proj / "ROADMAP.md").read_text()
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    rc, out, err = _run(
        ["--target=global", "--dry-run", "--yes"],
        proj,
        env={"HOME": str(fake_home), "VG_HOME": str(REPO_ROOT)},
    )
    # Source ROADMAP.md still at legacy location
    assert (proj / "ROADMAP.md").exists()
    assert (proj / "ROADMAP.md").read_text() == before_roadmap
    # No marker written
    assert not (proj / ".vg" / ".install-target").exists()


def test_dirty_tree_refused(tmp_path):
    proj = _make_legacy_project(tmp_path)
    (proj / "uncommitted.txt").write_text("dirty", encoding="utf-8")
    rc, out, err = _run(["--target=global", "--yes"], proj)
    assert rc == 2
    assert "dirty" in (out + err).lower()


def test_full_migration_to_global(tmp_path):
    proj = _make_legacy_project(tmp_path)
    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    rc, out, err = _run(
        ["--target=global", "--yes"],
        proj,
        env={"HOME": str(fake_home), "VG_HOME": str(REPO_ROOT)},
    )
    assert rc == 0, f"err={err}\nout={out}"
    # Docs moved
    assert (proj / ".vg" / "ROADMAP.md").exists()
    assert (proj / ".vg" / "FOUNDATION.md").exists()
    assert (proj / ".vg" / "config.md").exists()
    assert not (proj / "ROADMAP.md").exists()
    # Marker
    marker = (proj / ".vg" / ".install-target").read_text(encoding="utf-8").strip()
    assert marker == "global"
    # Backup directory created
    backups = list((proj / ".vg").glob(".backup-*"))
    assert len(backups) == 1
    # .gitignore has whitelist
    gi = (proj / ".gitignore").read_text(encoding="utf-8")
    assert "VGFlow v3 layout" in gi
    assert "!.vg/ROADMAP.md" in gi


def test_idempotent_when_already_at_target(tmp_path):
    """Re-running with same target after success exits 0 with no-op message."""
    proj = _make_legacy_project(tmp_path)
    fake_home = tmp_path / "fakehome"
    (fake_home / ".claude").mkdir(parents=True)
    env = {"HOME": str(fake_home), "VG_HOME": str(REPO_ROOT)}
    rc1, _, _ = _run(["--target=global", "--yes"], proj, env)
    assert rc1 == 0
    # Commit so working tree is clean for second run
    subprocess.run(["git", "add", "-A"], cwd=str(proj), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "post-migrate"], cwd=str(proj), check=True
    )
    rc2, out2, _ = _run(["--target=global", "--yes"], proj, env)
    assert rc2 == 0
    assert "already at target=global" in out2
