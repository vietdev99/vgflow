"""B100 v4.69.3 — issue #203 subagents not shipped in install.

User report:
> "Skills reference 4 subagents that don't exist in ~/.claude/agents/:
> vg-test-goal-verifier, vg-test-fixer, vg-test-codegen, vg-reflector.
> Each skill HARD-GATE says 'You MUST spawn subagent — DO NOT run inline'.
> With subagent missing, harness blocks. Consumers either: override + run
> inline (96.5% inline-skip rate per Codex review), spawn fallback
> general-purpose agent (drops contract guarantees), or stop pipeline."

## Root cause

`install.sh` line 160 only does `cp agents/*.md` — catches top-level
single-file agents (vg-planner.md, vg-plan-checker.md) but misses
ALL directory-form subagents:
  - vg-test-goal-verifier/SKILL.md
  - vg-test-fixer/SKILL.md
  - vg-test-codegen/SKILL.md
  - vg-blueprint-contracts/SKILL.md
  - vg-blueprint-fe-contracts/SKILL.md
  - vg-blueprint-planner/SKILL.md
  - vg-blueprint-workflows/SKILL.md
  - vg-build-post-executor/SKILL.md
  - vg-build-task-executor/SKILL.md
  - vg-accept-cleanup/SKILL.md
  - vg-accept-uat-builder/SKILL.md
  - vg-field-test-analyzer/SKILL.md

`bin/vg-cli-dispatcher.sh` had no `refresh_global_claude_agents()`
function at all — global sync NEVER refreshed `~/.claude/agents/`.
Subagents only landed via initial install (and only the .md ones).

(Note: vg-reflector is a SKILL — lives under `skills/`, not `agents/`.
Loaded via skills install path, not agent path. Not in scope for B100.)

## Fix

`install.sh`:
- Added loop that walks `agents/*/` subdirs, copies each containing
  SKILL.md into `~/.claude/agents/<name>/`
- Logs split counts (top-level vs subagent dir)

`bin/vg-cli-dispatcher.sh`:
- New `refresh_global_claude_agents()` function — copies top-level *.md
  + subagent dirs from `~/.vgflow/agents/` to `~/.claude/agents/`
- Wired into both `install` and `sync|update` dispatcher subcommands
  (lines 478, 520 — matched pattern of existing refresh_global_*)

Now `~/.vgflow/sync.sh` (and fresh `install.sh`) ship all subagent dirs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = REPO_ROOT / "install.sh"
INSTALL_MIRROR = REPO_ROOT / ".claude" / "install.sh"
DISPATCHER = REPO_ROOT / "bin" / "vg-cli-dispatcher.sh"
AGENTS_DIR = REPO_ROOT / "agents"


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

def test_b100_install_sh_copies_subagent_dirs() -> None:
    body = INSTALL.read_text(encoding="utf-8")
    # Must reference the directory-walking pattern
    assert 'find "$SCRIPT_DIR/agents"' in body, (
        "install.sh must walk agents subdirs"
    )
    assert "SKILL.md" in body, (
        "install.sh must check for SKILL.md in each subagent dir"
    )
    assert "B100 v4.69.3" in body, "B100 marker missing"


def test_b100_install_sh_preserves_top_level_md_copy() -> None:
    """Backward compat: existing top-level *.md copy must still work."""
    body = INSTALL.read_text(encoding="utf-8")
    assert 'cp "$SCRIPT_DIR/agents/"*.md' in body


def test_b100_install_sh_logs_split_counts() -> None:
    body = INSTALL.read_text(encoding="utf-8")
    assert "AGENT_MD_COUNT" in body
    assert "AGENT_DIR_COUNT" in body
    assert "AGENT_TOTAL" in body


def test_b100_dispatcher_has_refresh_agents_fn() -> None:
    body = DISPATCHER.read_text(encoding="utf-8")
    assert "refresh_global_claude_agents()" in body, (
        "dispatcher needs new refresh_global_claude_agents fn"
    )


def test_b100_dispatcher_refresh_agents_called_on_install_and_sync() -> None:
    body = DISPATCHER.read_text(encoding="utf-8")
    # Should be called at least twice (install path + sync path)
    occurrences = body.count("refresh_global_claude_agents")
    # Once for the definition + 2 callsites (install + sync) = 3
    assert occurrences >= 3, (
        f"refresh_global_claude_agents should be called from both install + sync, "
        f"found {occurrences} occurrences (need definition + 2 callsites)"
    )


def test_b100_dispatcher_walks_subagent_dirs() -> None:
    body = DISPATCHER.read_text(encoding="utf-8")
    # Function body must scan for SKILL.md in subagent dirs
    fn_idx = body.index("refresh_global_claude_agents()")
    # Function ends at next blank-then-non-indented line — heuristically
    # grab next 2000 chars
    region = body[fn_idx:fn_idx + 2000]
    assert "SKILL.md" in region
    assert "mindepth 1 -maxdepth 1 -type d" in region


def test_b100_install_mirror_parity() -> None:
    assert INSTALL.read_bytes() == INSTALL_MIRROR.read_bytes(), (
        "install.sh mirror drift — copy to .claude/install.sh"
    )


# ---------------------------------------------------------------------------
# Source-of-truth: each subagent dir should exist with SKILL.md
# ---------------------------------------------------------------------------

REQUIRED_SUBAGENT_DIRS = [
    "vg-test-goal-verifier",
    "vg-test-fixer",
    "vg-test-codegen",
]


def test_b100_required_subagent_dirs_present() -> None:
    """Per issue #203: these 3 subagents are referenced by /vg:test +
    /vg:test-spec skills. Source repo must have them as dirs with SKILL.md."""
    missing = []
    for name in REQUIRED_SUBAGENT_DIRS:
        d = AGENTS_DIR / name
        if not d.is_dir() or not (d / "SKILL.md").is_file():
            missing.append(name)
    assert not missing, f"Missing subagent dirs in source: {missing}"
