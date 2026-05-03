---
name: "vg-roadmap"
description: "Derive phases from PROJECT.md requirements — group, order, estimate, write ROADMAP.md"
metadata:
  short-description: "Derive phases from PROJECT.md requirements — group, order, estimate, write ROADMAP.md"
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

For tasklist projection, Codex must write evidence before any step marker call:
after `emit-tasklist.py`, run `vg-orchestrator tasklist-projected --adapter codex`
as its own tool call. Do not group `tasklist-projected` and `step-active` in
one shell command; PreToolUse evaluates the entire command before the evidence
file exists and will block the grouped command.

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

Invoke this skill as `$vg-roadmap`. Treat all user text after the skill name as arguments.
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
