<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 24: Codegen read-after-write helper + AST gate (build-side)

**Files:**
- Create: `scripts/codegen-helpers/expectReadAfterWrite.ts` (Playwright helper for generated specs)
- Create: `scripts/validators/verify-codegen-rcrurd-helper.py` (AST gate — verifies generated specs use the helper)
- Create: `tests/test_codegen_rcrurd_helper.py`
- Modify: `commands/vg/_shared/test/codegen/delegation.md` (vg-test-codegen MUST emit `expectReadAfterWrite()` for every mutation step, reading from Task 22 parser output)
- Modify: `agents/vg-test-codegen/SKILL.md` (Hard rule: every mutation goal in TEST-GOALS produces ≥1 `expectReadAfterWrite()` call in spec)

**Why (Codex GPT-5.5 review 2026-05-03):** VG codegen has `mutation-layers.py` regex check requiring toast + API + reload + console layers — but it doesn't prove `GET /api/users/:id.roles contains new role`. Generic regex for "GET-after-mutation" is brittle (false positives on unrelated GETs, false negatives on indirect verification). Codex prescription: **require generated specs to call a known helper `expectReadAfterWrite(request, invariant)` and AST-check that each mutation goal imports/calls that helper with the correct invariant ID.**

This is the **codegen consumer** of Task 22's single source of truth: helper accepts the structured invariant; codegen subagent emits one helper call per mutation goal; AST validator confirms the call exists with the correct invariant binding.

**Helper design:**

The helper at runtime mirrors what `verify-rcrurd-runtime.py` does in review (Task 23): write → cache-aware read → JSONPath assert. But it lives in the test bundle, runs in Playwright, and produces test-failure output (not BuildWarningEvidence JSON).

```typescript
// scripts/codegen-helpers/expectReadAfterWrite.ts
import { APIRequestContext, expect } from '@playwright/test';

export interface RCRURDInvariant {
  goal_id: string;
  write: { method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; endpoint: string };
  read: {
    method: 'GET';
    endpoint: string;
    cache_policy: 'no_store' | 'cache_ok' | 'bypass_cdn';
    settle: { mode: 'immediate' | 'poll' | 'wait_event'; timeout_ms?: number; interval_ms?: number };
  };
  assert: Array<{ path: string; op: 'contains' | 'equals' | 'matches' | 'not_contains'; value_from: string }>;
  precondition?: Array<{ path: string; op: string; value_from: string }>;
  side_effects?: Array<{ layer: string; path: string; op: string; value_from: string }>;
}

export async function expectReadAfterWrite(
  request: APIRequestContext,
  invariant: RCRURDInvariant,
  actionPayload: Record<string, unknown>,
): Promise<void> {
  // (full body in Step 3 below — keeping plan readable)
}
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_codegen_rcrurd_helper.py`:

```python
"""Tests for verify-codegen-rcrurd-helper.py — AST gate against generated specs."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-codegen-rcrurd-helper.py"


def test_spec_with_helper_call_passes(tmp_path: Path) -> None:
    """Generated spec calls expectReadAfterWrite — must PASS."""
    spec = tmp_path / "G-04.spec.ts"
    spec.write_text(textwrap.dedent("""
        import { test } from '@playwright/test';
        import { expectReadAfterWrite } from '@/test-helpers/expectReadAfterWrite';
        import { invariantG04 } from './fixtures/invariants/G-04';

        test('G-04: admin grants role', async ({ page, request }) => {
          // ... action code ...
          await expectReadAfterWrite(request, invariantG04, { new_role: 'admin', roles: ['admin'] });
        });
    """).strip(), encoding="utf-8")

    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-04.md").write_text(textwrap.dedent("""
        # G-04
        **goal_type:** mutation
        ## Read-after-write invariant
        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_spec_without_helper_call_blocks(tmp_path: Path) -> None:
    """Mutation goal but spec doesn't call expectReadAfterWrite — must BLOCK."""
    spec = tmp_path / "G-04.spec.ts"
    spec.write_text(textwrap.dedent("""
        import { test, expect } from '@playwright/test';

        test('G-04: admin grants role', async ({ page }) => {
          await page.click('[data-testid="grant-role"]');
          await expect(page.locator('.toast-success')).toBeVisible();
          // BUG: no expectReadAfterWrite — toast checked, DB not verified
        });
    """).strip(), encoding="utf-8")

    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-04.md").write_text(textwrap.dedent("""
        # G-04
        **goal_type:** mutation
        ## Read-after-write invariant
        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "G-04" in result.stderr
    assert "expectReadAfterWrite" in result.stderr or "helper" in result.stderr.lower()


def test_non_mutation_goal_doesnt_require_helper(tmp_path: Path) -> None:
    spec = tmp_path / "G-99.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\ntest('G-99: read-only health', async () => {});\n",
        encoding="utf-8",
    )
    goals = tmp_path / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-99.md").write_text("# G-99\n**goal_type:** read_only\n", encoding="utf-8")

    result = subprocess.run([
        "python3", str(GATE),
        "--specs-dir", str(tmp_path),
        "--goals-dir", str(goals),
        "--phase", "test",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
```

- [ ] **Step 2: Run failing tests**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_codegen_rcrurd_helper.py -v`
Expected: 3 failures.

- [ ] **Step 3: Write the helper TS file**

Create directory + file: `scripts/codegen-helpers/expectReadAfterWrite.ts`:

```typescript
/**
 * expectReadAfterWrite — Playwright test helper for read-after-write
 * verification (Task 22 invariant consumer).
 *
 * Generated specs MUST call this for every mutation step. AST validator
 * (verify-codegen-rcrurd-helper.py) confirms the call exists with the
 * correct invariant binding.
 *
 * Source of truth: schemas/rcrurd-invariant.schema.yaml
 */

import { APIRequestContext, expect } from '@playwright/test';

export interface Assertion {
  path: string;
  op: 'contains' | 'equals' | 'matches' | 'not_contains';
  value_from: string;
  layer?: string;
}

export interface RCRURDInvariant {
  goal_id: string;
  write: { method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; endpoint: string };
  read: {
    method: 'GET';
    endpoint: string;
    cache_policy: 'no_store' | 'cache_ok' | 'bypass_cdn';
    settle: { mode: 'immediate' | 'poll' | 'wait_event'; timeout_ms?: number; interval_ms?: number };
  };
  assert: Assertion[];
  precondition?: Assertion[];
  side_effects?: Assertion[];
}

function evalJsonPath(body: unknown, path: string): unknown[] {
  if (path === '$') return [body];
  let cur: unknown[] = [body];
  const parts = path.startsWith('$.') ? path.slice(2).split('.') : [path.slice(1)];
  for (const part of parts) {
    const m = /^([^[]+)(\[\*])?$/.exec(part);
    if (!m) return [];
    const key = m[1];
    const star = !!m[2];
    const next: unknown[] = [];
    for (const c of cur) {
      if (c && typeof c === 'object' && key in (c as Record<string, unknown>)) {
        const v = (c as Record<string, unknown>)[key];
        if (star && Array.isArray(v)) next.push(...v);
        else next.push(v);
      }
    }
    cur = next;
  }
  return cur;
}

function resolveValue(valueFrom: string, payload: Record<string, unknown>): unknown {
  if (valueFrom.startsWith('literal:')) return valueFrom.slice(8);
  if (valueFrom.startsWith('action.')) return payload[valueFrom.slice(7)];
  return valueFrom;
}

function applyOp(observed: unknown[], op: string, expected: unknown): boolean {
  const flat = observed.flat();
  if (op === 'contains') return flat.includes(expected);
  if (op === 'not_contains') return !flat.includes(expected);
  if (op === 'equals') return observed.length === 1 && observed[0] === expected;
  if (op === 'matches') {
    return observed.length === 1 && typeof observed[0] === 'string'
      && new RegExp(String(expected)).test(observed[0]);
  }
  return false;
}

function cacheHeaders(policy: string): Record<string, string> {
  if (policy === 'no_store') return { 'Cache-Control': 'no-store, no-cache', Pragma: 'no-cache' };
  if (policy === 'bypass_cdn') return { 'Cache-Control': 'no-store', 'X-Bypass-CDN': '1' };
  return {};
}

export async function expectReadAfterWrite(
  request: APIRequestContext,
  invariant: RCRURDInvariant,
  actionPayload: Record<string, unknown>,
): Promise<void> {
  const headers = cacheHeaders(invariant.read.cache_policy);

  // Optional: precondition — assert pre-state holds
  if (invariant.precondition?.length) {
    const preResp = await request.get(invariant.read.endpoint, { headers });
    const preBody = await preResp.json().catch(() => ({}));
    for (const a of invariant.precondition) {
      const observed = evalJsonPath(preBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      expect(
        applyOp(observed, a.op, expected),
        `[${invariant.goal_id}] precondition failed: ${a.path} ${a.op} ${expected} (observed=${JSON.stringify(observed)})`,
      ).toBeTruthy();
    }
  }

  // Write
  const writeResp = await request[invariant.write.method.toLowerCase() as 'post' | 'put' | 'patch' | 'delete'](
    invariant.write.endpoint, { data: actionPayload },
  );
  expect(
    writeResp.ok(),
    `[${invariant.goal_id}] write returned ${writeResp.status()} — R1 silent_state_mismatch suspected`,
  ).toBeTruthy();

  // Read with settle policy
  const readWithAssert = async (): Promise<{ allPassed: boolean; failures: string[] }> => {
    const readResp = await request.get(invariant.read.endpoint, { headers });
    const readBody = await readResp.json().catch(() => ({}));
    const failures: string[] = [];
    for (const a of invariant.assert) {
      const observed = evalJsonPath(readBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      if (!applyOp(observed, a.op, expected)) {
        failures.push(`${a.path} ${a.op} ${JSON.stringify(expected)} (observed=${JSON.stringify(observed).slice(0, 100)})`);
      }
    }
    return { allPassed: failures.length === 0, failures };
  };

  if (invariant.read.settle.mode === 'immediate') {
    const r = await readWithAssert();
    expect(
      r.allPassed,
      `[${invariant.goal_id}] R8 update_did_not_apply: ${r.failures.join('; ')}`,
    ).toBeTruthy();
  } else {
    const timeoutMs = invariant.read.settle.timeout_ms ?? 5000;
    const intervalMs = invariant.read.settle.interval_ms ?? 500;
    const deadline = Date.now() + timeoutMs;
    let last: { allPassed: boolean; failures: string[] } = { allPassed: false, failures: [] };
    while (Date.now() < deadline) {
      last = await readWithAssert();
      if (last.allPassed) break;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    expect(
      last.allPassed,
      `[${invariant.goal_id}] R8 update_did_not_apply (after settle ${timeoutMs}ms): ${last.failures.join('; ')}`,
    ).toBeTruthy();
  }

  // Side effects
  if (invariant.side_effects?.length) {
    const sideResp = await request.get(invariant.read.endpoint, { headers });
    const sideBody = await sideResp.json().catch(() => ({}));
    for (const a of invariant.side_effects) {
      const observed = evalJsonPath(sideBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      expect(
        applyOp(observed, a.op, expected),
        `[${invariant.goal_id}] side_effect ${a.layer} failed: ${a.path} ${a.op} ${expected}`,
      ).toBeTruthy();
    }
  }
}
```

- [ ] **Step 4: Write the AST gate**

Create `scripts/validators/verify-codegen-rcrurd-helper.py`:

```python
#!/usr/bin/env python3
"""verify-codegen-rcrurd-helper.py — Task 24 codegen-side AST gate.

Per Codex GPT-5.5 review 2026-05-03: regex check is brittle. Better cut:
require generated tests to call a known helper, AND verify each mutation
goal's spec imports/calls that helper.

This gate uses a pragmatic AST-lite check: for each TEST-GOAL with
`goal_type: mutation`, locate the matching `<goal_id>.spec.ts` (by stem
match) and verify it contains BOTH:
  1. `import ... expectReadAfterWrite ... from ...` (helper imported)
  2. `expectReadAfterWrite(...)` call site

This is stronger than mutation-layers.py's regex (which only checks
'reload' + 'API call' presence) because it requires the SPECIFIC helper
that consumes the structured invariant from Task 22.

Future upgrade (P3): full TypeScript AST via ts-morph subprocess —
verify the actual invariant object passed matches Task 22's parsed
shape for that goal. Today's gate is import+call presence.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


IMPORT_RE = re.compile(
    r"import\s+(?:\{[^}]*\bexpectReadAfterWrite\b[^}]*\}|\*\s+as\s+\w+)\s+from\s+['\"][^'\"]+['\"]",
    re.MULTILINE,
)
CALL_RE = re.compile(r"\bexpectReadAfterWrite\s*\(", re.MULTILINE)
GOAL_TYPE_RE = re.compile(r"\*\*goal_type:\*\*\s*(\S+)", re.MULTILINE)


def _is_mutation_goal(goal_path: Path) -> bool:
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return False
    m = GOAL_TYPE_RE.search(text)
    return bool(m and m.group(1).lower() == "mutation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specs-dir", required=True)
    parser.add_argument("--goals-dir", required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()

    specs_dir = Path(args.specs_dir)
    goals_dir = Path(args.goals_dir)
    if not specs_dir.exists():
        print(f"ERROR: specs-dir missing: {specs_dir}", file=sys.stderr)
        return 2
    if not goals_dir.exists():
        print(f"ERROR: goals-dir missing: {goals_dir}", file=sys.stderr)
        return 2

    # Index specs by stem for goal-id matching
    specs_by_stem: dict[str, Path] = {}
    for spec in specs_dir.rglob("*.spec.ts"):
        specs_by_stem[spec.stem.replace(".spec", "")] = spec

    failures: list[str] = []
    checked = 0
    for goal in sorted(goals_dir.glob("G-*.md")):
        if not _is_mutation_goal(goal):
            continue
        checked += 1
        goal_id = goal.stem
        spec = specs_by_stem.get(goal_id)
        if spec is None:
            failures.append(f"{goal_id}: mutation goal but no matching spec found "
                           f"(looked for {goal_id}.spec.ts in {specs_dir})")
            continue
        try:
            text = spec.read_text(encoding="utf-8")
        except OSError as e:
            failures.append(f"{goal_id}: cannot read spec {spec}: {e}")
            continue
        if not IMPORT_RE.search(text):
            failures.append(f"{goal_id}: spec {spec.name} does not import expectReadAfterWrite")
            continue
        if not CALL_RE.search(text):
            failures.append(f"{goal_id}: spec {spec.name} does not call expectReadAfterWrite()")

    if failures:
        print(f"⛔ codegen RCRURD gate: {len(failures)} mutation goal(s) failed "
              f"(checked {checked}):", file=sys.stderr)
        for f in failures:
            print(f"   - {f}", file=sys.stderr)
        return 1

    print(f"✓ codegen RCRURD gate: {checked} mutation goal(s) all use expectReadAfterWrite()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
mkdir -p scripts/codegen-helpers
chmod +x scripts/validators/verify-codegen-rcrurd-helper.py
python3 -m pytest tests/test_codegen_rcrurd_helper.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Wire into vg-test-codegen subagent**

Edit `agents/vg-test-codegen/SKILL.md`. Find the existing mutation-layers requirement. Add HARD RULE section:

```markdown
## RCRURD helper hard rule (Codex GPT-5.5 review 2026-05-03)

For EVERY mutation goal in TEST-GOALS, the generated `.spec.ts` MUST:
1. Import `expectReadAfterWrite` from the test-helpers package
2. Call `expectReadAfterWrite(request, invariant, actionPayload)` after
   the mutation step

The invariant comes from the structured YAML block in the goal's
TEST-GOALS/G-NN.md (parsed by Task 22's
`scripts/lib/rcrurd_invariant.py`). DO NOT regenerate or paraphrase
the invariant — import the parsed structure from a fixture file
(write fixture once at codegen time, generated specs reference it).

Post-codegen validator: `scripts/validators/verify-codegen-rcrurd-helper.py`
runs as part of mutation-layers gate. Missing helper call = BLOCK.
```

Edit `commands/vg/_shared/test/codegen/delegation.md` to reference the new helper rule (cite it in the existing mutation-layers checklist).

- [ ] **Step 7: Commit**

```bash
mkdir -p scripts/codegen-helpers
git add scripts/codegen-helpers/expectReadAfterWrite.ts \
        scripts/validators/verify-codegen-rcrurd-helper.py \
        tests/test_codegen_rcrurd_helper.py \
        agents/vg-test-codegen/SKILL.md \
        commands/vg/_shared/test/codegen/delegation.md
git commit -m "feat(rcrurd): codegen helper + AST gate for read-after-write verification

Codex GPT-5.5 review 2026-05-03: replace generic regex check with known-
helper pattern. Generated specs MUST call expectReadAfterWrite() with
the structured invariant from Task 22 parser. AST gate (import + call
site) blocks codegen output without the helper.

Helper handles cache_policy headers (no-store/no-cache), settle modes
(immediate/poll), JSONPath assertions, side-effect multi-asserts.
Single source of truth: schemas/rcrurd-invariant.schema.yaml."
```
