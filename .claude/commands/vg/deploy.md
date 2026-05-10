---
name: vg:deploy
description: Standalone deploy skill — multi-env (sandbox/staging/prod), writes deployed.{env} block to DEPLOY-STATE.json. Optional step between /vg:build and /vg:review/test/roam. Suggestion-only consumers downstream — this skill produces the data; runtime gates use it to recommend env via enrich-env-question.py.
argument-hint: "<phase> [--envs=sandbox,staging,prod] [--all-envs] [--dry-run] [--non-interactive] [--prod-confirm-token=DEPLOY-PROD-{phase}] [--allow-build-incomplete] [--pre-test]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - TodoWrite
runtime_contract:
  must_write:
    - "${PHASE_DIR}/DEPLOY-STATE.json"
  must_touch_markers:
    - "0_parse_and_validate"
    - "0a_env_select_and_confirm"
    - "1_deploy_per_env"
    - "2_persist_summary"
    - "complete"
  must_emit_telemetry:
    - event_type: "phase.deploy_started"
      phase: "${PHASE_NUMBER}"
    - event_type: "phase.deploy_completed"
      phase: "${PHASE_NUMBER}"
    # Task 44b — tasklist projection enforcement (Bug L)
    - event_type: "deploy.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "deploy.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "deploy.tasklist_projection_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_evidence_run_mismatch"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_depth_invalid"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_block_handled_unresolved"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
  forbidden_without_override:
    - "--allow-build-incomplete"
---

<HARD-GATE>
You MUST follow STEP 0 through `complete` in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.

You MUST call TodoWrite IMMEDIATELY after STEP 0 (`0_parse_and_validate`)
runs `emit-tasklist.py` — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The
PostToolUse TodoWrite hook auto-writes that signed evidence.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by the PostToolUse
depth check (Task 44b Rule V2 — `depth_valid=false` evidence triggers
the PreToolUse depth gate).
</HARD-GATE>

<rules>
1. **Build must be complete** — PIPELINE-STATE.steps.build.status ∈ {accepted, tested, reviewed, built-with-debt, built-complete}. Otherwise BLOCK (override: `--allow-build-incomplete` logs override-debt).
2. **Multi-env supported, sequential execution** — each env runs after the previous completes. Parallel would risk infrastructure contention (shared SSH connection, same DB seed, etc).
3. **Prod requires explicit confirmation** — separate AskUserQuestion 3-option danger gate (PROCEED / NON-PROD-ONLY / ABORT). For non-interactive runs, `--prod-confirm-token=DEPLOY-PROD-{phase}` must match exactly.
4. **Per-env failure handling** — DOES NOT auto-abort remaining envs. Ask user continue/skip-failed/abort-all. Failed env writes `health: "failed"` + error log.
5. **DEPLOY-STATE.json merges** — preserves `preferred_env_for` (set by /vg:scope step 1b), `preferred_env_for_skipped` flag, and any unrelated future keys. Only `deployed.{env}` block is rewritten per run.
6. **Rollback hint** — capture `previous_sha` from existing `deployed.{env}.sha` BEFORE overwriting. Future `/vg:rollback` consumer reads this.
7. **--dry-run** prints commands but doesn't execute. Useful for verifying config + flags before real deploy.
</rules>

<objective>
Standalone optional skill bridging /vg:build → /vg:review/test/roam. User
runs `/vg:deploy <phase>` after build, picks one or more envs, this skill
runs the canonical deploy sequence per env (build → restart → health) on
that target, captures SHA + timestamp + health into
`${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}` block.

Downstream env gates (review/test/roam step 0a) read this state via
`enrich-env-question.py` (B1) and surface "deployed Nmin ago, sha XXXX"
evidence in the AskUserQuestion options. The pipeline becomes:

```
specs → scope → blueprint → build → [DEPLOY] → review → test → [roam] → accept
                                       ↑                  ↑      ↑       ↑
                                   writes              all read DEPLOY-STATE
                                   DEPLOY-STATE        for env recommendation
```

This skill never auto-picks env at runtime gates — those still fire
AskUserQuestion. /vg:deploy just feeds the suggestion data layer.
</objective>

<process>

### Preflight section (extracted v2.73.0 T1)

Read `_shared/deploy/preflight.md` and follow it exactly.
Includes 2 steps: 0_parse_and_validate, 0a_env_select_and_confirm.

<step name="1_deploy_per_env">
## Step 1 — Deploy loop (sequential per env)

Per-env work delegated to `vg-deploy-executor`. Orchestrator only resolves
env config, narrates spawn, collects result JSON, asks user on failure.
Refs: `_shared/deploy/per-env-executor-contract.md` (spawn schema + post-spawn
validation), `_shared/deploy/overview.md` (flow). Initialize accumulator
(Step 2 reads this exact path):

```bash
DRY_RUN="false"
[[ "$ARGUMENTS" =~ --dry-run ]] && DRY_RUN="true"

LOCAL_SHA=$(git rev-parse --short HEAD)
DEPLOY_RESULTS_JSON="${PHASE_DIR}/.tmp/deploy-results.json"
mkdir -p "${PHASE_DIR}/.tmp"
echo '{"results":[]}' > "$DEPLOY_RESULTS_JSON"
```

For each env in `$SELECTED_ENVS`:

```bash
for env in $(echo "$SELECTED_ENVS" | tr ',' ' '); do
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Deploying to: ${env}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # ── Resolve env config from vg.config.md ──
  PREVIOUS_SHA=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('${PHASE_DIR}/DEPLOY-STATE.json'))
  print(d.get('deployed', {}).get('${env}', {}).get('sha', ''))
except Exception:
  print('')" 2>/dev/null)

  read_cmd() { ${PYTHON_BIN:-python3} -c "
import re
text = open('.claude/vg.config.md', encoding='utf-8').read()
em = re.search(r'^[[:space:]]+${env}:[[:space:]]*\$', text, re.M)
if not em: print(''); exit()
section = text[em.end():em.end()+5000]
m = re.search(r'^[[:space:]]+$1:[[:space:]]*\"([^\"]*)\"', section, re.M)
print(m.group(1) if m else '')" 2>/dev/null; }

  PRE_CMD=$(read_cmd "pre")
  BUILD_CMD=$(read_cmd "build")
  RESTART_CMD=$(read_cmd "restart")
  HEALTH_CMD=$(read_cmd "health")
  SEED_CMD=$(read_cmd "seed_command")
  RUN_PREFIX=$(read_cmd "run_prefix")

  if [ -z "$BUILD_CMD" ] && [ -z "$RESTART_CMD" ]; then
    echo "  env=${env} has no deploy.build / deploy.restart in config — skip"
    ${PYTHON_BIN:-python3} -c "
import json
d = json.load(open('${DEPLOY_RESULTS_JSON}'))
d['results'].append({'env': '${env}', 'health': 'failed', 'reason': 'no deploy commands in config', 'sha': '${LOCAL_SHA}', 'previous_sha': '${PREVIOUS_SHA}'})
open('${DEPLOY_RESULTS_JSON}', 'w').write(json.dumps(d))"
    continue
  fi

  # ── Stage 4 task 2/4 — pre-spawn meta-memory bootstrap inject (Section 13.5) ──
  # Loads deploy-specific procedural+declarative rules and exposes them via
  # BOOTSTRAP_RULES_BLOCK env var so the vg-deploy-executor capsule can read
  # them. Gated by vg.config.md::meta_memory_mode (default OFF — disabled).
  META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" vg.config.md 2>/dev/null | awk '{print $2}' || echo "disabled")
  BOOTSTRAP_RULES_BLOCK=""
  if [ "$META_MEMORY_MODE" = "inject-as-advice" ] || [ "$META_MEMORY_MODE" = "default" ]; then
    HAS_DOCKERFILE=$([ -f Dockerfile ] && echo "true" || echo "false")
    PRECONDITIONS_JSON="{\"env\": \"${env}\", \"has_dockerfile\": ${HAS_DOCKERFILE}}"

    RULES_JSON=$(${PYTHON_BIN:-python3} .claude/scripts/bootstrap-loader.py \
      --target-step deploy \
      --include-procedural \
      --filter-preconditions "$PRECONDITIONS_JSON" \
      --max-bytes 8192 \
      --emit rules 2>/dev/null || echo '{}')

    BOOTSTRAP_RULES_BLOCK=$(printf '%s' "$RULES_JSON" | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    data = json.loads(sys.stdin.read() or '{}')
except Exception:
    data = {}
parts = []
for r in (data.get('rules_procedural') or []):
    title = r.get('title', r.get('id', '?'))
    prose = (r.get('prose') or '')[:300]
    seq = r.get('sequence') or []
    seq_str = ' -> '.join([s.get('cmd','?') for s in seq][:5])
    parts.append(f'PROCEDURAL RECIPE: {title}\n  Prose: {prose}\n  Sequence: {seq_str}')
for r in (data.get('rules_declarative') or []):
    title = r.get('title', r.get('id', '?'))
    prose = (r.get('prose') or '')[:200]
    parts.append(f'DECLARATIVE: {title}\n  {prose}')
sys.stdout.write('\n\n'.join(parts))
" 2>/dev/null || echo "")

    export BOOTSTRAP_RULES_BLOCK
  fi

  # ── Spawn vg-deploy-executor (input schema: per-env-executor-contract.md §"Spawn site") ──
  bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=${PHASE_NUMBER} env=${env}"
  # AI: invoke Agent(subagent_type="vg-deploy-executor", prompt={phase, phase_dir,
  #     env, run_prefix, build_cmd, restart_cmd, health_cmd, seed_cmd, pre_cmd,
  #     local_sha, previous_sha, dry_run: ${DRY_RUN}, policy_ref,
  #     bootstrap_rules_block: $BOOTSTRAP_RULES_BLOCK}). Capture last
  #     stdout line into RESULT_JSON.

  # Parse result + narrate (post-spawn validation: contract §"Orchestrator post-spawn handling"):
  HEALTH=$(echo "$RESULT_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.load(sys.stdin)['health'])" 2>/dev/null || echo "unknown")
  ERROR=$(echo "$RESULT_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.load(sys.stdin).get('error') or 'none')" 2>/dev/null || echo "parse-failed")

  if [ "$HEALTH" = "failed" ]; then
    bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "env=${env} cause=${ERROR}"
  else
    bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "env=${env} health=${HEALTH}"
  fi

  # Append result to accumulator (Step 2 merges into DEPLOY-STATE.json)
  ${PYTHON_BIN:-python3} -c "
import json
acc = json.load(open('${DEPLOY_RESULTS_JSON}'))
acc['results'].append(json.loads('''${RESULT_JSON}'''))
open('${DEPLOY_RESULTS_JSON}', 'w').write(json.dumps(acc))"

  # Per-env failure handling (rule 4)
  if [ "$HEALTH" = "failed" ] && [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
    echo ""
    echo "  env=${env} deploy failed. AI: AskUserQuestion 3-option:"
    echo "    - continue    — chuyển sang env tiếp theo (skip failed env)"
    echo "    - abort-all   — dừng toàn bộ deploy loop, không deploy thêm env"
    echo "    - retry-once  — thử deploy lại env này 1 lần (clear log + re-run)"
  fi
done

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "1_deploy_per_env" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_deploy_per_env.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy 1_deploy_per_env 2>/dev/null || true
```

**MANDATORY POST-WAVE CONTINUATION:** After ALL per-env executor calls return (vg-deploy-executor across each selected env), you MUST IMMEDIATELY proceed to the NEXT STEP (Step 2 — persist summary + emit telemetry) IN THE SAME ASSISTANT TURN. Do NOT end the turn after per-env subagents return. The harness gates require sequential execution. See `vg-meta-skill.md` "Red Flags — Post-wave continuation" for rationale.
</step>

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
META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" vg.config.md 2>/dev/null | awk '{print $2}' || echo "disabled")

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

</process>

<success_criteria>
- Build prereq ok (or debt), selected envs exist, prod confirmed by AskUserQuestion or token.
- Env commands run sequentially; health retries 30s; failed env does not auto-abort siblings.
- DEPLOY-STATE.json merges `deployed.{env}`, preserves `preferred_env_for`, captures `previous_sha`.
- `phase.deploy_completed` telemetry emits; `${PHASE_DIR}/.deploy-log.{env}.txt` exists per env.
</success_criteria>
