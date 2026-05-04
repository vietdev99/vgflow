---
name: "vg-test"
description: "Clean goal verification + independent smoke + codegen regression + security audit"
metadata:
  short-description: "Clean goal verification + independent smoke + codegen regression + security audit"
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

Invoke this skill as `$vg-test`. Treat all user text after the skill name as arguments.
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


<TASKLIST_POLICY>
**Native tasklist is mandatory.**

`emit-tasklist.py` is the source of truth. It writes
`.vg/runs/<run_id>/tasklist-contract.json` containing profile-filtered
checklists and steps. Before any test execution beyond `create_task_tracker`,
project that contract into the active AI runtime:
- Claude Code: create/update native tasks with `TodoWrite` using one todo per
  checklist group. `TaskCreate` / `TaskUpdate` is acceptable only when this
  Claude runtime exposes those native task tools.
- Codex CLI: use native plan/tasklist UI or the Codex adapter exposed by the
  harness; every step start/end must be visible.
- Fallback: print `vg-orchestrator run-status --pretty`, but still emit
  `test.native_tasklist_projected`.

Lifecycle:
- `replace-on-start`: the first native projection MUST replace any stale task
  list from a previous workflow. Never append current test items onto a
  previous workflow's list.
- `close-on-complete`: before reporting success, mark all test checklist items
  completed. Then clear the native list if supported; otherwise replace it with
  one completed sentinel item: `vg:test phase ${PHASE_NUMBER} complete`.

Every profile-applicable step MUST call `vg-orchestrator step-active` when it
starts and `vg-orchestrator mark-step test {step}` when it finishes. The
final `complete` step recomputes the profile-filtered step list and BLOCKS if
any required marker is missing.

Long-running commands still use background execution + `BashOutput` polling so
the user sees live logs. Tasklist items are progress projection, not a reason
to split browser/lens work into extra passes.

**Dynamic sub-task append (RULE)** — projection từ emit-tasklist là baseline,
KHÔNG cứng. Khi AI đang execute 1 group/step phức tạp (e.g., `8_execute_waves`
trong build với --wave N có nhiều task), AI PHẢI append child todos vào group
đó ngay khi bắt đầu wave/step để user thấy real-time progress.

Pattern (PostToolUse hook tolerant — chấp nhận cả group title match + sub-step match):
- Initial projection: 1 todo per group header (từ projection_items)
- During wave/step execution: TodoWrite update — giữ group header, append children
  với title format `  ↳ <task-id>: <one-line desc>` (status: pending → in_progress
  → completed). Sub-tasks tự discover từ PLAN/index.md task list, RUNTIME-MAP
  goal_sequences, hoặc actual work items AI đang làm.
- Examples:
  - build wave 9: `  ↳ Task 91: route handler /api/sites POST`,
    `  ↳ Task 92: schema + zod validators`,
    `  ↳ Task 93: integration test`
  - review browser discovery: `  ↳ View /campaigns: 12 actions captured`,
    `  ↳ Lens lens-modal-state: 3 modals probed`
  - test codegen: `  ↳ G-04: spec.ts generated`,
    `  ↳ G-07: spec.ts (deep-probe variants pending)`

This gives operator visibility into "AI sẽ làm gì tiếp / tiến độ tới đâu" mà
không cần đọc Bash output. Hook không reject append vì tolerant match (B11.6+).

**Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `PASSED (đạt)`, `FAILED (thất bại)`, `regression (hồi quy)`, `coverage (độ phủ)`. Không áp dụng: file path, code identifier (`G-XX`, `git`), config tag values, lần lặp lại trong cùng message.
</TASKLIST_POLICY>

<rules>
1. **RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md required** — review must have completed. Missing = BLOCK.
2. **TEST-GOALS.md required** — goals must exist (from blueprint or review).
3. **No discovery in test** — review already explored. Test VERIFIES known paths.
4. **MINOR-only fix (auto-gated v1.14.4+)** — AI MUST emit `fix-plans.json` before attempting fix. Pre-flight script `severity-classify.py` auto-classifies dựa trên: file count ≥3 → MODERATE, touches `apps/api/**/routes|schemas|contracts` → MODERATE, touches `packages/**|apps/web/**/lib|apps/web/**/hooks` → MODERATE, `change_type=new_feature|contract` → MAJOR. Auto-escalate MODERATE/MAJOR → REVIEW-FEEDBACK.md, kick back to review. AI không được tự classify MINOR bypass gate.
5. **Independent smoke first** — spot-check RUNTIME-MAP accuracy before trusting it.
6. **Navigate via UI clicks** — browser_navigate BANNED except for initial login/domain switch.
7. **Console monitoring (hard gate v1.14.4+)** — runtime: `browser_console_messages` check after EVERY action (5c goal verification). Codegen: every mutation spec MUST contain setup (`window.__consoleErrors` OR `page.on('console'/'pageerror')`) + assertion (`expect(errs.length).toBe(0)` pattern). Post-codegen gate 5d-r7 greps generated `.spec.ts`, BLOCKS if mutation spec thiếu console assertion. Override: `--allow-missing-console-check` log debt.
8. **Goal-based codegen** — assertions from TEST-GOALS success criteria, paths from RUNTIME-MAP observation.
9. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
10. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    Browser steps (5c-smoke, 5c-flow, 5d codegen) carry `profile="web-fullstack,web-frontend-only"`.
    Contract-curl (5b) carries `profile="web-fullstack,web-backend-only"`.
    `create_task_tracker` preflight filters to applicable steps only; missing markers at step complete → BLOCK.
</rules>

<objective>
Step 5 of V5.1 pipeline. Clean goal verification — review already discovered + fixed. Test only verifies goals and generates regression tests.

Pipeline: specs → scope → blueprint → build → review → **test** → accept

Sub-steps:
- 5a: DEPLOY — push + build + restart on target
- 5b: RUNTIME CONTRACT VERIFY — curl + jq per endpoint
- 5c-smoke: INDEPENDENT SPOT CHECK — cross-check RUNTIME-MAP accuracy
- 5c-goal: GOAL VERIFICATION — verify each goal via known paths (topological sort)
- 5c-fix: MINOR FIX ONLY — minor fix in test, moderate/major escalate to review
- 5d: CODEGEN — generate .spec.ts from verified goals + RUNTIME-MAP paths
- 5e: REGRESSION RUN — npx playwright test
- 5f: SECURITY AUDIT — grep + optional deep scan
</objective>

<HARD-GATE>
You MUST follow STEP 1-8 in profile-filtered order. Each step is gated by
hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after `create_task_tracker` runs
emit-tasklist.py — DO NOT continue without it. The PreToolUse Bash hook will
block all subsequent step-active calls until signed evidence exists.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

Codegen MUST spawn vg-test-codegen (NOT inline). Goal verification MUST
spawn vg-test-goal-verifier. Console monitoring MUST run after every
action — silent error skip detected by Stop hook.

For Agent spawning use the `Agent` tool — NOT `Task` (Codex confirmed correct
tool name per Claude Code docs).
</HARD-GATE>

## Red Flags

| Thought | Reality |
|---|---|
| "Codegen 1 spec.ts file, đơn giản, làm inline" | 645-line step has L1/L2 binding gates that vg-test-codegen subagent enforces |
| "Goal verification chỉ là replay nhanh" | 303-line step has dual-mode: trust-review default + legacy replay fallback |
| "Skip TodoWrite — emit-tasklist đủ rồi" | PostToolUse hook fires on TodoWrite to emit native_tasklist_projected; missing = audit FAIL #8 |
| "Console errors là warning, ignore được" | Console monitoring is hard-gate post-codegen; mutation specs without console assertion BLOCK |
| "Re-codegen hoài cũng được, max=3" | L1 max 1 retry per goal; L2 escalates to AskUserQuestion (don't loop) |
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Subagent overkill cho step nặng" | Heavy step empirical 96.5% skip rate without subagent (Codex review confirmed) |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |

## Steps

### STEP 1 — preflight

Read `_shared/test/preflight.md` and follow it exactly.

This step covers: gate integrity precheck, session lifecycle, config-loader,
bug-detection-guide, MCP server claim, parse + validate args, state update,
telemetry suggestions, and `create_task_tracker` (emit-tasklist.py). MUST
call TodoWrite immediately after `create_task_tracker` completes.

### STEP 2 — deploy

Read `_shared/test/deploy.md` and follow it exactly.

Covers steps 5a (web deploy) and 5a_mobile (mobile deploy, profile-gated).
Background execution + BashOutput polling required for long-running build
commands. Step skippable via `--skip-deploy` (logs override debt).

### STEP 3 — runtime contract verify + smoke + flow

Read `_shared/test/runtime.md` and follow it exactly.

Covers steps 5b (runtime contract verify — curl + jq), 5c-smoke (independent
spot-check), 5c-flow (full user-journey flow), and 5c_mobile_flow
(profile-gated). Browser steps require `$MCP_PREFIX` from STEP 1. Release
Playwright server lock after this step completes or on error.

### STEP 4 — goal verification (HEAVY, subagent)

Read `_shared/test/goal-verification/overview.md` AND
`_shared/test/goal-verification/delegation.md`.

Then spawn: `Agent(subagent_type="vg-test-goal-verifier", prompt=<from delegation.md>)`.

DO NOT run goal verification inline. The subagent enforces dual-mode
(trust-review default + legacy replay fallback), topological sort, per-goal
console monitoring, minor-fix gate (`severity-classify.py`), auto-escalate
MODERATE/MAJOR back to review, and `5c_goal_verification` / `5c_fix` /
`5c_auto_escalate` marker emission.

### STEP 5 — codegen (HEAVY, subagent + L1/L2 binding gate)

Read `_shared/test/codegen/overview.md` AND
`_shared/test/codegen/delegation.md`.

Then spawn: `Agent(subagent_type="vg-test-codegen", prompt=<from delegation.md>)`.

DO NOT generate `.spec.ts` files inline. The subagent enforces L1 (1 retry
per goal) / L2 (AskUserQuestion escalation) binding gates, console assertion
in every mutation spec, post-codegen gate 5d-r7 grep, and emits the
`5d_codegen` orchestrator marker. `5d_binding_gate` is subagent-internal
(not surfaced as an orchestrator marker — see codegen/overview.md STEP 5.7
note + commit `04a5e79`). `5d_deep_probe` and `5d_mobile_codegen` markers
are emitted inside their orchestrator-side ref steps after the subagent
returns.

After subagent completes, orchestrator reads:
- `_shared/test/codegen/deep-probe.md` — orchestrator-side deep probe actions.
- If profile `mobile-*`: `_shared/test/codegen/mobile-codegen.md` — mobile
  codegen path with native test runner.

On L2 escalations from subagent: call AskUserQuestion with subagent's
escalation message, then re-spawn with user answer injected.

### STEP 6 — fix loop + auto escalate

Read `_shared/test/fix-loop.md` and follow it exactly.

Covers the post-codegen fix loop: run playwright regression, triage failures,
attempt MINOR fixes (MODERATE/MAJOR auto-escalate to review), re-run, cap
at configured max iterations. Emits `5c_fix` / `5c_auto_escalate` markers
(if not already emitted by goal-verifier in STEP 4).

### STEP 7 — regression + security

Read `_shared/test/regression-security.md` and follow it exactly.

Covers 5e (npx playwright test — full regression suite), 5f (security audit
— grep patterns + optional dynamic lens scan), 5f_mobile_security_audit
(profile-gated), 5g_performance_check (profile-gated), 5h_security_dynamic
(flag-gated). All findings written to SANDBOX-TEST.md security section.

### STEP 8 — close

Read `_shared/test/close.md` and follow it exactly.

Covers: write_report (SANDBOX-TEST.md final verdict), complete marker
(profile-filtered marker gate — BLOCKS if any required marker missing),
bootstrap_reflection (vg-reflector subagent call — non-blocking severity:warn),
telemetry `test.completed`, tasklist clear, run-complete signal.

## Diagnostic flow (5 layers)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
