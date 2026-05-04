# review findings collect (STEP 5 — collect + merge + adversarial challenge)

7 steps verbatim from review.md backup, sequenced as the findings pipeline:
- `phase2b_collect_merge` — wait Haiku, summary read, gap fill, build RUNTIME-MAP, generate REVIEW-LENS-PLAN
- `phase2c_enrich_test_goals` — enrich-test-goals.py emits G-AUTO-* stubs
- `phase2c_pre_dispatch_gates` — contract completeness + env contract preflight before lens dispatch
- `phase2d_crud_roundtrip_dispatch` — Gemini Flash CRUD round-trip lens workers
- `phase2e_findings_merge` — derive-findings.py → REVIEW-FINDINGS.json + REVIEW-BUGS.md
- `phase2e_post_challenge` — adversarial reducer challenges pass claims (false-pass detection)
- `phase2f_route_auto_fix` — route-findings-to-build.py emits AUTO-FIX-TASKS.md (opt-in for /vg:build)

<HARD-GATE>
You MUST execute these in order. Each step writes its own marker via
`mark_step` + `vg-orchestrator mark-step review <name>`. The Haiku-spawn
audit in 2b-3 (`verify-haiku-spawn-fired.py`) BLOCKs on missing telemetry
unless `--skip-haiku-audit` is passed (logs override-debt).

Findings written in 3-layer artifact (per UX req 1):
- Layer 1: `${PHASE_DIR}/FINDINGS/finding-NN.md` (per-finding deep-dive)
- Layer 2: `${PHASE_DIR}/FINDINGS/index.md` (links + 1-line summary per finding)
- Layer 3: `${PHASE_DIR}/REVIEW-FINDINGS.json` + `${PHASE_DIR}/REVIEW-BUGS.md` (machine + flat human view)

vg-load convention: any per-goal context the Opus-level orchestrator needs
in steps 2b-3 #5/#7 (gap-fill, quality check) should come from
`vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN` instead of
flat reads of the whole TEST-GOALS.md (~8K lines on large phases).
Validators called inside this ref read flat artifacts via grep/regex —
those reads do NOT enter AI context and remain as-is.
</HARD-GATE>

---

## STEP 5.1 — collect + merge (phase2b_collect_merge)

<step name="phase2b_collect_merge" profile="web-fullstack,web-frontend-only" mode="full">

#### 2b-3: Collect, Cross-Check, Fill Gaps (Opus, no browser)

```
1. Wait for all Haiku agents to complete

2. Read SUMMARIES ONLY (not full JSON):
   For each scan-{view}-{role}.json:
     Read only the top-level fields: view, role, elements_total, elements_visited,
     elements_stuck, errors[] count, forms[] count, sub_views_discovered[]
   → Build slim overview: { view, visited_pct, error_count, stuck_count }

   IF a view has error_count > 0 OR stuck_count > 3 OR visited_pct < 90%:
     THEN read that view's full scan-{view}-{role}.json for detail
   ELSE: discard full JSON content — do NOT load into context

3. Cross-check coverage vs SPECS:
   - SPECS says phase has payments feature → Haiku found /payments? ✓
   - PLAN says 3 modals built → Haiku found 3 modals? ✓
   - Haiku discovered sub-views not in original list? → note for gap-filling

4. Gaps detected:
   - View listed but Haiku couldn't reach → Opus investigates (wrong URL? auth?)
   - Haiku found sub-views (e.g., /sites/123/settings) → spawn more Haiku
   - Elements marked "stuck" (file upload, complex wizard) → Opus handles or defers

5. Spawn additional Haiku agents if gaps found → collect → merge.
   Use `vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN` for
   per-goal briefing on the new Haiku spawns instead of flat-loading
   TEST-GOALS.md.

6. MERGE all scan results into coverage-map:
   views = all Haiku view results
   errors = concatenate + deduplicate
   stuck = concatenate
   forms = concatenate

7. QUALITY CHECK (Opus judgment on Haiku results):
   Flag suspicious results:
     - elements_visited < elements_total without stuck explanation → mark INCOMPLETE
     - Form submitted but no network request recorded → mark SUSPICIOUS
     - Console errors present but Haiku didn't report them → mark NEEDS_REVIEW
     - elements_total very low for a complex page → mark SHALLOW (Haiku may have missed scroll/lazy-load)

8. UPDATE GOAL-COVERAGE-MATRIX:
   For each TEST-GOALS goal, check if Haiku scan results cover it:
   - Form submitted matching goal's mutation → ⬜ → 🔍 SCAN-COVERED
   - View explored but goal-specific action not triggered → ⬜ → ⚠️ SCAN-PARTIAL
   - View not scanned → ⬜ → ❌ NOT-COVERED

   Note: Haiku scanners don't pursue goals — they scan exhaustively.
   Goal coverage mapping is done by Opus reading scan results.

9. PROBE VARIATIONS (OPT-IN — only runs if --with-probes flag set):
   Default OFF: /vg:test generates deterministic Playwright probes via codegen — cheaper,
     more reliable than LLM-driven probes, and already covers edit/boundary/repeat patterns.
   Only set --with-probes when: test codegen can't cover the mutation (e.g., complex data
     setup, external service stubs), or debugging a goal that passed scan but failed probes.

   IF NOT --with-probes: skip to step 10.

   For each goal marked SCAN-COVERED that involves mutations (create/edit/delete):

   Spawn Haiku probe agent (model="haiku"):
   """
   You are a probe agent. Test mutation variations for goal: {goal_id}.

   URL: {view_url} | Login: {credentials}
   Primary action: {what Haiku scan already did — from scan JSON}

   Run 3 probes:

   Probe 1 — EDIT: Navigate to the record just created/modified.
     Open edit form → change 1-2 fields (different valid data) → submit
     → Record: {changed_fields, result, network[], console_errors[]}

   Probe 2 — BOUNDARY: Open same form again.
     Fill with edge values: empty optional fields, max-length "A"×255,
     special chars "O'Brien <script>", zero for numbers, past dates
     → Submit → Record: {values_description, result, validation_errors[]}

   Probe 3 — REPEAT: Open same form again.
     Fill with EXACT same data as primary scan → submit
     → Expect: success OR proper duplicate error — NOT crash/500
     → Record: {result, is_duplicate_handled}

   Write to: {PHASE_DIR}/probe-{goal_id}.json
   """

   Collect all probe JSONs → merge into goal_sequences[goal_id].probes[]
   Update matrix: SCAN-COVERED + probes passed → 🔍 PROBE-VERIFIED

10. For NOT-COVERED or SHALLOW items:
   Opus does targeted investigation using its own MCP Playwright:
   - Claim 1 server
   - Navigate to specific view/element
   - Investigate why Haiku missed it
   - Release server

<CHECKPOINT_RULE>
**Atomic artifact per major step — no separate state file (v1.14.4+):**
- Step 2b-1 → writes `${PHASE_DIR}/nav-discovery.json` (atomic)
- Step 2b-2 → writes `${PHASE_DIR}/scan-{view-slug}.json` per Haiku agent (atomic per view)
- Step 2b-3 → writes `${PHASE_DIR}/RUNTIME-MAP.json` + `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`
- Steps 8/9/10 → extend RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md

If session dies mid-2b-2: re-run `/vg:review {phase}` — nav-discovery.json + partial scan-*.json stay, orchestrator redoes only missing views. Per-view scan is cheap (~30s Haiku call), no need for global state file. Step-level idempotency handled by `.step-markers/*.done`.
</CHECKPOINT_RULE>
```

**Session model (from config):**
- `$SESSION_MODEL` = "multi-context": each Haiku agent uses own browser context (natural fit)
- "single-context": agents run sequentially sharing 1 context (fallback)
- Roles come from `config.credentials[ENV]` — NOT hardcoded

### 2d: Build RUNTIME-MAP

**3-layer schema: navigation graph + interactive elements + goal action sequences.**

No component-type classification (no "modal", "table", "card" types). Elements are binary: interactive or not. State changes are observed via fingerprint diff (URL + element count + DOM hash), not classified.

Write `${PHASE_DIR}/RUNTIME-MAP.json`:
```json
{
  "phase": "{phase}",
  "build_sha": "{sha}",
  "discovered_at": "{ISO timestamp}",

  "views": {
    "{view_path}": {
      "role": "{role from config.credentials}",
      "arrive_via": "{click sequence to get here — e.g. sidebar > menu item}",
      "snapshot_summary": "{free text — AI describes what it sees, chooses best format}",
      "fingerprint": { "url": "{url}", "element_count": 0, "dom_hash": "{sha256[:16]}" },
      "elements": [
        { "selector": "{from snapshot}", "label": "{visible text}", "visited": false }
      ],
      "issues": [],
      "screenshots": ["{phase}-{view}-{state}.png"]
    }
  },

  "goal_sequences": {
    "{goal_id}": {
      "start_view": "{view_path}",
      "result": "passed|failed",
      "steps": [
        { "do": "click", "selector": "{from snapshot}", "label": "{text}" },
        { "do": "fill", "selector": "{from snapshot}", "value": "{test data}" },
        { "do": "select", "selector": "{from snapshot}", "value": "{option}" },
        { "do": "wait", "for": "{condition — state_changed|network_idle|element_visible}" },
        { "observe": "{what_changed}", "network": [{"method": "POST", "url": "{observed}", "status": 201}], "console_errors": [] },
        { "assert": "{criterion from TEST-GOALS}", "passed": true }
      ],
      "probes": [
        { "type": "edit", "changed_fields": ["{field}"], "result": "passed|failed", "network": [], "console_errors": [] },
        { "type": "boundary", "values_description": "{what AI tried}", "result": "passed|failed", "network": [], "console_errors": [] },
        { "type": "repeat", "result": "passed|failed", "network": [], "console_errors": [] }
      ],
      "evidence": ["{screenshot paths}"]
    }
  },

  "free_exploration": [
    { "view": "{view_path}", "element_selector": "{selector}", "element_label": "{text}", "result": "{free text}", "issue": null }
  ],

  "errors": [],
  "coverage": {
    "views": 0,
    "goals_attempted": 0,
    "goals_passed": 0,
    "elements_visited": 0,
    "elements_total": 0,
    "pass_1_time": "{duration}",
    "pass_2_time": "{duration}"
  }
}
```

**Schema design principles (from research):**
- **No component types** — elements are just `{ selector, label, visited }`. AI doesn't classify "button" vs "link" vs "row action". Binary: interactive or not. (browser-use approach)
- **State change = fingerprint diff** — URL changed? element_count changed? dom_hash changed? = "something changed". AI describes *what* changed in free text `observe` steps. (browser-use PageFingerprint approach)
- **Goal sequences = replayable action chains** — each step is `do` (action) or `observe` (observation) or `assert` (verification). Test step replays these 1:1. Codegen converts to .spec.ts nearly 1:1. (Playwright codegen approach)
- **Free exploration = flat list** — unstructured, just records what AI found outside goal scope. Issues go to Phase 3.
- **All values from runtime observation** — selectors from browser_snapshot, labels from visible text, observations from what AI actually sees. Nothing invented.

Derive `${PHASE_DIR}/RUNTIME-MAP.md` from JSON (human-readable summary).

**JSON is the source of truth.** Markdown is derived. Downstream steps (test, codegen) read JSON.

**Phase 15 D-17 — phantom-aware Haiku spawn audit (NEW, 2026-04-27):**

Confirm the `review.haiku_scanner_spawned` event emitted by step 2b-2 is
actually present in events.db for every (view × role) we expected to scan.
The validator (`verify-haiku-spawn-fired.py`) is phantom-aware: it ignores
events from runs whose signature matches `args:""` + 0 step.marked + abort
within 60s (the D-17 hook-triggered noise pattern), so manual `/vg:learn`
invocations don't show up as false positives.

```bash
PHANTOM_VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-haiku-spawn-fired.py"
if [ -x "$PHANTOM_VALIDATOR" ] && [ -f "${REPO_ROOT}/.vg/events.db" ]; then
  ${PYTHON_BIN} "$PHANTOM_VALIDATOR" --phase "${PHASE_NUMBER}" \
      > "${VG_TMP}/haiku-spawn-audit.json" 2>&1 || true
  HSV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/haiku-spawn-audit.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$HSV" in
    PASS) echo "✓ D-17 Haiku-spawn audit: PASS — telemetry confirms scanner fired per view/role" ;;
    WARN) echo "⚠ D-17 Haiku-spawn audit: WARN — see ${VG_TMP}/haiku-spawn-audit.json (informational only)" ;;
    BLOCK)
      echo "⛔ D-17 Haiku-spawn audit: BLOCK — expected scanner spawns missing from events.db." >&2
      echo "   Inspect ${VG_TMP}/haiku-spawn-audit.json for the per-(view,role) breakdown." >&2
      echo "   Common cause: orchestrator ran briefing_for_view but Agent() spawn was skipped." >&2
      echo "   Override: --skip-haiku-audit (logs override-debt as kind=haiku-spawn-audit-skipped)." >&2
      if [[ ! "$ARGUMENTS" =~ --skip-haiku-audit ]]; then
        exit 1
      fi
      ;;
    SKIP|*) echo "ℹ D-17 Haiku-spawn audit: ${HSV} — likely no UI-profile views in this phase" ;;
  esac
fi
```

### 2b-4: Generate Review Lens Plan

After RUNTIME-MAP exists, materialize the plugin contract that the remaining
review steps must execute. This is the harness-level binding between the
visible step list and the smaller checks/lenses.

```bash
LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --write
  LENS_PLAN_RC=$?
  if [ "$LENS_PLAN_RC" -ne 0 ] || [ ! -f "${PHASE_DIR}/REVIEW-LENS-PLAN.json" ]; then
    echo "⛔ Review lens plan generation failed — cannot prove plugin checklist coverage." >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_plan_generated" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"artifact\":\"REVIEW-LENS-PLAN.json\"}" \
    >/dev/null 2>&1 || true
else
  echo "⛔ Missing review lens planner: $LENS_PLAN_SCRIPT" >&2
  exit 1
fi
```
</step>

---

## STEP 5.2 — enrich TEST-GOALS (phase2c_enrich_test_goals)

<step name="phase2c_enrich_test_goals" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2c — Enrich TEST-GOALS from runtime discovery (v2.34.0+, closes #52)

Bridges the design gap between **Step 3 (click many components)** and **Step 4 (rich goals for test layer)** of the original 4-step review architecture. Without this step, every Haiku-discovered button/form/modal/tab/row-action sits dead in `views[X].elements[]` and the downstream test layer never tests it.

`enrich-test-goals.py` reads every `scan-*.json`, classifies elements (modal triggers, mutations, forms, table row actions, paging, tabs), dedupes against existing TEST-GOALS.md `interactive_controls`, and emits `${PHASE_DIR}/TEST-GOALS-DISCOVERED.md` with `G-AUTO-*` goal stubs. `/vg:test` codegen (step 5d) reads both files; auto-emitted specs land as `auto-{goal-id}.spec.ts` for visual distinction.

```bash
echo ""
echo "━━━ Phase 2c — Enrich TEST-GOALS from runtime discovery ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2c_enrich_test_goals >/dev/null 2>&1 || true

ENRICH_THRESHOLD=$(vg_config_get "review.enrich_min_elements" "3" 2>/dev/null || echo "3")

${PYTHON_BIN:-python3} .claude/scripts/enrich-test-goals.py \
  --phase-dir "$PHASE_DIR" \
  --threshold "$ENRICH_THRESHOLD"
ENRICH_RC=$?

case "$ENRICH_RC" in
  0)
    AUTO_COUNT=$(grep -c "^id: G-AUTO-" "$PHASE_DIR/TEST-GOALS-DISCOVERED.md" 2>/dev/null || echo 0)
    echo "  ✓ Phase 2c: ${AUTO_COUNT} auto-emitted goals → ${PHASE_DIR}/TEST-GOALS-DISCOVERED.md"
    emit_telemetry_v2 "review_phase2c_enriched" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment" "PASS" \
      "{\"auto_goals\":${AUTO_COUNT}}" 2>/dev/null || true
    ;;
  *)
    echo "  ⚠ Phase 2c enrichment failed (rc=${ENRICH_RC}) — TEST-GOALS-DISCOVERED.md not written."
    echo "    Test layer codegen will fall back to TEST-GOALS.md only (legacy behavior)."
    emit_telemetry_v2 "review_phase2c_failed" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment" "WARN" \
      "{\"rc\":${ENRICH_RC}}" 2>/dev/null || true
    ;;
esac

# Coverage validator: BLOCK if any view had elements scanned but no goals derived.
# This catches the failure mode where Haiku ran but classification missed everything
# (e.g. element schema drift, parser bug). Per-phase override via --skip-enrich-validate.
if [[ ! "$ARGUMENTS" =~ --skip-enrich-validate ]]; then
  ${PYTHON_BIN:-python3} .claude/scripts/enrich-test-goals.py \
    --phase-dir "$PHASE_DIR" \
    --threshold "$ENRICH_THRESHOLD" \
    --validate-only
  VALIDATE_RC=$?
  if [ "$VALIDATE_RC" -ne 0 ]; then
    echo "  ⛔ Phase 2c enrichment validation FAILED."
    echo "     Either re-run /vg:review {phase} so scanners visit those views,"
    echo "     or pass --skip-enrich-validate=\"<reason>\" to log OVERRIDE-DEBT."
    emit_telemetry_v2 "review_phase2c_coverage_gap" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment_coverage" "FAIL" \
      "{\"rc\":${VALIDATE_RC}}" 2>/dev/null || true
    exit 1
  fi
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2c_enrich_test_goals 2>/dev/null || true
```
</step>

---

## STEP 5.3 — pre-dispatch gates (phase2c_pre_dispatch_gates)

<step name="phase2c_pre_dispatch_gates" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2c-pre — Contract completeness + env preflight (v2.39.0+)

Two pre-dispatch gates close Codex critiques #1 (contract validity not gated) + #6 (env state implicit):

1. `verify-contract-completeness.py` diffs runtime/code inventory against CRUD-SURFACES.md declared resources. Flags hidden routes, undeclared resources, background jobs, webhooks.
2. `verify-env-contract.py` reads ENV-CONTRACT.md preflight_checks and verifies each (app reachable, seed data present, login works).

If contract incomplete OR env preflight fails → review aborts BEFORE spawning expensive workers (Gemini Flash workers can run $0.30-1.00 per phase; aborting pre-spawn saves token cost when env is broken).

```bash
echo ""
echo "━━━ Phase 2c-pre — Contract completeness + env preflight ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2c_pre_dispatch_gates >/dev/null 2>&1 || true

# Contract completeness gate (severity warn first release for dogfood)
COMPLETE_SEV=$(vg_config_get "review.contract_completeness.severity" "warn" 2>/dev/null || echo "warn")
${PYTHON_BIN:-python3} .claude/scripts/verify-contract-completeness.py \
  --phase-dir "$PHASE_DIR" \
  --code-root "${REPO_ROOT}" \
  --severity "$COMPLETE_SEV"
COMPLETE_RC=$?
if [ "$COMPLETE_RC" -ne 0 ] && [ "$COMPLETE_SEV" = "block" ]; then
  echo "⛔ Contract completeness BLOCK — see CONTRACT-COMPLETENESS.json"
  exit 1
fi

# Env contract preflight (mandatory if any kit:crud-roundtrip declared, optional for kit:static-sast)
if grep -q '"kit"\s*:\s*"crud-roundtrip"\|"kit"\s*:\s*"approval-flow"\|"kit"\s*:\s*"bulk-action"' "${PHASE_DIR}/CRUD-SURFACES.md" 2>/dev/null; then
  ENV_SEV=$(vg_config_get "review.env_contract.severity" "block" 2>/dev/null || echo "block")
  if [[ "$ARGUMENTS" =~ --skip-env-contract=\"([^\"]*)\" ]]; then
    ENV_REASON="${BASH_REMATCH[1]}"
    echo "  ⚠ ENV-CONTRACT skipped: $ENV_REASON (logged to OVERRIDE-DEBT)"
  else
    ${PYTHON_BIN:-python3} .claude/scripts/verify-env-contract.py \
      --phase-dir "$PHASE_DIR" \
      > "${PHASE_DIR}/.tmp/env-contract-review.txt" 2>&1
    ENV_RC=$?
    if [ "$ENV_RC" -ne 0 ] && [ "$ENV_SEV" = "block" ]; then
      echo "⛔ ENV-CONTRACT preflight FAIL — fix env or pass --skip-env-contract=\"<reason>\""
      cat "${PHASE_DIR}/.tmp/env-contract-review.txt" 2>/dev/null || true
      DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
      if [ -f "$DIAG_SCRIPT" ]; then
        "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
          --gate-id "review.env_contract" \
          --phase-dir "$PHASE_DIR" \
          --input "${PHASE_DIR}/.tmp/env-contract-review.txt" \
          --out-md "${PHASE_DIR}/.tmp/env-contract-diagnostic.md" \
          >/dev/null 2>&1 || true
        cat "${PHASE_DIR}/.tmp/env-contract-diagnostic.md" 2>/dev/null || true
      fi
      exit 1
    fi
  fi
fi

emit_telemetry_v2 "review_phase2c_pre_gates" "${PHASE_NUMBER}" \
  "review.2c-pre" "pre_dispatch_gates" "PASS" \
  "{\"contract_complete_rc\":${COMPLETE_RC:-0}}" 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2c_pre_dispatch_gates 2>/dev/null || true
```
</step>

---

## STEP 5.4 — CRUD round-trip dispatch (phase2d_crud_roundtrip_dispatch)

<step name="phase2d_crud_roundtrip_dispatch" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2d — CRUD round-trip lens dispatch (v2.35.0+, closes #51)

Dispatches Gemini Flash workers per `(resource × role)` declared with `kit: crud-roundtrip` in CRUD-SURFACES.md. Each worker runs the 8-step Read→Create→Read→Update→Read→Delete→Read round-trip per `commands/vg/_shared/transition-kits/crud-roundtrip.md`.

**Why Gemini Flash (not Claude Haiku):** $0.075/M input vs $1.00/M = 13× cheaper. Already MCP-configured (5 Playwright servers in `~/.gemini/settings.json`). Already in cross-CLI plumbing.

**Pre-flight:** auth fixture must exist. If not, run `scripts/review-fixture-bootstrap.py` first.

```bash
echo ""
echo "━━━ Phase 2d — CRUD round-trip lens dispatch ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2d_crud_roundtrip_dispatch >/dev/null 2>&1 || true

# Skip if no CRUD-SURFACES or no resources declare this kit
if [ ! -f "${PHASE_DIR}/CRUD-SURFACES.md" ]; then
  echo "  (no CRUD-SURFACES.md — skipping Phase 2d)"
elif ! grep -q '"kit"\s*:\s*"crud-roundtrip"' "${PHASE_DIR}/CRUD-SURFACES.md"; then
  echo "  (no resources with kit: crud-roundtrip — skipping Phase 2d)"
else
  # Bootstrap auth tokens if missing
  TOKENS_PATH="${PHASE_DIR}/.review-fixtures/tokens.local.yaml"
  REPO_TOKENS_PATH="${REPO_ROOT}/.review-fixtures/tokens.local.yaml"
  if [ ! -f "$TOKENS_PATH" ] && [ ! -f "$REPO_TOKENS_PATH" ]; then
    echo "  Bootstrapping auth tokens..."
    ${PYTHON_BIN:-python3} .claude/scripts/review-fixture-bootstrap.py \
      --phase-dir "$PHASE_DIR" || {
        echo "  ⚠ Auth fixture bootstrap failed — Phase 2d skipped (workers cannot authenticate)"
      }
  fi

  if [ -f "$TOKENS_PATH" ] || [ -f "$REPO_TOKENS_PATH" ]; then
    COST_CAP=$(vg_config_get "review.crud_roundtrip.cost_cap_usd" "1.50" 2>/dev/null || echo "1.50")
    CONCURRENCY=$(vg_config_get "review.crud_roundtrip.concurrency" "2" 2>/dev/null || echo "2")

    ${PYTHON_BIN:-python3} .claude/scripts/spawn-crud-roundtrip.py \
      --phase-dir "$PHASE_DIR" \
      --concurrency "$CONCURRENCY" \
      --cost-cap "$COST_CAP"
    DISPATCH_RC=$?

    if [ "$DISPATCH_RC" -eq 0 ]; then
      ARTIFACTS=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('${PHASE_DIR}/runs/INDEX.json')); print(d.get('artifacts_present', 0))" 2>/dev/null || echo "0")
      echo "  ✓ CRUD round-trip dispatch complete: ${ARTIFACTS} run artifact(s)"
      emit_telemetry_v2 "review_phase2d_dispatched" "${PHASE_NUMBER}" \
        "review.2d-crud-dispatch" "crud_roundtrip" "PASS" \
        "{\"artifacts\":${ARTIFACTS}}" 2>/dev/null || true
    else
      echo "  ⚠ CRUD round-trip dispatch failed (rc=${DISPATCH_RC})"
      emit_telemetry_v2 "review_phase2d_failed" "${PHASE_NUMBER}" \
        "review.2d-crud-dispatch" "crud_roundtrip" "FAIL" \
        "{\"rc\":${DISPATCH_RC}}" 2>/dev/null || true
    fi
  fi
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2d_crud_roundtrip_dispatch 2>/dev/null || true
```
</step>

---

## STEP 5.5 — findings derivation (phase2e_findings_merge)

<step name="phase2e_findings_merge" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2e — Findings derivation (v2.35.0+)

Reads run artifacts from Phase 2d and derives `REVIEW-FINDINGS.json` (machine-readable, deduped) + `REVIEW-BUGS.md` (Strix-style human-readable triage doc).

**No auto-route to /vg:build in v2.35.0** — manual triage during dogfood per Codex review feedback. Auto-route candidate for v2.37.0 after schema confidence/dedupe quality validated on real findings.

```bash
echo ""
echo "━━━ Phase 2e — Findings derivation ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2e_findings_merge >/dev/null 2>&1 || true

if [ -d "${PHASE_DIR}/runs" ] && [ -n "$(ls -A ${PHASE_DIR}/runs/*.json 2>/dev/null | grep -v INDEX.json)" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/derive-findings.py \
    --phase-dir "$PHASE_DIR"
  DERIVE_RC=$?

  if [ "$DERIVE_RC" -eq 0 ] && [ -f "${PHASE_DIR}/REVIEW-FINDINGS.json" ]; then
    FINDING_COUNT=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('${PHASE_DIR}/REVIEW-FINDINGS.json')); print(d.get('findings_total', 0))" 2>/dev/null || echo "0")
    echo "  ✓ ${FINDING_COUNT} finding(s) derived → ${PHASE_DIR}/REVIEW-BUGS.md"
    emit_telemetry_v2 "review_phase2e_findings" "${PHASE_NUMBER}" \
      "review.2e-findings" "findings_derive" "PASS" \
      "{\"findings\":${FINDING_COUNT}}" 2>/dev/null || true
  fi
else
  echo "  (no run artifacts to derive — skipping)"
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2e_findings_merge 2>/dev/null || true
```
</step>

---

## STEP 5.6 — adversarial coverage challenge (phase2e_post_challenge)

<step name="phase2e_post_challenge" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2e-post — Manager adversarial challenge (v2.39.0+, closes Codex critique #7)

Workers report `coverage.passed`. This step asks: "do these passes actually imply coverage?". Heuristic adversarial reducer samples N% of run artifacts and challenges each pass step:
- `pass` with empty `evidence_ref` → downgrade to `weak-pass`
- `pass` with empty `observed` block → downgrade to `weak-pass`
- `pass` with observed status mismatching expected → flagged `false-pass` (severity DEGRADED)

Output: `${PHASE_DIR}/COVERAGE-CHALLENGE.json` with downgrades + warnings. v2.40 may add LLM-driven challenge for ambiguous claims.

```bash
echo ""
echo "━━━ Phase 2e-post — Manager adversarial challenge ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2e_post_challenge >/dev/null 2>&1 || true

if [ -d "${PHASE_DIR}/runs" ] && [ -n "$(ls -A ${PHASE_DIR}/runs/*.json 2>/dev/null | grep -v INDEX.json)" ]; then
  CHALLENGE_RATE=$(vg_config_get "review.challenge.sample_rate" "25" 2>/dev/null || echo "25")
  CHALLENGE_SEV=$(vg_config_get "review.challenge.severity" "warn" 2>/dev/null || echo "warn")

  ${PYTHON_BIN:-python3} .claude/scripts/challenge-coverage.py \
    --phase-dir "$PHASE_DIR" \
    --sample-rate "$CHALLENGE_RATE" \
    --severity "$CHALLENGE_SEV"
  CHALLENGE_RC=$?

  if [ "$CHALLENGE_RC" -ne 0 ] && [ "$CHALLENGE_SEV" = "block" ]; then
    echo "⛔ Coverage challenge: false-pass steps detected. See COVERAGE-CHALLENGE.json"
    emit_telemetry_v2 "review_phase2e_post_challenge_failed" "${PHASE_NUMBER}" \
      "review.2e-post" "coverage_challenge" "BLOCK" "{}" 2>/dev/null || true
    exit 1
  fi
  emit_telemetry_v2 "review_phase2e_post_challenge" "${PHASE_NUMBER}" \
    "review.2e-post" "coverage_challenge" "PASS" \
    "{\"sample_rate\":${CHALLENGE_RATE}}" 2>/dev/null || true
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2e_post_challenge 2>/dev/null || true
```
</step>

---

## STEP 5.7 — route auto-fix tasks (phase2f_route_auto_fix)

<step name="phase2f_route_auto_fix" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2f — Route findings to /vg:build (v2.37.0+, opt-in)

Reads `REVIEW-FINDINGS.json` and emits `AUTO-FIX-TASKS.md` for findings meeting the conservative gate (severity ≥ high, confidence == high, cleanup_status == completed). `/vg:build` consumes via `--include-auto-fix` flag (opt-in v2.37, may default-on v2.38 after dogfood).

```bash
echo ""
echo "━━━ Phase 2f — Route findings to /vg:build (auto-fix loop) ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2f_route_auto_fix >/dev/null 2>&1 || true

if [ -f "${PHASE_DIR}/REVIEW-FINDINGS.json" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/route-findings-to-build.py \
    --phase-dir "$PHASE_DIR"
  ROUTE_RC=$?

  if [ "$ROUTE_RC" -eq 0 ] && [ -f "${PHASE_DIR}/AUTO-FIX-TASKS.md" ]; then
    TASK_COUNT=$(grep -c "^### Task AF-" "${PHASE_DIR}/AUTO-FIX-TASKS.md" 2>/dev/null || echo 0)
    echo "  ✓ ${TASK_COUNT} auto-fix task group(s) → AUTO-FIX-TASKS.md"
    echo "    Run /vg:build ${PHASE_NUMBER} --include-auto-fix to consume"
    emit_telemetry_v2 "review_phase2f_routed" "${PHASE_NUMBER}" \
      "review.2f-route" "auto_fix_routing" "PASS" \
      "{\"task_groups\":${TASK_COUNT}}" 2>/dev/null || true
  else
    echo "  (no qualifying findings to route)"
  fi
else
  echo "  (no REVIEW-FINDINGS.json — skipping)"
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2f_route_auto_fix 2>/dev/null || true
```
</step>
