# accept cleanup (STEP 8 — HEAVY, subagent)

Maps to step `7_post_accept_actions` (306 lines in legacy accept.md).
Final post-accept lifecycle: scan-intermediate cleanup, bootstrap rule
attribution, VG-native state update, CROSS-PHASE-DEPS flip, DEPLOY-RUNBOOK
lifecycle, telemetry consolidation.

<HARD-GATE>
DO NOT cleanup inline. You MUST spawn `vg-accept-cleanup` via the `Agent`
tool. The 306-line step has 8+ subroutines (scan cleanup, screenshot
cleanup, worktree prune, bootstrap outcome attribution, PIPELINE-STATE
update, ROADMAP flip, CROSS-PHASE-DEPS flip, RUNBOOK draft+promote).
Inline execution will skim — empirical 96.5% skip rate without subagent.

Cleanup runs ONLY when UAT verdict is ACCEPTED. For DEFER/REJECTED/FAILED
verdicts, the cleanup short-circuits to a minimal lifecycle update (UAT.md
already written) and exits.
</HARD-GATE>

<step name="7_post_accept_actions">

## Pre-spawn narration

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 7_post_accept_actions 2>/dev/null || true

bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup spawning "post-accept ${PHASE_NUMBER}"
```

## Spawn

Read `delegation.md` for the input/output contract. Then call:

```
Agent(subagent_type="vg-accept-cleanup", prompt=<built from delegation>)
```

### Codex runtime spawn path

If the runtime is Codex, apply
`commands/vg/_shared/codex-spawn-contract.md` instead of calling the
Claude-only `Agent(...)` syntax:

1. Render `delegation.md` into
   `${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-accept-cleanup.prompt.md`.
2. Run `codex-spawn.sh --tier executor --sandbox workspace-write
   --spawn-role vg-accept-cleanup --spawn-id vg-accept-cleanup` with
   `--out ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-accept-cleanup.json`.
3. Set `SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"` and run output validation +
   post-subagent hard-exit gates unchanged.
4. Treat missing helper, missing Codex CLI, non-zero exit, empty output,
   malformed JSON, verdict mismatch, or failed hard-exit gate as a HARD BLOCK.

Do NOT cleanup inline on Codex.

## Post-spawn narration

On success:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup returned "<count> actions"
```

On failure:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup failed "<one-line cause>"
```

## Output validation

Subagent returns:
```json
{
  "verdict": "ACCEPTED" | "DEFER" | "REJECTED" | "FAILED" | "ABORTED",
  "cleanup_actions_taken": [
    "rm scan-*.json",
    "rm probe-*.json",
    "git worktree prune",
    "bootstrap.outcome_recorded x{N}",
    "PIPELINE-STATE → complete",
    "ROADMAP flip → complete",
    "CROSS-PHASE-DEPS flip {N} rows",
    "DEPLOY-RUNBOOK.md.staged → DEPLOY-RUNBOOK.md"
  ],
  "files_archived": ["..."],
  "files_removed": ["..."],
  "summary": "ACCEPTED phase {PHASE_NUMBER} — {N} cleanup actions"
}
```

After return, validate:
1. `verdict` matches the verdict written to `${PHASE_NUMBER}-UAT.md`
2. `cleanup_actions_taken[]` non-empty for ACCEPTED verdict (DEFER/REJECTED
   may be empty — subagent short-circuits)
3. PIPELINE-STATE.json `status=complete` and `pipeline_step=accepted` for
   ACCEPTED verdict

## Post-subagent hard-exit gates (main agent ONLY)

The subagent is forbidden from running these (exit-1 semantics belong to
the main agent; subagent error JSON cannot propagate `exit 1` to the Stop
hook). Run all 3 in order AFTER the subagent returns successfully:

### Gate A — Traceability chain (verify-acceptance-traceability.py)

```bash
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"
ATRACE_VAL=".claude/scripts/validators/verify-acceptance-traceability.py"
if [ -f "$ATRACE_VAL" ]; then
  ATRACE_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-traceability-gaps ]] && ATRACE_FLAGS="$ATRACE_FLAGS --allow-traceability-gaps"
  ${PYTHON_BIN:-python3} "$ATRACE_VAL" --phase "${PHASE_NUMBER}" $ATRACE_FLAGS
  ATRACE_RC=$?
  if [ "$ATRACE_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Acceptance traceability chain broken — phase cannot ship."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "accept.traceability_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

### Gate B — Profile marker contract

Every profile-applicable accept step MUST have its marker. Without this,
SkipTheatreNet bypasses the must_touch_markers contract.

```bash
EXPECTED_ACCEPT_STEPS=$(${PYTHON_BIN:-python3} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/accept.md \
  --profile "${PROFILE:-web-fullstack}" \
  --output-ids 2>/dev/null || echo "")
MISSING_ACCEPT_MARKERS=""
for STEP_ID in $(echo "$EXPECTED_ACCEPT_STEPS" | tr ',' ' '); do
  [ -z "$STEP_ID" ] && continue
  [ "$STEP_ID" = "7_post_accept_actions" ] && continue
  if [ -f "${PHASE_DIR}/.step-markers/accept/${STEP_ID}.done" ] || \
     [ -f "${PHASE_DIR}/.step-markers/${STEP_ID}.done" ]; then :
  else
    MISSING_ACCEPT_MARKERS="${MISSING_ACCEPT_MARKERS} ${STEP_ID}"
  fi
done
if [ -n "$(echo "$MISSING_ACCEPT_MARKERS" | xargs)" ]; then
  echo "⛔ /vg:accept profile marker gate BLOCKED — missing markers for profile ${PROFILE:-web-fullstack}:"
  for STEP_ID in $MISSING_ACCEPT_MARKERS; do echo "   - ${STEP_ID}"; done
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "accept.marker_gate_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"profile\":\"${PROFILE:-web-fullstack}\",\"missing\":\"$(echo "$MISSING_ACCEPT_MARKERS" | xargs)\"}" \
    >/dev/null 2>&1 || true
  exit 1
fi
```

### Gate C — Marker + terminal emit + run-complete

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_post_accept_actions" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_post_accept_actions.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 7_post_accept_actions 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ accept run-complete BLOCK — review orchestrator output + fix" >&2
  exit $RUN_RC
fi
```

The Stop hook verifies all 17 step markers are present + UAT.md
content_min_bytes satisfied + .uat-responses.json present + Verdict line
matches must_write contract.

</step>
