"""v2.68.0 C2 — QA-Checker meta-agent."""
from pathlib import Path
import re


def test_qa_checker_agent_exists():
    p = Path(".claude/agents/vg-review-qa-checker/SKILL.md")
    assert p.exists(), "vg-review-qa-checker agent definition missing (v2.68.0 C2)"
    body = p.read_text(encoding="utf-8")
    # Must reference issue traceability (not just spec/code match)
    assert re.search(r"issue.{0,80}(?:claim|trace|address|original)", body, re.IGNORECASE | re.DOTALL), \
        "QA-Checker must verify fix addresses original issue claim"
    # Must mention fix commit + finding linkage
    assert "commit" in body.lower() and "finding" in body.lower()


def test_review_phase3d_spawns_qa_checker():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Phase 3d region must reference QA-Checker spawn
    assert "vg-review-qa-checker" in body, \
        "review.md Phase 3d must spawn QA-Checker after fix agents return (v2.68.0 C2)"


def test_qa_checker_returns_pass_partial_fail():
    p = Path(".claude/agents/vg-review-qa-checker/SKILL.md")
    body = p.read_text(encoding="utf-8")
    for v in ["PASS", "PARTIAL", "FAIL"]:
        assert v in body, f"QA-Checker must define {v} verdict"
