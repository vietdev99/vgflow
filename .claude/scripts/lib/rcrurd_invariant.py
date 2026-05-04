"""rcrurd_invariant — Single Source of Truth for Read-After-Write invariants.

Codex GPT-5.5 review (2026-05-03): "A owns the schema and parser. B and C
must read that parser output. Do not let review/codegen independently
infer mutation invariants."

This module is consumed by:
  - Task 23 (review): lens-business-coherence runner reads invariant per goal
  - Task 24 (codegen): vg-test-codegen subagent emits expectReadAfterWrite()
                       calls from this parsed structure
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import yaml  # type: ignore


_VALID_OPS = {"contains", "equals", "matches", "not_contains"}
_VALID_CACHE = {"no_store", "cache_ok", "bypass_cdn"}
_VALID_SETTLE_MODE = {"immediate", "poll", "wait_event"}
_VALID_WRITE_METHOD = {"POST", "PUT", "PATCH", "DELETE"}

# Task 39 — RCRURDR lifecycle constants
_VALID_LIFECYCLE = {"rcrurd", "rcrurdr", "partial"}
_VALID_PHASE_NAMES = {
    "read_empty", "create", "read_populated", "update",
    "read_updated", "delete", "read_after_delete",
}
_RCRURDR_REQUIRED_PHASES = (
    "read_empty", "create", "read_populated", "update",
    "read_updated", "delete", "read_after_delete",
)
_GOAL_TYPE_REQUIRED_PHASES: dict[str, tuple[str, ...]] = {
    "create_only": ("read_empty", "create", "read_populated"),
    "update_only": ("read_populated", "update", "read_updated"),
    "delete_only": ("read_populated", "delete", "read_after_delete"),
    "crud_full": _RCRURDR_REQUIRED_PHASES,
}

_VALID_UI_OPS = {
    "count_matches_response_array",
    "text_contains_all",
    "each_exists_for_array_item",
    "text_equals_response_value",
    "text_matches_response_value",
    "visible_when_response_value",
    "hidden_when_response_value",
    "attribute_equals_response_value",
    "aria_state_matches",
    "input_value_equals_response",
}


class RCRURDInvariantError(ValueError):
    """Raised when an invariant doc fails schema validation."""


@dataclass(frozen=True)
class WriteSpec:
    method: str
    endpoint: str


@dataclass(frozen=True)
class SettleSpec:
    mode: Literal["immediate", "poll", "wait_event"]
    timeout_ms: int | None = None
    interval_ms: int | None = None


@dataclass(frozen=True)
class ReadSpec:
    method: str
    endpoint: str
    cache_policy: Literal["no_store", "cache_ok", "bypass_cdn"]
    settle: SettleSpec


@dataclass(frozen=True)
class Assertion:
    path: str
    op: Literal["contains", "equals", "matches", "not_contains"]
    value_from: str
    layer: str | None = None


@dataclass(frozen=True)
class UISettleSpec:
    """Independent of read.settle (Codex round 4 #5) — DOM render clock ≠ API."""
    timeout_ms: int
    poll_ms: int = 100


@dataclass(frozen=True)
class UIAssertOp:
    op: str
    dom_selector: str | None = None
    selector_template: str | None = None
    key_from: str | None = None
    response_path: str | None = None
    attribute: str | None = None
    aria_state: str | None = None
    regex: str | None = None
    expected_value: object = None


@dataclass(frozen=True)
class UIAssertBlock:
    settle: UISettleSpec
    ops: tuple[UIAssertOp, ...]
    # Task 39 (R9): pins DOM assertions to a specific lifecycle phase.
    # Backward-compat: None when lifecycle=rcrurd (single read).
    apply_to_phase: str | None = None


@dataclass(frozen=True)
class LifecyclePhase:
    """Task 39 — one phase in an RCRURDR or partial lifecycle."""
    phase: str  # one of _VALID_PHASE_NAMES
    write: WriteSpec | None  # None for read-only phases (read_empty, read_populated, etc.)
    read: ReadSpec
    assertions: tuple[Assertion, ...]


@dataclass(frozen=True)
class RCRURDInvariant:
    write: WriteSpec | None
    read: ReadSpec | None
    assertions: tuple[Assertion, ...]
    preconditions: tuple[Assertion, ...] = field(default=())
    side_effects: tuple[Assertion, ...] = field(default=())
    ui_assert: UIAssertBlock | None = None
    # Task 39 fields:
    lifecycle: str = "rcrurd"
    lifecycle_phases: tuple[LifecyclePhase, ...] = field(default=())


def parse_yaml(yaml_text: str) -> RCRURDInvariant:
    """Parse a YAML invariant doc → typed RCRURDInvariant. Raises
    RCRURDInvariantError on any schema violation (clearer than jsonschema).

    Supports three lifecycle discriminators (Task 39):
      - rcrurd  (default) — single write+read cycle, backward compat
      - rcrurdr — full 7-phase lifecycle via lifecycle_phases[]
      - partial  — goal_type-specific subset (3 phases)
    """
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise RCRURDInvariantError(f"yaml parse failed: {e}") from e

    if not isinstance(doc, dict):
        raise RCRURDInvariantError("top-level must be a mapping")

    lifecycle = doc.get("lifecycle", "rcrurd")
    if lifecycle not in _VALID_LIFECYCLE:
        raise RCRURDInvariantError(
            f"lifecycle must be one of {sorted(_VALID_LIFECYCLE)}, got {lifecycle!r}"
        )

    if lifecycle == "rcrurd":
        # Legacy single-cycle path: requires goal_type=mutation + read_after_write_invariant
        if doc.get("goal_type") != "mutation":
            raise RCRURDInvariantError("goal_type must be 'mutation'")
        raw = doc.get("read_after_write_invariant")
        if not isinstance(raw, dict):
            raise RCRURDInvariantError("read_after_write_invariant must be a mapping")

        write = _parse_write(raw.get("write"))
        read = _parse_read(raw.get("read"))
        assertions = _parse_assert_list(raw.get("assert"), "assert", min_items=1)
        preconditions = _parse_assert_list(raw.get("precondition"), "precondition", min_items=0)
        side_effects = _parse_side_effects(raw.get("side_effects"))
        ui_assert = _parse_ui_assert(raw.get("ui_assert"))

        return RCRURDInvariant(
            write=write, read=read, assertions=tuple(assertions),
            preconditions=tuple(preconditions), side_effects=tuple(side_effects),
            ui_assert=ui_assert,
            lifecycle="rcrurd", lifecycle_phases=(),
        )

    # New paths: rcrurdr or partial
    goal_type = doc.get("goal_type", "mutation")
    ui_assert = _parse_ui_assert(doc.get("ui_assert"))
    lifecycle_phases = _parse_lifecycle_phases(
        doc.get("lifecycle_phases"), lifecycle, goal_type,
    )
    return RCRURDInvariant(
        write=None, read=None, assertions=(),
        preconditions=(), side_effects=(),
        ui_assert=ui_assert,
        lifecycle=lifecycle,
        lifecycle_phases=tuple(lifecycle_phases),
    )


def _is_endpoint(s: object) -> bool:
    """Endpoint is either a relative path (`/api/...`) or absolute URL
    (`http(s)://host/api/...`). Relative is preferred in TEST-GOALS;
    runtime gate may inject base URL or accept absolute for tests."""
    return isinstance(s, str) and (s.startswith("/") or s.startswith("http://") or s.startswith("https://"))


def _parse_write(d: Any, optional: bool = False) -> WriteSpec | None:
    """Parse write spec. When optional=True, returns None if d is None (read-only phases)."""
    if d is None and optional:
        return None
    if not isinstance(d, dict):
        raise RCRURDInvariantError("write must be a mapping")
    method = d.get("method")
    if method not in _VALID_WRITE_METHOD:
        raise RCRURDInvariantError(f"write.method must be one of {sorted(_VALID_WRITE_METHOD)}, got {method!r}")
    endpoint = d.get("endpoint")
    if not _is_endpoint(endpoint):
        raise RCRURDInvariantError(f"write.endpoint must be a relative path '/...' or absolute URL, got {endpoint!r}")
    return WriteSpec(method=method, endpoint=endpoint)


def _parse_read(d: Any) -> ReadSpec:
    if not isinstance(d, dict):
        raise RCRURDInvariantError("read must be a mapping")
    method = d.get("method")
    if method != "GET":
        raise RCRURDInvariantError(f"read.method must be GET, got {method!r}")
    endpoint = d.get("endpoint")
    if not _is_endpoint(endpoint):
        raise RCRURDInvariantError(f"read.endpoint must be a relative path '/...' or absolute URL, got {endpoint!r}")
    cache_policy = d.get("cache_policy")
    if cache_policy not in _VALID_CACHE:
        raise RCRURDInvariantError(f"read.cache_policy must be one of {sorted(_VALID_CACHE)}, got {cache_policy!r}")
    settle = _parse_settle(d.get("settle"))
    return ReadSpec(method=method, endpoint=endpoint, cache_policy=cache_policy, settle=settle)


def _parse_settle(d: Any) -> SettleSpec:
    if not isinstance(d, dict):
        raise RCRURDInvariantError("settle must be a mapping")
    mode = d.get("mode")
    if mode not in _VALID_SETTLE_MODE:
        raise RCRURDInvariantError(f"settle.mode must be one of {sorted(_VALID_SETTLE_MODE)}, got {mode!r}")
    timeout_ms = d.get("timeout_ms")
    interval_ms = d.get("interval_ms")
    if mode in ("poll", "wait_event") and timeout_ms is None:
        raise RCRURDInvariantError(f"settle.mode={mode!r} requires explicit timeout_ms (eventual consistency must be declared)")
    return SettleSpec(mode=mode, timeout_ms=timeout_ms, interval_ms=interval_ms)


def _parse_one_assertion(d: Any, ctx: str) -> Assertion:
    if not isinstance(d, dict):
        raise RCRURDInvariantError(f"{ctx} item must be a mapping")
    path = d.get("path")
    if not isinstance(path, str) or not path.startswith("$"):
        raise RCRURDInvariantError(f"{ctx}.path must start with '$' (JSONPath), got {path!r}")
    op = d.get("op")
    if op not in _VALID_OPS:
        raise RCRURDInvariantError(f"{ctx}.op must be one of {sorted(_VALID_OPS)}, got {op!r}")
    value_from = d.get("value_from")
    if not isinstance(value_from, str):
        raise RCRURDInvariantError(f"{ctx}.value_from must be a string, got {type(value_from).__name__}")
    return Assertion(path=path, op=op, value_from=value_from, layer=d.get("layer"))


def _parse_assert_list(items: Any, ctx: str, min_items: int) -> list[Assertion]:
    if items is None:
        items = []
    if not isinstance(items, list):
        raise RCRURDInvariantError(f"{ctx} must be a list, got {type(items).__name__}")
    if len(items) < min_items:
        raise RCRURDInvariantError(f"{ctx} requires at least {min_items} item(s)")
    return [_parse_one_assertion(d, f"{ctx}[{i}]") for i, d in enumerate(items)]


def _parse_ui_settle(d: Any) -> UISettleSpec:
    if not isinstance(d, dict):
        raise RCRURDInvariantError("ui_assert.settle must be a mapping")
    timeout_ms = d.get("timeout_ms")
    if not isinstance(timeout_ms, int) or timeout_ms < 100 or timeout_ms > 60000:
        raise RCRURDInvariantError("ui_assert.settle.timeout_ms must be int [100, 60000]")
    poll_ms = d.get("poll_ms", 100)
    if not isinstance(poll_ms, int) or poll_ms < 50 or poll_ms > 5000:
        raise RCRURDInvariantError("ui_assert.settle.poll_ms must be int [50, 5000]")
    return UISettleSpec(timeout_ms=timeout_ms, poll_ms=poll_ms)


def _parse_ui_op(d: Any, ctx: str) -> UIAssertOp:
    if not isinstance(d, dict):
        raise RCRURDInvariantError(f"{ctx} item must be a mapping")
    op = d.get("op")
    if op not in _VALID_UI_OPS:
        raise RCRURDInvariantError(f"{ctx}.op must be one of {sorted(_VALID_UI_OPS)}, got {op!r}")

    if op == "each_exists_for_array_item":
        for k in ("response_path", "selector_template", "key_from"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op in ("count_matches_response_array", "text_contains_all"):
        for k in ("dom_selector", "response_path"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op == "text_matches_response_value":
        for k in ("dom_selector", "response_path", "regex"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op in ("visible_when_response_value", "hidden_when_response_value"):
        for k in ("dom_selector", "response_path", "expected_value"):
            if d.get(k) is None:
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op == "attribute_equals_response_value":
        for k in ("dom_selector", "response_path", "attribute"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op == "aria_state_matches":
        for k in ("dom_selector", "response_path", "aria_state"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")
    elif op in ("text_equals_response_value", "input_value_equals_response"):
        for k in ("dom_selector", "response_path"):
            if not d.get(k):
                raise RCRURDInvariantError(f"{ctx} ({op}) requires {k}")

    return UIAssertOp(
        op=op,
        dom_selector=d.get("dom_selector"),
        selector_template=d.get("selector_template"),
        key_from=d.get("key_from"),
        response_path=d.get("response_path"),
        attribute=d.get("attribute"),
        aria_state=d.get("aria_state"),
        regex=d.get("regex"),
        expected_value=d.get("expected_value"),
    )


def _parse_ui_assert(d: Any) -> UIAssertBlock | None:
    if d is None:
        return None
    if not isinstance(d, dict):
        raise RCRURDInvariantError("ui_assert must be a mapping or null")
    settle = _parse_ui_settle(d.get("settle"))
    ops_raw = d.get("ops")
    if not isinstance(ops_raw, list) or not ops_raw:
        raise RCRURDInvariantError("ui_assert.ops must be a non-empty list")
    ops = tuple(_parse_ui_op(o, f"ui_assert.ops[{i}]") for i, o in enumerate(ops_raw))
    # Task 39: apply_to_phase pins DOM assertions to a specific lifecycle phase
    apply_to_phase = d.get("apply_to_phase")
    if apply_to_phase is not None and apply_to_phase not in _VALID_PHASE_NAMES:
        raise RCRURDInvariantError(
            f"ui_assert.apply_to_phase must be one of {sorted(_VALID_PHASE_NAMES)}, got {apply_to_phase!r}"
        )
    return UIAssertBlock(settle=settle, ops=ops, apply_to_phase=apply_to_phase)


def _parse_lifecycle_phases(
    items: Any, lifecycle: str, goal_type: str
) -> list[LifecyclePhase]:
    """Parse lifecycle_phases list for rcrurdr / partial lifecycles."""
    if items is None:
        return []
    if not isinstance(items, list):
        raise RCRURDInvariantError("lifecycle_phases must be a list")

    phases: list[LifecyclePhase] = []
    seen_names: set[str] = set()
    for i, d in enumerate(items):
        ctx = f"lifecycle_phases[{i}]"
        if not isinstance(d, dict):
            raise RCRURDInvariantError(f"{ctx} must be a mapping")
        phase = d.get("phase")
        if phase not in _VALID_PHASE_NAMES:
            raise RCRURDInvariantError(
                f"{ctx}.phase must be one of {sorted(_VALID_PHASE_NAMES)}, got {phase!r}"
            )
        if phase in seen_names:
            raise RCRURDInvariantError(f"{ctx}.phase {phase!r} duplicated")
        seen_names.add(phase)

        # Read-only phases (starting with "read_") have no write spec
        is_read_only_phase = phase.startswith("read_")
        write = _parse_write(d.get("write"), optional=is_read_only_phase)
        read = _parse_read(d.get("read"))
        assertions = _parse_assert_list(d.get("assert"), f"{ctx}.assert", min_items=1)
        phases.append(LifecyclePhase(
            phase=phase, write=write, read=read, assertions=tuple(assertions),
        ))

    # Validate completeness per lifecycle/goal_type
    if lifecycle == "rcrurdr":
        required = set(_RCRURDR_REQUIRED_PHASES)
        if seen_names != required:
            missing = required - seen_names
            raise RCRURDInvariantError(
                f"lifecycle: rcrurdr requires all 7 phases; "
                f"missing: {sorted(missing)}"
            )
    elif lifecycle == "partial":
        required_tuple = _GOAL_TYPE_REQUIRED_PHASES.get(goal_type)
        if required_tuple is not None and seen_names != set(required_tuple):
            missing = set(required_tuple) - seen_names
            raise RCRURDInvariantError(
                f"goal_type: {goal_type} (lifecycle: partial) requires phases "
                f"{required_tuple}; missing: {sorted(missing)}"
            )

    return phases


def _parse_side_effects(items: Any) -> list[Assertion]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise RCRURDInvariantError("side_effects must be a list")
    out: list[Assertion] = []
    for i, d in enumerate(items):
        a = _parse_one_assertion(d, f"side_effects[{i}]")
        if not a.layer:
            raise RCRURDInvariantError(f"side_effects[{i}].layer is required")
        out.append(a)
    return out


def to_yaml(inv: RCRURDInvariant) -> str:
    """Round-trip serialize for snapshot tests + canonical storage."""
    doc: dict[str, Any] = {
        "goal_type": "mutation",
        "read_after_write_invariant": {
            "write": {"method": inv.write.method, "endpoint": inv.write.endpoint},
            "read": {
                "method": inv.read.method,
                "endpoint": inv.read.endpoint,
                "cache_policy": inv.read.cache_policy,
                "settle": _settle_to_dict(inv.read.settle),
            },
            "assert": [_assertion_to_dict(a) for a in inv.assertions],
        },
    }
    if inv.preconditions:
        doc["read_after_write_invariant"]["precondition"] = [_assertion_to_dict(a) for a in inv.preconditions]
    if inv.side_effects:
        doc["read_after_write_invariant"]["side_effects"] = [
            {**_assertion_to_dict(a), "layer": a.layer} for a in inv.side_effects
        ]
    return yaml.safe_dump(doc, sort_keys=False)


def _settle_to_dict(s: SettleSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": s.mode}
    if s.timeout_ms is not None:
        out["timeout_ms"] = s.timeout_ms
    if s.interval_ms is not None:
        out["interval_ms"] = s.interval_ms
    return out


def _assertion_to_dict(a: Assertion) -> dict[str, Any]:
    return {"path": a.path, "op": a.op, "value_from": a.value_from}


def extract_from_test_goal_md(goal_md_text: str) -> RCRURDInvariant | None:
    """Extract the YAML invariant block from a TEST-GOAL markdown file.

    Recognized fence: ```yaml-rcrurd ... ``` OR a `## Read-after-write invariant`
    H2 followed by a yaml fence. Returns None if not present (caller decides
    whether absence is a violation — e.g. mutation goal must have it).
    """
    import re
    m = re.search(r"```yaml-rcrurd\s*\n(.+?)\n```", goal_md_text, re.DOTALL)
    if not m:
        m = re.search(
            r"##\s+Read-after-write invariant\s*\n+```ya?ml\s*\n(.+?)\n```",
            goal_md_text, re.DOTALL | re.IGNORECASE,
        )
    if not m:
        return None
    return parse_yaml(m.group(1))
