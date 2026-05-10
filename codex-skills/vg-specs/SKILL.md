---
name: "vg-specs"
description: "Create SPECS.md for a phase — AI-draft or user-guided mode"
metadata:
  short-description: "Create SPECS.md for a phase — AI-draft or user-guided mode"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
`VG_RUNTIME=codex`, use Codex `update_plan` for the compact visible task
window, and bind it with `vg-orchestrator tasklist-projected --adapter codex`.

`.claude/scripts/*` and `.claude/commands/*` are canonical VGFlow source
paths shared by both adapters; those paths do not mean the runtime changed to
Claude. References below to "Claude CLI", `TodoWrite`, or Haiku describe the
Claude adapter only. Codex must map them through this adapter contract instead
of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use `tasklist-contract.json` as source of truth. Do not paste the full hierarchy into Codex `update_plan`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and `+N pending`. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`. |
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

Invoke this skill as `$vg-specs`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>

<objective>
Generate a concise SPECS.md defining phase goal, scope, constraints, and success criteria. This is the FIRST step of the VG pipeline — specs must be locked before scope, blueprint, or build can proceed.

Output: `${PLANNING_DIR}/phases/{phase_dir}/SPECS.md`
</objective>

<HARD-GATE>
You MUST follow STEP 1 through STEP 8 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 (`parse_args`) registers
the run and `emit-tasklist.py` writes the contract — DO NOT continue
without it. The PreToolUse Bash hook will block all subsequent
step-active calls until signed evidence exists at
`.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The PostToolUse
TodoWrite hook auto-writes that signed evidence.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

This fixes Bug D (2026-05-04): specs was the last mainline command
without TodoWrite enforcement — AI could complete /vg:specs end-to-end
without ever projecting the tasklist, defeating the universal contract.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Specs là step nhỏ, không cần Tasklist" | Bug D 2026-05-04: every mainline cmd MUST project. specs was the last hole. |
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "User trust me, skip approval gate" | OHOK Batch 1 B3: USER_APPROVAL=approve required, silent = BLOCK |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: vg.block.fired must pair with vg.block.handled or Stop blocks |
| "Spawn `Task()` như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |

## Tasklist policy (summary)

`emit-tasklist.py` writes the profile-filtered
`.vg/runs/<run_id>/tasklist-contract.json` (schema `native-tasklist.v2`).
The process preamble below calls it; this skill IMPERATIVELY calls
TodoWrite right after with one todo per `projection_items[]` entry
(group headers + sub-steps with `↳` prefix). Then calls
`vg-orchestrator tasklist-projected --adapter <auto|claude|codex|fallback>`
so `specs.native_tasklist_projected` event fires.

Lifecycle: `replace-on-start` (first projection replaces stale list) +
`close-on-complete` (final clear at run-complete).

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

**Context loading (was a separate step, now process preamble — OHOK Batch 1 A1).**

Before any step below, read these files once to build context for the entire run:
1. **ROADMAP.md** — Phase goal, success criteria, dependencies
2. **PROJECT.md** — Project constraints, stack, architecture decisions
3. **STATE.md** — Current progress, what's already done
4. **Prior SPECS.md files** — `${PHASES_DIR}/*/SPECS.md` (1-2 most recent for style reference)

Store: `phase_goal`, `phase_success_criteria`, `project_constraints`, `prior_phases_done`, `spec_style`.

```bash
# Register run with orchestrator
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:specs "${PHASE_NUMBER}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.started" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

# v2.5.1 anti-forge: show task list at flow start so user sees planned steps.
# Bug D 2026-05-04: writes .vg/runs/<run_id>/tasklist-contract.json — the
# create_task_tracker step below MUST project it via TodoWrite + emit
# tasklist-projected, otherwise PreToolUse Bash hook blocks step-active.
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:specs" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true
```

### Preflight section (extracted v2.75.0 T1)

Read `_shared/specs/preflight.md` and follow it exactly.
Includes 3 steps: create_task_tracker (prepare TodoWrite tracker for the SPECS workflow so progress is visible end-to-end), parse_args (parse {phase_number} positional + auto-discover phase directory and resolve naming/numbering), and check_existing (detect existing SPECS.md and ask before overwriting).

Step coverage: create_task_tracker, parse_args, check_existing.

CODEX NOTE: TodoWrite is Claude-only. On Codex, follow the adapter contract above (Tool mapping table) — emit progress inline in the main thread instead of using TodoWrite.

### Mode + guided + draft (extracted v2.75.0 T2)

Read `_shared/specs/mode-and-draft.md` and follow it exactly.
Includes 3 steps: choose_mode (interactive choice between AI-draft vs guided vs hybrid mode), guided_questions (structured user questionnaire when guided mode is selected), and generate_draft (produce SPECS.md draft tailored to the chosen mode).

Step coverage: choose_mode, guided_questions, generate_draft.

CODEX NOTE: Step choose_mode + guided_questions use AskUserQuestion on Claude. On Codex, ask the same options inline in the main thread per the adapter contract above (Tool mapping table).

### Write + interface standards + commit (extracted v2.75.0 T3 — final)

Read `_shared/specs/write-and-commit.md` and follow it exactly.
Includes 3 closing steps: write_specs (atomic write of ${PHASE_DIR}/SPECS.md with required sections), write_interface_standards (emit INTERFACE-STANDARDS.md when the phase exposes API or UI surfaces), and commit_and_next (commit SPECS.md + INTERFACE-STANDARDS.md to git and route to /vg:scope).

Step coverage: write_specs, write_interface_standards, commit_and_next.

</process>

<success_criteria>
- SPECS.md written to `${PHASE_DIR}/SPECS.md`
- INTERFACE-STANDARDS.md/json written to `${PHASE_DIR}/INTERFACE-STANDARDS.*`
- Contains ALL sections: Goal, Scope (In/Out), Constraints, Success Criteria, Dependencies
- Frontmatter includes phase, status, created, source fields
- User explicitly approved (`USER_APPROVAL=approve`) before writing — silent / unset = BLOCK
- All 8 step markers present under `.step-markers/` (guided_questions waived in --auto mode)
- `specs.started` + `specs.approved` telemetry events emitted
- Git committed + `run-complete` returned 0
</success_criteria>
