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
  # R5 specs slim pilot (2026-05-04): refactor to slim entry + 3 refs.
  # Step IDs unchanged — markers + telemetry preserved verbatim.
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
Generate a concise SPECS.md defining phase goal, scope, constraints, and
success criteria. This is the FIRST step of the VG pipeline — specs must be
locked before scope, blueprint, or build can proceed.

Output: `${PLANNING_DIR}/phases/{phase_dir}/SPECS.md`
</objective>

<HARD-GATE>
You MUST follow STEP 1 through STEP 3 in exact order. Marker-tracked
steps emit `step-active` + `mark-step` (those listed in
`must_touch_markers` above); skipping any of those is blocked by
PreToolUse + Stop hooks via missing-marker detection.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 (`parse_args` + preamble
emit-tasklist.py) — DO NOT continue without it. The PreToolUse Bash hook
will block all subsequent step-active calls until signed evidence exists
at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The PostToolUse
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

## Tasklist policy

Read `_shared/lib/tasklist-projection-instruction.md` and follow it
exactly for the canonical 2-layer projection contract (group headers
+ ↳ sub-items, adapter='claude' for Claude Code sessions, signed
evidence at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`).

Summary: `emit-tasklist.py` writes the profile-filtered
`.vg/runs/<run_id>/tasklist-contract.json` (schema `native-tasklist.v2`).
The process preamble below calls it; this skill IMPERATIVELY calls
TodoWrite right after with one todo per `projection_items[]` entry
(group headers + sub-steps with `↳` prefix). Then calls
`vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`
so `specs.native_tasklist_projected` event fires.

Lifecycle: `replace-on-start` (first projection replaces stale list) +
`close-on-complete` (final clear at run-complete).

**Payload ordering rule (Bug D2 2026-05-04):** Claude Code TodoWrite UI
renders in payload-array order — does NOT auto-sort. On every TodoWrite
call REORDER `todos[]` so active group header + its `in_progress`
sub-step appear FIRST, then remaining pending, completed LAST. Hierarchy
preserved: each group header still precedes its own sub-steps.

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

## Steps (3 STEP sections)

### STEP 1 — preflight (5 light steps)

Read `_shared/specs/preflight.md` and follow it exactly.

This step covers:
- `parse_args` — extract phase + --auto flag, validate ROADMAP entry
- `create_task_tracker` — IMPERATIVE TodoWrite + tasklist-projected (Bug D fix)
- `check_existing` — handle existing SPECS.md (View / Edit / Overwrite)
- `choose_mode` — AI Draft vs Guided
- `guided_questions` — 5 questions (Goal / Scope-IN / Scope-OUT /
  Constraints / Success Criteria), only in --guided mode

After STEP 1.create_task_tracker bash runs, you MUST call TodoWrite
IMMEDIATELY with the projection items from
`.vg/runs/<run_id>/tasklist-contract.json`.

### STEP 2 — authoring (3 sub-steps)

Read `_shared/specs/authoring.md` and follow it exactly.

This step covers:
- `generate_draft` — render preview + `AskUserQuestion` BLOCKING APPROVAL GATE.
  USER_APPROVAL ∈ {approve, edit, discard}; silent / unset = BLOCK.
- `write_specs` — write SPECS.md with frontmatter + sections; runs
  `verify-artifact-schema.py` post-write to catch frontmatter drift.
- `write_interface_standards` — generate INTERFACE-STANDARDS.{md,json}
  via `generate-interface-standards.py` + validate.

### STEP 3 — close (1 sub-step)

Read `_shared/specs/close.md` and follow it exactly.

This step covers `commit_and_next`:
- git add + commit SPECS.md + INTERFACE-STANDARDS.{md,json}
- Soft-suggest design discovery if FE work detected (P20 D-05)
- run-complete (orchestrator validates runtime_contract)

</process>

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3
escalation). After context compaction, SessionStart hook re-injects
open diagnostics (Layer 4).

## Architectural rationale (R5 specs pilot)

This slim entry replaces a 596-line specs.md monolith. The 9 step markers
+ must_emit_telemetry events are unchanged — only on-disk layout changed.
Heavy steps stay inline (no subagent — specs is small enough for main
agent context budget). Light steps moved to flat refs in `_shared/specs/`.

Token impact: ~300 lines saved from main agent's specs.md context load.
Combined with Bug D + D3 + R3 review slim, total session savings: 80-150K
tokens depending on workflow mix.

Companion artifacts:
- Backup: `commands/vg/.specs.md.r5-backup` (full 596-line pre-refactor)
- Refs:
  - `_shared/specs/preflight.md` (parse_args, create_task_tracker,
    check_existing, choose_mode, guided_questions — 183 lines)
  - `_shared/specs/authoring.md` (generate_draft, write_specs,
    write_interface_standards — 191 lines)
  - `_shared/specs/close.md` (commit_and_next — 54 lines)

<success_criteria>
- SPECS.md written to `${PHASE_DIR}/SPECS.md` (≥300 bytes, contains
  ## Goal + ## Scope sections)
- INTERFACE-STANDARDS.{md,json} written to `${PHASE_DIR}/`
- All 8 step markers present under `.step-markers/` (guided_questions
  waived in --auto mode)
- `specs.tasklist_shown` + `specs.native_tasklist_projected` (Bug D) +
  `specs.started` + `specs.approved` telemetry events emitted
- User explicitly approved (`USER_APPROVAL=approve`) before writing —
  silent / unset = BLOCK
- Git committed + `run-complete` returned 0
</success_criteria>
