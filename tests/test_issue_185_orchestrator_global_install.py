"""Regression test for issue #185 — vg-orchestrator missing on PATH in
global-only installs.

Symptoms reported:
- Skill bash blocks call `${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator
  run-start ...` but the project-relative path does not exist in global-only
  installs (CLAUDE.md mandates no project vendor).
- Hook scripts at `~/.vgflow/scripts/hooks/*.sh` use `command -v
  vg-orchestrator` which returns nothing because only `vg` is symlinked.
- Effect: `/vg:test` preflight cannot run, the whole pipeline blocks.

Fix (v4.11.0): vg-cli-dispatcher.sh gains two helpers used during install/sync:
- refresh_global_orchestrator_cli: writes a CLI wrapper at
  ~/.local/bin/vg-orchestrator. The wrapper resolves VG_HOME at runtime and
  invokes `python3 $VG_HOME/scripts/vg-orchestrator "$@"`. This makes
  `command -v vg-orchestrator` succeed and gives hooks a stable entry point.
- link_project_orchestrator_shim: links project `.claude/scripts/vg-orchestrator/`
  to `~/.vgflow/scripts/vg-orchestrator/` so the ~279 legacy skill bash blocks
  that use the project-relative path keep working without a mass rewrite.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "bin" / "vg-cli-dispatcher.sh"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_dispatcher_defines_orchestrator_cli_helper():
    body = _read(DISPATCHER)
    assert "refresh_global_orchestrator_cli()" in body, (
        "Issue #185: dispatcher must define refresh_global_orchestrator_cli "
        "to create ~/.local/bin/vg-orchestrator wrapper"
    )
    assert "${HOME}/.local/bin/vg-orchestrator" in body, (
        "Wrapper target path must be ~/.local/bin/vg-orchestrator"
    )


def test_orchestrator_wrapper_invokes_python_on_vg_home_package():
    body = _read(DISPATCHER)
    # The generated wrapper must exec python3 on the orchestrator package dir.
    # Wrapper string is double-quoted inside bash so $ + " are backslash-escaped.
    assert 'VG_HOME' in body and 'vg-orchestrator' in body
    # Find any line where the wrapper invokes python on the orchestrator package
    wrapper_lines = [l for l in body.splitlines() if 'exec' in l and 'PY' in l and 'VGH' in l]
    assert wrapper_lines, (
        "Issue #185: wrapper must invoke python on $VG_HOME/scripts/vg-orchestrator"
    )
    assert any('vg-orchestrator' in l for l in wrapper_lines), (
        "Issue #185: wrapper exec line must reference vg-orchestrator package dir"
    )


def test_dispatcher_defines_project_shim_helper():
    body = _read(DISPATCHER)
    assert "link_project_orchestrator_shim()" in body, (
        "Issue #185: dispatcher must define link_project_orchestrator_shim to "
        "create project .claude/scripts/vg-orchestrator/ pointer for legacy "
        "relative-path skill bash blocks"
    )


def test_project_shim_only_runs_for_vg_enabled_projects():
    body = _read(DISPATCHER)
    # Helper must guard on .git or .vg marker (not litter random dirs)
    assert '${project_root}/.git' in body or '${project_root}/.vg' in body, (
        "Issue #185: project shim must guard on project_root/.git or "
        "project_root/.vg presence — do not litter random dirs"
    )


def test_install_path_invokes_both_helpers():
    body = _read(DISPATCHER)
    # The `install)` case must call both helpers
    install_idx = body.index("install)")
    next_case_idx = body.index("sync|update)", install_idx)
    install_block = body[install_idx:next_case_idx]
    assert "refresh_global_orchestrator_cli" in install_block, (
        "Issue #185: install) case must call refresh_global_orchestrator_cli"
    )
    assert "link_project_orchestrator_shim" in install_block, (
        "Issue #185: install) case must call link_project_orchestrator_shim "
        "with the project_root"
    )


def test_sync_path_invokes_both_helpers():
    body = _read(DISPATCHER)
    sync_idx = body.index("sync|update)")
    next_case_idx = body.index("doctor)", sync_idx)
    sync_block = body[sync_idx:next_case_idx]
    assert "refresh_global_orchestrator_cli" in sync_block, (
        "Issue #185: sync|update) case must also refresh the orchestrator CLI "
        "wrapper so existing installs heal on next sync"
    )
    assert "link_project_orchestrator_shim" in sync_block, (
        "Issue #185: sync|update) case must also relink project shim"
    )
