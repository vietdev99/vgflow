---
name: vg:blueprint
description: Plan + API contracts + verify + CrossAI review — 4 sub-steps before build
argument-hint: "<phase> [--skip-research] [--gaps] [--reviews] [--text] [--crossai-only] [--skip-crossai] [--from=<substep>] [--override-reason=<text>] [--apply-amendments]"
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
    - path: "${PHASE_DIR}/crossai/result-*.xml"
      glob_min_count: 1
      required_unless_flag: "--skip-crossai"
  must_touch_markers:
    - "0_design_discovery"
    - "0_amendment_preflight"
    - "1_parse_args"
    - "create_task_tracker"
    - "2_verify_prerequisites"
    - "2b6c_view_decomposition"
    - "2b6_ui_spec"
    - "2a_plan"
    - "2a5_cross_system_check"
    - "2b_contracts"
    - "2b5_test_goals"
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
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
    - event_type: "blueprint.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
    - "--skip-codex-test-goal-lane"
    - "--override-reason"
---

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
