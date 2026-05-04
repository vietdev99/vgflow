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

Codex hook processes cannot mutate the environment of later shell tool calls.
If a command-body shell lacks `CLAUDE_SESSION_ID`, `vg-orchestrator` recovers
the session from `.vg/.session-context.json` and the matching
`.vg/active-runs/<session>.json`. Do not create a fresh run when the
UserPromptSubmit hook already registered the same command/phase.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Do not manually retype long command-body heredocs into nested shell strings.
Prefer deterministic Codex helpers shipped in `.claude/scripts/`. For
`/vg:blueprint` STEP 3.1, run `codex-vg-env.py` and
`codex-blueprint-plan-prep.py` exactly as documented in
`_shared/blueprint/plan-overview.md`; then spawn the planner from the prepared
prompt. This avoids zsh glob/quote expansion corrupting Python heredocs before
Bash executes them.

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

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

For tasklist projection, Codex must write evidence as soon as
`tasklist-contract.json` exists: after `emit-tasklist.py`, run
`vg-orchestrator tasklist-projected --adapter codex` as its own tool call.
Do not group `tasklist-projected` and `step-active` in one shell command;
PreToolUse evaluates the entire command before the evidence file exists and
will block the grouped command. Some command preflights have bootstrap steps
before `emit-tasklist.py`; only those declared bootstrap steps may run before
the tasklist contract exists.

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

When creating prompt files for `codex-spawn.sh`, use a single-quoted heredoc
delimiter such as `cat > "$PROMPT_FILE" <<'EOF'` or write from an existing
template. Do not use unquoted `<<EOF` for prompts that contain backticks,
`$...`, command substitutions, or markdown code fences: the shell will
expand them before Codex sees the prompt and can corrupt the child contract.
If runtime variables must be injected, prefer a small controlled render step
that substitutes placeholders after the quoted template is written.

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

Cascade analysis is delegated to `vg-amend-cascade-analyzer` subagent
(read-only). Subagent inspects PLAN/API-CONTRACTS/TEST-GOALS/SUMMARY/
RUNTIME-MAP for references to changed decisions, returns a markdown
impact report. Per rule 6, the report is informational — orchestrator
displays it to user but does NOT auto-modify any artifact.

### 5.1 Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer spawning "phase=$PHASE_NUMBER decisions=$CHANGED_DECISIONS"
```

### 5.2 Spawn

Construct prompt JSON and call:

```text
Agent(
  subagent_type="vg-amend-cascade-analyzer",
  prompt={
    "phase_dir": "${PHASE_DIR}",
    "changed_decision_ids": <JSON list of D-XX from Step 2>,
    "change_summary": "<one-line from Step 2 user input>"
  }
)
```

### 5.3 Post-spawn narrate

On success (markdown report returned):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer returned "report-len=$(echo "$REPORT" | wc -l)"
```

On failure (subagent emitted error JSON or no markdown block):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer failed "<one-line cause>"
```

### 5.4 Display report to user

Display the subagent's markdown report block inline in chat. Do NOT
write the report to a file (rule 6: informational only). The
AMENDMENT-LOG.md entry written in Step 3 already captures change context;
the cascade report is for user's pre-commit awareness.

### 5.5 If subagent failed

If the subagent failed (e.g. all artifacts unreadable), surface the
cause to user via:

> Cascade analysis failed: <cause>. Continue to Step 6 commit
> without impact report? (yes/no)

On yes → proceed to Step 6.
On no → abort entry skill (no commit, no telemetry beyond what was emitted).

See `.claude/agents/vg-amend-cascade-analyzer.md` for the full subagent
contract.
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
