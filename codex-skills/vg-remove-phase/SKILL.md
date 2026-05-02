---
name: "vg-remove-phase"
description: "Remove phase from ROADMAP.md + archive/delete phase directory"
metadata:
  short-description: "Remove phase from ROADMAP.md + archive/delete phase directory"
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

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

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

Invoke this skill as `$vg-remove-phase`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **ROADMAP.md required** — must exist. Missing = suggest `/vg:roadmap` first.
4. **No renumbering** — removing a phase NEVER changes existing phase numbers. Gap in numbering is acceptable.
5. **Dependency safety** — warn (not block) if other phases depend on the one being removed.
6. **Archive by default** — recommend archiving over permanent deletion. Data loss is irreversible.
</rules>

<objective>
Remove a phase from the project roadmap. Inverse of `/vg:add-phase`. Shows phase info, checks downstream dependencies, confirms action, then archives or deletes the phase directory and updates ROADMAP.md + REQUIREMENTS.md traceability.

Not part of the main pipeline — utility command run anytime.
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_validate">
## Step 0: Parse phase argument + validate state

```bash
PHASE_NUMBER="$1"
ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
REQUIREMENTS_FILE="${PLANNING_DIR}/REQUIREMENTS.md"

# Validate ROADMAP exists
if [ ! -f "$ROADMAP_FILE" ]; then
  echo "BLOCK: ROADMAP.md not found. Nothing to remove from."
  exit 1
fi

# Resolve phase directory
PHASE_DIR=$(find ${PHASES_DIR} -maxdepth 1 -type d \( -name "${PHASE_NUMBER}*" -o -name "0${PHASE_NUMBER}*" \) 2>/dev/null | head -1)

if [ -z "$PHASE_DIR" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "BLOCK: Phase ${PHASE_NUMBER} directory not found in ${PHASES_DIR}/"
  exit 1
fi

PHASE_NAME=$(basename "$PHASE_DIR")
```
</step>

<step name="1_show_phase_info">
## Step 1: Show phase info

Read ROADMAP.md and extract the phase block. Read phase directory to inventory artifacts.

```bash
# Count artifacts
ARTIFACT_COUNT=$(ls "${PHASE_DIR}"/*.md "${PHASE_DIR}"/*.json 2>/dev/null | wc -l)

# List key artifacts
ARTIFACTS=$(ls "${PHASE_DIR}"/*.md "${PHASE_DIR}"/*.json 2>/dev/null | xargs -I{} basename {})

# Check pipeline status by artifact presence
PIPELINE_STATUS="empty"
[ -f "${PHASE_DIR}/SPECS.md" ]          && PIPELINE_STATUS="specced"
[ -f "${PHASE_DIR}/CONTEXT.md" ]        && PIPELINE_STATUS="scoped"
[ -f "${PHASE_DIR}/PLAN.md" ]           && PIPELINE_STATUS="planned"
[ -f "${PHASE_DIR}/SUMMARY.md" -o -f "${PHASE_DIR}/SUMMARY-wave1.md" ] && PIPELINE_STATUS="built"
[ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]  && PIPELINE_STATUS="reviewed"
[ -f "${PHASE_DIR}/SANDBOX-TEST.md" ]   && PIPELINE_STATUS="tested"
[ -f "${PHASE_DIR}/UAT.md" ]            && PIPELINE_STATUS="accepted"
```

Display:
```
Phase ${PHASE_NUMBER}: ${PHASE_NAME}
  Directory: ${PHASE_DIR}/
  Pipeline status: ${PIPELINE_STATUS}
  Artifacts: ${ARTIFACT_COUNT} files
  ${ARTIFACTS}
```

Extract dependencies from ROADMAP.md (the "Depends on" field for this phase).
</step>

<step name="2_check_dependencies">
## Step 2: Check downstream dependencies

Grep ROADMAP.md for phases that list this phase in their "Depends on" field.

```bash
# Find phases that depend on the phase being removed
DEPENDENTS=$(grep -B5 "Depends on:.*${PHASE_NUMBER}" "$ROADMAP_FILE" | grep -oP 'Phase \K[\d.]+' | grep -v "^${PHASE_NUMBER}$")
```

If dependents found:
```
WARNING: The following phases depend on Phase ${PHASE_NUMBER}:
  ${DEPENDENTS}

Removing Phase ${PHASE_NUMBER} will break their dependency chain.
These phases' "Depends on" field will be updated to remove the reference.
```

If no dependents:
```
No downstream dependencies found. Safe to remove.
```
</step>

<step name="3_confirm">
## Step 3: Confirm removal action

```
AskUserQuestion:
  header: "Remove Phase ${PHASE_NUMBER}: ${PHASE_NAME}"
  question: "How should this phase be removed?"
  options:
    - "Remove + archive (recommended) — move to ${PLANNING_DIR}/archive/${PHASE_NAME}/"
    - "Remove + delete — permanently delete phase directory"
    - "Cancel — abort removal"
```

If "Cancel" → exit without changes.

Store: `$REMOVAL_MODE` = "archive" | "delete"
</step>

<step name="4_execute">
## Step 4: Execute removal

### 4a: Remove phase entry from ROADMAP.md

Find the phase block in ROADMAP.md (from `## Phase ${PHASE_NUMBER}:` to the next `## Phase` or end of file).
Use Edit tool to remove the entire block. Do NOT rewrite the entire file.

### 4b: Move or delete phase directory

```bash
if [ "$REMOVAL_MODE" = "archive" ]; then
  ARCHIVE_DIR="${PLANNING_DIR}/archive"
  mkdir -p "$ARCHIVE_DIR"
  mv "$PHASE_DIR" "${ARCHIVE_DIR}/${PHASE_NAME}"
  echo "Archived: ${PHASE_DIR} → ${ARCHIVE_DIR}/${PHASE_NAME}/"
else
  rm -rf "$PHASE_DIR"
  echo "Deleted: ${PHASE_DIR}/"
fi
```

### 4c: Update REQUIREMENTS.md traceability

If REQUIREMENTS.md exists:
- Find rows where Phase column = `${PHASE_NUMBER}`
- Set Phase column to `---` (unmap — requirement returns to available pool)
- Use Edit tool for surgical updates

```bash
if [ -f "$REQUIREMENTS_FILE" ]; then
  # For each REQ-ID mapped to this phase, reset Phase column to "---"
  # Use Edit tool — do NOT rewrite entire file
  echo "REQUIREMENTS.md: unmapped REQ-IDs from Phase ${PHASE_NUMBER}"
fi
```

### 4d: Update dependent phases (if any)

If step 2 found dependents:
- For each dependent phase in ROADMAP.md, edit its "Depends on" field to remove `${PHASE_NUMBER}`
- If "Depends on" becomes empty after removal, set to "None"

```bash
if [ -n "$DEPENDENTS" ]; then
  for dep in $DEPENDENTS; do
    # Edit ROADMAP.md: remove PHASE_NUMBER from the "Depends on" field of phase $dep
    echo "Updated Phase ${dep}: removed dependency on Phase ${PHASE_NUMBER}"
  done
fi
```
</step>

<step name="5_commit">
## Step 5: Commit changes

```bash
# Stage all changes
git add "$ROADMAP_FILE"
[ -f "$REQUIREMENTS_FILE" ] && git add "$REQUIREMENTS_FILE"

if [ "$REMOVAL_MODE" = "archive" ]; then
  git add "${PLANNING_DIR}/archive/${PHASE_NAME}"
  # Also stage the removal of the original directory
  git add "$PHASE_DIR"
else
  git add "$PHASE_DIR"
fi

git commit -m "roadmap: remove phase ${PHASE_NUMBER} — ${PHASE_NAME}

Action: ${REMOVAL_MODE}
$([ -n "$DEPENDENTS" ] && echo "Updated dependents: ${DEPENDENTS}")

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Display:
```
Phase ${PHASE_NUMBER} removed: ${PHASE_NAME}
  Action: ${REMOVAL_MODE}
  $([ "$REMOVAL_MODE" = "archive" ] && echo "Archive: ${PLANNING_DIR}/archive/${PHASE_NAME}/")
  ROADMAP.md updated (phase block removed)
  $([ -f "$REQUIREMENTS_FILE" ] && echo "REQUIREMENTS.md updated (REQ-IDs unmapped)")
  $([ -n "$DEPENDENTS" ] && echo "Dependent phases updated: ${DEPENDENTS}")
  
  Committed to git.
```
</step>

</process>

<success_criteria>
- Phase block removed from ROADMAP.md
- Phase directory archived to ${PLANNING_DIR}/archive/ or permanently deleted (per user choice)
- REQUIREMENTS.md Phase column reset to "---" for previously-mapped REQ-IDs
- Dependent phases' "Depends on" field updated to remove reference
- No existing phase numbers changed (gap in numbering is acceptable)
- All changes committed to git
- Clear summary of what was removed and where archive lives (if applicable)
</success_criteria>
