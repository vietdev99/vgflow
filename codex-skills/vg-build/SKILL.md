---
name: "vg-build"
description: "Execute phase plans with contract-aware wave-based parallel execution"
metadata:
  short-description: "Execute phase plans with contract-aware wave-based parallel execution"
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

Invoke this skill as `$vg-build`. Treat all user text after the skill name as arguments.
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
You MUST follow STEP 1 through STEP 7 in exact order. Each step is gated
by hooks (PreToolUse Bash + Stop). Skipping ANY step will be blocked.

You MUST call TodoWrite IMMEDIATELY after STEP 1.6 (create_task_tracker)
runs emit-tasklist.py. The PreToolUse Bash hook will block all subsequent
step-active calls until signed evidence exists.

For HEAVY steps (STEP 4 waves, STEP 5 post-execution), you MUST spawn the
named subagent via the `Agent` tool. DO NOT execute waves or
post-execution gates inline. The PreToolUse Agent hook
(vg-agent-spawn-guard) will deny:
  - subagent_type != vg-build-task-executor (typo / wrong agent) for waves
  - task_id missing from prompt
  - task_id not in current wave's remaining[]
  - capsule .task-capsules/task-${N}.capsule.json missing

You MUST narrate every Agent() spawn via vg-narrate-spawn.sh (R1a UX
baseline Req 2 — green-tag chip).

**Dynamic sub-task append (RULE)** — projection từ emit-tasklist là baseline,
KHÔNG cứng. Khi execute STEP 4 (`8_execute_waves`) đặc biệt với `--wave N`,
AI PHẢI append per-task children vào group `Wave Execution` trong TodoWrite
ngay khi wave start. Pattern (tolerant hook B11.6+):

- Initial: 1 todo per group (group title only, từ projection_items)
- Wave start: TodoWrite update — keep group, append children:
  `  ↳ Task 91: route handler /api/sites POST` (pending)
  `  ↳ Task 92: schema + zod validators` (pending)
  `  ↳ Task 93: integration test` (pending)
- Per-task: status pending → in_progress → completed
- Post-wave: roll up children into group (mark group completed only when all
  children done)

Operator giờ thấy real-time "AI sẽ làm Task 91/92/93, đang in_progress
Task 92" thay vì chỉ nhìn 1 dòng `Wave Execution`.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Wave có thể chạy inline cho nhanh" | spawn-guard count check (Task 1) blocks shortfall — N tasks MUST = N spawns |
| "Spawn 3 task xong, dừng vì biết hết rồi" | spawn-guard fires nếu spawned[] != expected[] khi wave-complete |
| "Capsule không cần, AI tự đọc PLAN.md cũng được" | PreToolUse Agent hook blocks spawn without .task-capsules/task-${N}.capsule.json |
| "Đọc PLAN.md/API-CONTRACTS.md cho gọn" | UX baseline Req 1: dùng vg-load --task NN / --endpoint <slug> — flat read trong AI-context path bị Task 16b enforcer chặn |
| "Spawn không cần narrate, save 1 bash call" | UX baseline Req 2 — operator courtesy convention; skip = ugly UX nhưng không block |
| "Build .completed event không cần emit" | Stop hook refuses run-complete without it |
| "Block message bỏ qua, retry là xong" | vg.block.fired phải pair với vg.block.handled hoặc Stop blocks |

## Steps (7 routing blocks)

### STEP 1 — preflight (light)
Read `_shared/build/preflight.md` and follow it exactly.
Includes the IMPERATIVE TodoWrite call after emit-tasklist.py.

### STEP 2 — context loading (light)
Read `_shared/build/context.md` and follow it exactly.
Steps 2_initialize + 4_load_contracts_and_context (Step 4 is the
"sandbox/contract context" upstream of capsule materialization in STEP 4).

### STEP 3 — validate blueprint (light)
Read `_shared/build/validate-blueprint.md` and follow it exactly.
Steps 3_validate_blueprint + 5_handle_branching + 6_validate_phase + 7_discover_plans.

### STEP 4 — execute waves (HEAVY)
Read BOTH `_shared/build/waves-overview.md` AND `_shared/build/waves-delegation.md`.
Then for EACH wave, in a SINGLE assistant message, narrate + spawn N
parallel subagents:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-task-executor spawning "task-${N} wave-${W}"
```
Then call `Agent(subagent_type="vg-build-task-executor", prompt=<rendered from waves-delegation.md>)`.
On return:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-task-executor returned "task-${N} commit ${SHA}"
```
DO NOT execute waves inline. Spawn-guard (Task 1) blocks shortfall.

### Post-wave gate (final-wave detection)

After STEP 4 returns to entry, BEFORE entering STEP 5, check whether this run
is a partial-wave (`--wave N` mid-wave) or a final-wave run. The
`waves-overview.md` orchestration writes `.vg/runs/${RUN_ID}/.is-final-wave`
with value `true` (run-all-waves OR --wave N is final) or `false` (mid-wave).

```bash
IS_FINAL_WAVE="true"
if [ -f ".vg/runs/${RUN_ID}/.is-final-wave" ]; then
  IS_FINAL_WAVE=$(cat ".vg/runs/${RUN_ID}/.is-final-wave")
fi

if [ "$IS_FINAL_WAVE" != "true" ]; then
  echo "▸ Partial-wave run detected (--wave N where N < max). Skipping STEP 5/6/7."
  echo "  Post-execution markers (9_post_execution, 10_postmortem_sanity,"
  echo "  11_crossai_build_verify_loop, 12_run_complete) waived by"
  echo "  is_partial_wave exemption in contract validator."
  echo "  Run \`/vg:build ${PHASE_NUMBER}\` (no --wave) for the FINAL wave to fire post-execution."
  # Mark partial-wave run-complete (orchestrator emits run.completed with partial flag)
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete --partial-wave 2>/dev/null || \
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete 2>/dev/null || true
  exit 0
fi
```

### STEP 5 — post-execution verification (HEAVY)
Read `_shared/build/post-execution-overview.md` AND `_shared/build/post-execution-delegation.md`.
Then narrate + spawn ONE vg-build-post-executor (single — sequential per-task gate walk):
```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor spawning "L2/L3/L5/L6 + truthcheck for ${PHASE_NUMBER}"
```
Then call `Agent(subagent_type="vg-build-post-executor", prompt=<rendered from post-execution-delegation.md>)`.
On return:
```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor returned "${N} gates passed, summary written"
```
DO NOT verify L gates inline.

### STEP 5.5 — In-scope warning auto-fix (HEAVY, conditional)

Read `_shared/build/in-scope-fix-loop.md`. Runs ONLY when STEP 5 emits
`build.l4a_violations_detected` or /vg:review left machine-readable evidence
in `${PHASE_DIR}/.evidence/`. For each IN_SCOPE warning, narrate + spawn:

```bash
bash scripts/vg-narrate-spawn.sh general-purpose spawning "in-scope-fix <warning_id>"
```

Then `Agent(subagent_type="general-purpose", prompt=<from in-scope-fix-loop-delegation.md>)`.

Build BLOCKS at end of STEP 5.5 if any IN_SCOPE remains UNRESOLVED OR any
warning classified NEEDS_TRIAGE.

### STEP 6 — crossai loop (deferred refactor — verbatim)
Read `_shared/build/crossai-loop.md` and follow it exactly.
Per spec §1.5, refactor deferred to separate round (88% loop fail
rate is architectural). This step preserves backup behavior so the
slim entry can route through it without behavior change.

### STEP 6.5 — Pre-Test Gate (HEAVY, conditional)

Read `_shared/build/pre-test-gate.md`. Runs T1 (static: typecheck + lint +
debug-leftover grep + secret scan) + T2 (local unit/integration tests).
Optional T4/T6 deploy + T7 post-deploy health/smoke driven by ENV-BASELINE
+ vg.config policy. Build BLOCKs on T1/T2 failure; deploy/smoke failures
route through Task 7 classifier (no dead-end BLOCK).

Output: `${PHASE_DIR}/PRE-TEST-REPORT.md`. Skippable via `--skip-pre-test`
+ `--override-reason=<text>` (logs override-debt via override-use, then
falls through to STEP 7 — does NOT terminate /vg:build).

### STEP 7 — close (postmortem + run-complete)
Read `_shared/build/close.md` and follow it exactly.
Steps 10_postmortem_sanity + 12_run_complete.
Final step MUST emit `build.completed` event before mark-step.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr 3-line block message + `.vg/blocks/{run_id}/{gate_id}.md` for full diagnostic.
2. Tell the user using the narrative template inside the block file (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the block file.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
