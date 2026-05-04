"""amend.md MUST keep all 7 rules in <rules> block, especially rule 6 (informational only)."""
import re


REQUIRED_RULE_FRAGMENTS = [
    "VG-native",
    "Config-driven",
    "AMENDMENT-LOG is append-only",
    "CONTEXT.md patch, not regenerate",
    "Git tag before modify",
    "Impact is informational",       # Rule 6 — CRITICAL: subagent must not auto-modify
    "no GSD delegation",             # part of rule 1
]


def test_amend_rules_block_present(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    assert "<rules>" in body and "</rules>" in body, "rules block missing"


def test_amend_all_rule_fragments_present(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    assert rules_match
    rules_text = rules_match.group(1)
    missing = [f for f in REQUIRED_RULE_FRAGMENTS if f not in rules_text]
    assert not missing, f"<rules> block missing fragments: {missing}"


def test_amend_rule_6_informational_explicit(skill_loader):
    """Rule 6 enforces NO auto-modify; subagent must respect."""
    skill = skill_loader("amend")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    rules_text = rules_match.group(1)
    assert "informational" in rules_text and ("NOT auto-modify" in rules_text or "does NOT" in rules_text), (
        "Rule 6 wording weakened — must keep 'informational' + 'NOT auto-modify' or 'does NOT' phrasing"
    )
