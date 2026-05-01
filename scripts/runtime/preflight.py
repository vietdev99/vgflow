"""data_invariants N-consumer preflight verifier (RFC v9 D5).

Closes the wave-3.x non-convergence ping-pong: when 3 destructive consumers
all run preflight checking "tier2 topup pending count >= 1", they each see 1
row, each thinks they're fine, all three try to mutate it, two collide.

D5 algorithm:
1. Parse `data_invariants:` block from ENV-CONTRACT.md.
2. Validate against schemas/data-invariants.v1.json.
3. For each invariant:
   destructive_n = count of consumers with consume_semantics='destructive'
   read_only_n   = count of consumers with consume_semantics='read_only'
   if isolation = 'per_consumer' (default):
     required = destructive_n + (1 if read_only_n > 0 else 0)
   if isolation = 'shared_when_read_only':
     required = max(destructive_n, 1 if read_only_n > 0 else 0)
4. Count actual entities via project-supplied count_fn(resource, where) → int.
5. If actual < required → BLOCK with fix-hint listing the gap.

The count_fn is pluggable so this verifier can be unit-tested without
hitting an HTTP API. /vg:review wires count_fn to the recipe_executor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


class PreflightError(Exception):
    """data_invariants block missing, malformed, or unsatisfied."""


@dataclass
class InvariantGap:
    invariant_id: str
    resource: str
    required: int
    actual: int
    consumers: list[str] = field(default_factory=list)
    isolation: str = "per_consumer"
    where: dict = field(default_factory=dict)


def parse_env_contract(path: Path | str) -> list[dict]:
    """Extract data_invariants[] from ENV-CONTRACT.md.

    Format: a fenced ```yaml block starting with `data_invariants:` OR
    a top-level YAML document (whole file is YAML). Both are supported.
    """
    text = Path(path).read_text(encoding="utf-8")
    if yaml is None:
        raise PreflightError("PyYAML required for ENV-CONTRACT parsing")

    # Try fenced yaml block first
    blocks = re.findall(r"```ya?ml\s*\n(.*?)\n```", text, re.DOTALL)
    for block in blocks:
        if "data_invariants:" in block:
            try:
                parsed = yaml.safe_load(block)
            except yaml.YAMLError as e:
                raise PreflightError(f"Malformed YAML block in ENV-CONTRACT: {e}") from e
            if isinstance(parsed, dict) and "data_invariants" in parsed:
                inv = parsed["data_invariants"]
                if not isinstance(inv, list):
                    raise PreflightError("data_invariants must be a list")
                return inv

    # Fall back: treat full file as YAML
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PreflightError(f"ENV-CONTRACT not valid YAML: {e}") from e
    if isinstance(parsed, dict) and "data_invariants" in parsed:
        inv = parsed["data_invariants"]
        if not isinstance(inv, list):
            raise PreflightError("data_invariants must be a list")
        return inv

    return []


def required_count(invariant: dict) -> int:
    """Compute required entity count for an invariant per D5 algorithm."""
    consumers = invariant.get("consumers") or []
    if not consumers:
        raise PreflightError(
            f"invariant '{invariant.get('id')}' has no consumers (D5 expects ≥1)"
        )
    destructive_n = sum(1 for c in consumers if c.get("consume_semantics") == "destructive")
    read_only_n = sum(1 for c in consumers if c.get("consume_semantics") == "read_only")
    isolation = invariant.get("isolation", "per_consumer")

    if isolation == "shared_when_read_only":
        if destructive_n == 0 and read_only_n > 0:
            return 1  # all read_only → share
        return destructive_n  # any destructive → per_consumer fallback
    if isolation == "per_consumer":
        return destructive_n + (1 if read_only_n > 0 else 0)
    raise PreflightError(
        f"invariant '{invariant.get('id')}' unknown isolation='{isolation}'"
    )


CountFn = Callable[[str, dict[str, Any]], int]


def verify_invariants(
    invariants: list[dict],
    count_fn: CountFn,
) -> list[InvariantGap]:
    """Returns gaps where actual < required.

    count_fn(resource, where_filter) → int. Project supplies via
    /vg:review wiring (uses recipe_executor against env's API).
    """
    gaps: list[InvariantGap] = []
    for inv in invariants:
        inv_id = inv.get("id")
        resource = inv.get("resource")
        where = inv.get("where") or {}
        if not (inv_id and resource):
            raise PreflightError(f"invariant missing id or resource: {inv}")
        required = required_count(inv)
        actual = count_fn(resource, where)
        if actual < required:
            consumer_ids = [c.get("goal", "?") for c in (inv.get("consumers") or [])]
            gaps.append(InvariantGap(
                invariant_id=inv_id,
                resource=resource,
                required=required,
                actual=actual,
                consumers=consumer_ids,
                isolation=inv.get("isolation", "per_consumer"),
                where=where,
            ))
    return gaps


def fix_hint(gap: InvariantGap) -> str:
    """Render a deterministic fix-hint for a gap."""
    needed = gap.required - gap.actual
    consumers_str = ", ".join(gap.consumers[:5])
    return (
        f"invariant {gap.invariant_id!r} on {gap.resource!r}: required={gap.required} "
        f"(consumers: {consumers_str}), actual={gap.actual} → create {needed} more "
        f"row(s) matching {gap.where!r}. Run /vg:review {{phase}} once consumers' "
        f"FIXTURES recipes can populate the gap, OR adjust isolation to "
        f"'shared_when_read_only' if all consumers are read_only."
    )
