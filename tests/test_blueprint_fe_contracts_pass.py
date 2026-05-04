"""Task 38 — verify Pass 2 vg-blueprint-fe-contracts subagent contract.

Pin: agent SKILL.md must declare 16-field BLOCK 5 schema. Delegation
prompt must include UI-MAP + VIEW-COMPONENTS + BE 4-block citations as
input refs. Output must be JSON listing per-endpoint BLOCK 5 bodies.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_MD = REPO / "agents/vg-blueprint-fe-contracts/SKILL.md"
DELEGATION_MD = REPO / "commands/vg/_shared/blueprint/fe-contracts-delegation.md"
OVERVIEW_MD = REPO / "commands/vg/_shared/blueprint/fe-contracts-overview.md"

REQUIRED_FIELDS = (
    "url", "consumers", "ui_states", "query_param_schema", "invalidates",
    "optimistic", "toast_text", "navigation_post_action", "auth_role_visibility",
    "error_to_action_map", "pagination_contract", "debounce_ms",
    "prefetch_triggers", "websocket_correlate", "request_id_propagation",
    "form_submission_idempotency_key",
)


def test_skill_md_exists_with_proper_frontmatter() -> None:
    assert SKILL_MD.exists(), f"missing: {SKILL_MD}"
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with frontmatter"
    assert re.search(r"^name:\s*vg-blueprint-fe-contracts$", text, re.MULTILINE)
    assert re.search(r"^description:\s*.+", text, re.MULTILINE)


def test_skill_md_declares_all_16_block5_fields() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for field in REQUIRED_FIELDS:
        assert field in text, f"SKILL.md missing field doc: {field}"


def test_delegation_md_cites_inputs() -> None:
    assert DELEGATION_MD.exists(), f"missing: {DELEGATION_MD}"
    text = DELEGATION_MD.read_text(encoding="utf-8")
    # Must reference all 3 input artifacts
    for ref in ("UI-MAP", "VIEW-COMPONENTS", "API-CONTRACTS"):
        assert ref in text, f"delegation prompt must cite {ref}"


def test_delegation_md_declares_output_json_shape() -> None:
    text = DELEGATION_MD.read_text(encoding="utf-8")
    # Must declare a JSON return shape with `endpoints` array containing slug+body
    assert "endpoints" in text and "slug" in text and "block5_body" in text, \
        "delegation must declare return JSON shape: { endpoints: [{ slug, block5_body }] }"


def test_overview_md_documents_pass_2_position() -> None:
    assert OVERVIEW_MD.exists(), f"missing: {OVERVIEW_MD}"
    text = OVERVIEW_MD.read_text(encoding="utf-8")
    assert "Pass 2" in text
    assert "2b5e_a_lens_walk" in text and "2b7_flow_detect" in text, \
        "overview must position Pass 2 between lens-walk and flow_detect"
