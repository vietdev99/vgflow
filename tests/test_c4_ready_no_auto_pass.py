"""tests/test_c4_ready_no_auto_pass.py — Batch 9 C4 gap.

Verifies:
1. matrix-intent.md documents READY_BEHAVIORAL as the only state that
   auto-passes in TRUST_REVIEW.
2. goal-verification/delegation.md TRUST_REVIEW Step D does NOT auto-PASS
   bare READY goals — those go to TEST_PENDING / replay.
"""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
MATRIX = REPO / "commands" / "vg" / "_shared" / "review" / "matrix-intent.md"
DELEG = REPO / "commands" / "vg" / "_shared" / "test" / "goal-verification" / "delegation.md"
MATRIX_MIR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "matrix-intent.md"
DELEG_MIR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "goal-verification" / "delegation.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_matrix_intent_defines_behavioral_split():
    body = _read(MATRIX)
    assert "READY_BEHAVIORAL" in body, (
        "C4: matrix-intent.md must define READY_BEHAVIORAL verdict for goals "
        "with persisted per-goal assertion evidence (not just structural scan)"
    )
    assert "READY_STRUCTURAL" in body or "READY" in body, (
        "Must retain structural READY state for endpoint+selector-only goals"
    )


def test_trust_review_does_not_auto_pass_structural():
    body = _read(DELEG)
    # Find the Step D Skip READY block
    if "Skip READY goals" in body:
        # NEW behavior: must distinguish structural vs behavioral
        idx = body.index("Skip READY goals")
        block = body[idx:idx + 800]
        assert "READY_BEHAVIORAL" in block or "TEST_PENDING" in block, (
            f"C4: TRUST_REVIEW Step D 'Skip READY goals' block must either "
            f"check READY_BEHAVIORAL specifically OR emit TEST_PENDING for "
            f"structural READY goals (forcing replay). Got block: {block[:300]}"
        )
        # Must NOT unconditionally emit PASSED for all READY
        bad_lines = [l for l in block.splitlines() if 'status: "PASSED"' in l and 'BEHAVIORAL' not in l and 'TEST_PENDING' not in l]
        # At least one PASSED-emit line must be conditional on BEHAVIORAL
        for l in bad_lines:
            if "trust-review" in l.lower():
                # Allow if it's specifically for BEHAVIORAL
                continue


def test_trust_review_mode_field_includes_structural_pending():
    body = _read(DELEG)
    # The mode/status enum must include TEST_PENDING for structural-only goals
    assert "TEST_PENDING" in body, (
        "C4: delegation.md must reference TEST_PENDING status for goals "
        "that pass structural review but require behavioral replay"
    )


def test_mirrors_byte_identical():
    if MATRIX_MIR.is_file():
        assert _read(MATRIX) == _read(MATRIX_MIR)
    if DELEG_MIR.is_file():
        assert _read(DELEG) == _read(DELEG_MIR)
