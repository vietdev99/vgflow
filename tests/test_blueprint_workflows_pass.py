"""Task 40 — verify vg-blueprint-workflows Pass 3 subagent contract."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_MD = REPO / "agents/vg-blueprint-workflows/SKILL.md"
DELEGATION_MD = REPO / "commands/vg/_shared/blueprint/workflows-delegation.md"
OVERVIEW_MD = REPO / "commands/vg/_shared/blueprint/workflows-overview.md"
BP_MD = REPO / "commands/vg/blueprint.md"

REQUIRED_SCHEMA_KEYS = (
    "workflow_id", "name", "goal_links", "actors", "steps", "state_machine"
)


def test_skill_md_exists_with_proper_frontmatter() -> None:
    assert SKILL_MD.exists(), f"missing: {SKILL_MD}"
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert re.search(r"^name:\s*vg-blueprint-workflows$", text, re.MULTILINE)


def test_skill_md_declares_schema_keys() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for k in REQUIRED_SCHEMA_KEYS:
        assert k in text, f"SKILL.md missing schema doc: {k}"
    assert "cred_switch_marker" in text
    assert "rcrurd_invariant_ref" in text


def test_delegation_md_cites_pass2_inputs() -> None:
    assert DELEGATION_MD.exists(), f"missing: {DELEGATION_MD}"
    text = DELEGATION_MD.read_text(encoding="utf-8")
    for ref in ("API-CONTRACTS", "UI-MAP", "VIEW-COMPONENTS", "BLOCK 5"):
        assert ref in text, f"delegation must cite {ref}"


def test_overview_md_documents_pass_3_position() -> None:
    assert OVERVIEW_MD.exists()
    text = OVERVIEW_MD.read_text(encoding="utf-8")
    assert "Pass 3" in text
    assert "2b6d_fe_contracts" in text or "2b9_workflows" in text


def test_blueprint_md_declares_2b9_workflows_step() -> None:
    text = BP_MD.read_text(encoding="utf-8")
    assert '"2b9_workflows"' in text or "2b9_workflows" in text, \
        "blueprint.md must list 2b9_workflows in steps"
    assert "blueprint.workflows_pass_completed" in text, \
        "blueprint.md must declare workflows_pass_completed telemetry event"
