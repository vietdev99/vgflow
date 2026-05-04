---
name: "vg-deploy"
description: "Standalone deploy skill — multi-env (sandbox/staging/prod), writes deployed.{env} block to DEPLOY-STATE.json. Optional step between /vg:build and /vg:review/test/roam. Suggestion-only consumers downstream — this skill produces the data; runtime gates use it to recommend env via enrich-env-question.py."
metadata:
  short-description: "Standalone deploy skill — multi-env (sandbox/staging/prod), writes deployed.{env} block to DEPLOY-STATE.json. Optional step between /vg:build and /vg:review/test/roam. Suggestion-only consumers downstream — this skill produces the data; runtime gates use it to recommend env via enrich-env-question.py."
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code and Codex now both have project-local hook substrates. VGFlow
`sync.sh`/`install.sh` installs `.codex/hooks.json` plus
`.codex/config.toml` with `[features].codex_hooks = true`. Codex hooks
wrap the same orchestrator that writes `.vg/events.db`, while command-body
guards remain mandatory because Codex hook coverage is still tool-path scoped:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Codex wrapper accepts both `/vg:cmd` and `$vg-cmd`; command-body `vg-orchestrator run-start` is still mandatory and must BLOCK if missing/failing |
| `PreToolUse` Bash -> `hooks/vg-pre-tool-use-bash.sh` | Blocks `vg-orchestrator step-active` until tasklist projection evidence is signed | Codex wrapper sets `CLAUDE_SESSION_ID`/`CLAUDE_HOOK_SESSION_ID` from Codex `session_id` and forwards to the same gate |
| `PreToolUse` Write/Edit -> `hooks/vg-pre-tool-use-write.sh` | Blocks direct writes to protected evidence, marker, and event paths | Codex `apply_patch` wrapper at `codex-hooks/vg-pre-tool-use-apply-patch.py` blocks the same protected paths before patch application |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Codex wrapper forwards Bash results to the same tracker; explicit `vg-orchestrator mark-step` lines remain required |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Codex wrapper runs the same verifier; command-body terminal `vg-orchestrator run-complete` is still required before claiming completion |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Codex hook processes cannot mutate the environment of later shell tool calls.
If a command-body shell lacks `CLAUDE_SESSION_ID`, `vg-orchestrator` recovers
the session from `.vg/.session-context.json` and the matching
`.vg/active-runs/<session>.json`. Do not create a fresh run when the
UserPromptSubmit hook already registered the same command/phase.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Before running any command-body snippet that calls validators, orchestrator
helpers, or `${PYTHON_BIN:-python3}`, execute the Python detection block from
`.claude/commands/vg/_shared/config-loader.md` in that same Bash shell and
export the selected `PYTHON_BIN`. Do not reset `PYTHON_BIN=python3` after
detection: on macOS, bare `python3` is often an older interpreter without
PyYAML, which makes VG validators fail even though a valid Homebrew/Python.org
interpreter is installed.

Each Codex shell tool call starts with a fresh environment. If a later command
invokes `.claude/scripts/*`, validators, or `vg-orchestrator`, redetect
`PYTHON_BIN` or carry the previously detected absolute interpreter into that
same command. Do not run `python3 .claude/scripts/...` directly for VG
validators/orchestrator calls.

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

For tasklist projection, Codex must write evidence as soon as
`tasklist-contract.json` exists: after `emit-tasklist.py`, run
`vg-orchestrator tasklist-projected --adapter codex` as its own tool call.
Do not group `tasklist-projected` and `step-active` in one shell command;
PreToolUse evaluates the entire command before the evidence file exists and
will block the grouped command. Some command preflights have bootstrap steps
before `emit-tasklist.py`; only those declared bootstrap steps may run before
the tasklist contract exists.

For top-level VG commands that include a mandatory `git commit` step, ensure
the parent Codex session can write Git metadata. Some Codex
`workspace-write` sandboxes deny `.git/index.lock`; when that happens,
BLOCK and ask the operator to rerun with a sandbox/profile that permits Git
metadata writes instead of skipping or forging the commit marker.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --spawn-role "<vg-subagent-role>" \
  --spawn-id "<stable-spawn-id>" \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.
When `--spawn-role` is set, it also writes Codex spawn evidence to
`.vg/runs/<run_id>/codex-spawns/` and appends
`.vg/runs/<run_id>/.codex-spawn-manifest.jsonl`. Codex Bash hooks block
heavy-step markers and `wave-complete` when required spawn evidence or
build wave `.spawn-count.json` is missing.

When creating prompt files for `codex-spawn.sh`, use a single-quoted heredoc
delimiter such as `cat > "$PROMPT_FILE" <<'EOF'` or write from an existing
template. Do not use unquoted `<<EOF` for prompts that contain backticks,
`$...`, command substitutions, or markdown code fences: the shell will
expand them before Codex sees the prompt and can corrupt the child contract.
If runtime variables must be injected, prefer a small controlled render step
that substitutes placeholders after the quoted template is written.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-deploy`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



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

# session lifecycle + run-start
${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator run-start vg:deploy "${PHASE_NUMBER}" "${ARGUMENTS}" 2>&1 | tail -1 || true

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "phase.deploy_started" --actor "orchestrator" --outcome "INFO" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"args\":\"${ARGUMENTS}\"}" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0_parse_and_validate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_parse_and_validate.done"
```
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
import re
text = open('.claude/vg.config.md', encoding='utf-8').read()
m = re.search(r'^environments:\s*\$', text, re.M)
if not m: print(''); exit()
section = text[m.end():m.end()+10000]
envs = []
for em in re.finditer(r'^\s+(local|sandbox|staging|prod):\s*\$', section, re.M):
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
  if ! grep -qE "^[[:space:]]+${env}:[[:space:]]*\$" .claude/vg.config.md; then
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

**AskUserQuestion (interactive prod gate, fires only if prod selected + no token):**

```
question: |
  ⚠️ DEPLOY TỚI **PRODUCTION** — phase ${PHASE_NUMBER}.

  Confirm bạn ĐÃ:
    ✓ /vg:review PASS trên sandbox
    ✓ /vg:test PASS trên sandbox
    ✓ /vg:roam (nếu apply) PASS trên staging hoặc sandbox
    ✓ /vg:accept human UAT đã làm

  Chọn chính xác (KHÔNG tap nhanh):
header: "PROD CONFIRM"
multiSelect: false
options:
  - label: "ABORT — không deploy gì hết"
    description: "An toàn nhất. Quit, kiểm tra lại trước khi thử lại."
  - label: "NON-PROD-ONLY — bỏ prod, deploy các env khác"
    description: "Deploy sandbox/staging trong selection, skip prod. Phù hợp khi muốn ship pre-prod trước, prod sau."
  - label: "PROCEED — yes deploy to PROD (đọc kỹ rồi mới chọn)"
    description: "Sẽ chạy deploy lên prod env. Live traffic sẽ thấy code mới. Chỉ chọn khi đã đủ 4 gate trên."
```

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

  # ── Spawn vg-deploy-executor (input schema: per-env-executor-contract.md §"Spawn site") ──
  bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=${PHASE_NUMBER} env=${env}"
  # AI: invoke Agent(subagent_type="vg-deploy-executor", prompt={phase, phase_dir,
  #     env, run_prefix, build_cmd, restart_cmd, health_cmd, seed_cmd, pre_cmd,
  #     local_sha, previous_sha, dry_run: ${DRY_RUN}, policy_ref}). Capture last
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
</step>

<step name="2_persist_summary">
## Step 2 — Merge results into DEPLOY-STATE.json + summary

Merge per-env results into `${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}`
block. Preserves `preferred_env_for` / `preferred_env_for_skipped` and any
unrelated future keys. Print summary table + emit telemetry.

```bash
${PYTHON_BIN:-python3} -c "
import json, sys
from pathlib import Path

results = json.load(open('${DEPLOY_RESULTS_JSON}'))['results']

state_path = Path('${PHASE_DIR}/DEPLOY-STATE.json')
if state_path.exists():
  state = json.loads(state_path.read_text(encoding='utf-8'))
else:
  state = {'phase': '${PHASE_NUMBER}'}

state.setdefault('deployed', {})
ok_envs, fail_envs = [], []
for r in results:
  env = r['env']
  state['deployed'][env] = {
    'sha': r['sha'],
    'deployed_at': r['deployed_at'],
    'health': r['health'],
    'deploy_log': r['deploy_log'],
    'previous_sha': r.get('previous_sha', ''),
    'dry_run': r.get('dry_run', False),
  }
  if r['health'] == 'ok' or r['health'] == 'dry-run':
    ok_envs.append(env)
  else:
    fail_envs.append(env)

state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print(f'  Deploy summary — phase ${PHASE_NUMBER}')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
for r in results:
  icon = '✓' if r['health'] in ('ok', 'dry-run') else '⛔'
  prev = f' (prev: {r[\"previous_sha\"]})' if r.get('previous_sha') else ''
  dry = ' [DRY-RUN]' if r.get('dry_run') else ''
  print(f'  {icon} {r[\"env\"]:10} sha={r[\"sha\"]} health={r[\"health\"]}{prev}{dry}')
print(f'  → DEPLOY-STATE.json updated ({len(ok_envs)} ok, {len(fail_envs)} failed)')
print()
if ok_envs:
  print('  Next: review/test/roam will see these envs as Recommended option')
  print(f'    /vg:review ${PHASE_NUMBER}    (env gate auto-suggests one of: {ok_envs})')
"

# Emit completion telemetry
RESULT_PAYLOAD=$(${PYTHON_BIN:-python3} -c "
import json
r = json.load(open('${DEPLOY_RESULTS_JSON}'))['results']
ok = [x['env'] for x in r if x['health'] in ('ok','dry-run')]
fail = [x['env'] for x in r if x['health'] not in ('ok','dry-run')]
print(json.dumps({'phase': '${PHASE_NUMBER}', 'ok_envs': ok, 'failed_envs': fail, 'total': len(r)}))")

if echo "$RESULT_PAYLOAD" | grep -q '"failed_envs": \[\]'; then
  EVENT_TYPE="phase.deploy_completed"
  OUTCOME="PASS"
else
  EVENT_TYPE="phase.deploy_failed"
  OUTCOME="WARN"
fi

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "$EVENT_TYPE" --actor "orchestrator" --outcome "$OUTCOME" \
  --payload "$RESULT_PAYLOAD" 2>/dev/null || true

# Also emit phase.deploy_completed always (gate requires it)
[ "$EVENT_TYPE" != "phase.deploy_completed" ] && ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "phase.deploy_completed" --actor "orchestrator" --outcome "INFO" \
  --payload "$RESULT_PAYLOAD" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2_persist_summary" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_persist_summary.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy 2_persist_summary 2>/dev/null || true
```
</step>

<step name="complete">
## Final — mark + run-complete

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step deploy complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete 2>&1 | tail -1 || true
```
</step>

</process>

<success_criteria>
- Build complete prereq satisfied (or override-debt logged for `--allow-build-incomplete`)
- Selected envs all exist in vg.config.md `environments.{env}` section
- Prod env requires explicit confirmation (interactive AskUserQuestion OR `--prod-confirm-token` match)
- Each env's deploy.{pre,build,restart,health,seed_command} commands run sequentially
- Health check retries up to 30s (6× 5s) before marking failed
- Failed env doesn't auto-abort siblings (interactive: ask user; non-interactive: continue)
- DEPLOY-STATE.json `deployed.{env}` block populated per env, MERGES with existing keys (preserves preferred_env_for)
- previous_sha captured for rollback hint
- phase.deploy_completed telemetry emitted regardless of outcome (with payload listing ok/failed envs)
- Per-env log file `${PHASE_DIR}/.deploy-log.{env}.txt` exists (truncated then appended per run)
</success_criteria>
