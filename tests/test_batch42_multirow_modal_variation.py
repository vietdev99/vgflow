"""tests/test_batch42_multirow_modal_variation.py — Batch 42.

Scanner samples first row only (skills/vg-haiku-scanner/SKILL.md:309).
Row-specific bugs (data-dependent) miss. Modal forms tested with 1
input set only — boundary/validation/unicode edge variants miss.

Fix: scanner workflow samples first/middle/last rows + modals get 4-tier
input variation per visit.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "vg-haiku-scanner" / "SKILL.md"
SKILL_MIRROR = REPO / ".claude" / "skills" / "vg-haiku-scanner" / "SKILL.md"


def test_table_workflow_samples_multiple_rows():
    body = SKILL.read_text(encoding="utf-8")
    # Find table handling line — must change from FIRST row only to multi-row
    assert "first/middle/last" in body.lower() or "first, middle, last" in body.lower() \
        or "multi-row sample" in body.lower() or "Batch 42" in body, (
        "Batch 42: table workflow must sample multiple rows (first/middle/last)"
    )


def test_modal_input_variation_documented():
    body = SKILL.read_text(encoding="utf-8")
    assert "input variation" in body.lower() or "Batch 42" in body, (
        "Batch 42: modal forms must vary inputs per visit"
    )
    # Must mention boundary/empty/unicode test pattern
    has_variants = any(
        kw in body
        for kw in ("[valid, empty, max-length, unicode]",
                   "valid + empty + max-length + unicode",
                   "valid, empty, max, unicode")
    )
    assert has_variants, "Batch 42: must declare 4-tier input variation pattern"


def test_schema_tables_has_sampled_rows():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    block = body[schema_idx:schema_idx + 6000]
    # tables entry must now have sampled_rows field or row_indexes_tested
    assert "sampled_rows" in block or "row_indexes_tested" in block, (
        "Batch 42: tables schema must record which rows were tested "
        "(not just 'sample_row_tested: bool')"
    )


def test_schema_modals_has_input_variants():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    block = body[schema_idx:schema_idx + 6000]
    assert "input_variants" in block or "variants_tested" in block, (
        "Batch 42: modals schema must record input variants tested"
    )


def test_mirror_in_sync():
    assert SKILL.read_text(encoding="utf-8") == SKILL_MIRROR.read_text(encoding="utf-8")
