---
name: "vg-gate-stats"
description: "Gate telemetry query surface — counts by gate_id/outcome, filter by --gate-id/--since/--outcome, flags high-override gates"
metadata:
  short-description: "Gate telemetry query surface — counts by gate_id/outcome, filter by --gate-id/--since/--outcome, flags high-override gates"
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

This skill is invoked by mentioning `$vg-gate-stats`. Treat all user text after `$vg-gate-stats` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `gate (cổng)`, `override (bỏ qua)`, `outcome (kết quả)`, `telemetry (đo đạc)`, `milestone (mốc)`, `threshold (ngưỡng)`, `event (sự kiện)`. Không áp dụng: file path, code ID, outcome ID (PASS/FAIL/OVERRIDE).
</NARRATION_POLICY>

<rules>
1. **Read-only** — queries telemetry JSONL only. No writes.
2. **Delegate to `telemetry_query` + `telemetry_warn_overrides`** — no reimplementation of event parsing.
3. **Filters** — `--gate-id=X`, `--since=ISO8601`, `--outcome=PASS|FAIL|OVERRIDE|SKIP|BLOCK|WARN`. Unfiltered = all events.
4. **Flag high-override gates** — threshold from `CONFIG_OVERRIDE_WARN_THRESHOLD` (default 2).
5. **Single `gate_stats_run` event** per invocation.
</rules>

<objective>
Answer: "Which gates fire most often? Which are being overridden too much?"

Produces a sorted table by total event volume, with per-outcome breakdown. Surfaces gates exceeding override threshold as remediation targets.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse filters + load helpers

```bash
PLANNING_DIR=".vg"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || {
  echo "⛔ telemetry.sh missing — cannot query" >&2
  exit 1
}

FILTER_GATE=""
FILTER_SINCE=""
FILTER_OUTCOME=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --gate-id=*) FILTER_GATE="${arg#--gate-id=}" ;;
    --since=*)   FILTER_SINCE="${arg#--since=}" ;;
    --outcome=*) FILTER_OUTCOME="${arg#--outcome=}" ;;
    --*)         echo "⚠ Unknown flag: $arg" ;;
    *)           echo "⚠ Positional arg ignored: $arg (use --gate-id=)" ;;
  esac
done

export VG_CURRENT_COMMAND="vg:gate-stats"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "📊 ━━━ /vg:gate-stats ━━━"
[ -n "$FILTER_GATE" ]    && echo "  Filter gate-id: ${FILTER_GATE}"
[ -n "$FILTER_SINCE" ]   && echo "  Filter since:   ${FILTER_SINCE}"
[ -n "$FILTER_OUTCOME" ] && echo "  Filter outcome: ${FILTER_OUTCOME}"
echo ""

if [ ! -f "$TELEMETRY_PATH" ]; then
  echo "  (no telemetry yet — run some VG commands first)"
  exit 0
fi
```
</step>

<step name="1_aggregate">
## Step 1: Aggregate events into per-gate × per-outcome counts

```bash
# Use telemetry_query when filters apply (it handles them); else stream raw file.
if type telemetry_query >/dev/null 2>&1 && { [ -n "$FILTER_GATE" ] || [ -n "$FILTER_SINCE" ] || [ -n "$FILTER_OUTCOME" ]; }; then
  QUERY_ARGS=()
  [ -n "$FILTER_GATE" ]    && QUERY_ARGS+=("--gate-id=${FILTER_GATE}")
  [ -n "$FILTER_SINCE" ]   && QUERY_ARGS+=("--since=${FILTER_SINCE}")
  [ -n "$FILTER_OUTCOME" ] && QUERY_ARGS+=("--outcome=${FILTER_OUTCOME}")
  STREAM_CMD=("telemetry_query" "${QUERY_ARGS[@]}")
  "${STREAM_CMD[@]}" > /tmp/vg-gate-stats.jsonl
  INPUT="/tmp/vg-gate-stats.jsonl"
else
  INPUT="$TELEMETRY_PATH"
fi

${PYTHON_BIN} - "$INPUT" <<'PY'
import json, sys
from collections import defaultdict
path = sys.argv[1]
counts = defaultdict(lambda: defaultdict(int))
try:
  for line in open(path, encoding='utf-8'):
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      gid = ev.get("gate_id")
      outc = ev.get("outcome")
      if gid and outc in ("PASS", "FAIL", "SKIP", "OVERRIDE", "BLOCK", "WARN"):
          counts[gid][outc] += 1
    except: pass
except FileNotFoundError:
  pass

if not counts:
  print("  (no gate events match filter)")
  sys.exit(0)

totals = {g: sum(oc.values()) for g, oc in counts.items()}
sorted_gates = sorted(counts.keys(), key=lambda g: -totals[g])

print("## Gate event counts")
print()
print("  | Gate | PASS | FAIL | BLOCK | OVERRIDE | SKIP | WARN | Total |")
print("  |------|------|------|-------|----------|------|------|-------|")
for g in sorted_gates:
    oc = counts[g]
    print(f"  | {g} | {oc.get('PASS',0)} | {oc.get('FAIL',0)} | {oc.get('BLOCK',0)} | {oc.get('OVERRIDE',0)} | {oc.get('SKIP',0)} | {oc.get('WARN',0)} | {totals[g]} |")
print()
PY
```
</step>

<step name="2_override_warn">
## Step 2: Surface high-override gates

```bash
echo "## High-override gates (bỏ qua nhiều)"
echo ""
THRESHOLD="${CONFIG_OVERRIDE_WARN_THRESHOLD:-2}"
if type telemetry_warn_overrides >/dev/null 2>&1; then
  telemetry_warn_overrides "$THRESHOLD" || echo "   (no gates exceed threshold ${THRESHOLD})"
else
  echo "   (telemetry_warn_overrides unavailable)"
fi
echo ""

echo "## Recommendations"
echo "   • If a gate is being overridden too often → investigate:"
echo "     - Is the gate threshold too strict?"
echo "     - Is the agent rationalizing past valid concerns?"
echo "     - Review ${PLANNING_DIR}/OVERRIDE-DEBT.md entries for that gate."
echo "   • Drill into a specific gate:  /vg:gate-stats --gate-id=X"
echo "   • Scope to recent window:      /vg:gate-stats --since=2026-04-01"
echo ""
```
</step>

<step name="3_telemetry">
## Step 3: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  payload="{\"filter_gate\":\"${FILTER_GATE}\",\"filter_since\":\"${FILTER_SINCE}\",\"filter_outcome\":\"${FILTER_OUTCOME}\"}"
  emit_telemetry_v2 "gate_stats_run" "project" "gate-stats" "" "PASS" "$payload" >/dev/null 2>&1 || true
fi
rm -f /tmp/vg-gate-stats.jsonl 2>/dev/null || true
```
</step>

</process>

<success_criteria>
- Pure read — no writes to telemetry or registers.
- Filters pass through to `telemetry_query` helper.
- Output = sorted table + override-pressure section + actionable drill-down hints.
- Single `gate_stats_run` telemetry event.
</success_criteria>
</content>
</invoke>
