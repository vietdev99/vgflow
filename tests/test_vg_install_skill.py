"""v3.6.6 — /vg:install global-only structure tests.

Verifies install.md skill exists, has required frontmatter, documents
global-only cleanup, and routes through bin/vg-cli-dispatcher.sh.

Source plan: docs/plans/2026-05-09-vg-global-install-implementation.md Stage 5
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_MD = REPO_ROOT / "commands" / "vg" / "install.md"
INSTALL_MD_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "install.md"
CODEX_INSTALL = REPO_ROOT / "codex-skills" / "vg-install" / "SKILL.md"


def test_install_md_exists():
    assert INSTALL_MD.exists(), "commands/vg/install.md must exist (Stage 5.1)"


def test_install_md_has_required_frontmatter():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert body.startswith("---\n"), "must start with frontmatter"
    fm_end = body.index("\n---\n", 4)
    fm = body[:fm_end]
    assert "name: vg:install" in fm, "frontmatter missing name: vg:install"
    assert "description:" in fm
    assert "argument-hint:" in fm
    assert "AskUserQuestion" in fm, "must declare AskUserQuestion allowed-tool"
    assert "Bash" in fm, "must declare Bash allowed-tool"


def test_install_md_emits_telemetry():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert 'event_type: "install.started"' in body
    assert 'event_type: "install.completed"' in body


def test_install_md_documents_target_flag():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert "--target=global" in body
    assert "global-only" in body
    assert "project-local" in body and "VG-owned" in body
    assert "coerce" in body


def test_install_md_documents_repair_flag():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert "--repair" in body
    assert "REPAIR=" in body, "bash must parse --repair flag"


def test_install_md_routes_through_dispatcher():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert "vg-cli-dispatcher.sh" in body, (
        "install.md must invoke bin/vg-cli-dispatcher.sh (no parallel install logic)"
    )
    assert 'install "--${RESOLVED}"' in body


def test_install_md_writes_marker_on_drift():
    body = INSTALL_MD.read_text(encoding="utf-8")
    # Must check marker after dispatcher and write directly if dispatcher path
    # didn't set it (e.g., dispatcher older or not in git repo).
    assert "marker mismatch" in body
    assert 'printf \'%s\\n\' "$RESOLVED" > "$MARKER"' in body


def test_install_md_backs_up_when_switching():
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert "NEED_BACKUP=1" in body
    assert ".vg/.backup-" in body, "backup directory pattern must use .vg/.backup-<ts>/"


def test_install_md_decision_matrix_present():
    """Decision matrix should cover global-only coercion."""
    body = INSTALL_MD.read_text(encoding="utf-8")
    assert "Decision matrix" in body
    assert "Install global" in body
    assert "project/switch" in body


def test_install_md_mirror_byte_identity():
    canonical = INSTALL_MD.read_bytes()
    mirror = INSTALL_MD_MIRROR.read_bytes()
    assert canonical == mirror, "commands/.../install.md and .claude mirror differ"


def test_codex_install_skill_exists():
    assert CODEX_INSTALL.exists(), "codex-skills/vg-install/SKILL.md must exist"


def test_project_codex_skill_mirror_removed_for_global_only():
    project_mirror = REPO_ROOT / ".codex" / "skills" / "vg-install" / "SKILL.md"
    assert not project_mirror.exists(), "project-local .codex skills must not be committed in global-only mode"


def test_codex_install_documents_codex_runtime():
    """Codex skill should carry adapter prefix even though source is shared."""
    body = CODEX_INSTALL.read_text(encoding="utf-8")
    assert "codex_skill_adapter" in body, (
        "codex skill must include adapter prefix for runtime parity"
    )
