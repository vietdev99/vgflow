"""R3.5 Roam Pilot — decomposition-only contract: NO new agent SKILL.md files."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_new_roam_subagent_skill_files():
    """R3.5 is decomposition-only; no new vg-roam-* agent SKILL.md should exist.

    Existing auto-fix subagent (if any) is preserved at its existing path —
    just ensure NO new vg-roam-* agent dirs were created by R3.5.
    """
    forbidden = [
        "agents/vg-roam-config-gate",
        "agents/vg-roam-discovery",
        "agents/vg-roam-aggregator",
        "agents/vg-roam-spawn-executors",
        "agents/vg-roam-preflight",
        "agents/vg-roam-artifacts",
        "agents/vg-roam-close",
        ".claude/agents/vg-roam-config-gate",
        ".claude/agents/vg-roam-discovery",
        ".claude/agents/vg-roam-aggregator",
        ".claude/agents/vg-roam-spawn-executors",
        ".claude/agents/vg-roam-preflight",
        ".claude/agents/vg-roam-artifacts",
        ".claude/agents/vg-roam-close",
    ]
    for p in forbidden:
        path = REPO / p
        assert not path.exists(), f"Unexpected new subagent created by R3.5: {p}"


def test_fix_loop_ref_documents_existing_subagent():
    """fix-loop.md must explicitly state that auto-fix subagent is preserved."""
    fix_loop = (REPO / "commands/vg/_shared/roam/fix-loop.md").read_text()
    assert "preserved" in fix_loop.lower(), (
        "fix-loop.md must document that the existing auto-fix subagent is preserved as-is"
    )
    assert "no new subagents" in fix_loop.lower() or "0 new subagents" in fix_loop.lower() or "no new subagent" in fix_loop.lower(), (
        "fix-loop.md should document the no-new-subagents constraint"
    )
