"""v2.66.1 B3 — Planner enforces TDD structure per task."""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).parent.parent


def test_planner_template_mentions_tdd():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-blueprint-planner" / "SKILL.md").read_text(encoding="utf-8")
    assert "TDD" in body or "test-driven" in body.lower(), \
        "planner must reference TDD pattern (v2.66.1 B3)"


def test_planner_requires_5_step_structure():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-blueprint-planner" / "SKILL.md").read_text(encoding="utf-8")
    # Must mention all 5 steps OR reference template that does
    required_phrases = [
        "failing test", "confirm FAIL", "minimal", "confirm PASS", "commit"
    ]
    missing = [p for p in required_phrases if p.lower() not in body.lower()]
    assert not missing, f"planner missing TDD step phrases: {missing}"


def test_planner_test_first_assertion():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-blueprint-planner" / "SKILL.md").read_text(encoding="utf-8")
    # Must explicitly say tests come BEFORE implementation
    assert re.search(
        r"test.{0,40}(?:before|first|prior).{0,40}impl|write.{0,40}test.{0,40}first",
        body, re.IGNORECASE
    ), "planner must enforce test-first ordering"
