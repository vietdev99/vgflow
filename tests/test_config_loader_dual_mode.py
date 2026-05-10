"""v2.84.0 Stage 7 critical — config-loader dual-mode read.

Verifies commands/vg/_shared/config-loader.md probes `.vg/config.md` first
and falls back to `.claude/vg.config.md`. Without dual-mode, every skill
that loads config breaks post `vg-migrate-v3.sh` migration.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
LOADER = REPO_ROOT / "commands" / "vg" / "_shared" / "config-loader.md"


# ── static body checks ──────────────────────────────────────────────


def test_loader_probes_new_layout_first():
    body = LOADER.read_text(encoding="utf-8")
    # Probe loop must list new path before legacy
    snippet = body[body.index("VG_CONFIG_PATH=\"\"") :]
    new_idx = snippet.index('".vg/config.md"')
    legacy_idx = snippet.index('".claude/vg.config.md"')
    assert new_idx < legacy_idx, (
        "config-loader must probe .vg/config.md before .claude/vg.config.md"
    )


def test_loader_writes_path_var():
    body = LOADER.read_text(encoding="utf-8")
    assert 'VG_CONFIG_PATH="$candidate"' in body, (
        "loader must capture resolved path into VG_CONFIG_PATH for downstream parsers"
    )


def test_loader_errors_when_neither_exists():
    body = LOADER.read_text(encoding="utf-8")
    assert "neither .vg/config.md nor .claude/vg.config.md found" in body, (
        "error message must enumerate both probe paths"
    )


def test_loader_uses_path_var_for_clean_strip():
    body = LOADER.read_text(encoding="utf-8")
    assert 'sed -e \'1s/^\\xEF\\xBB\\xBF//\' -e \'s/\\r$//\' "$VG_CONFIG_PATH"' in body


def test_loader_model_parsers_use_path_var():
    body = LOADER.read_text(encoding="utf-8")
    # All model awk lookups must use ${VG_CONFIG_PATH:-...} default
    assert '"${VG_CONFIG_PATH:-.claude/vg.config.md}"' in body, (
        "model awk parsers must reference VG_CONFIG_PATH var with legacy fallback"
    )


def test_loader_vg_config_get_uses_resolver():
    body = LOADER.read_text(encoding="utf-8")
    assert "_vg_config_resolve()" in body, (
        "vg_config_get/_array must call _vg_config_resolve helper for dual-mode"
    )
    assert 'local config="$(_vg_config_resolve)"' in body


def test_loader_drift_message_uses_path_var():
    body = LOADER.read_text(encoding="utf-8")
    assert 'sections missing from ${VG_CONFIG_PATH}' in body


def test_loader_mirror_byte_identity():
    canonical = LOADER.read_bytes()
    mirror = (
        REPO_ROOT
        / ".claude"
        / "commands"
        / "vg"
        / "_shared"
        / "config-loader.md"
    ).read_bytes()
    assert canonical == mirror


# ── functional smoke (Linux-only via WSL fragility) ──────────────────


pytestmark_funcsmoke = pytest.mark.skipif(
    sys.platform == "win32",
    reason="WSL bash path mapping fragile on Windows; CI Linux validates",
)


@pytestmark_funcsmoke
def test_loader_picks_new_layout_when_both_present(tmp_path):
    """When both `.vg/config.md` and `.claude/vg.config.md` exist, new wins."""
    if not shutil.which("bash"):
        pytest.skip("bash missing")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".vg").mkdir()
    (proj / ".vg" / "config.md").write_text(
        "project_name: new\npackage_manager: npm\nprofile: web-fullstack\n",
        encoding="utf-8",
    )
    (proj / ".claude").mkdir()
    (proj / ".claude" / "vg.config.md").write_text(
        "project_name: legacy\npackage_manager: npm\nprofile: web-fullstack\n",
        encoding="utf-8",
    )
    # Run just the probe block
    script = """
VG_CONFIG_PATH=""
for candidate in ".vg/config.md" ".claude/vg.config.md"; do
  if [ -f "$candidate" ]; then
    VG_CONFIG_PATH="$candidate"
    break
  fi
done
echo "$VG_CONFIG_PATH"
"""
    r = subprocess.run(
        ["bash", "-c", script],
        cwd=str(proj),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ".vg/config.md"


@pytestmark_funcsmoke
def test_loader_falls_back_to_legacy(tmp_path):
    """No `.vg/config.md`, fallback to `.claude/vg.config.md`."""
    if not shutil.which("bash"):
        pytest.skip("bash missing")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".claude").mkdir()
    (proj / ".claude" / "vg.config.md").write_text(
        "project_name: legacy\npackage_manager: npm\nprofile: web-fullstack\n",
        encoding="utf-8",
    )
    script = """
VG_CONFIG_PATH=""
for candidate in ".vg/config.md" ".claude/vg.config.md"; do
  if [ -f "$candidate" ]; then
    VG_CONFIG_PATH="$candidate"
    break
  fi
done
echo "$VG_CONFIG_PATH"
"""
    r = subprocess.run(
        ["bash", "-c", script],
        cwd=str(proj),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ".claude/vg.config.md"
