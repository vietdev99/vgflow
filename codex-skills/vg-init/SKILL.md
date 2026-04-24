---
name: "vg-init"
description: "[DEPRECATED — soft alias] Re-derive vg.config.md from existing FOUNDATION.md. Equivalent to /vg:project --init-only."
metadata:
  short-description: "[DEPRECATED — soft alias] Re-derive vg.config.md from existing FOUNDATION.md. Equivalent to /vg:project --init-only."
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

This skill is invoked by mentioning `$vg-init`. Treat all user text after `$vg-init` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **Soft alias** — `/vg:init` is preserved for backward compatibility but redirects to `/vg:project --init-only` (or `/vg:project` for first-time / `/vg:project --migrate` for legacy).
2. **No discussion** — this command never asks foundation questions. For first-time setup or foundation discussion, use `/vg:project`.
3. **FOUNDATION.md required** for redirect to `--init-only`. If missing → suggest `/vg:project` or `/vg:project --migrate`.
</rules>

<objective>
Backward-compat alias for users who learned the old workflow (`/vg:init` first). Auto-detects state and points to correct `/vg:project` invocation.

**Migration note (v1.6.0+):** `/vg:init` no longer creates `vg.config.md` from scratch. Foundation discussion moved to `/vg:project`. Config is now derived from foundation, not the other way around.
</objective>

<process>

<step name="0_alias_redirect">
## Soft alias execution

```bash
PLANNING_DIR=".vg"
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
PROJECT_FILE="${PLANNING_DIR}/PROJECT.md"

echo ""
echo "ℹ  /vg:init is now a soft alias (v1.6.0+)."
echo "   Foundation discussion moved to /vg:project — see CLAUDE.md VG Pipeline."
echo ""

if [ ! -f "$FOUNDATION_FILE" ] && [ ! -f "$PROJECT_FILE" ]; then
  echo "⛔ No PROJECT.md or FOUNDATION.md detected (first-time setup)."
  echo ""
  echo "Run instead:"
  echo "  /vg:project              ← first-time 7-round discussion"
  echo "  /vg:project @brief.md    ← parse from a brief document"
  echo ""
  echo "These will create PROJECT.md + FOUNDATION.md + vg.config.md atomically."
  exit 0
fi

if [ -f "$PROJECT_FILE" ] && [ ! -f "$FOUNDATION_FILE" ]; then
  echo "⚠ PROJECT.md exists but FOUNDATION.md missing (legacy v1 format)."
  echo ""
  echo "Run instead:"
  echo "  /vg:project --migrate    ← extract FOUNDATION.md from existing PROJECT.md + codebase"
  echo ""
  echo "After migration, /vg:init will redirect to --init-only as expected."
  exit 0
fi

# FOUNDATION.md exists → confirm + redirect
echo "✓ FOUNDATION.md found."
echo ""
```

Use AskUserQuestion:
```
"Re-derive vg.config.md from FOUNDATION.md?
 (No discussion, no foundation changes — chỉ refresh config.)

 [y] Yes — run /vg:project --init-only ngay
 [n] No — exit (run /vg:project --init-only manually later)"
```

If [y] → emit text "Redirecting to /vg:project --init-only..." and **invoke `/vg:project --init-only` as next action in same session**.

If [n] → exit with reminder text.
</step>

</process>

## Why this changed (v1.6.0 migration note)

Previously `/vg:init` was the entry point — it asked many config questions before the project was even defined (chicken-and-egg: config requires knowing the tech stack, but tech stack requires deciding the project).

In v1.6.0, the entry point is `/vg:project`. It captures project description, derives foundation (8 dimensions: platform/runtime/data/auth/hosting/distribution/scale/compliance), and **auto-generates `vg.config.md` from foundation** as a final step. Config is downstream of foundation, not upstream.

`/vg:init` is preserved as a soft alias for users with muscle memory. State-based redirect:

| State | `/vg:init` action |
|-------|-------------------|
| No artifacts | Suggest `/vg:project` (first-time) |
| PROJECT.md only (legacy) | Suggest `/vg:project --migrate` |
| Foundation present | Confirm + redirect to `/vg:project --init-only` |

## Success criteria

- `/vg:init` never crashes regardless of project state
- Always points user to correct `/vg:project` invocation
- Never overwrites artifacts — purely advisory + redirect
- Auto-chain into `/vg:project --init-only` if user confirms (foundation present)
