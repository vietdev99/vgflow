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

Invoke this skill as `$vg-blueprint`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>




---
name: vg:blueprint
description: Plan + API contracts + verify + CrossAI review — 4 sub-steps before build
argument-hint: "<phase> [--skip-research] [--gaps] [--reviews] [--text] [--crossai-only] [--skip-crossai] [--skip-codex-test-goal-lane] [--skip-edge-cases] [--skip-lens-walk] [--from=<substep>] [--override-reason=<text>] [--apply-amendments]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
  - TodoWrite
runtime_contract:
  must_write:
    # Layer 3: flat concat (legacy compat for grep validators)
    - "${PHASE_DIR}/PLAN.md"
    - "${PHASE_DIR}/INTERFACE-STANDARDS.md"
    - "${PHASE_DIR}/INTERFACE-STANDARDS.json"
    - "${PHASE_DIR}/API-CONTRACTS.md"
    - "${PHASE_DIR}/TEST-GOALS.md"
    # Layer 2: index files (table of contents)
    - "${PHASE_DIR}/PLAN/index.md"
    - "${PHASE_DIR}/API-CONTRACTS/index.md"
    - "${PHASE_DIR}/TEST-GOALS/index.md"
    # Layer 1: per-task / per-endpoint / per-goal split (primary, for build context budget)
    - path: "${PHASE_DIR}/PLAN/task-*.md"
      glob_min_count: 1
    - path: "${PHASE_DIR}/API-CONTRACTS/*.md"
      glob_min_count: 2  # at least index.md + 1 endpoint file
    - path: "${PHASE_DIR}/TEST-GOALS/G-*.md"
      glob_min_count: 1
    # Codex lane + CRUD-SURFACES (single docs, not split)
    - path: "${PHASE_DIR}/TEST-GOALS.codex-proposal.md"
      content_min_bytes: 40
      required_unless_flag: "--skip-codex-test-goal-lane"
    - path: "${PHASE_DIR}/TEST-GOALS.codex-delta.md"
      content_min_bytes: 80
      required_unless_flag: "--skip-codex-test-goal-lane"
    - path: "${PHASE_DIR}/CRUD-SURFACES.md"
      content_min_bytes: 120
      required_unless_flag: "--crossai-only"
    # Edge cases artifact (P1 v2.49+) — generated by 2b5e_edge_cases step.
    # required_unless_flag covers: legacy phases (no flag pre-v2.49 →
    # severity=warn fallback), --skip-edge-cases override, no-CRUD phases
    # (subagent emits blueprint.edge_cases_skipped, validator honors empty).
    - path: "${PHASE_DIR}/EDGE-CASES.md"
      content_min_bytes: 120
      required_unless_flag: "--skip-edge-cases"
      severity: "warn"
    - path: "${PHASE_DIR}/EDGE-CASES/index.md"
      required_unless_flag: "--skip-edge-cases"
      severity: "warn"
    - path: "${PHASE_DIR}/EDGE-CASES/G-*.md"
      glob_min_count: 1
      required_unless_flag: "--skip-edge-cases"
      severity: "warn"
    # Lens-walk artifact (Option B v2.50+) — produced by 2b5e_a_lens_walk
    # before 2b5e_edge_cases. Seeds bug-class-driven variants from canonical
    # lens-prompts library. severity=warn for legacy compat + advisory nature
    # (edge-cases is the contract; lens-walk is upstream input).
    - path: "${PHASE_DIR}/LENS-WALK/index.md"
      required_unless_flag: "--skip-lens-walk"
      severity: "warn"
    - path: "${PHASE_DIR}/LENS-WALK/G-*.md"
      glob_min_count: 1
      required_unless_flag: "--skip-lens-walk"
      severity: "warn"
    - path: "${PHASE_DIR}/crossai/result-*.xml"
      glob_min_count: 1
      required_unless_flag: "--skip-crossai"
  must_touch_markers:
    - "0_design_discovery"
    - "0_amendment_preflight"
    - "1_parse_args"
    - "create_task_tracker"
    - "2_verify_prerequisites"
    - "2a_plan"
    - "2a5_cross_system_check"
    - "2b_contracts"
    - "2b5_test_goals"
    # 2b5e_a_lens_walk (Option B v2.50+) — per-goal × per-applicable-lens
    # iteration. Seeds bug-class-driven variants from canonical lens-prompts.
    # Runs BEFORE 2b5e_edge_cases (edge-cases consumes lens-walk output).
    - name: "2b5e_a_lens_walk"
      severity: "warn"
      required_unless_flag: "--skip-lens-walk"
    # 2b5e_edge_cases (P1 v2.49+) — runs after test_goals, before expand.
    # severity=warn for legacy compat (phases pre-v2.49 không có step này).
    - name: "2b5e_edge_cases"
      severity: "warn"
      required_unless_flag: "--skip-edge-cases"
    - "2b5d_expand_from_crud_surfaces"
    - "2c_verify"
    - "2c_verify_plan_paths"
    - "2c_utility_reuse"
    - "2c_compile_check"
    - "2d_validation_gate"
    - "2d_test_type_coverage"
    - "2d_goal_grounding"
    - "2e_bootstrap_reflection"
    - "3_complete"
    # Profile-gated markers (only run for specified profiles).
    - name: "2_fidelity_profile_lock"
      profile: "web-fullstack,web-frontend-only"
    - name: "2b6c_view_decomposition"
      profile: "web-fullstack,web-frontend-only"
    - name: "2b6_ui_spec"
      profile: "web-fullstack,web-frontend-only"
    - name: "2b6b_ui_map"
      profile: "web-fullstack,web-frontend-only"
    - name: "2b7_flow_detect"
      profile: "web-fullstack,web-frontend-only"
    # Flag-gated markers (skip via override flag with debt entry)
    - name: "2b5a_codex_test_goal_lane"
      required_unless_flag: "--skip-codex-test-goal-lane"
    - name: "2d_crossai_review"
      required_unless_flag: "--skip-crossai"
  must_emit_telemetry:
    - event_type: "blueprint.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.plan_written"
      phase: "${PHASE_NUMBER}"
    - event_type: "blueprint.contracts_generated"
      phase: "${PHASE_NUMBER}"
    # P1 v2.49+ — edge cases either generated OR skipped (mutually exclusive)
    - event_type: "blueprint.edge_cases_generated"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "blueprint.edge_cases_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Option B v2.50+ — lens-walk either generated OR skipped (mutually exclusive)
    - event_type: "blueprint.lens_walk_generated"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "blueprint.lens_walk_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
    - event_type: "blueprint.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
    - "--skip-codex-test-goal-lane"
    - "--skip-edge-cases"
    - "--skip-lens-walk"
    - "--override-reason"
---


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

You MUST call TodoWrite IMMEDIATELY after STEP 1.4 (create_task_tracker)
runs emit-tasklist.py — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists.

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

## Steps (6 checklist groups)

### STEP 1 — preflight
Read `_shared/blueprint/preflight.md` and follow it exactly.
This step includes the IMPERATIVE TodoWrite call after emit-tasklist.py.

### STEP 2 — design (skipped for backend-only / cli-tool / library profiles)
Read `_shared/blueprint/design.md` and follow it exactly.

### STEP 3 — plan (HEAVY)
Read `_shared/blueprint/plan-overview.md` AND `_shared/blueprint/plan-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-planner", prompt=<from delegation>)`.
DO NOT plan inline.

### STEP 4 — contracts (HEAVY)
Read `_shared/blueprint/contracts-overview.md` AND `_shared/blueprint/contracts-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-contracts", prompt=<from delegation>)`.
DO NOT generate contracts inline.

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

### STEP 6 — close (reflection + run-complete + tasklist clear)
Read `_shared/blueprint/close.md` and follow it exactly.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
