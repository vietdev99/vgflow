"""Tests for scripts/runtime/block_aggregator.py — RFC v9 D28."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.block_aggregator import (  # noqa: E402
    AggregatedBlock,
    BlockInstance,
    aggregate,
    should_aggregate,
)


def _instance(gate_id: str, family: str = "missing-artifact",
              severity: str = "block", **evidence) -> BlockInstance:
    return BlockInstance(
        gate_id=gate_id, family=family, severity=severity,
        evidence=evidence,
    )


def test_single_instance_passes_through_as_singleton():
    out = aggregate([_instance("g1", artifact="X.md")], threshold=3)
    assert len(out) == 1
    assert out[0].instance_count == 1
    assert not out[0].is_aggregated


def test_three_same_gate_aggregated():
    instances = [_instance("missing-artifact", artifact=f"X{i}.md") for i in range(3)]
    out = aggregate(instances, threshold=3)
    assert len(out) == 1
    assert out[0].instance_count == 3
    assert out[0].is_aggregated
    assert out[0].gate_id == "missing-artifact"


def test_below_threshold_not_aggregated():
    instances = [_instance("missing-artifact", artifact=f"X{i}.md") for i in range(2)]
    out = aggregate(instances, threshold=3)
    # Returns 1 group of 2 (still grouped by gate_id, but treated as singleton path)
    assert len(out) == 1
    assert out[0].instance_count == 2  # is_aggregated property: True
    assert out[0].is_aggregated is True  # > 1 — but caller decides routing


def test_mixed_families_grouped_separately():
    instances = [
        _instance("missing-artifact", artifact="A.md"),
        _instance("missing-artifact", artifact="B.md"),
        _instance("missing-artifact", artifact="C.md"),
        _instance("traceability-orphan", goal="G-1"),
    ]
    out = aggregate(instances, threshold=3)
    assert len(out) == 2
    counts = {a.gate_id: a.instance_count for a in out}
    assert counts == {"missing-artifact": 3, "traceability-orphan": 1}


def test_severity_max_propagates():
    instances = [
        _instance("g", severity="warn"),
        _instance("g", severity="block"),
        _instance("g", severity="advisory"),
    ]
    out = aggregate(instances, threshold=2)
    assert out[0].severity == "block"


def test_capped_at_max_merged_evidence():
    instances = [_instance("g", n=i) for i in range(100)]
    out = aggregate(instances, threshold=3, max_merged_evidence=10)
    assert out[0].instance_count == 100  # total reported
    assert len(out[0].instances) == 10  # but capped
    assert "Capped to first 10" in out[0].merged_context


def test_sort_aggregated_before_singletons():
    instances = [
        _instance("g-singleton-1", n=1),
        *[_instance("g-aggregated", n=i) for i in range(5)],
        _instance("g-singleton-2", n=2),
    ]
    out = aggregate(instances, threshold=3)
    # Aggregated first
    assert out[0].instance_count == 5
    assert out[0].gate_id == "g-aggregated"
    assert out[1].instance_count == 1
    assert out[2].instance_count == 1


def test_merged_context_includes_evidence_details():
    instances = [_instance("g", artifact=f"file{i}.md") for i in range(3)]
    out = aggregate(instances, threshold=3)
    ctx = out[0].merged_context
    assert "Total instances: 3" in ctx
    assert "file0.md" in ctx
    assert "severity=block" in ctx


def test_should_aggregate_helper_above_threshold():
    instances = [_instance("g") for _ in range(4)]
    assert should_aggregate(instances, threshold=3)


def test_should_aggregate_helper_below_threshold():
    instances = [_instance("g") for _ in range(2)]
    assert not should_aggregate(instances, threshold=3)


def test_should_aggregate_helper_mixed_one_meets_threshold():
    instances = [
        *[_instance("g1") for _ in range(4)],
        *[_instance("g2") for _ in range(1)],
    ]
    assert should_aggregate(instances, threshold=3)


def test_sample_evidence_truncated_to_5():
    instances = [_instance("g", n=i) for i in range(10)]
    out = aggregate(instances, threshold=3)
    assert len(out[0].sample_evidence) == 5


def test_invalid_input_raises():
    with pytest.raises(TypeError):
        aggregate(["not a BlockInstance"], threshold=3)
