"""R4 Accept Pilot — CRITICAL: Step 5 interactive UAT MUST stay inline.

Spec §1.2 (docs/superpowers/specs/2026-05-03-vg-accept-design.md):
AskUserQuestion is a UI-presentation tool; subagent context handoff
breaks UX continuity. The 213-line interactive_uat step refactors via
slim ref + imperative language, NOT via subagent extraction.

This test prevents future "optimization" that would extract step 5 into
a subagent — the empirical 96.5% inline-skip rate makes subagent
extraction tempting, but UX cost is prohibitive for AskUserQuestion.
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
INTERACTIVE_REF = REPO / "commands/vg/_shared/accept/uat/interactive.md"
ACCEPT = REPO / "commands/vg/accept.md"
AGENTS = REPO / "agents"

AGENT_SPAWN_PATTERN = re.compile(r"Agent\s*\(\s*subagent_type", re.IGNORECASE)


def test_step5_interactive_no_subagent_call():
    """interactive.md MUST NOT contain Agent(subagent_type=...) call."""
    text = INTERACTIVE_REF.read_text()
    assert not AGENT_SPAWN_PATTERN.search(text), (
        "interactive.md contains Agent(subagent_type=...) call — "
        "Step 5 MUST stay inline (spec §1.2). UX requirement: "
        "AskUserQuestion needs main-agent presence; subagent context "
        "handoff breaks UX continuity."
    )


def test_interactive_ref_has_inline_hard_gate():
    """interactive.md MUST explicitly forbid subagent extraction."""
    text = INTERACTIVE_REF.read_text()
    inline_signals = [
        "STAYS INLINE",
        "MUST execute INLINE",
        "DO NOT spawn a subagent",
        "INLINE in the main agent",
    ]
    matched = [s for s in inline_signals if s in text]
    assert matched, (
        "interactive.md HARD-GATE must explicitly forbid subagent extraction. "
        "Expected one of: " + ", ".join(repr(s) for s in inline_signals)
    )


def test_slim_entry_step5_does_not_spawn():
    """Slim accept.md STEP 5 description MUST NOT mention Agent() spawn."""
    text = ACCEPT.read_text()
    m = re.search(r"### STEP 5.*?### STEP 6", text, re.DOTALL)
    assert m, "slim accept.md missing STEP 5 section"
    step5 = m.group(0)
    assert not AGENT_SPAWN_PATTERN.search(step5), (
        "Slim entry STEP 5 contains Agent(subagent_type=...) — "
        "interactive UX requires inline (spec §1.2)"
    )
    # Positive assertion: STEP 5 must explicitly say INLINE / NOT subagent
    assert "INLINE" in step5 or "NOT subagent" in step5 or "NOT a subagent" in step5, (
        "Slim entry STEP 5 must explicitly say INLINE or NOT subagent"
    )


def test_no_uat_interactive_subagent_skill():
    """No agents/vg-accept-uat-interactive/SKILL.md should exist."""
    forbidden = [
        AGENTS / "vg-accept-uat-interactive" / "SKILL.md",
        AGENTS / "vg-accept-interactive" / "SKILL.md",
        AGENTS / "vg-accept-ask" / "SKILL.md",
        AGENTS / "vg-accept-uat-interactive.md",
        AGENTS / "vg-accept-interactive.md",
    ]
    for p in forbidden:
        assert not p.exists(), (
            f"forbidden interactive subagent file exists: {p}\n"
            f"Step 5 (5_interactive_uat) MUST stay inline — UX requirement (spec §1.2)"
        )


def test_step5_marker_in_runtime_contract():
    """5_interactive_uat marker MUST be in must_touch_markers (still gated)."""
    text = ACCEPT.read_text()
    assert "5_interactive_uat" in text, (
        "5_interactive_uat marker missing from runtime_contract — "
        "step gate must still be enforced even though step is inline"
    )


def test_uat_responses_json_in_must_write():
    """`.uat-responses.json` MUST be in must_write contract (anti-theatre)."""
    text = ACCEPT.read_text()
    assert ".uat-responses.json" in text, (
        ".uat-responses.json missing from must_write — "
        "anti-theatre per-section persistence required (Batch 3 B4)"
    )
