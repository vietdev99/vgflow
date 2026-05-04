# test codegen delegation (STEP 5 — contract document)

<!-- Exception: contract document.
     This file is NOT an executable step ref — it documents the spawn
     payload + return contract for vg-test-codegen. No HARD-GATE block
     because the orchestrator-side HARD-GATE lives in
     `_shared/test/codegen/overview.md`. The subagent's own HARD-GATE
     lives in `agents/vg-test-codegen/SKILL.md`. Per review-v2 B1/B2. -->

This file contains the prompt template the main agent passes to
`Agent(subagent_type="vg-test-codegen", prompt=...)`.

Read `codegen/overview.md` for orchestration order. This file describes
ONLY the spawn payload + return contract.

---

## Input contract (JSON envelope)

```json
{
  "phase_dir": "${PHASE_DIR}",
  "phase_number": "${PHASE_NUMBER}",
  "phase_profile": "${PHASE_PROFILE}",
  "goals_loaded_via": "vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical",
  "goals_index": "<output of vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical>",
  "contracts_loaded_via": "vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>",
  "edge_cases_loaded_via": "vg-load --phase ${PHASE_NUMBER} --artifact edge-cases --goal G-NN",
  "edge_cases_available": true,
  "runtime_map_path": "${PHASE_DIR}/RUNTIME-MAP.json",
  "goal_coverage_matrix_path": "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md",
  "generated_tests_dir": "${GENERATED_TESTS_DIR}",
  "existing_specs": "<list of .spec.ts paths already in GENERATED_TESTS_DIR, if any>",
  "gtb_mode": "${GTB_MODE:-strict}",
  "config": {
    "python_bin": "${PYTHON_BIN:-python3}",
    "vg_tmp": "${VG_TMP:-${PHASE_DIR}/.vg-tmp}",
    "repo_root": "${REPO_ROOT:-.}",
    "arguments": "${ARGUMENTS}"
  }
}
```

**CRITICAL — vg-load mandate:**
- Goals MUST be loaded via `vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical`.
- Per-endpoint contracts MUST be loaded via `vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>` (endpoint slug derives from the goal's API binding).
- **Edge cases (P1 v2.49+)**: when `edge_cases_available: true`, MUST load
  per-goal variants via `vg-load --phase ${PHASE_NUMBER} --artifact edge-cases --goal G-NN`.
  Generate `test.each([...variants])` blocks per goal so each variant
  becomes its own assertion. Variant `expected_outcome` → assertion text.
  When `edge_cases_available: false` (legacy phase), generate single-path
  spec.ts as before; emit warning in return JSON.
  
  **TOOLING shortcut**: dùng `python3 .claude/scripts/edge-cases-to-spec.py
  --phase ${PHASE_NUMBER} --goal G-NN --framework playwright` để gen
  deterministic skeleton (vg-edge-case anchor + variant_id + priority đầy đủ
  trong test.each). Subagent CHỈ fill body (selector/click/fill/assertion)
  thay vì bịa skeleton — đảm bảo coverage check (Gate F.2.5) PASS.
- The subagent MUST NOT `cat PLAN.md`, `cat API-CONTRACTS.md`, `cat TEST-GOALS.md`,
  or `cat EDGE-CASES.md` directly. All artifacts loaded via vg-load.

---

## Prompt template (substitute then pass as `prompt`)

````
You are vg-test-codegen. Generate Playwright test specs for phase
${PHASE_NUMBER}, run the binding gate, and return a JSON envelope.
Do NOT browse files outside input. Do NOT ask user — input is the contract.

<inputs>
@${PHASE_DIR}/RUNTIME-MAP.json            (review-discovered paths — read-only)
@${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md    (review verdicts — read-only)
@${PHASE_DIR}/FIXTURES-CACHE.json        (if exists — fixture inject)
@${PHASE_DIR}/CRUD-SURFACES.md           (if exists — CRUD structural fallback)
@${PHASE_DIR}/TEST-GOALS-DISCOVERED.md   (if exists — G-AUTO-* skeleton specs)
@${PHASE_DIR}/TEST-GOALS-EXPANDED.md     (if exists — G-CRUD-* skeleton specs)
</inputs>

<config>
phase_number: ${PHASE_NUMBER}
phase_dir: ${PHASE_DIR}
generated_tests_dir: ${GENERATED_TESTS_DIR}
gtb_mode: ${GTB_MODE:-strict}
vg_tmp: ${VG_TMP:-${PHASE_DIR}/.vg-tmp}
python_bin: ${PYTHON_BIN:-python3}
arguments: ${ARGUMENTS}
</config>

# Your workflow

## Step A — goal-status map

Build status map from GOAL-COVERAGE-MATRIX.md. Parse Goal Details table.
Write to `${VG_TMP}/goal-status.json`:

```python
import json, re
matrix = open("${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md", encoding='utf-8').read()
status_map = {}
m = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', matrix, re.M|re.S)
if m:
    for line in m.group(1).splitlines():
        gm = re.match(r'^\|\s*(G-[\w.-]+)\s*\|[^|]*\|[^|]*\|\s*(\w+)\s*\|', line)
        if gm:
            status_map[gm.group(1)] = gm.group(2)
json.dump(status_map, open("${VG_TMP}/goal-status.json", 'w', encoding='utf-8'), indent=2)
```

## Step B — pre-codegen dynamic ID gate (HARD BLOCK)

Scan RUNTIME-MAP.json goal_sequences for dynamic ID selectors:

```bash
DYN_ID_PATTERNS='#[a-zA-Z_-]+_[0-9]{3,}|#row-[a-z0-9]{6,}|data-id="[0-9]+|\[id\^=|\[data-id\^='

DYN_FOUND=$(${PYTHON_BIN:-python3} -c "
import json, re
rt = json.load(open('${PHASE_DIR}/RUNTIME-MAP.json', encoding='utf-8'))
patterns = re.compile(r'${DYN_ID_PATTERNS}')
hits = []
for goal_id, seq in rt.get('goal_sequences', {}).items():
    for i, step in enumerate(seq.get('steps', [])):
        sel = step.get('selector', '')
        if sel and patterns.search(sel):
            hits.append((goal_id, i, sel))
for h in hits:
    print(f'{h[0]}|step={h[1]}|{h[2]}')
" 2>/dev/null)

if [ -n "$DYN_FOUND" ]; then
  echo "⛔ Dynamic ID selectors found in RUNTIME-MAP.json goal_sequences:"
  echo "$DYN_FOUND" | sed 's/^/  /'
  # Attempt L1 via block-resolver
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_PHASE="${PHASE_NUMBER}" VG_CURRENT_STEP="test.codegen.dynamic-ids"
    BR_GATE_CONTEXT="Dynamic ID selectors in RUNTIME-MAP.json goal_sequences will produce flaky tests. Fix: re-run /vg:review --retry-failed to re-record with stable selectors."
    BR_EVIDENCE=$(printf '{"dyn_found":"%s"}' "$(echo "$DYN_FOUND" | head -c 800 | tr '\n' ';')")
    BR_CANDIDATES='[{"id":"retry-failed-rescan","cmd":"echo L1-SAFE: would re-trigger review --retry-failed; exit 1","confidence":0.4,"rationale":"Re-scan often yields stable role-based locators if DOM updated"}]'
    BR_RESULT=$(block_resolve "dynamic-ids" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    case "$BR_LEVEL" in
      L1) echo "✓ L1 resolved — selectors re-recorded with stable locators" ;;
      L2) echo "▸ L2 architect proposal — return l2_escalation for dynamic-ids to main agent"; exit 2 ;;
      *)  exit 1 ;;
    esac
  else
    if [[ ! "${ARGUMENTS}" =~ --allow-dynamic-ids ]]; then
      exit 1
    fi
    echo "⚠ --allow-dynamic-ids set — proceeding with flaky selectors."
  fi
fi
```

## Step C — codegen per goal (READY goals)

For each goal in status_map, branch by status:

| Status | Action |
|---|---|
| `READY` (+ non-empty `goal_sequences[G-XX]`) | Generate full spec (Step C.1). |
| `READY` + missing `goal_sequences[G-XX]` | **BLOCK** — emit error: "Goal G-XX READY in matrix but RUNTIME-MAP has no sequence. Re-run /vg:review --retry-failed." |
| `MANUAL` | Emit skeleton with `test.skip()` (Step C.2). |
| `DEFERRED` | Skip entirely — log `[skip-deferred] {gid}`. |
| `INFRA_PENDING` | Emit skeleton `.skip()` with infra comment (Step C.2). |
| `BLOCKED` / `UNREACHABLE` | Skip — review gate should have caught these. Log error. |

### Step C.1 — READY goal codegen

**Interactive controls branch (v2.7 Phase B):**
If goal frontmatter has `interactive_controls.url_sync: true`, delegate codegen
to `vg-codegen-interactive` skill (Sonnet, 1 call per goal, temperature 0).
Validate output up to 3 attempts before falling back to manual flow.

**Rigor pack (Phase 15 T6.1 D-16):**
If goal frontmatter declares `interactive_controls.filters[]` and/or
`interactive_controls.pagination`, render rigor pack via matrix module
(deterministic, no Sonnet, pure JS substitution through
`skills/vg-codegen-interactive/filter-test-matrix.mjs`).
Validate with `verify-filter-test-coverage.py --phase ${PHASE_NUMBER}`.

**Manual codegen rules (READY goals without interactive_controls.url_sync):**

1. **Selector priority** (read from `vg.config.md > test_ids.codegen_priority`):
   1. `getByTestId` (data-testid)
   2. `getByRole` (semantic)
   3. `getByLabel` (accessibility)
   4. `getByText` (last resort — emit warning comment)
   NEVER use dynamic IDs as selectors.

2. **Login helper (i18n-stable, Bug-6 fix):**
   Emit `apps/<role>/e2e/utils/login.ts` using `<input id>` selectors (NOT
   `getByLabel(/password/i)` — breaks in non-English projects).

3. **Assertions from TEST-GOALS** — map each success criterion to one `expect()`.
   Never invent assertions beyond TEST-GOALS.

4. **Steps from goal_sequences** — each `do` step → Playwright action; each
   `assert` step → `expect()`. Nearly 1:1 mapping.

5. **Mutation 4-layer verify** (every POST/PUT/PATCH/DELETE):
   ```
   Layer 1: Toast text  → expect(page.getByRole('status')).toContainText(expected_toast)
   Layer 2: API 2xx     → res = await page.waitForResponse(...); expect(res.status()).toBeLessThan(400)
   Layer 3: Persistence → await page.reload(); expect(persisted_value).toBeVisible()
   Layer 4: Console     → errs = await page.evaluate(() => window.__consoleErrors || []);
                          expect(errs.length).toBe(0)
   ```

6. **Env var credentials** — never hardcode emails/passwords. Use
   `{ROLE_UPPER}_EMAIL`, `{ROLE_UPPER}_PASSWORD`, `{ROLE_UPPER}_DOMAIN`.

Output: `${GENERATED_TESTS_DIR}/${PHASE_NUMBER}-goal-{group}.spec.ts`

### Step C.2 — MANUAL / INFRA_PENDING skeleton

```typescript
// === AUTO-GENERATED SKELETON (MANUAL goal) — v1.14.0+ B.2 ===
// Goal: G-XX — {title}
// Status: MANUAL (verification_strategy: {strategy})
import { test, expect } from '@playwright/test';
test.skip('MANUAL: {goal title}', async ({ page }) => {
  // USER FILL: Steps to perform manually in UAT.
});
```

```typescript
// === AUTO-GENERATED SKELETON (INFRA_PENDING) — v1.14.0+ B.2 ===
// Goal: G-XX — {title}
// Infra deps: {list}
import { test, expect } from '@playwright/test';
test.skip('INFRA_PENDING: {goal title} — requires {deps}', async ({ page }) => {
  // Un-skip when infra deployed.
});
```

## Step D — auto-emitted goal skeletons (5d-auto)

After main codegen, emit skeleton specs for auto/expanded goals:

```bash
DISCOVERED_FILE="${PHASE_DIR}/TEST-GOALS-DISCOVERED.md"
EXPANDED_FILE="${PHASE_DIR}/TEST-GOALS-EXPANDED.md"
if [ -f "$DISCOVERED_FILE" ] || [ -f "$EXPANDED_FILE" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/codegen-auto-goals.py \
    --phase-dir "$PHASE_DIR" \
    --out-dir "$GENERATED_TESTS_DIR"
fi
```

Files land as `${GENERATED_TESTS_DIR}/auto-{goal-id-slug}.spec.ts`.

## Step E — RFC v9 codegen fixture inject (post-generation)

Run AFTER all generation paths above (manual, auto-emitted, interactive_controls).

Pass 1: Prepend `FIXTURE = {...}` const block (idempotent, sentinel-bracketed).
Pass 2: Substitute literal captured-value occurrences with `FIXTURE.<name>` refs.

```bash
CODEGEN_FIXTURE_INJECT="${REPO_ROOT}/.claude/scripts/codegen-fixture-inject.py"
[ -f "$CODEGEN_FIXTURE_INJECT" ] || CODEGEN_FIXTURE_INJECT="${REPO_ROOT}/scripts/codegen-fixture-inject.py"
if [ -f "$CODEGEN_FIXTURE_INJECT" ] && [ -f "${PHASE_DIR}/FIXTURES-CACHE.json" ]; then
  "${PYTHON_BIN:-python3}" "$CODEGEN_FIXTURE_INJECT" \
    --phase "$PHASE_NUMBER" \
    --sweep "${GENERATED_TESTS_DIR}" \
    --substitute 2>&1
fi
```

Validate:
```bash
CGFR_VAL=".claude/scripts/validators/verify-codegen-fixture-ref.py"
if [ -f "$CGFR_VAL" ] && [ -f "${PHASE_DIR}/FIXTURES-CACHE.json" ]; then
  "${PYTHON_BIN:-python3}" "$CGFR_VAL" \
    --phase "$PHASE_NUMBER" \
    --tests-dir "${GENERATED_TESTS_DIR}" \
    --severity "${VG_CODEGEN_FIXTURE_SEVERITY:-block}"
fi
```

## Step F — L1/L2 binding gate

### F.1 — R7 console monitoring enforcement gate

Verify generated mutation specs have console assertion:

```python
import re, sys, os
from pathlib import Path

tests_dir = Path("${GENERATED_TESTS_DIR}")
spec_files = list(tests_dir.rglob("*.spec.ts"))

SETUP_PATTERNS = [
    r'window\.__consoleErrors',
    r'page\.on\s*\(\s*[\'"]console[\'"]',
    r'captureConsoleErrors',
]
ASSERT_PATTERNS = [
    r'expect\s*\(\s*(?:errs|consoleErrors|window\.__consoleErrors)[\[\.\w]*\s*\)\.toBe\s*\(\s*0\s*\)',
    r'expect\s*\(\s*.*console.*\)\.toBe(?:Less|Equal)',
]
MUTATION_PATTERNS = [
    r'(?:POST|PUT|PATCH|DELETE)\s+',
    r'waitForResponse.*(?:post|put|patch|delete)',
]

violations = []
for spec in spec_files:
    content = spec.read_text(encoding='utf-8', errors='ignore')
    has_mutation = any(re.search(p, content, re.IGNORECASE) for p in MUTATION_PATTERNS)
    has_assert = any(re.search(p, content) for p in ASSERT_PATTERNS)
    if has_mutation and not has_assert:
        violations.append(spec.name)

if violations:
    # BLOCK — emit in l2_escalations if block-resolver fails
    pass
```

Override: `--allow-missing-console-check` (logs override-debt).

### F.2 — adversarial coverage gate (v2.21.0)

```bash
ADV_SEVERITY=$(vg_config_get "adversarial_coverage.severity" "warn" 2>/dev/null || echo "warn")
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-adversarial-coverage.py \
  --phase-dir "${PHASE_DIR}" \
  --severity "${ADV_SEVERITY}"
```

WARN-only by default. Promote to BLOCK via `vg.config.md adversarial_coverage.severity: block`.

### F.2.5 — edge-case variant coverage gate (P1 v2.49+)

Before goal-test binding gate, verify each variant from EDGE-CASES has a
matching `test()` or `test.each()` row in generated `.spec.ts`:

```bash
if [ "$EDGE_CASES_AVAILABLE" = "true" ]; then
  # For each goal in goals_index, load edge cases + grep generated specs
  EDGE_GAP_COUNT=0
  for gid in $GOALS_LIST; do
    EDGE_FILE="${PHASE_DIR}/EDGE-CASES/${gid}.md"
    [ -f "$EDGE_FILE" ] || continue

    # Extract variant_ids from edge case file
    VARIANTS=$(grep -oE "${gid}-[a-z]\d+" "$EDGE_FILE" | sort -u)
    for vid in $VARIANTS; do
      # Variant must appear in spec.ts comment OR test name
      if ! grep -rqE "vg-edge-case[: ]+${vid}|test\\(['\"].*${vid}|test\\.each.*${vid}" "${GENERATED_TESTS_DIR}/" 2>/dev/null; then
        echo "  ⚠ ${gid}: variant ${vid} không có test (spec.ts thiếu coverage)"
        EDGE_GAP_COUNT=$((EDGE_GAP_COUNT + 1))
      fi
    done
  done
  if [ "$EDGE_GAP_COUNT" -gt 0 ]; then
    echo "⛔ ${EDGE_GAP_COUNT} variant(s) không có test coverage."
    echo "   AI phải re-codegen với test.each(...) per variant từ EDGE-CASES."
    echo "   Reference variant_id ở comment hoặc test name."
    # Emit l2_escalation if user passed --skip-edge-cases-binding
    [ -z "$ALLOW_SKIP" ] && exit 1
  fi
fi
```

Severity: BLOCK by default; degrades to WARN if `--allow-edge-case-gap` flag
set (paired with override-reason).

### F.3 — goal-test binding gate (verify-goal-test-binding.py)

After R7 gate and adversarial gate, run the binding verification:

```bash
GTB_MODE=$(vg_config_get build_gates.goal_test_binding_phase_end strict)
if [ "$GTB_MODE" != "off" ]; then
  PHASE_FIRST_COMMIT=$(git log --format="%H" --reverse --grep="${PHASE_NUMBER}-" | head -1)
  SCAN_TAG="${PHASE_FIRST_COMMIT:+${PHASE_FIRST_COMMIT}^}"
  SCAN_TAG="${SCAN_TAG:-HEAD~200}"

  GTB_ARGS="--phase-dir ${PHASE_DIR} --wave-tag ${SCAN_TAG} --wave-number phase-end"
  [ "$GTB_MODE" = "warn" ] && GTB_ARGS="${GTB_ARGS} --lenient"

  if ! ${PYTHON_BIN:-python3} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS}; then
    echo "⛔ Goal-test binding FAILED."

    # Attempt L1 via block-resolver (re-codegen candidate)
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="${PHASE_NUMBER}" VG_CURRENT_STEP="test.5b-goal-test-binding"
      BR_GATE_CTX="Goal-test binding gate: plan tasks claim goals but no corresponding test file found."
      BR_EVIDENCE=$(printf '{"gate":"goal_test_binding_phase_end","generated_tests_dir":"%s","mode":"%s"}' "$GENERATED_TESTS_DIR" "$GTB_MODE")
      BR_CANDIDATES='[{"id":"recodegen","cmd":"echo L1-SAFE: would invoke codegen-only rerun; exit 1","confidence":0.6,"rationale":"codegen drift is most common cause"}]'
      BR_RESULT=$(block_resolve "goal-test-binding" "$BR_GATE_CTX" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LEVEL" = "L1" ]; then
        echo "✓ L1 resolved — re-run verification"
        ${PYTHON_BIN:-python3} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS}
        L1_RESOLVED=$((L1_RESOLVED + 1))
      elif [ "$BR_LEVEL" = "L2" ]; then
        # L2: package architect proposal for return JSON l2_escalations
        block_resolve_l2_handoff "goal-test-binding" "$BR_RESULT" "$PHASE_DIR"
        L2_ITEMS+=("goal-test-binding|$(echo "$BR_RESULT" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('architect_proposal',''))" 2>/dev/null)|binding gate failed")
      else
        block_resolve_l4_stuck "goal-test-binding" "L1 re-codegen failed, L2 architect unavailable"
        BINDING_FAILED=true
      fi
    else
      BINDING_FAILED=true
    fi
  fi
fi
```

**L1/L2 binding gate summary:**

| Outcome | Behavior |
|---|---|
| Binding passes | Continue to return JSON. |
| L1 self-resolved | `l1_resolved_count` incremented; re-verify passes. |
| L2 needed | Package `architect_proposal` text into `l2_escalations`; main agent handles via `AskUserQuestion`. |
| L4 stuck | Binding FAILED recorded; main agent sees `binding_failed: true`. |

The `5d_binding_gate` step is NOT marked at orchestrator level — it is
subagent-internal. The binding gate's `verify-goal-test-binding.py` call
and the block-resolver L1/L2 loop are both fully contained here.

## Return JSON envelope

After all steps complete, return:

```json
{
  "spec_files": [
    "${GENERATED_TESTS_DIR}/${PHASE_NUMBER}-goal-G-01.spec.ts",
    "..."
  ],
  "auto_spec_files": [
    "${GENERATED_TESTS_DIR}/auto-g-auto-001.spec.ts"
  ],
  "bindings_satisfied": true,
  "l1_resolved_count": 0,
  "l2_escalations": [
    {
      "goal_id": "G-XX",
      "architect_proposal": "<one-paragraph proposal text>",
      "evidence": "<what block-resolver returned>"
    }
  ],
  "binding_failed": false,
  "r7_violations": [],
  "deferred_goals": ["G-03", "G-07"],
  "manual_skeletons": ["G-05"],
  "summary": "<one paragraph>",
  "warnings": []
}
```

`l2_escalations` MUST be present (empty array if none).
`bindings_satisfied` is `true` only if binding gate passed (or L1 resolved it).
`binding_failed` is `true` only if L4 stuck (no resolution path found).
````

---

## Allowed tools

- Read
- Write
- Edit
- Bash
- Glob
- Grep

`vg-codegen-interactive` skill invocation is allowed (1 call per goal
with `interactive_controls.url_sync: true`).

---

## Forbidden

- Spawning sub-subagents (no nested `Agent` calls — no recursive spawn).
- Reading TEST-GOALS.md, PLAN.md, or API-CONTRACTS.md via `cat` directly —
  goals and contracts are passed via the `goals_index` input field (loaded
  by main agent via `vg-load`).
- Generating goal verdicts or updating GOAL-COVERAGE-MATRIX.md.
- Writing any artifact outside `${GENERATED_TESTS_DIR}/`, `${PHASE_DIR}/.vg-tmp/`.

---

## Output (subagent returns)

```json
{
  "spec_files": ["${GENERATED_TESTS_DIR}/${PHASE_NUMBER}-goal-G-01.spec.ts"],
  "auto_spec_files": [],
  "bindings_satisfied": true,
  "l1_resolved_count": 0,
  "l2_escalations": [],
  "binding_failed": false,
  "r7_violations": [],
  "deferred_goals": [],
  "manual_skeletons": [],
  "summary": "Phase N: 8 goals codegenned. 6 READY → full specs, 1 MANUAL skeleton, 1 DEFERRED skipped. Binding gate PASS.",
  "warnings": []
}
```

---

## Failure modes

| Error JSON | Cause | Action |
|---|---|---|
| `{"error":"missing_input","field":"runtime_map_path"}` | RUNTIME-MAP.json missing | Run /vg:review first |
| `{"error":"missing_input","field":"goal_coverage_matrix_path"}` | GOAL-COVERAGE-MATRIX.md missing | Run /vg:review first |
| `{"error":"goal_load_failed"}` | vg-load returned empty goals | Run /vg:blueprint first |
| `{"error":"dynamic_ids_blocked"}` | Dynamic IDs in goal_sequences, L1 failed | Re-run /vg:review --retry-failed |
| `{"error":"binding_failed","l2_escalations":[...]}` | L2 proposals pending | Main agent handles via AskUserQuestion |
| `{"error":"r7_violation","specs":[...]}` | Mutation specs missing console assertion | Fix codegen template; re-run |

Retry up to 2 times on transient errors, then surface `l2_escalations` to
main agent for `AskUserQuestion` (Layer 3). Never retry indefinitely on
binding failures — those require code fixes or architect decisions.

---

## RCRURD helper requirement (Codex GPT-5.5 review 2026-05-03 — Task 24)

In addition to selector binding (L1/L2/L3/L4), every mutation goal's
generated spec MUST call `expectReadAfterWrite()` — see
`scripts/codegen-helpers/expectReadAfterWrite.ts` and the "RCRURD helper
hard rule" section in `agents/vg-test-codegen/SKILL.md`.

Post-codegen validation: orchestrator runs
`scripts/validators/verify-codegen-rcrurd-helper.py --specs-dir <dir>
--goals-dir <dir> --phase <p>` after subagent returns. Missing import or
call site BLOCKs the codegen step. The orchestrator re-spawns with the
failing goal list so the subagent can patch the specs.

### Lifecycle round-trip — R8-A (codex audit 2026-05-05)

When a goal's YAML invariant has `lifecycle: rcrurdr` (full 7-phase
RCRURDR lifecycle: Read empty → Create → Read populated → Update → Read
updated → Delete → Read empty), the spec MUST import + call
`expectLifecycleRoundtrip()` instead of `expectReadAfterWrite()`. The
simpler helper only verifies write+1-read so cannot close the loop on
update/delete/cleanup phases. See `agents/vg-test-codegen/SKILL.md`
"Lifecycle round-trip (R8-A)" for the full helper-selection table.

The validator BLOCKs when a `lifecycle: rcrurdr` goal's spec uses only
`expectReadAfterWrite`. Goals with `lifecycle: rcrurd` (default) or
`partial` continue to accept the simpler helper for back-compat.
