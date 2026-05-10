"""v2.88.0 — /vg:update marker-aware refactor.

Closes 5 gaps from Codex audit (PR #N):
1. /vg:update reads .vg/.install-target marker
2. When marker=global: refresh ~/.vgflow/ via git pull or npm install -g
3. After global refresh: re-install hooks at ~/.claude/settings.json --mode global
4. After global refresh: clean up stale project-local VG-owned Claude/Codex surfaces
5. Project-mode rotate-and-repair passes --mode matching marker (default project)
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "preflight.md"
ROTATE = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "rotate-and-repair.md"


def test_preflight_reads_install_target_marker():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "INSTALL_TARGET=" in body, "preflight must capture marker into INSTALL_TARGET"
    assert '${REPO_ROOT}/.vg/.install-target' in body, (
        "preflight must read .vg/.install-target file path"
    )


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


def test_rotate_and_repair_passes_mode_to_install_hooks():
    body = ROTATE.read_text(encoding="utf-8")
    assert "HOOK_MODE=" in body
    assert '.vg/.install-target' in body, (
        "rotate-and-repair must read marker to set HOOK_MODE"
    )
    assert '--mode "$HOOK_MODE"' in body, (
        "install-hooks invocation must pass --mode $HOOK_MODE"
    )


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
