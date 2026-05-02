"""R4 Accept Pilot — 2 subagents valid + assert NO uat-interactive subagent.

Spec §1.2: Step 5 interactive UAT MUST stay inline. Subagent extraction
of AskUserQuestion breaks UX continuity. This test prevents future
'optimization' that would create vg-accept-uat-interactive.
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / "agents"

EXPECTED_SUBAGENTS = [
    ("vg-accept-uat-builder", ["Read", "Write", "Bash", "Grep"]),
    ("vg-accept-cleanup",     ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]),
]

FORBIDDEN_INTERACTIVE_SUBAGENTS = [
    "vg-accept-uat-interactive",
    "vg-accept-interactive",
    "vg-accept-ask",
]


def test_uat_builder_subagent_valid():
    p = AGENTS / "vg-accept-uat-builder" / "SKILL.md"
    assert p.exists(), f"missing subagent SKILL.md: {p}"
    body = p.read_text()
    # Frontmatter validation
    assert body.startswith("---"), "SKILL.md must start with YAML frontmatter"
    assert re.search(r"^name:\s*vg-accept-uat-builder\s*$", body, re.MULTILINE)
    assert re.search(r"^tools:\s*\[Read,\s*Write,\s*Bash,\s*Grep\]\s*$", body, re.MULTILINE)
    # Must NOT include Task or Agent in tools (no recursive spawn)
    tools_match = re.search(r"^tools:\s*\[([^\]]+)\]", body, re.MULTILINE)
    assert tools_match
    tools = [t.strip() for t in tools_match.group(1).split(",")]
    assert "Task" not in tools, "subagent must NOT have Task tool"
    assert "Agent" not in tools, "subagent must NOT have Agent tool (no recursive spawn)"
    # HARD-GATE present
    assert "<HARD-GATE>" in body
    # Must produce uat-checklist.md
    assert "uat-checklist.md" in body


def test_cleanup_subagent_valid():
    p = AGENTS / "vg-accept-cleanup" / "SKILL.md"
    assert p.exists(), f"missing subagent SKILL.md: {p}"
    body = p.read_text()
    assert body.startswith("---")
    assert re.search(r"^name:\s*vg-accept-cleanup\s*$", body, re.MULTILINE)
    # Allowed tools list must include Edit + Glob (cleanup needs them)
    tools_match = re.search(r"^tools:\s*\[([^\]]+)\]", body, re.MULTILINE)
    assert tools_match
    tools = [t.strip() for t in tools_match.group(1).split(",")]
    for required in ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]:
        assert required in tools, f"cleanup subagent missing tool: {required}"
    assert "Task" not in tools
    assert "Agent" not in tools
    assert "<HARD-GATE>" in body
    # Branches on UAT_VERDICT
    assert "UAT_VERDICT" in body


def test_no_uat_interactive_subagent():
    """Spec §1.2: Step 5 must stay inline (UX requirement)."""
    for name in FORBIDDEN_INTERACTIVE_SUBAGENTS:
        p_dir = AGENTS / name
        p_skill = p_dir / "SKILL.md"
        p_flat = AGENTS / f"{name}.md"
        assert not p_dir.exists(), (
            f"forbidden interactive subagent dir exists: {p_dir}\n"
            f"Step 5 (5_interactive_uat) MUST stay inline — UX requirement (spec §1.2)"
        )
        assert not p_skill.exists(), f"forbidden subagent SKILL.md: {p_skill}"
        assert not p_flat.exists(), f"forbidden subagent flat file: {p_flat}"


def test_exactly_two_accept_subagents():
    """Sanity: only 2 accept subagents exist, no more."""
    accept_subagents = []
    for child in AGENTS.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith("vg-accept-"):
            continue
        accept_subagents.append(child.name)
    expected = {name for name, _ in EXPECTED_SUBAGENTS}
    actual = set(accept_subagents)
    assert actual == expected, (
        f"accept subagent set mismatch: expected {expected}, got {actual}"
    )
