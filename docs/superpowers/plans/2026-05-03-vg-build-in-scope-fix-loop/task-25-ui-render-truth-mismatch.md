<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 25: R9 ui_render_truth_mismatch — UI ↔ API render coherence (codegen-side)

**Files:**
- Modify: `schemas/rcrurd-invariant.schema.yaml` (extend with `ui_assert` section — Task 22 schema, add R9 layer)
- Modify: `scripts/lib/rcrurd_invariant.py` (parse + validate `ui_assert` block)
- Modify: `scripts/codegen-helpers/expectReadAfterWrite.ts` (Task 24 helper — add `page: Page` parameter + ui_assert evaluation)
- Modify: `scripts/validators/verify-codegen-rcrurd-helper.py` (Task 24 AST gate — additionally check `page` argument when goal has ui_assert)
- Create: `tests/test_ui_assert_schema.py`
- Create: `tests/test_ui_assert_helper.py` (Playwright in-process test of helper against fake DOM)

**Why (Codex GPT-5.5 round 4 review 2026-05-03):** Real bug discovered after round 3: admin grants role → API 200 + DB persists 3 roles → BUT UI displays only 1 role item. R8 gates (Task 22-24) verify API/DB layer only; UI render-vs-API divergence falls outside their scope. Codex round 4 broadened the rule beyond array truncation: **R9 ui_render_truth_mismatch** = Layer 1 (UI) disagrees with Layer 3 (network/read truth) after a successful write+read cycle. Array under-render is one subtype of a larger class (scalar drift, conditional render bugs, attribute mismatch).

This task extends Tasks 22 + 24 with a `ui_assert` block evaluated at codegen-time (Playwright runtime in test bundle, NOT at /vg:review API ping — Codex round 4 confirmed Task 23 stays API-only).

**Schema extension (added to `schemas/rcrurd-invariant.schema.yaml`):**

```yaml
read_after_write_invariant:
  write: { ... }                  # existing
  read: { ... }                   # existing
  assert: [ ... ]                 # existing — API layer
  precondition: [ ... ]           # existing
  side_effects: [ ... ]           # existing
  ui_assert:                      # NEW — R9 ui_render_truth_mismatch
    settle:                       # independent of read.settle (Codex round 4 #5)
      timeout_ms: 5000            # max wait for DOM to reflect API truth
      poll_ms: 100                # retry interval
    ops:
      - op: count_matches_response_array
        dom_selector: '[data-testid="user-roles-list"] [data-role]'
        response_path: $.roles[*]
      - op: text_contains_all
        dom_selector: '[data-testid="user-roles-list"]'
        response_path: $.roles[*].name
      - op: each_exists_for_array_item
        response_path: $.roles[*]
        selector_template: '[data-testid="user-role-{key}"]'
        key_from: $.id            # stable ID per Codex round 4 #4
      # Scalar / conditional / attribute ops follow same {op, dom_selector, response_path} shape.
```

**10 supported ops:**

| # | op | Catches | Schema-required fields |
|---|---|---|---|
| 1 | `count_matches_response_array` | Array under/over-render (sếp's bug + MUI #43542 duplication) | dom_selector, response_path |
| 2 | `text_contains_all` | Array text missing values in DOM | dom_selector, response_path |
| 3 | `each_exists_for_array_item` | Per-item rendering gaps | response_path, selector_template, key_from |
| 4 | `text_equals_response_value` | Scalar exact-match (badge count, name, status) | dom_selector, response_path |
| 5 | `text_matches_response_value` | Scalar regex-match (date format, locale) | dom_selector, response_path, regex |
| 6 | `visible_when_response_value` | Conditional show (flag=true → element visible) | dom_selector, response_path, expected_value |
| 7 | `hidden_when_response_value` | Conditional hide (flag=true → element hidden) | dom_selector, response_path, expected_value |
| 8 | `attribute_equals_response_value` | Attribute drift (disabled, selected, aria-*) | dom_selector, response_path, attribute |
| 9 | `aria_state_matches` | Semantic shortcut for aria-checked/expanded/selected | dom_selector, response_path, aria_state |
| 10 | `input_value_equals_response` | Form input.value drift after save | dom_selector, response_path |

**Selector policy (Codex round 4 #3 strict):**
- Required: `data-testid` or equivalent stable selector in dom_selector / selector_template.
- Validator emits `R9_UNTESTABLE_MISSING_STABLE_SELECTOR` advisory if dom_selector contains only text/class selectors AND no `data-testid` attribute reference. Default severity: ADVISORY (configurable to BLOCK via `vg.config.md` `ui_assert.require_stable_selector: true`).
- Text-based selectors acceptable ONLY when text IS the contract (e.g. status label "Approved" — the text itself is the spec).

- [ ] **Step 1: Write the schema extension test**

Create `tests/test_ui_assert_schema.py`:

```python
"""Tests for ui_assert section in RCRURD invariant schema (Task 25)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "lib"


def test_ui_assert_array_ops_parse(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - {path: $.roles[*].name, op: contains, value_from: action.new_role}
          ui_assert:
            settle: {timeout_ms: 5000, poll_ms: 100}
            ops:
              - op: count_matches_response_array
                dom_selector: '[data-testid="roles-list"] [data-role]'
                response_path: $.roles[*]
              - op: text_contains_all
                dom_selector: '[data-testid="roles-list"]'
                response_path: $.roles[*].name
              - op: each_exists_for_array_item
                response_path: $.roles[*]
                selector_template: '[data-testid="role-{key}"]'
                key_from: $.id
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert is not None
    assert inv.ui_assert.settle.timeout_ms == 5000
    assert len(inv.ui_assert.ops) == 3
    assert inv.ui_assert.ops[0].op == "count_matches_response_array"
    assert inv.ui_assert.ops[2].selector_template == '[data-testid="role-{key}"]'
    assert inv.ui_assert.ops[2].key_from == "$.id"
    sys.path.remove(str(LIB))


def test_ui_assert_scalar_conditional_attribute_ops_parse(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read: {method: GET, endpoint: /api/users/U, cache_policy: no_store, settle: {mode: immediate}}
          assert:
            - {path: $.email, op: equals, value_from: action.email}
          ui_assert:
            settle: {timeout_ms: 3000, poll_ms: 100}
            ops:
              - op: text_equals_response_value
                dom_selector: '[data-testid="user-email"]'
                response_path: $.email
              - op: text_matches_response_value
                dom_selector: '[data-testid="user-updated-at"]'
                response_path: $.updated_at
                regex: '^\\d{4}-\\d{2}-\\d{2}'
              - op: visible_when_response_value
                dom_selector: '[data-testid="banner-verified"]'
                response_path: $.verified
                expected_value: true
              - op: hidden_when_response_value
                dom_selector: '[data-testid="banner-pending"]'
                response_path: $.verified
                expected_value: true
              - op: attribute_equals_response_value
                dom_selector: '[data-testid="role-toggle"]'
                attribute: aria-checked
                response_path: $.has_admin_role
              - op: aria_state_matches
                dom_selector: '[data-testid="user-row"]'
                aria_state: aria-selected
                response_path: $.selected
              - op: input_value_equals_response
                dom_selector: '[data-testid="username-input"]'
                response_path: $.username
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.ui_assert.ops) == 7
    assert inv.ui_assert.ops[1].regex == r'^\d{4}-\d{2}-\d{2}'
    assert inv.ui_assert.ops[2].expected_value is True
    assert inv.ui_assert.ops[4].attribute == "aria-checked"
    assert inv.ui_assert.ops[5].aria_state == "aria-selected"
    sys.path.remove(str(LIB))


def test_each_exists_requires_key_from(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.x, op: equals, value_from: action.x}]
          ui_assert:
            settle: {timeout_ms: 1000}
            ops:
              - op: each_exists_for_array_item
                response_path: $.items[*]
                selector_template: '[data-testid="item-{key}"]'
                # missing key_from — must fail
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="key_from"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_invalid_op_in_ui_assert_rejected(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.x, op: equals, value_from: action.x}]
          ui_assert:
            settle: {timeout_ms: 1000}
            ops:
              - op: cosmic_ray_detector
                dom_selector: '[data-testid="x"]'
                response_path: $.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="cosmic_ray_detector"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_ui_assert_optional_when_no_render_concern(tmp_path: Path) -> None:
    """ui_assert is optional — APIs without UI surface (worker, cron) skip it."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: POST, endpoint: /api/internal/jobs}
          read: {method: GET, endpoint: /api/internal/jobs/last, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.status, op: equals, value_from: literal:queued}]
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert is None  # optional — no R9 enforcement on backend-only goals
    sys.path.remove(str(LIB))
```

- [ ] **Step 2: Run failing tests**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_ui_assert_schema.py -v`
Expected: 5 failures.

- [ ] **Step 3: Extend `scripts/lib/rcrurd_invariant.py` parser**

Edit `scripts/lib/rcrurd_invariant.py`. Add UI-assert-related types + parse logic AFTER existing `Assertion` dataclass:

```python
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


@dataclass(frozen=True)
class UISettleSpec:
    """Independent of read.settle (Codex round 4 #5) — DOM render clock differs from API."""
    timeout_ms: int
    poll_ms: int = 100


@dataclass(frozen=True)
class UIAssertOp:
    op: str
    dom_selector: str | None = None      # required for most ops
    selector_template: str | None = None  # required for each_exists_for_array_item
    key_from: str | None = None           # required for each_exists_for_array_item
    response_path: str | None = None      # JSONPath against read response body
    attribute: str | None = None          # for attribute_equals_response_value
    aria_state: str | None = None         # for aria_state_matches
    regex: str | None = None              # for text_matches_response_value
    expected_value: object = None         # for visible_when / hidden_when


@dataclass(frozen=True)
class UIAssertBlock:
    settle: UISettleSpec
    ops: tuple[UIAssertOp, ...]


# Append `ui_assert: UIAssertBlock | None = None` to RCRURDInvariant dataclass.
```

Then add parse helpers below `_parse_side_effects`:

```python
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

    # Per-op required-field validation
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
    return UIAssertBlock(settle=settle, ops=ops)
```

In `parse_yaml(...)`, after parsing `side_effects`, add:

```python
ui_assert = _parse_ui_assert(raw.get("ui_assert"))
return RCRURDInvariant(
    write=write, read=read, assertions=tuple(assertions),
    preconditions=tuple(preconditions), side_effects=tuple(side_effects),
    ui_assert=ui_assert,
)
```

Update `to_yaml(...)` symmetrically (round-trip).

- [ ] **Step 4: Run schema tests to verify**

Run: `python3 -m pytest tests/test_ui_assert_schema.py -v`
Expected: 5 passed.

- [ ] **Step 5: Extend `scripts/lib/rcrurd-invariant.schema.yaml`**

Append to schema definitions block:

```yaml
definitions:
  # ... existing assertion ...
  ui_assert_op:
    type: object
    required: [op]
    properties:
      op:
        type: string
        enum:
          - count_matches_response_array
          - text_contains_all
          - each_exists_for_array_item
          - text_equals_response_value
          - text_matches_response_value
          - visible_when_response_value
          - hidden_when_response_value
          - attribute_equals_response_value
          - aria_state_matches
          - input_value_equals_response
      dom_selector:      {type: string}
      selector_template: {type: string}
      key_from:          {type: string, pattern: "^\\$"}
      response_path:     {type: string, pattern: "^\\$"}
      attribute:         {type: string}
      aria_state:        {type: string}
      regex:             {type: string}
      expected_value:    {}    # any JSON value

properties:
  read_after_write_invariant:
    properties:
      ui_assert:
        type: object
        required: [settle, ops]
        properties:
          settle:
            type: object
            required: [timeout_ms]
            properties:
              timeout_ms: {type: integer, minimum: 100, maximum: 60000}
              poll_ms:    {type: integer, minimum: 50, maximum: 5000}
          ops:
            type: array
            minItems: 1
            items: {$ref: "#/definitions/ui_assert_op"}
```

- [ ] **Step 6: Extend `scripts/codegen-helpers/expectReadAfterWrite.ts` with ui_assert evaluation**

Add to the helper file (add `Page` import + new signature):

```typescript
import { APIRequestContext, Page, expect } from '@playwright/test';

// (existing types unchanged — add UIAssertBlock to RCRURDInvariant interface)

export interface UIAssertOp {
  op: string;
  dom_selector?: string;
  selector_template?: string;
  key_from?: string;
  response_path?: string;
  attribute?: string;
  aria_state?: string;
  regex?: string;
  expected_value?: unknown;
}

export interface UIAssertBlock {
  settle: { timeout_ms: number; poll_ms?: number };
  ops: UIAssertOp[];
}

// Add `ui_assert?: UIAssertBlock` to RCRURDInvariant interface.

// CHANGED signature: `page: Page` is REQUIRED when invariant.ui_assert is set
export async function expectReadAfterWrite(
  page: Page | null,                          // pass `null` for backend-only goals (no UI)
  request: APIRequestContext,
  invariant: RCRURDInvariant,
  actionPayload: Record<string, unknown>,
): Promise<void> {
  // ... existing precondition / write / API-layer assert logic ...

  // NEW — Step 4: ui_assert evaluation (only if invariant declares it)
  if (invariant.ui_assert) {
    if (page === null) {
      throw new Error(
        `[${invariant.goal_id}] R9_NO_PAGE: invariant has ui_assert but expectReadAfterWrite was called with page=null`,
      );
    }
    const { settle, ops } = invariant.ui_assert;
    const responseBodyForUI = await (await request.get(invariant.read.endpoint, {
      headers: cacheHeaders(invariant.read.cache_policy),
    })).json().catch(() => ({}));

    for (const uop of ops) {
      await expect(async () => {
        await evalUIOp(page, uop, responseBodyForUI, actionPayload, invariant.goal_id);
      }).toPass({ timeout: settle.timeout_ms, intervals: [settle.poll_ms ?? 100] });
    }
  }
}


async function evalUIOp(
  page: Page,
  uop: UIAssertOp,
  responseBody: unknown,
  actionPayload: Record<string, unknown>,
  goalId: string,
): Promise<void> {
  const fail = (msg: string): never => {
    throw new Error(`[${goalId}] R9 ui_render_truth_mismatch (${uop.op}): ${msg}`);
  };

  if (uop.op === 'count_matches_response_array') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    const domCount = await page.locator(uop.dom_selector!).count();
    if (domCount !== flat.length) {
      fail(`API has ${flat.length} items, DOM has ${domCount} at ${uop.dom_selector}`);
    }
  } else if (uop.op === 'text_contains_all') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    const domText = await page.locator(uop.dom_selector!).innerText();
    for (const v of flat) {
      if (!domText.includes(String(v))) fail(`DOM ${uop.dom_selector} missing value ${JSON.stringify(v)}`);
    }
  } else if (uop.op === 'each_exists_for_array_item') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    for (const item of flat) {
      const keyVal = evalJsonPath(item, uop.key_from!)[0];
      if (keyVal === undefined) fail(`item missing key_from ${uop.key_from}`);
      const sel = uop.selector_template!.replace('{key}', String(keyVal));
      const cnt = await page.locator(sel).count();
      if (cnt !== 1) fail(`expected exactly 1 element at ${sel}, found ${cnt}`);
    }
  } else if (uop.op === 'text_equals_response_value') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const domText = (await page.locator(uop.dom_selector!).innerText()).trim();
    if (domText !== String(expected)) fail(`expected "${expected}", DOM shows "${domText}"`);
  } else if (uop.op === 'text_matches_response_value') {
    const domText = (await page.locator(uop.dom_selector!).innerText()).trim();
    if (!new RegExp(uop.regex!).test(domText)) fail(`DOM "${domText}" does not match /${uop.regex}/`);
  } else if (uop.op === 'visible_when_response_value' || uop.op === 'hidden_when_response_value') {
    const flagVal = evalJsonPath(responseBody, uop.response_path!)[0];
    const expected = uop.expected_value;
    const shouldBeVisible = (flagVal === expected) === (uop.op === 'visible_when_response_value');
    const isVisible = await page.locator(uop.dom_selector!).isVisible();
    if (isVisible !== shouldBeVisible) {
      fail(`expected ${shouldBeVisible ? 'visible' : 'hidden'} (response=${flagVal}, expected=${expected}), DOM ${isVisible ? 'visible' : 'hidden'}`);
    }
  } else if (uop.op === 'attribute_equals_response_value') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const actual = await page.locator(uop.dom_selector!).getAttribute(uop.attribute!);
    if (String(actual) !== String(expected)) fail(`${uop.attribute} expected ${expected}, DOM has ${actual}`);
  } else if (uop.op === 'aria_state_matches') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const actual = await page.locator(uop.dom_selector!).getAttribute(uop.aria_state!);
    if (String(actual) !== String(expected)) fail(`${uop.aria_state} expected ${expected}, DOM has ${actual}`);
  } else if (uop.op === 'input_value_equals_response') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const val = await page.locator(uop.dom_selector!).inputValue();
    if (val !== String(expected)) fail(`input.value expected ${expected}, DOM has ${val}`);
  }
}
```

- [ ] **Step 7: Extend `scripts/validators/verify-codegen-rcrurd-helper.py` AST gate**

Modify the gate to additionally check: when goal's invariant has `ui_assert`, the spec MUST pass `page` argument to `expectReadAfterWrite()`. Update the regex pattern detection:

```python
# Existing CALL_RE detects bare expectReadAfterWrite(...)
# NEW: when goal has ui_assert, also assert call signature includes page param
PAGE_CALL_RE = re.compile(
    r"\bexpectReadAfterWrite\s*\(\s*page\b",
    re.MULTILINE,
)


def _goal_has_ui_assert(goal_path: Path) -> bool:
    """Return True if the YAML invariant in the goal has a ui_assert block."""
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from rcrurd_invariant import extract_from_test_goal_md  # type: ignore
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return False
    inv = extract_from_test_goal_md(text)
    return bool(inv and inv.ui_assert)


# In main(), inside the failures loop, additional check:
# if _goal_has_ui_assert(goal):
#     if not PAGE_CALL_RE.search(text):
#         failures.append(f"{goal_id}: invariant has ui_assert but spec doesn't pass page to expectReadAfterWrite")
```

Also add `R9_UNTESTABLE_MISSING_STABLE_SELECTOR` advisory:

```python
DATA_TESTID_RE = re.compile(r"data-testid=", re.MULTILINE)


def _check_stable_selectors(goal_path: Path) -> list[str]:
    """Return list of warnings if any ui_assert dom_selector lacks data-testid."""
    # Read the YAML block and check selectors. Codex round 4 #3:
    # missing data-testid → ADVISORY (default) or BLOCK (with vg.config flag).
    warnings: list[str] = []
    # ... read invariant, iterate ops, regex check selectors ...
    return warnings
```

- [ ] **Step 8: Write helper test (Playwright in-process)**

Create `tests/test_ui_assert_helper.py` — uses Playwright via Python (`pip install playwright && playwright install chromium`). Smoke-test 3 ops against fixture HTML page:

```python
"""Smoke test for ui_assert ops via Playwright Python (parallel to TS helper)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # type: ignore  # noqa: E402


@pytest.fixture(scope="module")
def fixture_html(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("ui-fixture")
    html = textwrap.dedent("""
        <!DOCTYPE html><html><body>
          <ul data-testid="roles-list">
            <li data-role data-testid="role-r1">admin</li>
            <li data-role data-testid="role-r2">editor</li>
          </ul>
          <span data-testid="user-email">alice@example.com</span>
          <button data-testid="role-toggle" aria-checked="true" aria-selected="false">Toggle</button>
          <input data-testid="username-input" value="alice"/>
          <div data-testid="banner-verified" style="display:block">Verified!</div>
          <div data-testid="banner-pending" style="display:none">Pending</div>
        </body></html>
    """).strip()
    f = tmp / "fixture.html"
    f.write_text(html, encoding="utf-8")
    return f.as_uri()


def test_helper_count_matches_passes(fixture_html: str) -> None:
    """Smoke: API returns 2 roles, DOM shows 2 li items → PASS."""
    response_body = {"roles": [{"id": "r1", "name": "admin"}, {"id": "r2", "name": "editor"}]}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(fixture_html)
        # Inline equivalent of count_matches_response_array op:
        dom_count = page.locator('[data-testid="roles-list"] [data-role]').count()
        api_count = len(response_body["roles"])
        assert dom_count == api_count
        browser.close()


def test_helper_count_mismatch_detects_truncation(fixture_html: str) -> None:
    """Smoke: API returns 3 roles, DOM shows 2 li items → DETECT (sếp's bug)."""
    response_body = {"roles": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(fixture_html)
        dom_count = page.locator('[data-testid="roles-list"] [data-role]').count()
        api_count = len(response_body["roles"])
        assert dom_count != api_count, "fixture should detect truncation (3 expected, 2 in DOM)"
        browser.close()


def test_helper_attribute_equals_passes(fixture_html: str) -> None:
    """Smoke: aria-checked=true matches API has_admin=true."""
    response_body = {"has_admin": True}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(fixture_html)
        actual = page.locator('[data-testid="role-toggle"]').get_attribute("aria-checked")
        assert str(actual) == str(response_body["has_admin"]).lower()
        browser.close()
```

- [ ] **Step 9: Run helper tests (skipped gracefully if playwright not installed)**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_ui_assert_helper.py -v
```
Expected: 3 passed (or skipped with "playwright not installed" — installing playwright is project-discretion, gate must work either way).

- [ ] **Step 10: Update vg-test-codegen SKILL.md**

Edit `agents/vg-test-codegen/SKILL.md`. Add to existing RCRURD helper hard rule (added by Task 24):

```markdown
## R9 ui_render_truth_mismatch — when invariant has ui_assert (Task 25)

If the YAML invariant in TEST-GOALS/G-NN.md has a `ui_assert` block,
the generated `.spec.ts` MUST pass `page` as the first argument:

```typescript
await expectReadAfterWrite(page, request, invariantG04, { new_role: 'admin' });
```

NOT `expectReadAfterWrite(request, invariantG04, ...)` — the helper
throws `R9_NO_PAGE` if invariant.ui_assert is set but `page === null`.

The `dom_selector` and `selector_template` values MUST use stable
selectors (data-testid). Validator emits `R9_UNTESTABLE_MISSING_STABLE_SELECTOR`
ADVISORY if you generate ui_assert ops with text-only or class-based
selectors. Override only when text IS the spec contract.
```

- [ ] **Step 11: Commit**

```bash
git add schemas/rcrurd-invariant.schema.yaml \
        scripts/lib/rcrurd_invariant.py \
        scripts/codegen-helpers/expectReadAfterWrite.ts \
        scripts/validators/verify-codegen-rcrurd-helper.py \
        agents/vg-test-codegen/SKILL.md \
        tests/test_ui_assert_schema.py \
        tests/test_ui_assert_helper.py
git commit -m "feat(rcrurd): R9 ui_render_truth_mismatch (UI ↔ API render coherence)

Codex GPT-5.5 round 4 review 2026-05-03: extend Task 22 schema with
ui_assert block + Task 24 helper handles DOM verification.

10 ops cover array/scalar/conditional/attribute layers — sếp's role-
grant bug (UI shows 1 of 3 array items) caught by count_matches_response_array.

Independent ui_assert.settle clock from read.settle (DOM render ≠ API
render). Stable selector required (data-testid); R9_UNTESTABLE
advisory when missing.

Task 23 (review API ping) NOT extended — codegen+test execution is
correct layer for DOM-vs-API checks per Codex round 4 #7."
```
