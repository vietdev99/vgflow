"""v3.6.6 — duplicate Codex project mirrors are pruned, not deduped."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_REPORT_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "sync-and-report.md"
SYNC_REPORT_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "update" / "sync-and-report.md"

def _body() -> str:
    return SYNC_REPORT_CANON.read_text(encoding="utf-8")

def test_project_codex_dedupe_replaced_by_prune():
    body = _body()
    assert "global-only contract: never deploy Codex skills into the project" in body
    assert "vg_uninstall.py" in body
    assert "project-local VG files pruned" in body
    assert "prune_codex_dir()" not in body

def test_no_marker_based_project_or_global_choice_remains():
    body = _body()
    assert "INSTALL_TARGET" not in body
    assert "install-target=project" not in body
    assert "global-side" not in body

def test_project_codex_paths_are_not_deploy_targets():
    body = _body()
    assert '${REPO_ROOT}/.codex/skills/${skill}' not in body
    assert '${REPO_ROOT}/.codex/agents' not in body
    assert '$HOME/.codex/skills/${skill}' in body

def test_mirror_byte_identity():
    assert SYNC_REPORT_CANON.read_bytes() == SYNC_REPORT_MIRROR.read_bytes()
