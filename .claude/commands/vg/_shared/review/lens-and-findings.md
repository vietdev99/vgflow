<step name="phase2_5_recursive_lens_probe" profile="web-fullstack,web-frontend-only" mode="full">

#### 2b-2.5: Recursive Lens Probe (v2.40, manager dispatcher)

**Purpose:** After parallel Haiku scanners (2b-2) complete, run the recursive lens probe layer to deep-dive each interesting clickable through bug-class lenses (authz-negative, csrf, idor, ssrf, ...). Manager dispatcher reads scan-*.json, classifies clickables into element classes, picks lenses per class, spawns workers in parallel (auto), generates prompt files (manual), or both (hybrid). Goals discovered by lens probes are merged single-writer into TEST-GOALS-DISCOVERED.md.

**Task 36b dispatch chain (wires Task 26 infrastructure):**
Phase 2b-2.5 now runs a 5-step chain:
1. `emit-dispatch-plan.py` — emit LENS-DISPATCH-PLAN.json (trust anchor, declares all APPLICABLE dispatches before any spawn)
2. `spawn_recursive_probe.py --dispatch-plan` — iterate per dispatch with `lens_tier_dispatcher.select_tier()` per-lens model selection + `plan_hash` anti-reuse stamp
3. `verify-lens-runs-coverage.py` — assert every APPLICABLE dispatch has a matching artifact
4. `lens-coverage-matrix.py` — render LENS-COVERAGE-MATRIX.md (always, even on failure)
5. Coverage failure → `blocking_gate_prompt_emit` (Task 33 wrapper, NOT `exit 1`)

**Eligibility (6 rules — all must pass unless `--skip-recursive-probe` is set):**
1. `.phase-profile` declares `phase_profile ∈ {feature, feature-legacy, hotfix}`
2. `.phase-profile` declares `surface ∈ {ui, ui-mobile}` (NOT visual-only)
3. `CRUD-SURFACES.md` declares ≥1 resource
4. `SUMMARY.md` / `RIPPLE-ANALYSIS.md` lists ≥1 `touched_resources` intersecting CRUD
5. `surface != 'visual'`
6. `ENV-CONTRACT.md` present, `disposable_seed_data: true`, all `third_party_stubs` stubbed

If eligibility fails → write `.recursive-probe-skipped.yaml` and continue to 2b-3 (no error).

<MANDATORY_GATE>
**You MUST run the provider-native user prompt below BEFORE invoking the bash block** — unless `--non-interactive` / `VG_NON_INTERACTIVE=1` is set, OR all three axes (`--recursion`, `--probe-mode`, `--target-env`) were already passed on the `/vg:review` command line.
- Do NOT skip the pre-flight because "defaults look fine" — the operator must explicitly choose recursion depth, probe execution mode, and target environment per run.
- Do NOT delegate the prompt to `spawn_recursive_probe.py` stdin — Claude Code's bash sandbox makes `sys.stdin.isatty()` return False, so script-side prompts silently fall back to defaults.
- The bash block at the end of this section will refuse to launch (loud abort + telemetry) if it detects an interactive run with no env vars set, which means the pre-flight was skipped.
- Claude Code path: use `AskUserQuestion`. Codex path: ask the same concise questions in the main Codex thread or closest available Codex input UI.
- After the prompt answers, emit telemetry event `review.recursive_probe.preflight_asked` (logs the chosen axes for audit).
</MANDATORY_GATE>

**Pre-flight (v2.41.1) — operator config via provider-native prompt:**

> ⚠ Why this lives in the command layer (not script stdin):
> Claude Code wraps bash in a sandbox where `sys.stdin.isatty()` returns `False`,
> so the script-side `input()` prompts in `spawn_recursive_probe.py` silently fall
> back to defaults (`light` / `auto` / `sandbox`) without the operator ever
> seeing them. To deliver an actual interactive UX under Claude Code, the
> command layer asks **before** invoking bash, then exports the answers as
> env vars that bash forwards via flags.

Phase 2b-2.5 has three operator-controlled axes. The orchestrator MUST resolve
all three before invoking bash:

| Env var | Source priority | Default |
|---|---|---|
| `RECURSION_MODE` | (1) `--recursion` CLI flag → (2) provider-native prompt → (3) `light` | `light` |
| `PROBE_MODE`     | (1) `--probe-mode` CLI flag → (2) provider-native prompt → (3) `auto` | `auto` |
| `TARGET_ENV`     | (1) `--target-env` CLI flag → (2) `vg.config review.target_env` → (3) provider-native prompt → (4) `sandbox` | `sandbox` |

**Resolution procedure (the orchestrator runs these BEFORE the bash block):**

1. **Parse `/vg:review` CLI args.** For each of `--recursion`, `--probe-mode`,
   `--target-env` that the operator passed, set the matching env var
   (`RECURSION_MODE` / `PROBE_MODE` / `TARGET_ENV`) and skip its prompt.

2. **Skip prompts entirely if `VG_NON_INTERACTIVE=1`** (CI / piped runs) —
   downstream defaults apply.

3. **For each axis still unset, run the provider-native prompt** with the spec below.
   Ask in this order, ONE call per axis (so operator answers can short-circuit
   the next prompt — e.g. picking `skip` for probe-mode means we skip the
   target-env question because no probes will fire).

   **Question 1 — `RECURSION_MODE` (depth/coverage envelope):**
   - `light` *(recommended)* — ~15 workers, depth 2, goal cap 50. Quick coverage on touched resources only.
   - `deep` — ~40 workers, depth 3, goal cap 150. Typical dogfood pass.
   - `exhaustive` — ~100 workers, depth 4, goal cap 400. Pre-release sweep; expect ≥30min wall-clock.

   **Question 2 — `PROBE_MODE` (execution strategy):**
   - `auto` *(recommended)* — VG spawns Gemini Flash subprocess workers end-to-end.
   - `manual` — VG generates per-tool prompt files (`recursive-prompts/{codex,gemini}/`) for paste; operator runs CLI session, drops artifacts in `runs/<tool>/`, VG verifies. Pick when subprocess sandboxing isn't available.
   - `hybrid` — auto for high-confidence lenses (authz-negative, idor, csrf, ...), manual for human-judgment ones (business-logic, ssrf, auth-jwt). Routing comes from `vg.config review.recursive_probe.hybrid_routing`.
   - `skip` — emit `.recursive-probe-skipped.yaml` and continue to 2b-3. Logs OVERRIDE-DEBT critical with reason `"interactive: operator chose skip"`. Use when the recursive layer would be redundant (e.g. follow-up review of a phase that already passed 2b-2.5).

   **Question 3 — `TARGET_ENV` (deploy environment policy):** *only ask if probe-mode ≠ skip.*
   - `local` — full mutations OK, unlimited budget. Pick for local dev runs.
   - `sandbox` *(recommended)* — full mutations OK, 50-mutation/phase budget, disposable seed data assumed.
   - `staging` — mutations OK, `lens-input-injection` blocked, 25-mutation budget, shared-env hygiene.
   - `prod` — **READ-ONLY** (no POST/PUT/PATCH/DELETE), only safe lenses fire. Requires the operator to also pass `--i-know-this-is-prod=<reason>` on the next invocation (hard gate, logs OVERRIDE-DEBT critical).

4. **Export the resolved values** so the bash block sees them:

   ```bash
   export RECURSION_MODE PROBE_MODE TARGET_ENV
   ```

5. **If the operator chose `skip` for probe-mode**, also set
   `SKIP_RECURSIVE_PROBE="interactive: operator chose skip"` before bash.

**Bash invocation:**

```bash
# v2.41.1 — env vars resolved by the provider-native pre-flight above.
# Bash forwards each axis ONLY if set; the script's argparse defaults apply
# otherwise (matches CI / VG_NON_INTERACTIVE=1 contract).
SKIP_REASON="${SKIP_RECURSIVE_PROBE:-}"

# v2.41.2 — anti-forge guard: if the orchestrator skipped the provider-native prompt
# pre-flight (no env vars set + not in CI), refuse to launch with bare defaults.
# This catches the regression where Phase 2b-2.5 silently ran with light/auto/
# sandbox because the markdown narrative pre-flight was lazy-skipped by the LLM.
if [[ -z "${RECURSION_MODE:-}" && -z "${PROBE_MODE:-}" && -z "${TARGET_ENV:-}" \
      && "${VG_NON_INTERACTIVE:-0}" != "1" ]]; then
  echo "" >&2
  echo "⛔ Phase 2b-2.5 pre-flight skipped." >&2
  echo "   The MANDATORY_GATE above requires provider-native prompt to run BEFORE this bash block" >&2
  echo "   so the operator can choose recursion depth / probe-mode / target-env." >&2
  echo "   None of the three env vars (RECURSION_MODE / PROBE_MODE / TARGET_ENV) are set." >&2
  echo "" >&2
  echo "   Fix one of the following:" >&2
  echo "   1. Run the provider-native prompt to ask the operator (recommended for interactive runs)" >&2
  echo "   2. Pass --recursion / --probe-mode / --target-env on the /vg:review CLI" >&2
  echo "   3. Set VG_NON_INTERACTIVE=1 to accept defaults (CI / scripted runs only)" >&2
  echo "   4. Pass --skip-recursive-probe=<reason> to skip Phase 2b-2.5 entirely" >&2
  echo "" >&2
  emit_telemetry_v2 "review.recursive_probe.preflight_skipped" "${PHASE_NUMBER}" \
    --tag "severity=block" 2>/dev/null || true
  exit 2
fi

ARGS=( --phase-dir "$PHASE_DIR" )
if [[ -n "${RECURSION_MODE:-}" ]]; then
  ARGS+=( --mode "$RECURSION_MODE" )
fi
if [[ -n "${PROBE_MODE:-}" ]]; then
  ARGS+=( --probe-mode "$PROBE_MODE" )
fi
if [[ -n "${TARGET_ENV:-}" ]]; then
  ARGS+=( --target-env "$TARGET_ENV" )
fi
if [[ -n "$SKIP_REASON" ]]; then
  ARGS+=( --skip-recursive-probe "$SKIP_REASON" )
fi
if [[ "${VG_NON_INTERACTIVE:-0}" == "1" ]]; then
  ARGS+=( --non-interactive )
fi
# v2.65.0 A1 — parallel lens probe dispatch (default 1 = back-compat sequential).
ARGS+=( --parallel "${REVIEW_PARALLEL_WORKERS:-1}" )

# v2.41.2 — pre-flight succeeded; emit telemetry so audit can confirm prompts ran.
emit_telemetry_v2 "review.recursive_probe.preflight_asked" "${PHASE_NUMBER}" \
  --tag "recursion=${RECURSION_MODE:-default}" \
  --tag "probe_mode=${PROBE_MODE:-default}" \
  --tag "target_env=${TARGET_ENV:-default}" 2>/dev/null || true

# Task 36b — Lens dispatch enforcement (wires Task 26 infrastructure).

# Skip-mode escape (existing user decision — skip probe means skip coverage gate too)
if [ -f "${PHASE_DIR}/.recursive-probe-skipped.yaml" ]; then
  echo "▸ Phase 2b-2.5 skipped per .recursive-probe-skipped.yaml — coverage gate bypassed"
else

  # 1. Emit dispatch plan FIRST (trust anchor — declares all APPLICABLE dispatches)
  "${PYTHON_BIN:-python3}" .claude/scripts/lens-dispatch/emit-dispatch-plan.py \
    --phase-dir "${PHASE_DIR}" \
    --phase "${PHASE_NUMBER}" \
    --profile "$(python3 -c "import yaml,sys; d=yaml.safe_load(open('${PHASE_DIR}/.phase-profile').read()); print(d.get('phase_profile','web-fullstack'))" 2>/dev/null || echo "web-fullstack")" \
    --review-run-id "${REVIEW_RUN_ID:-$(date +%s)}" \
    --output "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" || {
    echo "⛔ Phase 2b-2.5: emit-dispatch-plan.py failed — cannot enforce lens coverage" >&2
    exit 1
  }

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_dispatch_emitted" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"plan_path\":\"${PHASE_DIR}/LENS-DISPATCH-PLAN.json\"}" \
    >/dev/null 2>&1 || true

  # 2. Add --dispatch-plan flag so spawn_recursive_probe uses Task 26 tier dispatcher
  ARGS+=( --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" )

fi

python scripts/spawn_recursive_probe.py "${ARGS[@]}"

# Post-spawn: coverage gate + matrix (only when probe actually ran)
if [ ! -f "${PHASE_DIR}/.recursive-probe-skipped.yaml" ]; then

  # 3. Coverage gate — assert every APPLICABLE dispatch has matching artifact
  "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-lens-runs-coverage.py \
    --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
    --runs-dir "${PHASE_DIR}/runs" \
    --phase "${PHASE_NUMBER}" \
    --evidence-out "${PHASE_DIR}/.lens-coverage-evidence.json"
  COVERAGE_RC=$?

  # 4. Render coverage matrix (always — gives user the picture even on failure)
  "${PYTHON_BIN:-python3}" .claude/scripts/aggregators/lens-coverage-matrix.py \
    --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
    --runs-dir "${PHASE_DIR}/runs" \
    --output "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md" || true

  # 5. Coverage failure → Task 33 wrapper (NOT exit 1 — user gets 4 options)
  if [ "$COVERAGE_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.lens_coverage_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence\":\"${PHASE_DIR}/.lens-coverage-evidence.json\"}" \
      >/dev/null 2>&1 || true

    # Task 33 wrapper: present 4 options
    # [a] auto-fix-spawn-missing-lenses / [s] skip-with-override / [r] amend / [x] abort
    source scripts/lib/blocking-gate-prompt.sh
    blocking_gate_prompt_emit "lens_coverage_blocked" \
      "${PHASE_DIR}/.lens-coverage-evidence.json" \
      "error" \
      "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
    # AI controller calls AskUserQuestion → re-invokes Leg 2
    # Branch on Leg 2 exit code per blocking-gate-prompt-contract.md
  fi

fi
```

**Argparse forwarding (entry point of /vg:review):**

```bash
# /vg:review accepts these flags. The orchestrator parses them BEFORE the
# Provider-native pre-flight runs and exports the matching env var so the
# operator only gets prompted for axes they didn't pre-supply:
#   --recursion={light,deep,exhaustive}     → export RECURSION_MODE=$value
#   --probe-mode={auto,manual,hybrid}       → export PROBE_MODE=$value
#   --target-env={local,sandbox,staging,prod} → export TARGET_ENV=$value
#   --skip-recursive-probe="<reason>"       → export SKIP_RECURSIVE_PROBE=$value
#   --non-interactive                       → export VG_NON_INTERACTIVE=1 (suppress provider prompts + stdin prompts)
#   --i-know-this-is-prod="<reason>"        → forwarded as-is (prod-safety opt-in)
```

**Manual mode (`PROBE_MODE=manual`):**

The dispatcher writes prompt files to `${PHASE_DIR}/recursive-prompts/MANIFEST.md` and pauses. Operator runs each prompt against their preferred CLI agent (gemini/codex/claude), drops artifacts back into `${PHASE_DIR}/runs/<tool>/`, then resumes the pipeline. The verifier runs automatically when the user signals completion:

```bash
if [[ "$PROBE_MODE" == "manual" ]]; then
  echo "Manual prompts written. Follow ${PHASE_DIR}/recursive-prompts/MANIFEST.md, drop artifacts in runs/, then press Enter."
  if [[ "${VG_NON_INTERACTIVE:-0}" != "1" ]]; then
    read -r _
  fi
  python scripts/verify_manual_run_artifacts.py --phase-dir "$PHASE_DIR" || exit 1
fi
```

**Hybrid mode:** dispatcher routes per-lens to auto vs manual based on `vg.config.md → review.recursive_probe.hybrid_routing`. See [vg:_shared:config-loader] for resolution.

**Aggregation (single-writer, end of 2b-2.5):**

```bash
python scripts/aggregate_recursive_goals.py --phase-dir "$PHASE_DIR" --mode "$RECURSION_MODE"
# Writes TEST-GOALS-DISCOVERED.md (G-RECURSE-* level-3 entries) + recursive-goals-overflow.json.
```

**Idempotency:** Re-running 2b-2.5 reuses existing `runs/` artifacts; canonical-key dedup in aggregator prevents duplicate goal stubs.

**Failure semantics:** Eligibility fail → skip block (continue). Worker fail → recorded in `runs/INDEX.json`, does not abort pipeline. Manual mode timeout → operator re-runs; no automatic retry.

</step>

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
   
5. Spawn additional Haiku agents if gaps found → collect → merge

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

Derive `${PHASE_DIR}/RUNTIME-MAP.md` from JSON (human-readable summary):
```markdown
# Runtime Map — Phase {phase}
Generated from: RUNTIME-MAP.json | Build: {sha}

## Views ({N} discovered)
### {view_path} ({role})
{snapshot_summary}
Elements: {N} interactive ({visited}/{total} visited)

## Goal Sequences ({passed}/{total} passed)
### {goal_id}: {description}
  1. {do}: {label} → {observe}
  2. {do}: {label} → {observe}
  ...
  Result: {passed|failed}

## Free Exploration ({N} elements, {issues} issues found)
## Errors ({N})
```

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

<step name="phase2f_route_auto_fix" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2f — Route findings to /vg:build (v2.37.0+, opt-in)

Reads `REVIEW-FINDINGS.json` and emits `AUTO-FIX-TASKS.md` for findings meeting the conservative gate (severity ≥ high, confidence == high, cleanup_status == completed). `/vg:build` consumes via `--include-auto-fix` flag (opt-in v2.37, may default-on v2.38 after dogfood).

### v2.67.0 #160 — BLOCKED 5-reason taxonomy + reason-based routing

GOAL-COVERAGE-MATRIX BLOCKED status is no longer monolithic. `scripts/challenge-coverage.py` now exposes `BlockedReason` enum + `classify_blocked()` so each BLOCKED goal carries one of:

| Reason | Routing |
|---|---|
| `APP_BLOCKED` | route to `/vg:build` (real bug, code shipped wrong) |
| `WORKFLOW_BLOCKED` | flag tool issue — file workflow bug, do NOT route |
| `PREREQ_MISSING` | propose `/vg:amend ${owner_phase}` — upstream patch was DEFERRED |
| `EXTERNAL_REQUIRED` | operator action — OAuth/WS/reset token needed before re-probe |
| `PROBE_INVALID` | flag probe bug (e.g., WS endpoint hit as GET) — fix probe, re-run; do NOT route |

Auto-fix routing in this phase only sends `APP_BLOCKED` goals to `/vg:build`. Other reasons are surfaced as separate handling text in `AUTO-FIX-TASKS.md` and not pushed to the build queue. This prevents the auto-fix loop from looping on goals where /vg:build cannot help (probe bugs, missing OAuth, deferred upstream).

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

    # v2.67.0 #160 — surface BLOCKED reason taxonomy if present in COVERAGE-CHALLENGE.json
    # so the user knows which BLOCKED goals are NOT routed (PREREQ_MISSING / EXTERNAL_REQUIRED /
    # PROBE_INVALID / WORKFLOW_BLOCKED) and need separate handling.
    COVERAGE_CHALLENGE="${PHASE_DIR}/COVERAGE-CHALLENGE.json"
    if [ -f "$COVERAGE_CHALLENGE" ]; then
      ${PYTHON_BIN:-python3} - "$COVERAGE_CHALLENGE" <<'PY' 2>/dev/null || true
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)
reasons = data.get("blocked_reasons") or {}
if not reasons:
    sys.exit(0)
# Reasons NOT routable to /vg:build
non_app = {k: v for k, v in reasons.items() if k != "APP_BLOCKED"}
if not non_app:
    sys.exit(0)
print("  ⚠ BLOCKED goals NOT routed to /vg:build (reason-based handling required):")
for reason, count in non_app.items():
    if reason == "PREREQ_MISSING":
        hint = "→ /vg:amend ${owner_phase}"
    elif reason == "EXTERNAL_REQUIRED":
        hint = "→ operator action (OAuth/WS/reset)"
    elif reason == "PROBE_INVALID":
        hint = "→ probe bug — fix probe + re-run"
    elif reason == "WORKFLOW_BLOCKED":
        hint = "→ workflow/tool issue — file bug"
    else:
        hint = ""
    print(f"    {reason}: {count} {hint}")
PY
    fi

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
