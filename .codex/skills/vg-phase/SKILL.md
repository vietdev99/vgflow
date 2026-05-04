---
name: "vg-phase"
description: "Run full 7-step phase pipeline — specs → scope → blueprint → build → review → test → accept"
metadata:
  short-description: "Run full 7-step phase pipeline — specs → scope → blueprint → build → review → test → accept"
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

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

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

Invoke this skill as `$vg-phase`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Orchestrate the full VG pipeline for a phase. Runs steps sequentially, stopping on failure with resume guidance.

Full pipeline (3 stages):
```
Project init:     /vg:project → /vg:roadmap → /vg:map (optional)
Phase planning:   /vg:prioritize → /vg:specs → /vg:scope → /vg:scope-review
Phase execution:  /vg:blueprint → /vg:build → /vg:review → /vg:test → /vg:accept
```

This command runs the **phase execution** stage (7 steps): specs → scope → blueprint → build → review → test → accept.
For project init (`/vg:init` → `/vg:project` → `/vg:roadmap` → `/vg:map`) or phase planning (`/vg:prioritize`), use the individual commands listed above.

Flags:
- `--from={step}` — resume from specific step (e.g., `--from=review`)
- `--auto` — auto-advance through steps without pausing between them
</objective>

<process>

<step name="0_load_config">
Read .claude/commands/vg/_shared/config-loader.md.
</step>

<step name="1_parse_args">
Parse `$ARGUMENTS`:
- First positional token → `PHASE_ARG`
- Optional `--from={step}` → `START_STEP` (default: auto-detect)
- Optional `--auto` → auto-advance mode

Valid step names: `specs`, `scope`, `blueprint`, `build`, `review`, `test`, `accept`

Resolve `PHASE_DIR` from `PHASE_ARG`:
```bash
PHASE_DIR=$(find ${PLANNING_DIR}/phases -maxdepth 1 -type d \( -name "${PHASE_ARG}*" -o -name "0${PHASE_ARG}*" \) 2>/dev/null | head -1)
if [ -z "$PHASE_DIR" ]; then
  echo "Phase dir not found for: $PHASE_ARG"
  exit 1
fi

# Warn if phase dir contains non-ASCII characters (Windows/git compatibility)
if echo "${PHASE_DIR}" | LC_ALL=C grep -q '[^[:print:][:space:]]'; then
  echo "WARNING: Phase directory contains non-ASCII characters: ${PHASE_DIR}"
  echo "  This may cause issues on Windows or in git. Consider renaming."
fi
```
</step>

<step name="1b_phase_recon">
**Phase Reconnaissance — inventory + classify + recommend BEFORE routing.**

Follow `.claude/commands/vg/_shared/phase-recon.md`.

This step runs `phase-recon.py` against the phase dir, classifies every file
(V6 canonical / V5 numbered / legacy GSD / versioned rot / orphan), determines
pipeline position, and if legacy/hybrid → presents interactive migration menu.

```bash
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" ${RECON_FRESH:+--fresh}

PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
```

If `PHASE_TYPE ∈ {legacy_gsd, v5_iterative, hybrid}`:
- Show `.recon-report.md` summary
- Present migration menu per `_shared/phase-recon.md` step R3b
- Apply user choice (consolidate → migrate → archive)
- Re-recon after mutations

After recon, read the recommended_action:
```bash
RECON_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
```

If `--from` was specified, `START_STEP = --from` (user override).
Otherwise, `START_STEP = ${RECON_STEP}` (recon-driven).
</step>

<step name="2_detect_start">
`START_STEP` is now set by step 1b (recon-driven) or `--from` (user override).

If `START_STEP == "complete"` → phase done, skip pipeline execution.

Display:
```
## VG Phase {N} — V6 Pipeline

Phase type:   {PHASE_TYPE} (from recon)
Starting from: {START_STEP} (step {N}/6)
Mode: {auto|interactive}
```
</step>

<step name="2b_create_task_tracker">
**Create visual task list for pipeline progress tracking.**

Create 6 tasks — one per pipeline step. Mark already-completed steps immediately.
Steps before `START_STEP` that have artifacts → mark as `completed`.
The `START_STEP` itself → leave as `pending` (will be marked `in_progress` when it runs).

```
Claude Code native projection: use `TodoWrite` to create these 6 visible
pipeline tasks. If this Claude runtime exposes `TaskCreate`/`TaskUpdate`,
that adapter is also acceptable.

Lifecycle: the first native projection is `replace-on-start` and MUST replace
any stale tasklist from a previous workflow. On normal completion, use
`close-on-complete`: mark all phase pipeline items completed, then clear the
native list if supported; otherwise replace it with one completed sentinel item:
`vg:phase phase ${PHASE_NUMBER} complete`.

TaskCreate/TodoWrite item: "Step 1/6: scope — extract decisions"        (activeForm: "Running scope...")
TaskCreate/TodoWrite item: "Step 2/6: blueprint — plan + API contracts"  (activeForm: "Running blueprint...")
TaskCreate/TodoWrite item: "Step 3/6: build — execute code"              (activeForm: "Running build...")
TaskCreate/TodoWrite item: "Step 4/6: review — discovery + fix loop"      (activeForm: "Running review...")
TaskCreate/TodoWrite item: "Step 5/6: test — goal verification"           (activeForm: "Running test...")
TaskCreate/TodoWrite item: "Step 6/6: accept — human UAT"                (activeForm: "Running accept...")
```

Store task IDs as: `TASK_SCOPE`, `TASK_BLUEPRINT`, `TASK_BUILD`, `TASK_REVIEW`, `TASK_TEST`, `TASK_ACCEPT`.

For each step with existing artifact (before START_STEP):
```
TodoWrite/TaskUpdate: mark taskId={TASK_ID} status="completed"
```
</step>

<step name="3_execute_pipeline">
Run steps sequentially. **For each step:**

1. `TodoWrite`/`TaskUpdate: taskId={TASK_ID}, status="in_progress"` — spinner shows activeForm
2. Invoke the command via SlashCommand
3. Check step succeeded (artifact created)
4. If **failed** → STOP:
   - `TodoWrite`/`TaskUpdate: taskId={TASK_ID}, status="pending"` (reset, not completed)
   - Display: "Resume with `/vg:phase {phase} --from={current_step}`"
5. If **succeeded**:
   - `TodoWrite`/`TaskUpdate: taskId={TASK_ID}, status="completed"`
   - If auto mode → proceed to next step
   - If interactive mode → pause:
     ```
     Step {N}/6 ({step_name}) complete.
     Continue to {next_step}? (y/skip/stop)
     ```
   - If user says "skip":
     - **⛔ PREREQUISITE GATE (tightened 2026-04-17):** check if the step AFTER the skipped one depends on artifacts produced by the skipped step. If yes, BLOCK the skip and force the step to run.

     Dependency rules (hardcoded — see "Step sequence" table below):
     | Skipping | Next step needs | Block if missing |
     |----------|-----------------|-------------------|
     | scope | blueprint needs CONTEXT.md | CONTEXT.md |
     | blueprint | build needs PLAN*.md + API-CONTRACTS.md | any PLAN*.md |
     | build | review needs commits (git log) | phase commits count > 0 |
     | review | test needs RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md | either file |
     | test | accept needs *-SANDBOX-TEST.md (verdict != FAILED) | SANDBOX-TEST.md |

     ```bash
     # Run before native task completion update. If block triggered, display:
     echo "⛔ Cannot skip ${step_name} — downstream step ${next_step} requires artifacts that haven't been built:"
     echo "   Missing: ${MISSING_ARTIFACTS}"
     echo "   Options:"
     echo "     (a) Run ${step_name} to produce the artifacts"
     echo "     (b) Provide artifacts manually, then /vg:${next_step} {phase}"
     echo "     (c) Exit pipeline"
     # Do NOT mark task completed. Do NOT advance.
     ```

     - If prerequisites ARE satisfied (e.g., artifacts from prior manual work exist) → `TodoWrite`/`TaskUpdate: taskId={NEXT_TASK_ID}, status="completed"` and move to step after.

**Step sequence:**

| # | Step | Command | Task ID | Success = artifact exists |
|---|------|---------|---------|--------------------------|
| 1 | scope | `/vg:scope {phase}` | TASK_SCOPE | CONTEXT.md |
| 2 | blueprint | `/vg:blueprint {phase}` | TASK_BLUEPRINT | PLAN*.md + API-CONTRACTS.md |
| 3 | build | `/vg:build {phase}` | TASK_BUILD | SUMMARY*.md |
| 4 | review | `/vg:review {phase}` | TASK_REVIEW | RUNTIME-MAP.json + RUNTIME-MAP.md |
| 5 | test | `/vg:test {phase}` | TASK_TEST | *-SANDBOX-TEST.md with verdict != FAILED |
| 6 | accept | `/vg:accept {phase}` | TASK_ACCEPT | *-UAT.md with status "complete" |

**Fast-path (AI-recommended):**
Before starting, assess scope complexity:
- Small change (1-2 files, no new pages) → **⛔ forced user pause** (review skip = fewer gates, higher risk of missed drift):
  Invoke `AskUserQuestion`:
    - header: "Skip review step?"
    - question: "Phase scope nhỏ (1-2 files). Recommend bỏ qua /vg:review → chạy: specs → scope → blueprint → build → test → accept. Review giúp phát hiện runtime drift, bỏ qua nhanh hơn nhưng rủi ro hơn. Approve skip?"
    - options:
      - "Yes — skip review (phase nhỏ, ít drift risk)"
      - "No — chạy full pipeline có review (safer)"
  Không auto-skip. Nếu user chọn Yes → `TodoWrite`/`TaskUpdate: taskId=TASK_REVIEW, status="completed"` (mark skipped + log reason to override-debt: "user-approved skip for small scope").
- Medium/large change → full pipeline (không hỏi, review luôn chạy)
</step>

<step name="4_complete">
After all steps:
```
Phase {N} — V5 Pipeline COMPLETE

Steps completed: {N}/6
Artifacts:
  ✓ SPECS.md → CONTEXT.md → PLAN.md + API-CONTRACTS.md
  ✓ SUMMARY.md → RUNTIME-MAP.json + RUNTIME-MAP.md
  ✓ SANDBOX-TEST.md → UAT.md
  
Generated tests: {N} .spec.ts files (CI-ready)

▶ /vg:next (advance to next phase)
```
</step>

</process>
