"""D28 multi-Type-A BLOCK aggregator (RFC v9 PR-block-aggregator).

When a /vg:* run hits N gate failures of the same family (e.g., 12 missing
artifacts, 8 traceability orphans), invoking block-resolver L2 N times
spends N × architect-spawn token cost. Aggregator collects same-family
blocks into ONE proposal request — architect sees all N instances in a
single context window, returns a multi-fix proposal that the resolver
applies in a single pass.

Aggregator policy:
- Group key: gate_id (e.g., "review-prereq-missing", "traceability-orphan")
- Threshold: aggregate when count ≥ 3 (configurable)
- Below threshold: pass through unchanged (single-block path)
- Sort instances by severity then chronologically
- Cap merged context at config.max_merged_evidence (default 50 instances)

Output shape mirrors single-block input so block-resolver consumes
without modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlockInstance:
    gate_id: str
    family: str
    severity: str = "block"  # block | warn | advisory
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None


@dataclass
class AggregatedBlock:
    gate_id: str
    family: str
    instance_count: int
    severity: str
    instances: list[BlockInstance]
    sample_evidence: list[dict[str, Any]]
    merged_context: str

    @property
    def is_aggregated(self) -> bool:
        return self.instance_count > 1


SEVERITY_RANK = {"block": 3, "warn": 2, "advisory": 1}


def aggregate(
    instances: list[BlockInstance],
    *,
    threshold: int = 3,
    max_merged_evidence: int = 50,
) -> list[AggregatedBlock]:
    """Group block instances by gate_id and emit aggregated or passthrough.

    Threshold rule: groups with size ≥ threshold → AggregatedBlock with
    merged context. Smaller groups → AggregatedBlock with instance_count=1
    (the single-block path; resolver treats it as one-shot).
    """
    by_family: dict[str, list[BlockInstance]] = {}
    for inst in instances:
        if not isinstance(inst, BlockInstance):
            raise TypeError(f"expected BlockInstance, got {type(inst).__name__}")
        by_family.setdefault(inst.gate_id, []).append(inst)

    out: list[AggregatedBlock] = []
    for gate_id, group in by_family.items():
        # Sort: highest severity first, then by timestamp ascending
        group_sorted = sorted(
            group,
            key=lambda i: (
                -SEVERITY_RANK.get(i.severity, 0),
                i.timestamp or "",
            ),
        )
        capped = group_sorted[:max_merged_evidence]
        max_sev = max(group_sorted, key=lambda i: SEVERITY_RANK.get(i.severity, 0))
        family = capped[0].family
        merged = _merge_context(capped, len(group_sorted), max_merged_evidence)
        out.append(AggregatedBlock(
            gate_id=gate_id,
            family=family,
            instance_count=len(group_sorted),
            severity=max_sev.severity,
            instances=capped,
            sample_evidence=[i.evidence for i in capped[:5]],
            merged_context=merged,
        ))
    # Sort output: aggregated (size ≥ threshold) first, then singletons
    out.sort(key=lambda a: (
        0 if a.instance_count >= threshold else 1,
        -a.instance_count,
    ))
    return out


def _merge_context(
    instances: list[BlockInstance],
    total: int,
    cap: int,
) -> str:
    """Render a markdown-ish context blob the architect can read."""
    lines = [f"# Aggregated BLOCK: {instances[0].gate_id}",
             f"Total instances: {total}"]
    if total > cap:
        lines.append(f"⚠ Capped to first {cap} instances (sorted by severity)")
    lines.append("")
    lines.append("## Instances")
    for i, inst in enumerate(instances, 1):
        lines.append(f"### {i}. severity={inst.severity}")
        if inst.timestamp:
            lines.append(f"- timestamp: {inst.timestamp}")
        if inst.evidence:
            lines.append("- evidence:")
            for k, v in inst.evidence.items():
                lines.append(f"  - {k}: {v!r}")
        lines.append("")
    return "\n".join(lines)


def should_aggregate(
    instances: list[BlockInstance],
    *,
    threshold: int = 3,
) -> bool:
    """Convenience: True if any gate_id family has ≥ threshold instances."""
    counts: dict[str, int] = {}
    for inst in instances:
        counts[inst.gate_id] = counts.get(inst.gate_id, 0) + 1
    return any(n >= threshold for n in counts.values())
