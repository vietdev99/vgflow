"""v2.66.0 Task 6 (#156) — Scope Check E upstream amendment enforcement.

Tests verify a new Check E in completeness-validation.md that scans owner
phase artifacts for prereq symbols and BLOCKs (no lenient exemption) when
missing, with a remedy pointing to /vg:amend or patch phase insertion.
"""
import re
from pathlib import Path


def test_scope_step5_mentions_upstream_amendment():
    body = Path("commands/vg/scope.md").read_text(encoding="utf-8")
    # Step 5 must reference upstream amendment requirement
    assert re.search(
        r"upstream\s+amendment|owner\s+phase.*amendment|prerequisite.*owner|Check\s+E",
        body,
        re.IGNORECASE,
    ), "scope.md Step 5 must enforce upstream amendment for cross-phase prereqs"


def test_completeness_check_e_exists():
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Must add new Check E (or named "Upstream Prereq Verification")
    assert re.search(
        r"Check\s+E|Upstream\s+Prereq\s+Verification",
        body,
        re.IGNORECASE,
    ), "completeness-validation.md must add Check E for upstream prereq verification"


def test_check_e_blocks_when_owner_missing():
    """Check E must BLOCK when prereq table references owner phase that hasn't scoped the field/endpoint."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # The check logic must call grep/scan on owner phase SPECS.md or PLAN.md
    assert re.search(
        r"owner.*SPECS\.md|owner.*PLAN\.md|grep.*owner|owner_specs|owner_plan",
        body,
        re.IGNORECASE | re.DOTALL,
    ), "Check E must scan owner phase artifacts for prereq fields/endpoints"


def test_check_e_demands_amendment_when_missing():
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Failure path must mention /vg:amend or insertion of patch phase
    assert re.search(
        r"/vg:amend|patch\s+phase|amend.*owner",
        body,
        re.IGNORECASE,
    ), "Check E failure must point to /vg:amend or patch phase remedy"


def test_codex_scope_skill_mirrors_enforcement():
    body = Path("codex-skills/vg-scope/SKILL.md").read_text(encoding="utf-8")
    # Codex skill must mention same enforcement (or reference completeness-validation.md)
    assert (
        "upstream" in body.lower()
        or "Check E" in body
        or "amend" in body.lower()
    ), "codex-skills/vg-scope/SKILL.md must mirror Check E enforcement note"
