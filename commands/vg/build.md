---
name: vg:build
description: Execute phase plans with contract-aware wave-based parallel execution
argument-hint: "<phase> [--wave N] [--only 15,16,17] [--gaps-only] [--interactive] [--auto] [--reset-queue] [--status] [--skip-truthcheck] [--skip-pre-test]"
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
argument-instructions: |
  Parse the argument as a phase number plus optional flags.
  Example: /vg:build 7.1
  Example: /vg:build 7.1 --gaps-only
  Example: /vg:build 7.1 --wave 2
runtime_contract:
  # Hook checks these at Stop. Missing evidence = exit 2, force Claude to continue.
  # Phase 13 failure mode (24 commits, 0 telemetry, 2/16 markers) is precisely
  # what this contract catches. See .claude/scripts/vg-verify-claim.py.
  must_write:
    - "${PHASE_DIR}/SUMMARY.md"
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.md"
      content_min_bytes: 500
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.json"
      content_min_bytes: 500
    - path: "${PHASE_DIR}/API-DOCS.md"
      content_min_bytes: 120
    # v2.5.1 anti-forge: build progress file proves wave actually ran.
    # Phase F v2.5 extended schema stores per-task commit_sha + typecheck +
    # wave_verify fields. Missing = AI forged summary without real commits.
    - path: "${PHASE_DIR}/.build-progress.json"
      content_min_bytes: 50
    # NEW per R1a UX baseline Req 1 — 3-layer BUILD-LOG split
    # Layer 1: per-task split (primary, for downstream context budget)
    - path: "${PHASE_DIR}/BUILD-LOG/task-*.md"
      glob_min_count: 1
    # Layer 2: index file (table of contents)
    - "${PHASE_DIR}/BUILD-LOG/index.md"
    # Layer 3: flat concat (legacy compat for grep validators)
    - "${PHASE_DIR}/BUILD-LOG.md"
    # Task 18 (pre-test gate) — PRE-TEST-REPORT.md (renderer at scripts/validators/write-pre-test-report.py)
    - path: "${PHASE_DIR}/PRE-TEST-REPORT.md"
      required_unless_flag: "--skip-pre-test"
      content_min_bytes: 80
  must_touch_markers:
    # OHOK Batch 4 C3 (2026-04-22): contract 8 → 15 markers.
    # Previously 8 steps (1/4/7/8/9/10/11/12) were validated — 11 other
    # steps could silent-skip without orchestrator detection. Now all
    # 18 steps declared; optional ones use severity=warn.
    # ─── Hard gates (block) — foundational enforcement ───
    - "0_gate_integrity_precheck"
    - "1_parse_args"
    - "1a_build_queue_preflight"
    - "1b_recon_gate"
    - "3_validate_blueprint"
    - "4_load_contracts_and_context"
    - "5_handle_branching"
    - "7_discover_plans"
    - "8_execute_waves"
    # ─── Post-execution markers (skipped for partial-wave; required for final wave) ───
    # When `--wave N` is set AND N is NOT the final wave, vg-detect-final-wave
    # writes `.is-final-wave=false` and the orchestrator's is_partial_wave logic
    # exempts these markers (PARTIAL_EXEMPT_MARKERS in
    # scripts/vg-orchestrator/__main__.py). When run-all-waves OR final wave,
    # all four are required by contract validator.
    - "9_post_execution"
    - "10_postmortem_sanity"
    - "11_crossai_build_verify_loop"
    - "12_run_complete"
    # ─── Advisory (warn) — missing ≠ block ───
    - name: "0_session_lifecycle"
      severity: "warn"
    - name: "create_task_tracker"
      severity: "warn"
    - name: "2_initialize"
      severity: "warn"
    - name: "6_validate_phase"
      severity: "warn"
    - name: "8_5_bootstrap_reflection_per_wave"
      severity: "warn"
    # Task 10 (build-fix-loop) — L3 in-scope auto-fix loop runs only when
    # STEP 5 emits l4a_violations_detected OR /vg:review left evidence files.
    # severity=warn so a clean build (no evidence) doesn't fail contract check.
    - name: "8_5_in_scope_fix_loop"
      severity: "warn"
    # Task 18 (pre-test gate) — STEP 6.5 between CrossAI loop and close.
    # Hard contract per Codex round 2 fix #9: NOT severity=warn — required
    # unless --skip-pre-test override is logged via override-use.
    - name: "12_5_pre_test_gate"
      required_unless_flag: "--skip-pre-test"
  must_emit_telemetry:
    # v1.15.2 — names match vg_run_start/vg_run_complete auto-emits.
    # Previously declared build.phase_start/build.phase_end but 0 emit calls
    # existed anywhere in body → hook always failed this check.
    # v2.5.1 anti-forge: tasklist visibility at flow start
    - event_type: "build.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "build.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "build.started"
      phase: "${PHASE_NUMBER}"
    # v2.5.1 anti-forge: wave execution evidence — at least 1 wave.started
    # event proves executor subagents actually spawned. Missing = AI claimed
    # build complete without wave work. Partial-wave runs exempt via is_partial_wave.
    - event_type: "wave.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "build.completed"
      phase: "${PHASE_NUMBER}"
    # Task 6 (build-fix-loop) — L4a deterministic phase-level gates
    # (verify-fe-be-call-graph + verify-contract-shape + verify-spec-drift)
    # run in STEP 5 post-execution. severity=warn (informational signal
    # to STEP 5.5 fix-loop, not a hard contract block).
    - event_type: "build.l4a_violations_detected"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "build.l4a_gates_passed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 18 (pre-test gate) — STEP 6.5 telemetry. complete = full T1+T2
    # ran (with optional deploy); skipped = --skip-pre-test override path.
    - event_type: "build.pre_test_complete"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-pre-test"
    - event_type: "build.pre_test_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 37 — per-task slice resolution (Bug E)
    - event_type: "build.envelope_slice_resolved"
      phase: "${PHASE_NUMBER}"
      severity: "info"
    # Task 42 — cross-wave workflow citation (M2)
    - event_type: "build.cross_wave_workflow_cited"
      phase: "${PHASE_NUMBER}"
      severity: "info"
    # Task 43 (M3) — workflow state drift detection (post-execution validator)
    - event_type: "build.workflow_state_drift_detected"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
  forbidden_without_override:
    # Every escape hatch must leave a debt-register trail.
    - "--override-reason"
    - "--allow-missing-commits"
    - "--allow-r5-violation"
    - "--force"
    - "--skip-truthcheck"
    # v2.41 R2 build pilot — hard-gate-skip flags surfaced by waves-overview
    # gates 8/8d.4/8d.5/8d.9. Each requires --override-reason=<text> + emits
    # override-debt entry. --allow-coverage-regression is informational and
    # logged via close.md PR-D path (NOT listed here).
    - "--skip-design-pixel-gate"
    - "--skip-uimap-injection-audit"
    - "--skip-task-fidelity-audit"
    - "--allow-verify-divergence"
    # Task 18 (pre-test gate) — escape hatch for STEP 6.5 (T1+T2+deploy+smoke)
    - "--skip-pre-test"
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
You MUST follow STEP 1 through STEP 7 in exact order. Each step is gated
by hooks (PreToolUse Bash + Stop). Skipping ANY step will be blocked.

You MUST call TodoWrite IMMEDIATELY after STEP 1.6 (create_task_tracker)
runs emit-tasklist.py. The PreToolUse Bash hook will block all subsequent
step-active calls until signed evidence exists.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

**Payload ordering (Bug D2 2026-05-04):** Claude Code TodoWrite UI renders
in payload-array order — does NOT auto-sort. On every TodoWrite call
REORDER `todos[]` so active group header + its `in_progress` sub-step
appear FIRST, remaining pending next, completed items LAST. Hierarchy
preserved (group header still precedes its own sub-steps).

For HEAVY steps (STEP 4 waves, STEP 5 post-execution), you MUST spawn the
named subagent via the `Agent` tool. DO NOT execute waves or
post-execution gates inline. The PreToolUse Agent hook
(vg-agent-spawn-guard) will deny:
  - subagent_type != vg-build-task-executor (typo / wrong agent) for waves
  - task_id missing from prompt
  - task_id not in current wave's remaining[]
  - capsule .task-capsules/task-${N}.capsule.json missing
  - subagent_type=vg-build-post-executor spawned 2nd time within same run (R6 Task 3)

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
| "Spawn post-executor lần 2 cho chắc / kiểm tra lại SUMMARY" | spawn-guard deny — exactly ONE post-executor per run; read existing SUMMARY.md or use `--resume` |
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
