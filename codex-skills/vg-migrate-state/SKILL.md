---
name: "vg-migrate-state"
description: "Detect + backfill phase state drift (missing step markers) after VG harness upgrades"
metadata:
  short-description: "Detect + backfill phase state drift (missing step markers) after VG harness upgrades"
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

This skill is invoked by mentioning `$vg-migrate-state`. Treat all user text after `$vg-migrate-state` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<objective>
Repair phase state drift introduced by VG harness upgrades. When a skill
adds new `<step>` blocks (or wires `mark-step` where it wasn't wired
before), phases that already ran the OLD skill miss the new markers.
`/vg:accept` then BLOCKs even though the pipeline actually ran end-to-end.

This command detects + backfills missing markers based on artifact
evidence (PLAN.md, REVIEW-FEEDBACK.md, SANDBOX-TEST.md, etc.). Idempotent.
Companion to Tier B (`.contract-pins.json` written at `/vg:scope`) which
prevents future drift; this command repairs legacy phases that pre-date
the pin mechanism.

Drift is detected per (phase, command) pair:
- Read step list from `.claude/commands/vg/{cmd}.md`
- Check artifact evidence (e.g. PLAN.md proves `/vg:blueprint` ran)
- If evidence present + markers missing → drift candidate
- If no evidence → skip (don't fabricate markers for commands that never ran)
</objective>

<process>

<step name="0_session_lifecycle">
Standard session banner + EXIT trap. No state mutation.

```bash
PHASE_NUMBER="${PHASE_NUMBER:-migrate-state}"
mkdir -p ".vg/.tmp"
```
</step>

<step name="1_parse_args">
Parse positional + flag arguments.

```bash
PHASE_ARG=""
SCAN=0
APPLY_ALL=0
DRY_RUN=0
JSON=0
for arg in $ARGUMENTS; do
  case "$arg" in
    --scan)        SCAN=1 ;;
    --apply-all)   APPLY_ALL=1 ;;
    --dry-run)     DRY_RUN=1 ;;
    --json)        JSON=1 ;;
    --*)           echo "⛔ Unknown flag: $arg" >&2; exit 2 ;;
    *)             PHASE_ARG="$arg" ;;
  esac
done

# Default: --scan if no positional + no apply-all
if [ -z "$PHASE_ARG" ] && [ $APPLY_ALL -eq 0 ] && [ $SCAN -eq 0 ]; then
  SCAN=1
fi
```
</step>

<step name="2_run_migrate">
Delegate to `migrate-state.py`. Script handles scan/apply/dry-run logic.

```bash
ARGS=()
[ -n "$PHASE_ARG" ] && ARGS+=("$PHASE_ARG")
[ $SCAN -eq 1 ]      && ARGS+=("--scan")
[ $APPLY_ALL -eq 1 ] && ARGS+=("--apply-all")
[ $DRY_RUN -eq 1 ]   && ARGS+=("--dry-run")
[ $JSON -eq 1 ]      && ARGS+=("--json")

"${PYTHON_BIN:-python3}" .claude/scripts/migrate-state.py "${ARGS[@]}"
RC=$?

# Emit telemetry
EVENT_TYPE="migrate_state.scanned"
[ $APPLY_ALL -eq 1 ] || ([ -n "$PHASE_ARG" ] && [ $DRY_RUN -eq 0 ]) && \
  EVENT_TYPE="migrate_state.applied"

PAYLOAD=$(printf '{"phase":"%s","mode":"%s","exit":%d}' \
  "${PHASE_ARG:-all}" \
  "$([ $DRY_RUN -eq 1 ] && echo dry-run || echo apply)" \
  "$RC")
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "$EVENT_TYPE" --payload "$PAYLOAD" >/dev/null 2>&1 || true
```

Exit codes:
- 0 → no drift OR migration applied successfully
- 1 → drift detected (--scan/--dry-run only)
- 2 → invalid args / phase not found / IO error
</step>

<step name="3_complete">
Self-mark final step.

```bash
mkdir -p ".vg/.step-markers/migrate-state" 2>/dev/null
touch ".vg/.step-markers/migrate-state/3_complete.done"
```
</step>

</process>

<success_criteria>
- `--scan` produces a project-wide drift table without writing anything
- `--apply` (or `{phase}` shorthand) backfills missing markers based on artifact evidence
- Single OD entry per applied phase (not per marker — prevents register bloat)
- Idempotent: re-running on a sync'd phase prints "no drift" + zero new OD entries
- `--dry-run` reports what would be backfilled without writing
- Phases without artifact evidence for a command are skipped (no fabricated markers)
</success_criteria>

<usage_examples>

**See project-wide drift before deciding what to fix:**
```
/vg:migrate-state --scan
```
Output: phase × (ran-commands, skipped, missing-markers) table.

**Preview what one phase would change:**
```
/vg:migrate-state 7.14.3 --dry-run
```

**Fix one phase + log audit trail:**
```
/vg:migrate-state 7.14.3
```

**Batch fix every phase with drift:**
```
/vg:migrate-state --apply-all
```

**Pipe machine-readable scan into other tooling:**
```
/vg:migrate-state --scan --json | jq '.scan[] | select(.totals.missing_markers > 0).phase'
```

</usage_examples>

<related>
- `marker-migrate.py` — one-time legacy fix for empty marker files (different drift class)
- `verify-step-markers.py` — gate that detects drift at `/vg:accept` time
- `.vg/OVERRIDE-DEBT.md` — schema-versioned audit trail
- Tier B (`/vg:scope` writes `.contract-pins.json`) — prevents future drift
</related>
