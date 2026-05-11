"""v3.6.6 — /vg:update global-only refactor.

Update refreshes one global VGFlow surface and prunes project-local Claude/Codex
workflow copies. Project marker values are coerced to global.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "preflight.md"
ROTATE = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "rotate-and-repair.md"


def test_preflight_reads_install_target_marker():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert 'INSTALL_TARGET="global"' in body, "preflight must coerce update to global-only"
    assert '${REPO_ROOT}/.vg/.install-target' in body, (
        "preflight must read .vg/.install-target file path"
    )
    assert "coercing to global-only" in body


def test_preflight_skips_helper_check_when_global():
    """vg_update.py is a project-mode helper. Global mode shouldn't require it
    because the global path bypasses 3-way merge entirely."""
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert '[ "$INSTALL_TARGET" != "global" ]' in body, (
        "global mode should bypass vg_update.py existence check"
    )


def test_preflight_has_marker_branch_step():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert '<step name="0b_marker_branch">' in body, (
        "preflight must declare 0b_marker_branch step"
    )


def test_marker_branch_does_git_pull_when_clone():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert 'git pull --ff-only origin main' in body, (
        "global path must git pull when ~/.vgflow is a clone"
    )


def test_marker_branch_falls_back_to_npm():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert 'npm install -g vgflow@latest' in body, (
        "global path must fall back to npm when not a git clone"
    )


def test_marker_branch_reinstalls_hooks_with_mode_global():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert '--mode global' in body
    assert '${HOME}/.claude/settings.json' in body, (
        "hooks must target ~/.claude/settings.json for global mode"
    )


def test_marker_branch_cleans_stale_project_local_dirs():
    body = PREFLIGHT.read_text(encoding="utf-8")
    helper = (REPO_ROOT / "scripts" / "vg_uninstall.py").read_text(encoding="utf-8")
    for d in (
        ".claude/commands/vg",
        ".claude/scripts",
        ".claude/schemas",
        ".claude/templates/vg",
    ):
        assert d in helper, f"stale cleanup helper must enumerate: {d}"
    assert "vg_uninstall.py" in body, "global cleanup must use canonical uninstall helper"
    assert "api-contract, flow-*, test-*" in body, (
        "global cleanup must include non-vg support skill removal"
    )


def test_marker_branch_refreshes_global_codex_before_exit():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "${HOME_VGFLOW}/codex-skills" in body
    assert "${HOME}/.codex/skills" in body
    assert "global Codex refreshed" in body


def test_marker_branch_backs_up_before_cleanup():
    body = PREFLIGHT.read_text(encoding="utf-8")
    helper = (REPO_ROOT / "scripts" / "vg_uninstall.py").read_text(encoding="utf-8")
    assert "vg_uninstall.py" in body
    assert ".vgflow-uninstall-backup" in helper, (
        "stale cleanup helper must backup removed files"
    )


def test_marker_branch_exits_after_global_path():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "exit 0" in body
    # Critical: 0b_marker_branch must short-circuit so v2.x merge flow
    # doesn't run on top of global path.
    section_start = body.index('<step name="0b_marker_branch">')
    section_end = body.index('</step>', section_start)
    section = body[section_start:section_end]
    assert "exit 0" in section, "global branch must exit before legacy merge runs"


def test_marker_branch_writes_global_marker():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert 'printf \'%s\\n\' "global" > "${REPO_ROOT}/.vg/.install-target"' in body


def test_preflight_mirror_byte_identity():
    canonical = PREFLIGHT.read_bytes()
    mirror = (
        REPO_ROOT
        / ".claude"
        / "commands"
        / "vg"
        / "_shared"
        / "update"
        / "preflight.md"
    ).read_bytes()
    assert canonical == mirror


def test_rotate_mirror_byte_identity():
    canonical = ROTATE.read_bytes()
    mirror = (
        REPO_ROOT
        / ".claude"
        / "commands"
        / "vg"
        / "_shared"
        / "update"
        / "rotate-and-repair.md"
    ).read_bytes()
    assert canonical == mirror
