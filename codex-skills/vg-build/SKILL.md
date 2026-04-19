---
name: "vg-build"
description: "Execute phase plans with contract-aware wave-based parallel execution"
metadata:
  short-description: "Execute phase plans with contract-aware wave-based parallel execution"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI, translate tool calls using the table + patterns below.

### Tool mapping table

| Claude tool | Codex equivalent | Notes |
|---|---|---|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) | For multi-select, format as "1. Option / 2. Option" and parse reply |
| Task (agent spawn) | `codex exec --model <model> "<prompt>"` subprocess | Foreground: `codex exec ... > /tmp/out.txt`. Parallel: launch N subprocesses + `wait`. See "Agent spawn" below |
| TaskCreate/TaskUpdate/TodoWrite | N/A — use inline markdown headers + status narration | Codex does not have a persistent task tail UI. Write `## ━━━ Phase X: step ━━━` in stdout instead |
| Monitor | Bash loop with `echo` + `sleep 3` polling | Codex streams stdout directly, no separate monitor channel |
| ScheduleWakeup | N/A — Codex is one-shot; user must re-invoke | Skill must tolerate single-execution model; no sleeping |
| WebFetch | `curl -sfL <url>` or `gh api <path>` | For GitHub URLs prefer `gh` for auth handling |
| mcp__playwright{1-5}__* | See "Playwright MCP" below | Playwright MCP tools ARE available in Codex's main orchestrator |
| mcp__graphify__* | `python -c "from graphify import ..."` inline | Graphify CLI/module works identically in Codex |
| mcp__context7__*, mcp__exa__*, mcp__firecrawl__* | Skip or fall back to WebFetch | Only available via SDK; not bundled in Codex CLI |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively | No adapter needed |

### Agent spawn (Task → codex exec)

Claude Code spawns isolated agents via `Task(subagent_type=..., prompt=...)`. Codex equivalent:

```bash
# Single agent, foreground (wait for completion + read output)
codex exec --model gpt-5 "<full isolated prompt>" > /tmp/agent-result.txt 2>&1
RESULT=$(cat /tmp/agent-result.txt)

# Multiple agents, parallel (Claude's pattern of 1 message with N Task calls)
codex exec --model gpt-5 "<prompt 1>" > /tmp/agent-1.txt 2>&1 &
PID1=$!
codex exec --model gpt-5 "<prompt 2>" > /tmp/agent-2.txt 2>&1 &
PID2=$!
wait $PID1 $PID2
R1=$(cat /tmp/agent-1.txt); R2=$(cat /tmp/agent-2.txt)
```

**Critical constraints when spawning:**
- Subagent inherits working directory + env vars, but **no MCP server access** (Codex exec spawns fresh CLI instance without `--mcp` wired). Subagent CANNOT call `mcp__playwright*__`, `mcp__graphify__`, etc.
- Model mapping for this project: `models.planner` opus → `gpt-5`, `models.executor` sonnet → `gpt-4o`, `models.scanner` haiku → `gpt-4o-mini` (or project-configured equivalent). Check `.claude/vg.config.md` `models` section for actual values and adapt.
- Timeout: wrap in `timeout 600s codex exec ...` to prevent hung subagents.
- Return schema: if skill expects structured JSON back, prompt subagent with "Return ONLY a single JSON object with keys: {...}". Parse with `jq` or `python -c "import json,sys; ..."`.

### Playwright MCP — orchestrator-only rule

Playwright MCP tools (`mcp__playwright1__browser_navigate`, `_snapshot`, `_click`, etc.) ARE available to the main Codex orchestrator (same MCP servers as Claude Code). **BUT subagents spawned via `codex exec` do NOT inherit MCP access** — they are fresh CLI instances.

Implication for skills using Haiku scanner pattern (scanner spawns → uses Playwright):
- **Claude model:** spawn haiku agent with prompt → agent calls `mcp__playwright__` tools directly
- **Codex model:** TWO options:
  1. **Orchestrator-driven:** main orchestrator calls Playwright tools + passes snapshots/results to subagent as text → subagent returns instructions/analysis only (no tool calls). Slower but preserves parallelism benefit.
  2. **Single-agent:** orchestrator runs scanner workflow inline (no spawn). Simpler but no parallelism; suitable for 1-2 view scans but slow for 14+ views.

Default: **single-agent inline** unless skill explicitly documents the orchestrator-driven pattern for that step.

### Persistence probe (Layer 4) — execution model

For review/test skills that verify mutation persistence:
- Main orchestrator holds Playwright session (claimed via lock manager)
- Pre-snapshot + submit + refresh + re-read all run in orchestrator Playwright calls (not spawned)
- If skill delegates analysis to subagent, orchestrator must capture snapshots + pass text to subagent; subagent returns verdict JSON `{persisted: bool, pre: ..., post: ...}`

### Lock manager (Playwright)

Same as Claude:
```bash
SESSION_ID="codex-${skill}-${phase}-$$"
PLAYWRIGHT_SERVER=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
```

Pool name in Codex: `codex` (separate from Claude's `claude` pool). Lock manager handles both without collision.

## Invocation

This skill is invoked by mentioning `$vg-build`. Treat all user text after `$vg-build` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate in this command.**

Why: those tools persist items in Claude Code's status tail across sessions. Wave-based parallel build can spawn 5+ subagents running 10-30 min each — items hang in UI for runs after if interrupted.

**Use these instead:**
1. **Markdown headers in YOUR text output** between tool calls — e.g., `## ━━━ Wave 2 / Task 7.6-04 ━━━`. Appears in message stream, does NOT persist after session ends.
2. **`run_in_background: true` for any Bash > 30s** (typecheck, lint, tests), then poll with `BashOutput` so user sees stdout live.
3. **For Task subagents > 2 min**: write 1-line status BEFORE spawning ("Wave 2 spawning 5 parallel executors for tasks 04-08...") + 1-line summary AFTER ("Wave 2 done: 5/5 commits, typecheck PASS").
4. Bash echo narration is audit log only — not user-visible during long runs.
5. **Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `Wave (đợt)`, `commit (lưu thay đổi)`, `typecheck (kiểm tra kiểu)`, `BLOCK (chặn)`. Không áp dụng: file path, code identifier, config tag values, lần lặp lại trong cùng message.
</NARRATION_POLICY>

<rules>
1. **Blueprint required** — phase must have PLAN*.md AND API-CONTRACTS.md before build. Missing = BLOCK.
2. **Contract injection** — every executor agent receives relevant contract sections as context.
3. **Orchestrator coordinates, not executes** — discover plans, group waves, spawn agents, collect results.
4. **Context budget per agent ~2000 lines** — each executor gets 7 context blocks (task/contract/goals/design/sibling/wave/execution). Modern Claude 200k comfortable; starving context causes drift. See step 8c for per-block line budgets.
5. **Wave execution** — sequential between waves, parallel within.
6. **Flags are opt-in** — only active when literal token appears in $ARGUMENTS.
7. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as its FINAL action, run:
   `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`
   where `{STEP_NAME}` matches the `<step name="...">` attribute. Step 9 verifies all expected markers exist; missing marker = BLOCK. This is deterministic enforcement — AI cannot silently skip a step without leaving forensic evidence.
8. **Bash vs MCP convention**:
   - ` ```bash ` blocks = REAL bash commands. Run via Bash tool. Outputs to shell variables for use in next step.
   - **MCP tool calls** (`mcp__graphify__*`, `mcp__playwright*__*`, etc.) = Claude tool invocations. NEVER call from bash — invoke directly via tool use. Required tool name is in prose; arguments listed as bullet points.
   - Confusing the two = silent fall-back to grep path / lost graphify benefit. When a step has BOTH (compute vars in bash → call MCP tool → parse result), the prose explicitly separates them with "(in bash)" vs "(Claude tool call)" labels.
</rules>

<objective>
Step 3 of V5 pipeline. Execute code based on blueprint (plans + API contracts).

Pipeline: specs → scope → blueprint → **build** → review → test → accept

Key difference from V4 execute: executors read API-CONTRACTS.md to ensure BE routes match contract fields and FE calls match contract endpoints.
</objective>

<available_agent_types>
- gsd-debugger — Diagnoses and fixes issues (generic Claude agent type for debugging — not a GSD workflow dependency)
</available_agent_types>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `.claude/commands/vg/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

<step name="0_gate_integrity_precheck">
**T8 gate (cổng) integrity precheck — blocks build if /vg:update left unresolved gate conflicts (xung đột).**

If `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` exists, a prior `/vg:update` detected that the 3-way merge (gộp) altered one or more HARD gate blocks. Until a human resolves them via `/vg:reapply-patches --verify-gates`, the pipeline cannot trust its own enforcement logic — so we BLOCK (chặn).

```bash
if [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved."
  echo "   File: ${PLANNING_DIR}/vgflow-patches/gate-conflicts.md"
  echo "   Cause: /vg:update 3-way merge altered hard-gate (cổng cứng) blocks."
  echo "   Fix:   /vg:reapply-patches --verify-gates"
  exit 1
fi
```
</step>

<step name="0_session_lifecycle">
**Session lifecycle (tightened 2026-04-17) — clean tail UI across runs.**

Follow `.claude/commands/vg/_shared/session-lifecycle.md`.

```bash
PHASE_ARG=$(echo "$ARGUMENTS" | awk '{print $1}')
# v1.9.2.2 — handle zero-padding via shared resolver
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-resolver.sh" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR_CANDIDATE=$(resolve_phase_dir "$PHASE_ARG" 2>/dev/null || echo "")
else
  PHASE_DIR_CANDIDATE=$(ls -d ${PLANNING_DIR}/phases/${PHASE_ARG}* 2>/dev/null | head -1)
fi

session_start "build" "${PHASE_ARG:-unknown}"
[ -n "$PHASE_DIR_CANDIDATE" ] && stale_state_sweep "build" "$PHASE_DIR_CANDIDATE"
[ "${CONFIG_SESSION_PORT_SWEEP_ON_START:-true}" = "true" ] && session_port_sweep "pre-flight"
session_mark_step "1-parse-args"
```
</step>

<step name="1_parse_args">
Parse `$ARGUMENTS`:
- First positional token → `PHASE_ARG`
- Optional `--wave N` → `WAVE_FILTER`
- Optional `--only 15,16,17` — resume specific tasks only (skip others). Use
  after partial Wave completion (crash, compact, manual kill) to re-run only
  the tasks that didn't commit. Reads `.build-progress.json` to verify.
- Optional `--status` — read-only: print `.build-progress.json` + exit. Safe
  to call after compact to see where we are. No state changes.
- Optional `--gaps-only`, `--interactive`, `--auto`
- Optional `--reset-queue` — wipe `.vg/.build-queue/` + unstage leftover files
  from a crashed prior run, then proceed. Use after SIGKILL / OS crash where
  the commit-queue mutex's EXIT trap didn't fire. Safe on clean state (no-op).

Sync chain flag:
```bash
# VG-native: auto-chain not used in VG pipeline
# (GSD auto-chain is N/A — VG uses explicit /vg:next routing)

# Flag allowlist (v1.14.4+ — typo guard). Unknown flag = hard BLOCK, not silent skip.
VALID_FLAGS_PATTERN='^--(wave|only|status|gaps-only|interactive|auto|reset-queue|skip-design-check|skip-context-rebuild|resume|allow-missing-commits|allow-r5-violation|override-reason|force|help)$'
UNKNOWN_FLAGS=""
for tok in ${ARGUMENTS:-}; do
  case "$tok" in
    --*)
      # Strip =value from --flag=value for allowlist match
      flag_name="${tok%%=*}"
      if ! echo "$flag_name" | grep -qE "$VALID_FLAGS_PATTERN"; then
        UNKNOWN_FLAGS="${UNKNOWN_FLAGS} ${flag_name}"
      fi
      ;;
  esac
done
if [ -n "$UNKNOWN_FLAGS" ]; then
  echo "⛔ Unknown flag(s):${UNKNOWN_FLAGS}"
  echo "   Valid flags: --wave, --only, --status, --gaps-only, --interactive, --auto,"
  echo "                --reset-queue, --skip-design-check, --skip-context-rebuild, --resume,"
  echo "                --allow-missing-commits, --allow-r5-violation, --override-reason=<text>, --force, --help"
  echo "   Có thể bạn gõ sai chính tả (typo). Check lại arguments trước khi chạy."
  exit 1
fi

# Detect flags
RESET_QUEUE=false
STATUS_ONLY=false
ONLY_TASKS=""
[[ "${ARGUMENTS:-}" =~ --reset-queue ]] && RESET_QUEUE=true
[[ "${ARGUMENTS:-}" =~ --status ]] && STATUS_ONLY=true
if [[ "${ARGUMENTS:-}" =~ --only[[:space:]]*=?[[:space:]]*([0-9,]+) ]]; then
  ONLY_TASKS="${BASH_REMATCH[1]}"
fi

# --status is a read-only shortcut — print progress + exit before doing any work
if [ "$STATUS_ONLY" = "true" ]; then
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh" 2>/dev/null
  PHASE_DIR_LOOKUP=$(ls -d ${PLANNING_DIR:-.vg}/phases/${PHASE_ARG}* 2>/dev/null | head -1)
  if [ -z "$PHASE_DIR_LOOKUP" ]; then
    echo "⛔ --status: phase ${PHASE_ARG} not found"
    exit 1
  fi
  vg_build_progress_status "$PHASE_DIR_LOOKUP"
  exit 0
fi
```
</step>

<step name="1a_build_queue_preflight">
## Step 1a — Build queue preflight (crash recovery)

Run BEFORE wave-start tagging to detect leftover state from prior crashed
runs. Catches 4 failure modes:

1. Stale commit-queue lock (mutex EXIT trap didn't fire on SIGKILL/crash)
2. Active commit-queue lock (another /vg:build running on same repo)
3. Staged-but-uncommitted files (would leak into wave-start baseline → every
   subsequent wave commit looks like it's over-claiming those files →
   attribution audit would flag the whole wave)
4. Unresolved merge conflicts (cannot build on conflicted tree)

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-queue-preflight.sh"

if ! vg_build_queue_preflight "$RESET_QUEUE" "$PHASE_ARG"; then
  echo ""
  echo "   Preflight gate blocks until state is clean."
  echo "   Quick fix: /vg:build ${PHASE_ARG} --reset-queue"
  exit 1
fi
```

The preflight helper:
- With `--reset-queue=true`: wipes `.vg/.build-queue/` + `git reset HEAD -- .`
  (working tree untouched — only unstages)
- Auto-breaks stale locks older than `VG_COMMIT_LOCK_STALE_SECONDS` (default 600s)
- Blocks on active lock < threshold, staged files, or merge conflicts
- Prints concrete fix options for each blocker
</step>

<step name="1b_recon_gate">
**Gate: verify phase is not raw legacy (prevents building without proper V6 contracts).**

```bash
RECON_STATE="${PHASE_DIR}/.recon-state.json"
if [ -f "$RECON_STATE" ]; then
  PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
  if [ "$PHASE_TYPE" = "legacy_gsd" ]; then
    echo "⛔ Phase ${PHASE_NUMBER} is legacy_gsd — V6 contracts missing."
    echo "   Run /vg:phase ${PHASE_NUMBER} first to migrate legacy artifacts."
    exit 1
  fi
else
  # No recon state — run quick recon to classify
  ${PYTHON_BIN} .claude/scripts/phase-recon.py \
    --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet
  PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
  if [ "$PHASE_TYPE" = "legacy_gsd" ]; then
    echo "⛔ Phase ${PHASE_NUMBER} is legacy_gsd — run /vg:phase ${PHASE_NUMBER} to migrate first."
    exit 1
  fi
fi
echo "✓ Phase type: ${PHASE_TYPE}"
```
</step>

<step name="create_task_tracker">
**Create sub-step task list for progress tracking — with profile-filter enforcement.**

### Step 0: Profile preflight (deterministic, bash)

```bash
PROFILE=$(${PYTHON_BIN} -c "
import re, sys
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^profile:\s*[\"\']?([^\"\'#\s]+)', line)
    if m: print(m.group(1)); break
")
if [ -z "$PROFILE" ]; then
  echo "⛔ config.profile missing in .claude/vg.config.md. Run /vg:init"
  exit 1
fi

# Compute expected applicable steps for this profile
EXPECTED_STEPS=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/build.md \
  --profile "$PROFILE" \
  --output-ids)
EXPECTED_COUNT=$(echo "$EXPECTED_STEPS" | tr ',' '\n' | wc -l)

echo "Profile: $PROFILE"
echo "Expected steps ($EXPECTED_COUNT): $EXPECTED_STEPS"

# Marker directory for post-execution verify
MARKER_DIR="${PHASE_DIR}/.step-markers"
mkdir -p "$MARKER_DIR"
if [[ ! "$ARGUMENTS" =~ --resume ]]; then
  rm -f "$MARKER_DIR"/*.done 2>/dev/null  # fresh run only
  echo "Fresh build — cleared markers."
else
  EXISTING_MARKERS=$(ls "$MARKER_DIR"/*.done 2>/dev/null | wc -l)
  echo "Resume build — keeping ${EXISTING_MARKERS} existing markers."
fi
```

### Step 1: Create tasks ONLY for applicable steps

Create one task per step in `$EXPECTED_STEPS` (comma-separated). Use the step name as task subject.
Do NOT create tasks for steps excluded by profile filter.

```
For each stepId in EXPECTED_STEPS:
  TaskCreate: subject=stepId, activeForm="Running ${stepId}..."
```

### Step 2: Task count assertion

After task creation, verify count matches:
```bash
ACTUAL_COUNT=$(gsd-tools task-list --count 2>/dev/null || echo "0")
if [ "$ACTUAL_COUNT" != "$EXPECTED_COUNT" ]; then
  echo "⛔ Task tracker mismatch: expected $EXPECTED_COUNT for profile $PROFILE, got $ACTUAL_COUNT"
  echo "   Missing or extra tasks indicate profile filter was ignored."
  exit 1
fi
```

**Rule for subsequent steps:** every `<step>` body MUST, as its FINAL action, write a marker:
```bash
touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"
```
Post-execution check (step 9) compares markers vs EXPECTED_STEPS. Missing marker = step skipped silently = BLOCK.

Each sub-step should: `TaskUpdate: status="in_progress"` at start, `status="completed"` at end, AND write marker at end.
</step>

<step name="2_initialize">
Load context:
```bash
# VG-native phase init (no GSD dependency)
PHASE_DIR=$(ls -d ${PLANNING_DIR}/phases/*${PHASE_ARG}* 2>/dev/null | head -1)
PHASE_NUMBER=$(echo "${PHASE_DIR}" | grep -oP '\d+(\.\d+)*' | head -1)
PHASE_NAME=$(basename "${PHASE_DIR}" | sed "s/^[0-9.]*-//")
PLAN_COUNT=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | wc -l)
INCOMPLETE_COUNT=$PLAN_COUNT
# VG-native: executor rules injected inline via vg-executor-rules.md (no GSD agent-skills needed)
AGENT_SKILLS=""
```

Parse from resolved vars: `phase_dir`, `phase_number`, `phase_name`, `plan_count`, `incomplete_count`. Models come from config-loader (`$MODEL_EXECUTOR`, `$MODEL_PLANNER`, `$MODEL_DEBUGGER`).

Errors: `PHASE_DIR` empty → stop. `PLAN_COUNT=0` → stop.
</step>

<step name="3_validate_blueprint">
**MANDATORY GATE — blueprint artifacts + CONTEXT.md format.**

### 3a: Check core artifacts exist

```bash
PLANS=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | head -1)
CONTRACTS=$(ls "${PHASE_DIR}"/API-CONTRACTS.md 2>/dev/null)
```

Missing PLAN → BLOCK: "Run `/vg:blueprint {phase}` first."
Missing CONTRACTS → WARNING: "No API contracts. Executors will build without contract guidance. Continue? (y/n)"

### 3b: CONTEXT.md format validation (v1.14.4+ — R2 enforcement)

Executor rules require commits cite `D-XX` / `P{phase}.D-XX` decisions. If CONTEXT.md missing or legacy format (no Endpoints / Test Scenarios sub-sections), executor cites stale decisions and commit-msg hook either fails or lets weak citations through.

```bash
# Only enforce for feature profile — other profiles (infra/hotfix/docs) skip CONTEXT per phase-profile rules
PHASE_PROFILE_FOR_CTX="${PHASE_PROFILE:-feature}"
if [ "$PHASE_PROFILE_FOR_CTX" = "feature" ]; then
  CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"

  if [ ! -f "$CONTEXT_FILE" ]; then
    echo "⛔ CONTEXT.md missing cho phase ${PHASE_NUMBER} (feature profile cần CONTEXT.md)."
    echo "   Run: /vg:scope ${PHASE_NUMBER} trước khi build."
    exit 1
  fi

  # Parse CONTEXT structure
  DECISION_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-[0-9]+' "$CONTEXT_FILE" 2>/dev/null || echo 0)
  ENDPOINT_SECTIONS=$(grep -c '^\*\*Endpoints:\*\*' "$CONTEXT_FILE" 2>/dev/null || echo 0)
  TEST_SECTIONS=$(grep -c '^\*\*Test Scenarios:\*\*' "$CONTEXT_FILE" 2>/dev/null || echo 0)

  if [ "$DECISION_COUNT" -eq 0 ]; then
    echo "⛔ CONTEXT.md có 0 decisions — phase chưa scoped đúng."
    echo "   Expected: '### D-01', '### D-02', ... hoặc '### P${PHASE_NUMBER}.D-01' format."
    echo "   Run: /vg:scope ${PHASE_NUMBER}"
    exit 1
  fi

  if [ "$ENDPOINT_SECTIONS" -eq 0 ] && [ "$TEST_SECTIONS" -eq 0 ]; then
    # Legacy format — warn but allow (blueprint step 2a also warns)
    echo "⚠ CONTEXT.md legacy format (không có 'Endpoints:' hoặc 'Test Scenarios:' sub-sections)."
    echo "   Executor sẽ cite decision IDs nhưng thiếu context cụ thể."
    echo "   Khuyến nghị: /vg:scope ${PHASE_NUMBER} để re-enrich."
    # Log to override-debt (technical debt tracking)
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "build-context-legacy" "${PHASE_NUMBER}" "CONTEXT.md legacy format — no Endpoints/Test sections" "$PHASE_DIR"
    fi
  fi

  echo "✓ CONTEXT.md: ${DECISION_COUNT} decisions, ${ENDPOINT_SECTIONS} endpoint blocks, ${TEST_SECTIONS} test blocks"
fi
```

Result routing:
- Feature profile + CONTEXT.md missing → HARD BLOCK
- Feature profile + 0 decisions → HARD BLOCK
- Feature profile + legacy format → WARN + log override-debt
- Non-feature profile → skip check (CONTEXT.md not required)
</step>

<step name="4_load_contracts_and_context">
**Load artifacts + resolve all context-injection variables BEFORE spawning executors.**

**Resume-safe:** This step MUST run even on `--resume` if its artifacts are missing.
The prior build may have used gsd-executor (no graphify) — new build needs step 4 data.

**⛔ HARD RULE (tightened 2026-04-17):** On `--resume`, step 4 MUST re-run UNLESS user explicitly passes `--skip-context-rebuild`. Reason: graphify may have been rebuilt since prior run, config may have changed, and stale sibling/caller context causes cross-module breaks. Reusing is OPT-IN, not default.

```bash
STEP4_NEEDED=true  # default: always run on resume
if [[ "$ARGUMENTS" =~ --skip-context-rebuild ]]; then
  # User explicitly opted out — check artifacts exist
  if [ -d "${PHASE_DIR}/.wave-context" ] \
     && [ -f "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" ]; then
    # Additional staleness check: compare graphify mtime vs marker mtime
    GRAPH_MTIME=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || echo 0)
    MARKER_MTIME=$(stat -c %Y "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" 2>/dev/null || stat -f %m "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" 2>/dev/null || echo 0)
    if [ "$GRAPH_MTIME" -gt "$MARKER_MTIME" ]; then
      echo "⛔ Graphify rebuilt since step 4 last ran (graph=${GRAPH_MTIME} > marker=${MARKER_MTIME}). Forcing step 4 re-run despite --skip-context-rebuild."
      STEP4_NEEDED=true
    else
      STEP4_NEEDED=false
      echo "Step 4: SKIPPED via --skip-context-rebuild (artifacts fresh)."
    fi
  else
    echo "⛔ --skip-context-rebuild requested but artifacts missing — running step 4 anyway."
  fi
fi

if [ "$STEP4_NEEDED" = "true" ]; then
  echo "Step 4: building sibling + caller context (graphify: ${GRAPHIFY_ACTIVE:-false})..."
fi
```

### 4_pre: Graphify + cross-platform vars

Already resolved by `_shared/config-loader.md` helpers at command start. Available:
- `$PYTHON_BIN` — Python 3.10+ interpreter (validated)
- `$REPO_ROOT` — absolute repo root (git toplevel)
- `$GRAPHIFY_GRAPH_PATH` — absolute graph path (resolved from config)
- `$GRAPHIFY_ACTIVE` — "true" if enabled + graph exists
- `$VG_TMP` — cross-platform temp dir

Steps 4c, 4e, 8c read these vars. No duplicate parsing here.

**Graphify auto-rebuild (stale check):**

```bash
if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
  # Source graphify-safe helper (verifies mtime advances post-rebuild, retries once on stuck)
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"

  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')

  if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
    echo "Graphify: ${COMMITS_SINCE} commits since last build — rebuilding for fresh context"
    vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-step4" || {
      echo "⚠ Graphify rebuild did not complete successfully; downstream sibling/caller context may be stale"
    }
  else
    echo "Graphify: up to date (0 commits since last build)"
  fi
fi
```

**Why always rebuild before build:** Graph is consumed by step 4c (siblings) and 4e (callers). Stale graph = wrong sibling suggestions = executor copies wrong patterns. Rebuild is fast (~10s for incremental) and runs once per build — cheap insurance vs debugging wrong sibling context.

### 4a: Contract context

Read `${PHASE_DIR}/API-CONTRACTS.md`. Per plan task, extract only endpoint sections the task touches (grep for endpoint paths task mentions).

### 4b: Design context paths (fixes G4)

```bash
# Resolve DESIGN_OUTPUT_DIR from config (fallback to default)
DESIGN_OUTPUT_DIR="${config.design_assets.output_dir:-${PLANNING_DIR}/design-normalized}"
DESIGN_MANIFEST="${DESIGN_OUTPUT_DIR}/manifest.json"

# If any task has <design-ref>, classify each as SLUG vs DESCRIPTIVE:
#   - SLUG: kebab-case filename-like (e.g., "dsp-partners-list", "deal_wizard_step2")
#     → must resolve in ${DESIGN_OUTPUT_DIR}/refs/${slug}.* + screenshots/${slug}.*
#     → hard gate (missing = BLOCK, executor can't build without asset)
#   - DESCRIPTIVE: contains spaces, uppercase, dots, or phrases like "pattern"/"similar to"
#     (e.g., "Phase 7.13 AdvCampaignWizard pattern")
#     → NOT a slug — this is code-pattern guidance, not a required asset
#     → injected into executor prompt as narrative hint, no asset check
#
# Rationale: Phase 10 PLAN had <design-ref>Phase 7.13 AdvCampaignWizard pattern</design-ref>
# which was descriptive guidance ("reuse the pattern from existing code") — the prior
# hard gate treated it as a slug and BLOCK'd build, false-positive.
if grep -l "<design-ref>" "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  MISSING_DESIGN=""
  DESCRIPTIVE_REFS=""
  SLUG_REFS=""

  # Collect all design-refs, classify each
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    # -oP extracts the inner text; sed strips the tags for clean tokens
    while IFS= read -r ref_text; do
      [ -z "$ref_text" ] && continue
      # Slug heuristic: only [a-z0-9_-], no spaces/uppercase/dots, length <= 80
      # Descriptive heuristic: anything else (spaces, uppercase, dots, phrases)
      if [[ "$ref_text" =~ ^[a-z0-9][a-z0-9_-]{1,79}$ ]]; then
        SLUG_REFS="${SLUG_REFS} ${ref_text}"
      else
        DESCRIPTIVE_REFS="${DESCRIPTIVE_REFS}|${ref_text}"
      fi
    done < <(grep -oP '<design-ref>[^<]+</design-ref>' "$plan" | sed 's/<[^>]*>//g')
  done

  # Report classification
  if [ -n "$DESCRIPTIVE_REFS" ]; then
    echo "ℹ Descriptive design-refs (code-pattern guidance, NOT required assets):"
    IFS='|' read -ra REFS_ARR <<< "${DESCRIPTIVE_REFS#|}"
    for r in "${REFS_ARR[@]}"; do
      [ -n "$r" ] && echo "    \"$r\""
    done
    echo "    → will be injected into executor prompt as narrative hint"
  fi

  # Only enforce manifest + asset check for SLUG-type refs
  if [ -n "$SLUG_REFS" ]; then
    if [ ! -f "$DESIGN_MANIFEST" ]; then
      MISSING_DESIGN="manifest (slugs found: ${SLUG_REFS})"
    else
      MISSING_REFS=""
      for slug in $SLUG_REFS; do
        if ! ls "${DESIGN_OUTPUT_DIR}/refs/${slug}".* >/dev/null 2>&1; then
          MISSING_REFS="${MISSING_REFS} ${slug}"
        fi
        if ! ls "${DESIGN_OUTPUT_DIR}/screenshots/${slug}".* >/dev/null 2>&1; then
          MISSING_REFS="${MISSING_REFS} ${slug}(screenshot)"
        fi
      done
      [ -n "$MISSING_REFS" ] && MISSING_DESIGN="refs:${MISSING_REFS}"
    fi
  fi

  if [ -n "$MISSING_DESIGN" ]; then
    echo "⛔ BLOCK: Tasks reference design but required assets missing: $MISSING_DESIGN"
    echo "   Required dir: $DESIGN_OUTPUT_DIR"
    echo "   Fix: /vg:design-extract  (blueprint should have auto-triggered this)"
    echo "   Override (NOT RECOMMENDED): /vg:build {phase} --skip-design-check"
    if [[ ! "$ARGUMENTS" =~ --skip-design-check ]]; then
      # v1.9.2 P4 — try block_resolve before hard exit
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="build.design-manifest"
        BR_GATE_CONTEXT="Tasks in PLAN reference design slugs, but referenced assets missing in ${DESIGN_OUTPUT_DIR}: ${MISSING_DESIGN}. Executor needs ground-truth UI to produce faithful code."
        BR_EVIDENCE=$(printf '{"missing":"%s","output_dir":"%s"}' "$MISSING_DESIGN" "$DESIGN_OUTPUT_DIR")
        BR_CANDIDATES='[{"id":"auto-extract","cmd":"echo \"Would trigger /vg:design-extract — orchestrator must call SlashCommand tool\" && exit 1","confidence":0.5,"rationale":"design-extract regenerates missing assets from configured sources"}]'
        BR_RESULT=$(block_resolve "build-design-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        case "$BR_LEVEL" in
          L1) echo "✓ L1 auto-extracted — continuing" >&2 ;;
          L2) block_resolve_l2_handoff "build-design-missing" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
          *)  exit 1 ;;
        esac
      else
        exit 1
      fi
    else
      # v1.9.0 T1: rationalization guard before honoring --skip-design-check
      RATGUARD_RESULT=$(rationalization_guard_check "design-check" \
        "Gate requires design assets present when plan tasks reference design-ref. Skipping = build without ground-truth UI." \
        "missing_design=${MISSING_DESIGN} user_arg=--skip-design-check")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "design-check" "--skip-design-check" "$PHASE_NUMBER" "build.design-manifest" "$MISSING_DESIGN"; then
        exit 1
      fi
      echo "⚠ --skip-design-check set — proceeding WITHOUT design context. Design fidelity compromised."
      echo "skip-design-check: $(date -u +%FT%TZ) MISSING=$MISSING_DESIGN" >> "${PHASE_DIR}/build-state.log"
    fi
  fi
fi
```

### 4c: Sibling module detection — hybrid script (graphify + filesystem + git)

**Why script not MCP**: graphify's AST extractor doesn't resolve path aliases (e.g., TS `@/hooks/useAuth` → `src/hooks/useAuth`). Pure MCP query misses alias-imported relationships → wrong community → wrong siblings. The hybrid script (`find-siblings.py`) combines filesystem walk (alias-independent) + git activity + graphify community signal (optional) for accurate peer detection on any stack.

**Run `find-siblings.py` for each task with file-path:**

```bash
mkdir -p "${PHASE_DIR}/.wave-context"

for task in "${WAVE_TASKS[@]}"; do
  # task iteration gives TASK_NUM + TASK_FILE_PATH
  SIBLING_OUT="${PHASE_DIR}/.wave-context/siblings-task-${TASK_NUM}.json"

  GRAPHIFY_FLAG=""
  if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  ${PYTHON_BIN} .claude/scripts/find-siblings.py \
    --file "$TASK_FILE_PATH" \
    --config .claude/vg.config.md \
    --top-n 3 \
    $GRAPHIFY_FLAG \
    --output "$SIBLING_OUT"
done
```

### Output format (`.wave-context/siblings-task-{N}.json`)

Step 8c reads this file when assembling the `<sibling_context>` executor prompt block. Format (~15-20 lines vs ~100 grep dump):

```
// <module_dir> (sibling — entry: <entry_file>)
<kind> <name>                  [L<line>]
// <module_dir> (sibling)
<kind> <name>                  [L<line>]
```

### Fallback behavior

If script exits non-zero OR `siblings` list is empty → orchestrator injects `<sibling_context>NONE — no peer modules at this directory level</sibling_context>` (correct signal for "first module in new architectural area", not an error).

**No MCP**: script is deterministic and alias-independent — works on any project regardless of TS path aliases, Python sys.path tweaks, or custom module resolution.

### 4d: Task section extraction (fixes G6)

For each task in PLAN*.md, pre-extract its section into a temp file so executor gets only that task, not the entire plan:

```bash
TASKS_DIR="${PHASE_DIR}/.wave-tasks"
mkdir -p "$TASKS_DIR"

# Parse PLAN*.md, split by task headings (h2 or h3 — VG-native uses ### under wave headings)
awk '
  /^#{2,3} Task [0-9]+/ { if (out) close(out); n=$3; gsub(":", "", n); out="'$TASKS_DIR'/task-" n ".md"; print > out; next }
  out { print >> out }
' "${PHASE_DIR}"/PLAN*.md
```

Each executor now injects `@${TASKS_DIR}/task-{N}.md` (task-only, ~100-300 lines) instead of `@${PLAN_FILE}` (full file).

### 4e: Caller graph load (semantic regression) — dispatch by graphify

Build or refresh `.callers.json` — maps each task's `<edits-*>` symbols to downstream callers across the repo. Executors read this to update or cite callers when changing shared symbols.

Output schema is identical regardless of source (graphify vs grep) — commit-msg hook reads same fields. Add `source: "graphify" | "grep"` field for traceability.

```bash
if [ "${config.semantic_regression.enabled:-true}" = "true" ]; then
  CALLER_GRAPH="${PHASE_DIR}/.callers.json"

  # Regenerate if missing OR any PLAN*.md newer than graph
  NEEDS_REGEN=false
  [ ! -f "$CALLER_GRAPH" ] && NEEDS_REGEN=true
  if [ -f "$CALLER_GRAPH" ]; then
    for plan in "${PHASE_DIR}"/PLAN*.md; do
      [ "$plan" -nt "$CALLER_GRAPH" ] && NEEDS_REGEN=true && break
    done
  fi

  if [ "$NEEDS_REGEN" = "true" ]; then
    if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
      # Graphify path — query MCP for callers per <edits-*> symbol
      # Tree-sitter AST catches dynamic imports, re-exports, type-only imports that grep misses
      echo "Building caller graph via graphify MCP..."

      # Extract all <edits-*> symbols from PLAN tasks
      EDITS=$(grep -hoE '<edits-(schema|function|endpoint|collection|topic)>[^<]+</edits-' "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
        | sed -E 's/<edits-([^>]+)>([^<]+)<.*/\1\t\2/' | sort -u)

      # For each symbol, query graphify for callers (incoming edges)
      # Build .callers.json with same schema as grep path
      ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
        --phase-dir "${PHASE_DIR}" \
        --config .claude/vg.config.md \
        --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
        --output "$CALLER_GRAPH"
      # Note: build-caller-graph.py auto-detects --graphify-graph flag and prefers MCP query
      # If MCP query fails per-symbol, falls back to grep for that symbol
    else
      # Grep fallback path — original implementation
      echo "Building caller graph via grep (graphify inactive)..."
      ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
        --phase-dir "${PHASE_DIR}" \
        --config .claude/vg.config.md \
        --output "$CALLER_GRAPH"
    fi
  fi

  # Per-task lookup: extract callers this task affects, store for step 8c injection
  # Orchestrator reads $CALLER_GRAPH, builds TASK_{N}_CALLERS env var per task
  # If task has no edits declared → TASK_{N}_CALLERS="NONE — no shared symbols edited"
else
  echo "semantic_regression.enabled=false → skipping caller graph"
fi
```

Final action: `touch "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done"`
</step>

<step name="5_handle_branching">
Check `branching_strategy` from init. If "phase" or "milestone": checkout branch.

Final action: `touch "${PHASE_DIR}/.step-markers/5_handle_branching.done"`
</step>

<step name="6_validate_phase">
Report plan count. Update PIPELINE-STATE.json:
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'building'; s['pipeline_step'] = 'build'
s['phase_number'] = '${PHASE_NUMBER}'; s['phase_name'] = '${PHASE_NAME}'
s['plan_count'] = '${PLAN_COUNT}'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```

Final action: `touch "${PHASE_DIR}/.step-markers/6_validate_phase.done"`
</step>

<step name="7_discover_plans">
```bash
# VG-native plan index (no GSD dependency)
PLAN_INDEX=$(ls -1 "${PHASE_DIR}"/PLAN*.md 2>/dev/null)
```

Filter: skip `has_summary: true`. If `--gaps-only`: skip non-gap_closure. If `--wave N`: skip non-matching.
Report execution plan table.

Final action: `touch "${PHASE_DIR}/.step-markers/7_discover_plans.done"`
</step>

<step name="8_execute_waves">
For each wave:

### 8a: Generate wave-context.md (BEFORE spawning executors)

Orchestrator writes `${PHASE_DIR}/wave-{N}-context.md` listing siblings. Each executor in wave reads this for cross-task field alignment.

```markdown
# Wave {N} Context — Phase {PHASE}

Tasks running in parallel this wave:

## Task <N1> — <task title from PLAN>
  File: <task.file_path>
  Endpoint: <method + path>           (if BE task — from <edits-endpoint> attribute)
  Request fields: <field list>         (from contract section)
  Response fields: <field list>
  Contract ref: API-CONTRACTS.md line <start>-<end>

## Task <N2> — <task title>
  File: <task.file_path>
  Consumes: <upstream endpoint> (Task <N1>)         (if FE task consuming a wave-mate's API)
  MUST use same field names as Task <N1> request
  Contract ref: API-CONTRACTS.md line <start>-<end>

## Task <N3> — <task title>
  File: <task.file_path>
  Shares <storage backend> collection/table with Task <N1>    (if relevant)
  Contract ref: API-CONTRACTS.md line <start>-<end>
```

Generated deterministically from PLAN*.md tasks (parse `<file-path>`, `<edits-endpoint>`, `<contract-ref>`, `<edits-collection>` attributes — no project hardcode).

### 8a.5: Initialize SUMMARY.md (first wave only)

```bash
SUMMARY_FILE="${PHASE_DIR}/SUMMARY.md"
if [ ! -f "$SUMMARY_FILE" ]; then
  cat > "$SUMMARY_FILE" << EOF
# Build Summary — Phase ${PHASE_NUMBER}

**Started:** $(date -Iseconds)
**Plan:** ${PLAN_FILE}
**Model:** ${MODEL_EXECUTOR}

EOF
  echo "SUMMARY.md initialized at ${SUMMARY_FILE}"
fi
```

Executors append their task summary sections to this file (per vg-executor-rules.md "Task summary output").
After all waves, step 9 verifies every task has a section.

### 8b: Tag wave start (for rollback) + init progress file

```bash
git tag "vg-build-${PHASE}-wave-${N}-start" HEAD
WAVE_TAG="vg-build-${PHASE}-wave-${N}-start"

# Init compact-safe progress file — survives context compacts + crashes.
# Orchestrator (or user via --status) can read .vg/phases/{phase}/.build-progress.json
# anytime to see "committed [15,19], in-flight [16], failed [18]".
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/typecheck-light.sh"

# Bootstrap typecheck cache once per build session (cold 3-5 min, but makes
# subsequent per-task + wave-gate checks fast 10-30s). Skipped if .tsbuildinfo
# already exists for the packages this wave touches.
#
# Heuristic: get distinct app names from PLAN file-paths, bootstrap each.
BOOTSTRAP_PKGS=$(grep -hoE '<file-path>apps/[^/]+' "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
  | sed 's|<file-path>apps/||' | sort -u)
for pkg in $BOOTSTRAP_PKGS; do
  if vg_typecheck_should_bootstrap "$pkg"; then
    echo "▸ Bootstrapping typecheck cache for $pkg (1-shot, ~3-5 min)..."
    vg_typecheck_bootstrap "$pkg"
  fi
done

# Apply --only filter if set (resume subset of wave tasks)
WAVE_TASK_LIST="${WAVE_TASKS[@]}"   # from PLAN parser in step 7
if [ -n "${ONLY_TASKS:-}" ]; then
  FILTERED=""
  for t in $WAVE_TASK_LIST; do
    if echo "$ONLY_TASKS" | tr ',' '\n' | grep -qx "$t"; then
      FILTERED="${FILTERED} $t"
    fi
  done
  WAVE_TASK_LIST="${FILTERED# }"
  echo "▸ --only filter — running tasks: $WAVE_TASK_LIST (skipping others)"
fi

vg_build_progress_init "$PHASE_DIR" "$N" "$WAVE_TAG" $WAVE_TASK_LIST

# Export vars so build-commit-queue mutex auto-hooks progress on acquire
export VG_BUILD_PHASE_DIR="$PHASE_DIR"
```

### 8c: Spawn executor per task in wave

**PRE-FLIGHT (MANDATORY before ANY executor spawn):**

Before spawning, the orchestrator MUST verify step 4 artifacts exist. If missing, run step 4 NOW:

```
CHECK these files exist (not empty):
  1. ${PHASE_DIR}/.callers.json     (from step 4e — semantic regression)
  2. ${PHASE_DIR}/.wave-context/    (from step 4c — sibling detection)

IF EITHER missing:
  1. Read .claude/vg.config.md — extract graphify.enabled, semantic_regression.enabled
  2. Run step 4c: find-siblings.py for each task (creates .wave-context/siblings-task-{N}.json)
  3. Run step 4e: build-caller-graph.py (creates .callers.json)
  4. Run step 4d: extract task sections from PLAN*.md

This prevents resume from skipping context injection — executor without sibling/caller
context produces code that may break cross-module dependencies.
```

**FILE CONFLICT DETECTION (MANDATORY before parallel spawn):**

Parse `<file-path>` from each task in the current wave. If 2+ tasks edit the SAME file,
those tasks MUST run sequentially (not parallel) to prevent git staging race conditions.

```bash
# Collect file paths per task in wave (grep within each task's extracted section)
WAVE_FILES=()
for task_num in "${WAVE_TASKS[@]}"; do
  TASK_FILE="${PHASE_DIR}/.wave-tasks/task-${task_num}.md"
  if [ -f "$TASK_FILE" ]; then
    FILE_PATH=$(grep -oP '<file-path>\K[^<]+' "$TASK_FILE" | head -1)
  else
    # Fallback: grep task section directly from PLAN*.md
    FILE_PATH=$(awk "/^#{2,3} Task 0?${task_num}[^0-9]/,/^#{2,3} (Task|Wave)/" "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
      | grep -oP '<file-path>\K[^<]+' | head -1)
  fi
  [ -n "$FILE_PATH" ] && WAVE_FILES+=("${task_num}:${FILE_PATH}")
done

# Detect conflicts — same file in 2+ tasks
CONFLICT_GROUPS=""
SEEN_FILES=$(printf '%s\n' "${WAVE_FILES[@]}" | cut -d: -f2 | sort | uniq -d)
if [ -n "$SEEN_FILES" ]; then
  echo "⚠ File conflict in wave ${N}:"
  for file in $SEEN_FILES; do
    TASKS=$(printf '%s\n' "${WAVE_FILES[@]}" | grep ":${file}$" | cut -d: -f1 | tr '\n' ',')
    echo "  ${file} → Tasks ${TASKS}"
    CONFLICT_GROUPS="${CONFLICT_GROUPS} ${TASKS}"
  done
  echo "  → Conflicting tasks will run SEQUENTIALLY within this wave."
fi

# R5 enforcement (v1.14.4+): write explicit spawn plan for orchestrator
# Bash detect xong rồi, nhưng spawn loop phải đọc plan này — không implicit nữa.
SPAWN_PLAN="${PHASE_DIR}/.wave-spawn-plan.json"

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - <<PY > "$SPAWN_PLAN"
import json, sys
wave_files = """$(printf '%s\n' "${WAVE_FILES[@]}")"""
pairs = [line.split(':', 1) for line in wave_files.strip().split('\n') if ':' in line]
file_to_tasks = {}
for t, f in pairs:
    try:
        file_to_tasks.setdefault(f, []).append(int(t))
    except ValueError:
        pass
seq_groups = [sorted(set(tasks)) for tasks in file_to_tasks.values() if len(tasks) >= 2]
seq_flat = {t for grp in seq_groups for t in grp}
all_tasks = []
for t, _ in pairs:
    try:
        all_tasks.append(int(t))
    except ValueError:
        pass
parallel = sorted(set(all_tasks) - seq_flat)
plan = {
    "wave": "${N:-unknown}",
    "parallel": parallel,
    "sequential_groups": seq_groups,
    "conflict_files": sorted(set(f for f, tasks in file_to_tasks.items() if len(tasks) >= 2)),
}
print(json.dumps(plan, indent=2))
PY

echo "✓ Wave ${N} spawn plan: $SPAWN_PLAN"
${PYTHON_BIN} -c "
import json
p = json.load(open('$SPAWN_PLAN', encoding='utf-8'))
print(f'  Parallel tasks ({len(p[\"parallel\"])}): {p[\"parallel\"]}')
print(f'  Sequential groups ({len(p[\"sequential_groups\"])}): {p[\"sequential_groups\"]}')
if p['conflict_files']:
    print(f'  Conflict files: {p[\"conflict_files\"]}')
"
```

**Why:** When 2+ parallel agents edit the same file, git staging races cause one agent's
changes to be absorbed into another's commit — the second agent loses its own commit silently.
Detection prevents this class of bugs by forcing conflicting tasks to run sequentially.

**⛔ SPAWN PLAN ENFORCEMENT (orchestrator MUST follow):**

Orchestrator đọc `${PHASE_DIR}/.wave-spawn-plan.json` và spawn theo 2 group:
1. **parallel[]** — spawn Agent cho mỗi task trong 1 message (multiple tool calls). Wait all.
2. **sequential_groups[][]** — mỗi group spawn từng task 1, wait mỗi task trước khi spawn next.

```
Example plan:
{
  "parallel": [1, 2, 5],
  "sequential_groups": [[3, 4], [6, 7, 8]]
}
Spawn order:
  Message 1: Agent(task 1) + Agent(task 2) + Agent(task 5)   # parallel batch
  Message 2: Agent(task 3), wait, Agent(task 4)             # group [3,4] serial
  Message 3: Agent(task 6), wait, Agent(task 7), wait, Agent(task 8)   # group [6,7,8] serial
```

**POST-SPAWN verification** chạy trong step 8d — compare `.build-progress.json` timestamps
vs plan. Nếu sequential_groups overlap (parallel execution) → R5 violation, BLOCK wave.

DO NOT SKIP THIS. If scripts are missing or fail, inject:
  <sibling_context>UNAVAILABLE — scripts not found. Review peer modules manually.</sibling_context>
  <downstream_callers>UNAVAILABLE — caller graph not built. Check imports manually.</downstream_callers>
```

**Record task as in-flight BEFORE Agent() spawn (compact-safe):**
```bash
# Progress file → tasks_in_flight[] so --status reflects reality even
# after a context compact. Agent ID isn't known at spawn; fill "pending".
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
vg_build_progress_start_task "$PHASE_DIR" "$TASK_NUM" "pending-agent"
```

**Fill context variables via pre-executor-check.py (deterministic, not pseudocode):**
```bash
# Run ONCE per task — outputs JSON with all context blocks ready
CONTEXT_JSON=$(${PYTHON_BIN} .claude/scripts/pre-executor-check.py \
  --phase-dir "${PHASE_DIR}" \
  --task-num ${TASK_NUM} \
  --config .claude/vg.config.md)

# Parse output into variables
TASK_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['task_context'])")
CONTRACT_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['contract_context'])")
GOALS_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['goals_context'])")
TASK_SIBLINGS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['sibling_context'])")
TASK_CALLERS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['downstream_callers'])")
DESIGN_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['design_context'])")
BUILD_CONFIG=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.dumps(json.load(sys.stdin)['build_config']))")

# Script auto-builds siblings + callers if missing (runs find-siblings.py + build-caller-graph.py)
# Graphify used: ${graphify.enabled} from config → sibling/caller enrichment

# R4 enforcement (v1.14.4+) — context budget check per block + total prompt size
# Rule 4 khai "Context budget per agent ~2000 lines, 7 blocks". Gate đây để tránh drift/OOM.
PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - <<PY
import json, sys

ctx = json.loads('''$CONTEXT_JSON''')

# Per-block soft limits (from rule R4)
BUDGETS = {
    'task_context': 300,
    'contract_context': 500,
    'goals_context': 200,
    'sibling_context': 400,
    'downstream_callers': 400,
    'design_context': 200,
}
HARD_TOTAL_MAX = ${CONFIG_BUILD_PROMPT_MAX_LINES:-2500}

per_block_lines = {}
total = 0
overflows = []

for key, budget in BUDGETS.items():
    val = ctx.get(key, '') or ''
    n = val.count('\n') + (1 if val and not val.endswith('\n') else 0)
    per_block_lines[key] = n
    total += n
    if n > budget:
        overflows.append(f"  - {key}: {n} lines > budget {budget}")

# Soft warn per-block overflow (R4 said ~2000 lines comfortable)
if overflows:
    print(f"⚠ R4 per-block overflow ({len(overflows)} block):")
    for o in overflows:
        print(o)
    print(f"  Total prompt: {total} lines")

# Hard total cap — protects against runaway
if total > HARD_TOTAL_MAX:
    print(f"⛔ R4 HARD gate: prompt total {total} lines > max {HARD_TOTAL_MAX}.")
    print(f"   Per-block: {per_block_lines}")
    print(f"   Reduce contract sections (chỉ endpoint task touches) hoặc tăng config.build.prompt_max_lines")
    sys.exit(1)
else:
    print(f"✓ R4 budget: {total} lines (hard max {HARD_TOTAL_MAX}), per-block ok")
PY
R4_RC=$?
if [ "$R4_RC" != "0" ]; then
  echo "R4-overflow task=${TASK_NUM} phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  echo "⛔ Executor spawn blocked — fix context budget or raise config.build.prompt_max_lines, then re-run."
  exit 1
fi
```

**Spawn executor agent (one per plan task):**
```
Agent(subagent_type="general-purpose", model="${MODEL_EXECUTOR}"):
  prompt: |
    <vg_executor_rules>
    @.claude/commands/vg/_shared/vg-executor-rules.md
    </vg_executor_rules>

    <build_config>
    typecheck_cmd: ${config.build_gates.typecheck_cmd}
    build_cmd: ${config.build_gates.build_cmd}
    generated_types_path: ${config.contract_format.generated_types_path}
    phase: ${PHASE_NUMBER}
    plan: ${PLAN_NUM}
    </build_config>

    <task_context>
    @${TASKS_DIR}/task-${TASK_NUM}.md  (~100-300 lines)
    </task_context>

    <contract_context>
    Relevant contract code blocks to COPY VERBATIM (not retype):
    @${PHASE_DIR}/API-CONTRACTS.md (section for this task's endpoint(s), ~400 lines)
    Import types from: ${config.contract_format.generated_types_path}
    </contract_context>

    <ui_spec_context>
    # Only if UI-SPEC.md exists (FE tasks) — layout/spacing/component tokens
    @${PHASE_DIR}/UI-SPEC.md  (relevant sections, ~200 lines)
    </ui_spec_context>

    <goals_context>
    Task implements: ${TASK_GOALS}  (from task's <goals-covered>)
    Success criteria + mutation evidence:
    @${PHASE_DIR}/TEST-GOALS.md (goals listed above only, ~200 lines)
    </goals_context>

    <design_context>
    # ONLY if task has <design-ref> attribute. Paths resolved from step 4b.
    Visual reference (AI VISION — nhìn pixel trực tiếp):
    @${DESIGN_OUTPUT_DIR}/screenshots/${DESIGN_SLUG}.default.png
    @${DESIGN_OUTPUT_DIR}/screenshots/${DESIGN_SLUG}.${STATE}.png  (per state relevant)
    Structural DOM: @${DESIGN_OUTPUT_DIR}/refs/${DESIGN_SLUG}.structural.html
    Interactions: @${DESIGN_OUTPUT_DIR}/refs/${DESIGN_SLUG}.interactions.md
    Rule: layout/components/spacing MUST match screenshot. DOM is structural truth.
    </design_context>

    <sibling_context>
    # Resolved by step 4c — top-2 peer modules (signatures only, not full code)
    # Source: ${SIBLING_SOURCE} (graphify | grep | ast)
    # Graphify path: focused subgraph from MCP query (~15-20 lines)
    # Grep fallback: signature dump from peer files (~100 lines)
    ${TASK_SIBLINGS}
    # If empty: "NONE — no peer modules for this task type yet"
    </sibling_context>

    <downstream_callers>
    # Resolved by step 4e from .callers.json
    # Source: ${CALLER_SOURCE} (graphify | grep) — see .callers.json metadata
    # This task edits shared symbols. Downstream files calling these symbols:
    ${TASK_CALLERS}
    # If empty: "NONE — no shared symbols edited by this task"

    Rule: If you change a listed symbol's signature/shape/return type:
      (a) Update the callers in THIS commit (add to staged files), OR
      (b) Add to commit body: "Caller <path>: <reason no breaking change>"
    The commit-msg hook verifies compliance. Missing update + no cite → commit rejected.
    </downstream_callers>

    <wave_context>
    Other tasks running in THIS WAVE — field names + endpoints MUST align:
    @${PHASE_DIR}/wave-${N}-context.md (~300 lines)
    </wave_context>

    <!-- execution_context: VG-native (self-contained in vg-executor-rules.md above) -->
    <!-- NO reference to CLAUDE.md VG rules, execute-plan.md, or summary.md template -->
    <!-- All rules injected via <vg_executor_rules> block at top of this prompt -->

    <files_to_read>
    - {phase_dir}/{plan_file}
    - ${PLANNING_DIR}/PROJECT.md
    - ${PLANNING_DIR}/STATE.md
    </files_to_read>

    Rules (summary — full rules in CLAUDE.md "VG Executor Rules"):
    - Copy contract code blocks VERBATIM (no retype)
    - Cite contract line / goal ID in commit message
    - Run ${config.build_gates.typecheck_cmd} before EVERY commit
    - NO --no-verify on apps/**/src/**, packages/**/src/**
    - Align field names with sibling tasks in wave-{N}-context
    - If <design-ref> present: match screenshot exactly, no "improvements"

    ${AGENT_SKILLS}
```

**Context budget per agent:** ~2200 lines max
- Plan task (extracted section only): ~300 lines
- Contract code blocks: ~400 lines
- UI-SPEC section (FE tasks only): ~200 lines
- Goals context: ~200 lines
- Design context (if present): ~300 lines (includes image tokens)
- Sibling module signatures: ~200 lines
- Wave context: ~300 lines
- Execution context (CLAUDE.md + GSD generic): ~300 lines

Modern Claude 200k context comfortable — 2000 lines ≈ 30k tokens ≈ 15% budget.
Starving context causes drift; expand to eliminate guess.

### 8d: Wave completion + strict verify gate

**⛔ MANDATORY — orchestrator MUST run ALL steps below after EVERY wave. Skipping = build on broken code.**

**Step 0-pre — R5 spawn plan honor check (MANDATORY, run FIRST v1.14.4+):**

Verify orchestrator honored `.wave-spawn-plan.json` — sequential_groups must have ran one-at-a-time (no timestamp overlap). If violated → commit race likely → BLOCK before commit count check masks the issue.

```bash
SPAWN_PLAN_FILE="${PHASE_DIR}/.wave-spawn-plan.json"
PROGRESS_FILE="${PHASE_DIR}/.build-progress.json"

if [ -f "$SPAWN_PLAN_FILE" ] && [ -f "$PROGRESS_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$SPAWN_PLAN_FILE" "$PROGRESS_FILE" <<'PY'
import json, sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
progress = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))

# Build task_num → (started_at, finished_at) map
tasks_info = {}
for t in progress.get('tasks', []):
    try:
        tid = int(t.get('task_num', 0))
    except (TypeError, ValueError):
        continue
    tasks_info[tid] = {
        'started_at': t.get('started_at') or '',
        'finished_at': t.get('finished_at') or '',
    }

seq_groups = plan.get('sequential_groups') or []
if not seq_groups:
    print("✓ R5 check: no sequential groups in this wave (all parallel)")
    sys.exit(0)

violations = []
for group in seq_groups:
    # Sort by started_at
    with_ts = [(t, tasks_info.get(t, {})) for t in group]
    with_ts = [(t, info) for t, info in with_ts if info.get('started_at')]
    if len(with_ts) < 2:
        continue  # not enough data to detect overlap
    with_ts.sort(key=lambda x: x[1]['started_at'])
    for i in range(len(with_ts) - 1):
        t_curr, info_curr = with_ts[i]
        t_next, info_next = with_ts[i+1]
        curr_end = info_curr.get('finished_at') or ''
        next_start = info_next.get('started_at') or ''
        if curr_end and next_start and next_start < curr_end:
            violations.append(
                f"Tasks {t_curr} + {t_next} overlapped: "
                f"task-{t_curr} finished={curr_end}, task-{t_next} started={next_start}"
            )

if violations:
    print(f"⛔ R5 VIOLATION: {len(violations)} sequential group(s) ran in PARALLEL despite spawn plan:")
    for v in violations:
        print(f"   - {v}")
    print("")
    print("Nguyên nhân: orchestrator không đọc .wave-spawn-plan.json trước khi spawn.")
    print("Hậu quả tiềm năng: commit race trên shared file — agent đè commit nhau silent.")
    print("")
    print("Hành động:")
    print("  1. Kiểm tra git log — có commit nào chứa changes của task khác không (wrong attribution)?")
    print("  2. Nếu có: revert wave, re-run với attention vào spawn plan")
    print("     git reset --hard ${WAVE_TAG}")
    print("     /vg:build ${PHASE_NUMBER} --wave ${N}")
    print("  3. Nếu không (may mắn không race): document override-debt + proceed")
    sys.exit(1)
else:
    print(f"✓ R5 check: all {len(seq_groups)} sequential group(s) ran one-at-a-time")
PY

  R5_RC=$?
  if [ "$R5_RC" != "0" ]; then
    echo "R5-violation wave=${N} phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    # Log to override-debt if --allow-r5-violation explicitly set, else hard block
    if [[ "$ARGUMENTS" =~ --allow-r5-violation ]]; then
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "build-r5-violation" "${PHASE_NUMBER}" "sequential group ran in parallel, commit race possible" "$PHASE_DIR"
      fi
      echo "⚠ --allow-r5-violation set — proceeding despite R5 breach, logged to debt register."
    else
      exit 1
    fi
  fi
fi
```

**Step 0 — Agent commit verification (MANDATORY, run FIRST):**

After all wave agents complete, count commits since wave tag. Each task MUST produce exactly 1 commit.

```bash
WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"
EXPECTED_COMMITS=${#WAVE_TASKS[@]}
ACTUAL_COMMITS=$(git log --oneline "${WAVE_TAG}..HEAD" | wc -l | tr -d ' ')

# Sync progress file with actual git log (compact-safe). For each commit in
# wave range, parse task number from subject and record in tasks_committed.
# Missing tasks (in expected but not in git log) get marked as failed.
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
while IFS= read -r line; do
  sha="${line%% *}"
  subject="${line#* }"
  if [[ "$subject" =~ ^[a-z]+\([0-9]+(\.[0-9]+)*-([0-9]+)\): ]]; then
    tnum="${BASH_REMATCH[2]}"
    vg_build_progress_commit_task "$PHASE_DIR" "$tnum" "$sha"
  fi
done < <(git log --format='%H %s' "${WAVE_TAG}..HEAD" 2>/dev/null)
# Mark expected-but-missing tasks as failed
for task_num in "${WAVE_TASKS[@]}"; do
  if ! git log --oneline "${WAVE_TAG}..HEAD" | grep -q "${PHASE_NUMBER}-$(printf '%02d' $task_num)"; then
    vg_build_progress_fail_task "$PHASE_DIR" "$task_num" "no-commit-found"
  fi
done

if [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]; then
  echo "⛔ COMMIT MISMATCH: wave ${N} expected ${EXPECTED_COMMITS} commits, got ${ACTUAL_COMMITS}"
  echo "  Missing tasks:"
  MISSING_TASKS=""
  for task_num in "${WAVE_TASKS[@]}"; do
    if ! git log --oneline "${WAVE_TAG}..HEAD" | grep -q "${PHASE_NUMBER}-$(printf '%02d' $task_num)"; then
      echo "  - Task ${task_num}: NO COMMIT FOUND"
      MISSING_TASKS="${MISSING_TASKS} ${task_num}"
    fi
  done
  echo ""

  # ⛔ HARD BLOCK (tightened 2026-04-17): silent agent failure = silent bad wave.
  # Previously asked user; now requires explicit --allow-missing-commits to proceed.
  if [[ "$ARGUMENTS" =~ --allow-missing-commits ]]; then
    # v1.9.0 T1: spawn isolated Haiku subagent to adjudicate skip justification
    # See _shared/rationalization-guard.md — dispatch Task tool with zero parent context.
    # Orchestrator MUST: (1) read gate spec "wave-commits: silent agent failures caught via commit count",
    # (2) read skip_reason from ARGUMENTS/--reason=, (3) dispatch Task(model=haiku) with prompt from
    # rationalization_guard_check template, (4) parse JSON verdict, (5) call rationalization_guard_dispatch.
    # If ESCALATE → block and exit 1. If PASS/FLAG → proceed (FLAG exports VG_RATGUARD_FORCE_CRITICAL=1).
    RATGUARD_RESULT=$(rationalization_guard_check "wave-commits" \
      "Gate blocks wave if commits < tasks. Silent agent failures cause broken waves if bypassed without concrete reason." \
      "missing_tasks=[${MISSING_TASKS}] user_arg=--allow-missing-commits")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "wave-commits" "--allow-missing-commits" "$PHASE_NUMBER" "build.wave-${N}" "${MISSING_TASKS}"; then
      exit 1
    fi
    echo "⚠ --allow-missing-commits set — recording missing tasks and proceeding."
    echo "wave-${N}: MISSING_COMMITS tasks=[${MISSING_TASKS}] allowed-by=--allow-missing-commits ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  else
    # v1.9.1 R2+R4: block-resolver — L1 tries re-dispatch for missing tasks automatically before demanding --allow-missing-commits.
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="build.wave-${N}"
      BR_CTX="Wave ${N} expected ${EXPECTED_COMMITS} commits, got ${ACTUAL_COMMITS}. Silent agent failure possible — re-dispatch missing tasks before treating as fatal."
      BR_EV=$(printf '{"expected":%d,"actual":%d,"missing_tasks":"%s","wave":%d}' "$EXPECTED_COMMITS" "$ACTUAL_COMMITS" "${MISSING_TASKS}" "$N")
      BR_CANDS='[{"id":"redispatch-missing","cmd":"echo L1-SAFE: orchestrator would re-dispatch missing tasks via Task tool; skipping in shell resolver safe mode","confidence":0.55,"rationale":"missing commits usually = transient agent failure, safe to retry once"}]'
      BR_RES=$(block_resolve "wave-commits" "$BR_CTX" "$BR_EV" "$PHASE_DIR" "$BR_CANDS")
      BR_LVL=$(echo "$BR_RES" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LVL" = "L1" ]; then
        echo "✓ Block resolver L1 re-dispatched missing tasks — re-count commits"
        ACTUAL_COMMITS=$(git log --oneline "${WAVE_TAG}..HEAD" | wc -l | tr -d ' ')
        [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ] && { echo "⛔ Still short after L1 retry ($ACTUAL_COMMITS / $EXPECTED_COMMITS)"; exit 1; }
      elif [ "$BR_LVL" = "L2" ]; then
        block_resolve_l2_handoff "wave-commits" "$BR_RES" "$PHASE_DIR"
        exit 2
      else
        block_resolve_l4_stuck "wave-commits" "L1 re-dispatch failed, L2 architect returned no proposal"
        exit 1
      fi
    else
      echo "  Fix: re-run missing tasks manually, then /vg:build ${PHASE_NUMBER} --resume"
      echo "  Or (NOT RECOMMENDED): /vg:build ${PHASE_NUMBER} --allow-missing-commits"
      echo "  Reason: agents may have failed silently (missing target file, dep missing, etc.)."
      exit 1
    fi
  fi
fi
```

**Why:** Agents can fail silently — target file doesn't exist, dependency missing, or agent
hits an error but doesn't commit. Without this count check, orchestrator proceeds to next wave
on broken state. Commit count verification catches all silent agent failures deterministically.

**Step 0b — Commit attribution audit (MANDATORY, run after count check):**

Commit count gate passes if N tasks → N commits. But parallel executors can race
on `.git/index`: agent A's `git add fileA.ts` lands before agent B's `git commit`,
so agent B absorbs fileA.ts silently. Count = N, but attribution is corrupted.

Run the attribution verifier to catch this class of race:

```bash
# Source override-debt helper once — every override site below calls log_override_debt
# so the debt register stays in sync with build-state.log (was previously OUT of sync —
# build-state.log had overrides, OVERRIDE-DEBT.md never saw them).
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || \
  echo "⚠ override-debt.sh missing — overrides will log to build-state.log only"

ATTR_SCRIPT=".claude/scripts/verify-commit-attribution.py"
if [ -f "$ATTR_SCRIPT" ]; then
  # Default strict mode — flags files not matching any task's <file-path>
  # (orchestration allowlist exempts SUMMARY.md, PIPELINE-STATE.json, step-markers)
  if ! ${PYTHON_BIN:-python} "$ATTR_SCRIPT" \
       --phase-dir "${PHASE_DIR}" \
       --wave-tag "${WAVE_TAG}" \
       --wave-number "${N}" \
       --strict; then
    echo ""
    echo "⛔ Commit attribution violations detected in wave ${N}."
    echo "   Root cause: executor agent(s) bypassed build-commit-queue mutex."
    echo "   See: .claude/commands/vg/_shared/vg-executor-rules.md § Parallel-wave commit safety"
    echo ""
    echo "   Fix paths:"
    echo "     (a) git reset --hard ${WAVE_TAG}  # roll back corrupted wave"
    echo "     (b) /vg:build ${PHASE_NUMBER} --wave ${N}  # re-run wave (agents will use mutex)"
    echo "     (c) --override-reason=<issue-id>  # accept + log for acceptance review"
    echo ""

    OVERRIDE_REASON=""
    if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
      OVERRIDE_REASON="${BASH_REMATCH[1]}"
    fi
    if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
      echo "⚠ Attribution gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
      echo "attribution-violations: wave-${N} override=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--override-reason" "$PHASE_NUMBER" "build.attribution.wave-${N}" "$OVERRIDE_REASON" "build-attribution-wave-${N}"
    else
      exit 1
    fi
  fi
else
  echo "⚠ verify-commit-attribution.py missing — skipping attribution audit (older install)"
fi
```

The attribution verifier:
1. Parses each wave commit's `type(phase-task):` to infer which task produced it
2. Reads `.wave-tasks/task-{N}.md` for that task's `<file-path>` expectation
3. Classifies each changed file: `own-main`, `own-test`, `own-dir`, `orchestration`, `other-task:M`, or `unrelated`
4. Fails (exit 2) if any file is `other-task:M` (cross-attribution) or `unrelated` in strict mode

This is the safety net. The PRIMARY fix is that executors hold the commit-queue
mutex, preventing the race at the source. See vg-executor-rules.md.

**Step 0c — Wave integrity reconciliation (MANDATORY, survives crashes):**

Runs `verify-wave-integrity.py` against the progress file + git log + filesystem.
Catches crash scenarios where agent work exists on disk but progress file never
recorded it (SIGKILL during work, context compact mid-wave, power failure).

Phase 10 Wave 5 reality check: apps/web tsc OOM killed 3 agents; their ~1500
LOC was still on disk but orphaned. Integrity verifier rescued the work. Without
this running automatically, user had to know to invoke it manually. Now auto.

```bash
INTEGRITY_SCRIPT=".claude/scripts/verify-wave-integrity.py"
if [ -f "$INTEGRITY_SCRIPT" ]; then
  echo ""
  echo "━━━ Step 0c: Wave ${N} integrity reconciliation ━━━"
  ${PYTHON_BIN:-python3} "$INTEGRITY_SCRIPT" \
    --phase-dir "${PHASE_DIR}" --wave "${N}" --repo-root "${REPO_ROOT:-.}"
  INTEG_EXIT=$?

  case "$INTEG_EXIT" in
    0) echo "✓ Integrity verdict: clean" ;;
    *)
      echo "⛔ Integrity verdict: corruption detected (exit ${INTEG_EXIT})."
      echo "   Next wave BLOCKED until reconciled. Options:"
      echo "     (a) Follow the script's Recovery suggestions above"
      echo "     (b) /vg:build ${PHASE_NUMBER} --wave ${N} --reset-queue  # re-run wave"
      echo "     (c) --override-reason=<issue-id>  # accept current state with debt"
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
        echo "⚠ Integrity gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
        echo "integrity-corruption: wave-${N} override=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
        type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
          "--override-reason" "$PHASE_NUMBER" "build.integrity.wave-${N}" "$OVERRIDE_REASON" "build-integrity-wave-${N}"
      else
        exit 1
      fi
      ;;
  esac
else
  echo "⚠ verify-wave-integrity.py missing — skipping integrity check (older install)"
fi
```

**Step 1 — Commit format + SUMMARY verification:**
Verify commits match pattern `^(feat|fix|refactor|test|chore)\([\d.]+-\d+\): `.
Verify SUMMARY.md sections exist for each task in wave.

**Step 2 — Post-wave strict verify gate (run in order, BLOCK on first failure):**

```bash
WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"
FAILED_GATE=""

# Gate 1: Typecheck (mandatory) — adaptive strategy
# v1.14.3: auto-select full vs narrow based on project size + OOM history.
# Rationale: apps with ≥1200 weighted files (TSX counts 3x) or prior OOM
# events get narrow check (only files changed since wave tag). Small/medium
# apps get full incremental. Config override: VG_TYPECHECK_STRATEGY env.
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/typecheck-light.sh" 2>/dev/null || true

if type -t vg_typecheck_adaptive >/dev/null 2>&1; then
  echo "Gate 1/4: Adaptive typecheck (per-package auto-selection)..."
  # Derive package list from wave's changed files
  WAVE_PKGS=$(git diff --name-only "${WAVE_TAG}" HEAD -- 'apps/*/src/**' 'packages/*/src/**' 2>/dev/null \
    | sed -E 's|^(apps\|packages)/([^/]+)/.*|\2|' | sort -u)
  GATE1_FAIL=0
  for pkg in $WAVE_PKGS; do
    vg_typecheck_adaptive "$pkg" "${WAVE_TAG}" || GATE1_FAIL=$((GATE1_FAIL + 1))
  done
  [ "$GATE1_FAIL" -gt 0 ] && FAILED_GATE="typecheck"
elif [ -n "${config.build_gates.typecheck_cmd}" ]; then
  # Fallback when lib unavailable (older install)
  echo "Gate 1/4: Running ${config.build_gates.typecheck_cmd} (non-adaptive)..."
  if ! eval "${config.build_gates.typecheck_cmd}"; then
    FAILED_GATE="typecheck"
  fi
fi

# Gate 2: Build (mandatory)
if [ -z "$FAILED_GATE" ] && [ -n "${config.build_gates.build_cmd}" ]; then
  echo "Gate 2/4: Running ${config.build_gates.build_cmd}..."
  if ! eval "${config.build_gates.build_cmd}"; then
    FAILED_GATE="build"
  fi
fi

# Gate 3: Unit tests — affected subset only (mandatory if test_unit_required=true)
if [ -z "$FAILED_GATE" ]; then
  UNIT_CMD="${config.build_gates.test_unit_cmd}"
  UNIT_REQ="${config.build_gates.test_unit_required:-true}"

  # Check test infrastructure presence
  if [ -z "$UNIT_CMD" ]; then
    # Auto-detect from package.json
    if [ -f package.json ] && jq -e '.scripts["test:unit"] // .scripts.test' package.json >/dev/null 2>&1; then
      UNIT_CMD=$(jq -r '.scripts["test:unit"] // .scripts.test' package.json)
      echo "⚠ test_unit_cmd empty — auto-detected: '$UNIT_CMD'. Persist to vg.config.md to silence."
    elif [ "$UNIT_REQ" = "true" ]; then
      # Required but not configured and not detectable → BLOCK unless --allow-no-tests
      if [[ ! "$ARGUMENTS" =~ --allow-no-tests ]]; then
        # First-time bootstrap leniency: log and allow (once)
        if ! grep -q "test-infrastructure-missing" "${PHASE_DIR}/build-state.log" 2>/dev/null; then
          echo "⚠ No test_unit_cmd + no detectable test script. Allowing first time; add tests before next phase."
          echo "test-infrastructure-missing: wave ${N}, first-time-allow" >> "${PHASE_DIR}/build-state.log"
        else
          echo "⛔ test_unit_cmd required but missing (test_unit_required=true)."
          echo "   Fix: add test_unit_cmd to .claude/vg.config.md"
          echo "   Or: run with --allow-no-tests (logged to build-state.log)"
          # v1.9.2 P4 — block-resolver handoff before declaring gate fail
          source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
          if type -t block_resolve >/dev/null 2>&1; then
            export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="build.gate3-test-unit"
            BR_GATE_CONTEXT="test_unit_required=true but test_unit_cmd empty and no auto-detect match in package.json scripts. Phase has src/ changes that need test coverage."
            BR_EVIDENCE=$(printf '{"wave":"%d","unit_cmd":"%s"}' "$N" "${UNIT_CMD}")
            BR_CANDIDATES='[{"id":"autodetect-vitest","cmd":"[ -f vitest.config.ts ] && echo \"vitest config detected — suggest: pnpm vitest run\" && exit 1","confidence":0.6,"rationale":"vitest.config.ts present — likely safe default"}]'
            BR_RESULT=$(block_resolve "build-test-unit-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
            BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
            [ "$BR_LEVEL" = "L1" ] && echo "✓ L1 resolved — test_unit_cmd suggestion applied" >&2
            [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "build-test-unit-missing" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
          fi
          FAILED_GATE="test_unit_missing"
        fi
      else
        echo "test-infrastructure-missing: wave ${N}, --allow-no-tests override" >> "${PHASE_DIR}/build-state.log"
      fi
    fi
  fi

  if [ -z "$FAILED_GATE" ] && [ -n "$UNIT_CMD" ]; then
    # Affected tests only — grep test files importing changed modules
    CHANGED=$(git diff --name-only "${WAVE_TAG}" HEAD -- 'apps/**/src/**' 'packages/**/src/**' 2>/dev/null || true)
    AFFECTED_TESTS=""
    if [ -n "$CHANGED" ]; then
      for f in $CHANGED; do
        MOD=$(dirname "$f")
        # Find tests importing this module (approximate)
        MATCHES=$(grep -rl "from.*${MOD}\|require.*${MOD}" \
          --include='*.test.ts' --include='*.test.tsx' \
          --include='*.spec.ts' --include='*.spec.tsx' \
          apps/ packages/ 2>/dev/null || true)
        AFFECTED_TESTS="$AFFECTED_TESTS $MATCHES"
      done
      AFFECTED_TESTS=$(echo "$AFFECTED_TESTS" | tr ' ' '\n' | sort -u | grep -v '^$' || true)
    fi

    if [ -n "$AFFECTED_TESTS" ]; then
      echo "Gate 3/4: Running affected tests ($(echo "$AFFECTED_TESTS" | wc -l) files)..."
      if ! eval "$UNIT_CMD $AFFECTED_TESTS"; then
        FAILED_GATE="test_unit"
      fi
    else
      echo "Gate 3/4: No affected tests — skipping (full suite runs at step 9)."
    fi
  fi
fi

# Gate 4: Contract verify (grep built code vs API-CONTRACTS.md)
if [ -z "$FAILED_GATE" ] && [ -n "${config.build_gates.contract_verify_grep}" ]; then
  echo "Gate 4/5: Running contract verify grep..."
  if ! eval "${config.build_gates.contract_verify_grep}"; then
    FAILED_GATE="contract_verify"
  fi
fi

# Gate 5: Goal-test binding (every task claiming <goals-covered> must commit
# a test file referencing the goal id or a success-criteria keyword).
# Mode from config.build_gates.goal_test_binding: strict | warn | off
if [ -z "$FAILED_GATE" ]; then
  GTB_MODE="${config.build_gates.goal_test_binding:-warn}"
  if [ "$GTB_MODE" != "off" ]; then
    echo "Gate 5/5: Goal-test binding (mode=${GTB_MODE})..."
    GTB_LOG="${PHASE_DIR}/build-state.log"
    GTB_ARGS="--phase-dir ${PHASE_DIR} --wave-tag ${WAVE_TAG} --wave-number ${N}"
    [ "$GTB_MODE" = "warn" ] && GTB_ARGS="${GTB_ARGS} --lenient"
    if ! ${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS} \
         | tee -a "$GTB_LOG"; then
      # Script exits 1 only in strict mode (lenient returns 0 with warnings)
      FAILED_GATE="goal_test_binding"
    fi
  else
    echo "Gate 5/10: skipped (goal_test_binding=off)"
  fi
fi

# Gate U: Utility duplication (wave-scope AST scan)
# Post-wave check — did this wave introduce a helper that now has ≥3 copies repo-wide?
# Root cause of tsc OOM + graphify noise (e.g., formatCurrency declared in 16 files).
if [ -z "$FAILED_GATE" ] && [ -f ".claude/scripts/verify-utility-duplication.py" ]; then
  DUP_PROJECT_MD="${PLANNING_DIR}/PROJECT.md"
  if [ -f "$DUP_PROJECT_MD" ]; then
    echo "Gate U: Utility duplication check (wave ${N})..."
    ${PYTHON_BIN} .claude/scripts/verify-utility-duplication.py \
      --since-tag "${WAVE_TAG}" \
      --project "$DUP_PROJECT_MD" \
      --repo-root "${REPO_ROOT:-.}" \
      --threshold-block 3 --threshold-warn 2
    DUP_EXIT=$?
    case "$DUP_EXIT" in
      0) ;;
      2) echo "⚠ Utility duplication WARNs logged — non-blocking, review in accept phase" ;;
      1) FAILED_GATE="utility_duplication" ;;
    esac
  else
    echo "⚠ Gate U skipped — PROJECT.md missing (no utility contract defined)"
  fi
fi

# ============================================================
# Gates 6-10 — MOBILE PROFILES ONLY
# Fires when profile ∈ {mobile-rn, mobile-flutter, mobile-native-ios,
# mobile-native-android, mobile-hybrid}. Uses config.mobile.gates section.
# For web profiles these gates are silently skipped.
# ============================================================

# Detect whether this run is a mobile profile (the workflow already has
# $PROFILE from config-loader; re-read here for safety).
IS_MOBILE=false
case "$PROFILE" in
  mobile-*) IS_MOBILE=true ;;
esac

if [ -z "$FAILED_GATE" ] && [ "$IS_MOBILE" = "true" ]; then

  # ---- Gate 6: Permission audit ----
  PA_ENABLED=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    permission_audit:/{p=1;next}
                    p && /^    [a-z]/{p=0}
                    p && /enabled:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
  if [ "$PA_ENABLED" = "true" ]; then
    echo "Gate 6/10: Mobile permission audit..."
    PA_ARGS="--phase-dir ${PHASE_DIR}"
    # Read optional paths — empty string => skip that platform
    for key in ios_plist_path android_manifest_path expo_config_path; do
      VAL=$(awk "/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                 g && /^    permission_audit:/{p=1;next}
                 p && /^    [a-z]/{p=0}
                 p && /${key}:/{print \$2;exit}" .claude/vg.config.md | tr -d '"' | head -1)
      case "$key" in
        ios_plist_path)        [ -n "$VAL" ] && PA_ARGS="$PA_ARGS --ios-plist $VAL" ;;
        android_manifest_path) [ -n "$VAL" ] && PA_ARGS="$PA_ARGS --android-manifest $VAL" ;;
        expo_config_path)      [ -n "$VAL" ] && PA_ARGS="$PA_ARGS --expo-config $VAL" ;;
      esac
    done
    if ! ${PYTHON_BIN} .claude/scripts/verify-mobile-permissions.py ${PA_ARGS}; then
      FAILED_GATE="mobile_permissions"
      echo "mobile-gate-6: permission_audit status=failed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    else
      echo "mobile-gate-6: permission_audit status=passed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    fi
  else
    echo "Gate 6/10: skipped (permission_audit.enabled != true)"
    echo "mobile-gate-6: permission_audit status=skipped reason=disabled ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  fi
fi

if [ -z "$FAILED_GATE" ] && [ "$IS_MOBILE" = "true" ]; then
  # ---- Gate 7: Cert expiry ----
  CE_ENABLED=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    cert_expiry:/{p=1;next}
                    p && /^    [a-z]/{p=0}
                    p && /enabled:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
  if [ "$CE_ENABLED" = "true" ]; then
    echo "Gate 7/10: Signing cert expiry..."
    WARN_DAYS=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                     g && /^    cert_expiry:/{p=1;next}
                     p && /^    [a-z]/{p=0}
                     p && /warn_days:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    BLOCK_DAYS=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                      g && /^    cert_expiry:/{p=1;next}
                      p && /^    [a-z]/{p=0}
                      p && /block_days:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    # Signing paths come from env var NAMES user declared in signing block —
    # the actual cert path + password live in runtime env (not config file).
    CE_ARGS="--warn-days ${WARN_DAYS:-30} --block-days ${BLOCK_DAYS:-0}"
    IOS_TEAM_VAR=$(awk '/^mobile:/{m=1;next} m && /^    signing:/{s=1;next}
                        s && /^    [a-z]/{s=0} s && /ios_team_id_env:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    # iOS p12 path typically in env var like APPLE_P12_PATH (user-defined)
    [ -n "${APPLE_P12_PATH:-}" ]   && CE_ARGS="$CE_ARGS --ios-p12 ${APPLE_P12_PATH}"
    [ -n "${APPLE_P12_PASSWORD:-}" ] && CE_ARGS="$CE_ARGS --ios-p12-password ${APPLE_P12_PASSWORD}"
    # Android keystore path from config-declared env var
    AND_KS_VAR=$(awk '/^mobile:/{m=1;next} m && /^    signing:/{s=1;next}
                       s && /^    [a-z]/{s=0} s && /android_keystore_env:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    if [ -n "$AND_KS_VAR" ]; then
      AND_KS=$(printenv "$AND_KS_VAR" 2>/dev/null)
      [ -n "$AND_KS" ] && CE_ARGS="$CE_ARGS --android-keystore $AND_KS"
    fi
    if ! ${PYTHON_BIN} .claude/scripts/verify-cert-expiry.py ${CE_ARGS}; then
      FAILED_GATE="cert_expiry"
      echo "mobile-gate-7: cert_expiry status=failed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    else
      echo "mobile-gate-7: cert_expiry status=passed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    fi
  else
    echo "Gate 7/10: skipped (cert_expiry.enabled != true)"
    echo "mobile-gate-7: cert_expiry status=skipped reason=disabled ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  fi
fi

if [ -z "$FAILED_GATE" ] && [ "$IS_MOBILE" = "true" ]; then
  # ---- Gate 8: Privacy manifest ----
  PM_ENABLED=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    privacy_manifest:/{p=1;next}
                    p && /^    [a-z]/{p=0}
                    p && /enabled:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
  if [ "$PM_ENABLED" = "true" ]; then
    echo "Gate 8/10: Privacy manifest consistency..."
    PM_ARGS=""
    for key_pair in "ios_plist_path:--ios-plist" \
                    "ios_privacy_info_path:--ios-privacy-info" \
                    "android_manifest_path:--android-manifest" \
                    "android_data_safety_yaml:--android-data-safety"; do
      KEY="${key_pair%%:*}"; FLAG="${key_pair##*:}"
      # ios_plist_path + android_manifest_path live under permission_audit in the
      # template to avoid duplication; read from whichever location has them.
      VAL=$(awk "/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                 g && /${KEY}:/{gsub(/[\"']/,\"\",\$2);print \$2;exit}" .claude/vg.config.md | head -1)
      [ -n "$VAL" ] && PM_ARGS="$PM_ARGS $FLAG $VAL"
    done
    if [ -n "$PM_ARGS" ]; then
      if ! ${PYTHON_BIN} .claude/scripts/verify-privacy-manifest.py ${PM_ARGS}; then
        FAILED_GATE="privacy_manifest"
        echo "mobile-gate-8: privacy_manifest status=failed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      else
        echo "mobile-gate-8: privacy_manifest status=passed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      fi
    else
      echo "  no privacy paths configured — skipped"
      echo "mobile-gate-8: privacy_manifest status=skipped reason=no-paths ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    fi
  else
    echo "Gate 8/10: skipped (privacy_manifest.enabled != true)"
    echo "mobile-gate-8: privacy_manifest status=skipped reason=disabled ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  fi
fi

if [ -z "$FAILED_GATE" ] && [ "$IS_MOBILE" = "true" ]; then
  # ---- Gate 9: Native module linking ----
  NM_ENABLED=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    native_module_linking:/{p=1;next}
                    p && /^    [a-z]/{p=0}
                    p && /enabled:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
  if [ "$NM_ENABLED" = "true" ]; then
    echo "Gate 9/10: Native module linking..."
    NM_ARGS="--profile ${PROFILE}"
    # Per-backend cmd strings (optional — missing = skip that backend)
    for key_pair in "ios_pods_check:--ios-cmd" \
                    "android_gradle_check:--android-cmd" \
                    "rn_autolinking_check:--rn-cmd" \
                    "flutter_pub_check:--flutter-cmd"; do
      KEY="${key_pair%%:*}"; FLAG="${key_pair##*:}"
      VAL=$(awk "/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                 g && /^    native_module_linking:/{p=1;next}
                 p && /^    [a-z]/{p=0}
                 p && /${KEY}:/{sub(/^[^:]+:[[:space:]]*/,\"\");gsub(/^\"|\"$/,\"\");print;exit}" \
                 .claude/vg.config.md | head -1)
      [ -n "$VAL" ] && NM_ARGS="$NM_ARGS $FLAG \"$VAL\""
    done
    # Read skip_on_missing_tool
    SKIP_TOOL=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                     g && /^    native_module_linking:/{p=1;next}
                     p && /^    [a-z]/{p=0}
                     p && /skip_on_missing_tool:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    [ "$SKIP_TOOL" = "false" ] && NM_ARGS="$NM_ARGS --no-skip-on-missing-tool"
    if ! eval ${PYTHON_BIN} .claude/scripts/verify-native-modules.py ${NM_ARGS}; then
      FAILED_GATE="native_module_linking"
      echo "mobile-gate-9: native_module_linking status=failed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    else
      echo "mobile-gate-9: native_module_linking status=passed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    fi
  else
    echo "Gate 9/10: skipped (native_module_linking.enabled != true)"
    echo "mobile-gate-9: native_module_linking status=skipped reason=disabled ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  fi
fi

if [ -z "$FAILED_GATE" ] && [ "$IS_MOBILE" = "true" ]; then
  # ---- Gate 10: Bundle size ----
  BS_ENABLED=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    bundle_size:/{p=1;next}
                    p && /^    [a-z]/{p=0}
                    p && /enabled:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
  if [ "$BS_ENABLED" = "true" ]; then
    echo "Gate 10/10: Bundle size budget..."
    IPA_MB=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                  g && /^    bundle_size:/{p=1;next}
                  p && /^    [a-z]/{p=0}
                  p && /ios_ipa_mb:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    APK_MB=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                  g && /^    bundle_size:/{p=1;next}
                  p && /^    [a-z]/{p=0}
                  p && /android_apk_mb:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    AAB_MB=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                  g && /^    bundle_size:/{p=1;next}
                  p && /^    [a-z]/{p=0}
                  p && /android_aab_mb:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    FAIL_ACTION=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                       g && /^    bundle_size:/{p=1;next}
                       p && /^    [a-z]/{p=0}
                       p && /fail_action:/{print $2;exit}' .claude/vg.config.md | tr -d '"' | head -1)
    BS_ARGS="--search-root ${REPO_ROOT} --ios-ipa-mb ${IPA_MB:-100} --android-apk-mb ${APK_MB:-50} --android-aab-mb ${AAB_MB:-80} --fail-action ${FAIL_ACTION:-block}"
    if ! ${PYTHON_BIN} .claude/scripts/verify-bundle-size.py ${BS_ARGS}; then
      FAILED_GATE="bundle_size"
      echo "mobile-gate-10: bundle_size status=failed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    else
      echo "mobile-gate-10: bundle_size status=passed ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    fi
  else
    echo "Gate 10/10: skipped (bundle_size.enabled != true)"
    echo "mobile-gate-10: bundle_size status=skipped reason=disabled ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  fi
fi
```

**Step 3 — Failure handling (max 2 debugger retries, then rollback):**

If `$FAILED_GATE` set:

```
RETRY_COUNT=0
MAX_RETRIES=2

while [ "$FAILED_GATE" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  echo "Wave ${N} failed gate: ${FAILED_GATE}. Spawning debugger (retry ${RETRY_COUNT}/${MAX_RETRIES})..."

  # gsd-debugger is a generic Claude agent type for debugging — not a GSD workflow dependency
  Agent(subagent_type="gsd-debugger", model="${MODEL_DEBUGGER}"):
    prompt: |
      Wave ${N} of phase ${PHASE_NUMBER} failed post-wave gate.

      Failed gate: ${FAILED_GATE}
      Wave tag (rollback point): ${WAVE_TAG}
      Plans executed in wave: ${WAVE_PLAN_LIST}

      Diagnose root cause and apply minimal fix. Commit with prefix `fix(${PHASE_NUMBER}-wave-${N}): `.

      Constraints:
      - Do NOT rewrite existing wave commits
      - Do NOT use --no-verify
      - Cite root cause in commit body: "Root cause: <1 sentence>"
      - Re-run failed gate after fix — your fix must make it pass

      ${AGENT_SKILLS}

  # Re-run failed gate only
  case "$FAILED_GATE" in
    typecheck) CMD="${config.build_gates.typecheck_cmd}" ;;
    build) CMD="${config.build_gates.build_cmd}" ;;
    test_unit) CMD="${config.build_gates.test_unit_cmd}" ;;
    contract_verify) CMD="${config.build_gates.contract_verify_grep}" ;;
    goal_test_binding)
      CMD="${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py --phase-dir ${PHASE_DIR} --wave-tag ${WAVE_TAG} --wave-number ${N}"
      ;;
    mobile_permissions)
      CMD="${PYTHON_BIN} .claude/scripts/verify-mobile-permissions.py --phase-dir ${PHASE_DIR} ${PA_ARGS}"
      ;;
    cert_expiry)
      CMD="${PYTHON_BIN} .claude/scripts/verify-cert-expiry.py ${CE_ARGS}"
      ;;
    privacy_manifest)
      CMD="${PYTHON_BIN} .claude/scripts/verify-privacy-manifest.py ${PM_ARGS}"
      ;;
    native_module_linking)
      CMD="${PYTHON_BIN} .claude/scripts/verify-native-modules.py --profile ${PROFILE} ${NM_ARGS}"
      ;;
    bundle_size)
      CMD="${PYTHON_BIN} .claude/scripts/verify-bundle-size.py ${BS_ARGS}"
      ;;
  esac

  if eval "$CMD"; then
    FAILED_GATE=""
    echo "Gate ${FAILED_GATE} recovered after retry ${RETRY_COUNT}."
  fi
done

if [ -n "$FAILED_GATE" ]; then
  echo "⛔ BLOCK: Wave ${N} failed gate ${FAILED_GATE} after ${MAX_RETRIES} retries."
  echo ""

  # ⛔ HARD GATE (tightened 2026-04-17): --override REMOVED as a free escape hatch.
  # Override now requires explicit citation (issue/PR link) in ARGUMENTS via --override-reason=
  # and logs to build-state.log with timestamp for acceptance audit.
  OVERRIDE_REASON=""
  if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
    OVERRIDE_REASON="${BASH_REMATCH[1]}"
  fi

  if [ -n "$OVERRIDE_REASON" ]; then
    # Validate reason is non-empty link/issue ID (minimum: 4 chars alphanumeric + punctuation)
    if [ ${#OVERRIDE_REASON} -lt 4 ]; then
      echo "⛔ --override-reason too short (min 4 chars). Must cite issue ID or URL."
      exit 1
    fi
    # v1.9.0 T1: rationalization guard adjudicates whether reason is concrete enough
    RATGUARD_RESULT=$(rationalization_guard_check "build-hard-gate" \
      "Gate ${FAILED_GATE} (typecheck/build/test/commit-citation) failed after ${MAX_RETRIES} retries. Override bypasses a hard block." \
      "failed_gate=${FAILED_GATE} reason=${OVERRIDE_REASON}")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "build-hard-gate" "--override-reason" "$PHASE_NUMBER" "build.hard-gate.wave-${N}" "$OVERRIDE_REASON"; then
      exit 1
    fi
    echo "⚠ OVERRIDE accepted for gate ${FAILED_GATE}"
    type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
      "--override-reason" "$PHASE_NUMBER" "build.hard-gate.wave-${N}" "$OVERRIDE_REASON" "build-${FAILED_GATE}-wave-${N}"
    echo "   Reason: $OVERRIDE_REASON"
    echo "   Recorded to build-state.log — acceptance gate MUST review."
    echo "override: wave=${N} gate=${FAILED_GATE} reason=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    FAILED_GATE=""  # clear so wave proceeds
  else
    echo "  Fix paths:"
    echo "    (a) git reset --hard ${WAVE_TAG}  # Roll back wave, re-plan"
    echo "    (b) Fix manually, then /vg:build ${PHASE_NUMBER} --wave ${N}"
    echo "    (c) /vg:build ${PHASE_NUMBER} --override-reason=<issue-id-or-url>  # Log override, proceed"
    echo ""
    echo "  Gate ${FAILED_GATE} is a hard block. No silent override."
    exit 1
  fi
fi
```

**Step 4 — Record wave result:**
```bash
# Append wave status to blueprint-state or build-state
echo "wave-${N}: ${FAILED_GATE:-passed} (retries: ${RETRY_COUNT})" >> "${PHASE_DIR}/build-state.log"
```

Only proceed to next wave if `$FAILED_GATE` empty.
</step>

<step name="9_post_execution">
Aggregate results:
- Count completed plans, failed plans
- Check all SUMMARY*.md files exist
- Check build-state.log — all waves passed gate? (no wave should have lingering failure)

**Step filter marker check (deterministic enforcement):**

```bash
# Re-compute expected steps — same as create_task_tracker
PROFILE=$(${PYTHON_BIN} -c "import re; [print(m.group(1)) or exit() for m in [re.match(r'^profile:\s*[\"\']?([^\"\'#\s]+)', l) for l in open('.claude/vg.config.md', encoding='utf-8')] if m]")
EXPECTED_STEPS=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/build.md \
  --profile "$PROFILE" \
  --output-ids | tr ',' ' ')

MISSED_STEPS=""
for step in $EXPECTED_STEPS; do
  if [ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]; then
    MISSED_STEPS="$MISSED_STEPS $step"
  fi
done

# 9_post_execution itself hasn't written its marker yet; allow self-exclusion
MISSED_STEPS=$(echo "$MISSED_STEPS" | tr ' ' '\n' | grep -v '^9_post_execution$' | tr '\n' ' ')

if [ -n "$(echo "$MISSED_STEPS" | xargs)" ]; then
  echo "⛔ Steps did not write markers:$MISSED_STEPS"
  echo "   Profile: $PROFILE expected these. AI skipped silently — BLOCK."
  echo "   Check ${PHASE_DIR}/.step-markers/ to see what ran."
  exit 1
fi
```

**Final gate (all waves combined) — BLOCK on fail:**

```bash
echo "Final gate: full-repo typecheck..."
if ! eval "${config.build_gates.typecheck_cmd}"; then
  echo "⛔ Final typecheck failed"
  exit 1
fi

echo "Final gate: full-repo build..."
if ! eval "${config.build_gates.build_cmd}"; then
  echo "⛔ Final build failed"
  exit 1
fi

# Full unit test suite (catches cross-wave regression)
# ⛔ HARD GATE (tightened 2026-04-17): --allow-no-tests replaced with --override-reason= requirement.
# Cannot silently skip final unit suite — must cite reason and log to build-state.
UNIT_CMD="${config.build_gates.test_unit_cmd}"
UNIT_REQ="${config.build_gates.test_unit_required:-true}"
if [ -n "$UNIT_CMD" ]; then
  echo "Final gate: full unit suite..."
  if ! eval "$UNIT_CMD"; then
    if [ "$UNIT_REQ" = "true" ]; then
      OVERRIDE_REASON=""
      if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
        echo "⚠ Final unit suite failed — override accepted (reason: $OVERRIDE_REASON)"
        echo "override: gate=final_unit_suite reason=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
        type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
          "--override-reason" "$PHASE_NUMBER" "build.final-unit-suite" "$OVERRIDE_REASON" "build-final-unit-suite"
      else
        echo "⛔ Final unit suite failed (test_unit_required=true)"
        echo "   To override: /vg:build ${PHASE_NUMBER} --override-reason=<issue-id-or-url>"
        exit 1
      fi
    else
      echo "⚠ Final unit suite failed — test_unit_required=false in config"
    fi
  fi
fi

# Regression gate — compare full test results against accepted-phase baselines
# Config: regression_guard section in vg.config.md
REGRESSION_ENABLED=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*regression_guard_enabled:\s*(\w+)', line)
    if m: print(m.group(1).lower()); break
else: print('true')
" 2>/dev/null)

if [ "$REGRESSION_ENABLED" = "true" ] && [ -d "${PLANNING_DIR}/phases" ]; then
  echo "Regression gate: collecting baselines from accepted phases..."
  ${PYTHON_BIN} .claude/scripts/regression-collect.py \
    --phases-dir "${PHASES_DIR}" --repo-root "${REPO_ROOT}" \
    --output "${VG_TMP}/regression-baselines.json" 2>&1

  BASELINE_COUNT=$(${PYTHON_BIN} -c "
import json
b = json.load(open('${VG_TMP}/regression-baselines.json', encoding='utf-8'))
print(b.get('total_goals', 0))
" 2>/dev/null)

  if [ "${BASELINE_COUNT:-0}" -gt 0 ]; then
    echo "Regression gate: comparing full suite results vs ${BASELINE_COUNT} goal baselines..."

    # Vitest results from final gate above (reuse if JSON output available)
    VITEST_JSON="${VG_TMP}/vitest-results.json"
    if [ ! -f "$VITEST_JSON" ] && [ -n "$UNIT_CMD" ]; then
      eval "$UNIT_CMD -- --reporter=json --outputFile=${VITEST_JSON}" 2>/dev/null || true
    fi

    ${PYTHON_BIN} .claude/scripts/regression-compare.py \
      --baselines "${VG_TMP}/regression-baselines.json" \
      --vitest-results "${VITEST_JSON}" \
      --output-dir "${VG_TMP}" \
      --json-only 2>&1
    REGRESSION_EXIT=$?

    if [ "$REGRESSION_EXIT" -eq 3 ]; then
      REG_COUNT=$(${PYTHON_BIN} -c "
import json
r = json.load(open('${VG_TMP}/regression-results.json', encoding='utf-8'))
print(r['summary']['REGRESSION'])
" 2>/dev/null)
      echo ""
      echo "⛔ Regression gate: ${REG_COUNT} goal(s) regressed (was PASS, now FAIL)."
      echo ""
      # Show top 5 regressions
      ${PYTHON_BIN} -c "
import json
r = json.load(open('${VG_TMP}/regression-results.json', encoding='utf-8'))
for c in r.get('classified', []):
    if c['current_status'] == 'REGRESSION':
        errs = c['current_errors'][0][:60] if c['current_errors'] else 'unknown'
        print(f\"  Phase {c['phase']} {c['goal_id']}: {c['title'][:40]} — {errs}\")
" 2>/dev/null | head -5
      echo ""
      echo "  Full report: /vg:regression --fix"
      echo ""

      FAIL_ACTION=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*regression_guard_fail_action:\s*(\w+)', line)
    if m: print(m.group(1).lower()); break
else: print('block')
" 2>/dev/null)

      case "$FAIL_ACTION" in
        block)
          echo "  regression_guard_fail_action=block → BLOCKING build."
          echo "  Fix: /vg:regression --fix  (auto-fix loop)"
          # ⛔ HARD BLOCK (tightened 2026-04-17): no silent skip option. Must --override-reason=.
          OVERRIDE_REASON=""
          if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
            OVERRIDE_REASON="${BASH_REMATCH[1]}"
          fi
          if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
            echo "⚠ Regression gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
            type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
              "--override-reason" "$PHASE_NUMBER" "build.regression.wave-${N}" "$OVERRIDE_REASON" "build-regression-wave-${N}"
            echo "regression-guard: wave-final OVERRIDE count=${REG_COUNT} reason=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
            # Mark phase as needing accept-gate review
            echo "${REG_COUNT}" > "${PHASE_DIR}/.regressions-overridden.count"
          else
            echo "  To override: /vg:build ${PHASE_NUMBER} --override-reason=<issue-id-or-url>"
            echo "  Or run: /vg:regression --fix"
            exit 1
          fi
          ;;
        warn)
          # ⛔ TIGHTENED: warn mode still logs to build-state for accept-gate audit.
          # Accept gate must read build-state.log and surface warn-mode regressions to user.
          echo "  regression_guard_fail_action=warn → proceeding with warning (logged for accept review)."
          echo "regression-guard: wave-final WARN count=${REG_COUNT} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
          echo "${REG_COUNT}" > "${PHASE_DIR}/.regressions-warned.count"
          ;;
      esac
    else
      echo "✓ Regression gate: 0 regressions. All baselines stable."
    fi
  else
    echo "Regression gate: no accepted phase baselines — skipping."
  fi
fi
```

**Spec Sync (auto-update specs from built code):**
After build completes, check if code changed API routes or pages that affect existing specs:
```bash
# Surface scan: new/changed endpoints vs API-CONTRACTS.md
CHANGED_ROUTES=$(git diff --name-only HEAD~${COMPLETED_COUNT} HEAD -- "$API_ROUTES" 2>/dev/null)
CHANGED_PAGES=$(git diff --name-only HEAD~${COMPLETED_COUNT} HEAD -- "$WEB_PAGES" 2>/dev/null)

if [ -n "$CHANGED_ROUTES" ] || [ -n "$CHANGED_PAGES" ]; then
  echo "Code changed after build — API-CONTRACTS.md may need sync."
  echo "Changed routes: $CHANGED_ROUTES"
  echo "Changed pages: $CHANGED_PAGES"
  echo "Run /vg:review to re-verify contracts + discover runtime drift."
fi
```

**VG-native State Update (MANDATORY):**
```bash
# 1. Verify all plans have SUMMARY — HARD BLOCK (tightened 2026-04-17)
# Missing SUMMARY = agent silently skipped documentation → orphan commits → review misses scope.
MISSING_SUMMARIES=""
for plan in ${PHASE_DIR}/*-PLAN*.md; do
  PLAN_NUM=$(basename "$plan" | grep -oE '^[0-9]+')
  SUMMARY="${PHASE_DIR}/${PLAN_NUM}-SUMMARY*.md"
  if ! ls $SUMMARY 1>/dev/null 2>&1; then
    echo "⛔ Plan ${PLAN_NUM} has no SUMMARY"
    MISSING_SUMMARIES="${MISSING_SUMMARIES} ${PLAN_NUM}"
  fi
done
if [ -n "$MISSING_SUMMARIES" ]; then
  OVERRIDE_REASON=""
  if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
    OVERRIDE_REASON="${BASH_REMATCH[1]}"
  fi
  if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
    echo "⚠ Missing SUMMARIES overridden (reason: $OVERRIDE_REASON) — plans:${MISSING_SUMMARIES}"
    echo "missing-summaries:${MISSING_SUMMARIES} override=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
      "--override-reason" "$PHASE_NUMBER" "build.missing-summaries" "$OVERRIDE_REASON" "build-missing-summaries"
  else
    echo "⛔ Missing SUMMARY for plans:${MISSING_SUMMARIES}"
    echo "   Each PLAN needs matching SUMMARY — executor must document what was built."
    echo "   Fix: regenerate missing SUMMARY manually or re-run wave with --resume"
    echo "   Override: --override-reason=<issue-id-or-url>"
    exit 1
  fi
fi

# 2. Update PIPELINE-STATE.json — mark phase execution complete (no GSD dependency)
#    IMPORTANT: must also append a structured ``steps.build`` entry so
#    vg-progress.py state-driven path recognises build as done. Prior
#    versions only wrote top-level fields (status/plans_*), which caused
#    /vg:progress to keep showing build=⬜ even though SUMMARY.md existed.
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from datetime import datetime; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'executed'; s['pipeline_step'] = 'build-complete'
s['plans_completed'] = '${COMPLETED_COUNT}'; s['plans_total'] = '${PLAN_COUNT}'
now = datetime.now().isoformat()
s['updated_at'] = now
s.setdefault('steps', {})['build'] = {
    'status': 'done',
    'finished_at': now,
    'plans_completed': '${COMPLETED_COUNT}',
    'plans_total': '${PLAN_COUNT}',
    'summary': 'SUMMARY.md (atomic build artifact)',
}
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# 3. Update ROADMAP.md — mark phase as "in progress" (not complete until accept)
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* executed/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```

Display:
```
Build complete for Phase {N}.
  Plans executed: {completed}/{total}
  Contract compliance: executors had contract context
  State: STATE.md + ROADMAP.md updated
  Next: /vg:review {phase}
```

Commit summaries:
```bash
git add ${PHASE_DIR}/SUMMARY*.md ${PLANNING_DIR}/STATE.md ${PLANNING_DIR}/ROADMAP.md
git commit -m "build({phase}): {completed}/{total} plans executed"
```
</step>

<step name="10_postmortem_sanity">
**Final sanity gate — catches recovery-mode bypass + silent gate failures.**

Historical: Phase 10 audit (2026-04-19) found build completed with 0 telemetry
events + 0 graphify rebuild events + `(recovered)` commits — gates were bypassed
via manual recovery path. This step ensures future bypasses are visible.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/build-postmortem.sh"

# Full post-mortem: telemetry + wave tags + recovery commits + step markers
vg_build_postmortem_check "${PHASE_NUMBER}" "${PHASE_DIR}" ".vg/telemetry.jsonl"
POSTMORTEM_RC=$?

# Phase-level goal coverage audit (complements per-task binding check)
echo ""
echo "━━━ Phase goal coverage audit ━━━"
${PYTHON_BIN} .claude/scripts/verify-goal-coverage-phase.py \
  --phase-dir "${PHASE_DIR}" \
  --repo-root "${REPO_ROOT}" \
  --advisory  # warn-only at build end; /vg:review enforces
GOAL_COVERAGE_RC=$?

# Signal to user but don't block (review is the enforcement point)
if [ "$POSTMORTEM_RC" -ne 0 ] || [ "$GOAL_COVERAGE_RC" -ne 0 ]; then
  echo ""
  echo "⚠ Post-mortem flagged issues — review will enforce. Run: /vg:review ${PHASE_NUMBER}"
fi

# UI structure drift check (chỉ chạy nếu UI-MAP.md tồn tại)
if [ -f "${PHASE_DIR}/UI-MAP.md" ]; then
  echo ""
  echo "━━━ UI structure drift (lệch cấu trúc UI) ━━━"

  UI_MAP_SRC=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /src:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
  UI_MAP_ENTRY=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /entry:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')

  if [ -n "$UI_MAP_SRC" ] && [ -n "$UI_MAP_ENTRY" ]; then
    # Sinh cây thực tế từ code vừa build
    node .claude/scripts/generate-ui-map.mjs \
      --src "$UI_MAP_SRC" \
      --entry "$UI_MAP_ENTRY" \
      --format json \
      --output "${PHASE_DIR}/.ui-map-actual.json" 2>&1 | tail -3

    # So sánh với UI-MAP.md (kế hoạch đích)
    MAX_MISSING=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /max_missing:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "0")
    MAX_UNEXPECTED=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /max_unexpected:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "3")

    ${PYTHON_BIN} .claude/scripts/verify-ui-structure.py \
      --expected "${PHASE_DIR}/UI-MAP.md" \
      --actual "${PHASE_DIR}/.ui-map-actual.json" \
      --max-missing "$MAX_MISSING" \
      --max-unexpected "$MAX_UNEXPECTED" \
      --layout-advisory
    UI_DRIFT_RC=$?

    if [ "$UI_DRIFT_RC" -eq 2 ]; then
      echo ""
      echo "⚠ UI structure drift vượt ngưỡng — /vg:review sẽ BLOCK nếu không khắc phục"
    fi
  else
    echo "⚠ ui_map.src/entry chưa cấu hình — bỏ qua UI drift check"
  fi
fi

touch "${PHASE_DIR}/.step-markers/10_postmortem_sanity.done"
```
</step>

</process>

<context_efficiency>
Orchestrator: ~10-15% context.
Subagents: fresh context each, ~2000 lines (~30k tokens ≈ 15% of 200k budget). Modern Claude comfortable at this scale. Starving context causes drift; expand to eliminate guess.
Re-run `/vg:build {phase}` to resume — discovers plans, skips completed SUMMARYs.
</context_efficiency>
