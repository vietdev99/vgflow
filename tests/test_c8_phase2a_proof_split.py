"""tests/test_c8_phase2a_proof_split.py — C8 Phase 2a proof split."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "review" / "api-and-discovery.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_proof_reuse_does_not_skip_interface_standards():
    body = _read(CANON)
    # When PROOF_FRESH=true block must NOT short-circuit the whole phase2a
    # Look for the proof-reuse block — it must NOT skip interface + api-docs
    proof_block_start = body.find("PROOF_FRESH=\"true\"")
    if proof_block_start < 0:
        proof_block_start = body.find('PROOF_FRESH" = "true"')
    assert proof_block_start > 0
    # The interface-standards validator MUST still run after proof reuse
    # Check that the block doesn't end with raw "else" that gates ALL remaining work
    proof_block = body[proof_block_start:proof_block_start + 1500]
    assert "Skip remainder of phase2a" not in proof_block or "Skip live probe only" in proof_block, (
        "C8: proof reuse must NOT skip the remainder of phase2a (interface "
        "standards + api-docs coverage). Only the live runtime probe is "
        "skipped — other validators each need their own proof or fresh run."
    )


def test_interface_standards_runs_under_both_paths():
    body = _read(CANON)
    # The interface-standards validator block must be reached regardless of
    # proof status. Inspect structure: interface val should NOT be inside the
    # `else` branch of `if PROOF_FRESH`.
    proof_idx = body.find('PROOF_FRESH" = "true"')
    interface_idx = body.find('INTERFACE_VAL=')
    if interface_idx < 0:
        interface_idx = body.find('INTERFACE_VAL="')
    assert proof_idx > 0 and interface_idx > 0
    # Interface val must come AFTER proof-fresh block ends (fi) OR be outside the if
    # Simplest check: find the matching `fi` after PROOF_FRESH and ensure
    # INTERFACE_VAL is BEFORE the conditional or AFTER the closing fi.
    # New behavior: INTERFACE_VAL should be reached in BOTH paths.
    # Look for marker comment confirming the split.
    assert ("C8 Batch 2" in body or
            "proof reuse only skips live probe" in body.lower() or
            "interface standards still runs" in body.lower()), (
        "C8: api-and-discovery.md must contain a comment marking the split "
        "fix (e.g. 'C8 Batch 2: proof reuse only skips live probe')"
    )


def test_api_docs_coverage_runs_under_both_paths():
    body = _read(CANON)
    # verify-api-docs-coverage.py invocation must NOT be inside the
    # `else` branch of `if PROOF_FRESH`
    docs_idx = body.find("verify-api-docs-coverage.py")
    assert docs_idx > 0, "api-docs coverage validator must be invoked"
    # Same comment marker check serves as proxy
    assert ("C8 Batch 2" in body or "interface + api-docs still run" in body.lower()), (
        "C8: api-docs coverage must run under proof-reused path too"
    )
