"""v2.66.1 B4 — In-build final reviewer agent."""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).parent.parent


def test_final_reviewer_agent_exists():
    p = REPO_ROOT / ".claude" / "agents" / "vg-build-final-reviewer" / "SKILL.md"
    assert p.exists(), "vg-build-final-reviewer agent definition missing (v2.66.1 B4)"
    body = p.read_text(encoding="utf-8")
    # Must reference cumulative review (not per-task — that's B1's lane)
    assert re.search(
        r"(?:cumulative|entire|full|all)\s+(?:delta|tasks|phase|implementation)",
        body, re.IGNORECASE
    ), "final reviewer must explicitly target cumulative delta"


def test_final_reviewer_reads_plan_md():
    p = REPO_ROOT / ".claude" / "agents" / "vg-build-final-reviewer" / "SKILL.md"
    body = p.read_text(encoding="utf-8")
    assert "PLAN.md" in body, "final reviewer must read PLAN.md as source of truth"


def test_close_md_spawns_final_reviewer():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "close.md").read_text(encoding="utf-8")
    assert "vg-build-final-reviewer" in body, \
        "close.md must spawn final reviewer (v2.66.1 B4)"


def test_final_reviewer_returns_three_verdicts():
    p = REPO_ROOT / ".claude" / "agents" / "vg-build-final-reviewer" / "SKILL.md"
    body = p.read_text(encoding="utf-8")
    # Must define PASS / PARTIAL / FAIL verdict semantics
    for v in ["PASS", "PARTIAL", "FAIL"]:
        assert v in body, f"final reviewer must define {v} verdict"
