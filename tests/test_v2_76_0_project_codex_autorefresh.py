"""v2.76.0 — symmetric VG_UPDATE_PROJECT_CODEX gate on /vg:update.

Bug: /vg:update step 8_sync_codex unconditionally deployed Codex skills/agents
to project-local .codex/. After v2.75.1 added auto-refresh for global ~/.codex,
users keeping vgflow in global only had no symmetric way to opt project out —
every /vg:update silently re-created .codex/skills/vg-* + .codex/agents/vgflow-*
= duplicate-flow bug at the project side.

Fix: add tri-state VG_UPDATE_PROJECT_CODEX (matches VG_UPDATE_GLOBAL_CODEX
semantics):
  1     -> always deploy to project (legacy/explicit)
  0     -> never deploy to project (opt-out)
  unset -> auto: deploy ONLY if .codex/skills/vg-update already exists
           (i.e., project previously had vgflow installed locally)

Default 'auto' makes /vg:update non-destructive: install.sh remains the
canonical first-time project installer; subsequent updates auto-refresh only
when vgflow is already there.
"""
from pathlib import Path


SYNC_FILE = Path("commands/vg/_shared/update/sync-and-report.md")
SYNC_MIRROR = Path(".claude/commands/vg/_shared/update/sync-and-report.md")
CODEX_SLIM = Path("codex-skills/vg-update/SKILL.md")
CODEX_SLIM_MIRROR = Path(".codex/skills/vg-update/SKILL.md")


def test_sync_file_has_project_autodetect_block():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "PROJECT_CODEX_HAS_VGFLOW" in body, \
        "8_sync_codex must declare PROJECT_CODEX_HAS_VGFLOW for auto-detect"
    assert '[ -d "${REPO_ROOT}/.codex/skills/vg-update" ]' in body, \
        "auto-detect must probe .codex/skills/vg-update existence"


def test_sync_file_has_project_tristate_decision():
    body = SYNC_FILE.read_text(encoding="utf-8")
    expected_states = [
        "deploy-explicit",
        "deploy-auto",
        "skip-explicit",
        "skip-auto",
    ]
    for state in expected_states:
        assert state in body, f"project tri-state decision missing: {state}"


def test_sync_file_handles_project_auto_default():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert '${VG_UPDATE_PROJECT_CODEX:-auto}' in body, \
        "VG_UPDATE_PROJECT_CODEX default must be 'auto' (symmetric with VG_UPDATE_GLOBAL_CODEX)"


def test_sync_file_warns_on_project_explicit_optout_with_stale():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "Stale vgflow detected at .codex/skills" in body, \
        "skip-explicit branch must warn when stale project vgflow present"
    assert "rm -rf .codex/skills/vg-*" in body, \
        "warning must include manual cleanup command for project"
    assert "rm -f .codex/agents/vgflow-*.toml" in body, \
        "warning must include agents cleanup"


def test_sync_file_message_for_project_auto_deploy():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "auto-detected prior project install" in body, \
        "deploy-auto branch must announce auto-detection"


def test_sync_file_legacy_optin_still_supported():
    """VG_UPDATE_PROJECT_CODEX=1 still forces project deploy."""
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "VG_UPDATE_PROJECT_CODEX=1 — refreshed" in body, \
        "explicit opt-in (VG_UPDATE_PROJECT_CODEX=1) message must remain"


def test_sync_file_project_skip_auto_message():
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "set VG_UPDATE_PROJECT_CODEX=1 to deploy" in body, \
        "skip-auto branch must hint at how to enable deploy"


def test_global_codex_gate_unchanged():
    """v2.75.1 global gate must remain intact (no regression)."""
    body = SYNC_FILE.read_text(encoding="utf-8")
    assert "GLOBAL_CODEX_HAS_VGFLOW" in body, "global tri-state must remain"
    assert '${VG_UPDATE_GLOBAL_CODEX:-auto}' in body, "global default must remain auto"
    assert "refresh-explicit" in body and "refresh-auto" in body, \
        "global tri-state states must remain"


def test_sync_file_mirror_byte_identity():
    src = SYNC_FILE.read_bytes()
    dst = SYNC_MIRROR.read_bytes()
    assert src == dst, \
        f"commands/.../sync-and-report.md and .claude mirror differ ({len(src)} vs {len(dst)} bytes)"


def test_codex_slim_documents_project_tristate():
    body = CODEX_SLIM.read_text(encoding="utf-8")
    assert "VG_UPDATE_PROJECT_CODEX" in body, \
        "codex vg-update slim must reference VG_UPDATE_PROJECT_CODEX env var"
    assert "auto-detect prior project install" in body, \
        "codex slim must document auto-detect semantics"


def test_codex_slim_mirror_byte_identity():
    src = CODEX_SLIM.read_bytes()
    dst = CODEX_SLIM_MIRROR.read_bytes()
    assert src == dst, \
        f"codex-skills/vg-update/SKILL.md and .codex mirror differ ({len(src)} vs {len(dst)} bytes)"
