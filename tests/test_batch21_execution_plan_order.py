"""tests/test_batch21_execution_plan_order.py — Batch 21 execution plan order."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_reads_execution_plan_for_order():
    body = RS.read_text(encoding="utf-8")
    # Must read TEST-EXECUTION-PLAN.json for execution_order or order
    assert "TEST-EXECUTION-PLAN.json" in body, (
        "Batch 21: test runtime must read TEST-EXECUTION-PLAN.json"
    )
    # And use it to order specs
    assert ("execution_order" in body or "order" in body and "playwright" in body), (
        "Batch 21: must consume execution_order from TEST-EXECUTION-PLAN.json "
        "(not rely on alphabetical default)"
    )


def test_family_routing_applied():
    body = RS.read_text(encoding="utf-8")
    # If TEST-EXECUTION-PLAN.json has family field per spec, must apply
    # --project=<family> to playwright invocation OR document family-aware run
    assert ("family" in body and "playwright" in body), (
        "Batch 21: family field from execution-plan must affect playwright "
        "invocation (e.g. --project=<family> or runner selection)"
    )
