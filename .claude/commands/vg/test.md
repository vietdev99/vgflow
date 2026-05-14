---
name: vg:test
description: Execute Playwright tests + fix-loop (user-confirm) + matrix verdict + security audit
argument-hint: "<phase> [--skip-deploy] [--regression-only] [--smoke-only] [--fix-only] [--skip-flow] [--allow-missing-console-check] [--headed] [--headless] [--ui] [--slow-mo <ms>]"
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
    - name: "5f_mobile_security_audit"
      severity: "warn"
    - name: "5g_performance_check"
      severity: "warn"
    - name: "5h_security_dynamic"
      severity: "warn"
    # v4.0 NEW — moved from /vg:review (fix-loop) and added (matrix verdict).
    # Logical step IDs, not section numbers; section headers in body are
    # "STEP 5 — fix loop" and "STEP 7 — matrix verdict".
    - name: "step5_fix_loop"
      severity: "warn"
    - name: "step7_matrix_verdict"
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
  - test fix-loop: `  ↳ Iter 1/5: 3 failing goals → spawned vg-test-fixer`,
    `  ↳ Iter 2/5: 1 remaining → re-running playwright`

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
7. **Console monitoring (hard gate v1.14.4+)** — runtime: `browser_console_messages` check after EVERY action (5c goal verification). Codegen (v4.0: produced by `/vg:test-spec`, not `/vg:test`): every mutation spec MUST contain setup (`window.__consoleErrors` OR `page.on('console'/'pageerror')`) + assertion (`expect(errs.length).toBe(0)` pattern). Override: `--allow-missing-console-check` log debt.
8. **Pre-built specs** — v4.0 `/vg:test` does NOT generate `.spec.ts`; it executes the suite produced by `/vg:test-spec` (Step 4_codegen). Missing suite = BLOCK.
9. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
10. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    Browser steps (5c-smoke, 5c-flow) carry `profile="web-fullstack,web-frontend-only"`.
    Contract-curl (5b) carries `profile="web-fullstack,web-backend-only"`.
    `create_task_tracker` preflight filters to applicable steps only; missing markers at step complete → BLOCK.
</rules>

<objective>
Step 7 of V4.0 pipeline. Execute pre-built Playwright suite (from `/vg:test-spec`)
against deployed phase, run user-confirm fix-loop on failures, compute matrix verdict.

Pipeline: specs → scope → blueprint → build → review → test-spec → **test** → accept

v4.0 split:
- `/vg:test-spec` Step 4_codegen owns `.spec.ts` generation (L1/L2 binding gate,
  console-assertion enforcement, vg-test-codegen subagent).
- `/vg:review` is discovery-only (no fix-loop, no matrix verdict).
- `/vg:test` (this skill) executes the suite, runs the fix-loop (user-confirm
  gate: A auto-fix / B manual / C skip+debt), then emits MATRIX-VERDICT.json.

Sub-steps:
- 5a: DEPLOY — push + build + restart on target
- 5b: RUNTIME CONTRACT VERIFY — curl + jq per endpoint
- 5c-smoke: INDEPENDENT SPOT CHECK — cross-check RUNTIME-MAP accuracy
- 5c-goal: GOAL VERIFICATION — verify each goal via known paths (topological sort)
- step5_fix_loop: user-confirm fix-loop on failing goals (A/B/C gate)
- 5e: REGRESSION RUN — npx playwright test (full suite)
- 5f: SECURITY AUDIT — grep + optional deep scan
- step7_matrix_verdict: 4-state per-goal verdict + flip next_command → /vg:accept
</objective>

## Observability flags (Batch 5 — v4.5.0)

Control headed/headless mode and Playwright inspector for live browser visibility.
These flags are forwarded to STEP 5 (5e_regression) via environment variables.

| Flag | Effect |
|------|--------|
| `--headed` | Force headed (visible browser) — overrides CI env + vg.config |
| `--headless` | Force headless — overrides everything (CI-safe) |
| `--ui` | Launch Playwright inspector UI (`npx playwright test --ui`) — interactive debug |
| `--slow-mo <ms>` | Set slowMo delay in ms (default 250 when headed, 0 when headless) |

**Default behaviour (no flag):** `vg.config.test.execution.headed_default` → then TTY+!CI auto-detect.

### `--ui` mode

When `--ui` is passed, step 5e_regression spawns Playwright inspector instead of headless run:

```bash
npx playwright test --ui \
  --config ${GENERATED_TESTS_DIR}/playwright.config.generated.ts \
  ${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts
```

This opens the full Playwright GUI — step-through tests, see locators, replay traces.

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

Goal verification MUST spawn vg-test-goal-verifier (NOT inline). Fix-loop
auto-fix path MUST spawn vg-test-fixer (NOT inline). Console monitoring
MUST run after every action — silent error skip detected by Stop hook.

Note (v4.0): codegen subagent (`vg-test-codegen`) is no longer spawned from
this skill — it now lives in `/vg:test-spec` Step 4_codegen.

For Agent spawning use the `Agent` tool — NOT `Task` (Codex confirmed correct
tool name per Claude Code docs).
</HARD-GATE>

## Red Flags

| Thought | Reality |
|---|---|
| "Codegen ở đây luôn — sửa spec inline" | v4.0: codegen lives in `/vg:test-spec` Step 4. `/vg:test` is execute-only, không sinh `.spec.ts` |
| "Failing goals → tự auto-fix luôn cho nhanh" | v4.0 user-confirm gate là MANDATORY: A/B/C answer required trước khi spawn vg-test-fixer |
| "Goal verification chỉ là replay nhanh" | 303-line step has dual-mode: trust-review default + legacy replay fallback |
| "Skip TodoWrite — emit-tasklist đủ rồi" | PostToolUse hook fires on TodoWrite to emit native_tasklist_projected; missing = audit FAIL #8 |
| "Console errors là warning, ignore được" | Console monitoring là hard-gate; mutation spec không có console assertion → BLOCK |
| "Re-fix-loop hoài cũng được" | MAX_ITER=5 per fix-loop; iter limit hit → diagnostic L2 fallback (user gate, không auto-apply) |
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

### STEP 5 — fix loop + user-confirm gate

Read `_shared/test/fix-loop-and-verdict.md` Step 5 (`step5_fix_loop`) and
follow it exactly. The shared file contains the full fix-loop algorithm
(3a error summary, 3b classify, 3c fix routing, 3d re-verify, 3d.5
QA-checker, 3e iterate + L2 fallback) relocated from `/vg:review` Phase 3.

**User-confirm gate (v4.0 NEW):**

Before spawning any fix subagent, compute `failing_goals` from the Playwright
JSON output produced by `goal-verifier`. If `failing_goals > 0`, call
`AskUserQuestion` with the following options:

```
AskUserQuestion:
  A) Auto-fix     — spawn vg-test-fixer subagent
  B) Manual fix   — block, wait for user to fix + re-run
  C) Skip fix-loop — emit override-debt, continue with failing goals
```

Behaviour by answer:
- **A** → spawn `vg-test-fixer` (defined in `agents/vg-test-fixer/SKILL.md`,
  delivered by T9) with the fix-loop body from `fix-loop-and-verdict.md`.
- **B** → write `${PHASE_DIR}/FIX-LOOP-BLOCKED.md` documenting the failing
  goals + expected fix scope, then exit so user can fix manually.
- **C** → append failing goal IDs to `${PLANNING_DIR}/KNOWN-ISSUES.md` and
  emit `--skip-fix-loop` debt entry. Pipeline continues.

Mark step at completion:

```bash
# Batch 29 F-29.3: outcome gate before mark. Cannot mark unconditionally.
# Status decided from artifacts:
# - .verdict-computed.json failing_goals==0 → PASS
# - FIX-LOOP-BLOCKED.md exists → BLOCKED (option B, manual fix path)
# - .override-debt-skip-fix-loop entry → SKIPPED (option C)
# - else → FAIL
FIX_LOOP_STATUS="UNKNOWN"
FIX_LOOP_REASON=""
VERDICT_JSON="${PHASE_DIR}/.verdict-computed.json"
FIX_LOOP_BLOCKED="${PHASE_DIR}/FIX-LOOP-BLOCKED.md"
SKIP_DEBT="${PHASE_DIR}/.override-debt-skip-fix-loop"

if [ -f "$FIX_LOOP_BLOCKED" ]; then
  FIX_LOOP_STATUS="BLOCKED"
  FIX_LOOP_REASON="user chose manual fix (option B)"
elif [ -f "$SKIP_DEBT" ]; then
  FIX_LOOP_STATUS="SKIPPED"
  FIX_LOOP_REASON="--skip-fix-loop debt logged (option C)"
elif [ -f "$VERDICT_JSON" ]; then
  FAILING=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${PHASE_DIR}/.verdict-computed.json', encoding='utf-8'))
    print(int(d.get('failing_goals', d.get('failed_count', -1))))
except Exception:
    print(-1)
" 2>/dev/null || echo "-1")
  if [ "${FAILING:-0}" -eq 0 ]; then
    FIX_LOOP_STATUS="PASS"
    FIX_LOOP_REASON="all goals passing"
  elif [ "${FAILING:-0}" -gt 0 ]; then
    FIX_LOOP_STATUS="FAIL"
    FIX_LOOP_REASON="${FAILING} goals still failing after fix loop"
  else
    FIX_LOOP_STATUS="FAIL"
    FIX_LOOP_REASON="verdict-computed.json malformed"
  fi
else
  FIX_LOOP_STATUS="FAIL"
  FIX_LOOP_REASON=".verdict-computed.json absent — goal-verifier never ran"
fi

if [ "$FIX_LOOP_STATUS" = "FAIL" ]; then
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
    emit-event "test.fix_loop_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"${FIX_LOOP_REASON}\"}" \
    >/dev/null 2>&1 || true
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/step-status-ledger.py" \
  --phase-dir "${PHASE_DIR}" --step "step5_fix_loop" --status "${FIX_LOOP_STATUS}" \
  --reason "${FIX_LOOP_REASON}" 2>/dev/null || true

"${PYTHON_BIN:-python3}" "$ORCH" mark-step test step5_fix_loop 2>/dev/null || true

if [ "$FIX_LOOP_STATUS" = "FAIL" ] && ! [[ "${ARGUMENTS:-}" =~ --allow-fix-loop-fail ]]; then
  echo "⛔ Batch 29 F-29.3: step5_fix_loop FAIL — ${FIX_LOOP_REASON}" >&2
  exit 1
fi
```

**MANDATORY POST-WAVE CONTINUATION:** After the goal-verifier Agent call
returns (STEP 4), you MUST IMMEDIATELY proceed to STEP 5 (this step) IN THE
SAME ASSISTANT TURN. Do NOT end the turn after the subagent returns. The
harness gates require sequential execution. See `vg-meta-skill.md` "Red
Flags — Post-wave continuation" for rationale.

### STEP 6 — regression + security

Read `_shared/test/regression-security.md` and follow it exactly.

Covers 5e (npx playwright test — full regression suite), 5f (security audit
— grep patterns + optional dynamic lens scan), 5f_mobile_security_audit
(profile-gated), 5g_performance_check (profile-gated), 5h_security_dynamic
(flag-gated). All findings written to SANDBOX-TEST.md security section.

### STEP 7 — matrix verdict

Compute final per-goal verdict (4-state):
`READY` / `BLOCKED` / `TEST_PENDING` / `NOT_SCANNED`.

Read `_shared/test/fix-loop-and-verdict.md` Step 7 (`step7_matrix_verdict`)
and follow it exactly. The shared file contains the full verdict algorithm
(4.0 RCRURD runtime, 4a load goals + edge cases, 4b map → RUNTIME-MAP,
4c-pre NOT_SCANNED resolution, 4c write matrix, 4d inline triage, 4e/4f
100% gate decision) relocated from `/vg:review` Phase 4.

Output:
- `${PHASE_DIR}/MATRIX-VERDICT.json` (machine-readable per-goal verdict)
- Flip `PIPELINE-STATE.json.next_command` → `/vg:accept`

Mark step at completion:

```bash
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test step7_matrix_verdict 2>/dev/null || true
```

### STEP 8 — close

Read `_shared/test/close.md` and follow it exactly.

Covers: write_report (SANDBOX-TEST.md final verdict), complete marker
(profile-filtered marker gate — BLOCKS if any required marker missing),
bootstrap_reflection (vg-reflector subagent call — non-blocking severity:warn),
telemetry `test.completed`, tasklist clear, run-complete signal.


### Post-test reflector trigger (Section 13.5 / meta-memory v1.1)

After `phase.test_completed` emits, spawn vg-reflector subagent IF
`meta_memory_mode != "disabled"`:

```bash
META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" vg.config.md 2>/dev/null | awk '{print $2}' || echo "disabled")

if [ "$META_MEMORY_MODE" != "disabled" ] && [ "$EVENT_TYPE" = "phase.test_completed" ]; then
  bash scripts/vg-narrate-spawn.sh vg-reflector spawning "post-test candidate draft"
  ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
    "reflection.trigger_requested" --actor "test" --outcome "INFO" \
    --metadata "{\"step\":\"test\",\"phase\":\"${PHASE_NUMBER}\",\"trigger\":\"post-test\"}"
fi
```

**Inputs to reflector:**
- events.db query: test.* + codegen.* for current phase
- TEST-GOALS.md per-goal verdicts
- fix-loop iteration count

**Candidate target:** `target_step=test`, `type=declarative|procedural` (auto-detect by reflector heuristic).

**Fingerprint:** `hash(framework + selector_strategy + repo_id)`.

## Diagnostic flow (5 layers)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).
