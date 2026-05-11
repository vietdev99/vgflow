<step name="2_persist_summary">
## Step 2 — Merge results into DEPLOY-STATE.json + summary

Merge per-env results into `${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}`
block. Preserves `preferred_env_for` / `preferred_env_for_skipped` and any
unrelated future keys. Print summary table + emit telemetry. Merge logic
lives in `scripts/vg-deploy-merge-summary.py` (extracted from this slim
entry per shared-build pattern).

```bash
MERGE_OUT=$(${PYTHON_BIN:-python3} .claude/scripts/vg-deploy-merge-summary.py \
  --phase "${PHASE_NUMBER}" --phase-dir "${PHASE_DIR}" \
  --results-json "${DEPLOY_RESULTS_JSON}")
echo "$MERGE_OUT" | grep -v '^RESULT_PAYLOAD='
RESULT_PAYLOAD=$(echo "$MERGE_OUT" | grep '^RESULT_PAYLOAD=' | head -1 | sed 's/^RESULT_PAYLOAD=//')

if echo "$RESULT_PAYLOAD" | grep -q '"failed_envs": \[\]'; then
  EVENT_TYPE="phase.deploy_completed"; OUTCOME="PASS"
else
  EVENT_TYPE="phase.deploy_failed"; OUTCOME="WARN"
fi

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "$EVENT_TYPE" --actor "orchestrator" --outcome "$OUTCOME" \
  --payload "$RESULT_PAYLOAD" 2>/dev/null || true
[ "$EVENT_TYPE" != "phase.deploy_completed" ] && ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "phase.deploy_completed" --actor "orchestrator" --outcome "INFO" \
  --payload "$RESULT_PAYLOAD" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2_persist_summary" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_persist_summary.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy 2_persist_summary 2>/dev/null || true
```
</step>

### Post-deploy reflector trigger (Section 13.5 / meta-memory v1.1)

After `phase.deploy_completed` emits, spawn vg-reflector subagent IF
`meta_memory_mode != "disabled"`:

```bash
# Check rollout flag
META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" "$VG_CONFIG_PATH" 2>/dev/null | awk '{print $2}' || echo "disabled")

if [ "$META_MEMORY_MODE" != "disabled" ] && [ "$EVENT_TYPE" = "phase.deploy_completed" ]; then
  # Narrate spawn (orchestrator UX baseline R2)
  bash scripts/vg-narrate-spawn.sh vg-reflector spawning "post-deploy candidate draft"

  # Emit telemetry that reflector trigger was requested
  ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
    "reflection.trigger_requested" --actor "deploy" --outcome "INFO" \
    --metadata "{\"step\":\"deploy\",\"phase\":\"${PHASE_NUMBER}\",\"trigger\":\"post-deploy\"}"

  # Note: actual subagent spawn is performed by the agent that owns this run.
  # This snippet only marks the event; orchestrator/skill flow handles dispatch.
fi
```

**Inputs to reflector:**
- `events.db` query: `deploy.{started,completed,failed}` for current phase
- `${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}` block
- `${PHASE_DIR}/.deploy-log.{env}.txt` per env stdout
- `vg.config.md` env list, deploy commands, package manager

**Candidate target:** `target_step=deploy`, `type=procedural`.

**Fingerprint:** `hash(repo_id + deploy_target + health_cmd + env + commands + dockerfile_hash + package_manager)`.

<step name="complete">
## Final — mark + run-complete

Before `run-complete`, close the native tasklist:
- Claude Code: mark every deploy checklist item completed via `TodoWrite`,
  then clear the list if supported; otherwise replace it with one completed
  sentinel: `vg:deploy phase ${PHASE_NUMBER} complete`.
- Codex CLI: update the compact plan to completed/sentinel so no previous
  workflow list remains visible.

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete 2>&1 | tail -1 || true
```
</step>
