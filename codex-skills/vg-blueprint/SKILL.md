---
name: "vg-blueprint"
description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
metadata:
  short-description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
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

Invoke this skill as `$vg-blueprint`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>




<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

Ví dụ:
- ❌ "Validator failed with 225 evidence count"
- ✅ "Validator báo 225 trường thiếu — chi tiết ở `[path]`. Mình sẽ sửa rồi chạy lại."

File paths, code identifiers (G-04, Wave 9, getUserById), commit messages,
CLI commands stay English. AskUserQuestion title + options + question prose:
ngôn ngữ config.
</LANGUAGE_POLICY>


<HARD-GATE>
You MUST follow STEP 1 through STEP 6 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST project native task UI IMMEDIATELY after STEP 1.4
(create_task_tracker) runs emit-tasklist.py — DO NOT continue without it.
The PreToolUse Bash hook will block all subsequent step-active calls until
signed evidence exists.

Claude Code: TodoWrite MUST include sub-items (`↳` prefix) for each group
header; flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

Codex CLI: update only the compact plan window, not the full hierarchy. Show
at most 6 rows from `codex_plan_window`: active group/step first, next 2-3
pending steps, completed groups collapsed, and `+N pending`.

For HEAVY steps (STEP 3, STEP 4), you MUST spawn the named subagent via
the `Agent` tool (NOT `Task` — Codex confirmed correct tool name per
Claude Code docs). DO NOT generate PLAN.md or API-CONTRACTS.md inline.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Subagent overkill cho step nặng" | Heavy step empirical 96.5% skip rate without subagent (Codex review confirmed) |
| "Tôi đã hiểu, không cần đọc reference" | Reference contains step-specific bash commands not in entry |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "Write evidence file trực tiếp cho nhanh" | PreToolUse Write hook blocks protected paths (Codex fix #2) |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: vg.block.fired must pair with vg.block.handled or Stop blocks |

<HARD-GATE-CODEX>
Codex has no PreToolUse/PostToolUse hooks. Claude Code's `vg-step-tracker.py`
hook auto-emits `must_touch_markers` declared in `commands/vg/blueprint.md`;
Codex does NOT receive that signal. AI MUST emit each HARD marker manually
after the corresponding STEP's primary action completes — failure to do so
causes the contract validator to reject the run with "8/N markers found".

After each STEP's primary action completes, run:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint <marker>
```

Required HARD markers for /vg:blueprint (v2.65.0 A9):

| STEP | Marker(s) to emit |
|---|---|
| STEP 1 (preflight) | `0_amendment_preflight`, `0_design_discovery`, `1_parse_args`, `create_task_tracker`, `2_verify_prerequisites` |
| STEP 3 (plan, subagent) | `2a_plan`, `2a5_cross_system_check` |
| STEP 4 (contracts, subagent) | `2b_contracts`, `2b5_test_goals`, `2b5d_expand_from_crud_surfaces` |
| STEP 5 (verify) | `2c_verify`, `2c_verify_plan_paths`, `2c_utility_reuse`, `2c_compile_check` |
| STEP 6 (close) | `2d_validation_gate`, `2d_test_type_coverage`, `2d_goal_grounding`, `2e_bootstrap_reflection`, `3_complete` |

Profile-gated markers (`2_fidelity_profile_lock`, `2b6c_view_decomposition`,
`2b6_ui_spec`, `2b6b_ui_map`, `2b7_flow_detect`, `2b6d_fe_contracts`,
`2b9_workflows`) and severity:warn markers (`2b5e_a_lens_walk`,
`2b5e_edge_cases`, `2b8_rcrurdr_invariants`, `2b5a_codex_test_goal_lane`,
`2d_crossai_review`) are advisory; emit them when the matching profile
branch executes.
</HARD-GATE-CODEX>

## Steps (6 checklist groups)

### STEP 1 — preflight
Read `_shared/blueprint/preflight.md` and follow it exactly.
This step includes the IMPERATIVE TodoWrite call after emit-tasklist.py.

After STEP 1 finishes (Codex hook fallback — these markers fire only on
Claude via hooks):

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 0_amendment_preflight
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 0_design_discovery
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 1_parse_args
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint create_task_tracker
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2_verify_prerequisites
```

### `--only=<step>` (selective re-run, Codex round-2 Amendment D)

When `--only=<step>` is passed, run ONLY that named step + its required
prerequisites (preflight, parse_args, create_task_tracker, complete). Skip
all other steps. Used for retroactive backfill after a new step is added.

<only-step-list>
Valid step names:
- `fe-contracts` — re-run Pass 2 (Task 38). Prereqs: 2b_contracts, 2b5e_a_lens_walk, 2b6c_view_decomposition.
- `rcrurdr-invariants` — re-run Task 39 RCRURDR generator.
- `workflows` — re-run Task 40 Pass 3 workflow specs.
- `lens-walk` — re-run 2b5e_a_lens_walk in isolation.
- `edge-cases` — re-run 2b5e_edge_cases in isolation.
</only-step-list>

If `<step>` is unknown / invalid / not in the valid list, emit `error`
event `blueprint.only_step_unknown` and exit 1 with message:
`ERROR: unknown step '<step>' for --only=. Valid: fe-contracts, rcrurdr-invariants, workflows, lens-walk, edge-cases`.

### STEP 2 — design (skipped for backend-only / cli-tool / library profiles)
Read `_shared/blueprint/design.md` and follow it exactly.

### STEP 3 — plan (HEAVY)
Read `_shared/blueprint/plan-overview.md` AND `_shared/blueprint/plan-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-planner", prompt=<from delegation>)`.
DO NOT plan inline.

After the planner subagent returns (PLAN.md written + cross-system check done):

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a_plan
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a5_cross_system_check
```

### STEP 4 — contracts (HEAVY)
Read `_shared/blueprint/contracts-overview.md` AND `_shared/blueprint/contracts-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-contracts", prompt=<from delegation>)`.
DO NOT generate contracts inline.

Contracts MUST NOT create `${PHASE_DIR}/LIFECYCLE-SPECS.json`. Blueprint only
authors API/CRUD/TEST-GOALS. Post-build `/vg:test-spec` owns
`LIFECYCLE-SPECS.json`, `DEEP-TEST-SPECS.md`, `TEST-FIXTURE-DAG.json`, and
`PLAYWRIGHT-SPEC-PLAN.md` after implemented DOM/routes/API/forms exist.

After the contracts subagent returns (API-CONTRACTS.md, TEST-GOALS, expand
from CRUD surfaces complete):

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b_contracts
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5_test_goals
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5d_expand_from_crud_surfaces
```

After contracts subagent returns, run `2b5e_a_lens_walk` then `2b5e_edge_cases`:

**`2b5e_a_lens_walk`** (Option B v2.50+) — read `_shared/blueprint/lens-walk.md`.
Re-spawn `vg-blueprint-contracts` with Part 5 prompt (per-goal × applicable-lens
seeds derived from canonical `_shared/lens-prompts/lens-*.md` library). Output:
`LENS-WALK/G-NN.md` per goal + `LENS-WALK/index.md` matrix. Skip with
`--skip-lens-walk` (paired with `--override-reason`). Auto-skip when no CRUD
resources or `--skip-edge-cases`.

**`2b5e_edge_cases`** — read `_shared/blueprint/edge-cases.md`. Re-spawn
`vg-blueprint-contracts` with Part 4 prompt; subagent now ALSO reads
LENS-WALK/G-NN.md (when present) and merges lens-derived seeds into the final
EDGE-CASES table. Output: `EDGE-CASES.md` (Layer 3) + `EDGE-CASES/index.md`
(Layer 2) + `EDGE-CASES/G-NN.md` (Layer 1).

### STEP 5 — verify (7 grep/path checks)
Read `_shared/blueprint/verify.md` and follow it exactly.

After STEP 5's verify checks all pass:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify_plan_paths
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_utility_reuse
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_compile_check
```

### STEP 6 — close (reflection + run-complete + tasklist clear)
Read `_shared/blueprint/close.md` and follow it exactly.

After STEP 6 finishes (validation gate, type coverage, goal grounding,
reflection, run-complete):

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_validation_gate
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_test_type_coverage
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_goal_grounding
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2e_bootstrap_reflection
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 3_complete
```

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
