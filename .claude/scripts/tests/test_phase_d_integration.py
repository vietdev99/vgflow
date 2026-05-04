"""
Phase D v2.5 (2026-04-23) — integration tests for skill file wiring.

Validates that project.md + blueprint.md carry the correct Phase D
integration points:
  - project.md Round 7 (Architecture Lock) exists and emits FOUNDATION §9
  - project.md Round 8 (Security Testing Strategy) exists and writes SECURITY-TEST-PLAN.md.staged
  - project.md Round 9 atomic write promotes 4 files (not 3)
  - blueprint.md step 2a planner prompt has <architecture_context> + <security_test_plan>
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT     = Path(__file__).resolve().parents[3]
PROJECT_MD    = REPO_ROOT / ".claude" / "commands" / "vg" / "project.md"
BLUEPRINT_MD  = REPO_ROOT / ".claude" / "commands" / "vg" / "blueprint.md"
STP_TEMPLATE  = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates" / "SECURITY-TEST-PLAN-template.md"


@pytest.fixture(scope="module")
def project_text() -> str:
    return PROJECT_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def blueprint_text() -> str:
    return BLUEPRINT_MD.read_text(encoding="utf-8")


# ─── project.md Round 7: Architecture Lock ──────────────────────────────

class TestProjectRound7ArchitectureLock:
    def test_round_7_header_present(self, project_text):
        assert "### Round 7: Architecture Lock" in project_text

    def test_all_8_subsections_referenced(self, project_text):
        """Round 7 must mention all 8 §9.x subsections."""
        for i in range(1, 9):
            assert f"9.{i}" in project_text, f"§9.{i} not referenced in Round 7"

    def test_tech_stack_prompt(self, project_text):
        assert "9.1 Tech stack" in project_text

    def test_module_boundary_prompt(self, project_text):
        assert "9.2 Module boundary" in project_text

    def test_security_baseline_items(self, project_text):
        """§9.5 must enumerate key security items (TLS/cookie/CORS/etc.)."""
        assert "9.5 Security baseline" in project_text
        for item in ("Cookie flag", "CORS", "TLS", "OAuth", "Compliance flags"):
            assert item in project_text, f"§9.5 missing {item}"

    def test_perf_baseline_p95(self, project_text):
        assert "9.6 Performance baseline" in project_text
        assert "p95" in project_text

    def test_code_style_model_portable(self, project_text):
        assert "9.8 Model-portable code style" in project_text

    def test_appends_to_foundation_content(self, project_text):
        """Round 7 must append §9 block to draft.foundation_md_content."""
        assert "foundation_md_content" in project_text
        assert "foundation_section_9" in project_text or "## 9. Architecture Lock" in project_text


# ─── project.md Round 8: Security Testing Strategy ────────────────────

class TestProjectRound8SecurityTesting:
    def test_round_8_header_present(self, project_text):
        assert "### Round 8: Security Testing Strategy" in project_text

    def test_four_questions_present(self, project_text):
        """Round 8 must ask 4 questions: risk profile, DAST, pentest, compliance."""
        assert "Risk profile classification" in project_text
        assert "DAST tool choice" in project_text
        assert "Pen-test strategy" in project_text
        assert "Compliance framework" in project_text

    def test_risk_profile_enum_values(self, project_text):
        """Round 8 must offer critical/moderate/low options."""
        assert "critical" in project_text.lower()
        assert "moderate" in project_text.lower()
        assert re.search(r"\b[Ll]ow\b", project_text)

    def test_dast_tool_options(self, project_text):
        for tool in ("ZAP", "Nuclei"):
            assert tool in project_text

    def test_writes_stp_staged_file(self, project_text):
        """Round 8 must write SECURITY-TEST-PLAN.md.staged."""
        assert "SECURITY-TEST-PLAN" in project_text
        assert ".staged" in project_text or "staged" in project_text

    def test_references_stp_template(self, project_text):
        """Round 8 must reference the SECURITY-TEST-PLAN-template.md."""
        assert "SECURITY-TEST-PLAN-template.md" in project_text

    def test_config_side_effect_risk_profile(self, project_text):
        """Round 8 must note risk_profile update to vg.config.md."""
        assert "risk_profile" in project_text


# ─── project.md Round 9: Atomic Write ─────────────────────────────────

class TestProjectRound9AtomicWrite:
    def test_round_9_header_present(self, project_text):
        assert "### Round 9: Atomic write + commit" in project_text

    def test_promotes_stp_file(self, project_text):
        """Round 9 atomic write must promote SECURITY-TEST-PLAN.md.staged."""
        atomic_section = project_text[project_text.find("Round 9:"):]
        assert "STP_FILE" in atomic_section or "SECURITY-TEST-PLAN.md.staged" in atomic_section

    def test_git_add_stp(self, project_text):
        """git add must include STP file when present."""
        atomic_section = project_text[project_text.find("Round 9:"):]
        assert "git add" in atomic_section
        assert "STP_FILE" in atomic_section


# ─── blueprint.md Step 2a: Architecture context injection ─────────────

class TestBlueprintArchitectureInjection:
    def test_architecture_context_block_present(self, blueprint_text):
        assert "<architecture_context>" in blueprint_text

    def test_security_test_plan_block_present(self, blueprint_text):
        assert "<security_test_plan>" in blueprint_text

    def test_references_foundation_section9(self, blueprint_text):
        """Architecture context must reference FOUNDATION §9."""
        assert "FOUNDATION.md" in blueprint_text
        assert re.search(r"§9|section 9", blueprint_text, re.IGNORECASE)

    def test_references_stp_artifact(self, blueprint_text):
        assert "SECURITY-TEST-PLAN.md" in blueprint_text

    def test_architecture_context_inside_planner_prompt(self, blueprint_text):
        """<architecture_context> must appear inside the planner Agent prompt."""
        # Find planner Agent() section
        planner_section = blueprint_text[blueprint_text.find("model=\"${MODEL_PLANNER}"):]
        # Allow 10KB window
        assert "<architecture_context>" in planner_section[:10000], (
            "architecture_context must be in planner Agent() prompt"
        )


# ─── SECURITY-TEST-PLAN template exists + has 8 sections ──────────────

class TestStpTemplate:
    def test_template_exists(self):
        assert STP_TEMPLATE.exists(), f"Template missing: {STP_TEMPLATE}"

    def test_template_has_8_sections(self):
        text = STP_TEMPLATE.read_text(encoding="utf-8")
        for i in range(1, 9):
            # Match `## 1. Risk`, `## 2. DAST`, etc.
            assert re.search(rf"^## {i}\.", text, re.MULTILINE), (
                f"Template missing section ## {i}. ..."
            )

    def test_template_has_placeholders(self):
        text = STP_TEMPLATE.read_text(encoding="utf-8")
        assert "{PROJECT_NAME}" in text
        assert "{ISO_TIMESTAMP}" in text or "ISO_TIMESTAMP" in text
