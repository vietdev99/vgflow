"""tests/test_batch29_smoke_flow_fixloop_gates.py — Batch 29 SCAFFOLD→gated.

Gaps #5/#8/#9 from docs/plans/2026-05-15-codex-test-flow-audit.md:
- 5c_smoke: prose only. SMOKE_STATUS defaults PASS regardless of mismatch count.
- 5c_flow: flow-runner invocation is prose. No bash invoke.
- step5_fix_loop: no concrete loop outcome check before mark.

Fix: artifact gate — each step requires evidence file with required fields
before marking. AI runner writes artifact, bash validates. On gate fail:
status=FAIL + event emit + exit 1 unless escape hatch.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"
TEST_MD = REPO / "commands" / "vg" / "test.md"
RUNTIME_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "runtime.md"
TEST_MD_MIRROR = REPO / ".claude" / "commands" / "vg" / "test.md"


def test_5c_smoke_artifact_gate():
    """5c_smoke must read smoke-results.json before marking. If file absent
    or mismatch count >= 2, FAIL + emit event."""
    body = RUNTIME.read_text(encoding="utf-8")
    smoke_start = body.find("vg-orchestrator step-active 5c_smoke")
    assert smoke_start > 0
    block = body[smoke_start:smoke_start + 3000]
    assert "smoke-results.json" in block, (
        "F-29.1: 5c_smoke must check smoke-results.json artifact "
        "before mark. AI runner writes file, bash validates count."
    )
    assert "SMOKE_STATUS" in block
    assert (
        "test.smoke_check_failed" in block
        or 'SMOKE_STATUS="FAIL"' in block
        or "SMOKE_STATUS=FAIL" in block
    ), "F-29.1: smoke FAIL must emit event or set FAIL status"


def test_5c_flow_artifact_gate():
    """5c_flow must check flow-results.json when FLOW-SPEC.md exists.
    Without flow-results.json, FAIL + emit event."""
    body = RUNTIME.read_text(encoding="utf-8")
    flow_start = body.find("vg-orchestrator step-active 5c_flow")
    assert flow_start > 0
    block = body[flow_start:flow_start + 5000]
    # Already has FLOW_RESULTS lookup at line 365-372, but no FAIL path
    # if FLOW-SPEC.md exists yet flow-results.json absent (means flow-runner
    # was never invoked despite spec).
    assert "FLOW_SPEC_EXISTS" in block or "flow-results.json" in block
    has_fail_gate = (
        "test.flow_check_failed" in block
        or "FLOW_STATUS=FAIL" in block
        or 'FLOW_STATUS="FAIL"' in block
    )
    assert has_fail_gate, (
        "F-29.2: 5c_flow must FAIL when FLOW-SPEC.md present but "
        "flow-results.json absent (runner never invoked)"
    )


def test_step5_fix_loop_outcome_gate():
    """step5_fix_loop mark must have explicit FIX_LOOP_STATUS variable set
    by outcome check. Cannot mark unconditionally with `|| true`."""
    body = TEST_MD.read_text(encoding="utf-8")
    mark_idx = body.find("mark-step test step5_fix_loop")
    assert mark_idx > 0
    pre = body[max(0, mark_idx - 2500):mark_idx]
    assert "FIX_LOOP_STATUS" in pre, (
        "F-29.3: step5_fix_loop must set FIX_LOOP_STATUS={PASS|FAIL|BLOCKED|SKIPPED} "
        "based on outcome (failing_goals==0 / FIX-LOOP-BLOCKED.md / "
        "--skip-fix-loop debt) before mark. Currently unconditional mark."
    )


def test_mirrors_in_sync():
    assert RUNTIME.read_text(encoding="utf-8") == RUNTIME_MIRROR.read_text(encoding="utf-8")
    assert TEST_MD.read_text(encoding="utf-8") == TEST_MD_MIRROR.read_text(encoding="utf-8")
