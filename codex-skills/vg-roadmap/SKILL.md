---
name: "vg-roadmap"
description: "Derive phases from PROJECT.md requirements — group, order, estimate, write ROADMAP.md"
metadata:
  short-description: "Derive phases from PROJECT.md requirements — group, order, estimate, write ROADMAP.md"
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

This skill is invoked by mentioning `$vg-roadmap`. Treat all user text after `$vg-roadmap` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **Requirements-first** — every phase MUST trace back to REQ-IDs from REQUIREMENTS.md.
4. **Dependency-aware** — detect and declare inter-phase dependencies explicitly.
5. **User controls grouping** — AI proposes, user adjusts via AskUserQuestion.
6. **Idempotent with --from-existing** — parse existing ROADMAP.md, only add phases for unmapped requirements.
</rules>

<objective>
Derive a phased roadmap from PROJECT.md requirements. Groups related requirements into phases, detects dependencies, estimates relative size, and writes ROADMAP.md.

Output: `${PLANNING_DIR}/ROADMAP.md` + phase directories created

Pipeline: project → **roadmap** → map → prioritize → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
## Step 0: Load Config

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

```bash
# Parse flags
FROM_EXISTING=false
for arg in $ARGUMENTS; do
  case "$arg" in
    --from-existing) FROM_EXISTING=true ;;
  esac
done

ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
PROJECT_FILE="${PLANNING_DIR}/PROJECT.md"
REQUIREMENTS_FILE="${PLANNING_DIR}/REQUIREMENTS.md"
```
</step>

<step name="1_validate_inputs">
## Step 1: Validate Inputs

**Check prerequisites:**

1. Read `${PROJECT_FILE}` — MUST exist. If missing:
   → "PROJECT.md not found. Run `/vg:project` first."
   → STOP.

2. Read `${REQUIREMENTS_FILE}` — MUST exist. If missing:
   → "REQUIREMENTS.md not found. Run `/vg:project` first (it generates both PROJECT.md and REQUIREMENTS.md)."
   → STOP.

3. If `$FROM_EXISTING` is false AND `${ROADMAP_FILE}` already exists:
   ```
   AskUserQuestion:
     header: "ROADMAP.md exists"
     question: "ROADMAP.md already exists. What do you want to do?"
     options:
       - "Overwrite — Start fresh from current requirements"
       - "Add missing — Only add phases for unmapped REQs (same as --from-existing)"
       - "Cancel"
   ```
   If "Overwrite" → continue to step 2.
   If "Add missing" → set `FROM_EXISTING=true`, continue to step 2.
   If "Cancel" → STOP.

4. If `$FROM_EXISTING` is true AND `${ROADMAP_FILE}` does NOT exist:
   → "--from-existing requires an existing ROADMAP.md. Run `/vg:roadmap` first (without the flag)."
   → STOP.
</step>

<step name="2_extract_requirements">
## Step 2: Extract Requirements

Parse `${REQUIREMENTS_FILE}`:

```
For each requirement row:
  Extract: REQ_ID, Category, Requirement text, Priority, Phase (if assigned), Status
  
Group by category:
  categories = { "Auth": [AUTH-01, AUTH-02, ...], "Billing": [BILL-01, ...], ... }

Count:
  total_reqs = N
  must_have = count where priority == "must-have"
  should_have = count where priority == "should-have"  
  nice_to_have = count where priority == "nice-to-have"
```

Also read `${PROJECT_FILE}` for:
- **Key Decisions** (D-P01, D-P02, ...) — may influence phase grouping
- **Non-Functional Requirements** — may create dedicated phases (e.g., "Performance Optimization")
- **Stack constraints** — informs dependency ordering

**If --from-existing:**
```
Parse existing ROADMAP.md → extract all REQ-IDs already assigned to phases
unmapped_reqs = all REQ-IDs from REQUIREMENTS.md NOT in any existing phase
If unmapped_reqs is empty:
  → "All requirements already mapped to phases. Nothing to add."
  → STOP.
Print: "{N} unmapped requirements found: {list}"
Only use unmapped_reqs for phase generation below.
```
</step>

<step name="3_ai_group_requirements">
## Step 3: AI Groups Requirements into Phases

Analyze requirements and propose phase groupings. Rules:

1. **Cluster related REQs** — features that share UI pages, API endpoints, or database collections go together.
2. **Respect priority** — must-have requirements form earlier phases.
3. **Right-size phases** — each phase should be 3-10 requirements. If a category has 15+ REQs, split into sub-phases.
4. **Infrastructure phases first** — auth, database setup, core models before feature phases.
5. **Non-functional as gates** — performance, security can be standalone phases or embedded in feature phases.

For each proposed phase, generate:
```
Phase {NN}: {Name}
  Requirements: [REQ-ID list]
  Depends on: [phase numbers] or "None"
  Size: S | M | L
  Rationale: {1 sentence why these REQs belong together}
```

**Size estimation:**
- **S** (Small): 1-3 REQs, single domain, no new infrastructure
- **M** (Medium): 4-7 REQs, may span 2 domains, moderate complexity
- **L** (Large): 8+ REQs, cross-cutting, new infrastructure or complex integration
</step>

<step name="4_detect_dependencies">
## Step 4: Detect Dependencies

For each pair of phases, check:

1. **Data dependency** — Phase B needs models/tables created in Phase A
   - REQs mentioning "user" depend on auth phase
   - REQs mentioning "payment"/"billing" depend on auth + potentially a billing phase
   - REQs mentioning "report"/"analytics" depend on the data-producing phases

2. **API dependency** — Phase B's frontend needs Phase A's API endpoints
   - CRUD pages depend on their API phase

3. **Infrastructure dependency** — Phase B needs services installed in Phase A
   - Search features depend on search engine setup
   - Real-time features depend on WebSocket/SSE setup

Build a dependency graph. Detect cycles — if found, merge the cycled phases.

**Dependency notation:**
```
Phase 3 depends on: 1, 2     → Phase 3 cannot start until 1 AND 2 are done
Phase 5 depends on: 3        → linear chain
Phase 4 depends on: None     → can start anytime (parallel with others)
```
</step>

<step name="4b_foundation_drift_check">
## Step 4b: Foundation drift check (soft warning, added v1.6.0)

Before presenting roadmap to user, scan all proposed phase titles + descriptions against FOUNDATION.md platform. If any phase introduces a keyword that hints at platform shift away from current foundation, surface a soft warning. Does NOT block — user proceeds, drift logged for milestone audit.

```bash
# Source helper from _shared/foundation-drift.md (conceptual — inline in practice)
PHASE_DIR=".vg"  # roadmap-level, not phase-specific
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"

if [ -f "$FOUNDATION_FILE" ]; then
  # Concatenate all proposed phase titles + descriptions for scan
  SCAN_TEXT=$(${PYTHON_BIN:-python3} -c "
import json, sys
phases = $(echo "$PROPOSED_PHASES_JSON")  # whatever variable held step 3 output
print(' '.join(p.get('name','') + ' ' + p.get('rationale','') for p in phases))
" 2>/dev/null || echo "")
  foundation_drift_check "$SCAN_TEXT" "roadmap:proposed-phases"
fi
# Always proceed regardless of warning (soft gate)
```

Skip silently if FOUNDATION.md doesn't exist (legacy projects pre-v1.6.0). Use `--no-drift-check` to silence.
</step>

<step name="5_present_to_user">
## Step 5: Present Proposed Phases to User

Display the full proposed roadmap:

```
Proposed Roadmap — {PROJECT_NAME}

{total_reqs} requirements → {N} phases

Phase 01: {Name} [{Size}]
  Requirements: AUTH-01, AUTH-02, AUTH-03
  Depends on: None
  Rationale: {why}

Phase 02: {Name} [{Size}]
  Requirements: BILL-01, BILL-02
  Depends on: 01
  Rationale: {why}

...

Dependency graph:
  01 ──→ 02 ──→ 05
  01 ──→ 03 ──→ 05
  04 (independent)
```

Then ask for adjustments:

```
AskUserQuestion:
  header: "Roadmap Review"
  question: "Review the proposed phases. What changes?"
  options:
    - "Approve — looks good, write ROADMAP.md"
    - "Merge phases — combine some phases together"
    - "Split phase — break a phase into smaller pieces"
    - "Reorder — change phase numbering/priority"
    - "Move REQs — reassign requirements between phases"
    - "Add phase — create a phase not derived from REQs (e.g., infra setup)"
```

**Loop until user approves.** Each adjustment round:
1. Apply the change
2. Re-validate dependencies (merging may break chains)
3. Re-display the updated roadmap
4. Ask again
</step>

<step name="6_write_roadmap">
## Step 6: Write ROADMAP.md

**If --from-existing:** Read existing ROADMAP.md, append new phases after last existing phase. Preserve existing phase content exactly.

**Format (per phase):**

```markdown
# Roadmap — {PROJECT_NAME}

Generated: {ISO date}
Total: {N} phases, {M} requirements mapped

## Phase {NN}: {Name}
**Goal:** {1 sentence derived from the requirements in this phase}
**Requirements:** {REQ-ID list, comma-separated}
**Depends on:** {phase numbers or "None"}
**Size:** {S|M|L}
**Success criteria:**
- {criterion derived from REQ acceptance criteria}
- {criterion derived from REQ acceptance criteria}
- ...
**Plans:** 0/0
**Status:** planned
```

**Success criteria derivation:**
- For each REQ in the phase, extract its "Acceptance Criteria" from REQUIREMENTS.md
- Synthesize into 3-6 phase-level success criteria (merge overlapping criteria)
- Each criterion must be testable/measurable

**Write the file:**

```bash
mkdir -p "${PLANNING_DIR}"
# Write ROADMAP.md (content generated above)
```
</step>

<step name="7_create_phase_dirs">
## Step 7: Create Phase Directories

For each phase in the roadmap:

```bash
# Phase directory naming: zero-padded number + slug
# e.g., Phase 1: "Auth & Access" → 01-auth-access
# e.g., Phase 7.2: "Publisher Polish" → 07.2-publisher-polish

for phase in phases:
  SLUG = lowercase(phase.name), replace spaces with hyphens, remove special chars
  PADDED = zero-pad phase.number to 2 digits (e.g., 1 → 01, 7.2 → 07.2)
  DIR_NAME = "${PADDED}-${SLUG}"
  
  mkdir -p "${PHASES_DIR}/${DIR_NAME}"
done
```

**If --from-existing:** Only create directories for NEW phases. Do not touch existing directories.
</step>

<step name="8_update_requirements">
## Step 8: Update REQUIREMENTS.md Traceability

Update the "Phase" column in REQUIREMENTS.md for each mapped REQ:

```
For each REQ assigned to a phase:
  Update REQUIREMENTS.md → set Phase column = phase number
```

Also update the Traceability Matrix section at the bottom:

```markdown
## Traceability Matrix
| REQ ID | Phase | Tasks | Verified |
|--------|-------|-------|----------|
| AUTH-01 | 01 | — | — |
| AUTH-02 | 01 | — | — |
| BILL-01 | 02 | — | — |
...
```
</step>

<step name="9_commit_and_next">
## Step 9: Commit + Suggest Next

```bash
git add "${PLANNING_DIR}/ROADMAP.md" "${PLANNING_DIR}/REQUIREMENTS.md" "${PHASES_DIR}/"
git commit -m "docs(roadmap): derive ${PHASE_COUNT} phases from ${REQ_COUNT} requirements

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Display:

```
Roadmap created: {N} phases from {M} requirements
  Phases: {list of phase names with sizes}
  Dependencies: {summary of dependency chains}
  Directories: {N} phase directories created in ${PHASES_DIR}/
  
  Next steps (recommended order):
    1. /vg:map — rebuild codebase knowledge graph
    2. /vg:prioritize — AI-rank phases by impact + readiness
    3. /vg:specs {first_phase} — start first phase specs
    
  Or batch: /vg:specs {phase} for each phase to pre-populate specs
```
</step>

</process>

<success_criteria>
- ROADMAP.md exists with all phases formatted correctly (Goal, Requirements, Depends on, Size, Success criteria, Plans, Status)
- Every REQ-ID from REQUIREMENTS.md is assigned to exactly one phase (no orphans, no duplicates)
- Dependencies form a valid DAG (no cycles)
- Phase directories created in ${PHASES_DIR}/
- REQUIREMENTS.md updated with Phase column and Traceability Matrix
- User explicitly approved the phase grouping before writing
- Git committed
- Next step guidance shows /vg:map → /vg:prioritize → /vg:specs
</success_criteria>
</output>
