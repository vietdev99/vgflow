"""tests/test_batch31_reflect_mobile_contract.py — Batch 31.

Audit gaps #3/#10/#14:
- bootstrap_reflection: mark fires regardless of REFLECTION.md existence.
- 5a_mobile_deploy: helper functions called without sourcing (defined in
  mobile-deploy.md markdown blocks).
- 5b_runtime_contract_verify: per-endpoint curl/jq compare is prose; bash
  stops after enumeration.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "commands" / "vg" / "_shared" / "test" / "close.md"
DEPLOY = REPO / "commands" / "vg" / "_shared" / "test" / "deploy.md"
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"


def test_bootstrap_reflection_status_gate():
    """bootstrap_reflection must set REFLECTION_STATUS before mark.
    PASS only if REFLECTION.md exists or explicitly skipped."""
    body = CLOSE.read_text(encoding="utf-8")
    mark_idx = body.find("mark-step test bootstrap_reflection")
    assert mark_idx > 0
    pre = body[max(0, mark_idx - 2500):mark_idx]
    assert "REFLECTION_STATUS" in pre, (
        "Batch 31 gap #10: bootstrap_reflection must gate on REFLECTION_STATUS "
        "(set from REFLECTION.md presence + skip flags) before mark"
    )


def test_5a_mobile_deploy_helper_sourced():
    """5a_mobile_deploy bash body must SOURCE helper bash, not just reference it."""
    body = DEPLOY.read_text(encoding="utf-8")
    # Find the actual bash block (not the header mention)
    mobile_idx = body.find("vg-orchestrator step-active 5a_mobile_deploy")
    assert mobile_idx > 0
    block = body[mobile_idx:mobile_idx + 4000]
    has_source = (
        "MOBILE_HELPERS_SOURCED" in block
        or "HELPER_BASH" in block
        or "extract_bash" in block
        or 'source "$HELPER' in block
    )
    assert has_source, (
        "Batch 31 gap #14: 5a_mobile_deploy bash body must SOURCE helper bash "
        "(extract from mobile-deploy.md markdown or load .sh file). "
        "Currently calls mobile_deploy_* functions that are undefined "
        "in shell scope."
    )


def test_5b_runtime_contract_per_endpoint_curl():
    """5b_runtime_contract_verify must have per-endpoint curl loop, not
    just enumeration. The 'For each endpoint' must be bash with explicit
    CONTRACT_MISMATCHES tracker (separate from idempotency curl block)."""
    body = RUNTIME.read_text(encoding="utf-8")
    contract_idx = body.find("5b_runtime_contract_verify")
    assert contract_idx > 0
    block = body[contract_idx:contract_idx + 8000]
    assert "CONTRACT_MISMATCHES" in block, (
        "Batch 31 gap #3: 5b_runtime_contract_verify must have explicit "
        "CONTRACT_MISMATCHES counter from per-endpoint curl/jq compare. "
        "Currently bash stops after endpoint enumeration; per-endpoint "
        "compare is prose only."
    )
    assert "CONTRACT_VERIFY_STATUS" in block, (
        "Batch 31 gap #3: must set CONTRACT_VERIFY_STATUS from CONTRACT_MISMATCHES"
    )


def test_mirrors_in_sync():
    for src in [CLOSE, DEPLOY, RUNTIME]:
        mirror = REPO / ".claude" / src.relative_to(REPO)
        assert src.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8"), (
            f"Mirror drift: {mirror.relative_to(REPO)}"
        )
