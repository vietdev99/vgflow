# review lens-dispatch (STEP 4 — architectural enforcement)

Single step `phase2_5_recursive_lens_probe` covers Phase 2b-2.5 — the
recursive-lens-probe layer that deep-dives every interesting clickable
through bug-class lenses (authz-negative, csrf, idor, ssrf, ...).

## Why mandatory

19 production lens probes cover security/UI/business surfaces. Without
forced dispatch, prior dogfood showed AI cherry-picks 3-4 lenses, missing
critical findings (phase 3.2 filter pending bug went undetected for 2
rounds). The 5-step dispatch chain (emit-plan → spawn-with-plan →
verify-coverage → render-matrix → blocking-gate-on-fail) is a trust
anchor: every APPLICABLE dispatch must produce a matching artifact, or
the orchestrator opens `blocking_gate_prompt_emit` and offers the user 4
options instead of `exit 1`.

<HARD-GATE>
You MUST execute this step unless `--skip-recursive-probe="<reason>"` is
set AND override-debt entry exists. Stop hook checks
`review.lens_phase.entered` event; missing = run-complete blocked.

You MUST NOT cherry-pick individual lenses. `LENS_MAP` in
`spawn_recursive_probe.py` enforces full element-class → lens mapping.
Skipping a lens is impossible unless the eligibility gate (6
preconditions) declines it (audit trail in `.recursive-probe-skipped.yaml`).

You MUST run lens-plan staleness check before dispatch. If stale,
regenerate via `python3 scripts/review-lens-plan.py --phase-dir
${PHASE_DIR}` and retry.

You MUST run the provider-native 3-axis preflight (RECURSION_MODE /
PROBE_MODE / TARGET_ENV) BEFORE the bash block. The anti-forge guard at
the top of the bash block aborts loud (exit 2 + telemetry) if all three
env vars are unset and `VG_NON_INTERACTIVE != 1` — i.e. the LLM lazy-
skipped the markdown narrative pre-flight.

The Tool name for ANY subagent spawn in this step is `Agent` (not `Task`)
per plan §C — Codex correction. The dispatch script `spawn_recursive_probe.py`
itself owns its worker spawning; the orchestrator only invokes the
script with the right CLI args.

vg-load convention: per-lens worker briefing should call
`vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>`
or `vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN` for
context, NOT flat reads of the whole API-CONTRACTS.md / TEST-GOALS.md.
This is enforced inside `spawn_recursive_probe.py` worker prompts (Phase
A — deferred), not in this orchestrator-layer ref.
</HARD-GATE>

---

## STEP 4.1 — phase2_5_recursive_lens_probe

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

**Pre-step: emit lens_phase.entered event (Task 2 wired) + staleness check (Task 3 wired):**

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2_5_recursive_lens_probe >/dev/null 2>&1 || true

# Task 3 — staleness check on REVIEW-LENS-PLAN.json
"${PYTHON_BIN:-python3}" .claude/scripts/review-lens-plan.py \
  --check-staleness \
  --phase-dir "${PHASE_DIR}"
STALE_RC=$?
if [ "$STALE_RC" -eq 2 ]; then
  echo "⛔ REVIEW-LENS-PLAN.json is stale — regenerate before dispatch:" >&2
  echo "   ${PYTHON_BIN:-python3} .claude/scripts/review-lens-plan.py --phase-dir ${PHASE_DIR}" >&2
  echo "   Then re-run /vg:review ${PHASE_NUMBER}" >&2
  exit 2
fi

# Task 2 — emit lens_phase.entered event (Stop hook gate)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.lens_phase.entered" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
```

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

# Per-lens telemetry (Task 1 wired) — emitted by spawn_recursive_probe.py per
# (element × lens × role) dispatch:
#   review.lens.<name>.dispatched
#   review.lens.<name>.completed
# Aggregator below summarizes per-lens success rate; >50% failure on any single
# lens triggers a 3-line stderr block-with-retry-suggestion (Task 1 stretch).

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

**Step-end markers + lens_phase.completed event (Task 2 wired):**

```bash
# Aggregate lens dispatch counts for the completed event payload.
LENS_DISPATCHED=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    p = json.load(open('${PHASE_DIR}/LENS-DISPATCH-PLAN.json'))
    print(len(p.get('dispatches', [])))
except: print(0)
")
LENS_COMPLETED=$(ls "${PHASE_DIR}/runs"/*.json 2>/dev/null | wc -l | tr -d ' ')

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.lens_phase.completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"lens_count_dispatched\":${LENS_DISPATCHED:-0},\"lens_count_completed\":${LENS_COMPLETED:-0}}" \
  >/dev/null 2>&1 || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_recursive_lens_probe" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_recursive_lens_probe.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_5_recursive_lens_probe 2>/dev/null || true
```

</step>
