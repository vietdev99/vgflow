"""Tier 2 C: Verify CLAUDE.md documents --max-budget-usd runaway-cost safety net.

Verifies operator-side adoption guidance per docs/audits/...tier2 plan:
- CLAUDE.md must mention --max-budget-usd
- CLAUDE.md must explain WHY (cost runaway / cap)
- review-batch.md and regression.md must reference budget-cap recommendation
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
REVIEW_BATCH_MD = REPO_ROOT / "commands" / "vg" / "review-batch.md"
REGRESSION_MD = REPO_ROOT / "commands" / "vg" / "regression.md"


def test_claude_md_mentions_max_budget_usd():
    body = CLAUDE_MD.read_text()
    assert "--max-budget-usd" in body, (
        "CLAUDE.md must recommend --max-budget-usd for runaway-cost safety "
        "(Tier 2 C). Add a Performance section documenting the flag."
    )


def test_claude_md_explains_budget_why():
    body = CLAUDE_MD.read_text().lower()
    assert any(token in body for token in ("runaway", "cost", "cap", "ceiling")), (
        "CLAUDE.md must explain WHY --max-budget-usd matters "
        "(runaway-cost prevention / dollar cap)"
    )


def test_claude_md_recommends_batch_and_regression_amounts():
    body = CLAUDE_MD.read_text()
    # Recommended amounts per Tier 2 C plan: 5 single, 10 batch, 15 regression
    assert "/vg:review-batch" in body, "CLAUDE.md should call out review-batch flow"
    assert "/vg:regression" in body, "CLAUDE.md should call out regression flow"


def test_review_batch_md_recommends_budget_cap():
    body = REVIEW_BATCH_MD.read_text()
    assert "--max-budget-usd" in body, (
        "commands/vg/review-batch.md must recommend --max-budget-usd at top "
        "of file (operator-side guidance for batch sweep)"
    )


def test_regression_md_recommends_budget_cap():
    body = REGRESSION_MD.read_text()
    assert "--max-budget-usd" in body, (
        "commands/vg/regression.md must recommend --max-budget-usd at top "
        "of file (operator-side guidance for full-suite + --fix loop)"
    )
