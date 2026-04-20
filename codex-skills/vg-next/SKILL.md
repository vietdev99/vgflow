---
name: "vg-next"
description: "Auto-detect current V5 pipeline step and advance to the next"
metadata:
  short-description: "Auto-detect current V5 pipeline step and advance to the next"
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

This skill is invoked by mentioning `$vg-next`. Treat all user text after `$vg-next` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<objective>
Detect current position in the 7-step phase pipeline and immediately invoke the next command.

Pipeline order: specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="load_config">
**Config:** Read .claude/commands/vg/_shared/config-loader.md first.
</step>

<step name="detect_state">
Read `${PLANNING_DIR}/STATE.md` and `${PLANNING_DIR}/ROADMAP.md`.

Extract `current_phase` and `phase_dir`.

If `${PLANNING_DIR}/` does not exist or STATE.md is missing:
  - Output: "No VG project detected. Run /vg:project to initialize."
  - STOP.
</step>

<step name="detect_pipeline_position">
**Phase reconnaissance — recon-driven routing (replaces binary file-exists checks).**

Follow `.claude/commands/vg/_shared/phase-recon.md`.

```bash
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet

PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
NEXT_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
HAS_PRE_ACTION=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print('yes' if s['recommended_action'].get('pre_action') else 'no')
")
```

**Route 0 (priority):** `STATE.md` shows `paused_at` field
→ Read PIPELINE-STATE.json. Resume logic (tightened 2026-04-17 — field-specific):

```bash
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
if [ -f "$PIPELINE_STATE" ]; then
  # Priority 1: find first step with status == "in_progress" (explicit pause)
  RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
for st in order:
    if steps.get(st, {}).get('status') == 'in_progress':
        print(st); break
")
  # Priority 2: if no in_progress, find last step with status == "done", resume from next
  if [ -z "$RESUME_STEP" ]; then
    RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
last_done = -1
for i, st in enumerate(order):
    if steps.get(st, {}).get('status') == 'done':
        last_done = i
next_step = order[last_done + 1] if last_done + 1 < len(order) else 'complete'
print(next_step)
")
  fi
else
  RESUME_STEP="scope"  # no state, start from beginning
fi

echo "Resume from: /vg:${RESUME_STEP} {phase}"
```

→ Next: `/vg:${RESUME_STEP} {phase}`

**⛔ Deferred-incomplete gate (tightened 2026-04-17):**

Before advancing to a NEW phase, check current phase for `.deferred-incomplete` marker:

```bash
CURRENT_PHASE_DIR="${PHASE_DIR}"  # from recon
if [ -f "${CURRENT_PHASE_DIR}/.deferred-incomplete" ]; then
  if [[ ! "$ARGUMENTS" =~ --allow-deferred ]]; then
    echo "⛔ Phase ${PHASE_NUMBER} is DEFERRED-INCOMPLETE — cannot advance."
    echo "   Open items in ${CURRENT_PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
    echo "   Resolve with: /vg:accept ${PHASE_NUMBER} --resume"
    echo "   Force advance (creates tech debt): /vg:next --allow-deferred"
    exit 1
  else
    echo "⚠ --allow-deferred set — advancing with ${PHASE_NUMBER} still deferred. Tech debt recorded."
    echo "next-advance-with-deferred: ${PHASE_NUMBER} ts=$(date -u +%FT%TZ)" >> ${PLANNING_DIR}/deferred-debt.log
  fi
fi
```

**Route 0b (legacy/hybrid):** `HAS_PRE_ACTION == "yes"` (recon found legacy artifacts)
→ Display: "Phase {N} has legacy GSD artifacts — run `/vg:migrate {N}` to convert to VG format."
→ Show what's missing: API-CONTRACTS.md, TEST-GOALS.md, enriched CONTEXT.md
→ Do NOT auto-invoke migration. `/vg:next` is fast — migrations require interactive approval via `/vg:migrate`.

**Route 0c (semantic enrichment gap, v1.14.0+):** Phase already migrated (no GSD legacy files) BUT TEST-GOALS missing v1.14.0 semantic fields (Persistence check, Surface classification, Plan-Goal linkage).

```bash
VERIFY_SCRIPT=""
[ -f "${REPO_ROOT}/.claude/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
[ -f "${REPO_ROOT}/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"

if [ -n "$VERIFY_SCRIPT" ] && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  SEMANTIC_JSON=$(${PYTHON_BIN:-python3} "$VERIFY_SCRIPT" --json "$PHASE_DIR" 2>/dev/null)
  FAIL_GATES=$(echo "$SEMANTIC_JSON" | ${PYTHON_BIN:-python3} -c "import sys,json; d=json.loads(sys.stdin.read()); print(','.join(r['name'] for r in d.get('results',[]) if r.get('status')=='FAIL'))" 2>/dev/null)
  if [ -n "$FAIL_GATES" ]; then
    echo "⚠ Phase ${PHASE_NUMBER}: v1.14.0 semantic gaps detected — ${FAIL_GATES}"
    echo "  Re-run /vg:migrate ${PHASE_NUMBER} --force để enrich (preserves existing decisions/goals)."
    echo "  Skip để continue pipeline với debt — but blueprint/build sẽ block khi gặp Rule 3b/Surface gates."
  fi
fi
```

Display only — không block. User decision: re-migrate (recommended) hay skip.

**Recon routes** (derived from `NEXT_STEP`):
- `NEXT_STEP == "scope"` → Next: `/vg:scope {phase}`
- `NEXT_STEP == "blueprint"` → Next: `/vg:blueprint {phase}`
- `NEXT_STEP == "build"` → Next: `/vg:build {phase}`
- `NEXT_STEP == "review"` → Next: `/vg:review {phase}` (see Cross-CLI option below)
- `NEXT_STEP == "test"` → Next: `/vg:test {phase}`
- `NEXT_STEP == "accept"` → Next: `/vg:accept {phase}`
- `NEXT_STEP == "complete"` → Phase done (check Route 8/9)

**Review cross-CLI option** (only when NEXT_STEP == "review"):
Display cross-CLI option:
→ Display cross-CLI option:
```
  **Review options:**
  A) Standard:  `/vg:review {phase}` — Claude does full review (discovery + evaluate + fix)
  B) Cross-CLI: Split work across AI CLIs for lower cost:
     1. Codex:  `$vg-review {phase} --discovery-only`  — Codex does discovery (cheap, has MCP browser)
     2. Claude: `/vg:review {phase} --evaluate-only`   — Claude reads scan results, evaluates + fixes
     
     Or Gemini: `/vg-review {phase} --discovery-only`  — same flow, Gemini does discovery
  
  Option B saves ~60-70% tokens on Claude (no browser interaction).
  
  Flag: add `--full-scan` to disable snapshot pruning (default: pruning ON, saves 50-70% tokens).
  Use --full-scan only when app has non-standard layout or no <main> selector.
```

**Route 5b:** `RUNTIME-MAP.json` exists + `GOAL-COVERAGE-MATRIX.md` exists + gate = BLOCK (goals < 100%)
→ Review ran but goals not met. Auto-detect cause from artifacts:

```
Read discovery-state.json → completed_phase field
Read GOAL-COVERAGE-MATRIX.md → goal statuses (READY / BLOCKED / UNREACHABLE / FAILED)
Read RUNTIME-MAP.json → goal_sequences[goal_id].start_view for each failed goal

SIGNAL 1 — discovery-state.json.completed_phase ≠ "investigate":
  → Review was INTERRUPTED (token exhaustion / session died mid-scan)
  → Auto-invoke: /vg:review {phase} --resume
  → No user choice needed.

SIGNAL 2 — completed_phase == "investigate" (review fully completed):
  Classify failed goals (4 distinct statuses — verify code presence before assuming):
    UNREACHABLE = goal has no start_view AND code for page/route NOT found in repo
                  (feature genuinely not built — grep config.code_patterns returns nothing)
    NOT_SCANNED = goal has no start_view BUT code for page/route DOES exist
                  (review didn't replay — multi-step wizard, orphan route, timeout, retry-scope miss)
    BLOCKED/FAILED = goal has start_view but result=failed
                     (view found, scan ran, criteria not met → code bug)
```

**Display to user (explain, then action):**

```
⚠ Phase {N} gate BLOCKED — {X}/{total} goals failed.

┌─ What the failure types mean ─────────────────────────────────┐
│ UNREACHABLE ({N})  Code for page/route NOT in repo (verified) │
│                    → Feature not built yet                    │
│                    → Fix: /vg:build {phase} --gaps-only       │
│                                                               │
│ NOT_SCANNED ({N})  Code EXISTS but review didn't replay       │
│                    (multi-step wizard/mutation, orphan route, │
│                     Haiku timeout, retry scope missed goal)   │
│                    → Fix: /vg:test {phase} (codegen walks)    │
│                         or --retry-failed (re-scan only)      │
│                                                               │
│ BLOCKED ({N})      View found, but goal criteria not met      │
│                    (form didn't submit, API error, etc.)      │
│                    → Code has a bug — fix and re-scan         │
│                                                               │
│ INTERRUPTED        Review died mid-scan (token/timeout)       │
│                    → Just resume where it left off            │
└───────────────────────────────────────────────────────────────┘

Failed goals:
  [UNREACHABLE] {goal_id}: {goal_desc}
  [NOT_SCANNED] {goal_id}: {goal_desc} (code: {path/to/page.tsx})
  [BLOCKED]     {goal_id}: {goal_desc} (view: {start_view})
  ...
```

**Then route by classification:**

```
IF all UNREACHABLE (code confirmed missing):
  → Auto-invoke: /vg:build {phase} --gaps-only
  Print: "All failures UNREACHABLE — feature missing. Auto-building gaps..."
  After build completes → re-run /vg:review {phase}

IF all NOT_SCANNED (code exists, review skipped):
  Print: "All failures NOT_SCANNED — code built but review didn't replay."
  Display (do NOT auto-invoke — user picks based on root cause):
    Common cause 1: Multi-step wizard/mutation needs dedicated browser session
      → /vg:test {phase}
        (codegen + Playwright auto-walks wizard, fills all steps, verifies goal)
    Common cause 2: Timeout or retry-scope missed the goal
      → /vg:review {phase} --retry-failed
        (fresh re-scan of only failed views)
    DO NOT run /vg:build --gaps-only — code already exists.

IF all BLOCKED (code bugs — user fix required first):
  Print: "All failures BLOCKED — code bugs in {N} views. Workflow:"
  Display (do NOT auto-invoke):
    Step 1: Fix the code (inspect logs/network errors in GOAL-COVERAGE-MATRIX.md)
    Step 2: Re-scan ONLY failed views: /vg:review {phase} --retry-failed
            (~5-10x faster than full review — skips passed views)
    Cross-CLI option: $vg-review {phase} --retry-failed --discovery-only
                    → /vg:review {phase} --evaluate-only

IF mix (any combination):
  Print: "Mixed failures — handle in order:"
  Display (do NOT auto-invoke):
    Step 1: /vg:build {phase} --gaps-only       ← if UNREACHABLE exists, build first
    Step 2: Fix code for BLOCKED goals (list shown above)
    Step 3: /vg:test {phase}                     ← if NOT_SCANNED exists (codegen for complex flows)
    Step 4: /vg:review {phase} --retry-failed   ← re-verify everything
```

**Route 6:** `RUNTIME-MAP.json` + `RUNTIME-MAP.md` exist + GOAL-COVERAGE-MATRIX gate = PASS + no `*-SANDBOX-TEST.md`
→ Next: `/vg:test {phase}`
Note: RUNTIME-MAP.json is the canonical artifact — .md alone is NOT sufficient for /vg:test.

**Route 7:** `*-SANDBOX-TEST.md` exists but no `*-UAT.md` OR UAT status != "complete"
→ Next: `/vg:accept {phase}`

**Route 8:** UAT complete AND next phase exists in ROADMAP.md AND next phase has NO `SPECS.md`
→ Next: `/vg:specs {next_phase}`

**Route 8b:** UAT complete AND next phase has `SPECS.md` but NO `CONTEXT.md`
→ Next: `/vg:scope {next_phase}`

**Route 9:** All phases complete
→ Next: `/vg:project --milestone` (milestone wrap-up — VG-native)
</step>

<step name="show_and_execute">
Display current status with artifact checklist, then IMMEDIATELY invoke.

```
## VG Next (V6)

**Current:** Phase {N} — {name}
**Phase type:** {PHASE_TYPE} (from recon)
**Pipeline position (from .recon-state.json):**
  scope:     {status} {v6_artifacts}
  blueprint: {status} {v6_artifacts}
  build:     {status} {v6_artifacts}
  review:    {status} {v6_artifacts}
  test:      {status} {v6_artifacts}
  accept:    {status} {v6_artifacts}

▶ **Next step:** `/vg:{NEXT_STEP} {phase}`
  {recommended_action.reason from recon}
```

Pipeline position is read from `.recon-state.json` (per-step status: done|partial|missing|legacy_only).
IMMEDIATELY invoke the next command. No confirmation prompt (except legacy migration which redirects to /vg:phase).
</step>

</process>

<success_criteria>
- Config loaded
- State detected from files
- Pipeline position determined
- Status displayed with V5 artifact checklist
- Next command invoked immediately
</success_criteria>
