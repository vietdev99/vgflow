# blueprint close (STEP 6)

Final 2 steps: bootstrap reflection + run-complete (with R7 marker verify,
traceability gates, terminal telemetry, tasklist clear).

<HARD-GATE>
You MUST execute both steps. The Stop hook verifies:
- All `must_write` artifacts present + content_min_bytes met
- All `must_emit_telemetry` events present
- All `must_touch_markers` touched (per filter-steps profile)
- vg.block.fired count == vg.block.handled count
- State machine ordering valid

If ANY fails → exit 2 + diagnostic. Else → run successful + tasklist
projected closed/cleared per `close-on-complete`.
</HARD-GATE>

---

## STEP 6.1 — bootstrap reflection (2e_bootstrap_reflection)

Before final commit, spawn reflector to analyze PLAN*.md + API-CONTRACTS.md +
TEST-GOALS.md + user messages for learnings about the planning step.

**Skip silently if `.vg/bootstrap/` absent.** Follow protocol in
`.claude/commands/vg/_shared/reflection-trigger.md`.

```bash
vg-orchestrator step-active 2e_bootstrap_reflection

if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="blueprint"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 Running end-of-blueprint reflection..."

  # Spawn vg-reflector via Skill tool (existing skill from R0):
  #   Skill(skill="vg-reflector", args="--phase ${PHASE_NUMBER} --command vg:blueprint --output ${REFLECT_OUT}")
  #
  # Reflector reads PLAN*.md + API-CONTRACTS.md + TEST-GOALS.md +
  # last 30 user messages. Output: candidate learnings YAML.
  # Interactive y/n/e/s prompt for each candidate, delegate to /vg:learn --promote.
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2e_bootstrap_reflection" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2e_bootstrap_reflection.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2e_bootstrap_reflection 2>/dev/null || true
```

---

## STEP 6.2 — run complete (3_complete)

### 6.2.1 — R7 step-markers verify gate (BLOCK on missing)

Trước khi commit, verify mọi step đã touch marker. Missing marker = step
silently skipped → blueprint incomplete.

```bash
vg-orchestrator step-active 3_complete

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
    [ "$step" = "3_complete" ] && continue  # self-marker written below
    if [ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]; then
      MISSING_MARKERS="${MISSING_MARKERS} ${step}"
    fi
  done

  if [ -n "$MISSING_MARKERS" ]; then
    echo "⛔ R7 violation: blueprint steps silently skipped —${MISSING_MARKERS}"
    echo "   Blueprint không được commit với steps thiếu. Nguyên nhân:"
    echo "   - Flag --from=2b/2c/2d skip step trước"
    echo "   - Step fail mid-execution nhưng không early exit"
    echo "   - Code path bypass touch command"
    echo ""
    echo "   Fix:"
    echo "   1. Re-run /vg:blueprint ${PHASE_NUMBER} (no --from) để chạy đủ"
    echo "   2. --override-reason='<text>' nếu cố tình skip (log debt)"
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      exit 1
    else
      # Canonical override.used emit — runtime_contract.forbidden_without_override
      # requires an exact override.used.flag match for --override-reason.
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag "--override-reason" \
        --reason "blueprint R7 missing markers:${MISSING_MARKERS}" \
        >/dev/null 2>&1 || true
      type -t log_override_debt >/dev/null 2>&1 && \
        log_override_debt "blueprint-r7-missing-markers" "${PHASE_NUMBER}" "steps skipped:${MISSING_MARKERS}" "$PHASE_DIR"
      echo "⚠ --override-reason set — proceeding despite R7 breach, debt logged"
    fi
  else
    STEP_COUNT=$(echo "$EXPECTED_STEPS" | tr ',' '\n' | wc -l | tr -d ' ')
    echo "✓ R7 markers complete: ${STEP_COUNT} steps"
  fi
fi
```

### 6.2.2 — display summary

```bash
PLAN_COUNT=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | wc -l | tr -d ' ')
ENDPOINT_COUNT=$(grep -c '^## ' "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || true)
ENDPOINT_COUNT="${ENDPOINT_COUNT:-0}"
echo ""
echo "Blueprint complete for Phase ${PHASE_NUMBER}."
echo "  Plans: ${PLAN_COUNT} created"
echo "  API contracts: ${ENDPOINT_COUNT} endpoints defined"
echo "  Verify 1 (grep): see step 5.1 output"
echo "  CrossAI: see step 5.5.6 output"
echo "  Next: /vg:build ${PHASE_NUMBER}"
```

### 6.2.3 — commit all artifacts

Track every blueprint output (N9 fix: prevent silent orphans of
UI-MAP-AS-IS / TEST-GOALS / UI-SPEC / UI-MAP / FLOW-SPEC).

```bash
# Layer 3 flat artifacts (legacy compat — root files)
git add "${PHASE_DIR}/PLAN"*.md \
        "${PHASE_DIR}/API-CONTRACTS.md" \
        "${PHASE_DIR}/TEST-GOALS.md" \
        "${PHASE_DIR}/crossai/" 2>/dev/null

# Layer 1+2 split artifacts — declared in blueprint.md must_write
# (PLAN/index.md + PLAN/task-*.md, API-CONTRACTS/*.md, TEST-GOALS/G-*.md).
# Without these, /vg:build's vg-load --task / --endpoint / --goal lookups
# silently fall back to flat reads (defeating context-budget split).
for split_dir in PLAN API-CONTRACTS TEST-GOALS; do
  if [ -d "${PHASE_DIR}/${split_dir}" ]; then
    git add "${PHASE_DIR}/${split_dir}/" 2>/dev/null || true
  fi
done

# Optional artifacts — only present when relevant generator fired
for opt in INTERFACE-STANDARDS.md INTERFACE-STANDARDS.json CRUD-SURFACES.md \
           UI-SPEC.md UI-MAP.md UI-MAP-AS-IS.md FLOW-SPEC.md \
           VIEW-COMPONENTS.md TEST-GOALS-EXPANDED.md \
           TEST-GOALS.codex-proposal.md TEST-GOALS.codex-delta.md; do
  [ -f "${PHASE_DIR}/${opt}" ] && git add "${PHASE_DIR}/${opt}"
done

git commit -m "blueprint(${PHASE_NUMBER}): plans + contracts + goals — CrossAI ${CROSSAI_VERDICT:-skipped}"
```

### 6.2.4 — write 3_complete marker

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3_complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 3_complete 2>/dev/null || true
```

### 6.2.5 — Phase 6 traceability gates (v2.46+)

Closes "AI bịa goal/decision" gap. Migration: pre-2026-05-01 phases use
`VG_TRACEABILITY_MODE=warn`; new phases default `block`.

```bash
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"

# L6a — goal frontmatter completeness (spec_ref + decisions + business_rules + expected_assertion + goal_class)
TRACE_VAL=".claude/scripts/validators/verify-goal-traceability.py"
if [ -f "$TRACE_VAL" ]; then
  TRACE_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-traceability-gaps ]] && TRACE_FLAGS="$TRACE_FLAGS --allow-traceability-gaps"
  ${PYTHON_BIN:-python3} "$TRACE_VAL" --phase "${PHASE_NUMBER}" $TRACE_FLAGS
  TRACE_RC=$?
  if [ "$TRACE_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Goal traceability gate failed."
    echo "   Goals must cite: spec_ref, decisions, business_rules, expected_assertion, goal_class."
    echo "   Template: commands/vg/_shared/templates/TEST-GOAL-enriched-template.md"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.traceability_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

# D-XX → tasks coverage
DTASK_VAL=".claude/scripts/validators/verify-decisions-to-tasks.py"
if [ -f "$DTASK_VAL" ]; then
  DTASK_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-uncovered-decisions ]] && DTASK_FLAGS="$DTASK_FLAGS --allow-uncovered-decisions"
  ${PYTHON_BIN:-python3} "$DTASK_VAL" --phase "${PHASE_NUMBER}" $DTASK_FLAGS
  DTASK_RC=$?
  if [ "$DTASK_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Decisions → tasks coverage gate failed."
    echo "   Every D-XX in CONTEXT must be referenced in ≥1 PLAN*.md task."
    exit 1
  fi
fi

# D-XX → goals coverage
DGOAL_VAL=".claude/scripts/validators/verify-decisions-to-goals.py"
if [ -f "$DGOAL_VAL" ]; then
  DGOAL_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-uncovered-decisions ]] && DGOAL_FLAGS="$DGOAL_FLAGS --allow-uncovered-decisions"
  ${PYTHON_BIN:-python3} "$DGOAL_VAL" --phase "${PHASE_NUMBER}" $DGOAL_FLAGS
  DGOAL_RC=$?
  if [ "$DGOAL_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Decisions → goals coverage gate failed."
    echo "   Every D-XX must be cited by ≥1 goal in TEST-GOALS.md (decisions: [D-XX])."
    exit 1
  fi
fi
```

### 6.2.5b — Task 38: verify BLOCK 5 FE consumer contracts (before blueprint.completed)

```bash
# Task 38 — run verify-fe-contract-block5.py before close. BLOCKs if BLOCK 5
# is missing on any endpoint. Legacy phases escape via --allow-block5-missing
# (set ALLOW_BLOCK5_MISSING_FLAG from slim-entry arg-parser when user passes flag).
BLOCK5_VALIDATOR="${REPO_ROOT:-.}/.claude/scripts/validators/verify-fe-contract-block5.py"
if [ -f "$BLOCK5_VALIDATOR" ] && [ -d "${PHASE_DIR}/API-CONTRACTS" ]; then
  python3 "$BLOCK5_VALIDATOR" \
    --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
    ${ALLOW_BLOCK5_MISSING_FLAG:-}
  rc=$?
  if [ "$rc" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event blueprint.fe_contract_block5_blocked --phase "${PHASE_NUMBER}" 2>/dev/null || true
    echo "BLOCK: BLOCK 5 FE contract validator failed. Use --allow-block5-missing for legacy phases." >&2
    exit "$rc"
  fi
fi
```

### 6.2.6 — terminal telemetry + run-complete

```bash
# Terminal telemetry per runtime_contract
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"plans\":${PLAN_COUNT},\"endpoints\":${ENDPOINT_COUNT}}" >/dev/null

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ blueprint run-complete BLOCK — review orchestrator output + fix before /vg:build" >&2
  exit $RUN_RC
fi
```

### 6.2.7 — tasklist close-on-complete

Mark all checklist items completed via TodoWrite. Then either clear the
list (preferred) or replace with one sentinel:
`vg:blueprint phase ${PHASE_NUMBER} complete`.

The PostToolUse TodoWrite hook captures the final state for evidence.

---

## Success criteria

- CONTEXT.md verified as prerequisite (STEP 1.5)
- PLAN*.md created via vg-blueprint-planner with ORG 6-dim check (STEP 3)
- API-CONTRACTS.md generated from code + CONTEXT (STEP 4)
- TEST-GOALS.md + CRUD-SURFACES.md generated with persistence + URL state (STEP 4)
- Verify 1 (grep) PASS (STEP 5.1)
- 8 deterministic Python validators PASS or WARN (STEP 5.5.4)
- Auto-fix loop converged or exhausted with debt (STEP 5.5.5)
- CrossAI consensus verdict ∈ {pass, flag} or skipped with debt (STEP 5.5.6)
- D18 test_type + PR-F goal_grounding gates PASS (STEP 5.6, 5.7)
- R7 markers verified (STEP 6.2.1)
- Phase 6 traceability gates PASS (STEP 6.2.5)
- All artifacts committed (STEP 6.2.3)
- `blueprint.completed` telemetry emitted (STEP 6.2.6)
- `vg-orchestrator run-complete` exits 0 (STEP 6.2.6)
- Stop hook verifies runtime_contract + state-machine + diagnostic pairing
- Tasklist closed/cleared (STEP 6.2.7)
- Next step guidance shows `/vg:build ${PHASE_NUMBER}`
