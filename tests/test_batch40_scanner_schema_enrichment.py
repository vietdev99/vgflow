"""tests/test_batch40_scanner_schema_enrichment.py — Batch 40.

Haiku scanner schema enrichment. Current schema (skills/vg-haiku-scanner/
SKILL.md:359-410) emits results/forms/modals/tabs/menus/tables but
missing filters/sort_headers/pagination/search. Read-only views with
filter+sort+paginate UI emit sparse scan data → enrich-test-goals.py
can't auto-emit filter stubs (Batch 28 F13 dead) → sparse specs.

Fix: extend schema with 4 new emit fields + classification rules.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "vg-haiku-scanner" / "SKILL.md"
SKILL_MIRROR = REPO / ".claude" / "skills" / "vg-haiku-scanner" / "SKILL.md"
ENRICH = REPO / "scripts" / "enrich-test-goals.py"


def test_schema_declares_filters_field():
    """SKILL.md output schema must declare filters[] field with name/kind."""
    body = SKILL.read_text(encoding="utf-8")
    # Find schema JSON block
    schema_idx = body.find('"view": "{VIEW_URL}"')
    assert schema_idx > 0
    schema_block = body[schema_idx:schema_idx + 4000]
    assert '"filters"' in schema_block, (
        "Batch 40: scanner schema must include filters[] field"
    )
    # Need at least one example showing structure with name + kind
    assert '"name":' in schema_block and ('"kind":' in schema_block or '"type":' in schema_block)


def test_schema_declares_sort_headers_field():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    schema_block = body[schema_idx:schema_idx + 4000]
    assert '"sort_headers"' in schema_block, (
        "Batch 40: scanner schema must include sort_headers[] field"
    )


def test_schema_declares_pagination_field():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    schema_block = body[schema_idx:schema_idx + 4000]
    assert '"pagination"' in schema_block, (
        "Batch 40: scanner schema must include pagination field"
    )


def test_schema_declares_search_field():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    schema_block = body[schema_idx:schema_idx + 4000]
    assert '"search"' in schema_block, (
        "Batch 40: scanner schema must include search[] field"
    )


def test_workflow_classifies_filter_widgets():
    """SKILL workflow must instruct: classify combobox/select/text-input
    near tables as filter widgets."""
    body = SKILL.read_text(encoding="utf-8")
    # Some marker mentioning filter classification rule
    assert "Batch 40" in body or "filter widget" in body.lower() or "classify.*filter" in body.lower(), (
        "Batch 40: SKILL must have classification rule for filter widgets"
    )


def test_mirror_in_sync():
    assert SKILL.read_text(encoding="utf-8") == SKILL_MIRROR.read_text(encoding="utf-8")


def test_enrich_consumes_scan_filters():
    """enrich-test-goals.py classify_elements iterates scan.filters[]
    (Batch 28 F13 + Batch 40 dependency)."""
    body = ENRICH.read_text(encoding="utf-8")
    # Batch 36 already added the loop; verify it's still there
    assert 'scan.get("filters")' in body or 'scan.filters' in body, (
        "Batch 40: enrich-test-goals.py must consume scan.filters[]"
    )
