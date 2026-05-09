"""v2.66.1 B2 — executor allows questions + self-reviews diff."""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).parent.parent


def test_executor_allows_questions_when_capsule_ambiguous():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-build-task-executor" / "SKILL.md").read_text(encoding="utf-8")
    # Must NOT have absolute "MUST NOT ask questions" anymore
    bad = re.search(r"MUST NOT ask user questions", body)
    assert not bad, "executor must allow questions when capsule ambiguous (v2.66.1 B2)"
    # Must have explicit "MAY ask" or "if ambiguous, ask" clause
    assert re.search(
        r"(?:MAY|may|allowed to)\s+ask\s+(?:user\s+)?questions|ambiguous.*ask",
        body, re.IGNORECASE
    ), "executor must explicitly permit questions when capsule ambiguous"


def test_executor_has_self_review_step():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-build-task-executor" / "SKILL.md").read_text(encoding="utf-8")
    # Must mention self-review of diff before commit
    assert re.search(r"self.?review", body, re.IGNORECASE), \
        "executor must include self-review step (v2.66.1 B2)"
    # Must specify when (before commit)
    assert re.search(
        r"(?:before commit|before staging|after impl).*self.?review|self.?review.*before commit",
        body, re.IGNORECASE | re.DOTALL
    ), "self-review must be explicitly before commit"


def test_self_review_checklist_present():
    body = (REPO_ROOT / ".claude" / "agents" / "vg-build-task-executor" / "SKILL.md").read_text(encoding="utf-8")
    # Self-review section should have concrete checklist items
    # (e.g., scope creep, missing tests, mirror byte-identity)
    assert re.search(r"(?:scope\s*creep|test.*present|mirror.*byte)", body, re.IGNORECASE), \
        "self-review must have concrete checklist items"
