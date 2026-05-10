"""v2.76.0 Stage 1.2 — find_vg_home() helper for v3.0.0.

Resolves WHERE static VG harness assets live (skills, commands, scripts,
schemas) — distinct from find_repo_root() which resolves WHERE project state
lives (.vg/).

Resolution priority:
  1. VG_HOME env var
  2. Project marker .vg/.install-target → "global"|"project"
  3. Legacy detect: .claude/VGFLOW-VERSION present → project mode
  4. Global fallback: ~/.vgflow/ if exists
  5. Error

Source plan: docs/plans/2026-05-09-vg-global-install-implementation.md Stage 1.2
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HELPER = (
    Path(__file__).resolve().parent.parent
    / ".claude"
    / "scripts"
    / "vg-orchestrator"
    / "_vg_home.py"
)


def _run_resolver(cwd: Path, env_extra: dict | None = None) -> tuple[int, str, str]:
    code = (
        f"import sys; sys.path.insert(0, {str(HELPER.parent)!r}); "
        "from _vg_home import find_vg_home; print(find_vg_home())"
    )
    env = os.environ.copy()
    # Strip inherited VG_* env so each test sets exactly what it needs
    for k in ("VG_HOME", "VG_REPO_ROOT", "VG_PROJECT"):
        env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout.strip(), r.stderr


def test_env_var_top_priority(tmp_path):
    """VG_HOME env always wins."""
    fake = tmp_path / "fake_vgflow"
    fake.mkdir()
    rc, out, err = _run_resolver(tmp_path, {"VG_HOME": str(fake)})
    assert rc == 0, f"rc={rc} err={err}"
    assert Path(out).resolve() == fake.resolve()


def test_marker_global_loads_from_home(tmp_path):
    """Marker .vg/.install-target=global → resolve to ~/.vgflow/ if exists."""
    proj = tmp_path / "proj"
    (proj / ".vg").mkdir(parents=True)
    (proj / ".vg" / ".install-target").write_text("global", encoding="utf-8")
    (proj / ".git").mkdir()
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".vgflow").mkdir()
    rc, out, err = _run_resolver(
        proj,
        {
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
            "VG_PROJECT": str(proj),
        },
    )
    assert rc == 0, f"rc={rc} err={err}"
    assert Path(out).resolve() == (fake_home / ".vgflow").resolve()


def test_marker_project_loads_from_dot_claude(tmp_path):
    """Marker .vg/.install-target=project → resolve to .claude/."""
    proj = tmp_path / "proj"
    (proj / ".vg").mkdir(parents=True)
    (proj / ".vg" / ".install-target").write_text("project", encoding="utf-8")
    (proj / ".claude").mkdir()
    (proj / ".git").mkdir()
    rc, out, err = _run_resolver(proj, {"VG_PROJECT": str(proj)})
    assert rc == 0, f"rc={rc} err={err}"
    assert Path(out).resolve() == (proj / ".claude").resolve()


def test_marker_global_but_home_missing_errors(tmp_path):
    """Marker=global but ~/.vgflow/ missing → RuntimeError."""
    proj = tmp_path / "proj"
    (proj / ".vg").mkdir(parents=True)
    (proj / ".vg" / ".install-target").write_text("global", encoding="utf-8")
    (proj / ".git").mkdir()
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    rc, out, err = _run_resolver(
        proj,
        {
            "HOME": str(empty_home),
            "USERPROFILE": str(empty_home),
            "VG_PROJECT": str(proj),
        },
    )
    assert rc != 0, f"expected error rc != 0; got rc={rc} stdout={out}"
    assert "global" in err.lower() or "vgflow" in err.lower()


def test_legacy_no_marker_falls_back_to_dot_claude(tmp_path):
    """No marker + .claude/VGFLOW-VERSION present → legacy project mode."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "VGFLOW-VERSION").write_text("2.75.2", encoding="utf-8")
    (proj / ".git").mkdir()
    rc, out, err = _run_resolver(proj, {"VG_PROJECT": str(proj)})
    assert rc == 0, f"rc={rc} err={err}"
    assert Path(out).resolve() == (proj / ".claude").resolve()


def test_no_marker_no_legacy_uses_global_fallback(tmp_path):
    """No marker, no legacy .claude → fall back to ~/.vgflow/ if exists."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".vgflow").mkdir()
    rc, out, err = _run_resolver(
        proj,
        {
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
            "VG_PROJECT": str(proj),
        },
    )
    assert rc == 0, f"rc={rc} err={err}"
    assert Path(out).resolve() == (fake_home / ".vgflow").resolve()


def test_no_marker_no_legacy_no_global_errors(tmp_path):
    """No marker, no legacy, no ~/.vgflow → RuntimeError with install hint."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    rc, out, err = _run_resolver(
        proj,
        {
            "HOME": str(empty_home),
            "USERPROFILE": str(empty_home),
            "VG_PROJECT": str(proj),
        },
    )
    assert rc != 0, f"expected error; got rc={rc} stdout={out}"
    assert "vgflow" in err.lower() or "install" in err.lower()
