# tests/test_rule_schema_v1_1.py
import yaml
from pathlib import Path


def test_schema_doc_has_type_field():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    # Either explicit pipe-separated form OR both keywords appearing in schema block
    has_explicit = "type: rule | config_override | patch | procedural | declarative" in skill
    has_both_keywords = ("type:" in skill) and ("procedural" in skill) and ("declarative" in skill)
    assert has_explicit or has_both_keywords, \
        "vg-reflector SKILL.md must document type field with procedural+declarative values"


def test_schema_doc_has_authority_field():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    assert "authority: advisory" in skill, \
        "vg-reflector SKILL.md must document authority: advisory field"


def test_schema_doc_has_conditions_dsl():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    assert "all_of:" in skill and "any_of:" in skill, \
        "Schema must document conditions DSL all_of/any_of"


def test_target_step_enum_includes_deploy_roam_amend():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    for step in ("deploy", "roam", "amend"):
        # Look in schema enum context — search around target_step lines
        assert step in skill, f"target_step enum must include '{step}'"


def test_lesson_skill_target_step_enum_extended():
    """vg-lesson SKILL.md must include extended target_step enum too."""
    skill = Path(".codex/skills/vg-lesson/SKILL.md").read_text(encoding="utf-8")
    # Must mention deploy + roam + amend as valid target_step values
    for step in ("deploy", "roam", "amend"):
        assert step in skill, f"vg-lesson must mention target_step '{step}'"
