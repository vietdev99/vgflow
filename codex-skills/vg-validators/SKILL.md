---
name: "vg-validators"
description: "Query the validator registry — list catalog, check drift, manage enable/disable status."
metadata:
  short-description: "Query the validator registry — list catalog, check drift, manage enable/disable status."
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

This skill is invoked by mentioning `$vg-validators`. Treat all user text after `$vg-validators` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<objective>
Phase S surface for the validator registry. Read-only queries over
`.claude/scripts/validators/registry.yaml` + drift metrics from
`.vg/state/events.db`.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

## Subcommands

### `/vg:validators list [--domain X] [--severity Y]`

Print validator catalog.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list --domain security
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list --severity block
```

### `/vg:validators describe <id>`

Show full registry entry for one validator.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py describe artifact-freshness
```

### `/vg:validators missing`

List validators on disk not in registry (indicates audit gap).

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py missing
```

Non-zero exit if any found.

### `/vg:validators orphans`

List registry entries whose backing file doesn't exist (stale entries).

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py orphans
```

### `/vg:validators drift [--lookback-days N] [--min-runs N]`

Detect validators with drift patterns over the lookback window:
- `never_fires` — registry-active but 0 runs → dead or mis-wired
- `always_pass` — 100% pass rate → likely too permissive
- `high_block_rate` — 80%+ block/fail → candidate false-positive pattern
- `perf_regression` — p95 runtime > 2x registry target → performance issue

```bash
${PYTHON_BIN:-python3} .claude/scripts/validators/verify-validator-drift.py \
  --lookback-days 30 --min-runs 10
```

### `/vg:validators validate`

Schema check the registry YAML itself.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py validate
```

### `/vg:validators disable <id> --reason "..." [--until YYYY-MM-DD]`

Mark a validator disabled (ops action). Rubber-stamp detection applies
via Phase O `allow_flag_gate.py` — requires human TTY or env approver
if this command writes to registry.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py disable \
  log-hygiene --reason "false positives on proxy middleware" --until 2026-06-01
```

## Notes

- Runtime metrics come from `events.db` table `events` with
  `event_type LIKE 'validator.%'` + JSON payload containing
  `{validator, verdict, duration_ms}`.
- Validators emit these events via `_common.py` `emit_and_exit` helper
  (automatic — no per-script wiring needed).
- Drift output is advisory — ops team runs weekly to catch patterns.
- Registry is the source of truth for validator catalog; `missing` +
  `orphans` close the audit surface.

</process>

<success_criteria>
- List/describe/missing/orphans/validate return within 2s
- Drift completes within 10s for 30-day window
- Disable/enable persist to registry.yaml (preserves YAML formatting)
- All commands support `--json` for machine output
- `observation_only` contract exempts from Phase J must_emit_telemetry
</success_criteria>
