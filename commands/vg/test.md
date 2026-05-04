---
name: vg:test
description: Clean goal verification + independent smoke + codegen regression + security audit
argument-hint: "<phase> [--skip-deploy] [--regression-only] [--smoke-only] [--fix-only] [--skip-flow] [--allow-missing-console-check]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - TodoWrite
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
  - BashOutput
runtime_contract:
  # /vg:test MUST produce SANDBOX-TEST.md with explicit pass/fail verdict per
  # goal. Missing = test was skipped/simulated in AI head, not executed.
  must_write:
    - "${PHASE_DIR}/SANDBOX-TEST.md"
  must_touch_markers:
    - "00_gate_integrity_precheck"
    - "00_session_lifecycle"
    - "0_parse_and_validate"
    - "0c_telemetry_suggestions"
    - "create_task_tracker"
    - "0_state_update"
    - "5c_goal_verification"
    - "5c_fix"
    - "5c_auto_escalate"
    - "5e_regression"
    - "5f_security_audit"
    - "write_report"
    - "complete"
    # Profile-specific markers are verified hard by the profile-aware marker
    # gate in step `complete`. Runtime contract keeps them as WARN here
    # because this YAML contract is intentionally profile-agnostic.
    - name: "5a_deploy"
      severity: "warn"
    - name: "5a_mobile_deploy"
      severity: "warn"
    - name: "5b_runtime_contract_verify"
      severity: "warn"
    - name: "5c_smoke"
      severity: "warn"
    - name: "5c_flow"
      severity: "warn"
    - name: "5c_mobile_flow"
      severity: "warn"
    - name: "5d_codegen"
      severity: "warn"
    # 5d_binding_gate is subagent-internal (vg-test-codegen handles L1/L2
    # binding via verify-goal-test-binding.py + block-resolver inside the
    # subagent). It is intentionally NOT exposed as an orchestrator marker;
    # do not list it under must_touch_markers — see
    # _shared/test/codegen/delegation.md (Step F.3) and
    # _shared/test/codegen/overview.md (STEP 5.7 note).
    - name: "5d_deep_probe"
      severity: "warn"
    - name: "5d_mobile_codegen"
      severity: "warn"
    - name: "5f_mobile_security_audit"
      severity: "warn"
    - name: "5g_performance_check"
      severity: "warn"
    - name: "5h_security_dynamic"
      severity: "warn"
    # BOOT-1 (2026-04-23): reflector must run at test-close so the learning
    # loop captures evidence from the full specs→accept pipeline, not only
    # review. severity=warn (non-blocking) — reflector crashes don't fail test.
    - name: "bootstrap_reflection"
      severity: "warn"
  must_emit_telemetry:
    # v2.5.1 anti-forge: tasklist visibility at flow start
    - event_type: "test.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "test.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "test.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "test.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--override-reason"
    - "--skip-deploy"
    - "--skip-flow"
    - "--allow-missing-console-check"
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
- `payload-ordering` (Bug D2 2026-05-04): Claude Code TodoWrite UI renders
  in payload-array order, NOT auto-sorted by status. On every TodoWrite
  call REORDER `todos[]` so the active group header + its `in_progress`
  sub-step appear FIRST, remaining pending next, completed items LAST.
  Hierarchy preserved (group header before its own sub-steps).

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
    Browser steps (5c-smoke, 5c-flow, 5d_codegen) carry `profile="web-fullstack,web-frontend-only"`.
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

**Payload ordering (Bug D2 2026-05-04):** Claude Code TodoWrite UI renders
in payload-array order — does NOT auto-sort. On every TodoWrite call
REORDER `todos[]` so active group header + its `in_progress` sub-step
appear FIRST, remaining pending next, completed items LAST. Hierarchy
preserved (group header still precedes its own sub-steps).

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
