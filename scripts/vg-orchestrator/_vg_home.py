"""Resolve VG harness location (where static assets live).

Distinct from _repo_root.py (project state location):
  - VG_HOME    → static assets: skills, commands, scripts, schemas, codex-skills
  - VG_PROJECT → project state: .vg/ (events.db, runs/, phases/, bootstrap/)

v2.76.0 (Stage 1.2 of v3.0.0 plan): introduces this helper so global install
(`~/.vgflow/`) and legacy project-local install (`.claude/`) coexist via a
single resolution function.

Resolution priority:
  1. VG_HOME env var — explicit, trusted
  2. Project marker .vg/.install-target → "global"|"project"
  3. Legacy detect: .claude/VGFLOW-VERSION present → project mode (.claude/)
  4. Global fallback: ~/.vgflow/ if exists
  5. RuntimeError with npm install hint
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _repo_root import find_repo_root


def find_vg_home(start_file: str | None = None) -> Path:
    """Return absolute Path to VG harness install root.

    Args:
        start_file: Optional `__file__` of the caller, forwarded to
          find_repo_root() for the marker-driven branch.
    """
    # 1. Explicit env
    env = os.environ.get("VG_HOME")
    if env:
        return Path(env).resolve()

    # 2. Marker-driven (project tells us global vs project)
    project = find_repo_root(start_file)
    marker = project / ".vg" / ".install-target"
    if marker.exists():
        target = marker.read_text(encoding="utf-8").strip()
        if target == "global":
            home_vgflow = Path.home() / ".vgflow"
            if home_vgflow.exists():
                return home_vgflow
            raise RuntimeError(
                f"Project marked install-target=global but ~/.vgflow/ missing "
                f"({home_vgflow}). Run `/vg:install --repair` or switch to "
                f"project mode."
            )
        if target == "project":
            return project / ".claude"

    # 3. Legacy detect (no marker but .claude/VGFLOW-VERSION present)
    legacy_version = project / ".claude" / "VGFLOW-VERSION"
    if legacy_version.exists():
        return project / ".claude"

    # 4. Global fallback (~/.vgflow/ exists)
    home_vgflow = Path.home() / ".vgflow"
    if home_vgflow.exists():
        return home_vgflow

    # 5. Not installed anywhere
    raise RuntimeError(
        "VG not installed. Run: npm install -g vgflow"
    )
