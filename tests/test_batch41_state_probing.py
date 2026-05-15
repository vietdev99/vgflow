"""tests/test_batch41_state_probing.py — Batch 41.

Scanner doesn't actively probe error/empty/loading states. Read-only
specs Batch 36 R2 have those stages but no evidence (selector,
screenshot) → spec body uses generic selectors → flaky tests.

Fix: scanner workflow + schema add state_observations capturing:
- empty_state: navigate to filter-no-match → DOM signature
- error_state_4xx: visit invalid id → 404 UI selector
- loading_state: throttle network → skeleton DOM during fetch
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "vg-haiku-scanner" / "SKILL.md"
SKILL_MIRROR = REPO / ".claude" / "skills" / "vg-haiku-scanner" / "SKILL.md"
ENRICH = REPO / "scripts" / "enrich-test-goals.py"


def test_schema_declares_state_observations():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    block = body[schema_idx:schema_idx + 6000]
    assert '"state_observations"' in block, (
        "Batch 41: scanner schema must declare state_observations object"
    )
    for key in ('"empty_state"', '"error_state_4xx"', '"loading_state"'):
        assert key in block, f"Batch 41: state_observations missing {key}"


def test_workflow_has_state_probing_section():
    body = SKILL.read_text(encoding="utf-8")
    assert "State Probing" in body or "state probing" in body.lower() or "Batch 41" in body, (
        "Batch 41: SKILL must have state probing workflow section"
    )


def test_state_observation_entry_has_selector_field():
    """Each state entry must include selector + evidence keys."""
    body = SKILL.read_text(encoding="utf-8")
    state_idx = body.find('"state_observations"')
    assert state_idx > 0
    block = body[state_idx:state_idx + 3000]
    assert '"selector"' in block, "state observations must declare selector field"
    assert '"observed"' in block, "must declare observed bool field"


def test_enrich_emits_state_stubs():
    """enrich-test-goals.py must iterate scan.state_observations and emit
    G-AUTO-{view}-empty-state / -error-state / -loading-state stubs."""
    body = ENRICH.read_text(encoding="utf-8")
    assert "state_observations" in body, (
        "Batch 41: enrich must consume scan.state_observations"
    )
    assert "empty-state" in body or "empty_state" in body
    assert "error-state" in body or "error_state" in body


def test_mirror_in_sync():
    assert SKILL.read_text(encoding="utf-8") == SKILL_MIRROR.read_text(encoding="utf-8")
