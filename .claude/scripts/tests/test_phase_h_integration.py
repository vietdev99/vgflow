"""
Phase H v2.5 (2026-04-23) — Learn Auto-Surface integration tests.

Validates skill file wiring for tiered candidate surface:
  - accept.md step 6c_learn_auto_surface exists and calls scripts
  - learn.md has --auto-surface mode + tier documentation
  - vg-reflector/SKILL.md candidate schema has impact/first_seen/reject_count fields
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT      = Path(__file__).resolve().parents[3]
ACCEPT_MD      = REPO_ROOT / ".claude" / "commands" / "vg" / "accept.md"
LEARN_MD       = REPO_ROOT / ".claude" / "commands" / "vg" / "learn.md"
REFLECTOR_SKILL = REPO_ROOT / ".claude" / "skills" / "vg-reflector" / "SKILL.md"


@pytest.fixture(scope="module")
def accept_text() -> str:
    return ACCEPT_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def learn_text() -> str:
    return LEARN_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def reflector_text() -> str:
    return REFLECTOR_SKILL.read_text(encoding="utf-8")


# ─── accept.md 6c_learn_auto_surface ──────────────────────────────────

class TestAccept6cLearnAutoSurface:
    def test_step_exists(self, accept_text):
        assert '<step name="6c_learn_auto_surface">' in accept_text

    def test_positioned_before_write_uat(self):
        text = ACCEPT_MD.read_text(encoding="utf-8")
        pos_6c = text.find('name="6c_learn_auto_surface"')
        pos_uat = text.find('name="6_write_uat_md"')
        assert pos_6c != -1 and pos_uat != -1
        assert pos_6c < pos_uat, "6c must come before 6_write_uat_md"

    def test_invokes_learn_dedupe(self, accept_text):
        assert "learn-dedupe.py" in accept_text

    def test_invokes_learn_tier_classify(self, accept_text):
        assert "learn-tier-classify.py" in accept_text

    def test_reads_auto_surface_config(self, accept_text):
        """Config gate must read bootstrap.auto_surface_at_accept."""
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "auto_surface_at_accept" in step_body

    def test_tier_a_auto_promote_logic(self, accept_text):
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "Tier A" in step_body
        assert "Auto-promoted" in step_body or "auto_promote" in step_body.lower()

    def test_tier_b_cap_enforced(self, accept_text):
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "tier_b_max_per_phase" in step_body

    def test_tier_c_silent_mention(self, accept_text):
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "Tier C" in step_body
        assert "silent" in step_body.lower() or "--review --all" in step_body

    def test_telemetry_events_emitted(self, accept_text):
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "bootstrap.candidate_surfaced" in step_body or \
               "bootstrap.rule_promoted" in step_body

    def test_step_marker_written(self, accept_text):
        m = re.search(r'<step name="6c_learn_auto_surface">(.*?)</step>', accept_text, re.DOTALL)
        step_body = m.group(1) if m else ""
        assert "6c_learn_auto_surface.done" in step_body


# ─── learn.md --auto-surface mode ──────────────────────────────────────

class TestLearnAutoSurface:
    def test_auto_surface_section(self, learn_text):
        assert "--auto-surface" in learn_text

    def test_tier_a_auto_promote_mentioned(self, learn_text):
        assert "Tier A" in learn_text
        assert re.search(r"auto-promote|auto_promote", learn_text, re.IGNORECASE)

    def test_tier_b_max_per_phase(self, learn_text):
        assert "Tier B" in learn_text
        assert "tier_b_max_per_phase" in learn_text or "max 2" in learn_text.lower()

    def test_tier_c_silent(self, learn_text):
        assert "Tier C" in learn_text
        assert "silent" in learn_text.lower() or "parking" in learn_text.lower()

    def test_retirement_mentioned(self, learn_text):
        """Candidate rejected ≥ 2 times → retired forever."""
        assert "RETIRED" in learn_text or "retire" in learn_text.lower()

    def test_dedupe_threshold_mentioned(self, learn_text):
        assert "similarity" in learn_text.lower() or "0.8" in learn_text

    def test_argument_hint_updated(self, learn_text):
        """argument-hint frontmatter must include --auto-surface."""
        head = learn_text[:500]
        assert "--auto-surface" in head


# ─── vg-reflector/SKILL.md candidate schema ────────────────────────────

class TestReflectorSchema:
    def test_impact_field_documented(self, reflector_text):
        assert "impact:" in reflector_text

    def test_impact_enum_values(self, reflector_text):
        """impact must be critical|important|nice."""
        schema_section = reflector_text[reflector_text.find("impact:"):]
        assert "critical" in schema_section[:2000]
        assert "important" in schema_section[:2000]
        assert "nice" in schema_section[:2000]

    def test_first_seen_field(self, reflector_text):
        assert "first_seen:" in reflector_text

    def test_reject_count_field(self, reflector_text):
        assert "reject_count:" in reflector_text

    def test_tier_computed_downstream(self, reflector_text):
        """Reflector NOT set tier directly — downstream classifier computes."""
        assert "learn-tier-classify" in reflector_text or \
               "NOT set by reflector" in reflector_text or \
               "computed downstream" in reflector_text

    def test_impact_guidance_present(self, reflector_text):
        """Must document when to use each impact level."""
        assert "critical" in reflector_text.lower()
        # At least one of these guidance words:
        assert any(word in reflector_text.lower() for word in (
            "auth", "security", "auto-promote", "data integrity"
        ))
