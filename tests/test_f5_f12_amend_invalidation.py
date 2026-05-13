"""tests/test_f5_f12_amend_invalidation.py — F5+F12 amend cascade enforcement."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
AMEND = REPO / "commands" / "vg" / "amend.md"
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "accept" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_amend_writes_invalidation_artifact():
    body = _read(AMEND)
    assert ".amend-invalidation.json" in body, (
        "F5: /vg:amend Phase 4 (close) must write ${PHASE_DIR}/.amend-invalidation.json "
        "with {amended_at, changed_goals, changed_decisions} so downstream phases "
        "can detect 'test results pre-date amend'"
    )
    # Must include changed_decisions / changed_goals payload
    assert "changed_decisions" in body or "changed_goals" in body or "decision_refs" in body, (
        "F5: invalidation artifact must enumerate WHICH decisions/goals changed"
    )


def test_amend_invalidation_includes_timestamp():
    body = _read(AMEND)
    assert "amended_at" in body, (
        "F5: invalidation artifact must include amended_at ISO timestamp for "
        "accept-time comparison vs SANDBOX-TEST.md tested field"
    )


def test_accept_preflight_checks_amend_invalidation():
    body = _read(PREFLIGHT)
    assert ".amend-invalidation.json" in body, (
        "F12: accept/preflight.md must read .amend-invalidation.json and "
        "compare amended_at vs SANDBOX-TEST.md tested timestamp"
    )
    assert "amended_at" in body, (
        "F12: accept preflight must check amended_at against tested timestamp"
    )


def test_accept_preflight_blocks_when_amend_postdates_test():
    body = _read(PREFLIGHT)
    # The check must lead to BLOCK or exit non-zero
    assert "BLOCK" in body or "exit 1" in body or "amend_invalidation_block" in body, (
        "F12: when amended_at > SANDBOX-TEST.md.tested, accept preflight must "
        "BLOCK with message 'Test results pre-date amend; re-run /vg:test'"
    )
