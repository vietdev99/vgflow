# blueprint preflight (STEP 1)

5 light steps: 0_design_discovery, 0_amendment_preflight, 1_parse_args,
create_task_tracker, 2_verify_prerequisites.

<HARD-GATE>
You MUST execute steps in order. Each step finishes with a marker touch +
`vg-orchestrator mark-step blueprint <step>`. Skipping ANY step = Stop hook block.

The PreToolUse Bash hook gates `vg-orchestrator step-active` calls. Each
step's bash must be wrapped with step-active before its real work and
mark-step after.
</HARD-GATE>

---

## STEP 1.1 — design discovery (0_design_discovery)

Before any planning work, verify FE phases have mockup ground truth.
Without mockups, the executor ships AI-imagined UI (the L-002 anti-pattern
this whole stack was built to prevent).

UI scope detection: Haiku 4.5 semantic analysis distinguishes scope-inclusion
vs scope-exclusion (e.g., "UI deferred to Phase X"). Result cached at
`${PHASE_DIR}/.ui-scope.json` as authoritative ground truth consumed by
this step's scaffold/extract gating, validators/verify-ui-scope-coherence.py,
and downstream UI steps 2b6_ui_spec / 2b6b / 2b6c.

If the phase has UI:
1. Detect existing mockups from phase `design/`, legacy phase `designs/`,
   `design_assets.paths`, and common repo mockup dirs.
2. Import existing raw mockups into `${PHASE_DIR}/design/`.
3. If still no mockups, automatically run `/vg:design-scaffold`.
4. Once raw mockups exist, automatically run `/vg:design-extract --auto` so
   PLAN generation can bind `<design-ref>` to real slugs.

```bash
vg-orchestrator step-active 0_design_discovery

DESIGN_DISCOVERY_ENABLED=$(vg_config_get design_discovery.enabled true 2>/dev/null || echo true)
if [ "$DESIGN_DISCOVERY_ENABLED" != "true" ]; then
  echo "ℹ design_discovery.enabled=false — skipping P20 D-12 pre-flight"
elif [[ "$ARGUMENTS" =~ --skip-design-discovery ]]; then
  echo "⚠ --skip-design-discovery set — Form B 'no-asset:greenfield-explicit-skip' will trigger /vg:accept critical block"
else
  mkdir -p "${PHASE_DIR}/.tmp"

  # AI semantic UI scope detection (replaces grep heuristic)
  UI_SCOPE_JSON="${PHASE_DIR}/.ui-scope.json"
  AI_SCOPE_DETECT_ENABLED=$(vg_config_get ui_scope.ai_detect_enabled true 2>/dev/null || echo true)

  if [ "$AI_SCOPE_DETECT_ENABLED" = "true" ] && { [ ! -f "$UI_SCOPE_JSON" ] || [[ "$ARGUMENTS" =~ --redetect-ui-scope ]]; }; then
    echo "▸ Detecting UI scope via Haiku semantic analysis..."
    DETECT_FLAGS=()
    [[ "$ARGUMENTS" =~ --redetect-ui-scope ]] && DETECT_FLAGS+=( --force )
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/preflight/detect-ui-scope.py" \
      --phase-dir "${PHASE_DIR}" \
      --output ".ui-scope.json" \
      "${DETECT_FLAGS[@]}" >/dev/null 2>&1
    UI_SCOPE_RC=$?

    case "$UI_SCOPE_RC" in
      0) echo "✓ UI scope auto-applied (confidence ≥ 0.8). See $UI_SCOPE_JSON" ;;
      2)
        echo "⚠ UI scope tie-break needed (confidence 0.5-0.8). Accept low-confidence result with debt log."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.ui_scope_tie_break" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
        ;;
      3)
        echo "⛔ UI scope confidence < 0.5 — operator must answer 'Phase này có UI không?'"
        echo "   Edit ${UI_SCOPE_JSON} manually (set has_ui + confidence + method=user-confirmed) or improve SPECS clarity then re-run with --redetect-ui-scope."
        if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
          exit 1
        fi
        ;;
      *) echo "⚠ detect-ui-scope.py exit=${UI_SCOPE_RC} — falling back to legacy grep heuristic" ;;
    esac
  fi

  # Read authoritative UI scope decision from .ui-scope.json (AI cache)
  HAS_UI=""
  if [ -f "$UI_SCOPE_JSON" ]; then
    HAS_UI=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('has_ui') else '0')" "$UI_SCOPE_JSON")
    UI_SCOPE_METHOD=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d.get('method','unknown'))" "$UI_SCOPE_JSON")
    UI_SCOPE_DEFERRED=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d.get('deferred_to') or 'none')" "$UI_SCOPE_JSON")
    echo "  has_ui=${HAS_UI} (method=${UI_SCOPE_METHOD}, deferred_to=${UI_SCOPE_DEFERRED})"
  fi

  BLUEPRINT_DESIGN_PREFLIGHT_JSON="${PHASE_DIR}/.tmp/blueprint-design-preflight.json"
  PREFLIGHT_EXTRA=()
  [[ "$ARGUMENTS" =~ --allow-shared-mockup-reuse ]] && PREFLIGHT_EXTRA+=( --allow-shared-mockup-reuse )
  "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/blueprint-design-preflight.py" \
    --phase-dir "${PHASE_DIR}" \
    --repo-root "${REPO_ROOT}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" \
    --apply \
    --output "${BLUEPRINT_DESIGN_PREFLIGHT_JSON}" \
    "${PREFLIGHT_EXTRA[@]}" >/dev/null

  if [ -z "${HAS_UI}" ]; then
    HAS_UI=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('has_ui') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
    echo "ℹ HAS_UI from legacy grep heuristic (.ui-scope.json not generated): ${HAS_UI}"
  fi
  IMPORTED_COUNT=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d.get('imported_count',0))" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
  NEEDS_SCAFFOLD=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('needs_scaffold') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
  NEEDS_EXTRACT=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('needs_extract') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
  PHASE_DESIGN_DIR=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d.get('phase_design_dir',''))" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
  SHARED_MANIFEST_EXISTS=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('shared_or_legacy_manifest_exists') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")

  if [ "$HAS_UI" = "1" ]; then
    echo "▸ Blueprint design preflight: UI phase detected. Report: $BLUEPRINT_DESIGN_PREFLIGHT_JSON"
    [ "${IMPORTED_COUNT:-0}" -gt 0 ] 2>/dev/null && echo "✓ Imported ${IMPORTED_COUNT} existing mockup file(s) into ${PHASE_DESIGN_DIR}"

    if [ "$NEEDS_SCAFFOLD" = "1" ]; then
      if [ "$SHARED_MANIFEST_EXISTS" = "1" ]; then
        echo "ℹ Note: shared/legacy design manifest exists, but this phase has 0 per-phase mockups."
        echo "   Strict policy: each UI phase needs its own mockups for new surfaces."
        echo "   Re-run with: /vg:blueprint <phase> --allow-shared-mockup-reuse if reusing slugs."
      fi
      echo "▸ No design mockups found — auto-running /vg:design-scaffold --tool=pencil-mcp"
      SlashCommand: /vg:design-scaffold --tool=pencil-mcp
      "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/blueprint-design-preflight.py" \
        --phase-dir "${PHASE_DIR}" --repo-root "${REPO_ROOT}" \
        --config "${REPO_ROOT}/.claude/vg.config.md" --apply \
        --output "${BLUEPRINT_DESIGN_PREFLIGHT_JSON}" "${PREFLIGHT_EXTRA[@]}" >/dev/null
      NEEDS_SCAFFOLD=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('needs_scaffold') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
      NEEDS_EXTRACT=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('needs_extract') else '0')" "$BLUEPRINT_DESIGN_PREFLIGHT_JSON")
      [ "$NEEDS_SCAFFOLD" = "1" ] && { echo "⛔ /vg:design-scaffold did not produce phase design assets."; exit 1; }
    fi

    if [ "$NEEDS_EXTRACT" = "1" ]; then
      echo "▸ Phase design assets need normalization — auto-running /vg:design-extract --auto"
      SlashCommand: /vg:design-extract --auto
      [ ! -f "${PHASE_DIR}/design/manifest.json" ] && { echo "⛔ /vg:design-extract did not produce manifest.json"; exit 1; }
    fi
  else
    echo "ℹ Blueprint design preflight: no UI signal in phase artifacts — design scaffold not required."
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "0_design_discovery" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_design_discovery.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 0_design_discovery 2>/dev/null || true
```

---

## STEP 1.2 — amendment preflight (0_amendment_preflight)

Before planning, enforce any `config_amendments_needed` locked during /vg:scope.
Running blueprint with stale config → tasks spawn against wrong surface paths.

```bash
vg-orchestrator step-active 0_amendment_preflight

# Inject rule cards: 5-30 line digest of skill rules instead of skimming 1500-line body.
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-blueprint" "0_amendment_preflight" 2>&1 || true

# Register run with orchestrator (idempotent if UserPromptSubmit hook already fired).
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start \
    vg:blueprint "${PHASE_NUMBER}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/amendment-preflight.sh"

AMEND_MODE="block"
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

# If amendments applied, commit config change before proceeding
if [ "$AMEND_MODE" = "apply" ]; then
  if ! git diff --quiet .claude/vg.config.md 2>/dev/null; then
    git add .claude/vg.config.md
    git commit -m "config(${PHASE_NUMBER}): apply scope amendments

Auto-applied via /vg:blueprint ${PHASE_NUMBER} --apply-amendments.
See PHASE_DIR/CONTEXT.md scope decisions for rationale."
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "0_amendment_preflight" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_amendment_preflight.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 0_amendment_preflight 2>/dev/null || true
```

Scanner reads `PIPELINE-STATE.steps.scope.config_amendments_needed[]`
(populated by `/vg:scope` step 5). Generic non-surface amendments require
manual edit — preflight blocks, user edits, re-runs.

---

## STEP 1.3 — parse args (1_parse_args)

Extract from `$ARGUMENTS`: phase_number (required), plus optional flags:
- `--skip-research`, `--gaps`, `--reviews`, `--text` — pass through to GSD planner
- `--crossai-only` — skip 2a/2b/2c, run only 2d (CrossAI review)
- `--skip-crossai` — run full blueprint but skip CrossAI review (faster + cheaper)
- `--from=2b|2c|2d` — resume from specific sub-step (R2 prereq assertion below)
- `--override-reason="<text>"` — bypass R2/R5/R7 gates, log to override-debt
- `--allow-missing-persistence` — bypass Rule 3b persistence gate. Log debt.
- `--allow-missing-org` — bypass Rule 6 ORG 6-dim gate. Log debt.
- `--allow-crossai-inconclusive` — treat CrossAI timeout as non-blocking. Log debt.
- `--skip-codex-test-goal-lane` — skip independent Codex TEST-GOALS lane. Log debt.

Validate: phase exists. Determine `$PHASE_DIR`.

**Skip logic:**
- `--crossai-only` → jump to step 2d_crossai_review
- `--from=2b` → skip 2a, start at 2b_contracts (PLAN*.md must exist)
- `--from=2c` → skip 2a+2b, start at 2c_verify (PLAN*.md + API-CONTRACTS.md must exist)
- `--from=2d` → same as `--crossai-only`

```bash
vg-orchestrator step-active 1_parse_args

# Register run so Stop hook can verify runtime_contract evidence
type -t vg_run_start >/dev/null 2>&1 && \
  vg_run_start "vg:blueprint" "${PHASE_NUMBER:-unknown}" "${ARGUMENTS:-}"

# Anti-forge: user sees authoritative step list at start.
# Emits blueprint.tasklist_shown event proving user had visibility.
# Required by runtime_contract.
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:blueprint" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true

# IMMEDIATELY after this block: apply TASKLIST_POLICY → project
# `.vg/runs/{run_id}/tasklist-contract.json` to native task UI and call
# `vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`.

# R2 skip prereq assertion: --from=X must verify prior steps actually completed.
FROM_STEP=""
if [[ "$ARGUMENTS" =~ --from=(2b|2c|2d|2b5|2b6|2b7) ]]; then
  FROM_STEP="${BASH_REMATCH[1]}"
fi

if [ -n "$FROM_STEP" ] || [[ "$ARGUMENTS" =~ --crossai-only ]]; then
  [[ "$ARGUMENTS" =~ --crossai-only ]] && FROM_STEP="2d"

  MISSING_PREREQ=""
  case "$FROM_STEP" in
    2b|2b5|2b6|2b7)
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/.step-markers/2a_plan.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2a_plan"
      ;;
    2c)
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/API-CONTRACTS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} API-CONTRACTS.md(step 2b)"
      [ -f "${PHASE_DIR}/TEST-GOALS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} TEST-GOALS.md(step 2b5)"
      [[ "$ARGUMENTS" =~ --skip-codex-test-goal-lane ]] || [ -f "${PHASE_DIR}/.step-markers/2b5a_codex_test_goal_lane.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2b5a_codex_test_goal_lane"
      ;;
    2d)
      ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 || MISSING_PREREQ="${MISSING_PREREQ} PLAN*.md(step 2a)"
      [ -f "${PHASE_DIR}/API-CONTRACTS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} API-CONTRACTS.md(step 2b)"
      [ -f "${PHASE_DIR}/TEST-GOALS.md" ] || MISSING_PREREQ="${MISSING_PREREQ} TEST-GOALS.md(step 2b5)"
      [[ "$ARGUMENTS" =~ --skip-codex-test-goal-lane ]] || [ -f "${PHASE_DIR}/.step-markers/2b5a_codex_test_goal_lane.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2b5a_codex_test_goal_lane"
      [ -f "${PHASE_DIR}/.step-markers/2c_verify.done" ] || MISSING_PREREQ="${MISSING_PREREQ} marker:2c_verify"
      ;;
  esac

  if [ -n "$MISSING_PREREQ" ]; then
    echo "⛔ R2 skip prerequisite missing for --from=${FROM_STEP}:"
    for p in $MISSING_PREREQ; do echo "   - ${p}"; done
    echo ""
    echo "Rule 2: 4 sub-steps must run IN ORDER. Prior artifacts missing → not actually complete."
    echo "Fix: chạy full /vg:blueprint ${PHASE_NUMBER} (bỏ --from)."
    echo "Override (NOT recommended): --override-reason='<reason>' (log debt)"
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      exit 1
    else
      # Canonical override.used emit — runtime_contract.forbidden_without_override
      # requires an exact override.used.flag match for --override-reason.
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag "--override-reason" \
        --reason "blueprint R2 skip prereq missing for --from=${FROM_STEP}: ${MISSING_PREREQ}" \
        >/dev/null 2>&1 || true
      type -t emit_telemetry_v2 >/dev/null 2>&1 && \
        emit_telemetry_v2 "blueprint_r2_skip_missing" "${PHASE_NUMBER}" "blueprint.1" "blueprint_r2_skip_missing" "FAIL" "{}"
      type -t log_override_debt >/dev/null 2>&1 && \
        log_override_debt "blueprint-r2-skip-missing" "${PHASE_NUMBER}" "--from=${FROM_STEP} with missing: ${MISSING_PREREQ}" "$PHASE_DIR"
      echo "⚠ --override-reason set — proceeding despite R2 breach, logged to debt"
    fi
  else
    echo "✓ R2 skip OK: all prerequisites present for --from=${FROM_STEP}"
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "1_parse_args" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_parse_args.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 1_parse_args 2>/dev/null || true
```

---

## STEP 1.4 — create task tracker (create_task_tracker)

**Bind native tasklist to blueprint hierarchical projection.**

`tasklist-contract.json` (schema `native-tasklist.v2`) contains:
- `checklists[]` — 6 coarse groups (preflight, design, plan, contracts, verify, close)
- `projection_items[]` — flat list of N items: 6 group headers + per-group sub-steps
  (each sub-step prefixed with `  ↳`). This is what TodoWrite projects.

<HARD-GATE>
You MUST IMMEDIATELY call TodoWrite AFTER the bash below runs. Do NOT continue
without TodoWrite — the PreToolUse Bash hook will block all subsequent
step-active calls until signed evidence exists at
`.vg/runs/<run_id>/.tasklist-projected.evidence.json`.

The PostToolUse TodoWrite hook auto-writes that signed evidence after your
TodoWrite call.
</HARD-GATE>

Required behavior:
1. Read `.vg/runs/<run_id>/tasklist-contract.json` → consume `projection_items[]`.
2. Call `TodoWrite` with one todo per `projection_items[]` entry — full hierarchy
   (group headers + sub-steps with `↳` prefix). Use the entry's `title` verbatim
   as todo `content`.
3. Call `vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`.
4. Keep `.step-markers/*.done` as the durable enforcement signal.

Per sub-step lifecycle:
- BEFORE sub-step work: set its sub-step todo `in_progress`. Group header
  stays `in_progress` while ANY of its sub-steps is pending/active.
- AFTER `mark-step` writes marker: set sub-step todo `completed`.
- When ALL sub-steps in a group are `completed`: set group header todo `completed`.
- On run-complete: clear projected tasklist per `close-on-complete`.

Example projection for vg:blueprint web-fullstack (32 items):
```
[ ] 📋 Blueprint Preflight (5 steps)
[ ]   ↳ 0_design_discovery
[ ]   ↳ 0_amendment_preflight
[ ]   ↳ 1_parse_args
[ ]   ↳ create_task_tracker
[ ]   ↳ 2_verify_prerequisites
[ ] 📋 Design Grounding (4 steps)
[ ]   ↳ 2_fidelity_profile_lock
... (continues for 6 groups, 26 sub-steps total)
```

```bash
vg-orchestrator step-active create_task_tracker

# (TodoWrite call happens here per HARD-GATE above — PostToolUse hook signs evidence)

# Bug D 2026-05-04: explicit emission — was previously instruction-text-only,
# AI could skip the tasklist-projected call and rely on PostToolUse implicit
# write. Now bash-enforced: blueprint.native_tasklist_projected MUST fire.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator tasklist-projected \
  --adapter "${VG_TASKLIST_ADAPTER:-claude}" || {
    echo "⛔ vg-orchestrator tasklist-projected failed — blueprint.native_tasklist_projected event will not fire." >&2
    echo "   Check .vg/runs/<run_id>/tasklist-contract.json + adapter ∈ {claude,codex,fallback}." >&2
    exit 1
}

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "create_task_tracker" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/create_task_tracker.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint create_task_tracker 2>/dev/null || true
```

---

## STEP 1.5 — verify prerequisites (2_verify_prerequisites)

Phase profile detection BEFORE prerequisite check.

```bash
vg-orchestrator step-active 2_verify_prerequisites

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

CONTEXT.md required ONLY for feature profile (other profiles skip scope + CONTEXT).

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
    BR_RESULT=$(block_resolve "blueprint-no-context" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" '[]')
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "blueprint-no-context" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
  fi
  echo "   Run first: /vg:scope ${PHASE_NUMBER}"
  exit 1
fi

# For non-feature profiles, skip scope and contracts generation.
if [ "$PHASE_PROFILE" != "feature" ]; then
  echo "ℹ Blueprint profile-aware mode: PHASE_PROFILE=${PHASE_PROFILE} — bỏ qua sub-steps 2b, 2b5, 2b7."
  echo "   Chỉ tạo PLAN.md (+ ROLLBACK.md nếu migration). CrossAI review vẫn áp dụng."
  export BLUEPRINT_PROFILE_SHORT_CIRCUIT=true
fi

# Interface standards locked before PLAN/API-CONTRACTS generated.
INTERFACE_GEN="${REPO_ROOT}/.claude/scripts/generate-interface-standards.py"
INTERFACE_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_GEN" ]; then
  "${PYTHON_BIN:-python3}" "$INTERFACE_GEN" \
    --phase-dir "${PHASE_DIR}" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}"
fi
if [ -f "$INTERFACE_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  "${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
    --phase-dir "${PHASE_DIR}" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    > "${PHASE_DIR}/.tmp/interface-standards-blueprint.json" 2>&1
  INTERFACE_RC=$?
  cat "${PHASE_DIR}/.tmp/interface-standards-blueprint.json"
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ INTERFACE-STANDARDS gate failed before blueprint generation."
    exit 1
  fi
fi
```

Design-extract auto-trigger (fixes G1):

```bash
DESIGN_PATHS=$(vg_config_get_array design_assets.paths)
if [ -n "$DESIGN_PATHS" ]; then
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/design-path-resolver.sh"
  DESIGN_PHASE_DIR="$(vg_design_phase_dir "$PHASE_DIR")"
  DESIGN_SHARED_DIR="$(vg_design_shared_dir)"
  DESIGN_LEGACY_DIR="$(vg_design_legacy_dir)"

  if [ -f "${DESIGN_PHASE_DIR}/manifest.json" ]; then
    DESIGN_OUT="$DESIGN_PHASE_DIR"
  elif [ -f "${DESIGN_SHARED_DIR}/manifest.json" ]; then
    DESIGN_OUT="$DESIGN_SHARED_DIR"
  elif [ -n "$DESIGN_LEGACY_DIR" ] && [ -f "${DESIGN_LEGACY_DIR}/manifest.json" ]; then
    DESIGN_OUT="$DESIGN_LEGACY_DIR"
    echo "⚠ Using legacy design dir ${DESIGN_LEGACY_DIR}/ — soft-deprecated since v2.30." >&2
  else
    DESIGN_OUT="$DESIGN_PHASE_DIR"
  fi
  DESIGN_MANIFEST="${DESIGN_OUT}/manifest.json"
  DESIGN_OUTPUT_DIR="$DESIGN_OUT"
  export DESIGN_OUTPUT_DIR DESIGN_MANIFEST

  NEEDS_EXTRACT=false
  if [ ! -f "$DESIGN_MANIFEST" ]; then
    NEEDS_EXTRACT=true; REASON="manifest missing"
  else
    while read -r pattern; do
      [ -z "$pattern" ] && continue
      if find $pattern -newer "$DESIGN_MANIFEST" 2>/dev/null | grep -q .; then
        NEEDS_EXTRACT=true; REASON="assets changed since last extract"; break
      fi
    done <<< "$DESIGN_PATHS"
  fi

  if [ "$NEEDS_EXTRACT" = true ]; then
    echo "Design assets detected, manifest $REASON. Auto-running /vg:design-extract --auto..."
    SlashCommand: /vg:design-extract --auto
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_verify_prerequisites" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_verify_prerequisites.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2_verify_prerequisites 2>/dev/null || true
```

After ALL 5 step markers touched, return to entry SKILL.md → STEP 2 (design).
