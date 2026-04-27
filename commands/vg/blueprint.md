---
name: vg:blueprint
description: Plan + API contracts + verify + CrossAI review — 4 sub-steps before build
argument-hint: "<phase> [--skip-research] [--gaps] [--reviews] [--text] [--crossai-only] [--skip-crossai] [--from=<substep>] [--override-reason=<text>] [--allow-missing-persistence] [--allow-missing-org] [--allow-crossai-inconclusive] [--apply-amendments] [--skip-amendment-check]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
  - TaskCreate
  - TaskUpdate
  - SlashCommand
runtime_contract:
  # Deterministic Stop-hook check. If ANY required artifact is missing when
  # orchestrator tries to Stop after /vg:blueprint <phase>, hook exits 2 and
  # tells AI to continue. Paths use ${PHASE_DIR} = .vg/phases/{phase}-*.
  must_write:
    - "${PHASE_DIR}/PLAN.md"
    - "${PHASE_DIR}/API-CONTRACTS.md"
    - "${PHASE_DIR}/TEST-GOALS.md"
    # v2.5 anti-forge (2026-04-23): CrossAI XML result files REQUIRED
    # unless explicit --skip-crossai flag. Previously AI could touch
    # 2d_crossai_review.done marker without actually invoking CLIs
    # (observed gap in phase 7.14 blueprint run — 0 crossai events + empty
    # crossai/ dir despite marker present). Closes forge surface.
    - path: "${PHASE_DIR}/crossai/result-*.xml"
      glob_min_count: 1
      required_unless_flag: "--skip-crossai"
  must_touch_markers:
    # Subset of filter-steps.py output (feature profile). Missing any =
    # step silently skipped = BLOCK Stop.
    - "2a_plan"
    - "2b_contracts"
    - "2b5_test_goals"
    - "2c_verify"
    # OHOK-9 (d): crossai marker waived when --skip-crossai flag present
    # (aligns with forbidden_without_override — user can opt-out via
    # override-debt, marker check matches).
    - name: "2d_crossai_review"
      required_unless_flag: "--skip-crossai"
  must_emit_telemetry:
    # Events that MUST land in .vg/telemetry.jsonl for this phase+command.
    # Hook greps event_type + phase + command match.
    # v2.5.1 anti-forge (2026-04-24): tasklist visibility — user MUST see
    # authoritative step list at flow start. emit-tasklist.py helper runs
    # filter-steps.py + echoes list + emits event. Missing = AI started
    # flow without showing user what it plans to do = contract violation.
    - event_type: "blueprint.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.plan_written"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.contracts_generated"
      phase: "${PHASE_NUMBER}"
    # v2.5 anti-forge (2026-04-23): crossai.verdict event proves the CrossAI
    # step actually invoked the CLIs + computed a verdict. Paired with
    # must_write crossai/result-*.xml files. Together they eliminate
    # the "touch marker but skip work" forge surface. Waived by --skip-crossai.
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
  forbidden_without_override:
    # If these flags present, hook also checks override-debt register updated.
    # OHOK v2 Day 1: added --skip-design-check + --skip-crossai. These were
    # silently honored before → dogfood phase 14 exposed /vg:review over-skip
    # pattern (OD-149); phase 13 UI-SPEC had 10 orphan colors + 18 undefined
    # CSS vars (retroactive validator finding). Enforcement path: validator
    # vg-design-coherence BLOCKs unless either the UI-SPEC is clean OR
    # --skip-design-check + valid --override-reason present + rationalization
    # guard PASS/FLAG verdict.
    - "--allow-missing-persistence"
    - "--allow-missing-org"
    - "--allow-crossai-inconclusive"
    - "--skip-crossai"
    - "--override-reason"
---

<rules>
1. **CONTEXT.md required** — must exist before blueprint. No CONTEXT = BLOCK.
2. **4 sub-steps in order** — 2a Plan → 2b Contracts → 2c Verify → 2d CrossAI. No skipping.
3. **API contracts BEFORE build** — contracts are INPUT to build, not POST-build check.
4. **Verify is grep-only** — step 2c uses no AI. Pure grep diff. Fast (<5 seconds).
5. **Max 400 lines per agent** — planner gets ~300, contract gen gets ~200.
6. **ORG 6-dimension gate** — plan MUST answer: Infra, Env, Deploy, Smoke, Integration, Rollback.
7. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action, run:
   `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
   Preflight: `create_task_tracker` runs `filter-steps.py --command blueprint.md --profile $PROFILE --output-ids`
   and MUST create tasks matching exactly that list (count check). Step 3_complete verifies markers.
</rules>

<objective>
Step 2 of V5 pipeline. Heaviest planning step — 4 sub-steps produce PLAN.md + API-CONTRACTS.md, both verified.

Pipeline: specs → scope → **blueprint** → build → review → test → accept

Sub-steps:
- 2a: PLAN — GSD planner creates tasks + acceptance criteria (~300 lines)
- 2b: CONTRACTS — Generate API contracts from code/specs (~200 lines)
- 2c: VERIFY 1 — Grep diff contracts vs code/specs (no AI, <5 sec)
- 2d: CROSSAI REVIEW — 2 CLIs review plan + contracts + context
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

<step name="0_amendment_preflight">
## Step 0: Scope Amendment Preflight (v1.14.1+ NEW)

Before planning, enforce any `config_amendments_needed` locked during /vg:scope (e.g. new surfaces proposed in Round 2 via surface-gap detector). Running blueprint with stale config → tasks spawn against wrong surface paths → silent failure downstream.

```bash
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-blueprint" "0_amendment_preflight" 2>&1 || true

# v2.2 — register run with orchestrator (idempotent if UserPromptSubmit hook
# already fired). Hard-fail if orchestrator unreachable.
# Round-4 BLOCK fix: defensive parse PHASE_NUMBER from ARGUMENTS before run-start
# (argument parsing proper happens in step 1, but telemetry needs phase-id now).
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start \
    vg:blueprint "${PHASE_NUMBER}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}


source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/amendment-preflight.sh"

# Mode from flag
AMEND_MODE="block"   # default
if [[ "$ARGUMENTS" =~ --apply-amendments ]]; then
  AMEND_MODE="apply"
elif [[ "$ARGUMENTS" =~ --skip-amendment-check ]]; then
  AMEND_MODE="warn"
fi

amendment_block_if_pending "${PHASE_DIR}" ".claude/vg.config.md" "$AMEND_MODE"
preflight_rc=$?

if [ $preflight_rc -ne 0 ]; then
  echo ""
  echo "Retry options:"
  echo "  /vg:blueprint ${PHASE_NUMBER} --apply-amendments     # auto-apply to config"
  echo "  /vg:blueprint ${PHASE_NUMBER} --skip-amendment-check # debt mode"
  exit 1
fi

# If amendments were applied, commit the config change before proceeding
if [ "$AMEND_MODE" = "apply" ]; then
  if ! git diff --quiet .claude/vg.config.md 2>/dev/null; then
    git add .claude/vg.config.md
    git commit -m "config(${PHASE_NUMBER}): apply scope amendments

Auto-applied via /vg:blueprint ${PHASE_NUMBER} --apply-amendments.
See PHASE_DIR/CONTEXT.md scope decisions for rationale."
  fi
fi
```

Scanner is authoritative: reads `PIPELINE-STATE.steps.scope.config_amendments_needed[]` array (populated by `/vg:scope` step 5). Enrichment pulls surface name + paths + stack from decision YAML snippet in CONTEXT.md. Generic (non-surface) amendments require manual edit — preflight blocks, user edits, re-runs.

**Rationale:** surfaces config drives multi-surface gate, design-system lookup, multi-platform E2E routing. Missing surface → silent workflow misalignment. Forcing apply before tasks spawn ensures planner + executor see correct config.

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "0_amendment_preflight" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_amendment_preflight.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 0_amendment_preflight 2>/dev/null || true
```
</step>

<step name="1_parse_args">
Extract from `$ARGUMENTS`: phase_number (required), plus optional flags:
- `--skip-research`, `--gaps`, `--reviews`, `--text` — pass through to GSD planner
- `--crossai-only` — skip 2a/2b/2c, run only 2d (CrossAI review). Requires PLAN*.md + API-CONTRACTS.md to exist.
- `--skip-crossai` — run full blueprint but skip CrossAI review in 2d-6 (deterministic gate only). Faster + cheaper. Use when phase is small/iterative and CrossAI third-opinion adds little.
- `--from=2b` / `--from=2c` / `--from=2d` — resume from specific sub-step. Skip prior sub-steps (require their artifacts to exist via R2 assertion).
- `--override-reason="<text>"` — bypass R2/R5/R7 gates, log to override-debt register.
- `--allow-missing-persistence` — bypass Rule 3b persistence check gate (2b5). Log debt.
- `--allow-missing-org` — bypass Rule 6 ORG 6-dim critical gate (2a5). Log debt.
- `--allow-crossai-inconclusive` — treat CrossAI timeout/crash as non-blocking (2d-6). Log debt.

Validate: phase exists. Determine `$PHASE_DIR`.

**Skip logic:**
- `--crossai-only` → jump directly to step 2d_crossai_review
- `--from=2b` → skip 2a, start at 2b_contracts (PLAN*.md must exist)
- `--from=2c` → skip 2a+2b, start at 2c_verify (PLAN*.md + API-CONTRACTS.md must exist)
- `--from=2d` → same as `--crossai-only`

### R2 skip prerequisite assertion (v1.14.4+)

Rule 2 khai "4 sub-steps in order". `--from=X` là resume feature, nhưng phải verify prior steps thực sự đã complete — không cho silent skip.

```bash
# v1.15.2 — register run so Stop hook can verify runtime_contract evidence
# (blueprint has no session_start; explicit call here.)
type -t vg_run_start >/dev/null 2>&1 && \
  vg_run_start "vg:blueprint" "${PHASE_NUMBER:-unknown}" "${ARGUMENTS:-}"

# v2.5.1 anti-forge (2026-04-24): user sees authoritative step list at start.
# Emits blueprint.tasklist_shown event proving user had visibility.
# Required by runtime_contract — AI cannot silently skip this.
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:blueprint" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true

FROM_STEP=""
if [[ "$ARGUMENTS" =~ --from=(2b|2c|2d|2b5|2b6|2b7) ]]; then
  FROM_STEP="${BASH_REMATCH[1]}"
fi

if [ -n "$FROM_STEP" ] || [[ "$ARGUMENTS" =~ --crossai-only ]]; then
  [[ "$ARGUMENTS" =~ --crossai-only ]] && FROM_STEP="2d"

  MISSING_PREREQ=""
  case "$FROM_STEP" in
    2b|2b5|2b6|2b7)
      # Needs 2a done → PLAN*.md exists + marker
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/.step-markers/2a_plan.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2a_plan"
      ;;
    2c)
      # Needs 2a + 2b + 2b5 done
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/API-CONTRACTS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} API-CONTRACTS.md(step 2b)"
      [ -f "${PHASE_DIR}/TEST-GOALS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} TEST-GOALS.md(step 2b5)"
      ;;
    2d)
      # Needs all above + 2c verify marker
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/API-CONTRACTS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} API-CONTRACTS.md(step 2b)"
      [ -f "${PHASE_DIR}/TEST-GOALS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} TEST-GOALS.md(step 2b5)"
      [ -f "${PHASE_DIR}/.step-markers/2c_verify.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2c_verify"
      ;;
  esac

  if [ -n "$MISSING_PREREQ" ]; then
    echo "⛔ R2 skip prerequisite missing for --from=${FROM_STEP}:"
    for p in $MISSING_PREREQ; do echo "   - ${p}"; done
    echo ""
    echo "Rule 2 khai: 4 sub-steps must run IN ORDER. --from=${FROM_STEP} bypass prior steps"
    echo "nhưng prior artifacts chưa tồn tại → có nghĩa 2a/2b/2c chưa thực sự complete."
    echo ""
    echo "Fix: chạy full /vg:blueprint ${PHASE_NUMBER} (bỏ --from) để build đủ artifacts."
    echo "Override (NOT recommended): --override-reason='<reason>' (log debt)"
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      exit 1
    else
            if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "blueprint_r2_skip_missing" "${PHASE_NUMBER}" "blueprint.1" "blueprint_r2_skip_missing" "FAIL" "{}"
      fi
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "blueprint-r2-skip-missing" "${PHASE_NUMBER}" "--from=${FROM_STEP} with missing: ${MISSING_PREREQ}" "$PHASE_DIR"
      fi
      echo "⚠ --override-reason set — proceeding despite R2 breach, logged to debt"
    fi
  else
    echo "✓ R2 skip OK: all prerequisites present for --from=${FROM_STEP}"
  fi
fi
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "1_parse_args" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_parse_args.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 1_parse_args 2>/dev/null || true
```
</step>

<step name="create_task_tracker">
**Create sub-step task list for progress tracking.**

Create tasks for each sub-step in this command:
```
TaskCreate: "2a. Plan — GSD planner"           (activeForm: "Creating plans...")
TaskCreate: "2b. Contracts — API contracts"     (activeForm: "Generating API contracts...")
TaskCreate: "2b5. Test goals — generate goals"   (activeForm: "Generating TEST-GOALS...")
TaskCreate: "2b7. Flow detect — FLOW-SPEC"      (activeForm: "Detecting business flows...")
TaskCreate: "2c. Verify 1 — grep diff"          (activeForm: "Verifying contracts (grep)...")
TaskCreate: "2d. CrossAI review"               (activeForm: "Running CrossAI review...")
```

Store task IDs for updating status as each sub-step runs.
Each sub-step should: `TaskUpdate: status="in_progress"` at start, `status="completed"` at end.

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "create_task_tracker" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/create_task_tracker.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint create_task_tracker 2>/dev/null || true
```
</step>

<step name="2_verify_prerequisites">
**Phase profile detection (P5, v1.9.2) — done BEFORE prerequisite check.**

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  SKIP_ARTIFACTS=$(phase_profile_skip_artifacts "$PHASE_PROFILE")
  export PHASE_PROFILE SKIP_ARTIFACTS
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"
else
  PHASE_PROFILE="feature"
  SKIP_ARTIFACTS=""
fi
```

**CONTEXT.md required ONLY for feature profile** (other profiles skip scope + CONTEXT).

```bash
needs_context=true
for a in $SKIP_ARTIFACTS; do
  [ "$a" = "CONTEXT.md" ] && needs_context=false
done

if [ "$needs_context" = "true" ] && [ ! -f "${PHASES_DIR}/${phase_dir}/CONTEXT.md" ]; then
  echo "⛔ CONTEXT.md not found for Phase ${PHASE_NUMBER} (profile=${PHASE_PROFILE} requires it)."

  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="blueprint.2-verify-prereq"
    BR_GATE_CONTEXT="Feature profile requires CONTEXT.md (scope decisions). User must run /vg:scope first."
    BR_EVIDENCE=$(printf '{"profile":"%s","missing":"CONTEXT.md"}' "$PHASE_PROFILE")
    BR_CANDIDATES='[]'
    BR_RESULT=$(block_resolve "blueprint-no-context" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "blueprint-no-context" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
  fi
  echo "   Run first: /vg:scope ${PHASE_NUMBER}"
  exit 1
fi

# For non-feature profiles, skip scope and contracts generation.
# Blueprint for infra/hotfix/bugfix/migration/docs only produces PLAN (and ROLLBACK for migration).
if [ "$PHASE_PROFILE" != "feature" ]; then
  echo "ℹ Blueprint profile-aware mode: PHASE_PROFILE=${PHASE_PROFILE} — bỏ qua (skip) sub-steps 2b, 2b5, 2b7 (contracts/test-goals/flow)."
  echo "   Chỉ tạo PLAN.md (+ ROLLBACK.md nếu migration). CrossAI review vẫn áp dụng để kiểm tra PLAN quality."
  export BLUEPRINT_PROFILE_SHORT_CIRCUIT=true
fi
```

**Legacy fallback (profile detection unavailable):** Check `${PHASES_DIR}/{phase_dir}/CONTEXT.md` exists.

Missing → BLOCK:
```
CONTEXT.md not found for Phase {N}.
Run first: /vg:scope {phase}
```

**Design-extract auto-trigger (fixes G1):**

```bash
# If project has design assets configured, ensure they're normalized BEFORE planning
# (so R4 granularity check + executor design_context have something to point at)
# OHOK-9 round-4 Codex fix: ${config.X.Y} is invalid bash (dots not allowed
# in var names). Previously returned empty string AND broke subsequent parsing.
# Use vg_config_get / vg_config_get_array helpers from config-loader.
DESIGN_PATHS=$(vg_config_get_array design_assets.paths)
if [ -n "$DESIGN_PATHS" ]; then
  DESIGN_OUT=$(vg_config_get design_assets.output_dir "${PLANNING_DIR}/design-normalized")
  DESIGN_MANIFEST="${DESIGN_OUT}/manifest.json"

  # Stale check: any source asset newer than manifest?
  NEEDS_EXTRACT=false
  if [ ! -f "$DESIGN_MANIFEST" ]; then
    NEEDS_EXTRACT=true
    REASON="manifest missing"
  else
    # Compare mtimes — if any asset newer than manifest, re-extract
    while read -r pattern; do
      [ -z "$pattern" ] && continue
      if find $pattern -newer "$DESIGN_MANIFEST" 2>/dev/null | grep -q .; then
        NEEDS_EXTRACT=true
        REASON="assets changed since last extract"
        break
      fi
    done <<< "$DESIGN_PATHS"
  fi

  if [ "$NEEDS_EXTRACT" = true ]; then
    echo "Design assets detected, manifest $REASON. Auto-running /vg:design-extract..."
    # --auto flag inherits; manual run lets user approve
    if [[ "$ARGUMENTS" =~ --auto ]]; then
      SlashCommand: /vg:design-extract --auto
    else
      AskUserQuestion: "Extract design assets now? (Required for <design-ref> linkage)"
        Options: [Yes (recommended), Skip — build without design]
      # If Yes → SlashCommand: /vg:design-extract
    fi
  fi
fi
```

Skip gracefully when `design_assets.paths` empty (pure backend phase).

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_verify_prerequisites" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_verify_prerequisites.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2_verify_prerequisites 2>/dev/null || true
```
</step>

<step name="2_fidelity_profile_lock" profile="web-fullstack,web-frontend-only">
## Sub-step 2: DESIGN FIDELITY PROFILE LOCK (Phase 15 D-08)

**Mục tiêu:** Lock the per-phase visual-fidelity threshold profile BEFORE
planner writes PLAN. The profile (prototype / default / production) sets
the SSIM/structural-diff threshold the post-wave drift gate enforces in
`/vg:review` (D-12b/c/e). Locking at blueprint time prevents executor or
reviewer from quietly relaxing the bar mid-phase.

Profile defaults (D-08):
- `prototype`  → 0.70 (early exploration, large layout swings tolerated)
- `default`    → 0.85 (most product work — Phase 15 default)
- `production` → 0.95 (visual-spec-grade, near pixel-perfect)

Resolution order (highest precedence first):
1. `--fidelity-profile <name>` CLI arg
2. Phase frontmatter `design_fidelity.profile: <name>` in CONTEXT.md
3. `vg.config.md` → `design_fidelity.default_profile`
4. Hardcoded fallback: `default` (0.85)

```bash
# Skip if no design assets in scope (pure backend phase)
if [ ! -f "${PHASE_DIR}/design-normalized/_INDEX.md" ] \
   && ! grep -lE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null | head -1 >/dev/null; then
  echo "ℹ No design or FE work in phase — skip fidelity profile lock"
else
  PROFILE_LOCK_FILE="${PHASE_DIR}/.fidelity-profile.lock"

  if [ -f "$PROFILE_LOCK_FILE" ]; then
    LOCKED=$(cat "$PROFILE_LOCK_FILE")
    echo "ℹ Fidelity profile already locked: ${LOCKED} (delete .fidelity-profile.lock to relock)"
  else
    # Resolve via threshold-resolver helper (Phase 15 T3.1).
    # Stdout = numeric threshold (e.g., "0.85"); stderr (with --verbose) =
    # `source=<src> profile=<name> threshold=<n>`. CLI override travels via
    # the VG_FIDELITY_PROFILE env var which threshold-resolver reads from
    # CONTEXT.md / vg.config.md merge — there is no --cli-profile flag.
    RESOLVED_ERR_FILE="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/threshold-resolver.err"
    mkdir -p "$(dirname "$RESOLVED_ERR_FILE")" 2>/dev/null
    THRESHOLD=$(${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/lib/threshold-resolver.py" \
        --phase "${PHASE_NUMBER}" --verbose 2> "$RESOLVED_ERR_FILE")
    PROFILE=$(grep -oE 'profile=[a-z-]+' "$RESOLVED_ERR_FILE" | head -1 | cut -d= -f2)
    SOURCE=$(grep -oE 'source=[a-z._-]+' "$RESOLVED_ERR_FILE"  | head -1 | cut -d= -f2)
    PROFILE="${PROFILE:-default}"
    THRESHOLD="${THRESHOLD:-0.85}"

    echo "$PROFILE" > "$PROFILE_LOCK_FILE"
    echo "✓ Fidelity profile locked: ${PROFILE} (threshold=${THRESHOLD}, source=${SOURCE:-fallback})"
    echo "  → ${PROFILE_LOCK_FILE}"
    echo "  /vg:review post-wave drift gate (D-12b/c/e) will use threshold=${THRESHOLD}"
  fi

  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_fidelity_profile_lock" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_fidelity_profile_lock.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2_fidelity_profile_lock 2>/dev/null || true
fi
```

**Override path** (DEBT — recorded in override-debt register):
- `--fidelity-profile prototype` on a phase that should be production-grade
  is allowed but logged as `kind=fidelity-profile-relaxed` so reviewers see
  it during /vg:accept.
</step>

<step name="2a_plan">
## Sub-step 2a: PLAN

**CONTEXT.md format validation (quick, <5 sec):**

Before planning, verify CONTEXT.md has the enriched format scope.md should have produced:

```bash
CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"
# Check enriched format: at least some P{phase}.D-XX (or legacy D-XX) decisions should have Endpoints or Test Scenarios
HAS_ENDPOINTS=$(grep -c "^\*\*Endpoints:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
HAS_TESTS=$(grep -c "^\*\*Test Scenarios:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
DECISION_COUNT=$(grep -cE "^### (P[0-9.]+\.)?D-" "$CONTEXT_FILE" 2>/dev/null || echo 0)

if [ "$DECISION_COUNT" -eq 0 ]; then
  echo "⛔ CONTEXT.md has 0 decisions. Run /vg:scope ${PHASE_NUMBER} first."
  exit 1
fi

if [ "$HAS_ENDPOINTS" -eq 0 ] && [ "$HAS_TESTS" -eq 0 ]; then
  echo "⚠ CONTEXT.md may be legacy format (no Endpoints/Test Scenarios sub-sections)."
  echo "  Blueprint will proceed but may produce less accurate plans."
  echo "  For best results: /vg:scope ${PHASE_NUMBER} (re-scope with enriched format)"
fi

echo "CONTEXT.md: ${DECISION_COUNT} decisions, ${HAS_ENDPOINTS} with endpoints, ${HAS_TESTS} with test scenarios"
```

Create execution plans using VG-native planner (self-contained, no GSD delegation).

**⛔ BUG #2 fix (2026-04-18): Auto-rebuild graphify BEFORE planner spawn.**

Mirrors `vg:build` step 4 auto-rebuild logic. Without this, planner plans against
stale graph (we observed 46h / 140 commits stale at audit) → planner references
symbols that no longer exist → tasks fabricated → executor fails or produces wrong code.

```bash
if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
  # Use graphify-safe wrapper — verifies mtime advances + retries on stuck rebuild
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"

  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')

  echo "Blueprint: graphify ${COMMITS_SINCE} commits since last build"

  if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
    vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "blueprint-phase-${PHASE_NUMBER}" || {
      echo "⚠ Planner will see stale graph — expect weaker task/sibling suggestions"
    }
  else
    echo "Graphify: up to date (0 commits since last build)"
  fi
fi
```

**Pre-spawn graphify context build (MANDATORY when `$GRAPHIFY_ACTIVE=true`):**

Before spawning the planner, extract structural context from graphify so the planner can
plan with blast-radius awareness instead of grep-only guesses. Without this, planners
produce `<edits-*>` annotations missing 60-90% of true downstream impact.

```bash
GRAPHIFY_BRIEF="${PHASE_DIR}/.graphify-brief.md"

if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
  # 1. God nodes (orchestrator MUST query via mcp__graphify__god_nodes — Claude tool call):
  #    Save top-20 god nodes ordered by community_size + edge_count. These are
  #    "touch with care" sentinels — planner MUST flag any task editing them.

  # 2. Communities relevant to phase:
  #    Grep CONTEXT.md endpoints + file paths → for each, query
  #    mcp__graphify__get_node + get_neighbors → collect community_id set.
  #    Save community summaries.

  # 3. Existing-symbol map for endpoints in CONTEXT (avoid re-introducing names):
  #    Grep CONTEXT.md "GET /api/..." patterns → query mcp__graphify__query_graph
  #    {"node_type":"route","path":"/api/v1/auth/login"} → emit "EXISTS at file:line"
  #    so planner annotates as REUSED, not NEW.

  # 4. Brief format (markdown, ≤150 lines, planner reads as injected context):
  cat > "$GRAPHIFY_BRIEF" <<EOF
# Graphify brief — Phase ${PHASE_NUMBER} structural context

Generated from graphify-out/graph.json (${GRAPH_NODE_COUNT} nodes, ${GRAPH_EDGE_COUNT} edges, mtime ${GRAPH_MTIME_HUMAN}).

## God nodes (touch with care)
$GOD_NODES_TABLE

## Phase-relevant communities
$COMMUNITY_TABLE

## Existing endpoints/symbols (REUSE, don't re-create)
$EXISTING_SYMBOLS_TABLE

## Sibling files (likely co-edited)
$SIBLINGS_TABLE
EOF
else
  # Fallback: emit a stub brief explaining graphify unavailable
  cat > "$GRAPHIFY_BRIEF" <<EOF
# Graphify brief — UNAVAILABLE
Graph not built or stale. Planner falls back to grep-only structural awareness.
Run: cd \$REPO_ROOT && \${PYTHON_BIN} -m graphify update .
EOF
fi
```

**Orchestrator note:** mcp__graphify__god_nodes / get_node / get_neighbors / query_graph
are Claude TOOL CALLS, not bash commands. Invoke directly via tool use after the
bash block computes the variable inputs (CONTEXT endpoint list, CONTEXT file path list).
DO NOT shell-out to graphify CLI — MCP tool round-trip is the supported path.

**v1.14.0+ C.5 — deploy_lessons injection** (silent, NO AskUserQuestion):

Trước khi spawn planner, extract lessons + env vars liên quan services mà phase này tác động, tiêm vào prompt planner dưới `<deploy_lessons>` block. Planner MUST reference khi đề cập ORG dimensions 3 (Deploy) + 4 (Smoke) + 6 (Rollback).

```bash
DEPLOY_LESSONS_BRIEF="${PHASE_DIR}/.deploy-lessons-brief.md"
DEPLOY_LESSONS_FILE=".vg/DEPLOY-LESSONS.md"
ENV_CATALOG_FILE=".vg/ENV-CATALOG.md"

if [ -f "$DEPLOY_LESSONS_FILE" ] || [ -f "$ENV_CATALOG_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$PHASE_DIR" "$DEPLOY_LESSONS_FILE" "$ENV_CATALOG_FILE" "$DEPLOY_LESSONS_BRIEF" <<'PY'
import re, sys
from pathlib import Path

phase_dir = Path(sys.argv[1])
lessons_file = Path(sys.argv[2])
env_file = Path(sys.argv[3])
brief_out = Path(sys.argv[4])

# 1. Infer services phase này touches (same heuristic aggregator)
service_hints = [
    ("apps/api",        [r"\bapi\b", r"fastify", r"modules?/", r"REST\s+API"]),
    ("apps/web",        [r"\bweb\b", r"\bdashboard\b", r"\bpage\b", r"\bReact\b", r"\bFE\b", r"\badvertiser\b", r"\bpublisher\b", r"\badmin\b"]),
    ("apps/rtb-engine", [r"\brtb[_-]?engine\b", r"\baxum\b", r"\bbid\s+request\b", r"\bauction\b"]),
    ("apps/workers",    [r"\bworkers?\b", r"\bconsumer\b", r"\bkafka\s+consumer\b", r"\bcron\b"]),
    ("apps/pixel",      [r"\bpixel\b", r"\bpostback\b", r"\btracking\b"]),
    ("infra/clickhouse",[r"\bclickhouse\b", r"\bOLAP\b", r"\banalytic\b"]),
    ("infra/mongodb",   [r"\bmongo(?:db)?\b", r"\bcollection\b"]),
    ("infra/kafka",     [r"\bkafka\b", r"\btopic\b", r"\bpartition\b"]),
    ("infra/redis",     [r"\bredis\b", r"\bcache\b"]),
]
services_touched = set()
for fname in ("SPECS.md", "CONTEXT.md"):
    f = phase_dir / fname
    if not f.exists():
        continue
    text = f.read_text(encoding="utf-8", errors="ignore").lower()
    for svc, pats in service_hints:
        for pat in pats:
            if re.search(pat, text, re.I):
                services_touched.add(svc)
                break

# Also infer from phase name
name_lower = phase_dir.name.lower()
for svc, pats in service_hints:
    for pat in pats:
        if re.search(pat, name_lower, re.I):
            services_touched.add(svc)
            break

# 2. Extract relevant lessons from DEPLOY-LESSONS View A (by service)
lessons_by_service = {}
if lessons_file.exists():
    text = lessons_file.read_text(encoding="utf-8", errors="ignore")
    # Parse View A: `### {service}` followed by `- **Phase X:** lesson`
    current_svc = None
    for line in text.splitlines():
        svc_m = re.match(r"^### ((?:apps|infra)/\S+)\s*$", line)
        if svc_m:
            current_svc = svc_m.group(1)
            lessons_by_service.setdefault(current_svc, [])
            continue
        # Stop at View B
        if line.startswith("## View B"):
            break
        if current_svc:
            bullet = re.match(r"^-\s+\*\*Phase ([\d.]+):\*\*\s+(.+)$", line)
            if bullet:
                lessons_by_service[current_svc].append((bullet.group(1), bullet.group(2)))

# 3. Extract env vars touched services from ENV-CATALOG
relevant_env = []
if env_file.exists():
    text = env_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        m = re.match(r"^\|\s*`(\w+)`\s*\|\s*([\d.]+)\s*\|\s*([^|]+)\s*\|", line)
        if not m:
            continue
        name, phase_added, service_list = m.groups()
        service_list = service_list.strip()
        # Match any service token trong cột Service với services_touched
        svc_tokens = re.split(r",\s*", service_list)
        if any(t.strip() in services_touched for t in svc_tokens):
            relevant_env.append((name, phase_added, service_list))

# 4. Write brief
out = ["# Deploy Lessons Brief — Phase-specific context cho planner", ""]
out.append(f"**Services touched:** {', '.join(sorted(services_touched)) or '(chưa xác định)'}")
out.append("")

if lessons_by_service:
    out.append("## Lessons từ phases trước (service-filtered)")
    out.append("")
    printed = 0
    for svc in sorted(services_touched):
        items = lessons_by_service.get(svc, [])
        if not items:
            continue
        out.append(f"### {svc}")
        for pid, lesson in items:
            out.append(f"- **Phase {pid}:** {lesson}")
            printed += 1
        out.append("")
    if printed == 0:
        out.append("_(Không có lesson nào liên quan service này.)_")
        out.append("")
else:
    out.append("_(DEPLOY-LESSONS.md chưa có lesson nào — phase đầu của v1.14.0+ flow.)_")
    out.append("")

if relevant_env:
    out.append("## Env vars liên quan (từ ENV-CATALOG)")
    out.append("")
    out.append("| Name | Added Phase | Service |")
    out.append("|---|---|---|")
    for name, pid, svc in relevant_env[:20]:  # limit 20 để prompt gọn
        out.append(f"| `{name}` | {pid} | {svc} |")
    if len(relevant_env) > 20:
        out.append(f"| _... và {len(relevant_env) - 20} env var nữa — xem ENV-CATALOG đầy đủ_ | | |")
    out.append("")
else:
    out.append("_(ENV-CATALOG trống hoặc không có env var nào map tới services của phase này.)_")
    out.append("")

out.append("## Hướng dẫn cho planner")
out.append("")
out.append("- ORG dimension 3 (Deploy): reference lessons về build/restart timing + pitfalls nếu có.")
out.append("- ORG dimension 4 (Smoke): include smoke check commands (xem SMOKE-PACK.md) cho services touched.")
out.append("- ORG dimension 6 (Rollback): nếu phase trước đã document rollback steps cùng service → reuse pattern.")
out.append("- Env vars liệt kê ở trên: nếu phase cần thêm var mới, tuân format reload/rotation/storage đã established.")
out.append("")

brief_out.write_text("\n".join(out), encoding="utf-8")
print(f"✓ deploy_lessons brief: {brief_out} (services={len(services_touched)}, lessons={sum(len(v) for v in lessons_by_service.values())}, env_vars={len(relevant_env)})")
PY
else
  echo "ℹ DEPLOY-LESSONS.md / ENV-CATALOG.md chưa tồn tại — skip deploy_lessons brief."
fi
```

### R5 prompt size gate (v1.14.4+ — pre-spawn planner)

Rule 5 khai max ~300 lines planner context. Gate đếm tổng size của các file tiêm vào prompt. Vượt = BLOCK để tránh drift/context overflow.

```bash
# Size check: sum lines of all files injected into planner prompt
R5_FILES=(
  "${PHASE_DIR}/.graphify-brief.md"
  "${PHASE_DIR}/.deploy-lessons-brief.md"
  "${PHASE_DIR}/SPECS.md"
  "${PHASE_DIR}/CONTEXT.md"
  ".claude/commands/vg/_shared/vg-planner-rules.md"
)
R5_TOTAL=0
R5_PER_FILE=""
for f in "${R5_FILES[@]}"; do
  if [ -f "$f" ]; then
    n=$(wc -l < "$f" 2>/dev/null | tr -d ' ')
    R5_TOTAL=$((R5_TOTAL + n))
    R5_PER_FILE="${R5_PER_FILE}\n    $(basename "$f"): ${n}"
  fi
done

R5_HARD_MAX="${CONFIG_BLUEPRINT_PLANNER_MAX_LINES:-1200}"
if [ "$R5_TOTAL" -gt "$R5_HARD_MAX" ]; then
  echo "⛔ R5 planner prompt overflow: ${R5_TOTAL} lines > hard max ${R5_HARD_MAX}"
  printf "Per-file breakdown:%b\n" "$R5_PER_FILE"
  echo ""
  echo "Nguyên nhân thường gặp:"
  echo "  - SPECS.md quá dài → split sang PRD bổ sung, tinh gọn"
  echo "  - CONTEXT.md có decisions dư → clean hoặc split phase"
  echo "  - graphify-brief god-node table quá dài → giảm top-N trong step 2a"
  echo ""
  echo "Override: /vg:blueprint ${PHASE_NUMBER} --override-reason='<reason>' (log debt)"
  echo "Raise threshold: config.blueprint.planner_max_lines = ${R5_TOTAL} trong vg.config.md"
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    exit 1
  else
        if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "blueprint_r5_planner_overflow" "${PHASE_NUMBER}" "blueprint.2a" "blueprint_r5_planner_overflow" "FAIL" "{}"
    fi
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "blueprint-r5-planner-overflow" "${PHASE_NUMBER}" "planner prompt ${R5_TOTAL} lines > ${R5_HARD_MAX}" "$PHASE_DIR"
    fi
    echo "⚠ --override-reason set — proceeding despite R5 breach"
  fi
else
  echo "✓ R5 planner prompt: ${R5_TOTAL} lines (hard max ${R5_HARD_MAX})"
fi
```

Bootstrap rules injection (v1.15.1 — hard rule: promoted learnings MUST reach the planner so past-phase mistakes don't repeat):

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"
```

Spawn planner agent với VG-specific rules + graphify brief + deploy_lessons brief + bootstrap rules:
```
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>

    <graphify_brief>
    @${PHASE_DIR}/.graphify-brief.md
    </graphify_brief>

    <deploy_lessons>
    @${PHASE_DIR}/.deploy-lessons-brief.md (if exists — v1.14.0+ C.5)
    </deploy_lessons>

    <specs>
    @${PHASE_DIR}/SPECS.md
    </specs>

    <context>
    @${PHASE_DIR}/CONTEXT.md
    </context>

    <architecture_context>
    # Phase D v2.5: FOUNDATION §9 Architecture Lock (injected if §9 exists)
    # This is the authoritative architecture contract — every plan MUST respect:
    # - §9.1 Tech stack (no substitutions without /vg:project --update)
    # - §9.2 Module boundary (dependency direction rules)
    # - §9.3 Folder convention (route layout, test colocation)
    # - §9.4 Cross-cutting concerns (logging, error handling, async pattern)
    # - §9.5 Security baseline (session/identity + server hardening rules)
    # - §9.6 Performance baseline (p95 per tier, cache, bundle budget)
    # - §9.7 Testing baseline (runner, E2E framework, coverage)
    # - §9.8 Model-portable code style (imports, exports, naming, idioms)
    # Plans MUST cite F-XX decisions when deviating; unreferenced deviation = drift.
    @${PLANNING_DIR:-.vg}/FOUNDATION.md (section 9 only — verify-foundation-architecture.py enforces presence)
    </architecture_context>

    <security_test_plan>
    # Phase D v2.5: SECURITY-TEST-PLAN.md (injected if exists)
    # Drives DAST severity gate + compliance control mapping per risk_profile.
    @${PLANNING_DIR:-.vg}/SECURITY-TEST-PLAN.md (if exists)
    </security_test_plan>

    <contracts>
    @${PHASE_DIR}/API-CONTRACTS.md (if exists)
    </contracts>

    <goals>
    @${PHASE_DIR}/TEST-GOALS.md (if exists)
    </goals>

    <config>
    profile: ${PROFILE}
    typecheck_cmd: ${config.build_gates.typecheck_cmd}
    contract_format: ${config.contract_format.type}
    phase: ${PHASE_NUMBER}
    phase_dir: ${PHASE_DIR}
    graphify_active: ${GRAPHIFY_ACTIVE}
    </config>

    Create PLAN.md for phase ${PHASE_NUMBER}. Follow vg-planner-rules exactly.

    GRAPHIFY USAGE (when graphify_active=true):
    - graphify_brief lists god nodes + existing symbols + sibling files
    - For EVERY task touching code, set <edits-*> attributes (REQUIRED, not optional)
      so the post-plan caller-graph script (step 2a5) can compute blast radius
    - When task touches a god node listed in brief, prefix description with
      "BLAST-RADIUS: god node — ripple to N callers expected" and include
      mitigation note (gradual rollout / feature flag / regression suite)
    - When task lists an endpoint in <edits-endpoint>, check brief's existing
      symbols table — if found, mark as REUSED-MODIFY not NEW-CREATE

    DEPLOY_LESSONS USAGE (v1.14.0+ C.5, when brief exists):
    - Nếu deploy_lessons có service-specific lessons → reference TRỰC TIẾP trong task
      description của ORG dimensions 3/4/6. VD: "Rebuild incremental tsc (Phase 7.12
      lesson: force --skip-lib-check if node_modules freshly cleared)".
    - Nếu deploy_lessons có env vars liên quan → tasks add new env var PHẢI tuân
      format reload/rotation/storage đã establish trong ENV-CATALOG (90-day vault
      cho secrets, config-stable cho URLs, tuning-knob cho TTL/cache).
    - Không có lessons liên quan → OK, ignore block.

    CONTEXT-REFS USAGE (Phase C v2.5 — context_injection.mode: scoped):
    When config.context_injection.mode is "scoped" (or phase_number >= phase_cutover),
    each task MUST include a <context-refs> element listing the specific decision IDs
    from CONTEXT.md that the executor needs. Example:

    ## Task 03: Add POST /api/v1/sites handler
    <context-refs>P7.14.D-02,P7.14.D-05</context-refs>
    <file-path>apps/api/src/modules/sites/routes.ts</file-path>
    ...

    Rules for picking refs:
    - Only cite decisions that directly constrain the task's implementation choices
    - Include D-XX for auth model, schema format, error handling idiom, naming
    - EXCLUDE decisions about other subsystems the task doesn't touch
    - If a task is infra-only (Ansible, env) → cite infra/env decisions only
    - Maximum 5 refs per task (more = probably over-citing; executor gets too much noise)
    When mode is "full" (phases 0-13), <context-refs> is optional but recommended.

    Output: ${PHASE_DIR}/PLAN.md with waves, task attributes, goal coverage.
```

Wait for completion. Verify `PLAN.md` exists in `${PHASE_DIR}`.

**Post-plan ORG check (v1.14.4+ — executable gate, Rule 6 enforcement):**

Read all PLAN*.md files. Deterministic parse qua keyword matching per dimension. Missing CRITICAL dimension (Deploy/Rollback) → BLOCK. Missing NON-CRITICAL dimension (Infra/Env/Smoke/Integration) → WARN + log.

```bash
PLAN_GLOB="${PHASE_DIR}/PLAN*.md"
ORG_CHECK_FILE="${PHASE_DIR}/.org-check-result.json"

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}" "${ORG_CHECK_FILE}" <<'PY'
import re, json, sys, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])

plan_files = sorted(glob.glob(str(phase_dir / "PLAN*.md")))
if not plan_files:
    print("⚠ ORG check: no PLAN*.md files — skip gate")
    sys.exit(0)

# Merge all plan content
plan_text = "\n".join(Path(p).read_text(encoding='utf-8', errors='ignore') for p in plan_files)
plan_lower = plan_text.lower()

# ORG 6 dimensions — keyword patterns (each dim needs ≥1 hit to be "addressed")
DIMENSIONS = {
    1: {
        "name": "Infra",
        "critical": False,
        "patterns": [
            r"\binstall\s+(clickhouse|redis|kafka|mongodb|postgres|nginx|haproxy)",
            r"\bansible\b.*\b(playbook|role)\b",
            r"\bprovision\b",
            r"\bn/a\s*[—-].*no\s+new\s+(infra|service)",
            r"\b(infra|service)\s+(existing|already|unchanged)",
        ],
    },
    2: {
        "name": "Env",
        "critical": False,
        "patterns": [
            r"\b(env|environment)\s+(var|variable|vars)",
            r"\.env\b",
            r"\bsecret(s)?\b.*\b(add|new|rotate)",
            r"\bvault\b",
            r"\benv\.j2\b",
            r"\bn/a\s*[—-].*no\s+new\s+env",
        ],
    },
    3: {
        "name": "Deploy",
        "critical": True,
        "patterns": [
            r"\bdeploy\s+(to|on)\b",
            r"\brsync\b",
            r"\bpm2\s+(reload|restart|start)",
            r"\bsystemctl\s+(restart|start)",
            r"\bbuild\s+(and|then)\s+(deploy|restart)",
            r"\brun\s+on\s+(target|vps|sandbox)",
        ],
    },
    4: {
        "name": "Smoke",
        "critical": False,
        "patterns": [
            r"\bsmoke\s+(test|check)",
            r"\bhealth\s+check",
            r"\b/health\b",
            r"\bcurl\b.*\b(health|status|ping)",
            r"\bverif(y|ying)\s+(alive|running|up)",
        ],
    },
    5: {
        "name": "Integration",
        "critical": False,
        "patterns": [
            r"\bintegration\s+(test|with)",
            r"\bE2E\b",
            r"\bconsumer\s+receives\b",
            r"\bend[-\s]to[-\s]end\b",
            r"\b(works|working)\s+with\s+(existing|phase)",
        ],
    },
    6: {
        "name": "Rollback",
        "critical": True,
        "patterns": [
            r"\brollback\b",
            r"\brecover(y|y path)?\b",
            r"\bgit\s+(revert|reset)",
            r"\brestore\s+(from|backup|previous)",
            r"\brollback\s+plan",
            r"\bn/a\s*[—-].*(additive|backward|no\s+rollback\s+needed)",
        ],
    },
}

results = {"dimensions": {}, "missing_critical": [], "missing_non_critical": []}
for num, dim in DIMENSIONS.items():
    hit_patterns = []
    for pat in dim["patterns"]:
        if re.search(pat, plan_lower, re.IGNORECASE):
            hit_patterns.append(pat)
    addressed = len(hit_patterns) > 0
    results["dimensions"][str(num)] = {
        "name": dim["name"],
        "critical": dim["critical"],
        "addressed": addressed,
        "hit_count": len(hit_patterns),
    }
    if not addressed:
        if dim["critical"]:
            results["missing_critical"].append(f"{num}.{dim['name']}")
        else:
            results["missing_non_critical"].append(f"{num}.{dim['name']}")

out_path.write_text(json.dumps(results, indent=2), encoding='utf-8')

# Report
total = len(DIMENSIONS)
addressed_count = sum(1 for d in results["dimensions"].values() if d["addressed"])
print(f"ORG check: {addressed_count}/{total} dimensions addressed")
for num, d in sorted(results["dimensions"].items()):
    marker = "✓" if d["addressed"] else "✗"
    crit = " [CRITICAL]" if d["critical"] else ""
    print(f"   {marker} {num}. {d['name']}{crit} (hits: {d['hit_count']})")

if results["missing_critical"]:
    print(f"\n⛔ Rule 6 violation: missing CRITICAL dimensions: {', '.join(results['missing_critical'])}")
    print("   Deploy + Rollback are MANDATORY cho mọi phase có code change.")
    print("   Fix: thêm task explicit vào PLAN với keywords:")
    print("     - Deploy: rsync/pm2/systemctl/deploy to target/build and deploy")
    print("     - Rollback: git revert/rollback plan/recovery path/N/A — additive")
    sys.exit(2)
elif results["missing_non_critical"]:
    print(f"\n⚠ ORG warn: missing non-critical dimensions: {', '.join(results['missing_non_critical'])}")
    print("   Add N/A note nếu không applicable, hoặc task explicit nếu cần.")
    sys.exit(0)
else:
    print("✓ Rule 6: all 6 ORG dimensions addressed")
    sys.exit(0)
PY

ORG_RC=$?
if [ "$ORG_RC" = "2" ]; then
  echo "blueprint-r6-org-missing phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/blueprint-state.log"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "blueprint_r6_org_missing" "${PHASE_NUMBER}" "blueprint.2a5" "blueprint_r6_org_missing" "FAIL" "{\"detail\":\"phase=${PHASE_NUMBER}\"}"
    fi
  if [[ "$ARGUMENTS" =~ --allow-missing-org ]]; then
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "blueprint-missing-org-critical" "${PHASE_NUMBER}" "missing critical ORG dims (Deploy/Rollback)" "$PHASE_DIR"
    fi
    echo "⚠ --allow-missing-org set — proceeding despite R6 breach, logged to debt"
  else
    echo "   Override (NOT recommended): /vg:blueprint ${PHASE_NUMBER} --from=2a5 --allow-missing-org"
    exit 1
  fi
fi
```

**Post-plan granularity check** (mandatory — execute sát blueprint):

Parse all tasks from PLAN*.md. For each task, validate:

| Rule | Requirement | Severity |
|------|-------------|----------|
| R1: Exact file path | Task specifies `{file-path}` or equivalent (not vague "can be in ...") | HIGH |
| R2: Contract reference | If task touches API (has verb POST/GET/PUT/DELETE OR creates endpoint handler) → must cite `<contract-ref>` pointing to API-CONTRACTS.md line range | HIGH |
| R3: Goals covered | Task has `<goals-covered>[G-XX, G-YY]</goals-covered>` when applicable. If task is pure infra/tooling: `no-goal-impact` acceptable. | MED |
| R4: Design reference | If task builds FE page/component AND config.design_assets is non-empty → must cite `<design-ref>` pointing to design-specs or design-screenshots. | MED |
| R5: Scope size | Estimated LOC delta ≤ 250 lines. If larger → recommend split into sub-tasks. | MED |

**⛔ R2 contract-ref format (tightened 2026-04-17 — MUST match regex, not free-form):**

```
<contract-ref>API-CONTRACTS.md#{endpoint-id} lines {start}-{end}</contract-ref>
```

Regex: `^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$`

Valid examples:
- `<contract-ref>API-CONTRACTS.md#post-api-sites lines 45-80</contract-ref>`
- `<contract-ref>API-CONTRACTS.md#get-api-campaigns-id lines 130-175</contract-ref>`

Invalid (will fail commit-msg Gate 2b and build citation resolver):
- `<contract-ref>API-CONTRACTS.md#post-sites</contract-ref>` — missing line range
- `<contract-ref>API-CONTRACTS.md line 45-80</contract-ref>` — missing #endpoint-id
- `<contract-ref>contracts.md#post-sites lines 45-80</contract-ref>` — wrong filename

Validation (inline in plan checker):
```bash
for ref in $(grep -oE '<contract-ref>[^<]+</contract-ref>' "$PLAN_FILE"); do
  body=$(echo "$ref" | sed 's/<[^>]*>//g')
  if ! echo "$body" | grep -qE '^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$'; then
    echo "⛔ R2 malformed contract-ref: '$body' — expected 'API-CONTRACTS.md#{id} lines X-Y'"
    R2_MALFORMED=$((R2_MALFORMED + 1))
  fi
done
```

Malformed R2 is treated as HIGH (not MED) — downstream build citation check parses this string literally.

**Inject warnings into PLAN.md as HTML comments** (non-intrusive):
```markdown
## Task 04: Add POST /api/sites handler

**Scope:** apps/api/src/modules/sites/routes.ts

<!-- plan-warning:R2 missing <contract-ref> — task creates endpoint but doesn't cite API-CONTRACTS.md line range. Add: <contract-ref>API-CONTRACTS.md#post-api-sites line 45-80</contract-ref> -->

Implementation: ...
```

**Warning budget:**
- > 50% tasks have HIGH warnings → return to planner with feedback for regeneration (loop to 2a)
- > 30% tasks have MED warnings → proceed but surface in step 2d (CrossAI review catches + Auto-fix loop)

Display:
```
Plan granularity check:
  Total tasks: {N}
  R1 file-path missing: {N}
  R2 contract-ref missing: {N}  (HIGH → {block|warn})
  R3 goals-covered missing: {N}
  R4 design-ref missing: {N}
  R5 scope >250 LOC: {N}
  Warnings injected: {total}
```

```bash
# v2.7 Phase E — schema validation post-write (BLOCK on PLAN.md frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact plan \
  > "${PHASE_DIR}/.tmp/artifact-schema-plan.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ PLAN.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-plan.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-plan.json"
  exit 2
fi

# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2a_plan" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2a_plan.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a_plan 2>/dev/null || true
```
</step>

<step name="2a5_cross_system_check">
## Sub-step 2a5: CROSS-SYSTEM CHECK (grep, no AI, <10 sec)

Scan the existing codebase and prior phases to detect conflicts/overlaps BEFORE writing contracts and code. This prevents phase isolation blindness.

**Check 1: Route conflicts**
```bash
# Grep all registered routes in existing code
EXISTING_ROUTES=$(grep -r "router\.\(get\|post\|put\|delete\|patch\)" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'/[^']+'" | sort)
# Compare with endpoints planned in CONTEXT.md decisions
# Flag: route already exists → plan must UPDATE, not CREATE
```

**Check 2: Schema/model field conflicts**
```bash
# Grep existing model/schema definitions
EXISTING_SCHEMAS=$(grep -r "z\.object\|Schema\|interface\s" "$API_ROUTES" --include="*.ts" --include="*.js" -l 2>/dev/null)
# For each model this phase touches (from CONTEXT.md):
#   Check if schema already has fields that conflict with planned changes
```

**Check 3: Shared component impact**
```bash
# Grep components this phase's pages import
# For each shared component: find ALL pages that import it
# Flag: shared component change affects N other pages outside this phase
grep -r "import.*from.*components" "$WEB_PAGES" --include="*.tsx" --include="*.jsx" -h 2>/dev/null | sort | uniq -c | sort -rn | head -20
```

**Check 4: Prior phase overlap**
```bash
# Read SUMMARY*.md from recent phases (last 3-5 phases)
# Check if any SUMMARY mentions same files/modules this phase plans to touch
for summary in $(ls ${PHASES_DIR}/*/SUMMARY*.md 2>/dev/null | tail -5); do
  grep -l "$(basename ${PHASE_DIR})" "$summary" 2>/dev/null
done
```

**Check 5: Database collection conflicts**
```bash
# Grep all collection references in existing code
grep -r "collection\(\|\.find\|\.insertOne\|\.updateOne" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'[^']+'" | sort | uniq -c | sort -rn
# Flag: this phase adds fields to collection another phase also modifies
```

**Output:** Inject warnings into PLAN.md as `<!-- cross-system-warning: ... -->` markers.

```
Cross-System Check:
  Routes: {N} potential conflicts
  Schemas: {N} shared fields
  Components: {N} shared, affecting {M} other pages
  Prior phases: {N} overlaps
  Collections: {N} conflicts
  
  Warnings injected into PLAN.md: {count}
```

No block — warnings only. AI planner should address each warning in task descriptions.

### Cross-system check 2: Caller graph (semantic regression)

Build `.callers.json` — maps each PLAN task's `<edits-*>` symbols to all downstream files using them. Build step 4e consumes this; commit-msg hook enforces caller update or citation.

```bash
if [ "$(vg_config_get semantic_regression.enabled true)" = "true" ]; then  # OHOK-9 round-4
  # ⛔ BUG #1 fix (2026-04-18): MUST pass --graphify-graph when active.
  # Without flag, script falls back to grep-only (misses path-alias imports
  # like `@/hooks/X`, misses cross-monorepo symbol callers).
  GRAPHIFY_FLAG=""
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
    --phase-dir "${PHASE_DIR}" \
    --config .claude/vg.config.md \
    $GRAPHIFY_FLAG \
    --output "${PHASE_DIR}/.callers.json"

  # Inject per-task warnings into PLAN.md listing downstream callers
  # Planner should ensure tasks updating shared symbols know their blast radius
  CALLER_COUNT=$(jq '.affected_callers | length' "${PHASE_DIR}/.callers.json")
  TOOLS_USED=$(jq -r '.tools_used | join(",")' "${PHASE_DIR}/.callers.json")
  echo "Semantic regression: tracked ${CALLER_COUNT} downstream callers (tools: ${TOOLS_USED})"

  # Sanity check: if graphify active but tools_used doesn't include 'graphify',
  # something went wrong — graph file unreadable or schema mismatch.
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ] && ! echo "$TOOLS_USED" | grep -q graphify; then
    echo "⚠ GRAPHIFY ENRICHMENT FAILED — graph active but caller-graph used grep-only."
    echo "  Inspect: ${PHASE_DIR}/.callers.json + check graphify-out/graph.json validity"
    echo "  Run: ${PYTHON_BIN} -c 'import json; json.load(open(\"$GRAPHIFY_GRAPH_PATH\"))'"
  fi
fi
```

Planner should convert each warning into task annotations: `<edits-schema>X</edits-schema>` so the graph can track changes reliably.

**⚠ Recurring problem (Phase 13 retro):** when planner produces 22 tasks but only 3 have `<edits-*>` annotations, the caller script can only compute blast-radius for those 3. The other 19 silently get zero callers — appearing safe when they may have many. See `vg-planner-rules.md` for the rule that EVERY code-touching task MUST have at least one `<edits-*>` attribute.

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2a5_cross_system_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2a5_cross_system_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a5_cross_system_check 2>/dev/null || true
```
</step>

<step name="2b_contracts">
## Sub-step 2b: CONTRACTS (strict format — executable code block)

Read `.claude/skills/api-contract/SKILL.md` — Mode: Generate.
Read `config.contract_format` from `.claude/vg.config.md`:
- `type`: zod_code_block | openapi_yaml | typescript_interface | pydantic_model
- `compile_cmd`: how to validate syntax (used in 2c2)

**Input:** CONTEXT.md + code at `config.code_patterns.api_routes` and `config.code_patterns.web_pages`

**Process:**
1. Grep existing schemas in codebase (match config.contract_format type)
2. Grep HTML/JSX forms and tables (if web_pages path exists)
3. Extract endpoints from CONTEXT.md decisions — supports both formats:
   - **VG-native bullet format** (from /vg:scope): `- POST /api/v1/sites (auth: publisher, purpose: create site)`
     Match regex: `^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - **Legacy header format** (from manual/older CONTEXT.md): `### POST /api/v1/sites`
     Match regex: `^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - Collect all matched `(method, path)` pairs into endpoint list for contract generation
4. Cross-reference endpoint list with CONTEXT decisions (each decision with data/CRUD → endpoint)
5. AI drafts contract for any endpoint without existing schema

**STRICT OUTPUT FORMAT — each endpoint MUST have executable code block:**

Example for `contract_format.type == "zod_code_block"`:

**4 blocks per endpoint. Blocks 1-3 = executor copies. Block 4 = test consumes.**

````markdown
### POST /api/sites

**Purpose:** Create new site (publisher role)

```typescript
// === BLOCK 1: Auth + middleware (COPY VERBATIM to route handler) ===
// Executor: paste this EXACT line in the route registration
export const postSitesAuth = [requireAuth(), requireRole('publisher'), rateLimit(30)];
```

```typescript
// === BLOCK 2: Request/Response schemas (COPY VERBATIM — same as before) ===
export const PostApiSitesRequest = z.object({
  domain: z.string().url().max(255),
  name: z.string().min(1).max(100),
  categoryId: z.string().uuid(),
});
export type PostApiSitesRequest = z.infer<typeof PostApiSitesRequest>;

export const PostApiSitesResponse = z.object({
  id: z.string().uuid(),
  domain: z.string(),
  status: z.enum(['pending', 'active', 'rejected']),
  createdAt: z.string().datetime(),
});
export type PostApiSitesResponse = z.infer<typeof PostApiSitesResponse>;
```

```typescript
// === BLOCK 3: Error responses (COPY VERBATIM to error handler) ===
// Executor: use these EXACT shapes in catch blocks. FE reads error.message for toast.
export const PostSitesErrors = {
  400: { error: { code: 'VALIDATION_FAILED', message: 'Invalid site data' } },
  401: { error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } },
  403: { error: { code: 'FORBIDDEN', message: 'Publisher role required' } },
  409: { error: { code: 'DUPLICATE_DOMAIN', message: 'Domain already registered' } },
} as const;
// FE toast rule: always show `response.data.error.message` — never HTTP status text
```

```typescript
// === BLOCK 4: Valid test sample (for idempotency + smoke tests) ===
// Executor: do NOT copy this block into app code. Used by test.md step 5b-2.
export const PostSitesSample = {
  domain: "https://test-idem.example.com",
  name: "Idempotency Test Site",
  categoryId: "00000000-0000-0000-0000-000000000001",
} as const;
```

**Mutation evidence:** `sites collection count +1`
**Cross-ref tasks:** Task {N} (BE handler), Task {M} (FE form)
````

**4 blocks per endpoint. Blocks 1-3 = executor copies verbatim. Block 4 = test consumes (step 5b-2). Executor does NOT write auth, schema, or error handling from scratch.**

Format per type (all 4 blocks adapt to format):
- `zod_code_block` → `\`\`\`typescript` with z.object, requireRole, error map, sample const
- `openapi_yaml` → `\`\`\`yaml` with security schemes, schemas, error responses, example values
- `typescript_interface` → `\`\`\`typescript` with interfaces + error types + sample const
- `pydantic_model` → `\`\`\`python` with BaseModel + FastAPI Depends + HTTPException + sample dict

**Rationale:** Billing-403 bug class happens when AI "decides" auth role or error shape instead of
copying from contract. By generating executable code blocks for ALL 3 concerns, the executor has
zero decision points — it copies, it doesn't think. Same principle as Zod schema copy, extended to
auth middleware and error responses. Block 4 eliminates the second bug class: heuristic payload
generation in test.md step 5b-2 producing values that fail Zod validation (e.g. `idempotency-test-domain`
is not a valid URL). Contract author knows the schema best — they provide the valid sample.

**Error response shape** is project-wide consistent. Read `config.error_response_shape` (default:
`{ error: { code: string, message: string } }`) — every endpoint's Block 3 MUST use this shape.
FE code reads `response.data.error.message` for toast — never `response.statusText` or raw code.

**Block 4 rules:**
1. Each endpoint MUST have Block 4 with valid sample payload matching Block 2 schema.
2. Use realistic values: valid email (test@example.com), valid UUID (00000000-...-000001), valid URL (https://test.example.com), ISO date, etc.
3. Zod/Pydantic validation of Block 4 values must pass against Block 2 schema.
4. Block 4 is consumed by test.md step 5b-2 idempotency check — NOT copied into app code.
5. Sample const name convention: `{Method}{Resource}Sample` (e.g. `PostSitesSample`, `PutCampaignSample`).
6. Mark `as const` (TypeScript) or freeze (Python) to prevent accidental mutation.
7. GET endpoints do NOT need Block 4 (no mutation payload).
8. For endpoints with path params, include a comment with sample path: `// path: /api/sites/00000000-0000-0000-0000-000000000001`

**Context budget:** ~500 lines (increased from 400 — 4 blocks per endpoint). Agent reads:
- CONTEXT.md (decisions list, ~50 lines)
- Grep results from code (extracted field hints, ~100 lines)
- Contract format template from config (~150 lines)
- Existing auth middleware patterns in codebase (~100 lines)

**Output:** Write `${PHASE_DIR}/API-CONTRACTS.md`. Must contain at least 1 code block per endpoint.

If no API routes or web pages detected → write minimal contract with CONTEXT-derived endpoints only. Still enforce code block format.

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b_contracts" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b_contracts.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b_contracts 2>/dev/null || true
```
</step>

<step name="2b5_test_goals">
## Sub-step 2b5: TEST GOALS

Generate TEST-GOALS.md from CONTEXT.md decisions + API-CONTRACTS.md endpoints.

**Agent context (~300 lines):**
- CONTEXT.md decisions (`P{phase}.D-01` through `P{phase}.D-XX`, or legacy `D-01..D-XX`) (~100 lines)
- API-CONTRACTS.md endpoints + fields (~100 lines)
- Output format template (~100 lines)

**Agent prompt:**
```
Convert CONTEXT decisions into testable GOALS.

For each decision (`P{phase}.D-XX`, or legacy `D-XX`), produce 1+ goals. Each goal:
- Has success criteria (what the user can do, what the system shows)
- Has mutation evidence (for create/update/delete: API response + UI change)
- Has dependencies (which goals must pass first)
- Has priority (critical = core feature, important = expected feature, nice-to-have = edge case/polish)

CONTEXT decisions:
[P{phase}.D-01 through P{phase}.D-XX — phase-scoped namespace, mandatory prefix]

API endpoints:
[from API-CONTRACTS.md]

RULES:
1. Every decision MUST have at least 1 goal
2. Goals describe WHAT to verify, not HOW (no selectors, no exact clicks)
3. Mutation evidence must be specific: "POST returns 201 AND row count +1" not "data changes"
3b. **Persistence check field (MANDATORY for mutation goals)**: Every goal with non-empty Mutation evidence MUST also have `**Persistence check:**` block describing Layer 4 verify (refresh + re-read + diff):
    ```
    **Persistence check:**
    - Pre-submit: read <field/row/state> value (e.g., role="editor")
    - Action: <what user does> (fill dropdown role="admin", click Save)
    - Post-submit wait: API 2xx + toast
    - Refresh: page.reload() OR navigate away + back
    - Re-read: <where to re-read> (re-open edit modal)
    - Assert: <field> = <new value> AND != <pre value> (role="admin", not "editor")
    ```
    Why mandatory: "ghost save" bug pattern — toast + API 200 + console clean NHƯNG refresh hiện data cũ. Only refresh-then-read detects backend silent skip / client optimistic rollback. Read-only goals (GET only) KHÔNG cần field này.
4. Dependencies must reference goal IDs (G-XX)
5. Priority assignment (deterministic rules, evaluate in order):
   a. Endpoints matching config `routing.critical_goal_domains` (auth, billing, auction, payout, compliance) → priority: critical
   b. Auth/session/token goals (login, logout, JWT refresh, session persist) → priority: critical
   c. Data mutation goals (POST/PUT/DELETE endpoints) → priority: important (minimum — upgrade to critical if also matches rule a/b)
   d. Read-only goals (GET endpoints, list/detail views) → priority: important (default)
   e. Cosmetic/display goals (formatting, sorting, empty states, UI polish) → priority: nice-to-have
6. Infrastructure dependency annotation (config-driven):
   If a goal requires services listed in config.infra_deps.services that are NOT part of this phase's build scope (e.g., ClickHouse, Kafka, pixel server), add:
   ```
   **Infra deps:** [clickhouse, kafka, pixel_server]
   ```
   Review Phase 4 auto-classifies goals with unmet infra_deps as INFRA_PENDING (skipped from gate).
   Determine infra scope by reading PLAN.md — services explicitly provisioned in tasks = in scope.
   Services referenced but not provisioned = external infra dep.

7. **URL state interactive_controls (MANDATORY for list/table/grid views — v2.8.4 Phase J):**
   If a goal has `surface: ui` AND its main_steps OR title mentions list/table/grid (or trigger is `GET /<plural-noun>`), the goal MUST declare `interactive_controls` frontmatter block. This is the dashboard UX baseline (executor R7) — list view filter/sort/page/search state MUST sync to URL search params so refresh/share-link/back-forward work.

   Auto-populate based on goal context:
   - If main_steps mention "filter by X" or trigger has `?status=`/`?type=` → emit `filters:` array with name + values + assertion
   - If main_steps mention "page through" or list endpoint returns >20 rows → emit `pagination:` block (page_size from config default 20)
   - If main_steps mention "search by name" or has search input → emit `search:` block (debounce_ms from config default 300)
   - If main_steps mention "sort by X" or table has sortable columns → emit `sort:` block

   Default url_param_naming reads from `config.ui_state_conventions.url_param_naming` (default `kebab` → `?sort-by=`, `?page-size=`).
   Default array_format reads from `config.ui_state_conventions.array_format` (default `csv` → `?tags=a,b,c`).

   Example for a campaign list goal:
   ```yaml
   interactive_controls:
     url_sync: true
     filters:
       - name: status
         values: [active, paused, completed, archived]
         url_param: status
         assertion: "rows.status all match selected; URL ?status=active synced; reload preserves"
     pagination:
       page_size: 20
       url_param_page: page
       ui_pattern: "first-prev-numbered-window-next-last"  # MANDATORY — locked
       window_radius: 5                                    # numbered window = current ±5
       show_total_records: true                            # MANDATORY "Showing X-Y of Z"
       show_total_pages: true                              # MANDATORY "Page N of M"
       assertion: "page2 first row != page1 first row; total count consistent; URL ?page=2 synced; reload preserves; UI shows << < numbered-window > >> + Showing X-Y of Z + Page N of M"
     search:
       url_param: q
       debounce_ms: 300
       assertion: "type query → debounce → URL ?q=... synced; rows contain query (case-insensitive)"
     sort:
       columns: [created_at, name, status]
       url_param_field: sort
       url_param_dir: dir
       assertion: "click header toggles asc↔desc; URL synced; ORDER BY holds"
   ```

   Override (rare): if state is genuinely local-only (modal-internal filter, transient drag-sort), declare `url_sync: false` + `url_sync_waive_reason: "<why>"`. Validator at /vg:review phase 2.7 logs soft OD debt for waivers.

   Verifier: `verify-url-state-sync.py` runs at review phase 2.7 — BLOCKs (phase ≥ cutover) or WARNs (grandfather) if list-view goal missing this block.

Output format:

# Test Goals — Phase {PHASE}

Generated from: CONTEXT.md decisions + API-CONTRACTS.md
Total: {N} goals ({critical} critical, {important} important, {nice} nice-to-have)

## Goal G-00: Authentication (F-06 or P{phase}.D-XX)
**Priority:** critical
**Success criteria:**
- User can log in with valid credentials
- Invalid credentials show error message
- Session persists across page navigation
**Mutation evidence:**
- Login: POST /api/auth/login returns 200 + token
**Dependencies:** none (root goal)
**Infra deps:** none

## Goal G-01: {Feature} (P{phase}.D-XX — or F-XX if foundation-sourced)
**Priority:** critical | important | nice-to-have
**Success criteria:**
- [what the user can do]
- [what the system shows]
- [error handling]
**Mutation evidence:**
- [Create: POST /api/X returns 201, table row +1]
- [Update: PUT /api/X/:id returns 200, row reflects change]
**Persistence check:**
- Pre-submit: read <field/row/state> (e.g., status="draft" in detail panel)
- Action: <what user does> (change status dropdown, click Save)
- Post-submit wait: API 2xx + toast "Updated"
- Refresh: page.reload()
- Re-read: re-open same record / navigate back to list
- Assert: <field> = <new value> AND != <pre value> (status="published", not "draft")
**Dependencies:** G-00

## Decision Coverage
| Decision | Goal IDs | Priority |
|----------|----------|----------|
| D-01 | G-01, G-02 | critical |
| D-02 | G-03 | important |
| ...  | ... | ... |

Coverage: {covered}/{total} decisions → {percentage}%
```

Write `${PHASE_DIR}/TEST-GOALS.md`.

### Rule 3b gate: Persistence check coverage (v1.14.4+)

Post-generation verify: mọi mutation goal PHẢI có `**Persistence check:**` block. Thiếu → blueprint fail sớm, không đợi review Layer 4 catch.

```bash
GOALS_FILE="${PHASE_DIR}/TEST-GOALS.md"
if [ -f "$GOALS_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$GOALS_FILE" <<'PY'
import re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse per-goal sections: '## Goal G-XX' or '### Goal G-XX' header boundaries
goal_pattern = re.compile(r'(^#{2,3}\s+(?:Goal\s+)?G-\d+[^\n]*)\n(.*?)(?=^#{2,3}\s+(?:Goal\s+)?G-\d+|\Z)',
                          re.MULTILINE | re.DOTALL)

mutation_goals_missing_persist = []
mutation_count = 0
persist_count = 0

for m in goal_pattern.finditer(text):
    header = m.group(1).strip()
    body = m.group(2)
    gid_match = re.search(r'G-\d+', header)
    gid = gid_match.group(0) if gid_match else '?'

    # Extract mutation evidence value (not just header existence)
    mut_match = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.DOTALL)
    has_mutation = False
    if mut_match:
        mut_value = mut_match.group(1).strip()
        # Non-empty + not "N/A" / "none"
        if mut_value and not re.match(r'^(N/A|none|—|-|_)\s*$', mut_value, re.I):
            has_mutation = True
            mutation_count += 1

    # Check persistence block presence
    has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
    if has_persist:
        persist_count += 1

    # Gate: mutation present but persistence missing
    if has_mutation and not has_persist:
        mutation_goals_missing_persist.append(gid)

if mutation_goals_missing_persist:
    print(f"⛔ Rule 3b violation: {len(mutation_goals_missing_persist)} mutation goal(s) thiếu Persistence check:")
    for gid in mutation_goals_missing_persist:
        print(f"   - {gid}")
    print("")
    print("Mỗi goal có **Mutation evidence** (state thay đổi) PHẢI có block:")
    print("   **Persistence check:**")
    print("   - Pre-submit: read <field> value")
    print("   - Action: <what user does>")
    print("   - Post-submit wait: API 2xx + toast")
    print("   - Refresh: page.reload() OR navigate away + back")
    print("   - Re-read: <where to re-read>")
    print("   - Assert: <field> = <new value> AND != <pre value>")
    print("")
    print("Lý do: Layer 4 persistence gate ở review/test sẽ catch ghost save bug.")
    print("Thiếu Persistence check block = review matrix-merger không eval được → goal BLOCKED.")
    sys.exit(1)

print(f"✓ Rule 3b: {mutation_count} mutation goals, {persist_count} with Persistence check")
PY
  PERSIST_RC=$?
  if [ "$PERSIST_RC" != "0" ]; then
    echo "blueprint-r3b-violation phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/blueprint-state.log"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "blueprint_r3b_persistence_missing" "${PHASE_NUMBER}" "blueprint.2b5" "blueprint_r3b_persistence_missing" "FAIL" "{\"detail\":\"phase=${PHASE_NUMBER}\"}"
    fi
    # Allow override via explicit flag (debt logged)
    if [[ "$ARGUMENTS" =~ --allow-missing-persistence ]]; then
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "blueprint-missing-persistence" "${PHASE_NUMBER}" "mutation goals without Persistence check block" "$PHASE_DIR"
      fi
      echo "⚠ --allow-missing-persistence set — proceeding, logged to debt register"
    else
      echo "   Fix: edit TEST-GOALS.md, thêm Persistence check block cho các goals liệt kê ở trên"
      echo "   Override (NOT recommended): /vg:blueprint ${PHASE_NUMBER} --from=2b5 --allow-missing-persistence"
      exit 1
    fi
  fi
fi
```

**Bidirectional linkage with PLAN (mandatory post-gen):**

After TEST-GOALS.md is written, inject cross-references so build step 8 can quickly find context:

1. **Goals → Tasks** (in TEST-GOALS.md): for each G-XX, detect which tasks in PLAN*.md implement it (match by endpoint/file mentions). Add:
   ```markdown
   ## Goal G-03: Create site (D-02)
   **Implemented by:** Task 04 (BE handler), Task 07 (FE form)   ← NEW
   ...
   ```

2. **Tasks → Goals** (in PLAN*.md): for each task, inject `<goals-covered>` attribute if not already present. Auto-detect based on task description mentioning endpoint/feature that maps to goal's mutation evidence.

Algorithm (deterministic, no AI guess):
```
For each goal G-XX in TEST-GOALS.md:
  extract endpoints from "mutation evidence" (e.g., POST /api/sites)
  For each task in PLAN*.md:
    If task description contains matching endpoint OR feature-name from goal:
      append task to goal.implemented_by
      append goal to task.<goals-covered>

For orphan tasks (no goal match):
  inject <goals-covered>no-goal-impact</goals-covered>
  OR <goals-covered>UNKNOWN — review</goals-covered> (flag for user)

For orphan goals (no task match):
  inject **Implemented by:** ⚠ NONE (spec gap — plan regeneration needed)
```

Display:
```
Test Goals: {N} goals generated ({critical} critical, {important} important, {nice} nice-to-have)
Decision coverage: {covered}/{total} ({percentage}%)
Goal ↔ Task linkage:
  Goals linked to tasks: {N}/{total}
  Orphan goals (no task): {N}       ← spec gap, surfaced to 2d validation
  Orphan tasks (no goal): {N}       ← may be infra or spec bloat
```

**Surface classification (v1.9.1 R1 — lazy migration):**

Immediately after TEST-GOALS.md is written (including bidirectional linkage), classify each goal into a **test surface** (ui / ui-mobile / api / data / time-driven / integration / custom). This is what `/vg:review` and `/vg:test` use to pick runners — backend-only phases must not deadlock on browser discovery.

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
```

Behaviour by return code:
- `0` → all goals classified at ≥0.8 confidence (narration prints auto-count).
- `2` → 0.5..0.8 band needs Haiku tie-break. Read `${PHASE_DIR}/.goal-classifier-pending.tsv`, spawn ONE Haiku subagent per goal (pattern identical to `rationalization-guard` — subagent receives goal block + candidate surface + keywords found, returns `{surface, confidence}`). Call `classify_goals_apply` with the resolved TSV.
- `3` → some goals <0.5 confidence. BLOCK until user picks via `AskUserQuestion` (options = configured surface list + "custom"). Call `classify_goals_apply` with user answers.

After classification, include per-goal surface in blueprint narration:
```
🎯 Goal surfaces: 17 ui · 5 api · 3 data · 2 time-driven · 1 integration
```

```bash
# v2.7 Phase E — schema validation post-write (BLOCK on TEST-GOALS.md frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact test-goals \
  > "${PHASE_DIR}/.tmp/artifact-schema-test-goals.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ TEST-GOALS.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-test-goals.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-test-goals.json"
  exit 2
fi

# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b5_test_goals" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b5_test_goals.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5_test_goals 2>/dev/null || true
```
</step>

<step name="2b6_ui_spec">
## Sub-step 2b6: UI SPEC (FE tasks only)

**Skip conditions:**
- No task has `file-path` matching `config.code_patterns.web_pages` → skip entirely
- `config.design_assets.paths` empty → skip (no visual reference to derive from)
- `${PHASE_DIR}/UI-SPEC.md` already exists and is newer than all PLAN*.md + design manifest → skip (already fresh)

**Purpose:** Produce UI contract executor reads alongside API-CONTRACTS. Answers: layout, component set, spacing tokens, interaction states, responsive breakpoints.

**Input (~600 lines agent context):**
- CONTEXT.md (design decisions if any, ~100 lines)
- Task file-paths of FE tasks + their `<design-ref>` attributes (~100 lines)
- `${DESIGN_OUTPUT_DIR}/manifest.json` — list of available screenshots + structural refs (~50 lines)
- Sample design refs (read 2-3 representative ones — `*.structural.html` + `*.interactions.md`) (~300 lines)

**Agent prompt:**
```
Generate UI-SPEC.md for phase {PHASE}. This is the design contract FE executors copy verbatim.

RULES:
1. Extract visible patterns from design-normalized refs — do NOT invent.
2. For each component used: name, markup structure (from structural.html), states (from interactions.md).
3. Spacing/color tokens only if consistent across refs. If refs conflict, flag for user.
4. Per-page section: layout (grid/flex), slots (header/sidebar/main), interaction patterns.
5. Reference screenshots by slug — executor opens them for pixel truth.

Output format:

# UI Spec — Phase {PHASE}

Source: ${DESIGN_OUTPUT_DIR}/  (screenshots + structural + interactions)
Derived: {YYYY-MM-DD}

## Design Tokens
| Token | Value | Source |
|-------|-------|--------|
| color.primary | #6366f1 | consistent across {slug-a}, {slug-b} |
| spacing.lg | 24px | ... |

## Component Library (observed in design)
### Button
- Variants: primary | secondary | ghost
- States: default | hover | disabled
- Markup: `<button class="btn btn-{variant}">...</button>`  (from {slug}.structural.html#btn-primary)

### Modal
- Pattern: overlay + centered card
- Open/close: `data-modal-open="{id}"` / `data-modal-close` (from {slug}.interactions.md)
...

## Per-Page Layout
### /publisher/sites (Task 07)
- Screenshot: ${DESIGN_OUTPUT_DIR}/screenshots/sites-list.default.png
- Layout: sidebar (fixed 240px) + main (flex-1)
- Sections: toolbar (search + Add button), table (5 cols), pagination footer
- States needed: empty | loading | populated | error
- Interactions: row click → detail drawer; Add button → modal (component ref above)

## Responsive Breakpoints
(only if design has multiple viewport screenshots)

## Conflicts / Ambiguities
(flag anything where design refs disagree — user decides)
```

Write `${PHASE_DIR}/UI-SPEC.md`. Build step 4/8c injects relevant section per FE task.

Display:
```
UI-SPEC:
  FE tasks detected: {N}
  Design refs consumed: {N}
  Tokens: {N} | Components: {N} | Pages: {N}
  Conflicts flagged: {N}
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6_ui_spec" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6_ui_spec.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6_ui_spec 2>/dev/null || true
```
</step>

<step name="2b6b_ui_map" profile="web-fullstack,web-frontend-only">
## Sub-step 2b6b: UI-MAP (bản vẽ đích cây component)

**Mục tiêu:** Tạo `UI-MAP.md` chứa cây component kế hoạch đích (to-be blueprint) cho các
view mới/sửa trong phase này. Executor sẽ bám vào cây này khi viết code, verify-ui-structure.py
sẽ so sánh post-wave để phát hiện lệch hướng (drift).

**Khác biệt với 2b6_ui_spec:**
- `UI-SPEC.md` = spec cấp cao (design tokens, typography, interactions) — thường áp dụng toàn phase.
- `UI-MAP.md` = cây component cụ thể cho từng view — thứ executor bám theo từng dòng.

**Skip khi:**
- Phase không có task UI (profile backend-only)
- Config `ui_map.enabled: false`

```bash
# Đọc config ui_map
UI_MAP_ENABLED=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /enabled:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "true")

if [ "$UI_MAP_ENABLED" != "true" ]; then
  echo "ℹ ui_map disabled in config — skipping UI-MAP generation"
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
else
  # Kiểm tra phase có touch FE không
  FE_TASKS=$(grep -cE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo "0")

  if [ "${FE_TASKS:-0}" -eq 0 ]; then
    echo "ℹ Phase không có task FE — skip UI-MAP"
    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
  else
    echo "Phase có ${FE_TASKS} dòng task FE. Chuẩn bị UI-MAP.md..."

    # ─── Bước 1: Sinh as-is map nếu phase sửa view cũ ───
    # Detect: task có edit file UI đã tồn tại
    EXISTING_UI_FILES=$(grep -hE "^\s*-\s*(Edit|Modify):" "${PHASE_DIR}"/PLAN*.md 2>/dev/null | \
                        grep -oE "[a-z_-]+\.(tsx|jsx|vue|svelte)" | sort -u)

    if [ -n "$EXISTING_UI_FILES" ]; then
      echo "Phát hiện task sửa view cũ — sinh UI-MAP-AS-IS.md để planner hiểu cấu trúc hiện tại"

      UI_MAP_SRC=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /src:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
      UI_MAP_ENTRY=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /entry:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')

      if [ -n "$UI_MAP_SRC" ] && [ -n "$UI_MAP_ENTRY" ]; then
        node .claude/scripts/generate-ui-map.mjs \
          --src "$UI_MAP_SRC" \
          --entry "$UI_MAP_ENTRY" \
          --format both \
          --output "${PHASE_DIR}/UI-MAP-AS-IS.md" 2>&1 | tail -3
      else
        echo "⚠ ui_map.src / ui_map.entry chưa cấu hình — bỏ qua as-is scan"
      fi
    fi

    # ─── Bước 2: Planner viết UI-MAP.md (to-be blueprint) ───
    # Orchestrator spawn planner agent với:
    # - CONTEXT.md (decisions)
    # - PLAN*.md (tasks)
    # - UI-SPEC.md (component inventory nếu có)
    # - UI-MAP-AS-IS.md (cây hiện trạng nếu phase sửa view cũ)
    # - Design refs từ design-normalized/ (nếu có)
    #
    # Output: ${PHASE_DIR}/UI-MAP.md với:
    #   - Cây ASCII cho mỗi view mới/sửa
    #   - JSON tree (machine-readable, cho verify-ui-structure.py diff)
    #   - Layout notes (class layout + style keys mong muốn)
    #
    # Template ở ${REPO_ROOT}/.claude/commands/vg/_shared/templates/UI-MAP-template.md

    if [ ! -f "${PHASE_DIR}/UI-MAP.md" ]; then
      echo "▸ Orchestrator cần spawn planner agent (model=${MODEL_PLANNER:-opus}) để viết UI-MAP.md"
      echo "   Input: CONTEXT.md + PLAN*.md + UI-SPEC.md + UI-MAP-AS-IS.md (nếu có)"
      echo "   Output: ${PHASE_DIR}/UI-MAP.md"
      echo ""
      echo "   Planner prompt (tóm tắt):"
      echo "   'Với mỗi view tạo mới hoặc cải tạo trong phase này, vẽ cây component"
      echo "    dạng ASCII + JSON. Mỗi node component ghi: tên, file path đích, class"
      echo "    layout mong muốn, state/props gì quan trọng. Cây phải khả thi (executor"
      echo "    build theo được). Nếu sửa view cũ: điều chỉnh UI-MAP-AS-IS.md.'"
      echo ""
      echo "   Phase 15 D-15 + D-12a — schema lock + ownership tags:"
      echo "    - JSON tree MUST validate against schemas/ui-map.v1.json (5 fields per node:"
      echo "        tag, classes, children_count_order, props_bound, text_content_static)."
      echo "    - Each node MUST carry owner_wave_id (and owner_task_id when finer scope is"
      echo "        useful). Children inherit ownership unless they override; verify-ui-structure"
      echo "        can then filter to a single wave's subtree (D-12b)."
      echo "    - extract-subtree-haiku.mjs reads these tags during /vg:build step 8c to inject"
      echo "        the wave-scoped subtree into the executor prompt — missing tags = no"
      echo "        deterministic injection, executor falls back to full UI-MAP (cost spike)."
    else
      echo "ℹ UI-MAP.md đã có — skip regeneration. Xoá file này để regenerate."
      # Phase 15 D-15 schema check on existing UI-MAP.md (deterministic, no AI)
      if [ -x "${REPO_ROOT}/.claude/scripts/validators/verify-uimap-schema.py" ]; then
        ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uimap-schema.py" \
            --phase "${PHASE_NUMBER}" 2>&1 | tail -5
      fi
    fi

    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b6b_ui_map" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"

    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6b_ui_map 2>/dev/null || true
  fi
fi
```

**Gate (chưa block, chỉ warn):** nếu phase có task FE nhưng UI-MAP.md không có, in warning — step 2d validation sẽ escalate.
</step>

<step name="2b7_flow_detect" profile="web-fullstack,web-frontend-only">
## Sub-step 2b7: FLOW-SPEC AUTO-DETECT (deterministic, no AI for detection)

**Purpose:** Detect goal dependency chains >= 3 in TEST-GOALS.md. When found, auto-generate
FLOW-SPEC.md skeleton so `/vg:test` step 5c-flow has flows to verify. Without this,
multi-page state-machine bugs (login → create → edit → delete) slip through because
per-goal tests verify each step independently but miss continuity failures.

**Skip conditions:**
- TEST-GOALS.md does not exist → skip (blueprint hasn't generated goals yet)
- Profile is `web-backend-only` or `cli-tool` or `library` → skip (no UI flows)

**Step 1: Parse dependency graph from TEST-GOALS.md**

```bash
# Extract goal IDs and their dependencies (deterministic grep, no AI)
CHAIN_OUTPUT=$(${PYTHON_BIN} - "${PHASE_DIR}/TEST-GOALS.md" <<'PYEOF'
import sys, re, json
from pathlib import Path
from collections import defaultdict

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse goals: ID, title, priority, dependencies
goals = {}
current = None
for line in text.splitlines():
    m = re.match(r'^## Goal (G-\d+):\s*(.+?)(?:\s*\(D-\d+\))?$', line)
    if m:
        current = m.group(1)
        goals[current] = {'title': m.group(2).strip(), 'deps': [], 'priority': 'important'}
        continue
    if current:
        dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
        if dm:
            deps_str = dm.group(1).strip()
            if deps_str.lower() not in ('none', 'none (root goal)', ''):
                goals[current]['deps'] = re.findall(r'G-\d+', deps_str)
        pm = re.match(r'\*\*Priority:\*\*\s*(\w+)', line)
        if pm:
            goals[current]['priority'] = pm.group(1).strip()

# Build dependency chains via DFS — find all maximal chains
def find_chains(goal_id, visited=None):
    if visited is None:
        visited = []
    visited = visited + [goal_id]
    deps = goals.get(goal_id, {}).get('deps', [])
    # Find goals that depend on this one (forward chains)
    dependents = [g for g, info in goals.items() if goal_id in info['deps'] and g not in visited]
    if not dependents:
        return [visited]
    chains = []
    for dep in dependents:
        chains.extend(find_chains(dep, visited))
    return chains

# Find root goals (no dependencies or only depend on auth)
roots = [g for g, info in goals.items() if not info['deps']]
all_chains = []
for root in roots:
    all_chains.extend(find_chains(root))

# Filter chains >= 3 goals (these are multi-step business flows)
long_chains = [c for c in all_chains if len(c) >= 3]
# Deduplicate (keep longest chain per root)
seen = set()
unique_chains = []
for chain in sorted(long_chains, key=len, reverse=True):
    key = tuple(chain[:2])  # dedup by first 2 elements
    if key not in seen:
        seen.add(key)
        unique_chains.append(chain)

output = {
    'total_goals': len(goals),
    'total_chains': len(unique_chains),
    'chains': [{'goals': c, 'length': len(c),
                'titles': [goals[g]['title'] for g in c if g in goals]}
               for c in unique_chains],
    'goals': {g: info for g, info in goals.items()}
}
print(json.dumps(output, indent=2))
PYEOF
)
```

**Step 2: Generate FLOW-SPEC.md skeleton (only if chains found)**

```bash
CHAIN_COUNT=$(echo "$CHAIN_OUTPUT" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['total_chains'])" 2>/dev/null || echo "0")

if [ "$CHAIN_COUNT" -eq 0 ]; then
  echo "Flow detect: no dependency chains >= 3 found. Skipping FLOW-SPEC generation."
  # No FLOW-SPEC.md = 5c-flow will skip (expected for simple phases)
else
  echo "Flow detect: $CHAIN_COUNT chains >= 3 goals found. Generating FLOW-SPEC.md skeleton..."

  # Bootstrap rule injection — project rules targeting blueprint fire here
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
  BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
  vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"

  # Generate skeleton — AI fills in step details from goal success criteria
  Agent(subagent_type="general-purpose", model="${MODEL_TEST_GOALS}"):
    prompt: |
      Generate FLOW-SPEC.md for phase ${PHASE}. This defines multi-page test flows
      for the flow-runner skill.

      <bootstrap_rules>
      ${BOOTSTRAP_RULES_BLOCK}
      </bootstrap_rules>


      Input — detected dependency chains (goals that form sequential business flows):
      ${CHAIN_OUTPUT}

      Input — full TEST-GOALS.md:
      @${PHASE_DIR}/TEST-GOALS.md

      Input — API-CONTRACTS.md (for endpoint details):
      @${PHASE_DIR}/API-CONTRACTS.md

      RULES:
      1. Each chain becomes 1 flow. Flow = ordered sequence of steps.
      2. Each step maps to 1 goal in the chain.
      3. Step has: action (what user does), expected (what system shows), checkpoint (what to save for next step).
      4. Use goal success criteria + mutation evidence as step expected/checkpoint.
      5. Do NOT invent steps outside the chain — only goals in the chain.
      6. Do NOT specify selectors, CSS classes, or exact clicks — describe WHAT, not HOW.
      7. Flow names should describe the business operation: "Site CRUD lifecycle", "Campaign create-to-launch".

      Output format:

      # Flow Specs — Phase {PHASE}

      Generated from: TEST-GOALS.md dependency chains >= 3
      Total: {N} flows

      ## Flow F-01: {Business operation name}
      **Chain:** {G-00 → G-01 → G-03 → G-05}
      **Priority:** critical | important
      **Roles:** [{roles involved}]

      ### Step 1: {Action name} (G-00)
      **Action:** {what the user does}
      **Expected:** {what the system shows — from goal success criteria}
      **Checkpoint:** {state to verify/save for next step — from mutation evidence}

      ### Step 2: {Action name} (G-01)
      **Action:** ...
      **Expected:** ...
      **Checkpoint:** ...
      ...

      ## Flow Coverage
      | Flow | Goals covered | Priority |
      |------|--------------|----------|
      | F-01 | G-00, G-01, G-03, G-05 | critical |

      Write to: ${PHASE_DIR}/FLOW-SPEC.md
fi
```

Display:
```
Flow detection:
  Goals parsed: {N}
  Dependency chains >= 3: {CHAIN_COUNT}
  FLOW-SPEC.md: {generated|skipped (no chains)}
  Flows defined: {N}
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b7_flow_detect" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b7_flow_detect.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b7_flow_detect 2>/dev/null || true
```
</step>

<step name="2c_verify">
## Sub-step 2c: VERIFY 1 (grep only, no AI)

Automated contract verification. Must complete in <5 seconds.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
CONTEXT="${PHASE_DIR}/CONTEXT.md"
API_ROUTES="${CONFIG_CODE_PATTERNS_API_ROUTES:-apps/api/src}"
WEB_PAGES="${CONFIG_CODE_PATTERNS_WEB_PAGES:-apps/web/src}"

if [ ! -f "$CONTRACTS" ]; then
  echo "⛔ API-CONTRACTS.md not found — step 2b must run first"
  exit 1
fi

# Extract endpoints (method, path) from contracts — supports both header formats
CONTRACT_EPS=$(grep -oE '^###\s+(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTRACTS" \
  | sed 's/^###[[:space:]]*//' | sort -u)

# Extract endpoints from CONTEXT.md — both VG-native bullet + legacy header
CONTEXT_EPS=""
if [ -f "$CONTEXT" ]; then
  BULLET_EPS=$(grep -oE '^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTEXT" \
    | sed -E 's/^\s*-\s+//' | sort -u)
  HEADER_EPS=$(grep -oE '^###\s+([0-9]+\.[0-9]+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTEXT" \
    | sed -E 's/^###[[:space:]]*([0-9]+\.[0-9]+[[:space:]]+)?//' | sort -u)
  CONTEXT_EPS=$(printf '%s\n%s\n' "$BULLET_EPS" "$HEADER_EPS" | sort -u | sed '/^$/d')
fi

MISMATCHES=0
MISSING_ENDPOINTS=""
MISSING_HANDLERS=""

# 1. Contract endpoints vs CONTEXT decisions — every CONTEXT endpoint must have contract
if [ -n "$CONTEXT_EPS" ]; then
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    # Normalize (method + path only, strip trailing comments)
    ep_norm=$(echo "$ep" | awk '{print $1, $2}')
    if ! echo "$CONTRACT_EPS" | grep -qFx "$ep_norm"; then
      MISSING_ENDPOINTS="${MISSING_ENDPOINTS}\n   - ${ep_norm}"
      MISMATCHES=$((MISMATCHES + 1))
    fi
  done <<< "$CONTEXT_EPS"
fi

# 2. Contract endpoints vs backend handlers (code-pattern grep)
if [ -d "$API_ROUTES" ] && [ -n "$CONTRACT_EPS" ]; then
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    method=$(echo "$ep" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    path=$(echo "$ep" | awk '{print $2}')
    # Path with colons for params (e.g., /sites/:id)
    path_escaped=$(echo "$path" | sed 's/\//\\\//g; s/\./\\./g')
    # Grep route definitions — fastify/express/hono patterns
    if ! grep -rqE "(\.|router\.|app\.|fastify\.|${method}\s*\(\s*['\"])${path_escaped}['\"]|(route|path):\s*['\"]${path_escaped}['\"]" \
         "$API_ROUTES" 2>/dev/null; then
      MISSING_HANDLERS="${MISSING_HANDLERS}\n   - ${ep} (no handler detected)"
      MISMATCHES=$((MISMATCHES + 1))
    fi
  done <<< "$CONTRACT_EPS"
fi

ENDPOINT_COUNT=$(echo "$CONTRACT_EPS" | grep -c . || echo 0)
CONTEXT_COUNT=$(echo "$CONTEXT_EPS" | grep -c . || echo 0)

echo "Verify 1 (grep): ${ENDPOINT_COUNT} contract endpoints, ${CONTEXT_COUNT} CONTEXT endpoints, ${MISMATCHES} mismatches"

if [ "$MISMATCHES" -eq 0 ]; then
  echo "✓ PASS"
elif [ "$MISMATCHES" -le 3 ]; then
  echo "⚠ WARNING — ${MISMATCHES} mismatches (auto-fix threshold)"
  [ -n "$MISSING_ENDPOINTS" ] && printf "Missing in contracts:%b\n" "$MISSING_ENDPOINTS"
  [ -n "$MISSING_HANDLERS" ] && printf "Missing handlers (may land in build step):%b\n" "$MISSING_HANDLERS"
else
  echo "⛔ BLOCK — ${MISMATCHES} mismatches (>3)"
  [ -n "$MISSING_ENDPOINTS" ] && printf "Missing in contracts:%b\n" "$MISSING_ENDPOINTS"
  [ -n "$MISSING_HANDLERS" ] && printf "Missing handlers:%b\n" "$MISSING_HANDLERS"
  echo ""
  echo "Fix: re-run step 2b để regenerate contracts đầy đủ hoặc update CONTEXT.md"
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    exit 1
  else
        if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "blueprint_2c_mismatches" "${PHASE_NUMBER}" "blueprint.2c" "blueprint_2c_mismatches" "FAIL" "{}"
    fi
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "blueprint-2c-mismatches" "${PHASE_NUMBER}" "${MISMATCHES} endpoint mismatches between contracts and CONTEXT/handlers" "$PHASE_DIR"
    fi
    echo "⚠ --override-reason set — proceeding, logged to debt register"
  fi
fi
```

**Results:**
- 0 mismatches → PASS, proceed to 2d
- 1-3 mismatches → WARNING, auto-fix contracts, re-verify once
- 4+ mismatches → BLOCK, show mismatch table (override via --override-reason log debt)

Display:
```
Verify 1 (grep): {N} endpoints checked, {M} field comparisons
Result: {PASS|WARNING|BLOCK} — {N} mismatches
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_verify.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify 2>/dev/null || true
```
</step>

<step name="2c_verify_plan_paths">
## Sub-step 2c1b: PLAN PATH VALIDATION (no AI, <5 sec)

Catches stale `<file-path>` tags in PLAN — the class of bug seen in Phase 10:
- Task 2 PLAN said `apps/api/src/infrastructure/clickhouse/migrations/0017_add_deal_columns.sql`
  but that directory doesn't exist (real CH schemas in apps/workers/src/consumer/clickhouse/schemas.js)
- Task 12 PLAN said `apps/rtb-engine/src/auction/pipeline.rs`
  but that directory doesn't exist (real auction entry at apps/rtb-engine/src/handlers/bid.rs)

Both were only caught when the executor agent opened the file. This step runs
at blueprint time — catches them before /vg:build spawns executors.

```bash
PATH_CHECKER=".claude/scripts/verify-plan-paths.py"
if [ -f "$PATH_CHECKER" ]; then
  echo ""
  echo "━━━ Sub-step 2c1b: PLAN path validation ━━━"
  ${PYTHON_BIN:-python} "$PATH_CHECKER" \
    --phase-dir "${PHASE_DIR}" \
    --repo-root "${REPO_ROOT:-.}"
  PATH_EXIT=$?

  case "$PATH_EXIT" in
    0)
      echo "✓ All PLAN paths valid"
      ;;
    2)
      echo "⚠ PLAN has path warnings — review output above."
      echo "  If paths are intentional new subsystems, proceed (non-blocking)."
      echo "  If paths are stale, fix PLAN now before /vg:build spawns executors against wrong paths."
      # Non-blocking — planner may be creating new subsystems. User inspects.
      ;;
    1)
      echo "⛔ PLAN has malformed paths — fix PLAN.md before proceeding."
      exit 1
      ;;
  esac
else
  echo "⚠ verify-plan-paths.py missing — skipping PLAN path validation (older install)"
fi
```

Classifications:
- `VALID` — file exists (editing) OR parent dir exists (new file in existing dir) OR parent dir will be created by another task
- `WARN` — parent dir doesn't exist and no other task creates it (likely stale, but could be intentional new subsystem)
- `FAIL` — malformed path (absolute / escapes repo via `..` / has `+` separator / empty)

WARN → non-blocking report. User can `<also-edits>foo/bar/` on an upstream task to declare the new dir is intentional.
FAIL → hard exit 1. PLAN author must fix.

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_verify_plan_paths" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_verify_plan_paths.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify_plan_paths 2>/dev/null || true
```
</step>

<step name="2c1c_verify_utility_reuse">
## Sub-step 2c1c: UTILITY REUSE CHECK (no AI, <5 sec)

Catches PLAN tasks that redeclare helper functions already exported from the shared utility contract in `PROJECT.md` → `## Shared Utility Contract`. Root cause of ~1500-2500 LOC duplicate seen in Phase 10 audit (16 files declaring own `formatCurrency`, 52 occurrences of `Intl.NumberFormat currency` pattern).

```bash
UTILITY_CHECKER=".claude/scripts/verify-utility-reuse.py"
PROJECT_MD="${PLANNING_DIR}/PROJECT.md"

if [ -f "$UTILITY_CHECKER" ] && [ -f "$PROJECT_MD" ]; then
  echo ""
  echo "━━━ Sub-step 2c1c: Utility reuse check (prevent duplicate helpers) ━━━"
  ${PYTHON_BIN:-python} "$UTILITY_CHECKER" \
    --project "$PROJECT_MD" \
    --phase-dir "${PHASE_DIR}"
  UTIL_EXIT=$?

  case "$UTIL_EXIT" in
    0)
      echo "✓ No utility-reuse violations"
      ;;
    2)
      echo "⚠ Utility-reuse warnings — consider consolidating into @vollxssp/utils"
      echo "  Non-blocking. If phase legitimately needs new helper, add Task 0 (extend utils) in PLAN."
      ;;
    1)
      echo "⛔ PLAN redeclares helpers already in shared utility contract."
      echo "   Fix: replace re-declaration with import from @vollxssp/utils, OR"
      echo "        if PLAN needs an extended variant, add Task 0 (extend utils) + reuse across tasks."
      echo "   Rationale: every duplicate helper adds AST nodes (tsc slowdown) + graphify noise."
      echo ""
      echo "Override (NOT recommended): /vg:blueprint ${PHASE_NUMBER} --override-reason=<issue-id>"
      if [[ ! "${ARGUMENTS:-}" =~ --override-reason= ]]; then
        exit 1
      fi
      echo "⚠ --override-reason set — proceeding with utility duplication debt"
      echo "utility-reuse: $(date -u +%FT%TZ) phase=${PHASE_NUMBER} override=yes" >> "${PHASE_DIR}/build-state.log"
      ;;
  esac
else
  [ ! -f "$UTILITY_CHECKER" ] && echo "⚠ verify-utility-reuse.py missing — skipping utility-reuse check (older install)"
  [ ! -f "$PROJECT_MD" ] && echo "⚠ PROJECT.md missing — skipping utility-reuse check (run /vg:project first)"
fi
```

BLOCK conditions:
- Task declares a function name (via `function X`, `const X =`, `export function X`, "add helper X", etc.) AND that name exists in the contract table.
- EXCEPTION: task's `<file-path>` is inside `packages/utils/` — that IS the canonical place.

WARN conditions:
- Task declares NEW helper (not in contract) AND spans ≥2 non-utils file paths — suggests reuse that should start in utils.

**Override:** `--override-reason=<issue-id>` on `/vg:blueprint` allows passing with debt logged. Use only when the new helper is genuinely phase-local (e.g., deal-specific formatter only used in 1 file forever).

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c1c_verify_utility_reuse" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c1c_verify_utility_reuse.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c1c_verify_utility_reuse 2>/dev/null || true
```
</step>

<step name="2c2_compile_check">
## Sub-step 2c2: CONTRACT COMPILE CHECK (no AI, <10 sec)

Extract executable code blocks from API-CONTRACTS.md → compile via `config.contract_format.compile_cmd`.
Catches contract syntax errors BEFORE build consumes them.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
# OHOK-9 round-4 Codex fix: invalid bash dotted substitution → use helper
COMPILE_CMD=$(vg_config_get contract_format.compile_cmd "")
CONTRACT_TYPE=$(vg_config_get contract_format.type "zod_code_block")

# Select code block language per contract_format.type:
#   zod_code_block / typescript_interface → ```typescript
#   openapi_yaml → ```yaml
#   pydantic_model → ```python
case "$CONTRACT_TYPE" in
  zod_code_block|typescript_interface) FENCE_LANG="typescript" ;;
  openapi_yaml)                        FENCE_LANG="yaml" ;;
  pydantic_model)                      FENCE_LANG="python" ;;
  *)                                   FENCE_LANG="typescript" ;;
esac

# Extract all matching fenced code blocks into tmp file
TMP_DIR=$(mktemp -d)
${PYTHON_BIN} - "$CONTRACTS" "$TMP_DIR" "$FENCE_LANG" "$CONTRACT_TYPE" <<'PYEOF'
import sys, re
from pathlib import Path
contracts, tmpdir, lang, ctype = sys.argv[1:5]
text = Path(contracts).read_text(encoding='utf-8')
pattern = re.compile(r"```" + re.escape(lang) + r"\s*\n(.*?)\n```", re.DOTALL)
blocks = pattern.findall(text)
if not blocks:
    print(f"NO_CODE_BLOCKS: expected ```{lang} blocks, found 0. Contract format violated.")
    sys.exit(3)

# Concatenate with appropriate prelude per type
prelude = ""
if ctype == "zod_code_block":
    prelude = "import { z } from 'zod';\n\n"
elif ctype == "pydantic_model":
    prelude = "from pydantic import BaseModel\nfrom typing import Optional, List, Literal\nfrom datetime import datetime\n\n"

ext = {"typescript": "ts", "yaml": "yaml", "python": "py"}.get(lang, "ts")
out = Path(tmpdir) / f"contracts-check.{ext}"
out.write_text(prelude + "\n\n".join(blocks), encoding='utf-8')
print(out)
PYEOF

COMPILE_INPUT=$(${PYTHON_BIN} ... last line)

# Run compile command on extracted file
if [ -n "$COMPILE_CMD" ]; then
  ACTUAL_CMD=$(echo "$COMPILE_CMD" | sed "s|{FILE}|$COMPILE_INPUT|g")
  # If no {FILE} placeholder, append file path
  [[ "$COMPILE_CMD" == *"{FILE}"* ]] || ACTUAL_CMD="$COMPILE_CMD $COMPILE_INPUT"

  eval "$ACTUAL_CMD" 2>&1 | tee "${PHASE_DIR}/contract-compile.log"
  EXIT=${PIPESTATUS[0]}
  if [ $EXIT -ne 0 ]; then
    echo "CONTRACT COMPILE FAILED — see ${PHASE_DIR}/contract-compile.log"
    echo "Fix contract syntax in ${PHASE_DIR}/API-CONTRACTS.md and re-run /vg:blueprint --from=2b"
    exit 1
  fi
fi
```

**Results:**
- PASS → contracts syntactically valid, proceed to 2d
- FAIL → BLOCK, show compile errors, user must fix API-CONTRACTS.md code blocks

Display:
```
Verify 2 (compile): {N} code blocks extracted
Compile check: {PASS|FAIL} via {config.contract_format.compile_cmd}
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c2_compile_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c2_compile_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c2_compile_check 2>/dev/null || true
```
</step>

<step name="2d_validation_gate">
## Sub-step 2d: VALIDATION GATE + AUTO-FIX RETRY + CROSSAI

**Combined step:** deterministic validation (plan↔SPECS↔goals↔contracts) + auto-fix retry loop + existing CrossAI review.

**Skip conditions:** none — this is the quality gate before commit.

### 2d-1: Load or create blueprint-state.json

```bash
STATE_FILE="${PHASE_DIR}/blueprint-state.json"
if [ -f "$STATE_FILE" ]; then
  # Resume scenario — prompt user
  LAST_STEP=$(jq -r .current_step "$STATE_FILE")
  LAST_ITER=$(jq -r '.iterations | length' "$STATE_FILE")
  LAST_MODE=$(jq -r '.validation_mode_chosen // "unknown"' "$STATE_FILE")
  echo "Blueprint state found for ${PHASE}:"
  echo "  Last step: $LAST_STEP  (iterations: $LAST_ITER)"
  echo "  Mode: $LAST_MODE"
  # AskUserQuestion: Resume / Restart from step / Fresh
fi

# Fresh start — init state
jq -n --arg phase "$PHASE" --arg ts "$(date -u +%FT%TZ)" '{
  phase: $phase,
  pipeline_version: "vg-v5.2",
  started_at: $ts,
  updated_at: $ts,
  current_step: "2d_validation",
  last_step_completed: "2c2_compile_check",
  steps_status: {
    "2a_plan": "completed", "2a5_cross_system": "completed",
    "2b_contracts": "completed", "2b4_design_ref_linkage": "pending",
    "2b5_test_goals": "completed", "2b7_flow_detect": "pending",
    "2c_verify_grep": "completed",
    "2c2_compile_check": "completed", "2d_validation": "in_progress",
    "3_complete": "pending"
  },
  validation_mode_chosen: null,
  thresholds: null,
  iterations: [],
  user_overrides: []
}' > "$STATE_FILE"
```

### 2d-2: Runtime prompt — strictness mode

**Skip if --auto (use config.plan_validation.default_mode):**

```
AskUserQuestion:
  "Plan validation strictness — AI will auto-fix up to 3 iterations with gap feedback."
  [Recommended: Strict]
  Options:
    - Strict (10% D / 15% G / 5% endpoints miss → BLOCK)
    - Default (20% / 30% / 10%)
    - Loose (40% / 50% / 20%)
    - Custom (enter values)
```

Save mode + thresholds to blueprint-state.json.

### 2d-3: Validation checks (deterministic, no AI)

For current iteration N (starts at 1):

```bash
# OHOK-8 round-4 Codex fix: real bash (was pseudocode) + namespace-aware regex.
# Previously grep '^D-[0-9]+' missed both '### D-XX:' legacy headers AND
# '### P{phase}.D-XX:' namespaced headers (scope v1.8+ canonical). Result:
# decision coverage gate false-passed with zero decisions found.

# Parse CONTEXT decisions — accepts bare D-XX AND namespaced P{phase}.D-XX
# headers (both with ### prefix per scope.md §§ generating format).
DECISIONS=$(grep -oE '^### (P[0-9.]+\.)?D-[0-9]+' "${PHASE_DIR}/CONTEXT.md" \
  | sed -E 's/^### //' | sort -u)
# Parse PLAN tasks with goals-covered
TASKS=$(grep -oE '^## Task [0-9]+' "${PHASE_DIR}"/PLAN*.md | sort -u)
# Parse TEST-GOALS — accepts both '### G-XX' and '### Goal G-XX' (phase 14 drift)
GOALS=$(grep -oE '^### (Goal\s+)?G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" \
  | sed -E 's/^### (Goal\s+)?//' | sort -u)
# Parse API-CONTRACTS endpoints
ENDPOINTS=$(grep -oE '^### (POST|GET|PUT|DELETE|PATCH) /' "${PHASE_DIR}/API-CONTRACTS.md" | sort -u)

# Cross-check 1 — Decisions covered by tasks (SPECS tracing)
decisions_missing=""
for D in $DECISIONS; do
  # Task attribute format: <goals-covered>G-01,G-02</goals-covered> OR
  # <implements-decision>P14.D-01</implements-decision>. Also accept bare
  # D-XX inside goals-covered for legacy tasks.
  if ! grep -rqE "(implements-decision[>:]\s*${D}|<goals-covered>[^<]*${D}\b)" \
       "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    decisions_missing="${decisions_missing} ${D}"
  fi
done

# Cross-check 2 — Goals covered by tasks (normal direction)
goals_missing=""
for G in $GOALS; do
  if ! grep -rqE "<goals-covered>[^<]*${G}\b" \
       "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    goals_missing="${goals_missing} ${G}"
  fi
done

# Cross-check 2-bis — Orphan goals flagged by step 2b5 bidirectional linkage
orphan_goals=$(grep -B1 "Implemented by:.*⚠ NONE" "${PHASE_DIR}/TEST-GOALS.md" \
  | grep -oE 'G-[0-9]+' | sort -u)
goals_missing=$(echo "${goals_missing} ${orphan_goals}" | tr ' ' '\n' | sort -u | tr '\n' ' ')

# Cross-check 3 — Endpoints covered by tasks
endpoints_missing=""
for E_HEADER in $ENDPOINTS; do
  # Extract METHOD + PATH from '### METHOD /path'
  E=$(echo "$E_HEADER" | sed -E 's/^### //')
  if ! grep -rqF "${E}" "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    endpoints_missing="${endpoints_missing} ${E}"
  fi
done

# Compute counts for percentage gate
DEC_TOTAL=$(echo "$DECISIONS" | wc -w)
DEC_MISS=$(echo "$decisions_missing" | wc -w)
GOAL_TOTAL=$(echo "$GOALS" | wc -w)
GOAL_MISS=$(echo "$goals_missing" | wc -w)
EP_TOTAL=$(echo "$ENDPOINTS" | wc -w)
EP_MISS=$(echo "$endpoints_missing" | wc -w)

# Percentages (bash arithmetic, guard against div-by-zero)
decisions_miss_pct=$(( DEC_TOTAL > 0 ? DEC_MISS * 100 / DEC_TOTAL : 0 ))
goals_miss_pct=$(( GOAL_TOTAL > 0 ? GOAL_MISS * 100 / GOAL_TOTAL : 0 ))
endpoints_miss_pct=$(( EP_TOTAL > 0 ? EP_MISS * 100 / EP_TOTAL : 0 ))
```

### 2d-3b: Deep blueprint completeness gates (Phase 17 polish — orphan validators wired)

Two Python validators historically existed (commits per Phase 7.14.3
retrospective: "AI lazy-read blueprint markdown rules → skip filter row +
pagination + state-machine guards → bugs runtime") but were ORPHANED —
not registered, not wired. Phase 17 polish wires them here so blueprint
quality is machine-checked, not just bash grep coverage.

These run AFTER the 2d-3 bash cross-checks pass surface-level (decisions/
goals/endpoints exist) — they then check DEPTH (does each endpoint have
auth_path + happy + 4xx + 401 goal coverage; does every list-view goal
declare interactive_controls; do mutation goals declare 4-layer
persistence check; etc.).

```bash
# Gate A: blueprint-completeness (C1 GOAL↔PLAN coverage; C2 ENDPOINT↔GOAL
#         coverage incl auth_path/happy/4xx/401)
BC_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-blueprint-completeness.py"
if [ -x "$BC_VAL" ]; then
  ${PYTHON_BIN} "$BC_VAL" --phase "${PHASE_NUMBER}" \
      --config "${REPO_ROOT}/.claude/vg.config.md" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/blueprint-completeness.json" 2>&1 || true
  BC_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
        "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/blueprint-completeness.json" 2>/dev/null)
  case "$BC_V" in
    PASS|WARN) echo "✓ blueprint-completeness: $BC_V" ;;
    BLOCK)
      echo "⛔ blueprint-completeness: BLOCK — see ${VG_TMP}/blueprint-completeness.json" >&2
      echo "   GOAL↔PLAN or ENDPOINT↔GOAL coverage gaps detected." >&2
      echo "   Override: --skip-blueprint-completeness (logs override-debt)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-blueprint-completeness ]]; then exit 1; fi
      ;;
    *) echo "ℹ blueprint-completeness: $BC_V" ;;
  esac
fi

# Gate B: test-goals-platform-essentials (filter row + pagination + column
#         visibility persistence + mutation 4-layer + state-machine guards)
TG_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-test-goals-platform-essentials.py"
if [ -x "$TG_VAL" ]; then
  ${PYTHON_BIN} "$TG_VAL" --phase "${PHASE_NUMBER}" \
      --config "${REPO_ROOT}/.claude/vg.config.md" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/test-goals-platform-essentials.json" 2>&1 || true
  TG_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
        "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/test-goals-platform-essentials.json" 2>/dev/null)
  case "$TG_V" in
    PASS|WARN) echo "✓ test-goals-platform-essentials: $TG_V" ;;
    BLOCK)
      echo "⛔ test-goals-platform-essentials: BLOCK — see ${VG_TMP}/test-goals-platform-essentials.json" >&2
      echo "   Phase 7.14.3 retrospective gaps detected (filter row / pagination /" >&2
      echo "   column visibility persistence / mutation 4-layer / state-machine guard)." >&2
      echo "   Override: --skip-platform-essentials (logs override-debt)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-platform-essentials ]]; then exit 1; fi
      ;;
    *) echo "ℹ test-goals-platform-essentials: $TG_V" ;;
  esac
fi
```

### 2d-3c: Phase 16 task schema + cross-AI output gates (hot-fix v2.11.1)

Phase 16 hot-fix wires two validators that were registered/documented but
never invoked from this skill body (cross-AI consensus BLOCKer 5).

**Gate C: verify-task-schema.py** — classify PLAN tasks as xml/heading/mixed.
Mode resolves from `vg.config.task_schema` (default: `legacy` → WARN-only
on heading format; `structured` → BLOCK heading; `both` → WARN both). XML
tasks REQUIRE frontmatter `acceptance: [...]` array (BLOCK if missing).

**Gate D: verify-crossai-output.py** — diff-based audit of cross-AI
enrichment (only fires when `--crossai` flag in arguments — gates the
output of /vg:blueprint --crossai or /vg:scope --crossai run that just
happened). Catches: long prose inlined into task body without context-refs
escape, and missing `cross_ai_enriched: true` flag in CONTEXT.md
frontmatter (which would silently disable Phase 16 D-04 R4 cap bumps).

```bash
# Gate C: task-schema (always runs; mode-aware)
TS_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-task-schema.py"
if [ -x "$TS_VAL" ]; then
  ${PYTHON_BIN} "$TS_VAL" --phase "${PHASE_NUMBER}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-schema.json" 2>&1 || true
  TS_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
        "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-schema.json" 2>/dev/null)
  case "$TS_V" in
    PASS|WARN) echo "✓ P16 task-schema: $TS_V" ;;
    BLOCK)
      echo "⛔ P16 task-schema: BLOCK — see ${VG_TMP}/task-schema.json" >&2
      echo "   Mode=structured rejects heading-format tasks, OR XML task missing" >&2
      echo "   frontmatter 'acceptance:' array. Migrate or add acceptance criteria." >&2
      echo "   Override: --skip-task-schema (logs override-debt)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-task-schema ]]; then exit 1; fi
      ;;
    *) echo "ℹ P16 task-schema: $TS_V" ;;
  esac
fi

# Gate D: crossai-output (gated on --crossai flag — only audits diff if a
# cross-AI enrichment actually ran)
if [[ "$ARGUMENTS" =~ --crossai ]]; then
  CO_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crossai-output.py"
  if [ -x "$CO_VAL" ]; then
    ${PYTHON_BIN} "$CO_VAL" --phase "${PHASE_NUMBER}" \
        > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/crossai-output.json" 2>&1 || true
    CO_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
          "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/crossai-output.json" 2>/dev/null)
    case "$CO_V" in
      PASS|WARN) echo "✓ P16 crossai-output: $CO_V" ;;
      BLOCK)
        echo "⛔ P16 crossai-output: BLOCK — see ${VG_TMP}/crossai-output.json" >&2
        echo "   Cross-AI inlined > 30 prose lines into a task body without adding" >&2
        echo "   <context-refs> ID. Move long prose to CONTEXT decision block." >&2
        echo "   Override: --skip-crossai-output (logs override-debt)" >&2
        if [[ ! "$ARGUMENTS" =~ --skip-crossai-output ]]; then exit 1; fi
        ;;
      *) echo "ℹ P16 crossai-output: $CO_V" ;;
    esac
  fi
fi
```

### 2d-4: Gate decision

```
Threshold T = state.thresholds (per chosen mode)

if decisions_miss_pct <= T.decisions_miss_pct AND
   goals_miss_pct <= T.goals_miss_pct AND
   endpoints_miss_pct <= T.endpoints_miss_pct:
  → PASS (proceed to CrossAI review 2d-6)
else if iteration < max_auto_fix_iterations (default 3):
  → AUTO-FIX (step 2d-5)
else:
  → EXHAUSTED (step 2d-7)
```

### 2d-5: Auto-fix iteration

```
# Backup current plan
ITER=$(jq '.iterations | length' "$STATE_FILE")
NEXT_ITER=$((ITER + 1))
cp "${PHASE_DIR}"/PLAN*.md "${PHASE_DIR}/PLAN.md.v${NEXT_ITER}"

# Write gap report
cat > "${PHASE_DIR}/GAPS-REPORT.md" <<EOF
# Gaps Report — Iteration $NEXT_ITER (Phase ${PHASE})

## Missing decisions (plan↔SPECS)
${decisions_missing[@]}

## Missing goals (plan↔TEST-GOALS)
${goals_missing[@]}

## Missing endpoints (plan↔API-CONTRACTS)
${endpoints_missing[@]}

## Instruction for planner
APPEND tasks covering the missing items. DO NOT rewrite existing tasks.
Match each new task to 1 missing `P{phase}.D-XX` / `F-XX`, G-XX, or endpoint.
EOF

# Refresh bootstrap rules for gap-closure planner (same injection discipline as 2a)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"

# Spawn planner via SlashCommand with gap context
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>

    PATCH MODE — do NOT replace existing PLAN.md. APPEND tasks covering gaps.
    Read ${PHASE_DIR}/GAPS-REPORT.md for specific missing items.
    Read ${PHASE_DIR}/PLAN.md for existing task structure.
    Add new tasks at the end as "Gap closure wave".
    Follow vg-planner-rules for task attribute schema.

# Update state
jq --arg n "$NEXT_ITER" --argjson gaps "$(cat ...)" \
   '.iterations += [{n: ($n|tonumber), gaps_found: $gaps, plan_backup: ("PLAN.md.v" + $n), status: "failed", timestamp: now|strftime("%FT%TZ")}] |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

# Re-run granularity check (2a post-check), bidirectional linkage (2b5 post-check),
# grep verify (2c), compile check (2c2)
# Then loop back to 2d-3 validation
```

### 2d-6: CrossAI review (when gate PASSED)

**v2.5.2.9+ enforcement** — explicit bash skip-gate thay vì prose "Skip if..." mà AI có thể silent fall-through.

```bash
# ─────────────────────────────────────────────────────────────────────────
# Explicit CrossAI skip enforcement (v2.5.2.9)
# Phase 7.14 precedent: blueprint CrossAI bị skip với rationale "UI-only no
# API change" rồi 7.15/7.16 copy-paste nguyên văn. 12+15+3 contract waives
# logged nhưng AI tự quyết — user không được hỏi.
# Now: guard chặn rubber-stamp + force event emit + debt log.
# ─────────────────────────────────────────────────────────────────────────

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-skip-guard.sh" 2>/dev/null || {
  echo "⚠ crossai-skip-guard.sh missing — skip audit không enforce được" >&2
}

SKIP_CAUSE_BP=$(crossai_detect_skip_cause "${ARGUMENTS:-}" ".claude/vg.config.md" 2>/dev/null || echo "")

if [ -n "$SKIP_CAUSE_BP" ]; then
  REASON_BP="blueprint CrossAI skip cho phase ${PHASE_NUMBER} (args=${ARGUMENTS:-none})"
  if ! crossai_skip_enforce "vg:blueprint" "$PHASE_NUMBER" "blueprint.2d_crossai_review" \
       "$SKIP_CAUSE_BP" "$REASON_BP"; then
    echo "⛔ Rubber-stamp guard chặn skip — exit." >&2
    echo "   Blueprint của phase này cần CrossAI chạy thật (không được copy lý do từ phase trước)." >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/2d_crossai_review.done"
  return 0 2>/dev/null || exit 0
fi

echo "▸ CrossAI blueprint review starting — phase ${PHASE_NUMBER}"
echo "  AI thứ 2 review plan + contracts + goals cho quality pass trước build."
```

Prepare context file at `${VG_TMP}/vg-crossai-{phase}-blueprint-review.md`:

```markdown
# CrossAI Blueprint Review — Phase {PHASE}

Gate passed deterministic validation. CrossAI reviews qualitative:

## Checklist
1. Plan covers all CONTEXT decisions (quick re-verify)
2. API contracts consistent with plan tasks
3. ORG 6 dimensions addressed (Infra/Env/Deploy/Smoke/Integration/Rollback)
4. Contract fields reasonable between request/response pairs
5. No duplicate endpoints or conflicting field definitions
6. Acceptance criteria are testable (not vague)
7. Design-refs linked appropriately (if config.design_assets non-empty)

## Verdict Rules
- pass: all checks pass, score >=7
- flag: minor quality concerns, score >=5
- block: missing/wrong content (deterministic gate should have caught — CrossAI as safety net)

## Artifacts
---
[CONTEXT.md content]
---
[PLAN*.md content — concatenated]
---
[API-CONTRACTS.md content]
---
[TEST-GOALS.md content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="blueprint-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

### CrossAI verdict explicit handling (v1.14.4+)

crossai-invoke.md set `$CROSSAI_VERDICT` ∈ {pass, flag, block, inconclusive}. Blueprint MUST branch explicit — không assume PASS khi CLI timeout/crash.

```bash
# crossai-invoke.md populated these vars:
#   CROSSAI_VERDICT: pass|flag|block|inconclusive
#   OK_COUNT + TOTAL_CLIS: số CLIs responded cleanly
#   CLI_STATUS[]: per-CLI status (ok|timeout|malformed|crash)

case "${CROSSAI_VERDICT:-unknown}" in
  pass)
    echo "✓ CrossAI: PASS (${OK_COUNT:-?}/${TOTAL_CLIS:-?} CLIs agreed)"
    ;;

  flag)
    echo "⚠ CrossAI: FLAG — minor concerns raised"
    echo "   Review ${PHASE_DIR}/crossai/result-*.xml for findings"
    echo "   Auto-fix path: apply Minor fixes inline, proceed to build"
    # Non-blocking — orchestrator applies minor fixes + continues
    ;;

  block)
    echo "⛔ CrossAI: BLOCK — major/critical concerns"
    echo "   ${PHASE_DIR}/crossai/result-*.xml chứa findings cần resolve"
    echo ""
    echo "Orchestrator MUST:"
    echo "  1. Parse findings XML → surface to user via AskUserQuestion (recommended option first)"
    echo "  2. User accept fix → apply, re-invoke crossai until PASS/FLAG"
    echo "  3. User reject → block_resolve_l4_stuck + exit"
    # Do NOT auto-proceed. Orchestrator handles via AskUserQuestion pattern below.
    exit 2
    ;;

  inconclusive)
    echo "⛔ CrossAI: INCONCLUSIVE (${OK_COUNT:-0}/${TOTAL_CLIS:-?} CLIs responded cleanly)"
    echo "   Timeout/crash/malformed → không thể treat silence = agreement."
    echo ""
    if [[ "$ARGUMENTS" =~ --allow-crossai-inconclusive ]]; then
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "blueprint-crossai-inconclusive" "${PHASE_NUMBER}" "${OK_COUNT:-0}/${TOTAL_CLIS:-?} CLIs inconclusive" "$PHASE_DIR"
      fi
      echo "⚠ --allow-crossai-inconclusive set — proceeding, logged to debt"
    else
      echo "Fix options:"
      echo "  1. Retry (có thể CLI tạm thời down): /vg:blueprint ${PHASE_NUMBER} --from=2d"
      echo "  2. Skip CrossAI tầng 3-opinion: /vg:blueprint ${PHASE_NUMBER} --from=2d --skip-crossai"
      echo "  3. Accept inconclusive (log debt): /vg:blueprint ${PHASE_NUMBER} --from=2d --allow-crossai-inconclusive"
      exit 1
    fi
    ;;

  unknown|"")
    echo "⚠ CrossAI: verdict chưa set — có thể crossai-invoke.md skip logic (empty config.crossai_clis) hoặc --skip-crossai flag"
    # This is OK — orchestrator chose to skip, không block
    ;;

  *)
    echo "⛔ CrossAI: unexpected verdict '${CROSSAI_VERDICT}' — check crossai-invoke.md output"
    exit 1
    ;;
esac
```

**Handle findings (when verdict=flag, auto-fix minors):**
- Minor → auto-fix (update contracts or plan)
- Major/Critical → present to user via AskUserQuestion, re-verify if fixed

**MANDATORY when escalating CrossAI concerns to user (AskUserQuestion):**

For EACH user-judgment concern (e.g., schema-vs-storage choice, architectural fork, test-strategy
trade-off), the orchestrator MUST present options with an explicit recommended option. Pattern:

1. **Pick the recommended option** before showing the question — base on:
   - CrossAI consensus (if 2+ CLIs converge on same fix → that's the recommendation)
   - Project context (CONTEXT.md decision wins over post-hoc PLAN drift)
   - Codebase reality (if existing pattern in repo, prefer aligning to it)
   - Security / correctness > convenience
2. **Order options with recommended FIRST**, label with " (Recommended)" suffix.
3. **Explain WHY recommended** in the option's `description` field — not just what it is.
4. **Do NOT ask without recommendation** — silent multi-option choices put rationalization burden on user.
   Per global guidance: "If you recommend a specific option, make that the first option in the
   list and add '(Recommended)' at the end of the label."

Bad example (no recommendation):
```
AskUserQuestion: "Refresh storage backend?"
  - Redis-only
  - Mongo collection
  - Both
```

Good example (with recommendation):
```
AskUserQuestion: "Refresh token storage backend? Recommend Both — Mongo source-of-truth survives
restart + Redis JTI cache provides fast revocation. CrossAI Codex flagged single-layer as conflict-prone."
  - Both (Mongo persist + Redis cache) (Recommended)  — production-grade, audit-friendly, fast revocation
  - Mongo only — simpler, slower revocation (each refresh checks DB)
  - Redis only — fast but loses sessions on restart
```

Apply this pattern to ALL CrossAI-escalation questions. The user can still pick a non-recommended
option (or "Other") — the recommendation just provides a default path so they don't have to
re-derive the analysis CrossAI just did.

### 2d-7: Exhausted — user intervention

```
echo "Plan validation exhausted after ${max_auto_fix_iterations} iterations."
echo "Remaining gaps:"
echo "  Decisions missing: ${decisions_missing[@]}"
echo "  Goals missing: ${goals_missing[@]}"
echo "  Endpoints missing: ${endpoints_missing[@]}"
echo ""
echo "Options:"
echo "  (a) /vg:blueprint ${PHASE} --override        → accept gaps, proceed with warning"
echo "  (b) Edit PLAN.md manually → /vg:blueprint ${PHASE} --from=2d"
echo "  (c) /vg:scope ${PHASE}                       → refine SPECS/CONTEXT (root cause may be spec gap)"

# Mark state exhausted, preserve for resume
jq '.steps_status["2d_validation"] = "exhausted"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
exit 1
```

### 2d-8: PASSED — finalize state

```
jq '.steps_status["2d_validation"] = "completed" |
    .current_step = "3_complete" |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
```

Display:
```
Plan validation: PASSED (iteration $N/${max})
  Decisions covered: $C/$total ($pct%)
  Goals covered: $C/$total ($pct%)
  Endpoints covered: $C/$total ($pct%)
  Mode: $MODE
CrossAI review: $verdict ($score/10)
Proceeding to commit.
```

```bash
# R7 step marker (v1.14.4+ — enforced via 3_complete gate)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_validation_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_validation_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_validation_gate 2>/dev/null || true
# v1.15.2 — fix marker drift. Frontmatter runtime_contract declares
# "2d_crossai_review" but body historically only wrote "2d_validation_gate"
# → Stop hook always blocked on a marker that never existed. Touch both now.
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_crossai_review" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_crossai_review.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review 2>/dev/null || true

# Emit contract-declared telemetry + release run on clean blueprint exit
type -t vg_emit >/dev/null 2>&1 && {
  vg_emit "blueprint.plan_written"         "{\"phase\":\"${PHASE_NUMBER}\"}"
  vg_emit "blueprint.contracts_generated"  "{\"phase\":\"${PHASE_NUMBER}\"}"
}
# (OHOK-3 2026-04-22) Legacy vg_run_complete call removed — canonical
# `python vg-orchestrator run-complete` runs at terminal block below.
```
</step>

<step name="2e_bootstrap_reflection">
## Sub-step 2e: End-of-Step Reflection (v1.15.0 Bootstrap Overlay)

Before final commit, spawn reflector to analyze PLAN*.md + API-CONTRACTS.md +
TEST-GOALS.md + user messages for learnings about the planning step.

**Skip silently if `.vg/bootstrap/` absent.** Follow protocol in
`.claude/commands/vg/_shared/reflection-trigger.md`:

```bash
if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="blueprint"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 Running end-of-blueprint reflection..."
  # Spawn Agent with vg-reflector skill (see reflection-trigger.md)
  # Interactive y/n/e/s prompt for each candidate, delegate to /vg:learn --promote
fi
```
</step>

<step name="3_complete">

### R7 step markers verify gate (v1.14.4+)

Trước khi commit blueprint artifacts, verify mọi step đã touch marker. Missing marker = step silently skipped → blueprint incomplete.

```bash
EXPECTED_STEPS=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/blueprint.md \
  --profile "${PHASE_PROFILE:-feature}" \
  --output-ids 2>/dev/null || echo "")

if [ -z "$EXPECTED_STEPS" ]; then
  echo "⚠ filter-steps.py unavailable — skipping marker verify (soft)"
else
  MISSING_MARKERS=""
  IFS=',' read -ra STEP_ARR <<< "$EXPECTED_STEPS"
  for step in "${STEP_ARR[@]}"; do
    step=$(echo "$step" | xargs)
    [ -z "$step" ] && continue
    # step 3_complete marker written below; skip self-check
    [ "$step" = "3_complete" ] && continue
    if [ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]; then
      MISSING_MARKERS="${MISSING_MARKERS} ${step}"
    fi
  done

  if [ -n "$MISSING_MARKERS" ]; then
    echo "⛔ R7 violation: blueprint steps silently skipped —${MISSING_MARKERS}"
    echo "   Blueprint không được commit với steps thiếu. Nguyên nhân phổ biến:"
    echo "   - Flag --from=2b/2c/2d skip step trước"
    echo "   - Step fail mid-execution nhưng không early exit"
    echo "   - Code path bypass touch command"
    echo ""
    echo "   Fix options:"
    echo "   1. Re-run /vg:blueprint ${PHASE_NUMBER} (không --from) để chạy đủ steps"
    echo "   2. --override-reason='<explicit>' nếu cố tình skip (log debt)"
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      exit 1
    else
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "blueprint-r7-missing-markers" "${PHASE_NUMBER}" "steps skipped:${MISSING_MARKERS}" "$PHASE_DIR"
      fi
      echo "⚠ --override-reason set — proceeding despite R7 breach, logged to debt"
    fi
  else
    STEP_COUNT=$(echo "$EXPECTED_STEPS" | tr ',' '\n' | wc -l | tr -d ' ')
    echo "✓ R7 markers complete: ${STEP_COUNT} steps"
  fi
fi
```

### Display summary

Count plans, endpoints, decisions. Display:
```
Blueprint complete for Phase {N}.
  Plans: {N} created
  API contracts: {N} endpoints defined
  Verify 1 (grep): {verdict}
  CrossAI: {verdict} ({score}/10)
  Next: /vg:build {phase}
```

Commit all artifacts (track every blueprint output — N9 fix: prevent UI-MAP-AS-IS / TEST-GOALS / UI-SPEC / UI-MAP / FLOW-SPEC silent orphan):
```bash
git add "${PHASE_DIR}/PLAN"*.md \
        "${PHASE_DIR}/API-CONTRACTS.md" \
        "${PHASE_DIR}/TEST-GOALS.md" \
        "${PHASE_DIR}/crossai/"
# Optional artifacts — only present when the relevant generator fired this phase.
for opt in UI-SPEC.md UI-MAP.md UI-MAP-AS-IS.md FLOW-SPEC.md; do
  [ -f "${PHASE_DIR}/${opt}" ] && git add "${PHASE_DIR}/${opt}"
done
git commit -m "blueprint({phase}): plans + contracts + goals — CrossAI {verdict}"
```

```bash
# R7 step marker (self-final)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3_complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 3_complete 2>/dev/null || true

# v2.2 — terminal emit + run-complete. Validators fire here; BLOCK on violations.
PLAN_COUNT=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | wc -l | tr -d ' ')
ENDPOINT_COUNT=$(grep -c '^## ' "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || echo 0)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"plans\":${PLAN_COUNT},\"endpoints\":${ENDPOINT_COUNT}}" >/dev/null

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ blueprint run-complete BLOCK — review orchestrator output + fix before /vg:build" >&2
  exit $RUN_RC
fi
```
</step>

</process>

<success_criteria>
- CONTEXT.md verified as prerequisite
- PLAN*.md created via GSD planner with ORG check
- API-CONTRACTS.md generated from code + CONTEXT
- Verify 1 (grep) passed — contracts match code
- CrossAI reviewed (or skipped if no CLIs)
- All artifacts committed
- Next step guidance shows /vg:build
</success_criteria>
