<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 22: RCRURD invariant schema + parser (Single Source of Truth)

**Files:**
- Create: `schemas/rcrurd-invariant.schema.yaml` (canonical schema)
- Create: `scripts/lib/rcrurd_invariant.py` (parser + serializer — Tasks 23 + 24 read from here)
- Modify: `commands/vg/_shared/blueprint/contracts-delegation.md` (TEST-GOAL template require structured invariant for `goal_type: mutation`)
- Modify: `commands/vg/_shared/blueprint/contracts-overview.md` (block when mutation goal lacks structured invariant)
- Test: `tests/test_rcrurd_invariant.py`

**Why (Codex GPT-5.5 review 2026-05-03):** VG already has a `**Persistence check:**` block requirement (Rule 3b) for mutation goals — but it only checks Markdown block existence, not structured fields. Result: `persistence_probe.persisted: true` gets accepted as proof without field/value comparison. The user's bug (grant role → toast OK → role NOT applied) lands here: existing block says "persisted" but doesn't verify `roles[]` contains the new role.

This task creates the **single source of truth**: a structured YAML schema that downstream Tasks 23 (review) and 24 (codegen) MUST read from. No independent inference allowed in B/C.

**Schema design (Codex-provided exact shape):**

```yaml
goal_type: mutation
read_after_write_invariant:
  write:
    method: PATCH
    endpoint: /api/users/{userId}/roles
  read:
    method: GET
    endpoint: /api/users/{userId}
    cache_policy: no_store     # no_store | cache_ok | bypass_cdn
    settle:
      mode: immediate          # immediate | poll | wait_event
      timeout_ms: 5000         # only used when mode=poll/wait_event
      interval_ms: 500
  assert:
    - path: $.roles[*].name    # JSONPath against read response body
      op: contains             # contains | equals | matches | not_contains
      value_from: action.new_role
  precondition:                # optional — pre-mutation state check
    - path: $.roles[*].name
      op: not_contains
      value_from: action.new_role
  side_effects:                # multi-assert — Codex blind-spot fix
    - layer: audit_log
      path: $.events[?(@.type == 'role_granted')].user_id
      op: contains
      value_from: action.target_user_id
    - layer: effective_permission
      path: $.can_access_admin
      op: equals
      value_from: derived_from_role
```

`cache_policy: no_store` — read MUST bypass HTTP cache + CDN. Default for role/permission/billing.
`settle.mode: immediate` — assert MUST hold at time of first read (read-your-writes guarantee). Use `poll` only with explicit business justification (e.g. async indexing).
`side_effects[]` — covers Codex blind spot: audit log, effective permission, tenant identity, auth cache.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rcrurd_invariant.py`:

```python
"""Tests for RCRURD invariant schema parser + serializer (Single Source of Truth)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "lib"


def test_minimal_invariant_parses(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariant  # type: ignore

    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: PATCH
            endpoint: /api/users/{userId}/roles
          read:
            method: GET
            endpoint: /api/users/{userId}
            cache_policy: no_store
            settle:
              mode: immediate
          assert:
            - path: $.roles[*].name
              op: contains
              value_from: action.new_role
    """).strip()

    inv = parse_yaml(yaml_doc)
    assert isinstance(inv, RCRURDInvariant)
    assert inv.write.method == "PATCH"
    assert inv.write.endpoint == "/api/users/{userId}/roles"
    assert inv.read.cache_policy == "no_store"
    assert inv.read.settle.mode == "immediate"
    assert len(inv.assertions) == 1
    assert inv.assertions[0].path == "$.roles[*].name"
    assert inv.assertions[0].op == "contains"
    assert inv.assertions[0].value_from == "action.new_role"
    sys.path.remove(str(LIB))


def test_eventual_consistency_requires_explicit_timeout(tmp_path: Path) -> None:
    """Codex blind-spot: eventual consistency must declare settle.timeout_ms."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read:
            method: GET
            endpoint: /api/x
            cache_policy: no_store
            settle:
              mode: poll
              # missing timeout_ms — must fail
          assert:
            - path: $.x
              op: equals
              value_from: action.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="timeout_ms"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_invalid_op_rejected(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert:
            - path: $.x
              op: looks_like_maybe   # invalid op
              value_from: action.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="op"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_side_effects_multi_assert_supported(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/{id}/roles}
          read:
            method: GET
            endpoint: /api/users/{id}
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles[*].name
              op: contains
              value_from: action.new_role
          side_effects:
            - layer: audit_log
              path: $.events[*].type
              op: contains
              value_from: literal:role_granted
            - layer: effective_permission
              path: $.can_access_admin
              op: equals
              value_from: literal:true
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.side_effects) == 2
    assert inv.side_effects[0].layer == "audit_log"
    assert inv.side_effects[1].layer == "effective_permission"
    sys.path.remove(str(LIB))


def test_round_trip_yaml_serialization(tmp_path: Path) -> None:
    """Parse → serialize → parse must produce identical structure."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, to_yaml  # type: ignore

    src = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read:
            method: GET
            endpoint: /api/x
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - {path: $.x, op: equals, value_from: action.x}
    """).strip()
    inv1 = parse_yaml(src)
    out = to_yaml(inv1)
    inv2 = parse_yaml(out)
    assert inv1.write.method == inv2.write.method
    assert inv1.assertions[0].path == inv2.assertions[0].path
    sys.path.remove(str(LIB))
```

- [ ] **Step 2: Write the schema + parser**

Create `schemas/rcrurd-invariant.schema.yaml`:

```yaml
$schema: "http://json-schema.org/draft-07/schema#"
title: RCRURDInvariant
description: |
  Read-after-write invariant for a mutation goal. Single source of truth
  consumed by review (Task 23) + codegen (Task 24). Authored in TEST-GOALS.md
  per mutation goal.

type: object
required: [goal_type, read_after_write_invariant]
properties:
  goal_type:
    type: string
    enum: [mutation]
  read_after_write_invariant:
    type: object
    required: [write, read, assert]
    properties:
      write:
        type: object
        required: [method, endpoint]
        properties:
          method:    {type: string, enum: [POST, PUT, PATCH, DELETE]}
          endpoint:  {type: string, pattern: "^/.*"}
      read:
        type: object
        required: [method, endpoint, cache_policy, settle]
        properties:
          method:        {type: string, enum: [GET]}
          endpoint:      {type: string, pattern: "^/.*"}
          cache_policy:  {type: string, enum: [no_store, cache_ok, bypass_cdn]}
          settle:
            type: object
            required: [mode]
            properties:
              mode:         {type: string, enum: [immediate, poll, wait_event]}
              timeout_ms:   {type: integer, minimum: 100, maximum: 60000}
              interval_ms:  {type: integer, minimum: 50, maximum: 5000}
      assert:
        type: array
        minItems: 1
        items: {$ref: "#/definitions/assertion"}
      precondition:
        type: array
        items: {$ref: "#/definitions/assertion"}
      side_effects:
        type: array
        items:
          allOf:
            - {$ref: "#/definitions/assertion"}
            - {type: object, required: [layer], properties: {layer: {type: string}}}

definitions:
  assertion:
    type: object
    required: [path, op, value_from]
    properties:
      path:        {type: string, pattern: "^\\$"}
      op:          {type: string, enum: [contains, equals, matches, not_contains]}
      value_from:  {type: string}
```

Create `scripts/lib/rcrurd_invariant.py`:

```python
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
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore


_VALID_OPS = {"contains", "equals", "matches", "not_contains"}
_VALID_CACHE = {"no_store", "cache_ok", "bypass_cdn"}
_VALID_SETTLE_MODE = {"immediate", "poll", "wait_event"}
_VALID_WRITE_METHOD = {"POST", "PUT", "PATCH", "DELETE"}


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
    layer: str | None = None  # populated only for side_effects entries


@dataclass(frozen=True)
class RCRURDInvariant:
    write: WriteSpec
    read: ReadSpec
    assertions: tuple[Assertion, ...]
    preconditions: tuple[Assertion, ...] = field(default=())
    side_effects: tuple[Assertion, ...] = field(default=())


def parse_yaml(yaml_text: str) -> RCRURDInvariant:
    """Parse a YAML invariant doc → typed RCRURDInvariant. Raises
    RCRURDInvariantError on any schema violation (clearer than jsonschema)."""
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise RCRURDInvariantError(f"yaml parse failed: {e}") from e

    if not isinstance(doc, dict):
        raise RCRURDInvariantError("top-level must be a mapping")
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

    return RCRURDInvariant(
        write=write, read=read, assertions=tuple(assertions),
        preconditions=tuple(preconditions), side_effects=tuple(side_effects),
    )


def _parse_write(d: Any) -> WriteSpec:
    if not isinstance(d, dict):
        raise RCRURDInvariantError("write must be a mapping")
    method = d.get("method")
    if method not in _VALID_WRITE_METHOD:
        raise RCRURDInvariantError(f"write.method must be one of {sorted(_VALID_WRITE_METHOD)}, got {method!r}")
    endpoint = d.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        raise RCRURDInvariantError(f"write.endpoint must start with '/', got {endpoint!r}")
    return WriteSpec(method=method, endpoint=endpoint)


def _parse_read(d: Any) -> ReadSpec:
    if not isinstance(d, dict):
        raise RCRURDInvariantError("read must be a mapping")
    method = d.get("method")
    if method != "GET":
        raise RCRURDInvariantError(f"read.method must be GET, got {method!r}")
    endpoint = d.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        raise RCRURDInvariantError(f"read.endpoint must start with '/', got {endpoint!r}")
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
    # Codex blind-spot: eventual consistency requires explicit timeout
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
    doc = {
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
```

- [ ] **Step 3: Run tests to verify**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -c "import yaml" 2>/dev/null || pip3 install pyyaml
python3 -m pytest tests/test_rcrurd_invariant.py -v
```
Expected: 5 passed.

- [ ] **Step 4: Update blueprint TEST-GOAL template + Rule 3b validator**

Edit `commands/vg/_shared/blueprint/contracts-delegation.md`. Find the existing `**Persistence check:**` block requirement (around line 190). After it, add:

```markdown
**Read-after-write invariant (REQUIRED for goal_type: mutation, Codex GPT-5.5 review 2026-05-03):**

For every mutation goal, append a fenced YAML block declaring the
structured invariant (single source of truth consumed by review +
codegen). Schema: `schemas/rcrurd-invariant.schema.yaml`.

Example:

````yaml-rcrurd
goal_type: mutation
read_after_write_invariant:
  write:
    method: PATCH
    endpoint: /api/users/{userId}/roles
  read:
    method: GET
    endpoint: /api/users/{userId}
    cache_policy: no_store
    settle: {mode: immediate}
  assert:
    - path: $.roles[*].name
      op: contains
      value_from: action.new_role
````

Mutation goals WITHOUT a structured invariant fail Rule 3b → blueprint
BLOCKED. The unstructured `**Persistence check:**` prose still required
for human readability, but the YAML block is the machine contract.
```

Edit `commands/vg/_shared/blueprint/contracts-overview.md`. Find the existing Rule 3b enforcement (around line 154 — search for "Persistence check"). Add after the prose check:

```bash
# Codex GPT-5.5 fix: structured invariant required, not just prose block
for goal_file in "${PHASE_DIR}/TEST-GOALS"/G-*.md; do
  if grep -qE "^\*\*goal_type:\*\*\s*mutation" "$goal_file"; then
    if ! "${PYTHON_BIN:-python3}" -c "
import sys
sys.path.insert(0, '.claude/scripts/lib')
from rcrurd_invariant import extract_from_test_goal_md
text = open('$goal_file').read()
inv = extract_from_test_goal_md(text)
sys.exit(0 if inv is not None else 1)
" 2>/dev/null; then
      echo "⛔ Rule 3b extended: $goal_file is mutation goal but missing structured read-after-write invariant"
      echo "   See contracts-delegation.md for required ```yaml-rcrurd``` block format"
      exit 1
    fi
  fi
done
```

- [ ] **Step 5: Commit**

```bash
git add schemas/rcrurd-invariant.schema.yaml \
        scripts/lib/rcrurd_invariant.py \
        tests/test_rcrurd_invariant.py \
        commands/vg/_shared/blueprint/contracts-delegation.md \
        commands/vg/_shared/blueprint/contracts-overview.md
git commit -m "feat(rcrurd): structured read-after-write invariant schema (single source of truth)

Codex GPT-5.5 review 2026-05-03: existing **Persistence check:** Markdown
block requirement is too coarse — accepts persistence_probe.persisted=true
without field/value comparison. Add structured YAML schema with cache_policy,
settle.timeout_ms (eventual consistency), assert+side_effects multi-layer.
Rule 3b extended: mutation goal must declare structured invariant.

Tasks 23 (review) + 24 (codegen) consume this parser — single source of
truth, no independent inference."
```
