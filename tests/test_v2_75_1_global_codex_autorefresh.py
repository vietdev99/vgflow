"""v3.6.6 — global Codex refresh is mandatory on /vg:update."""
from pathlib import Path

SYNC_FILE = Path("commands/vg/_shared/update/sync-and-report.md")
SYNC_MIRROR = Path(".claude/commands/vg/_shared/update/sync-and-report.md")

def test_sync_file_refreshes_global_codex():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "Global ~/.codex deploy is mandatory in global-only mode" in body
    assert 'mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"' in body
    assert 'rm -rf "$HOME/.codex/skills/${skill}"' in body
    assert 'cp -R "$skill_dir"/. "$HOME/.codex/skills/${skill}/"' in body

def test_sync_file_registers_global_agents():
    body = SYNC_FILE.read_text(encoding="utf-8")
    for name in ("vgflow-orchestrator", "vgflow-executor", "vgflow-classifier"):
        assert name in body

def test_sync_file_has_no_global_optout_tristate():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "VG_UPDATE_GLOBAL_CODEX" not in body
    assert "refresh-auto" not in body
    assert "skip-explicit" not in body

def test_sync_file_mirror_byte_identity():
    assert SYNC_FILE.read_bytes() == SYNC_MIRROR.read_bytes()

def test_codex_skill_routes_to_sync_subfile():
    body = Path("codex-skills/vg-update/SKILL.md").read_text(encoding="utf-8")
    assert "_shared/update/sync-and-report.md" in body
