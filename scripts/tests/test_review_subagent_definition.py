"""R3 Phase E Task 22 — Static tests for vg-review-browser-discoverer subagent.

Asserts:
- agents/vg-review-browser-discoverer/SKILL.md exists with valid frontmatter
- Frontmatter has name, description, tools, model fields
- vg-review-goal-scorer does NOT exist (phase4 stays inline-split per audit)
- SKILL.md mentions Task tool for ≤5 parallel Haiku spawn
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBAGENT_DIR = REPO_ROOT / "agents" / "vg-review-browser-discoverer"
SKILL_MD = SUBAGENT_DIR / "SKILL.md"


def test_subagent_skill_md_exists() -> None:
    """vg-review-browser-discoverer subagent must exist for STEP 3 (browser
    discovery, 947-line source step from backup)."""
    assert SKILL_MD.exists(), (
        f"Missing subagent SKILL.md: {SKILL_MD.relative_to(REPO_ROOT)}. "
        f"R3 Task 18 created this for the HEAVY phase2_browser_discovery "
        f"step. Without it, AI cannot execute STEP 3 of slim review.md."
    )


def test_subagent_frontmatter_has_required_fields() -> None:
    """Anthropic Agent Skills standard: SKILL.md frontmatter must declare
    name, description (becomes /slash-command + system prompt index)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md missing YAML frontmatter (--- ... ---)"
    fm = m.group(1)

    # Required by Anthropic Agent Skills spec
    assert re.search(r"^name:\s*\S+", fm, re.MULTILINE), (
        "frontmatter missing `name:` field (becomes /slash-command per "
        "Anthropic spec)"
    )
    assert re.search(r"^description:", fm, re.MULTILINE), (
        "frontmatter missing `description:` field (used by Claude to decide "
        "when to invoke the skill — first level of progressive disclosure)"
    )

    # VG-specific (not Anthropic-required but expected by VG harness)
    assert re.search(r"^tools:", fm, re.MULTILINE) or re.search(
        r"^allowed-tools:", fm, re.MULTILINE
    ), "frontmatter should declare tools/allowed-tools list"


def test_subagent_name_matches_directory() -> None:
    """name: in frontmatter must match directory name (Claude Code resolution
    rule)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.search(r"^name:\s*(\S+)", text, re.MULTILINE)
    assert m, "frontmatter missing name field"
    assert m.group(1) == "vg-review-browser-discoverer", (
        f"frontmatter name='{m.group(1)}' does not match directory "
        f"'vg-review-browser-discoverer'"
    )


def test_subagent_uses_task_tool_for_haiku_spawn() -> None:
    """Per R3 plan §C: subagent uses Task tool for ≤5 parallel Haiku scanner
    spawn. SKILL.md body should mention this pattern."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Task" in text, (
        "SKILL.md should reference Task tool for parallel Haiku spawn"
    )
    # Sanity check: parallel scan limit
    assert re.search(r"≤?5|max[\s_]?haiku|five|max.*5", text, re.IGNORECASE), (
        "SKILL.md should document the ≤5 parallel slot cap (Playwright MCP "
        "constraint)"
    )


def test_no_vg_review_goal_scorer_exists() -> None:
    """phase4_goal_comparison is binary lookup (audit confirmed 2026-05-03);
    NO scorer subagent. R3 plan §C explicitly forbids creation of this dir
    to prevent future drift back to formula-based scoring.

    If a future contributor creates agents/vg-review-goal-scorer/, they
    must first remove this assertion AND update the architecture decision
    in docs/superpowers/specs/2026-05-03-vg-review-design.md §1.4."""
    forbidden_dir = REPO_ROOT / "agents" / "vg-review-goal-scorer"
    assert not forbidden_dir.exists(), (
        f"agents/vg-review-goal-scorer/ MUST NOT exist. phase4 is binary "
        f"lookup (READY/BLOCKED), not weighted scoring. If this directory "
        f"was created, revert and use the inline-split refs at "
        f"commands/vg/_shared/review/verdict/{{overview,pure-backend-fastpath,"
        f"web-fullstack,profile-branches}}.md instead."
    )


def test_subagent_documents_workflow_steps() -> None:
    """SKILL.md should document the 6-step workflow (validate → allocate →
    partition → spawn → aggregate → return) per R3 Task 18 spec."""
    text = SKILL_MD.read_text(encoding="utf-8")
    # Loose check: at least 4 of these workflow keywords present
    keywords = [
        "validate", "allocate", "partition", "spawn",
        "aggregate", "return",
    ]
    found = sum(1 for kw in keywords if kw.lower() in text.lower())
    assert found >= 4, (
        f"SKILL.md only mentions {found}/6 expected workflow keywords "
        f"({keywords}). Subagent workflow should be explicit per Anthropic "
        f"Agent Skills standard for skill body documentation."
    )


def test_subagent_documents_failure_modes() -> None:
    """Anthropic best practice: skills should document failure modes so AI
    can recover gracefully."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r"failure\s*mode|failure.mode", text, re.IGNORECASE), (
        "SKILL.md should have a 'Failure modes' section per Anthropic skill-"
        "authoring guidelines"
    )
