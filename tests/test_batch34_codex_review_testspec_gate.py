"""tests/test_batch34_codex_review_testspec_gate.py — Batch 34.

Codex audit findings F1/F2/F8 (docs/plans/2026-05-15-codex-review-testspec-test-flow-audit.md):

F1 CRITICAL: test-spec doesn't enforce review artifacts (RUNTIME-MAP,
  GOAL-COVERAGE-MATRIX, scan-*.json) before generation.
F2 CRITICAL: GOAL-COVERAGE-MATRIX.json contract drift — review writes .md
  only, test-spec consumes .json that may not exist.
F8 CRITICAL: codegen status table only handles bare READY, not
  READY_STRUCTURAL/READY_BEHAVIORAL emitted by review.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
REVIEW_CLOSE = REPO / "commands" / "vg" / "_shared" / "review" / "close.md"
CODEGEN_DEL = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


def test_f1_test_spec_requires_runtime_map():
    """test-spec 1_build_artifact_gate must require RUNTIME-MAP.json
    (review output). Currently only build + TEST-GOALS checks."""
    body = TEST_SPEC.read_text(encoding="utf-8")
    gate_idx = body.find('<step name="1_build_artifact_gate">')
    assert gate_idx > 0
    gate_end = body.find("</step>", gate_idx)
    block = body[gate_idx:gate_end]
    assert "RUNTIME-MAP.json" in block, (
        "Batch 34 F1: test-spec 1_build_artifact_gate must require "
        "RUNTIME-MAP.json (from /vg:review) before generation."
    )
    assert "GOAL-COVERAGE-MATRIX" in block, (
        "Batch 34 F1: test-spec must require GOAL-COVERAGE-MATRIX from review"
    )


def test_f2_review_writes_canonical_json():
    """Review close.md must write GOAL-COVERAGE-MATRIX.json (canonical),
    not just .md. Test-spec consumes JSON downstream."""
    body = REVIEW_CLOSE.read_text(encoding="utf-8")
    assert "GOAL-COVERAGE-MATRIX.json" in body, (
        "Batch 34 F2: review close.md must write canonical "
        "GOAL-COVERAGE-MATRIX.json so test-spec downstream consumption "
        "doesn't fall back silently."
    )


def test_f8_codegen_handles_ready_variants():
    """Codegen delegation status table must handle READY_STRUCTURAL +
    READY_BEHAVIORAL (review emits these). Currently only bare READY."""
    body = CODEGEN_DEL.read_text(encoding="utf-8")
    # Find status table
    table_idx = body.find("For each goal in status_map, branch by status")
    assert table_idx > 0
    block = body[table_idx:table_idx + 2000]
    assert "READY_STRUCTURAL" in block or "READY_BEHAVIORAL" in block, (
        "Batch 34 F8: codegen status table must handle READY_STRUCTURAL "
        "and READY_BEHAVIORAL variants (review emits these in matrix). "
        "Currently only bare READY routed."
    )


def test_mirrors_in_sync():
    for src in [TEST_SPEC, REVIEW_CLOSE, CODEGEN_DEL]:
        mirror = REPO / ".claude" / src.relative_to(REPO)
        assert src.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8"), (
            f"Mirror drift: {mirror.relative_to(REPO)}"
        )
