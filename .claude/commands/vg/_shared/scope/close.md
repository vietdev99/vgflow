# scope close (STEP 7)

> Marker: `5_commit_and_next`.
> Contract pin write, decisions-trace gate, atomic git commit, mark final step, emit `scope.completed`, run-complete.

<HARD-GATE>
Final step. §0 fires `step-active 5_commit_and_next` BEFORE work.
§5 fires `mark-step` + `scope.completed` event + `run-complete`.
If run-complete returns non-zero (Stop hook gate failure), exit non-zero
so the caller surfaces the violation.
</HARD-GATE>

## §0. Mark step active (gate enforcement)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 5_commit_and_next
```

## §1. PIPELINE-STATE summary

Update `${PHASE_DIR}/PIPELINE-STATE.json`:
- `steps.scope.status = "done"`
- `steps.scope.finished_at = <now>`
- `last_action = "scope: {N} decisions, {M} endpoints, {K} test scenarios"`

```bash
DECISION_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")
ENDPOINT_COUNT=$(grep -c '^\- .* /api/' "${PHASE_DIR}/CONTEXT.md" || echo 0)
TEST_SCENARIO_COUNT=$(grep -c '^\- TS-' "${PHASE_DIR}/CONTEXT.md" || echo 0)
```

## §2. Contract pin write (Tier B)

```bash
# Write per-phase contract pin so future harness upgrades that mutate
# must_touch_markers / must_emit_telemetry don't retroactively invalidate
# this phase. Subsequent /vg:blueprint, /vg:build, /vg:review, /vg:test,
# /vg:accept will validate against this pin instead of the live skill body.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-contract-pins.py write "${PHASE_NUMBER}" 2>/dev/null || \
  echo "⚠ contract-pin write failed (non-fatal — orchestrator will fall back to live skill)"
```

## §3. Atomic git add + commit

```bash
git add "${PHASE_DIR}/CONTEXT.md" \
        "${PHASE_DIR}/CONTEXT/" \
        "${PHASE_DIR}/DISCUSSION-LOG.md" \
        "${PHASE_DIR}/PIPELINE-STATE.json"
[ -f "${PHASE_DIR}/.contract-pins.json" ] && git add "${PHASE_DIR}/.contract-pins.json"
[ -f "${PHASE_DIR}/DEPLOY-STATE.json" ] && git add "${PHASE_DIR}/DEPLOY-STATE.json"
[ -f "${PHASE_DIR}/TEST-STRATEGY.md" ] && git add "${PHASE_DIR}/TEST-STRATEGY.md"

git commit -m "scope(${PHASE_NUMBER}): ${DECISION_COUNT} decisions, ${ENDPOINT_COUNT} endpoints, ${TEST_SCENARIO_COUNT} test scenarios"
```

## §4. Decisions-trace gate (D-XX → user answer in DISCUSSION-LOG)

```bash
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"
DTRACE_VAL=".claude/scripts/validators/verify-decisions-trace.py"
if [ -f "$DTRACE_VAL" ]; then
  DTRACE_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-decisions-untraced ]] && DTRACE_FLAGS="$DTRACE_FLAGS --allow-decisions-untraced"
  ${PYTHON_BIN:-python3} "$DTRACE_VAL" --phase "${PHASE_NUMBER}" $DTRACE_FLAGS
  DTRACE_RC=$?
  if [ "$DTRACE_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Decisions-trace gate failed: D-XX statements drift from DISCUSSION-LOG user answers."
    echo "   Add 'Quote source: DISCUSSION-LOG.md#round-N' field to each D-XX in CONTEXT.md."
    vg-orchestrator emit-event scope.decisions_trace_blocked \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

Closes "AI paraphrases user answer wrongly into D-XX" gap.

## §5. Mark final step + emit completion + run-complete

```bash
vg-orchestrator mark-step scope 5_commit_and_next
vg-orchestrator emit-event scope.completed \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"decisions\":${DECISION_COUNT},\"endpoints\":${ENDPOINT_COUNT},\"scenarios\":${TEST_SCENARIO_COUNT}}" >/dev/null

vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ scope run-complete BLOCK — review orchestrator output + fix before /vg:blueprint" >&2
  exit $RUN_RC
fi
```

## §6. Display summary

```
Scope complete for Phase {N}.
  Decisions: {N} ({business} business, {technical} technical)
  Endpoints: {M} noted
  UI Components: {K} noted
  Test Scenarios: {J} noted
  CrossAI: {verdict} ({score}/10) | skipped
  Validation: {pass_count}/4 checks passed, {warn_count} warnings
  Per-decision split: {N} CONTEXT/D-*.md files written

  Next: /vg:blueprint {phase}
```

## End

STEP 7 complete. Stop hook will validate runtime_contract artifacts + telemetry + markers. If all pass → run-complete already fired success. If any check fails, Stop hook emits `vg.block.fired` requiring `vg.block.handled` to clear.
