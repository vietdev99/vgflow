"""v3.6.6 — /vg:update is global-only for Codex.

Project-local .codex mirrors are no longer refreshed. The canonical Codex
surface is `codex-skills/` in the source repo and `~/.codex/skills` at
install/update time.
"""
from pathlib import Path

SYNC_FILE = Path("commands/vg/_shared/update/sync-and-report.md")
SYNC_MIRROR = Path(".claude/commands/vg/_shared/update/sync-and-report.md")
CODEX_SLIM = Path("codex-skills/vg-update/SKILL.md")
CODEX_PROJECT_MIRROR = Path(".codex/skills/vg-update/SKILL.md")

def test_sync_file_disables_project_codex_deploy():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "global-only contract: never deploy Codex skills into the project" in body
    assert "Codex project deploy: disabled (global-only)" in body
    assert 'mkdir -p "${REPO_ROOT}/.codex/skills"' not in body
    assert 'cp -R "$skill_dir"/. "${REPO_ROOT}/.codex/skills/${skill}/"' not in body

def test_sync_file_prunes_project_local_vg_files():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "vg_uninstall.py" in body
    assert '--root "$REPO_ROOT" --apply' in body

def test_sync_file_refreshes_global_codex_unconditionally():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "Global ~/.codex deploy is mandatory in global-only mode" in body
    assert 'mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"' in body
    assert 'cp -R "$skill_dir"/. "$HOME/.codex/skills/${skill}/"' in body
    assert "Codex global deploy: refreshed ~/.codex skills/agents (global-only)" in body

def test_sync_file_no_project_codex_tristate():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "VG_UPDATE_PROJECT_CODEX" not in body
    assert "deploy-auto" not in body
    assert "deploy-explicit" not in body

def test_global_codex_agents_registered():
    body = SYNC_FILE.read_text(encoding="utf-8")
    for name in ("vgflow-orchestrator", "vgflow-executor", "vgflow-classifier"):
        assert name in body

def test_sync_file_mirror_byte_identity():
    assert SYNC_FILE.read_bytes() == SYNC_MIRROR.read_bytes()

def test_codex_slim_documents_global_only():
    body = CODEX_SLIM.read_text(encoding="utf-8")
    assert "`~/.codex/skills`" in body
    assert "Project-local VG-owned `.claude/` and `.codex/` files are pruned" in body
    assert "VG_UPDATE_PROJECT_CODEX" not in body

def test_project_codex_slim_mirror_absent_global_only():
    assert not CODEX_PROJECT_MIRROR.exists()
