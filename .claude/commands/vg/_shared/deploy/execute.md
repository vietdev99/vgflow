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

  read_cmd() {
    VG_DEPLOY_ENV="$env" VG_DEPLOY_KEY="$1" ${PYTHON_BIN:-python3} <<'PY' 2>/dev/null
import os, re
cfg = os.environ['VG_CONFIG_PATH']
env = os.environ.get('VG_DEPLOY_ENV', '')
key = os.environ.get('VG_DEPLOY_KEY', '')
text = open(cfg, encoding='utf-8').read()
em = re.search(r'^[ \t]+%s:[ \t]*$' % re.escape(env), text, re.M)
if not em:
    print('')
    raise SystemExit
tail = text[em.end():]
nm = re.search(r'^[ \t]{2}[A-Za-z0-9_-]+:[ \t]*$', tail, re.M)
section = tail[:nm.start()] if nm else tail
m = re.search(r'^[ \t]+%s:[ \t]*["\']?([^"\'\n]*)' % re.escape(key), section, re.M)
print(m.group(1).strip() if m else '')
PY
  }

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
  META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" "$VG_CONFIG_PATH" 2>/dev/null | awk '{print $2}' || echo "disabled")
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
