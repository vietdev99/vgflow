<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 39: RCRURDR full lifecycle — extend rcrurd_invariant.py with `lifecycle_phases[]`

**Files:**
- Modify: `scripts/lib/rcrurd_invariant.py` (extend in place — no rename)
- Modify: `scripts/validators/verify-rcrurd-runtime.py` (consume lifecycle_phases)
- Modify: `scripts/codegen-helpers/expectReadAfterWrite.ts` (emit per-phase calls)
- Test: `tests/test_rcrurdr_lifecycle.py`

**Why:** Task 22 RCRURD invariant only handles ONE write+read cycle. Real lens-form-lifecycle pattern is **R-C-R-U-R-D-R** (Read empty → Create → Read populated → Update → Read updated → Delete → Read after delete) = 7 ops, 4 reads. Codex round-2 #55: extend in place (no rename) — preserves Task 23/24/25 callsites. Codex Gap H still open: state-machine parallel branches deferred to v4.

**Codex round-2 acceptance criteria** addressed: `goal_type → required_phases` enforcement, `ui_assert.apply_to_phase` keying, single-cycle `rcrurd` lifecycle stays default backward-compat.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rcrurdr_lifecycle.py`:

```python
"""Task 39 — RCRURDR 7-phase lifecycle schema + parser."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts/lib"


def test_legacy_single_cycle_still_parses(tmp_path: Path) -> None:
    """lifecycle: rcrurd (default) — backward compat."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: "/api/users/U"}
          read: {method: GET, endpoint: "/api/users/U", cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.email, op: equals, value_from: action.email}]
    """).strip()
    inv = parse_yaml(doc)
    # Default lifecycle is "rcrurd" (single cycle)
    assert inv.lifecycle == "rcrurd"
    assert inv.lifecycle_phases == ()
    sys.path.remove(str(LIB))


def test_rcrurdr_lifecycle_with_7_phases(tmp_path: Path) -> None:
    """lifecycle: rcrurdr requires lifecycle_phases[] with 7 entries."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users, op: equals, value_from: literal:[]}]
          - phase: create
            write: {method: POST, endpoint: "/api/users"}
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users[0].id, op: matches, value_from: "literal:^[a-f0-9-]{36}$"}]
          - phase: read_populated
            read: {method: GET, endpoint: "/api/users/{created_id}", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.id, op: equals, value_from: action.created_id}]
          - phase: update
            write: {method: PATCH, endpoint: "/api/users/{created_id}"}
            read: {method: GET, endpoint: "/api/users/{created_id}", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.email, op: equals, value_from: action.new_email}]
          - phase: read_updated
            read: {method: GET, endpoint: "/api/users/{created_id}", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.email, op: equals, value_from: action.new_email}]
          - phase: delete
            write: {method: DELETE, endpoint: "/api/users/{created_id}"}
            read: {method: GET, endpoint: "/api/users/{created_id}", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.error.code, op: equals, value_from: literal:NOT_FOUND}]
          - phase: read_after_delete
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users, op: equals, value_from: literal:[]}]
    """).strip()
    inv = parse_yaml(doc)
    assert inv.lifecycle == "rcrurdr"
    assert len(inv.lifecycle_phases) == 7
    phases = [p.phase for p in inv.lifecycle_phases]
    assert phases == [
        "read_empty", "create", "read_populated", "update",
        "read_updated", "delete", "read_after_delete",
    ]
    sys.path.remove(str(LIB))


def test_rcrurdr_missing_phases_rejected(tmp_path: Path) -> None:
    """RCRURDR with only 5 phases — rejected."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users, op: equals, value_from: literal:[]}]
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="lifecycle.*rcrurdr.*requires.*7"):
        parse_yaml(doc)
    sys.path.remove(str(LIB))


def test_create_only_goal_type_partial_lifecycle(tmp_path: Path) -> None:
    """goal_type: create_only requires phases [read_empty, create, read_populated]."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: create_only
        lifecycle: partial
        lifecycle_phases:
          - phase: read_empty
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users, op: equals, value_from: literal:[]}]
          - phase: create
            write: {method: POST, endpoint: "/api/users"}
            read: {method: GET, endpoint: "/api/users", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.users[0].id, op: matches, value_from: "literal:.+"}]
          - phase: read_populated
            read: {method: GET, endpoint: "/api/users/{created_id}", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.id, op: equals, value_from: action.created_id}]
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.lifecycle_phases) == 3
    sys.path.remove(str(LIB))


def test_ui_assert_apply_to_phase_keying(tmp_path: Path) -> None:
    """ui_assert ops must specify apply_to_phase when lifecycle: rcrurdr."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: equals, value_from: literal:[]}]
          - phase: create
            write: {method: POST, endpoint: "/api/x"}
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: contains, value_from: action.new}]
          - phase: read_populated
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: contains, value_from: action.new}]
          - phase: update
            write: {method: PATCH, endpoint: "/api/x"}
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: contains, value_from: action.new}]
          - phase: read_updated
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: contains, value_from: action.new}]
          - phase: delete
            write: {method: DELETE, endpoint: "/api/x"}
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: equals, value_from: literal:[]}]
          - phase: read_after_delete
            read: {method: GET, endpoint: "/api/x", cache_policy: no_store, settle: {mode: immediate}}
            assert: [{path: $.x, op: equals, value_from: literal:[]}]
        ui_assert:
          apply_to_phase: read_populated
          settle: {timeout_ms: 3000}
          ops:
            - op: text_equals_response_value
              dom_selector: '[data-testid="x-display"]'
              response_path: $.x[0]
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert.apply_to_phase == "read_populated"
    sys.path.remove(str(LIB))
```

- [ ] **Step 2: Run failing tests**

Expected: 5 failures (lifecycle field + lifecycle_phases array not yet in schema).

- [ ] **Step 3: Extend rcrurd_invariant.py**

Edit `scripts/lib/rcrurd_invariant.py`. Add field `lifecycle: str = "rcrurd"` to `RCRURDInvariant`. Add nested `LifecyclePhase` dataclass. Update `parse_yaml` to handle `lifecycle: rcrurdr` + `lifecycle: partial` paths. Add validation:

```python
_VALID_LIFECYCLE = {"rcrurd", "rcrurdr", "partial"}
_VALID_PHASE_NAMES = {
    "read_empty", "create", "read_populated", "update",
    "read_updated", "delete", "read_after_delete",
}
_RCRURDR_REQUIRED_PHASES = (
    "read_empty", "create", "read_populated", "update",
    "read_updated", "delete", "read_after_delete",
)
_GOAL_TYPE_REQUIRED_PHASES = {
    "create_only": ("read_empty", "create", "read_populated"),
    "update_only": ("read_populated", "update", "read_updated"),
    "delete_only": ("read_populated", "delete", "read_after_delete"),
    "crud_full": _RCRURDR_REQUIRED_PHASES,
}


@dataclass(frozen=True)
class LifecyclePhase:
    phase: str  # one of _VALID_PHASE_NAMES
    write: WriteSpec | None  # None for read-only phases (read_empty, read_populated, etc)
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
    # NEW Task 39 fields:
    lifecycle: str = "rcrurd"
    lifecycle_phases: tuple[LifecyclePhase, ...] = field(default=())


def _parse_lifecycle_phases(items: Any, lifecycle: str, goal_type: str) -> list[LifecyclePhase]:
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

        # Read phases: read-only, no write
        is_read_only_phase = phase.startswith("read_")
        write = None if is_read_only_phase else _parse_write(d.get("write"))
        read = _parse_read(d.get("read"))
        assertions = _parse_assert_list(d.get("assert"), f"{ctx}.assert", min_items=1)
        phases.append(LifecyclePhase(
            phase=phase, write=write, read=read, assertions=tuple(assertions),
        ))

    # Validate completeness per lifecycle/goal_type
    if lifecycle == "rcrurdr":
        if seen_names != set(_RCRURDR_REQUIRED_PHASES):
            missing = set(_RCRURDR_REQUIRED_PHASES) - seen_names
            raise RCRURDInvariantError(
                f"lifecycle: rcrurdr requires all 7 phases; missing: {sorted(missing)}"
            )
    elif lifecycle == "partial":
        required = _GOAL_TYPE_REQUIRED_PHASES.get(goal_type)
        if required and seen_names != set(required):
            missing = set(required) - seen_names
            raise RCRURDInvariantError(
                f"goal_type: {goal_type} (lifecycle: partial) requires phases "
                f"{required}; missing: {sorted(missing)}"
            )

    return phases


# In parse_yaml(), after existing parsing:
def parse_yaml(yaml_text: str) -> RCRURDInvariant:
    # ...existing logic...
    lifecycle = doc.get("lifecycle", "rcrurd")
    if lifecycle not in _VALID_LIFECYCLE:
        raise RCRURDInvariantError(f"lifecycle must be one of {_VALID_LIFECYCLE}, got {lifecycle!r}")

    if lifecycle == "rcrurd":
        # Legacy path: read_after_write_invariant
        # ...existing parsing...
        return RCRURDInvariant(
            write=write, read=read, assertions=tuple(assertions),
            preconditions=tuple(preconditions), side_effects=tuple(side_effects),
            ui_assert=ui_assert, lifecycle="rcrurd", lifecycle_phases=(),
        )

    # New paths: rcrurdr or partial
    goal_type = doc.get("goal_type", "mutation")
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
```

Also add `apply_to_phase: str | None = None` field to `UIAssertBlock`.

- [ ] **Step 4: Update Task 23 review-runtime gate**

Edit `scripts/validators/verify-rcrurd-runtime.py`. When `inv.lifecycle == "rcrurdr"` (or "partial"), iterate `inv.lifecycle_phases` and run write+read+assert per phase. Legacy single-cycle path stays for `inv.lifecycle == "rcrurd"`.

- [ ] **Step 5: Update Task 24 codegen helper**

Edit `scripts/codegen-helpers/expectReadAfterWrite.ts`. Add `expectLifecycleRoundtrip(invariant: RCRURDInvariant, page, request)` helper. When `lifecycle: rcrurdr`, iterate phases and emit per-phase write+read+assert calls.

- [ ] **Step 5.5: Register `2b8_rcrurdr_invariants` blueprint step + telemetry event (Codex round-3 S9 + S10 fix)**

Spec architecture summary line 732 + Bug G migration plan reference a
`2b8_rcrurdr_invariants` step that emits per-goal RCRURD invariants
during blueprint. Without registering it in the slim entry, downstream
artifacts (Task 40 references `RCRURD-INVARIANTS/` path) won't get
populated and Stop hook silent-skips the missing event.

Edit `commands/vg/blueprint.md`:

1. Add to `steps:` block, AFTER `2b7_flow_detect` (line 113):

```yaml
    # Task 39 (Bug G) — emit per-goal RCRURD invariants from extracted
    # ```yaml-rcrurd``` fences in TEST-GOALS/G-NN.md. Optional skip:
    # --skip-rcrurdr (with --override-reason) for phases without crud goals.
    - name: "2b8_rcrurdr_invariants"
      severity: "warn"
      required_unless_flag: "--skip-rcrurdr"
```

2. Append to `must_emit_telemetry:` block (spec line 786):

```yaml
    # Task 39 — RCRURDR per-goal invariant emission (Bug G)
    - event_type: "blueprint.rcrurdr_invariant_emitted"
      phase: "${PHASE_NUMBER}"
      severity: "info"
```

3. Add `--skip-rcrurdr` to the `forbidden_without_override` list
   alongside `--skip-edge-cases` / `--skip-lens-walk` etc.

4. Add `rcrurdr-invariants` to the valid `--only=<step>` enum (Task 38's
   `<only-step-list>` block) — it's listed there but Task 38 wrote it
   pointing at "Task 39 RCRURDR generator"; this Step now ensures the
   step it references exists.

Add a test to `tests/test_rcrurdr_lifecycle.py`:

```python
def test_blueprint_md_registers_2b8_rcrurdr_step() -> None:
    text = (REPO / "commands/vg/blueprint.md").read_text(encoding="utf-8")
    assert "2b8_rcrurdr_invariants" in text, \
        "blueprint.md must register 2b8_rcrurdr_invariants step (Task 39 / Bug G)"
    assert "blueprint.rcrurdr_invariant_emitted" in text, \
        "blueprint.md must declare blueprint.rcrurdr_invariant_emitted telemetry event"
```

- [ ] **Step 6: Run tests + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_rcrurdr_lifecycle.py tests/test_rcrurd_invariant.py tests/test_rcrurd_runtime.py -v
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/lib/rcrurd_invariant.py \
        scripts/validators/verify-rcrurd-runtime.py \
        scripts/codegen-helpers/expectReadAfterWrite.ts \
        commands/vg/blueprint.md \
        tests/test_rcrurdr_lifecycle.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(rcrurd): R-C-R-U-R-D-R full lifecycle (Task 39, Bug G)

Codex round-2 #55-58: extend rcrurd_invariant.py in place (no rename) so
Tasks 23/24/25 callsites stay compatible.

NEW schema field 'lifecycle': discriminator ∈ {rcrurd, rcrurdr, partial}.
- rcrurd (default, backward-compat) — existing single-cycle path
- rcrurdr — requires lifecycle_phases[] with all 7 phases:
  read_empty → create → read_populated → update → read_updated →
  delete → read_after_delete
- partial — for goal_type ∈ {create_only, update_only, delete_only,
  crud_full}; requires phases per _GOAL_TYPE_REQUIRED_PHASES table

NEW LifecyclePhase dataclass: per-phase write+read+assert + phase name.
Read phases (read_empty, etc) have write=None.

ui_assert gains apply_to_phase: str field — pins DOM assertions to a
specific lifecycle phase (e.g. read_populated). Backward-compat: when
lifecycle=rcrurd, defaults to the single read.

Tasks 23 (review runtime) + 24 (codegen) updated to iterate lifecycle_phases
when lifecycle=rcrurdr; legacy path preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
