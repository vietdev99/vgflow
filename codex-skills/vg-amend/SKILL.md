---
name: "vg-amend"
description: "Mid-phase change request — discuss changes, update CONTEXT.md decisions, cascade impact analysis"
metadata:
  short-description: "Mid-phase change request — discuss changes, update CONTEXT.md decisions, cascade impact analysis"
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

Invoke this skill as `$vg-amend`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **AMENDMENT-LOG is append-only** — never overwrite previous amendments, only append.
4. **CONTEXT.md patch, not regenerate** — apply surgical edits to decision list, do NOT rewrite the file.
5. **Git tag before modify** — always create a rollback tag before touching CONTEXT.md.
6. **Impact is informational** — cascade analysis warns but does NOT auto-modify PLAN.md or API-CONTRACTS.md.
</rules>

<objective>
Mid-pipeline change request handler. When requirements shift or decisions need revision during an active phase, this command:
1. Detects current pipeline step
2. Discusses changes with user
3. Writes AMENDMENT-LOG.md (append)
4. Patches CONTEXT.md decisions
5. Analyzes cascade impact on downstream artifacts
6. Tags + commits

Pipeline: specs → scope → blueprint → build → review → test → accept
Amend can run at ANY point after scope.
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_detect">
## Step 0: Parse phase argument + detect current pipeline step

```bash
PHASE_NUMBER="$1"
PHASE_DIR="${PHASES_DIR}/${PHASE_NUMBER}-*"
# Resolve glob to actual directory
PHASE_DIR=$(ls -d ${PHASES_DIR}/${PHASE_NUMBER}-* 2>/dev/null | head -1)

if [ -z "$PHASE_DIR" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "BLOCK: Phase ${PHASE_NUMBER} directory not found in ${PHASES_DIR}/"
  exit 1
fi
```

Detect current step by checking which artifacts exist (ordered latest → earliest):

```bash
CURRENT_STEP="unknown"
[ -f "${PHASE_DIR}/UAT.md" ]              && CURRENT_STEP="accepted"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SANDBOX-TEST.md" ]    && CURRENT_STEP="tested"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]   && CURRENT_STEP="reviewed"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SUMMARY.md" -o -f "${PHASE_DIR}/SUMMARY-wave1.md" ] && CURRENT_STEP="built"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/PLAN.md" ]            && CURRENT_STEP="blueprinted"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]         && CURRENT_STEP="scoped"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SPECS.md" ]           && CURRENT_STEP="specced"
```

Validate: CONTEXT.md MUST exist (amend modifies decisions — no decisions = nothing to amend).
Missing → BLOCK: "Phase ${PHASE_NUMBER} has no CONTEXT.md. Run `/vg:scope ${PHASE_NUMBER}` first."

Display: `"Phase ${PHASE_NUMBER} — current step: ${CURRENT_STEP}"`

Count existing amendments:
```bash
AMENDMENT_COUNT=0
if [ -f "${PHASE_DIR}/AMENDMENT-LOG.md" ]; then
  AMENDMENT_COUNT=$(grep -c '^## Amendment #' "${PHASE_DIR}/AMENDMENT-LOG.md" 2>/dev/null || echo 0)
fi
NEXT_AMENDMENT=$((AMENDMENT_COUNT + 1))
```
</step>

<step name="1_change_type">
## Step 1: What to change?

```
AskUserQuestion:
  header: "Amendment #${NEXT_AMENDMENT} — Phase ${PHASE_NUMBER} (step: ${CURRENT_STEP})"
  question: "What kind of change?"
  options:
    - "Add feature/endpoint" — new functionality not in original scope
    - "Modify decision" — change an existing D-XX decision
    - "Remove feature" — descope something (defer to later phase or drop)
    - "Change technical approach" — different implementation for same goal
```

Store: `$CHANGE_TYPE` = selected option.
</step>

<step name="2_discussion">
## Step 2: Discuss change details

Read current CONTEXT.md → extract all D-XX decisions into memory.

```
AskUserQuestion:
  header: "Change Details"
  question: "Describe the change. I'll show which decisions (D-XX) are affected."
  (open text)
```

AI analyzes user's description against existing decisions:
- List D-XX decisions that this change touches (show current text)
- Identify new decisions needed (propose D-XX IDs continuing from max)
- Identify decisions to remove/defer (show what will be dropped)
- Flag any contradictions with remaining decisions

Present summary:
```
Amendment #${NEXT_AMENDMENT} impact on decisions:
  MODIFY: D-05 — was: "Use MongoDB aggregation for reports" → proposed: "Use ClickHouse for reports"
  ADD:    D-12 — "Add /api/reports/export endpoint for CSV download"
  REMOVE: D-08 — "Client-side PDF generation" (deferred to phase {X})
  
Confirm these changes?
```

```
AskUserQuestion:
  header: "Confirm"
  question: "Proceed with these decision changes?"
  options:
    - "Yes — apply changes"
    - "Adjust — let me modify"
    - "Cancel — abort amendment"
```

If "Adjust" → loop back to discussion.
If "Cancel" → exit without changes.
</step>

<step name="3_write_amendment_log">
## Step 3: Write AMENDMENT-LOG.md (APPEND)

If file does not exist, create with header:
```markdown
# Amendment Log — Phase ${PHASE_NUMBER}

Append-only record of mid-phase changes. Each amendment references decisions modified in CONTEXT.md.
```

Append new amendment block:

```markdown

---

## Amendment #${NEXT_AMENDMENT} — ${ISO_DATE}

**Trigger:** ${user_description}
**Phase step at time of amendment:** ${CURRENT_STEP}
**Change type:** ${CHANGE_TYPE}

**Changes:**
- ${CHANGE_TYPE === "modify" ? "D-XX updated: was \"${old_text}\" → now \"${new_text}\"" : ""}
- ${CHANGE_TYPE === "add" ? "Added: D-XX \"${new_decision}\"" : ""}
- ${CHANGE_TYPE === "remove" ? "Removed: D-XX \"${removed}\" (deferred to phase ${X})" : ""}

**Impact analysis:**
- PLAN.md: ${has_plan ? "tasks ${affected_task_nums} affected (touch ${affected_files})" : "not yet created"}
- API-CONTRACTS.md: ${has_contracts ? "${N} endpoints added/modified/removed" : "not yet created"}
- TEST-GOALS.md: ${has_goals ? "${N} goals added/invalidated" : "not yet created"}
- Code (SUMMARY): ${has_summary ? "gap-closure build may be needed" : "no code yet"}

**Rollback point:** `git tag vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}`
```
</step>

<step name="4_update_context">
## Step 4: Update CONTEXT.md

**Patch, do NOT regenerate.**

For each change:
- **Modify D-XX**: Edit the specific line in CONTEXT.md, preserve surrounding decisions
- **Add D-XX**: Append new decision at end of decisions section, use next available ID
- **Remove D-XX**: Strike through with reason: `~~D-XX: {text}~~ (removed — amendment #${NEXT_AMENDMENT}, deferred to phase {X})`

Add amendment reference footer at bottom of CONTEXT.md (append, do not overwrite existing footers):

```markdown

---
_Amendment #${NEXT_AMENDMENT} applied ${ISO_DATE} — see AMENDMENT-LOG.md_
```
</step>

<step name="5_cascade_impact">
## Step 5: Cascade impact analysis

Check which downstream artifacts exist and report impact:

**If PLAN.md exists:**
- Read PLAN.md → find tasks that reference modified/removed D-XX decisions
- **Matching algorithm** (deterministic, 3 strategies — union of all matches):
  1. Grep PLAN.md for `<goals-covered>` tags containing D-XX references (e.g., `<goals-covered>G-03 (D-05)</goals-covered>`)
  2. Grep PLAN.md for task descriptions mentioning the decision text or keywords from the changed D-XX
  3. Grep PLAN.md for `<contract-ref>` tags if the changed decision has endpoints — match endpoint paths (e.g., `POST /api/sites`)
- Affected tasks = union of all matches from strategies 1-3
- List affected task numbers and file paths they touch
- Display: "PLAN.md: tasks {N-M} reference changed decisions. Re-plan recommended."

**If API-CONTRACTS.md exists:**
- Read API-CONTRACTS.md → find endpoints that map to changed decisions
- List added/removed/modified endpoints
- Display: "API-CONTRACTS.md: {N} endpoints affected."

**If TEST-GOALS.md exists:**
- Read TEST-GOALS.md → find goals that trace to changed decisions
- Flag goals that are now invalid or need new goals added
- Display: "TEST-GOALS.md: {N} goals invalidated, {M} new goals needed."

**If SUMMARY*.md exists (code built):**
- Warn: "Code has been built. Changes may require gap-closure build."
- Display: "Run `/vg:build ${PHASE_NUMBER} --gaps-only` to build missing pieces."

**If RUNTIME-MAP.json exists (reviewed):**
- Warn: "Review completed. Re-review recommended after code changes."

**Suggest next action based on current step:**

| Current Step | Suggested Next |
|---|---|
| scoped | `/vg:blueprint ${PHASE_NUMBER}` — plan will incorporate amendments |
| blueprinted | `/vg:blueprint ${PHASE_NUMBER} --from=2a` — re-plan affected tasks |
| built | `/vg:build ${PHASE_NUMBER} --gaps-only` — build only new/changed parts |
| reviewed | `/vg:build ${PHASE_NUMBER} --gaps-only` then `/vg:review ${PHASE_NUMBER} --retry-failed` |
| tested | `/vg:build ${PHASE_NUMBER} --gaps-only` then `/vg:review ${PHASE_NUMBER}` (full re-review) |
| accepted | Warning: phase already accepted. Consider opening a new phase instead. |
</step>

<step name="6_git_tag_and_commit">
## Step 6: Git tag + commit

```bash
# Create rollback tag BEFORE committing changes
git tag "vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}" HEAD

# Stage amended files
git add "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/AMENDMENT-LOG.md"

# Commit
git commit -m "amend(${PHASE_NUMBER}): ${CHANGE_TYPE} — ${short_summary}

Amendment #${NEXT_AMENDMENT}: ${user_description_short}
Decisions changed: ${changed_decision_ids}
Rollback: git checkout vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}

Co-Authored-By: Claude <noreply@anthropic.com>"

# v2.46 Phase 6 — cascade cross-phase validity check
# When this phase amends decisions, walk ALL downstream phases to mark
# goals citing revoked D-XX as STALE so user knows what to re-review.
CROSS_VAL=".claude/scripts/validators/verify-cross-phase-decision-validity.py"
if [ -f "$CROSS_VAL" ] && [ -d ".vg/phases" ]; then
  echo ""
  echo "🔄 v2.46 amend cascade: checking dependent phases for stale D-XX references..."
  STALE_PHASES=()
  for phase_dir in .vg/phases/*/; do
    other_phase_name=$(basename "$phase_dir")
    other_phase_num=$(echo "$other_phase_name" | sed 's/^0*//' | grep -oE '^[0-9]+(\.[0-9]+)?')
    if [ -z "$other_phase_num" ] || [ "$other_phase_num" = "$PHASE_NUMBER" ]; then
      continue
    fi
    OUT=$(${PYTHON_BIN:-python3} "$CROSS_VAL" --phase "$other_phase_num" --severity warn 2>/dev/null)
    BAD=$(echo "$OUT" | python3 -c "import json,sys
try:
  d = json.load(sys.stdin)
  bad = [e for e in d.get('evidence', []) if str(e.get('type','')).startswith('cross_phase')]
  print(len(bad))
except Exception:
  print(0)" 2>/dev/null || echo 0)
    if [ "${BAD:-0}" -gt 0 ]; then
      STALE_PHASES+=("$other_phase_num ($BAD stale)")
    fi
  done
  if [ ${#STALE_PHASES[@]} -gt 0 ]; then
    echo "  ⚠ Stale references in downstream phase(s):"
    for p in "${STALE_PHASES[@]}"; do echo "     - $p"; done
    echo "  Run /vg:review on each to refresh, OR /vg:amend to update goal references."
  else
    echo "  ✓ No downstream phases reference revoked decisions."
  fi
fi
```

Display:
```
Amendment #${NEXT_AMENDMENT} applied to Phase ${PHASE_NUMBER}
  Type: ${CHANGE_TYPE}
  Decisions modified: ${list}
  Rollback tag: vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}
  
  Suggested next: ${suggested_action}
```
</step>

</process>

<success_criteria>
- AMENDMENT-LOG.md exists with new amendment block appended (never overwrites previous)
- CONTEXT.md patched with decision changes (not regenerated)
- Git tag created before changes for rollback safety
- Cascade impact displayed for all existing downstream artifacts
- Commit message references amendment number and changed decisions
- Clear next-action guidance based on current pipeline step
</success_criteria>
