---
name: "vg-integrity"
description: "Artifact manifest integrity sweep — hash-validates every phase artifact, reports CORRUPT/MISSING/VALID per phase"
metadata:
  short-description: "Artifact manifest integrity sweep — hash-validates every phase artifact, reports CORRUPT/MISSING/VALID per phase"
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

This skill is invoked by mentioning `$vg-integrity`. Treat all user text after `$vg-integrity` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `manifest (kê khai)`, `integrity (toàn vẹn)`, `corruption (hư hỏng)`, `hash mismatch (lệch băm)`, `artifact (tạo phẩm)`, `sweep (quét)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Read-only** — sweep compares file hashes against `.artifact-manifest.json`. Never repairs. Recovery belongs in `/vg:recover`.
2. **Delegates to `artifact_manifest_validate`** — no reimplementation.
3. **No-arg = all phases. `{phase}` arg = that phase only.**
4. **Graceful** — missing manifest = LEGACY (WARN), not corruption. Exit 1 only on bad args.
5. **Emit single `integrity_run` event** per invocation.
</rules>

<objective>
Answer: "Are any artifacts corrupted or missing on disk?"

Produces a 3-bucket report (VALID / LEGACY / CORRUPT) per phase. Each CORRUPT row points at `/vg:recover {phase}` for remediation.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse + load helpers

```bash
PLANNING_DIR=".vg"
PHASES_DIR="${PLANNING_DIR}/phases"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || {
  echo "⛔ artifact-manifest.sh missing — cannot run integrity sweep" >&2
  exit 1
}
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || true

PHASE_ARG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --*) echo "⚠ Unknown flag: $arg" ;;
    *)   PHASE_ARG="$arg" ;;
  esac
done

export VG_CURRENT_COMMAND="vg:integrity"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
if [ -n "$PHASE_ARG" ]; then
  echo "🔍 ━━━ /vg:integrity — phase ${PHASE_ARG} ━━━"
else
  echo "🔍 ━━━ /vg:integrity — all phases ━━━"
fi
echo ""
```
</step>

<step name="1_select_phases">
## Step 1: Select phase list to sweep

```bash
TARGET_PHASES=()
if [ -n "$PHASE_ARG" ]; then
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      TARGET_PHASES+=("$d"); break
    fi
  done
  if [ ${#TARGET_PHASES[@]} -eq 0 ]; then
    echo "⛔ Phase ${PHASE_ARG} not found under ${PHASES_DIR}"
    exit 1
  fi
else
  while IFS= read -r d; do
    [ -d "$d" ] && TARGET_PHASES+=("$d")
  done < <(find "$PHASES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
fi

if [ ${#TARGET_PHASES[@]} -eq 0 ]; then
  echo "⚠ No phases to sweep. Run /vg:roadmap."
  exit 0
fi
```
</step>

<step name="2_sweep">
## Step 2: Sweep loop

```bash
total=0; valid=0; legacy=0; corrupt=0
issues=()

echo "## Sweep results"
echo ""
echo "| Phase | Status | Detail |"
echo "|-------|--------|--------|"

for phase_dir in "${TARGET_PHASES[@]}"; do
  total=$((total + 1))
  phase_name=$(basename "$phase_dir")
  phase_num=$(echo "$phase_name" | grep -oE '^[0-9.]+')

  output=$(artifact_manifest_validate "$phase_dir" 2>&1)
  rc=$?
  case $rc in
    0)
      valid=$((valid + 1))
      printf "| %s | ✓ VALID | all artifacts match manifest |\n" "$phase_num"
      ;;
    1)
      legacy=$((legacy + 1))
      printf "| %s | ⚠ LEGACY | no manifest (auto-backfill on next read) |\n" "$phase_num"
      ;;
    2)
      corrupt=$((corrupt + 1))
      first_line=$(echo "$output" | head -1 | sed 's/|/ /g')
      printf "| %s | ⛔ CORRUPT | %s |\n" "$phase_num" "$first_line"
      issues+=("${phase_num}|${output}")
      ;;
    *)
      printf "| %s | ? unknown rc=%d | %s |\n" "$phase_num" "$rc" "$output"
      ;;
  esac
done
echo ""

echo "## Totals"
echo "   Total:    ${total}"
echo "   ✓ Valid:   ${valid}"
echo "   ⚠ Legacy:  ${legacy}  (auto-backfills — no action needed)"
echo "   ⛔ Corrupt: ${corrupt}"
echo ""
```
</step>

<step name="3_corruption_detail">
## Step 3: Corruption detail + recovery pointer

```bash
if [ "$corrupt" -gt 0 ]; then
  echo "## Corruption details"
  echo ""
  for entry in "${issues[@]}"; do
    phase="${entry%%|*}"
    detail="${entry#*|}"
    echo "### Phase ${phase}"
    echo "$detail" | sed 's/^/  /'
    echo ""
    echo "  **Recovery:** /vg:recover ${phase}"
    echo ""
  done
else
  echo "🎉 No corruption detected."
  echo ""
fi
```
</step>

<step name="4_telemetry">
## Step 4: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "integrity_run" "${PHASE_ARG:-project}" "integrity.sweep" \
    "" "PASS" "{\"total\":${total},\"valid\":${valid},\"legacy\":${legacy},\"corrupt\":${corrupt}}" \
    >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Read-only; no repair attempt.
- Uses `artifact_manifest_validate` for all checks.
- Output = 3-bucket table + corruption detail + recovery pointer.
- Single `integrity_run` telemetry event.
</success_criteria>
</content>
</invoke>
