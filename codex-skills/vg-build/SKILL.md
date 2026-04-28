---
name: "vg-build"
description: "Execute phase plans with contract-aware wave-based parallel execution"
metadata:
  short-description: "Execute phase plans with contract-aware wave-based parallel execution"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
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

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

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

Invoke this skill as `$vg-build`. Treat all user text after the skill name as arguments.
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
2. **Contract injection + runtime verification** — every executor agent receives relevant contract sections as context. At run-complete, orchestrator dispatches `verify-contract-runtime` validator: for each `## METHOD /path` endpoint declared in API-CONTRACTS.md, static presence check across framework patterns (fastify / express / nest / hono); missing routes → BLOCK. Catches phantom endpoints at wave-commit boundary instead of surfacing at review/test 1+ hour later (OHOK A2, v2.4).
3. **Orchestrator coordinates, not executes** — discover plans, group waves, spawn agents, collect results.
4. **Context budget per agent ~2000 lines** — each executor gets scoped context blocks (task/API contract/CRUD surface/goals/design/sibling/wave/execution). Modern Claude 200k comfortable; starving context causes drift. See step 8c for per-block line budgets.
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
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-build" "0_gate_integrity_precheck" 2>&1 || true

# v2.2 — T8 gate now routes through block_resolve. L1 auto-clears stale
# file if every entry carries a resolution marker ([resolved-upstream|
# resolved-merged|skipped|manual-review]). Only genuinely unresolved
# conflicts BLOCK. Helper unavailable → fall through to original hard exit.
if [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh" ]; then
  [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" ] && \
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh"
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh"
  t8_gate_check "${PLANNING_DIR}" "build"
  T8_RC=$?
  [ "$T8_RC" -eq 2 ] && exit 2
  [ "$T8_RC" -eq 1 ] && exit 1
elif [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved."
  echo "   File: ${PLANNING_DIR}/vgflow-patches/gate-conflicts.md"
  echo "   Cause: /vg:update 3-way merge altered hard-gate (cổng cứng) blocks."
  echo "   Fix:   /vg:reapply-patches --verify-gates"
  exit 1
fi
```
</step>

```bash
# v2.2 — register run with orchestrator (idempotent if UserPromptSubmit hook fired)
# OHOK-8 round-4 Codex fix: parse phase BEFORE run-start (was registering
# empty phase because PHASE_ARG/PHASE_NUMBER not set until step 1 below).
[ -z "${PHASE_ARG:-}" ] && PHASE_ARG=$(echo "${ARGUMENTS}" | awk '{print $1}')
PHASE_NUMBER="${PHASE_NUMBER:-$PHASE_ARG}"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:build "${PHASE_NUMBER:-${PHASE_ARG}}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 0_gate_integrity_precheck 2>/dev/null || true
```

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
# v2.5.1 anti-forge (2026-04-24): emit tasklist so user sees authoritative
# step plan before N-wave execution. Contract requires build.tasklist_shown
# event — AI cannot silently start build without visible task plan.
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:build" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_ARG:-unknown}" 2>&1 | head -40 || true
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
VALID_FLAGS_PATTERN='^--(wave|only|status|gaps-only|interactive|auto|reset-queue|skip-design-check|skip-context-rebuild|resume|allow-missing-commits|allow-r5-violation|skip-reflection|skip-cross-phase-ripple|skip-ux-gates|allow-ux-violations|override-reason|force|help)$'
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
WAVE_FILTER=""
[[ "${ARGUMENTS:-}" =~ --reset-queue ]] && RESET_QUEUE=true
[[ "${ARGUMENTS:-}" =~ --status ]] && STATUS_ONLY=true
if [[ "${ARGUMENTS:-}" =~ --only[[:space:]]*=?[[:space:]]*([0-9,]+) ]]; then
  ONLY_TASKS="${BASH_REMATCH[1]}"
fi
# --wave N → WAVE_FILTER (declared in flag list line 157, gate-used at step 8 line 796)
if [[ "${ARGUMENTS:-}" =~ --wave[[:space:]]*=?[[:space:]]*([0-9]+) ]]; then
  WAVE_FILTER="${BASH_REMATCH[1]}"
  export WAVE_FILTER
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

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "1_parse_args" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_parse_args.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 1_parse_args 2>/dev/null || true
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

### Step 1: Narrate step plan (NO TaskCreate — see NARRATION_POLICY above)

Per NARRATION_POLICY (`⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate`), progress tracking in /vg:build uses `.step-markers/*.done` files as the authoritative signal, NOT a task list. Before proceeding:

1. Write a markdown header in your text output listing the expected step plan:
   ```
   ## ━━━ /vg:build step plan (profile=$PROFILE, $EXPECTED_COUNT steps) ━━━
   - ${stepId_1}
   - ${stepId_2}
   - ...
   ```
2. Run each step in order. At start: write `## ━━━ Running ${stepId} ━━━` header. At end: `touch "${PHASE_DIR}/.step-markers/${stepId}.done"`.

### Step 2: Marker directory sanity check (replaces task count assertion)

Confirm marker dir is empty on fresh build (or populated as expected on resume):
```bash
EXISTING_COUNT=$(ls "$MARKER_DIR"/*.done 2>/dev/null | wc -l | tr -d ' ')
if [[ ! "$ARGUMENTS" =~ --resume ]] && [ "$EXISTING_COUNT" -ne 0 ]; then
  echo "⛔ Fresh build but ${EXISTING_COUNT} stale markers in ${MARKER_DIR}. Run with --reset-queue or manually clean."
  exit 1
fi
echo "▸ Step plan: $EXPECTED_COUNT steps for profile=$PROFILE. Progress tracked via ${MARKER_DIR}/*.done."
```

**Rule for subsequent steps:** every `<step>` body MUST, as its FINAL action, write a marker:
```bash
touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"
```
Post-execution check (step 9) compares markers vs EXPECTED_STEPS. Missing marker = step skipped silently = BLOCK.

Each sub-step: write narration header at start, marker file at end. No TaskCreate/TaskUpdate invocation anywhere in /vg:build.
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

### 3c: Amendment freshness check (harness v2.7-fixup-C1)

**Why:** `/vg:amend` writes `AMENDMENT-LOG.md` mid-phase. If user runs amend AFTER blueprint but BEFORE build, PLAN.md / API-CONTRACTS.md are stale relative to the amendment. Build would silently execute the pre-amendment plan. This gate detects mtime drift and blocks unless user explicitly overrides.

```bash
# C1 fix — Amendment freshness check
# Detect /vg:amend ran between blueprint and build → BLOCK with re-blueprint guidance.
AMENDMENT_FILE="${PHASE_DIR}/AMENDMENT-LOG.md"
if [ -f "$AMENDMENT_FILE" ]; then
  PLAN_FILE="${PHASE_DIR}/PLAN.md"
  CONTRACTS_FILE="${PHASE_DIR}/API-CONTRACTS.md"
  STALE=""
  if [ -f "$PLAN_FILE" ] && [ "$AMENDMENT_FILE" -nt "$PLAN_FILE" ]; then
    STALE="PLAN.md"
  fi
  if [ -f "$CONTRACTS_FILE" ] && [ "$AMENDMENT_FILE" -nt "$CONTRACTS_FILE" ]; then
    STALE="${STALE:+$STALE+}API-CONTRACTS.md"
  fi
  if [ -n "$STALE" ]; then
    echo "⛔ Amendment freshness BLOCK — AMENDMENT-LOG.md is newer than $STALE"
    echo "   Mid-phase amendment landed after last blueprint pass."
    echo "   Re-run: /vg:blueprint ${PHASE_NUMBER} --from=2a"
    echo "   (or override via --override-reason if amendment is doc-only)"
    if [[ ! "${ARGUMENTS}" =~ --override-reason ]]; then
      exit 1
    fi
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "amendment-stale-blueprint" "${PHASE_NUMBER}" \
        "amendment newer than blueprint; user override" "$PHASE_DIR"
    echo "⚠ --override-reason set — proceeding with stale plan, debt logged"
  fi
fi
```

Result routing:
- AMENDMENT-LOG.md absent → skip (no mid-phase change)
- AMENDMENT newer than PLAN/CONTRACTS + no --override-reason → HARD BLOCK
- AMENDMENT newer + --override-reason set → WARN + log override-debt
- AMENDMENT older than PLAN/CONTRACTS → PASS (blueprint already incorporated changes)

### 3d: CONTEXT.md freshness vs PLAN.md (harness v2.7-fixup-M4)

**Why:** Step 3b validates CONTEXT.md format + decision count, but does NOT detect when user manually edits CONTEXT.md after blueprint completed. Mid-phase decision tweak (e.g., adding D-15 directly to CONTEXT.md without /vg:amend) leaves PLAN.md stale referencing the pre-edit decision set. Build executes against an inconsistent decision graph. This gate compares mtimes and forces a re-blueprint or explicit override.

```bash
# M4 fix — CONTEXT.md mtime freshness check
# Detects post-blueprint edits to CONTEXT.md → BLOCK with re-blueprint or /vg:amend guidance.
if [ "$PHASE_PROFILE_FOR_CTX" = "feature" ] && [ -f "$CONTEXT_FILE" ]; then
  PLAN_FILE="${PHASE_DIR}/PLAN.md"
  if [ -f "$PLAN_FILE" ] && [ "$CONTEXT_FILE" -nt "$PLAN_FILE" ]; then
    echo "⛔ CONTEXT.md modified after PLAN.md — re-blueprint or run /vg:amend"
    echo "   PLAN.md is stale relative to current CONTEXT.md decisions."
    echo "   Run: /vg:blueprint ${PHASE_NUMBER} --from=2a   (re-plan from current CONTEXT)"
    echo "   OR:  /vg:amend ${PHASE_NUMBER}                  (capture change as amendment)"
    echo "   Override (NOT RECOMMENDED): re-run with --override-reason=\"...\""
    if [[ ! "${ARGUMENTS}" =~ --override-reason ]]; then
      exit 1
    fi
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "context-stale-plan" "${PHASE_NUMBER}" \
        "CONTEXT newer than PLAN; user override" "$PHASE_DIR"
    echo "⚠ --override-reason set — proceeding with stale plan, debt logged"
  fi
fi
```

Result routing:
- CONTEXT.md older than PLAN.md → PASS (blueprint incorporated current decisions)
- CONTEXT.md newer + no --override-reason → HARD BLOCK
- CONTEXT.md newer + --override-reason set → WARN + log override-debt
- Non-feature profile → skip (CONTEXT.md not required)
</step>

<step name="4_load_contracts_and_context">
**Load artifacts + resolve all context-injection variables BEFORE spawning executors.**

**Resume-safe:** This step MUST run even on `--resume` if its artifacts are missing.
Prior builds may have lacked graphify context — new build needs step 4 data.

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
if [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  # Source graphify-safe helper (verifies mtime advances post-rebuild, retries once on stuck)
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"

  if [ ! -f "$GRAPHIFY_GRAPH_PATH" ]; then
    echo "Graphify: enabled but graph missing — cold-building before executor context"
    if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-step4-cold"; then
      GRAPHIFY_ACTIVE="true"
    elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
      echo "⛔ Graphify cold build failed and fallback_to_grep=false"
      exit 1
    else
      echo "⚠ Graphify cold build failed; step 4 will use grep fallback"
    fi
  fi

  if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
    GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
    COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')

    if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
      echo "Graphify: ${COMMITS_SINCE} commits since last build — rebuilding for fresh context"
      vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-step4" || {
        if [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
          echo "⛔ Graphify rebuild failed and fallback_to_grep=false"
          exit 1
        fi
        echo "⚠ Graphify rebuild did not complete successfully; downstream sibling/caller context may be stale"
      }
    else
      echo "Graphify: up to date (0 commits since last build)"
    fi
  fi
fi
```

**Why always rebuild before build:** Graph is consumed by step 4c (siblings) and 4e (callers). Stale graph = wrong sibling suggestions = executor copies wrong patterns. Rebuild is fast (~10s for incremental) and runs once per build — cheap insurance vs debugging wrong sibling context.

### 4_pre_b: Read pre-build CrossAI verdict (harness v2.7-fixup-M6)

**Why:** Blueprint step 2d-6 emits `${PHASE_DIR}/crossai/result-blueprint-review*.xml`
(MUST_WRITE per blueprint frontmatter). Build's own CrossAI loop (step 11) writes
into a SEPARATE directory and has zero awareness of the pre-build verdict. If the
blueprint pass flagged unresolved major/critical issues that minor auto-fix didn't
land, the executor is unaware of them. Surface that verdict here so the operator
sees continuity across blueprint→build, and downstream prompts can tag the warning.

```bash
# M6 fix — surface blueprint-review CrossAI verdict + unresolved flag count
BLUEPRINT_CROSSAI_DIR="${PHASE_DIR}/crossai"
if [ -d "$BLUEPRINT_CROSSAI_DIR" ]; then
  # shellcheck disable=SC2086
  RESULT_XMLS=$(ls "$BLUEPRINT_CROSSAI_DIR"/result-blueprint-review*.xml 2>/dev/null)
  if [ -n "$RESULT_XMLS" ]; then
    # shellcheck disable=SC2086
    BLUEPRINT_VERDICT=$(grep -h -oP '<verdict>\K[^<]+' $RESULT_XMLS 2>/dev/null \
      | sort -u | head -3 | tr '\n' ',' | sed 's/,$//')
    # shellcheck disable=SC2086
    BLUEPRINT_FLAGS=$(grep -ch 'severity="major"\|severity="critical"' $RESULT_XMLS 2>/dev/null \
      | awk '{s+=$1} END{print s+0}')
    echo "📋 Blueprint CrossAI verdict: ${BLUEPRINT_VERDICT:-none} (${BLUEPRINT_FLAGS} unresolved major/critical)"
    # Surface to executor — appended to TASK_CONTEXT later if non-empty
    export VG_BLUEPRINT_CROSSAI_SUMMARY="verdict=${BLUEPRINT_VERDICT:-none} unresolved=${BLUEPRINT_FLAGS}"
  else
    echo "📋 Blueprint CrossAI: no result-blueprint-review*.xml found (skip-crossai or pre-2d phase)"
  fi
fi
```

Result routing:
- result-blueprint-review*.xml present → log verdict + unresolved count, export VG_BLUEPRINT_CROSSAI_SUMMARY
- No XMLs (skip-crossai run, or older phases without blueprint CrossAI) → silent skip
- Verdict==BLOCK with unresolved>0 → not auto-blocked here (build proceeds), but surfaced loudly so operator can abort

### 4a: Contract context

Read `${PHASE_DIR}/API-CONTRACTS.md`. Per plan task, extract only endpoint sections the task touches (grep for endpoint paths task mentions).

### 4b: Design context paths (fixes G4)

```bash
# Resolve DESIGN_OUTPUT_DIR from config (fallback to default)
DESIGN_OUTPUT_DIR=$(vg_config_get design_assets.output_dir "${PLANNING_DIR}/design-normalized")  # OHOK-9 round-4
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

OHOK Batch 4 B7 (2026-04-22): subprocess failure now exits build. Previously
script failure was silent — executor got empty sibling context without
orchestrator knowing.

```bash
mkdir -p "${PHASE_DIR}/.wave-context"

SIBLINGS_FAILED=()
for task in "${WAVE_TASKS[@]}"; do
  # task iteration gives TASK_NUM + TASK_FILE_PATH
  SIBLING_OUT="${PHASE_DIR}/.wave-context/siblings-task-${TASK_NUM}.json"

  GRAPHIFY_FLAG=""
  if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  if ! ${PYTHON_BIN} .claude/scripts/find-siblings.py \
       --file "$TASK_FILE_PATH" \
       --config .claude/vg.config.md \
       --top-n 3 \
       $GRAPHIFY_FLAG \
       --output "$SIBLING_OUT" 2>&1; then
    # Non-fatal per-task — new modules legitimately have no siblings.
    # But track + emit telemetry so pattern surfacing on a whole wave triggers review.
    SIBLINGS_FAILED+=("${TASK_NUM}:${TASK_FILE_PATH}")
    # Write stub so downstream 8c doesn't crash on missing JSON
    echo '{"siblings":[],"source":"find-siblings-failed"}' > "$SIBLING_OUT"
  fi
done

# If ALL tasks failed, something is systemically wrong — BLOCK.
if [ "${#SIBLINGS_FAILED[@]}" -gt 0 ] && \
   [ "${#SIBLINGS_FAILED[@]}" -eq "${#WAVE_TASKS[@]}" ]; then
  echo "⛔ find-siblings.py failed for ALL ${#WAVE_TASKS[@]} tasks in wave — systemic issue" >&2
  echo "   Failures: ${SIBLINGS_FAILED[@]}" >&2
  echo "   Check: (a) find-siblings.py exists + executable, (b) config valid," >&2
  echo "          (c) graphify graph path correct if GRAPHIFY_ACTIVE=true" >&2
  exit 1
fi
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
if [ "$(vg_config_get semantic_regression.enabled true)" = "true" ]; then  # OHOK-9 round-4
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

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_load_contracts_and_context" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done"`

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_load_contracts_and_context" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 4_load_contracts_and_context 2>/dev/null || true
```
</step>

<step name="5_handle_branching">
**OHOK Batch 4 B6 (2026-04-22):** replace prose "checkout branch" with real bash.
Previously step had ZERO code — marker touched blindly regardless of whether
branch existed, checkout succeeded, or git was in conflicted state. Now gated.

```bash
BRANCH_STRATEGY=$(vg_config_get branching_strategy "none" 2>/dev/null || echo "none")

case "$BRANCH_STRATEGY" in
  phase|milestone)
    BRANCH_NAME="phase/${PHASE_NUMBER}"
    if [ "$BRANCH_STRATEGY" = "milestone" ]; then
      # milestone strategy → branch per milestone (first phase of milestone creates, others reuse)
      MILESTONE_NUM=$(echo "$PHASE_NUMBER" | cut -d. -f1)
      BRANCH_NAME="milestone/${MILESTONE_NUM}"
    fi

    # Pre-flight: no uncommitted changes that would block checkout.
    # Check BOTH worktree AND staged (index) changes — `git diff --quiet` alone
    # ignores staged-only files (CrossAI Round 6 finding).
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
      echo "⛔ Uncommitted changes (worktree or staged) — cannot checkout ${BRANCH_NAME}" >&2
      git status --short 2>/dev/null | head -10 >&2
      echo "   Commit or stash first: git stash save --include-untracked 'pre-build-${PHASE_NUMBER}'" >&2
      exit 1
    fi

    CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [ "$CURRENT" = "$BRANCH_NAME" ]; then
      echo "✓ Already on ${BRANCH_NAME}"
    elif git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
      if ! git checkout "${BRANCH_NAME}" 2>&1; then
        echo "⛔ git checkout ${BRANCH_NAME} failed" >&2
        exit 1
      fi
      echo "✓ Checked out existing branch ${BRANCH_NAME}"
    else
      if ! git checkout -b "${BRANCH_NAME}" 2>&1; then
        echo "⛔ git checkout -b ${BRANCH_NAME} failed" >&2
        exit 1
      fi
      echo "✓ Created + checked out new branch ${BRANCH_NAME}"
    fi
    ;;
  none|"")
    echo "↷ branching_strategy=none — staying on current branch ($(git rev-parse --abbrev-ref HEAD 2>/dev/null))"
    ;;
  *)
    echo "⚠ Unknown branching_strategy='${BRANCH_STRATEGY}' — skipping (expected: phase|milestone|none)" >&2
    ;;
esac

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_handle_branching" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_handle_branching.done"
```
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

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6_validate_phase" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_validate_phase.done"`
</step>

<step name="7_discover_plans">
```bash
# VG-native plan index (no GSD dependency)
PLAN_INDEX=$(ls -1 "${PHASE_DIR}"/PLAN*.md 2>/dev/null)
```

Filter: skip `has_summary: true`. If `--gaps-only`: skip non-gap_closure. If `--wave N`: skip non-matching.
Report execution plan table.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_discover_plans" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_discover_plans.done"`

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_discover_plans" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_discover_plans.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 7_discover_plans 2>/dev/null || true
```
</step>

<step name="8_execute_waves">

**⚠ WAVE_FILTER gate (v2.2):** If `WAVE_FILTER` is set (from `--wave N`), execute **ONLY** that wave. After Wave N completes + commits successfully, skip all subsequent waves and proceed directly to step 9_post_execution. Use for incremental testing on large phases (8+ waves).

```bash
if [ -n "${WAVE_FILTER:-}" ]; then
  echo "▸ --wave ${WAVE_FILTER} mode: orchestrator will execute ONLY Wave ${WAVE_FILTER} then exit to step 9."
fi
```

For each wave (subject to WAVE_FILTER gate above):

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
TASK_CAPSULE_DIR="${PHASE_DIR}/.task-context-capsules"
mkdir -p "$TASK_CAPSULE_DIR" 2>/dev/null
TASK_CAPSULE_PATH="${TASK_CAPSULE_DIR}/task-${TASK_NUM}.json"
CONTEXT_JSON=$(${PYTHON_BIN} .claude/scripts/pre-executor-check.py \
  --phase-dir "${PHASE_DIR}" \
  --task-num ${TASK_NUM} \
  --config .claude/vg.config.md \
  --capsule-out "$TASK_CAPSULE_PATH")

# Parse output into variables
TASK_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['task_context'])")
CONTRACT_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['contract_context'])")
GOALS_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['goals_context'])")
CRUD_SURFACE_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin).get('crud_surface_context','CRUD-SURFACES.md not found'))")
TASK_CONTEXT_CAPSULE=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.dumps(json.load(sys.stdin)['task_context_capsule'], indent=2, ensure_ascii=False))")
TASK_SIBLINGS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['sibling_context'])")
TASK_CALLERS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['downstream_callers'])")
DESIGN_CONTEXT=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['design_context'])")
# L1 design pixel gate inputs
DESIGN_IMAGE_PATHS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('design_image_paths', []) or []))")
DESIGN_IMAGE_REQUIRED=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print('1' if json.load(sys.stdin).get('design_image_required') else '0')")
BUILD_CONFIG=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print(json.dumps(json.load(sys.stdin)['build_config']))")

# ─── L1 hard-gate: PNG must exist on disk before spawning executor ────────
# Without this, executor receives a path that resolves to nothing — the Read
# tool would fail, the model would silently fall back to fabricating layout.
# This gate runs deterministically before every executor spawn for any task
# whose body declares a SLUG-form <design-ref>.
if [ "$DESIGN_IMAGE_REQUIRED" = "1" ]; then
  if [ -z "$DESIGN_IMAGE_PATHS" ]; then
    echo "⛔ L1 design-pixel gate: task ${TASK_NUM} declares <design-ref> but no PNG resolved." >&2
    echo "   Likely cause: slug missing from manifest. Run: /vg:design-extract --refresh" >&2
    if [[ ! "$ARGUMENTS" =~ --skip-design-pixel-gate ]]; then exit 1; fi
    echo "⚠ --skip-design-pixel-gate set — executor will be blind to layout." >&2
  else
    L1_MISSING=""
    while IFS= read -r p; do
      [ -z "$p" ] && continue
      if [ ! -f "$p" ]; then
        L1_MISSING="${L1_MISSING}\n  - ${p}"
      fi
    done <<< "$DESIGN_IMAGE_PATHS"
    if [ -n "$L1_MISSING" ]; then
      echo -e "⛔ L1 design-pixel gate: required PNG(s) missing on disk:${L1_MISSING}" >&2
      echo "   Run: /vg:design-extract --refresh   (regenerates manifest + screenshots)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-design-pixel-gate ]]; then exit 1; fi
      echo "⚠ --skip-design-pixel-gate set — proceeding without ground-truth pixels." >&2
    else
      L1_COUNT=$(printf '%s\n' "$DESIGN_IMAGE_PATHS" | grep -c .)
      echo "✓ L1 design-pixel gate: ${L1_COUNT} PNG(s) verified on disk for task ${TASK_NUM}"
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "build_l1_design_pixel" "${PHASE_NUMBER}" "build.8c" \
          "design_pixel_verified" "PASS" "{\"task\":${TASK_NUM},\"png_count\":${L1_COUNT}}"
      fi
    fi
  fi
fi

if [ ! -s "$TASK_CAPSULE_PATH" ]; then
  echo "⛔ Task context capsule missing for task ${TASK_NUM}: $TASK_CAPSULE_PATH" >&2
  echo "   pre-executor-check.py must write this before spawning. Do not spawn with ad-hoc context." >&2
  exit 1
fi

# ─── Phase 15 D-12a + D-14 — UI-MAP wave-scoped subtree injection ────────
# Pull the ~50-line subtree owned by the current wave (and optionally the
# current task) out of the planner's UI-MAP.md and inject as a dedicated
# context block. Deterministic JSON filter via extract-subtree-haiku.mjs —
# despite the filename, no Haiku sub-agent is spawned (D-14 settled on the
# pure-JS filter as faster + free + reproducible).
#
# Skip when:
#   - UI-MAP.md missing (backend-only phase or planner skipped 2b6b)
#   - extract-subtree-haiku.mjs missing (Phase 15 T4.2 not installed)
UI_MAP_SUBTREE=""
UI_MAP_SUBTREE_BLOCK=""
if [ -f "${PHASE_DIR}/UI-MAP.md" ] \
   && [ -f "${REPO_ROOT}/.claude/scripts/extract-subtree-haiku.mjs" ]; then
  UIMAP_TMP="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-subtree-w${N}-t${TASK_NUM}.md"
  mkdir -p "$(dirname "$UIMAP_TMP")" 2>/dev/null
  # owner-wave-id convention: planner emits "wave-${N}" (per blueprint 2b6b
  # planner prompt). owner-task-id convention: "T-${TASK_NUM}".
  if node "${REPO_ROOT}/.claude/scripts/extract-subtree-haiku.mjs" \
        --uimap "${PHASE_DIR}/UI-MAP.md" \
        --owner-wave-id "wave-${N}" \
        --owner-task-id "T-${TASK_NUM}" \
        --format markdown \
        --output "$UIMAP_TMP" 2>/dev/null; then
    SUBTREE_LINES=$(wc -l < "$UIMAP_TMP" 2>/dev/null || echo 0)
    if [ "${SUBTREE_LINES:-0}" -gt 1 ]; then
      UI_MAP_SUBTREE=$(cat "$UIMAP_TMP")
      # H2 marker required by verify-uimap-injection.py (D-12a). Don't change
      # `## UI-MAP-SUBTREE-FOR-THIS-WAVE` — validator greps that exact string.
      UI_MAP_SUBTREE_BLOCK="## UI-MAP-SUBTREE-FOR-THIS-WAVE

Wave-scoped subtree from planner UI-MAP.md (Phase 15 D-12a + D-14).
Owner filter: wave-${N} / T-${TASK_NUM}. ~${SUBTREE_LINES} lines.
Build the components listed below — names, classes, props, text are the
planned target. Reviewer post-wave drift gate (D-12b) compares your code
against this subtree.

${UI_MAP_SUBTREE}
"
      echo "✓ UI-MAP subtree (${SUBTREE_LINES} lines) extracted for wave-${N}/T-${TASK_NUM}"
    else
      # Empty subtree — task likely doesn't own UI nodes (e.g., backend task
      # within a mixed-profile wave). Inject explicit NONE marker so executor
      # doesn't accidentally invent components.
      UI_MAP_SUBTREE_BLOCK="## UI-MAP-SUBTREE-FOR-THIS-WAVE

NONE — task has no owned UI subtree (backend / non-FE task in mixed wave).
"
    fi
  fi
fi

# ─── Phase 16 hot-fix (v2.11.1) — split persist (BLOCKers 2+3) ────────────
# Cross-AI consensus rework: previous code wrapped BOTH the prompt body
# persist AND the meta sidecar persist inside the UI/design conditional.
# Two failure modes:
#   (B2) UI tasks: ${TASK_NUM}.md contained UI-MAP wrapper, NOT task body —
#        verify-task-fidelity.py compared against that wrapper's line count
#        → false BLOCK on every UI task (test fixture bypassed by writing
#        body directly to disk).
#   (B3) Backend tasks (no UI subtree, no design context): step 8c
#        short-circuited entirely → no meta.json → audit silent PASS →
#        orchestrator could paraphrase backend task bodies freely.
#
# Now: 3 file shapes, 2 always-on + 1 conditional:
#   ${TASK_NUM}.body.md  — raw task body (what the executor's <task_context>
#                          should mirror). Always persisted. Read by
#                          verify-task-fidelity.py for hash compare.
#   ${TASK_NUM}.meta.json — D-01 sidecar with source_block_sha256. Always
#                          persisted. Read by verify-task-fidelity.py.
#   ${TASK_NUM}.uimap.md  — D-12a UI-MAP+DESIGN-REF wrapper. Only persisted
#                          for UI tasks. Read by verify-uimap-injection.py.

PROMPT_PERSIST_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
mkdir -p "$PROMPT_PERSIST_DIR" 2>/dev/null
PROMPT_BODY_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.body.md"
PROMPT_META_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.meta.json"
PROMPT_FULL_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.prompt.md"

# (1) Body persist — always. Source of truth is $TASK_CONTEXT (the
# canonical PLAN task body from CONTEXT_JSON, written by
# pre-executor-check.py extract_task_section_v2 in C1 hot-fix).
printf '%s\n' "$TASK_CONTEXT" > "$PROMPT_BODY_PERSIST"
echo "✓ Task body persisted → $PROMPT_BODY_PERSIST"

# (2) Meta sidecar — always. wave field overridden from "unknown"
# (pre-executor-check.py default) to actual wave-${N}.
echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "
import json, sys
ctx = json.load(sys.stdin)
meta = ctx.get('task_meta')
if not meta:
    sys.exit(0)  # hasher missing — sidecar skipped, T-4.3 audit will WARN
meta['wave'] = 'wave-${N}'
print(json.dumps(meta, indent=2))
" > "$PROMPT_META_PERSIST" 2>/dev/null || true
if [ -s "$PROMPT_META_PERSIST" ]; then
  echo "✓ P16 D-01 task meta persisted → $PROMPT_META_PERSIST"
fi

# (3) UI-MAP wrapper persist — UI tasks only (D-12a injection audit input).
if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then
  PROMPT_UIMAP_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.uimap.md"
  {
    echo "<!-- Wave ${N} / Task ${TASK_NUM} UI-MAP+design-ref wrapper (Phase 15 D-12a). -->"
    echo "<!-- Read by verify-uimap-injection.py — separate from .body.md (P16 hotfix). -->"
    echo ""
    echo "${UI_MAP_SUBTREE_BLOCK:-## UI-MAP-SUBTREE-FOR-THIS-WAVE\n\nNONE}"
    echo ""
    echo "## DESIGN-REF"
    echo ""
    if [ -n "$DESIGN_CONTEXT" ]; then
      echo "$DESIGN_CONTEXT"
    else
      echo "NONE — task has no <design-ref> attribute (non-UI task)."
    fi
  } > "$PROMPT_UIMAP_PERSIST"
  echo "✓ UI-MAP+design-ref wrapper persisted → $PROMPT_UIMAP_PERSIST"
fi

# Script auto-builds siblings + callers if missing (runs find-siblings.py + build-caller-graph.py)
# Graphify used: ${graphify.enabled} from config → sibling/caller enrichment

# R4 enforcement (v1.14.4+) — context budget check per block + total prompt size
# Rule 4 khai "Context budget per agent ~2000 lines, 7 blocks". Gate đây để tránh drift/OOM.
PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - <<PY
import json, sys

ctx = json.loads('''$CONTEXT_JSON''')

# Phase 16 D-04 — read R4 caps from CONTEXT_JSON.applied_caps (set by
# pre-executor-check.py based on CONTEXT.md frontmatter cross_ai_enriched
# flag). Falls back to baseline 300/500/200/400/400/200/80 + total 2500
# when applied_caps absent (older pre-executor-check.py without D-04).
BUDGETS = ctx.get('applied_caps') or {
    'task_context': 300,
    'contract_context': 500,
    'goals_context': 200,
    'crud_surface_context': 300,
    'sibling_context': 400,
    'downstream_callers': 400,
    'design_context': 200,
    'ui_map_subtree': 80,
}
HARD_TOTAL_MAX = ctx.get('hard_total_max') or ${CONFIG_BUILD_PROMPT_MAX_LINES:-2500}
BUDGET_MODE = ctx.get('budget_mode', 'default')

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
    print(f"✓ R4 budget [{BUDGET_MODE}]: {total} lines (hard max {HARD_TOTAL_MAX}), per-block ok")
PY
R4_RC=$?
if [ "$R4_RC" != "0" ]; then
  echo "R4-overflow task=${TASK_NUM} phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_r4_overflow" "${PHASE_NUMBER}" "build.8c" "build_r4_overflow" "FAIL" "{\"detail\":\"task=${TASK_NUM}\"}"
    fi
  echo "⛔ Executor spawn blocked — fix context budget or raise config.build.prompt_max_lines, then re-run."
  exit 1
fi

# Bootstrap rules injection (v1.15.1 — hard rule: learnings from past phases MUST
# reach the executor). BOOTSTRAP_PAYLOAD_FILE is exported by config-loader.md;
# scope DSL already filtered rules against current phase metadata at load time.
# Here we render only rules whose target_step matches `build` or `global`.
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "build")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "build" "${PHASE_NUMBER}"

# Phase C (v2.5): Scoped context injection
# Read context_injection.mode from config. Default "full" (backward-compat).
CTX_INJECT_MODE=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*mode:\s*[\'\"]{0,1}(full|scoped)[\'\"]{0,1}', line)
    if m: print(m.group(1)); break
" 2>/dev/null || echo "full")
CTX_INJECT_FALLBACK=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*scoped_fallback_on_missing:\s*(true|false)', line, re.IGNORECASE)
    if m: print(m.group(1)); break
" 2>/dev/null || echo "true")

# Phase cutover: phases >= cutover default to scoped if config says "full" + phase is new
CTX_CUTOVER=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*phase_cutover:\s*(\d+)', line)
    if m: print(int(m.group(1))); break
" 2>/dev/null || echo "14")
PHASE_NUM_FLOAT=$(echo "${PHASE_NUMBER}" | awk '{printf "%.0f", $1}' 2>/dev/null || echo "0")
if [ "$CTX_INJECT_MODE" = "full" ] && [ "${PHASE_NUM_FLOAT:-0}" -ge "${CTX_CUTOVER:-14}" ] 2>/dev/null; then
  CTX_INJECT_MODE="scoped"
  echo "⚠ Phase ${PHASE_NUMBER} >= cutover ${CTX_CUTOVER} — auto-upgrading context_injection.mode to scoped"
fi

# Resolve DECISION_CONTEXT block for executor prompt
DECISION_CONTEXT=""
TASK_FILE="${PHASE_DIR}/.wave-tasks/task-${TASK_NUM}.md"
if [ "$CTX_INJECT_MODE" = "scoped" ] && [ -f "$TASK_FILE" ]; then
  # Extract <context-refs> from task file
  CTX_REFS=$(${PYTHON_BIN} -c "
import re, sys
text = open('${TASK_FILE}', encoding='utf-8').read()
m = re.search(r'<context-refs>(.*?)</context-refs>', text, re.DOTALL)
if m:
    refs = [r.strip() for r in re.split(r'[,\s]+', m.group(1).strip()) if r.strip()]
    print(','.join(refs))
" 2>/dev/null || echo "")

  if [ -n "$CTX_REFS" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
    # Extract only the referenced decision blocks from CONTEXT.md
    DECISION_CONTEXT=$(${PYTHON_BIN} - "${PHASE_DIR}/CONTEXT.md" "$CTX_REFS" <<'PY'
import re, sys
from pathlib import Path
ctx_text = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace')
refs = sys.argv[2].split(',') if sys.argv[2] else []
blocks = []
# Split on ### header — each decision is a block
parts = re.split(r'^(#{2,3}\s+(?:P[\d.]+\.)?D-\d+.*?)$', ctx_text, flags=re.MULTILINE)
for i, part in enumerate(parts):
    header_m = re.match(r'^#{2,3}\s+((?:P[\d.]+\.)?D-\d+)', part)
    if header_m:
        did = header_m.group(1)
        body = parts[i+1] if i+1 < len(parts) else ""
        if any(r == did or did.endswith(r) or r.endswith(did) for r in refs):
            blocks.append(part + body)
if blocks:
    print('Relevant decisions from CONTEXT.md:\n' + '\n---\n'.join(blocks).strip())
else:
    print('(no matching decisions found for refs: ' + ', '.join(refs) + ')')
PY
    )
    elif [ "$CTX_INJECT_FALLBACK" = "true" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
      # Fallback: inject full CONTEXT.md when refs missing + fallback enabled
      DECISION_CONTEXT="$(cat "${PHASE_DIR}/CONTEXT.md")"
      echo "⚠ Task ${TASK_NUM} has no <context-refs>, falling back to full CONTEXT.md inject."
    fi
  elif [ "$CTX_INJECT_MODE" = "full" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
    DECISION_CONTEXT="$(cat "${PHASE_DIR}/CONTEXT.md")"
  fi
elif [ "$CTX_INJECT_MODE" = "full" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  DECISION_CONTEXT="$(cat "${PHASE_DIR}/CONTEXT.md")"
fi

# Materialize critical prompt blocks literally. Do not rely on @file expansion
# inside child Agent/Task prompts; that is exactly where lazy-read drift starts.
VG_EXECUTOR_RULES=""
[ -f ".claude/commands/vg/_shared/vg-executor-rules.md" ] && \
  VG_EXECUTOR_RULES="$(cat .claude/commands/vg/_shared/vg-executor-rules.md)"

UI_SPEC_CONTEXT="NONE - UI-SPEC.md unavailable or not relevant for this task."
[ -f "${PHASE_DIR}/UI-SPEC.md" ] && \
  UI_SPEC_CONTEXT="$(sed -n '1,260p' "${PHASE_DIR}/UI-SPEC.md")"

WAVE_CONTEXT="NONE - wave context unavailable."
[ -f "${PHASE_DIR}/wave-${N}-context.md" ] && \
  WAVE_CONTEXT="$(cat "${PHASE_DIR}/wave-${N}-context.md")"

# Persist the full executor prompt evidence before spawn. D-06 task-fidelity
# validator verifies that this full prompt contains TASK_CONTEXT verbatim, not
# just a pointer to a task file or a paraphrased summary.
{
  echo "<task_context_capsule path=\"$TASK_CAPSULE_PATH\">"
  printf '%s\n' "$TASK_CONTEXT_CAPSULE"
  echo "</task_context_capsule>"
  echo ""
  echo "<vg_executor_rules>"
  printf '%s\n' "$VG_EXECUTOR_RULES"
  echo "</vg_executor_rules>"
  echo ""
  echo "<bootstrap_rules>"
  printf '%s\n' "$BOOTSTRAP_RULES_BLOCK"
  echo "</bootstrap_rules>"
  echo ""
  echo "<decision_context>"
  printf '%s\n' "$DECISION_CONTEXT"
  echo "</decision_context>"
  echo ""
  echo "<task_context>"
  printf '%s\n' "$TASK_CONTEXT"
  echo "</task_context>"
  echo ""
  echo "<contract_context>"
  printf '%s\n' "$CONTRACT_CONTEXT"
  echo "</contract_context>"
  echo ""
  echo "<crud_surface_context>"
  printf '%s\n' "$CRUD_SURFACE_CONTEXT"
  echo "</crud_surface_context>"
  echo ""
  echo "<ui_spec_context>"
  printf '%s\n' "$UI_SPEC_CONTEXT"
  echo "</ui_spec_context>"
  echo ""
  echo "<goals_context>"
  printf '%s\n' "$GOALS_CONTEXT"
  echo "</goals_context>"
  echo ""
  echo "<design_context>"
  printf '%s\n' "$DESIGN_CONTEXT"
  echo "</design_context>"
  echo ""
  printf '%s\n' "$UI_MAP_SUBTREE_BLOCK"
  echo ""
  echo "<sibling_context>"
  printf '%s\n' "$TASK_SIBLINGS"
  echo "</sibling_context>"
  echo ""
  echo "<downstream_callers>"
  printf '%s\n' "$TASK_CALLERS"
  echo "</downstream_callers>"
  echo ""
  echo "<wave_context>"
  printf '%s\n' "$WAVE_CONTEXT"
  echo "</wave_context>"
} > "$PROMPT_FULL_PERSIST"
echo "✓ Full executor prompt persisted -> $PROMPT_FULL_PERSIST"
```

**Spawn executor agent (one per plan task):**

**MANDATORY:** subagent_type MUST be `general-purpose`. **NEVER spawn
`gsd-executor`.** GSD's executor enforces a different (looser) rule set
including `--no-verify` parallel mode that VG explicitly forbids. If
the project's CLAUDE.md mentions "gsd-executor spawned by /vg:build",
that is a stale doc from old vgflow versions — IGNORE it; spawn
general-purpose with the VG_EXECUTOR_RULES block below. The wave
status line in your output will read `general-purpose(Wave N Task M)`,
not `gsd-executor(...)`.

```
Agent(subagent_type="general-purpose", model="${MODEL_EXECUTOR}"):
  prompt: |
    <task_context_capsule path="${TASK_CAPSULE_PATH}">
    ${TASK_CONTEXT_CAPSULE}
    </task_context_capsule>

    <vg_executor_rules>
    ${VG_EXECUTOR_RULES}
    </vg_executor_rules>

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>

    <build_config>
    typecheck_cmd: ${TYPECHECK_CMD_RESOLVED:-$(vg_config_get build_gates.typecheck_cmd pnpm\ typecheck)}
    build_cmd: ${BUILD_CMD_RESOLVED:-$(vg_config_get build_gates.build_cmd pnpm\ build)}
    generated_types_path: ${GENERATED_TYPES_PATH_RESOLVED:-$(vg_config_get contract_format.generated_types_path packages/api-types)}
    phase: ${PHASE_NUMBER}
    plan: ${PLAN_NUM}
    </build_config>

    <decision_context>
    # Phase C (v2.5): decisions extracted from CONTEXT.md per context_injection.mode.
    # mode=scoped: only decisions listed in task's <context-refs> element.
    # mode=full:   full CONTEXT.md (backward-compat for phases 0-13).
    # Empty = task has no relevant decisions OR CONTEXT.md unavailable.
    ${DECISION_CONTEXT}
    </decision_context>

    <task_context>
    ${TASK_CONTEXT}
    </task_context>

    <contract_context>
    Relevant contract code blocks to COPY VERBATIM (not retype).
    M3 fix (harness v2.7-fixup): DROPPED full-file @-include of API-CONTRACTS.md.
    The block below is the SCOPED, per-endpoint slice resolved by
    pre-executor-check.py — single source of truth, R4 budget stays accurate.
    ${CONTRACT_CONTEXT}
    Import types from: ${config.contract_format.generated_types_path}
    </contract_context>

    <crud_surface_context>
    Resource-level CRUD contract slice from CRUD-SURFACES.md. This is the
    source of truth for platform-specific list/form/delete/API behavior.
    Follow the overlay matching this task's platform; do not apply web table
    rules to mobile screens or backend-only endpoints.
    ${CRUD_SURFACE_CONTEXT}
    </crud_surface_context>

    <ui_spec_context>
    ${UI_SPEC_CONTEXT}
    </ui_spec_context>

    <goals_context>
    ${GOALS_CONTEXT}
    </goals_context>

    <design_context>
    ${DESIGN_CONTEXT}
    </design_context>

    ${UI_MAP_SUBTREE_BLOCK}

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
    ${WAVE_CONTEXT}
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
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_r5_violation" "${PHASE_NUMBER}" "build.8d" "build_r5_violation" "FAIL" "{\"detail\":\"wave=${N}\"}"
    fi
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

**Phase 15 D-12a — UI-MAP + design-ref injection audit (NEW, 2026-04-27):**

Audits the executor prompts persisted in step 8c to confirm BOTH
`## UI-MAP-SUBTREE-FOR-THIS-WAVE` and `## DESIGN-REF` H2 sections were
injected for every UI-touching task. Catches regressions like Wave 7
B2 where the inject path silently dropped the markers.

```bash
INJ_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-uimap-injection.py"
WAVE_PROMPT_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
if [ -x "$INJ_VAL" ] && [ -d "$WAVE_PROMPT_DIR" ]; then
  ${PYTHON_BIN} "$INJ_VAL" --phase "${PHASE_NUMBER}" \
      --prompts-dir "$WAVE_PROMPT_DIR" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-injection-w${N}.json" 2>&1 || true
  IV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-injection-w${N}.json" 2>/dev/null)
  case "$IV" in
    PASS|WARN) echo "✓ D-12a UI-MAP+design-ref injection audit: $IV" ;;
    BLOCK)
      echo "⛔ D-12a injection audit: BLOCK — see ${VG_TMP}/uimap-injection-w${N}.json" >&2
      echo "   Step 8c persist did not write both ## UI-MAP-SUBTREE-FOR-THIS-WAVE +" >&2
      echo "   ## DESIGN-REF headers into ${WAVE_PROMPT_DIR}/<task>.md." >&2
      if [[ ! "$ARGUMENTS" =~ --skip-uimap-injection-audit ]]; then exit 1; fi
      ;;
    *) echo "ℹ D-12a injection audit: $IV" ;;
  esac
fi
```

**Phase 16 D-06 — Task fidelity audit (orchestrator paraphrase detection):**

Post-spawn 3-way hash audit. For each (wave × task) pair under
`.build/wave-${N}/executor-prompts/`, compares:
  1. PLAN.md task block re-extracted now (current truth)
  2. .meta.json sidecar (snapshot at spawn time, P16 D-01)
  3. .md prompt body (what executor actually received)

Detects 2 failure modes:
- PLAN drift since spawn (rare; mid-build edit → WARN)
- Body shortfall (orchestrator paraphrase / truncate):
    ≤10% PASS, 10-30% WARN, >30% BLOCK

Closes the PARAPHRASE leg of the "AI lazy-read blueprint" failure mode
(P15 W9 closed SPAWN AUDIT, v2.11.0 closed MISSING + TRUNCATION).

```bash
TF_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-task-fidelity.py"
WAVE_PROMPT_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
if [ -x "$TF_VAL" ] && [ -d "$WAVE_PROMPT_DIR" ]; then
  ${PYTHON_BIN} "$TF_VAL" --phase "${PHASE_NUMBER}" \
      --prompts-dir "$WAVE_PROMPT_DIR" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-fidelity-w${N}.json" 2>&1 || true
  TFV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-fidelity-w${N}.json" 2>/dev/null)
  case "$TFV" in
    PASS|WARN) echo "✓ D-06 task fidelity audit: $TFV" ;;
    BLOCK)
      echo "⛔ D-06 task fidelity audit: BLOCK — orchestrator likely paraphrased task body" >&2
      echo "   See ${VG_TMP}/task-fidelity-w${N}.json for per-task shortfall breakdown" >&2
      echo "   Override: --skip-task-fidelity-audit (logs override-debt as kind=task-fidelity-audit-skipped)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-task-fidelity-audit ]]; then exit 1; fi
      ;;
    *) echo "ℹ D-06 task fidelity audit: $TFV" ;;
  esac
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
else
  # Fallback when lib unavailable (older install) — use vg_config_get helper
  TYPECHECK_CMD=$(vg_config_get build_gates.typecheck_cmd "")
  if [ -n "$TYPECHECK_CMD" ]; then
    echo "Gate 1/4: Running ${TYPECHECK_CMD} (non-adaptive)..."
    if ! eval "$TYPECHECK_CMD"; then
      FAILED_GATE="typecheck"
    fi
  fi
fi

# Gate 2: Build (mandatory)
if [ -z "$FAILED_GATE" ]; then
  BUILD_CMD=$(vg_config_get build_gates.build_cmd "")
  if [ -n "$BUILD_CMD" ]; then
    echo "Gate 2/4: Running ${BUILD_CMD}..."
    if ! eval "$BUILD_CMD"; then
      FAILED_GATE="build"
    fi
  fi
fi

# Gate 3: Unit tests — affected subset only (mandatory if test_unit_required=true)
if [ -z "$FAILED_GATE" ]; then
  UNIT_CMD=$(vg_config_get build_gates.test_unit_cmd "")
  UNIT_REQ=$(vg_config_get build_gates.test_unit_required "true")

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
if [ -z "$FAILED_GATE" ]; then
  CONTRACT_VERIFY_CMD=$(vg_config_get build_gates.contract_verify_grep "")
  if [ -n "$CONTRACT_VERIFY_CMD" ]; then
    echo "Gate 4/5: Running contract verify grep..."
    if ! eval "$CONTRACT_VERIFY_CMD"; then
      FAILED_GATE="contract_verify"
    fi
  fi
fi

# Gate 5: Goal-test binding (every task claiming <goals-covered> must commit
# a test file referencing the goal id or a success-criteria keyword).
# Mode from config.build_gates.goal_test_binding: strict | warn | off
if [ -z "$FAILED_GATE" ]; then
  GTB_MODE=$(vg_config_get build_gates.goal_test_binding "warn")
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
#
# M7 — Note (harness v2.7-fixup): Blueprint runs verify-utility-reuse.py at
# sub-step 2c1c (PLAN-static analysis of declarations). Gate U here runs
# verify-utility-duplication.py (post-wave AST scan, threshold-block=3).
# These have different scope intentionally — blueprint catches DECLARED helpers
# in the plan, Gate U catches RUNTIME duplications introduced across waves.
# Inconsistency is by design. If Gate U fails after blueprint passed, AST scan
# caught a copy/paste blueprint missed (executor diverged from PLAN, or PLAN
# didn't list the new helper). Threshold unification is deferred to v2.8.
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

  # Re-run failed gate only (vg_config_get for bash-safe dotted path lookup)
  case "$FAILED_GATE" in
    typecheck) CMD=$(vg_config_get build_gates.typecheck_cmd "") ;;
    build) CMD=$(vg_config_get build_gates.build_cmd "") ;;
    test_unit) CMD=$(vg_config_get build_gates.test_unit_cmd "") ;;
    contract_verify) CMD=$(vg_config_get build_gates.contract_verify_grep "") ;;
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

**Step 4b — Post-wave independent verify (v2.5 Phase A, 2026-04-23):**

Spawn fresh subprocess to re-run typecheck/tests/contract scoped to wave's changed files. Compare with executor's claims in commit messages. Divergence → rollback wave via `git reset --soft` + set FAILED_GATE.

Critical: runs AFTER commit mutex released (commit_sha stable) but BEFORE next wave starts mutating index. Outside commit-queue to avoid serializing parallelism.

```bash
# Only run if wave succeeded and bash log integrity passed
if [ -z "$FAILED_GATE" ] && [ "${CONFIG_INDEPENDENT_VERIFY_ENABLED:-true}" = "true" ]; then
  WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"

  echo "▸ Wave ${N} independent verify (post-mutex) — subprocess re-run typecheck/tests/contract"

  VERIFY_OUT=$(${PYTHON_BIN:-python3} \
    .claude/scripts/validators/wave-verify-isolated.py \
    --phase "${PHASE_NUMBER}" \
    --wave-tag "${WAVE_TAG}" 2>&1)
  VERIFY_RC=$?

  # Surface verdict + evidence for audit log
  echo "$VERIFY_OUT" | tail -1 | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f\"  wave-verify verdict: {d.get('verdict','?')} ({len(d.get('evidence',[]))} evidence)\")
    for e in d.get('evidence', [])[:3]:
        print(f\"    ─ {e.get('type')}: {e.get('message','')[:200]}\")
except Exception:
    pass
" 2>/dev/null || true

  if [ "$VERIFY_RC" -ne 0 ]; then
    # Divergence in strict mode → rollback wave commits
    if [[ "$ARGUMENTS" =~ --allow-verify-divergence ]]; then
      echo "⚠ Wave ${N} verify divergence — OVERRIDE accepted via --allow-verify-divergence"
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--allow-verify-divergence" "$PHASE_NUMBER" "build.wave-${N}.verify" \
        "executor claim vs subprocess divergence accepted by user" \
        "build-wave-${N}-verify"
      echo "override: wave=${N} gate=wave-verify reason=user-allow ts=$(date -u +%FT%TZ)" \
        >> "${PHASE_DIR}/build-state.log"
    else
      echo "⛔ Wave ${N} verify divergence — executor claim does NOT match subprocess re-run."
      echo "   Rolling back wave commits via: git reset --soft ${WAVE_TAG}"
      git reset --soft "${WAVE_TAG}" 2>/dev/null || echo "   (tag missing — manual rollback needed)"
      FAILED_GATE="wave-verify-divergence"
      echo "wave-${N}: FAILED (wave-verify-divergence, retries: ${RETRY_COUNT})" \
        >> "${PHASE_DIR}/build-state.log"
      echo ""
      echo "  Fix paths:"
      echo "    (a) Fix underlying code issue, re-run wave"
      echo "    (b) If environment flaky: --allow-verify-divergence + reason"
      echo "    (c) Check stderr_tail in evidence for subprocess failure detail"
    fi
  else
    echo "  ✓ wave-verify PASS — executor claims match subprocess reality"
  fi
fi
```

**Step 4c — Post-wave graphify refresh (MANDATORY when graphify.enabled=true):**

```bash
# Refresh graphify after each successful wave so the next wave sees the code
# that just landed. Without this, wave N+1 can read stale sibling/caller
# context and copy wrong patterns from pre-build code.
if [ -z "$FAILED_GATE" ] && [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
  if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-wave-${N}-complete"; then
    GRAPHIFY_ACTIVE="true"
  elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
    echo "⛔ Graphify post-wave rebuild failed and fallback_to_grep=false"
    exit 1
  else
    echo "⚠ Graphify post-wave rebuild failed; continuing with grep fallback visibility"
  fi
fi
```

Only proceed to next wave if `$FAILED_GATE` empty.

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "8_execute_waves" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/8_execute_waves.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 8_execute_waves 2>/dev/null || true
```
</step>

<step name="8_5_bootstrap_reflection_per_wave">
## Step 8.5: End-of-Wave Reflection (v1.15.0 Bootstrap Overlay)

Unlike scope/blueprint/review (reflect once per step), `/vg:build` reflects
**after each wave completes** — build is long-running and multiple learnings
may emerge mid-step (typecheck OOM, test flakiness, commit discipline).

**Skip silently if `.vg/bootstrap/` absent.** Per wave:

```bash
if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="wave-${WAVE_NUMBER}"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 End-of-wave ${WAVE_NUMBER} reflection..."

  # Explicit marker for orchestrator (v1.14.4+ — was implicit prose-only)
  echo "▸ REFLECTION_TRIGGER_REQUIRED step=${REFLECT_STEP} out=${REFLECT_OUT}"
  echo "  Orchestrator MUST: read .claude/commands/vg/_shared/reflection-trigger.md → Agent spawn vg-reflector"
  echo "  Skip allowed via: --skip-reflection (logs override-debt)"

  # Telemetry — reflection requested (will pair with reflection_completed in step 9 verify)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "reflection_requested" "${PHASE_NUMBER}" "build.8_5" "wave-${WAVE_NUMBER}" "PENDING" \
      "{\"wave\":${WAVE_NUMBER},\"out\":\"${REFLECT_OUT}\"}"
  fi
fi
```

**Rate limit:** max 1 reflection per wave. If 0 candidates → silent.

**Post-wave verify (added in step 9 `9_post_execution`):**
- If `.vg/bootstrap/` present + wave succeeded → `reflection-wave-N-*.yaml` MUST exist
- Missing reflection file = WARN (not block) + log telemetry `reflection_skipped` for `/vg:gate-stats` visibility
- Override: `--skip-reflection` flag bypasses warn, logs override-debt
</step>

<step name="9_post_execution">
Aggregate results:
- Count completed plans, failed plans
- Check all SUMMARY*.md files exist
- Check build-state.log — all waves passed gate? (no wave should have lingering failure)

### 9-pre-uxgates: i18n + a11y lightweight gates (v1.14.4+)

Static AST scan của FE changed files (`.tsx`/`.jsx`). Catches:
- **i18n drift**: hardcoded text trong JSX không wrap `t()` / `useTranslation`
- **a11y gap**: button/img/input thiếu aria-label/alt/label

Lightweight (no browser). Heavy Playwright + axe-core thuộc về `/vg:test`. Skip silently nếu phase không touch FE.

```bash
if [[ ! "$ARGUMENTS" =~ --skip-ux-gates ]]; then
  # Get FE files changed in this phase
  FE_CHANGED=""
  if [ -n "${first_commit:-}" ]; then
    FE_CHANGED=$(git diff --name-only "${first_commit}^..HEAD" 2>/dev/null | grep -E '\.(tsx|jsx)$' | grep -E '(apps/web|packages/ui)' || true)
  fi

  if [ -n "$FE_CHANGED" ]; then
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - <<PY
import re, sys
from pathlib import Path

changed = """$FE_CHANGED""".strip().split("\n")
i18n_violations = []
a11y_violations = []

# i18n patterns: JSX text nodes hardcoded (not wrapped in t())
JSX_TEXT_RE = re.compile(r'>\s*([A-Z][A-Za-z0-9 ,.!?\'-]{3,})\s*<')
T_CALL_RE = re.compile(r'\bt\s*\(')

# a11y patterns
BTN_NO_LABEL = re.compile(r'<button\b(?![^>]*\baria-label\b)(?![^>]*\baria-labelledby\b)[^>]*>(?:\s*<[^>]*/>)*\s*</button>')
IMG_NO_ALT = re.compile(r'<img\b(?![^>]*\balt\b)[^>]*/?>')
INPUT_NO_LABEL = re.compile(r'<input\b(?![^>]*\baria-label\b)(?![^>]*\baria-labelledby\b)(?![^>]*\bid\b)[^>]*/?>')

for fpath in changed:
    if not fpath:
        continue
    p = Path(fpath)
    if not p.exists():
        continue
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue

    # Skip files that are pure type declarations / config
    if '.d.ts' in fpath or fpath.endswith('.config.tsx'):
        continue

    # i18n: hardcoded JSX text without t() in same file
    has_t_import = bool(re.search(r'\b(useTranslation|i18n|from\s+[\'\"](react-i18next|next-i18next)[\'\"])', text))
    jsx_texts = [m.group(1).strip() for m in JSX_TEXT_RE.finditer(text)]
    # Filter: short single-word likely tags, numbers, dev placeholders
    real_texts = [t for t in jsx_texts if len(t.split()) >= 2 and not t.isdigit() and 'TODO' not in t]
    if real_texts and not has_t_import:
        i18n_violations.append({"file": fpath, "samples": real_texts[:3], "count": len(real_texts)})

    # a11y: button/img/input checks
    btn_count = len(BTN_NO_LABEL.findall(text))
    img_count = len(IMG_NO_ALT.findall(text))
    if btn_count or img_count:
        a11y_violations.append({"file": fpath, "buttons_no_label": btn_count, "imgs_no_alt": img_count})

# Report
print(f"UX gate scan: {len([f for f in changed if f])} FE files changed")

if i18n_violations:
    print(f"⚠ i18n: {len(i18n_violations)} files có hardcoded JSX text không wrap useTranslation/t():")
    for v in i18n_violations[:5]:
        print(f"   - {v['file']}: {v['count']} strings, samples: {v['samples'][:2]}")
    if len(i18n_violations) > 5:
        print(f"   ... +{len(i18n_violations)-5} more files")
else:
    print("✓ i18n: no hardcoded JSX text drift")

if a11y_violations:
    print(f"⚠ a11y: {len(a11y_violations)} files có button/img missing label/alt:")
    for v in a11y_violations[:5]:
        parts = []
        if v['buttons_no_label']: parts.append(f"{v['buttons_no_label']} button-no-label")
        if v['imgs_no_alt']: parts.append(f"{v['imgs_no_alt']} img-no-alt")
        print(f"   - {v['file']}: {', '.join(parts)}")
    if len(a11y_violations) > 5:
        print(f"   ... +{len(a11y_violations)-5} more files")
else:
    print("✓ a11y: no missing labels detected")

# Threshold for block: >5 i18n files OR >3 a11y files = significant drift
total_violation_files = len(i18n_violations) + len(a11y_violations)
if total_violation_files > 8:
    print(f"\n⛔ UX gate: {total_violation_files} violation files > threshold 8")
    sys.exit(1)
PY

    UX_RC=$?
    if [ "$UX_RC" != "0" ]; then
      echo "build-ux-gate-violation phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "ux_gate_violation" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" "{}"
      fi
      if [[ "$ARGUMENTS" =~ --allow-ux-violations ]]; then
        if type -t log_override_debt >/dev/null 2>&1; then
          log_override_debt "build-ux-violations" "${PHASE_NUMBER}" "i18n+a11y violations exceeded threshold" "$PHASE_DIR"
        fi
        echo "⚠ --allow-ux-violations set — proceeding, logged to debt"
      else
        echo "   Override (NOT recommended): /vg:build ${PHASE_NUMBER} --resume --allow-ux-violations"
        exit 1
      fi
    fi
  fi
elif [[ "$ARGUMENTS" =~ --skip-ux-gates ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-ux-gates" "${PHASE_NUMBER}" "user opted out i18n/a11y gates" "$PHASE_DIR"
  fi
fi
```

### 9-pre-ripple: Cross-phase ripple impact gate (v1.14.4+)

Verify build phase X không vô tình break code của phases trước. Sử dụng graphify caller graph để identify upstream callers, group theo phase commit ranges, run quick regression cho affected phases.

```bash
if [[ ! "$ARGUMENTS" =~ --skip-cross-phase-ripple ]]; then
  RIPPLE_REPORT="${PHASE_DIR}/.cross-phase-ripple.json"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}" "${PHASE_NUMBER}" <<'PY' > "$RIPPLE_REPORT"
import json, subprocess, sys, re, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
phase_num = sys.argv[2]
planning_dir = Path(".vg") if Path(".vg").exists() else Path(".planning")

# 1. Get files changed in this phase (git diff vs phase start)
try:
    first_commit = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", "--grep", f"({phase_num}-"],
        capture_output=True, text=True, check=True
    ).stdout.strip().split("\n")[0]
    if not first_commit:
        print(json.dumps({"skipped": "no_phase_commits"})); sys.exit(0)
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{first_commit}^..HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip().split("\n")
    changed = [f for f in changed if f and (f.endswith('.ts') or f.endswith('.tsx') or f.endswith('.js'))]
except Exception as e:
    print(json.dumps({"error": str(e)})); sys.exit(0)

if not changed:
    print(json.dumps({"changed_files": 0, "affected_phases": []})); sys.exit(0)

# 2. Find phases referencing these files (via SUMMARY.md mentions or commit attribution)
affected_phases = {}
for summary in glob.glob(str(planning_dir / "phases" / "*" / "SUMMARY*.md")):
    p = Path(summary)
    phase_name = p.parent.name
    # Extract phase num from dir name
    m = re.match(r'^(\d+(?:\.\d+)*)', phase_name)
    if not m:
        continue
    other_phase = m.group(1)
    # Skip self + future phases (lexical compare may not be perfect — skip exact match)
    if other_phase == phase_num:
        continue
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
        hits = sum(1 for f in changed if f in text)
        if hits > 0:
            affected_phases[other_phase] = hits
    except Exception:
        continue

result = {
    "phase": phase_num,
    "changed_files_count": len(changed),
    "affected_phases": affected_phases,
    "ripple_severity": "high" if len(affected_phases) >= 3 else ("medium" if len(affected_phases) >= 1 else "low"),
}
print(json.dumps(result, indent=2))
PY

  RIPPLE_RESULT=$(cat "$RIPPLE_REPORT" 2>/dev/null)
  AFFECTED_COUNT=$(echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "import sys,json; d=json.loads(sys.stdin.read()); print(len(d.get('affected_phases', {})))" 2>/dev/null || echo 0)

  if [ "${AFFECTED_COUNT:-0}" -gt 0 ]; then
    echo "⚠ Cross-phase ripple: ${AFFECTED_COUNT} previous phases reference changed files"
    echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "
import sys, json
d = json.loads(sys.stdin.read())
for p, hits in sorted(d.get('affected_phases', {}).items()):
    print(f'   - Phase {p}: {hits} file mentions in SUMMARY')
" 2>/dev/null

    echo ""
    echo "Recommended (manual): /vg:regression --phases=$(echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "import sys, json; print(','.join(json.loads(sys.stdin.read()).get('affected_phases', {}).keys()))" 2>/dev/null)"
    echo ""

    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "cross_phase_ripple" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" \
        "{\"affected_count\":${AFFECTED_COUNT}}"
    fi
  else
    echo "✓ Cross-phase ripple: 0 previous phases impacted"
  fi
elif [[ "$ARGUMENTS" =~ --skip-cross-phase-ripple ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-ripple" "${PHASE_NUMBER}" "user opted out cross-phase ripple analysis" "$PHASE_DIR"
  fi
fi
```

### 9-pre: Reflection coverage verify (v1.14.4+)

If `.vg/bootstrap/` present, verify mỗi wave thành công đã produce reflection file. Missing = WARN + telemetry (không block để không ngăn build merge khi reflector fail nhẹ).

```bash
if [ -d ".vg/bootstrap" ] && [[ ! "$ARGUMENTS" =~ --skip-reflection ]]; then
  WAVES_TOTAL=$(ls "${PHASE_DIR}"/SUMMARY-WAVE-*.md 2>/dev/null | wc -l | tr -d ' ')
  REFLECTIONS_PRESENT=$(ls "${PHASE_DIR}"/reflection-wave-*.yaml 2>/dev/null | wc -l | tr -d ' ')
  MISSING_COUNT=$((WAVES_TOTAL - REFLECTIONS_PRESENT))

  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "⚠ Reflection coverage: ${REFLECTIONS_PRESENT}/${WAVES_TOTAL} waves có reflection file"
    echo "   Missing reflections sẽ giảm chất lượng bootstrap candidates."
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "reflection_skipped" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" \
        "{\"missing\":${MISSING_COUNT},\"total\":${WAVES_TOTAL}}"
    fi
  else
    echo "✓ Reflection coverage: ${REFLECTIONS_PRESENT}/${WAVES_TOTAL} waves complete"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "reflection_complete" "${PHASE_NUMBER}" "build.9" "post-execution" "PASS" \
        "{\"count\":${REFLECTIONS_PRESENT}}"
    fi
  fi
elif [[ "$ARGUMENTS" =~ --skip-reflection ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-reflection" "${PHASE_NUMBER}" "user opted out reflection step" "$PHASE_DIR"
  fi
  echo "⚠ --skip-reflection set — reflection skipped, logged to debt register"
fi
```

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
FINAL_TYPECHECK=$(vg_config_get build_gates.typecheck_cmd "")
FINAL_BUILD=$(vg_config_get build_gates.build_cmd "")
echo "Final gate: full-repo typecheck..."
if [ -n "$FINAL_TYPECHECK" ] && ! eval "$FINAL_TYPECHECK"; then
  echo "⛔ Final typecheck failed"
  exit 1
fi

echo "Final gate: full-repo build..."
if [ -n "$FINAL_BUILD" ] && ! eval "$FINAL_BUILD"; then
  echo "⛔ Final build failed"
  exit 1
fi

# Full unit test suite (catches cross-wave regression)
# ⛔ HARD GATE (tightened 2026-04-17): --allow-no-tests replaced with --override-reason= requirement.
# Cannot silently skip final unit suite — must cite reason and log to build-state.
UNIT_CMD=$(vg_config_get build_gates.test_unit_cmd "")
UNIT_REQ=$(vg_config_get build_gates.test_unit_required "true")
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
# Canonical: blueprint writes single `PLAN.md` → expect `SUMMARY.md`.
# Legacy (GSD-migrated): `{N}-PLAN*.md` pairs with `{N}-SUMMARY*.md`.
# Glob handles both; [ ! -e "$plan" ] skips unexpanded literal when no match.
for plan in ${PHASE_DIR}/PLAN*.md ${PHASE_DIR}/*-PLAN*.md; do
  [ ! -e "$plan" ] && continue
  plan_base=$(basename "$plan")
  if [[ "$plan_base" =~ ^([0-9]+)-PLAN ]]; then
    PLAN_NUM="${BASH_REMATCH[1]}"
    SUMMARY="${PHASE_DIR}/${PLAN_NUM}-SUMMARY*.md"
  else
    PLAN_NUM="canonical"
    SUMMARY="${PHASE_DIR}/SUMMARY*.md"
  fi
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
s['status'] = 'executing'; s['pipeline_step'] = 'build-crossai-pending'
s['plans_completed'] = '${COMPLETED_COUNT}'; s['plans_total'] = '${PLAN_COUNT}'
now = datetime.now().isoformat()
s['updated_at'] = now
s.setdefault('steps', {})['build'] = {
    'status': 'in_progress',
    'updated_at': now,
    'plans_completed': '${COMPLETED_COUNT}',
    'plans_total': '${PLAN_COUNT}',
    'summary': 'SUMMARY.md written; CrossAI build verification pending',
    'reason': 'code execution complete; build is not done until CrossAI loop and run-complete pass',
}
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# 3. Update ROADMAP.md — mark phase as "in progress" (not complete until accept)
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* build-crossai-pending/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```

Display:
```
Code execution complete for Phase {N}; build is NOT complete yet.
  Plans executed: {completed}/{total}
  Contract compliance: executors had contract context
  State: SUMMARY.md written; PIPELINE-STATE build=in_progress
  Next: mandatory CrossAI build-verify -> run-complete -> /vg:review {phase}
  Do not claim /vg:build PASS until step 12 run-complete succeeds.
```

Commit summaries:
```bash
git add ${PHASE_DIR}/SUMMARY*.md ${PLANNING_DIR}/STATE.md ${PLANNING_DIR}/ROADMAP.md
git commit -m "build({phase}): {completed}/{total} plans executed"
```

```bash
# v2.7 Phase E — schema validation post-write (BLOCK on SUMMARY.md frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact summary \
  > "${PHASE_DIR}/.tmp/artifact-schema-summary.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ SUMMARY.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  exit 2
fi

# ─── L2 forcing-function gate: LAYOUT-FINGERPRINT.md per design-ref task ──
# For every task body that declared a SLUG-form <design-ref>, the executor
# is required (per vg-executor-rules.md "Design fidelity") to write a
# fingerprint to .fingerprints/task-${N}.fingerprint.md before any UI code.
# Validator below confirms each section is present + non-thin. Missing or
# thin = BLOCK build phase (override: --skip-fingerprint-check).
if [[ ! "$ARGUMENTS" =~ --skip-fingerprint-check ]]; then
  FP_BLOCKED=""
  FP_TASKS_CHECKED=0
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    [ -f "$plan" ] || continue
    "${PYTHON_BIN:-python3}" - "$plan" "${PHASE_DIR}" <<'PY' >> "${PHASE_DIR}/.tmp/fp-tasks.tsv" 2>/dev/null
import re, sys
plan_path, phase_dir = sys.argv[1], sys.argv[2]
text = open(plan_path, encoding="utf-8", errors="ignore").read()
slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
# XML-format tasks
for m in re.finditer(r'<task\s+id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</task>', text, re.DOTALL | re.IGNORECASE):
    tid, body = m.group(1), m.group(2)
    has_slug_ref = any(
        slug_re.match(r.strip())
        for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body)
        for r in re.split(r"[,\s]+", raw.strip())
    )
    if has_slug_ref:
        print(f"{tid}\t{plan_path}")
# Heading-format tasks
heading_re = re.compile(r'^#{2,3}\s+Task\s+(0?\d+)\b', re.IGNORECASE | re.MULTILINE)
lines = text.splitlines()
heads = [(i, m.group(1).lstrip("0") or "0") for i, line in enumerate(lines) for m in [heading_re.match(line)] if m]
for idx, (line_no, tid) in enumerate(heads):
    end = heads[idx+1][0] if idx+1 < len(heads) else len(lines)
    body = "\n".join(lines[line_no:end])
    has_slug_ref = any(
        slug_re.match(r.strip())
        for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body)
        for r in re.split(r"[,\s]+", raw.strip())
    )
    if has_slug_ref:
        print(f"{tid}\t{plan_path}")
PY
  done
  if [ -s "${PHASE_DIR}/.tmp/fp-tasks.tsv" ]; then
    while IFS=$'\t' read -r task_num plan_file; do
      [ -z "$task_num" ] && continue
      FP_REPORT="${PHASE_DIR}/.tmp/fp-task-${task_num}.json"
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-layout-fingerprint.py \
            --phase-dir "${PHASE_DIR}" --task-num "${task_num}" \
            --output "$FP_REPORT" >/dev/null 2>&1; then
        FP_BLOCKED="${FP_BLOCKED} task-${task_num}"
      fi
      FP_TASKS_CHECKED=$((FP_TASKS_CHECKED + 1))
    done < "${PHASE_DIR}/.tmp/fp-tasks.tsv"
    rm -f "${PHASE_DIR}/.tmp/fp-tasks.tsv"
  fi
  if [ -n "$FP_BLOCKED" ]; then
    echo "⛔ L2 fingerprint gate: missing or thin LAYOUT-FINGERPRINT.md for:${FP_BLOCKED}"
    echo "   See per-task report: ${PHASE_DIR}/.tmp/fp-task-*.json"
    echo "   Executor was supposed to write .fingerprints/task-N.fingerprint.md before UI code."
    echo "   Override (NOT RECOMMENDED — re-spawn executor with reminder is preferred): --skip-fingerprint-check"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_l2_fingerprint" "${PHASE_NUMBER}" "build.9" \
        "fingerprint_gate" "BLOCK" "{\"blocked_tasks\":\"${FP_BLOCKED}\"}"
    fi
    exit 1
  elif [ "${FP_TASKS_CHECKED:-0}" -gt 0 ]; then
    echo "✓ L2 fingerprint gate: ${FP_TASKS_CHECKED} design-ref task(s) wrote a non-thin fingerprint"
  fi
fi

# ─── L3 build-time visual gate: render UI vs design baseline (per task) ──
# Only fires when:
#   - phase has tasks with SLUG-form <design-ref>
#   - dev server reachable at build_gates.dev_server_url
#   - Node + Playwright + pixelmatch+PIL available
# Otherwise: SKIP (logged) — deliberate. We do NOT block builds when the
# visual harness isn't installed; that's the user's setup choice. Real
# pixel drift past threshold = BLOCK; override --skip-build-visual.
if [[ ! "$ARGUMENTS" =~ --skip-build-visual ]]; then
  L3_BLOCKED=""
  L3_CHECKS=0
  L3_DEV_URL="${VG_DEV_SERVER_URL:-$(vg_config_get build_gates.dev_server_url http://localhost:3000)}"
  L3_THRESHOLD="$(vg_config_get build_gates.visual_threshold_pct 5.0)"
  DESIGN_DIR_REL="$(vg_config_get design_assets.output_dir .vg/design-normalized)"
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    [ -f "$plan" ] || continue
    "${PYTHON_BIN:-python3}" - "$plan" <<'PY' >> "${PHASE_DIR}/.tmp/l3-tasks.tsv" 2>/dev/null
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")

def emit_for(tid, body):
    refs = []
    for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body):
        for r in re.split(r"[,\s]+", raw.strip()):
            r = r.strip()
            if r and slug_re.match(r):
                refs.append(r)
    if not refs:
        return
    route_m = re.search(r"<route>([^<]+)</route>", body)
    route = route_m.group(1).strip() if route_m else ""
    for slug in refs:
        print(f"{tid}\t{slug}\t{route}")

for m in re.finditer(r'<task\s+id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</task>', text, re.DOTALL | re.IGNORECASE):
    emit_for(m.group(1), m.group(2))
heading_re = re.compile(r'^#{2,3}\s+Task\s+(0?\d+)\b', re.IGNORECASE | re.MULTILINE)
lines = text.splitlines()
heads = [(i, m.group(1).lstrip("0") or "0") for i, line in enumerate(lines) for m in [heading_re.match(line)] if m]
for idx, (line_no, tid) in enumerate(heads):
    end = heads[idx+1][0] if idx+1 < len(heads) else len(lines)
    emit_for(tid, "\n".join(lines[line_no:end]))
PY
  done
  if [ -s "${PHASE_DIR}/.tmp/l3-tasks.tsv" ]; then
    while IFS=$'\t' read -r task_num slug route; do
      [ -z "$task_num" ] && continue
      [ -z "$route" ] && route="/"
      L3_REPORT="${PHASE_DIR}/.tmp/l3-task-${task_num}-${slug}.json"
      MSYS_NO_PATHCONV=1 "${PYTHON_BIN:-python3}" .claude/scripts/verify-build-visual.py \
        --phase-dir "${PHASE_DIR}" --task-num "${task_num}" --slug "${slug}" \
        --route "${route}" --design-dir "${DESIGN_DIR_REL}" \
        --server-url "${L3_DEV_URL}" --threshold-pct "${L3_THRESHOLD}" \
        --output "${L3_REPORT}" >/dev/null 2>&1
      RC=$?
      L3_CHECKS=$((L3_CHECKS + 1))
      if [ "$RC" != "0" ]; then
        L3_BLOCKED="${L3_BLOCKED} task-${task_num}/${slug}"
      fi
    done < "${PHASE_DIR}/.tmp/l3-tasks.tsv"
    rm -f "${PHASE_DIR}/.tmp/l3-tasks.tsv"
  fi
  if [ -n "$L3_BLOCKED" ]; then
    echo "⛔ L3 build visual gate: drift exceeds threshold for:${L3_BLOCKED}"
    echo "   See per-task report: ${PHASE_DIR}/.tmp/l3-task-*.json"
    echo "   Diff PNGs: ${PHASE_DIR}/build-visual/task-*/*.diff.png"
    echo "   Override: --skip-build-visual (logs override-debt)"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_l3_visual" "${PHASE_NUMBER}" "build.9" \
        "build_visual_gate" "BLOCK" "{\"blocked\":\"${L3_BLOCKED}\"}"
    fi
    exit 1
  elif [ "${L3_CHECKS:-0}" -gt 0 ]; then
    echo "✓ L3 build visual gate: ${L3_CHECKS} check(s) ran (PASS or SKIP if dev server / Playwright unavailable)"
  fi
fi

# ─── L5 design-fidelity-guard — semantic adjudication (P19 D-05) ──────────
# Spawns a Haiku zero-context with the design PNG + task commit diff to
# decide whether the code ships the components the PNG shows. Closes the
# gap where pixel-similar UI happens to miss components entirely.
#
# OFF by default (config visual_checks.vision_self_verify.enabled=false).
# When enabled: BLOCK only on guard verdict BLOCK (FLAG = log debt + continue).
# Auto-SKIPs cleanly without claude CLI / missing PNG / non-FE commit so
# unconfigured projects are never blocked by this layer.
L5_ENABLED=$(vg_config_get visual_checks.vision_self_verify.enabled false 2>/dev/null || echo false)
if [ "$L5_ENABLED" = "true" ] && [[ ! "$ARGUMENTS" =~ --skip-vision-self-verify ]]; then
  L5_BLOCKED=""
  L5_FLAGS=0
  L5_CHECKS=0
  L5_MODEL="$(vg_config_get visual_checks.vision_self_verify.model claude-haiku-4-5-20251001 2>/dev/null || echo claude-haiku-4-5-20251001)"
  L5_TIMEOUT="$(vg_config_get visual_checks.vision_self_verify.timeout_s 30 2>/dev/null || echo 30)"
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    [ -f "$plan" ] || continue
    "${PYTHON_BIN:-python3}" - "$plan" <<'PY' >> "${PHASE_DIR}/.tmp/l5-tasks.tsv" 2>/dev/null
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
def emit_for(tid, body):
    refs = []
    for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body):
        for r in re.split(r"[,\s]+", raw.strip()):
            r = r.strip()
            if r and slug_re.match(r):
                refs.append(r)
    for slug in refs:
        print(f"{tid}\t{slug}")
for m in re.finditer(r'<task\s+id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</task>', text, re.DOTALL | re.IGNORECASE):
    emit_for(m.group(1), m.group(2))
heading_re = re.compile(r'^#{2,3}\s+Task\s+(0?\d+)\b', re.IGNORECASE | re.MULTILINE)
lines = text.splitlines()
heads = [(i, m.group(1).lstrip("0") or "0") for i, line in enumerate(lines) for m in [heading_re.match(line)] if m]
for idx, (line_no, tid) in enumerate(heads):
    end = heads[idx+1][0] if idx+1 < len(heads) else len(lines)
    emit_for(tid, "\n".join(lines[line_no:end]))
PY
  done
  if [ -s "${PHASE_DIR}/.tmp/l5-tasks.tsv" ]; then
    DESIGN_DIR_REL_L5="$(vg_config_get design_assets.output_dir .vg/design-normalized 2>/dev/null || echo .vg/design-normalized)"
    while IFS=$'\t' read -r task_num slug; do
      [ -z "$task_num" ] && continue
      L5_COMMIT_SHA=$("${PYTHON_BIN:-python3}" -c "
import json, sys
try:
    d = json.load(open('${PHASE_DIR}/.build-progress.json', encoding='utf-8'))
    for c in d.get('tasks_committed', []):
        if c.get('task') == ${task_num}:
            print(c.get('commit_sha') or 'HEAD'); sys.exit(0)
    print('HEAD')
except Exception:
    print('HEAD')
" 2>/dev/null)
      L5_REPORT="${PHASE_DIR}/.tmp/l5-task-${task_num}-${slug}.json"
      "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-vision-self-verify.py \
        --phase-dir "${PHASE_DIR}" --task-num "${task_num}" --slug "${slug}" \
        --commit-sha "${L5_COMMIT_SHA}" --design-dir "${DESIGN_DIR_REL_L5}" \
        --model "${L5_MODEL}" --timeout "${L5_TIMEOUT}" \
        --output "${L5_REPORT}" >/dev/null 2>&1
      L5_CHECKS=$((L5_CHECKS + 1))
      L5_VERDICT=$("${PYTHON_BIN:-python3}" -c "import json; print(json.load(open('${L5_REPORT}')).get('verdict','SKIP'))" 2>/dev/null)
      case "$L5_VERDICT" in
        BLOCK) L5_BLOCKED="${L5_BLOCKED} task-${task_num}/${slug}" ;;
        FLAG)
          L5_FLAGS=$((L5_FLAGS + 1))
          if type -t log_override_debt >/dev/null 2>&1; then
            log_override_debt "design-fidelity-flag" "task-${task_num} slug=${slug}" "medium"
          fi
          ;;
      esac
    done < "${PHASE_DIR}/.tmp/l5-tasks.tsv"
    rm -f "${PHASE_DIR}/.tmp/l5-tasks.tsv"
  fi
  if [ -n "$L5_BLOCKED" ]; then
    echo "⛔ L5 design-fidelity guard: BLOCK verdict for:${L5_BLOCKED}"
    echo "   See per-task report: ${PHASE_DIR}/.tmp/l5-task-*.json"
    echo "   Override: --skip-vision-self-verify (logs override-debt + rationalization-guard)"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_l5_vision_guard" "${PHASE_NUMBER}" "build.9" \
        "vision_self_verify" "BLOCK" "{\"blocked\":\"${L5_BLOCKED}\"}"
    fi
    exit 1
  elif [ "${L5_CHECKS:-0}" -gt 0 ]; then
    echo "✓ L5 design-fidelity guard: ${L5_CHECKS} check(s) ran (${L5_FLAGS} FLAG, 0 BLOCK)"
  fi
fi

# ─── L6 read-evidence sentinel (P19 D-09) ─────────────────────────────────
# Strongest "prove you Read it" gate available without runtime hook
# transcript surface. Validator re-hashes every PNG declared in
# .read-evidence/task-${N}.json — fabricated sentinels with wrong sha256
# get BLOCK. Off by default until executor rule rollout.
L6_ENABLED=$(vg_config_get visual_checks.read_evidence.enabled false 2>/dev/null || echo false)
if [ "$L6_ENABLED" = "true" ] && [[ ! "$ARGUMENTS" =~ --skip-read-evidence ]]; then
  L6_BLOCKED=""
  L6_CHECKS=0
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    [ -f "$plan" ] || continue
    "${PYTHON_BIN:-python3}" - "$plan" <<'PY' >> "${PHASE_DIR}/.tmp/l6-tasks.tsv" 2>/dev/null
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
def emit_for(tid, body):
    refs = []
    for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body):
        for r in re.split(r"[,\s]+", raw.strip()):
            r = r.strip()
            if r and slug_re.match(r):
                refs.append(r)
    for slug in refs:
        print(f"{tid}\t{slug}")
for m in re.finditer(r'<task\s+id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</task>', text, re.DOTALL | re.IGNORECASE):
    emit_for(m.group(1), m.group(2))
heading_re = re.compile(r'^#{2,3}\s+Task\s+(0?\d+)\b', re.IGNORECASE | re.MULTILINE)
lines = text.splitlines()
heads = [(i, m.group(1).lstrip("0") or "0") for i, line in enumerate(lines) for m in [heading_re.match(line)] if m]
for idx, (line_no, tid) in enumerate(heads):
    end = heads[idx+1][0] if idx+1 < len(heads) else len(lines)
    emit_for(tid, "\n".join(lines[line_no:end]))
PY
  done
  if [ -s "${PHASE_DIR}/.tmp/l6-tasks.tsv" ]; then
    DESIGN_DIR_REL_L6="$(vg_config_get design_assets.output_dir .vg/design-normalized 2>/dev/null || echo .vg/design-normalized)"
    while IFS=$'\t' read -r task_num slug; do
      [ -z "$task_num" ] && continue
      L6_REPORT="${PHASE_DIR}/.tmp/l6-task-${task_num}-${slug}.json"
      "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-read-evidence.py \
        --phase-dir "${PHASE_DIR}" --task-num "${task_num}" --slug "${slug}" \
        --design-dir "${DESIGN_DIR_REL_L6}" \
        --output "${L6_REPORT}" >/dev/null 2>&1
      RC=$?
      L6_CHECKS=$((L6_CHECKS + 1))
      if [ "$RC" != "0" ]; then
        L6_BLOCKED="${L6_BLOCKED} task-${task_num}/${slug}"
      fi
    done < "${PHASE_DIR}/.tmp/l6-tasks.tsv"
    rm -f "${PHASE_DIR}/.tmp/l6-tasks.tsv"
  fi
  if [ -n "$L6_BLOCKED" ]; then
    echo "⛔ L6 read-evidence gate: sentinel missing or sha256 mismatch for:${L6_BLOCKED}"
    echo "   See per-task report: ${PHASE_DIR}/.tmp/l6-task-*.json"
    echo "   Cause: executor did not Write .read-evidence/task-N.json after Read PNG,"
    echo "          OR sentinel sha256 differs from disk (likely fabricated)."
    echo "   Override: --skip-read-evidence (logs override-debt; defeats the forcing function)"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "build_l6_read_evidence" "${PHASE_NUMBER}" "build.9" \
        "read_evidence" "BLOCK" "{\"blocked\":\"${L6_BLOCKED}\"}"
    fi
    exit 1
  elif [ "${L6_CHECKS:-0}" -gt 0 ]; then
    echo "✓ L6 read-evidence gate: ${L6_CHECKS} sentinel(s) verified, sha256 matches disk"
  fi
fi

# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "9_post_execution" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/9_post_execution.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 9_post_execution 2>/dev/null || true
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

# Final graphify refresh after all build mutations and post-execution gates.
# This closes the "first build has no graph / build ended with stale graph"
# gap: run-complete validator checks the graphify_auto_rebuild event emitted here.
if [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
  if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-final"; then
    GRAPHIFY_ACTIVE="true"
  elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
    echo "⛔ Graphify final rebuild failed and fallback_to_grep=false"
    exit 1
  else
    echo "⚠ Graphify final rebuild failed; run-complete will surface evidence"
  fi
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "10_postmortem_sanity" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/10_postmortem_sanity.done"
```

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "10_postmortem_sanity" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/10_postmortem_sanity.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 10_postmortem_sanity 2>/dev/null || true
```
</step>

<step name="11_crossai_build_verify_loop">
## Step 11: OHOK-7 MANDATORY CrossAI build verification loop

After wave execution + post-mortem, we MUST verify the build actually
completed against its 4 source-of-truth artifacts (API-CONTRACTS.md,
TEST-GOALS.md, CONTEXT.md decisions, PLAN.md tasks). This is ENFORCED
by `build-crossai-required.py` validator at run-complete — no "promise"
path; events.db evidence required.

**Flow**:

```
for iteration in 1..5:
  Run: python .claude/scripts/vg-build-crossai-loop.py \
          --phase ${PHASE_NUMBER} --iteration ${iter} --max-iterations 5

  Exit code 0 (CLEAN):
    - Both Codex + Gemini report no BLOCK findings
    - Emit build.crossai_loop_complete → BREAK out of loop
    - Build done
  Exit code 1 (BLOCKS_FOUND):
    - Read ${PHASE_DIR}/crossai-build-verify/findings-iter${iter}.json
    - Spawn Sonnet Task subagent:
      * description: "Fix CrossAI BLOCK findings iter ${iter}"
      * prompt: findings JSON + artifact paths + "fix each BLOCK, commit
                with feat(${phase}-${iter}.fixN): subject"
    - After subagent returns, continue to iter+1
  Exit code 2 (CLI_INFRA_FAILURE):
    - Retry once. If still fails, prompt user (CLI down / network / quota)

After loop:
  If cleaned before max: emit build.crossai_loop_complete (already done on
                          clean exit, just a safety)
  If 5 iterations exhausted WITHOUT clean:
    - Emit build.crossai_loop_exhausted
    - Prompt user with 3 options:
      (a) continue — run another 5 iterations
      (b) defer — proceed to /vg:review with remaining findings as known
          issues (emit build.crossai_loop_user_override)
      (c) skip + HARD debt — emit build.crossai_loop_user_override +
          vg-orchestrator override --flag=skip-crossai-build-loop
          --reason='<URL + explanation, ≥50ch>'
```

**Fix subagent model**: Sonnet (`claude-sonnet-4-6`). Sonnet is:
- Fast enough to not bloat loop runtime (~1 min per fix)
- Strong enough for contract-gap level fixes
- Isolated context so main Claude doesn't accumulate fix noise

**Severity threshold for triggering fix**: ANY BLOCK finding from either
CLI. MEDIUM/LOW findings are captured but deferred to /vg:review or
/vg:test phase (not blocking the build loop).

**Prompt template for fix subagent**:

```
You are fixing CrossAI BLOCK findings from build iteration ${N} of phase ${P}.

Read findings: ${PHASE_DIR}/crossai-build-verify/findings-iter${N}.json

For each finding with severity=BLOCK:
  1. Read the file at finding.file
  2. Understand the gap (finding.message) against the artifact ref
     (finding.artifact_ref — D-XX / G-XX / endpoint / task)
  3. Apply the minimal fix per finding.fix_hint
  4. Commit with: feat(${P}-${N}.fix${K}): <finding.artifact_ref>
     body: "Per CrossAI iter ${N} — <finding.message>"

Do NOT refactor, do NOT add features beyond the fix. Stop and return.
```

**IMPORTANT — this step is Claude-orchestrated, not bash-looped.**

Bash auto-loop was wrong: re-running CrossAI on SAME unfixed code just
re-produces the same findings. Main Claude (Opus) MUST orchestrate
iteration-by-iteration with Sonnet Task subagent fixing between iters.

```bash
# Phase 1 — iteration 1: establish baseline
CROSSAI_PHASE="${PHASE_NUMBER:-${PHASE_ARG}}"
CROSSAI_MAX_ITER=5
echo "▸ CrossAI build-verify iteration 1/${CROSSAI_MAX_ITER}..."
"${PYTHON_BIN:-python3}" .claude/scripts/vg-build-crossai-loop.py \
  --phase "${CROSSAI_PHASE}" --iteration 1 --max-iterations ${CROSSAI_MAX_ITER}
CROSSAI_RC=$?
echo "▸ iter 1 exit code: ${CROSSAI_RC} (0=CLEAN, 1=BLOCKS_FOUND, 2=INFRA_FAILURE)"
```

**Now the orchestrator (main Claude Opus) reads CROSSAI_RC and decides**:

- **CROSSAI_RC = 0**: loop script already emitted `build.crossai_loop_complete`.
  Proceed directly to step 12 (run-complete). Build done clean at iter 1.

- **CROSSAI_RC = 1**: BLOCK findings exist at
  `${PHASE_DIR}/crossai-build-verify/findings-iter1.json`.
  **Opus MUST dispatch a Sonnet Task subagent** with the findings JSON +
  fix prompt (see template above). Subagent reads each finding, applies
  minimal fix, commits with `feat(${PHASE}-1.fixN):` subject. After
  subagent returns (all BLOCKS fixed + committed), Opus re-invokes:
  ```bash
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-build-crossai-loop.py \
    --phase "${CROSSAI_PHASE}" --iteration 2 --max-iterations ${CROSSAI_MAX_ITER}
  ```
  Repeat: exit 0 → done; exit 1 → fix + iter 3; ... up to iter 5.

- **CROSSAI_RC = 2**: CLI infra failure (Codex/Gemini network/timeout/parse
  fail). Opus investigates (check `${PHASE_DIR}/crossai-build-verify/
  codex-iter*.md` + `gemini-iter*.md` for error detail). Either retry
  the same iteration after fixing infra OR escalate to user for override.

**After iter 5 without clean** — Opus MUST prompt user with 3 options:

```
━━━ ACTION REQUIRED — CrossAI loop exhausted ━━━

5 iterations ran without clean. Remaining BLOCK findings listed in
${PHASE_DIR}/crossai-build-verify/findings-iter5.json.

Pick one:
  (a) continue — spawn another Sonnet fix round + run iterations 6-10
  (b) defer — record exhausted + proceed to /vg:review with remaining
      findings as known issues. Runs:
      python .claude/scripts/vg-orchestrator emit-crossai-terminal exhausted \
        --payload '{"iterations":5,"reason":"user_deferred"}'
  (c) skip + HARD debt — requires override.used with crossai flag:
      python .claude/scripts/vg-orchestrator override \
        --flag=skip-crossai-build-loop --reason='<ticket URL or SHA ≥50ch>'
      python .claude/scripts/vg-orchestrator emit-crossai-terminal user_override
```

Opus presents options, user picks, Opus invokes the chosen command. Run-
complete (step 12) BLOCKs until ONE of the three terminal events lands.

**Why no bash while-loop**: the fix between iterations needs a Task subagent
(Sonnet with isolated context reading findings-iterN.json), which a bash
block can't spawn. Each iteration is a discrete Claude-orchestrated step.

**If Opus bypasses this step** entirely: step 12 fires
`build-crossai-required` validator which sees 0 iteration events → BLOCK.
No way to skip via "promise" — events.db evidence required (OHOK-7/8).
```

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "11_crossai_build_verify_loop" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/11_crossai_build_verify_loop.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 11_crossai_build_verify_loop 2>/dev/null || true
```
</step>

<step name="12_run_complete">
## Step 12: Run-complete (validators fire, BLOCK on violations)

```bash
# Emit final completion telemetry only after the CrossAI loop has reached an
# accepted terminal state. run-complete validates this event in the same call.
SUMMARY_COUNT=$(ls "${PHASE_DIR}"/SUMMARY*.md 2>/dev/null | wc -l | tr -d " ")
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.completed" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"summaries\":${SUMMARY_COUNT},\"after_crossai\":true}" >/dev/null

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "12_run_complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/12_run_complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_run_complete 2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ build run-complete BLOCK — review orchestrator output + fix before /vg:review" >&2
  exit $RUN_RC
fi

PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN:-python3} -c "
import json; from datetime import datetime; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
now = datetime.now().isoformat()
s['status'] = 'executed'
s['pipeline_step'] = 'build-complete'
s['updated_at'] = now
prev = s.get('steps', {}).get('build', {})
prev.update({
    'status': 'done',
    'finished_at': now,
    'reason': 'CrossAI loop and run-complete passed',
})
s.setdefault('steps', {})['build'] = prev
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* executed/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```
</step>

</process>

<context_efficiency>
Orchestrator: ~10-15% context.
Subagents: fresh context each, ~2000 lines (~30k tokens ≈ 15% of 200k budget). Modern Claude comfortable at this scale. Starving context causes drift; expand to eliminate guess.
Re-run `/vg:build {phase}` to resume — discovers plans, skips completed SUMMARYs.
</context_efficiency>
