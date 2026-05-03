"""debug.md MUST keep all 7 rules in <rules> block, especially rule 2 (no max iterations)."""
import re


REQUIRED_RULE_FRAGMENTS = [
    "Standalone session",
    "AskUserQuestion-driven loop",   # Rule 2 — CRITICAL
    "no max iterations",              # Rule 2 enforcement
    "Auto-classify",
    "Spec gap",
    "Browser MCP fallback",
    "Atomic commits",
    "No destructive actions",
]


def test_debug_rules_block_present(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    assert "<rules>" in body and "</rules>" in body, "rules block missing"


def test_debug_all_rule_fragments_present(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    assert rules_match
    rules_text = rules_match.group(1)
    missing = [f for f in REQUIRED_RULE_FRAGMENTS if f not in rules_text]
    assert not missing, f"<rules> block missing fragments: {missing}"


def test_debug_rule_2_no_cap_explicit(skill_loader):
    """Rule 2 wording must contain 'no max iterations' or equivalent."""
    skill = skill_loader("debug")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    rules_text = rules_match.group(1)
    assert "no max iterations" in rules_text or "no max" in rules_text.lower(), (
        "Rule 2 wording weakened — must keep 'no max iterations' phrasing"
    )
