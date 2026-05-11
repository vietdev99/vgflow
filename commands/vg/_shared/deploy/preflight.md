<step name="0_parse_and_validate">
## Step 0 — Parse args, validate prerequisites

```bash
PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
[ -z "$PHASE_NUMBER" ] && { echo "⛔ Usage: /vg:deploy <phase> [flags]"; exit 1; }

# Resolve phase dir (zero-padding tolerant)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-resolver.sh" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR=$(resolve_phase_dir "$PHASE_NUMBER" 2>/dev/null)
else
  PHASE_DIR=$(ls -d .vg/phases/${PHASE_NUMBER}* 2>/dev/null | head -1)
fi

if [ -z "$PHASE_DIR" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "⛔ Phase ${PHASE_NUMBER} not found in .vg/phases/"
  exit 1
fi

# Resolve project config. Global-only installs keep project data in .vg/config.md;
# legacy project-local installs used .claude/vg.config.md.
VG_CONFIG_PATH="${VG_CONFIG_PATH:-}"
if [ -z "$VG_CONFIG_PATH" ]; then
  for candidate in ".vg/config.md" ".claude/vg.config.md" "vg.config.md"; do
    if [ -f "$candidate" ]; then
      VG_CONFIG_PATH="$candidate"
      break
    fi
  done
fi
if [ -z "$VG_CONFIG_PATH" ]; then
  echo "⛔ Config not found. Expected .vg/config.md or legacy .claude/vg.config.md."
  echo "   Run /vg:init or /vg:update --repair to restore project config."
  exit 1
fi
export VG_CONFIG_PATH

# Build-complete check (override: --allow-build-incomplete)
BUILD_STATUS=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('${PHASE_DIR}/PIPELINE-STATE.json'))
  print(d.get('steps', {}).get('build', {}).get('status', 'unknown'))
except Exception:
  print('missing')" 2>/dev/null)

case "$BUILD_STATUS" in
  accepted|tested|reviewed|built-with-debt|built-complete|complete)
    echo "✓ Build status OK: ${BUILD_STATUS}"
    ;;
  *)
    if [[ "$ARGUMENTS" =~ --allow-build-incomplete ]]; then
      echo "⚠ Build status '${BUILD_STATUS}' but --allow-build-incomplete set — proceeding (override-debt logged)"
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
      type -t log_override_debt >/dev/null 2>&1 && \
        log_override_debt "--allow-build-incomplete" "${PHASE_NUMBER}" "deploy.0-prereq" \
          "deploy with build_status=${BUILD_STATUS}" "deploy-build-required"
    else
      echo "⛔ Build not complete (status: ${BUILD_STATUS}). Run /vg:build ${PHASE_NUMBER} first."
      echo "   Override (NOT recommended): --allow-build-incomplete"
      exit 1
    fi
    ;;
esac

# session lifecycle + run-start. Do not swallow failures: a started run
# without a tasklist contract is worse than a hard stop.
RUN_START_OUT="$(${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator run-start vg:deploy "${PHASE_NUMBER}" "${ARGUMENTS}" 2>&1)"
RUN_START_RC=$?
printf '%s\n' "$RUN_START_OUT"
if [ "$RUN_START_RC" -ne 0 ]; then
  echo "⛔ vg-orchestrator run-start failed for vg:deploy ${PHASE_NUMBER}" >&2
  exit "$RUN_START_RC"
fi
RUN_ID="$(printf '%s\n' "$RUN_START_OUT" | tail -1)"
export RUN_ID

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "phase.deploy_started" --actor "orchestrator" --outcome "INFO" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"args\":\"${ARGUMENTS}\"}"

# Task 44b — tasklist projection enforcement: emit the deploy taskboard so
# user sees planned steps and tasklist-contract.json is written for the
# PreToolUse hook gate. AI MUST then call TodoWrite (with ↳ sub-items per
# group) before any subsequent step-active.
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:deploy" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}"

# See `_shared/lib/tasklist-projection-instruction.md` for the full
# projection contract. After native tasklist projection, AI MUST call:
#   ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator tasklist-projected --adapter auto
# (`auto` resolves to `claude` or `codex`). Until evidence exists, every
# subsequent `step-active` / `mark-step` is BLOCKED by the PreToolUse Bash hook.
# Do not mark 0_parse_and_validate in this Bash call. First project TodoWrite,
# then run:
#   ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step deploy 0_parse_and_validate
```

### Step 0b — Native tasklist projection (mandatory, immediate)

Before `0a_env_select_and_confirm`, replace any stale native tasklist with the
contract for this run:

1. Read `.vg/runs/${RUN_ID}/tasklist-contract.json`.
2. Claude Code: call `TodoWrite` once with every `projection_items[]` entry,
   preserving group headers and `↳` sub-items, replacing the whole old list.
3. Codex CLI: update the compact plan window from `codex_plan_window`:
   active group/step first, next 2-3 pending, completed groups collapsed,
   plus `+N pending` if needed.
4. Run:
   ```bash
   ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator tasklist-projected --adapter auto
   ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step deploy 0_parse_and_validate
   ```

If `tasklist-projected` fails, stop and fix projection. Do not ask deploy env
or run deploy commands until this returns 0.
</step>

<step name="0a_env_select_and_confirm">
## Step 0a — Select envs (multi-select) + prod danger gate

**MANDATORY FIRST ACTION** (before any deploy work) — invoke
`AskUserQuestion` to pick which env(s) to deploy to, UNLESS one of:

- `${ARGUMENTS}` contains `--envs=<csv>` (parse + validate)
- `${ARGUMENTS}` contains `--all-envs` (deploy to ALL configured envs except local)
- `${ARGUMENTS}` contains `--non-interactive` (require `--envs=` to be set)

### Resolve selection from CLI flags first

```bash
SELECTED_ENVS=""
if [[ "$ARGUMENTS" =~ --envs=([a-z,]+) ]]; then
  SELECTED_ENVS="${BASH_REMATCH[1]}"
elif [[ "$ARGUMENTS" =~ --all-envs ]]; then
  SELECTED_ENVS=$(${PYTHON_BIN:-python3} -c "
import os, re
text = open(os.environ['VG_CONFIG_PATH'], encoding='utf-8').read()
m = re.search(r'^environments:\s*$', text, re.M)
if not m: print(''); exit()
tail = text[m.end():]
end = re.search(r'^[A-Za-z_][A-Za-z0-9_-]*:\s*', tail, re.M)
section = tail[:end.start()] if end else tail
envs = []
for em in re.finditer(r'^[ \t]{2}([A-Za-z0-9_-]+):\s*$', section, re.M):
  if em.group(1) != 'local':
    envs.append(em.group(1))
print(','.join(envs))")
fi
```

### AskUserQuestion (multi-select) — fires when no CLI flag

```
question: "Deploy phase ${PHASE_NUMBER} tới env nào? (chọn nhiều — sequential deploy)"
header: "Deploy targets"
multiSelect: true
options:
  - label: "sandbox — VPS Hetzner (printway.work)"
    description: "Production-like, ssh deploy. Mặc định cho phase ship-ready."
  - label: "staging — staging server"
    description: "CHỈ chọn nếu config có. Project hiện chưa cấu hình → sẽ fail."
  - label: "prod — production (CẢNH BÁO)"
    description: "Live traffic. Sẽ ask separate confirmation. CHỈ chọn khi review/test/UAT đều PASS."
```

### Apply selection + validate

```bash
# Convert AskUserQuestion answer to comma-separated list (or use CLI flag value)
[ -z "$SELECTED_ENVS" ] && SELECTED_ENVS="${SELECTED_ENVS_FROM_PROMPT:-}"

if [ -z "$SELECTED_ENVS" ]; then
  echo "⛔ No envs selected — abort"
  exit 1
fi

# Validate each env exists in config
for env in $(echo "$SELECTED_ENVS" | tr ',' ' '); do
  if ! grep -qE "^[[:space:]]+${env}:[[:space:]]*\$" "$VG_CONFIG_PATH"; then
    echo "⛔ Env '${env}' not found in vg.config.md environments — abort"
    exit 1
  fi
done

# Persist selection
mkdir -p "${PHASE_DIR}/.tmp"
echo "$SELECTED_ENVS" > "${PHASE_DIR}/.tmp/deploy-targets.txt"
echo "▸ Selected envs: ${SELECTED_ENVS}"
```

### Prod danger gate (separate AskUserQuestion)

If `prod` is in `$SELECTED_ENVS`:

```bash
if [[ ",${SELECTED_ENVS}," =~ ,prod, ]]; then
  PROD_OK="false"

  # Token-based non-interactive bypass
  EXPECTED_TOKEN="DEPLOY-PROD-${PHASE_NUMBER}"
  if [[ "$ARGUMENTS" =~ --prod-confirm-token=([A-Za-z0-9.\-]+) ]]; then
    if [ "${BASH_REMATCH[1]}" = "$EXPECTED_TOKEN" ]; then
      PROD_OK="true"
      echo "✓ Prod confirmation via --prod-confirm-token (token matched: ${EXPECTED_TOKEN})"
    else
      echo "⛔ --prod-confirm-token mismatch. Expected: ${EXPECTED_TOKEN}"
      exit 1
    fi
  elif [[ "$ARGUMENTS" =~ --non-interactive ]]; then
    echo "⛔ Prod selected in --non-interactive mode but no --prod-confirm-token=${EXPECTED_TOKEN}"
    echo "   Refusing to deploy prod without explicit token."
    exit 1
  else
    # Interactive — AI fires AskUserQuestion 3-option danger gate
    echo "▸ Prod in selection — AI: AskUserQuestion 3-option danger gate"
  fi
fi
```

**AskUserQuestion (interactive prod gate):**
Ask once with header `PROD CONFIRM`, no multi-select, options `ABORT`, `NON-PROD-ONLY`, `PROCEED`. Prompt must name prod + `${PHASE_NUMBER}` and require prior `/vg:review`, `/vg:test`, applicable `/vg:roam`, `/vg:accept`.

### Apply prod gate answer

```bash
case "$PROD_GATE_CHOICE" in
  *PROCEED*)
    PROD_OK="true"
    echo "✓ User confirmed PROD deploy"
    ;;
  *NON-PROD-ONLY*)
    SELECTED_ENVS=$(echo "$SELECTED_ENVS" | tr ',' '\n' | grep -v '^prod$' | tr '\n' ',' | sed 's/,$//')
    echo "▸ Prod removed; deploying: ${SELECTED_ENVS}"
    if [ -z "$SELECTED_ENVS" ]; then
      echo "⛔ Only prod was selected and user removed it — nothing to deploy"
      exit 0
    fi
    ;;
  *ABORT*|*)
    echo "⛔ User aborted prod deploy gate"
    exit 1
    ;;
esac

# Re-persist updated selection
echo "$SELECTED_ENVS" > "${PHASE_DIR}/.tmp/deploy-targets.txt"
```

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_env_select_and_confirm" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_env_select_and_confirm.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy 0a_env_select_and_confirm 2>/dev/null || true
```
</step>
