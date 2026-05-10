---
name: vg:specs
description: Create SPECS.md for a phase — AI-draft or user-guided mode
argument-hint: "<phase> [--auto]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - TodoWrite
runtime_contract:
  # OHOK Batch 1 (2026-04-22): specs.md runtime_contract.
  # Previously zero enforcement — step 1 of pipeline was 100% performative.
  # Now orchestrator validates markers + artifact + approval at run-complete.
  must_write:
    - path: "${PHASE_DIR}/SPECS.md"
      content_min_bytes: 300
      # Match skill template literal headings (lines 280, 284 below).
      # Was ["Goal:", "Scope:"] — inconsistent with template that emits "## Goal"
      # + "## Scope" (no colons). Phase 7.14.3 dogfood fix 2026-04-25.
      content_required_sections: ["## Goal", "## Scope"]
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.md"
      content_min_bytes: 500
      content_required_sections: ["## API Standard", "## Frontend Error Handling Standard", "## CLI Standard", "## Harness Enforcement"]
    - path: "${PHASE_DIR}/INTERFACE-STANDARDS.json"
      content_min_bytes: 500
  must_touch_markers:
    - "parse_args"
    - "create_task_tracker"
    - "check_existing"
    - "choose_mode"
    # guided_questions only fires in interactive mode → warn severity
    - name: "guided_questions"
      severity: "warn"
      required_unless_flag: "--auto"
    - "generate_draft"
    - "write_specs"
    - "write_interface_standards"
    - "commit_and_next"
  must_emit_telemetry:
    - event_type: "specs.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    # Bug D — universal tasklist enforcement (2026-05-04). specs was the
    # only mainline command lacking the projection event; AI could run
    # full /vg:specs without ever calling TodoWrite.
    - event_type: "specs.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "specs.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "specs.approved"
      phase: "${PHASE_NUMBER}"
    # specs.rejected is emitted on user-rejection branch; declare so Stop hook
    # validates either approved OR rejected was emitted (severity=warn since
    # only one of the two fires per run).
    - event_type: "specs.rejected"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
  forbidden_without_override:
    - "--override-reason"
---

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
Includes 3 steps: create_task_tracker, parse_args, check_existing.

Step coverage: create_task_tracker, parse_args, check_existing.


### Mode + guided + draft (extracted v2.75.0 T2)

Read `_shared/specs/mode-and-draft.md` and follow it exactly.
Includes 3 steps: choose_mode, guided_questions, generate_draft.

Step coverage: choose_mode, guided_questions, generate_draft.


### Write + interface standards + commit (extracted v2.75.0 T3 — final)

Read `_shared/specs/write-and-commit.md` and follow it exactly.
Includes 3 steps: write_specs, write_interface_standards, commit_and_next.

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
