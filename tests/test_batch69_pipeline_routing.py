"""tests/test_batch69_pipeline_routing.py — B69 pipeline routing fixes.

User report: "pipeline vẫn bị gợi ý thiếu ở bước review -> test-specs -> test.
thiếu test-specs, rà lại toàn bộ VGFlow đi". Pipeline skips /vg:test-spec
recommendation between /vg:review and /vg:test.

3 parallel audits found 4 concrete bugs:

B1 — commands/vg/_shared/build/close.md never emitted next_command at all.
     After build, user had no machine-readable next-step pointer.
     Fix: emit next_command="/vg:review {phase}".

B2 — commands/vg/test-spec.md:841 incorrectly set next_command="/vg:review"
     (review already ran upstream — test-spec REQUIRES RUNTIME-MAP from
     review per Step 1 gate). Should set next_command="/vg:test".

B3 — commands/vg/_shared/review/close.md printed "Next: /vg:test-spec" in
     user-facing message but did NOT emit it as PIPELINE-STATE.next_command.
     /vg:next read empty next_command → fell back to /vg:test → skipped
     test-spec → review preflight blocked next run.

B4 — commands/vg/LIFECYCLE.md mermaid showed build → test-spec → review
     but actual code dependencies require build → review → test-spec → test.
     Also test-spec.md:62-64 objective stated "before /vg:review" which
     contradicts the Step 1 gate requiring RUNTIME-MAP from review.

Coverage:
  1. build/close.md emits next_command=/vg:review
  2. review/close.md emits next_command=/vg:test-spec
  3. test-spec.md emits next_command=/vg:test (NOT /vg:review)
  4. LIFECYCLE.md mermaid order: build → review → test-spec → test
  5. LIFECYCLE.md auto-chain table reflects fixed emissions
  6. test-spec.md objective aligned with canonical order
  7. test-spec.md no longer states "before /vg:review"
  8. Mirror parity x4
"""
from __future__ import annotations
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BUILD_CLOSE = REPO / "commands" / "vg" / "_shared" / "build" / "close.md"
BUILD_CLOSE_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "build" / "close.md"
REVIEW_CLOSE = REPO / "commands" / "vg" / "_shared" / "review" / "close.md"
REVIEW_CLOSE_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "close.md"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"
LIFECYCLE = REPO / "commands" / "vg" / "LIFECYCLE.md"
LIFECYCLE_MIRROR = REPO / ".claude" / "commands" / "vg" / "LIFECYCLE.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_b1_build_close_emits_next_command_review():
    """B1: build/close.md MUST emit next_command=/vg:review."""
    body = _read(BUILD_CLOSE)
    # PIPELINE-STATE write block must include next_command assignment
    assert "s['next_command'] = '/vg:review" in body, (
        "B69-B1: build/close.md must emit next_command=/vg:review after run-complete"
    )
    assert "B69 fix" in body


def test_b2_test_spec_next_command_is_test_not_review():
    """B2: test-spec next_command MUST be /vg:test, NOT /vg:review."""
    body = _read(TEST_SPEC)
    # The fixed assignment
    assert 'state["next_command"] = "/vg:test ' in body
    # Old broken assignment must be gone
    assert 'state["next_command"] = "/vg:review' not in body
    assert "B69 fix" in body


def test_b3_review_close_emits_next_command_test_spec():
    """B3: review/close.md MUST emit next_command=/vg:test-spec."""
    body = _read(REVIEW_CLOSE)
    # The PIPELINE-STATE write block must include next_command
    pipeline_block_idx = body.find("**Update PIPELINE-STATE.json:**")
    assert pipeline_block_idx > 0
    block = body[pipeline_block_idx:pipeline_block_idx + 1500]
    assert "s['next_command'] = '/vg:test-spec" in block, (
        "B69-B3: review/close.md must emit next_command=/vg:test-spec"
    )
    assert "B69 fix" in block


def test_b4_lifecycle_mermaid_canonical_order():
    """B4: LIFECYCLE.md mermaid must show build → review → test-spec → test."""
    body = _read(LIFECYCLE)
    mermaid_start = body.find("```mermaid")
    mermaid_end = body.find("```", mermaid_start + 10)
    mermaid = body[mermaid_start:mermaid_end]
    # Canonical edges (Phase 5 = "Verify" per LIFECYCLE convention,
    # slash command /vg:review). B69 inserted test-spec as Phase 5b.
    assert "P4 --> P5[5. Verify]" in mermaid
    assert "P5 --> P5B[5b. Test Spec]" in mermaid
    assert "P5B --> P6[6. Test]" in mermaid
    # Old broken edges must be gone
    assert "P4 --> P4B[4b. Test Spec]" not in mermaid
    assert "P4B --> P5[5. Verify]" not in mermaid


def test_b4_lifecycle_auto_chain_table_fixed():
    """B4: LIFECYCLE.md auto-chain table reflects fixed routing."""
    body = _read(LIFECYCLE)
    # build/close.md row
    assert "| `build/close.md` | `/vg:review {phase}` | always" in body
    # review/close.md fixed
    assert "| `review/close.md` | `/vg:test-spec {phase}` |" in body
    # test-spec.md fixed
    assert "| `test-spec.md` | `/vg:test {phase}` |" in body
    # Old broken row must be gone
    assert "| `test-spec.md` | `/vg:review {phase}` | always |" not in body
    # B69 tags
    assert "B69 fix" in body


def test_b4_test_spec_objective_canonical_order():
    """B4: test-spec.md objective MUST state post-review, NOT pre-review."""
    body = _read(TEST_SPEC)
    objective_start = body.find("<objective>")
    objective_end = body.find("</objective>")
    objective = body[objective_start:objective_end]
    # Must mention runs AFTER /vg:review
    assert "after `/vg:review`" in objective
    # Must NOT state "before /vg:review" anymore
    assert "before\n`/vg:review`" not in objective
    assert "and before\n`/vg:review`" not in objective
    # Canonical pipeline string present
    assert "build → review → test-spec → test → accept" in objective
    assert "B69" in objective


def test_b4_test_spec_no_stale_self_contradiction():
    """test-spec.md must not contradict its own Step 1 RUNTIME-MAP requirement."""
    body = _read(TEST_SPEC)
    # Step 1 still requires RUNTIME-MAP
    assert "RUNTIME-MAP.json" in body
    # Objective explanation now consistent
    obj_start = body.find("<objective>")
    obj_end = body.find("</objective>")
    objective = body[obj_start:obj_end]
    # Must explain why review must come first
    assert "RUNTIME-MAP" in objective


def test_mirrors_in_sync():
    assert _read(BUILD_CLOSE) == _read(BUILD_CLOSE_MIRROR)
    assert _read(REVIEW_CLOSE) == _read(REVIEW_CLOSE_MIRROR)
    assert _read(TEST_SPEC) == _read(TEST_SPEC_MIRROR)
    assert _read(LIFECYCLE) == _read(LIFECYCLE_MIRROR)
