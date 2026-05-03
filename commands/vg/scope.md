---
name: vg:scope
description: Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md
argument-hint: "<phase> [--skip-crossai] [--skip-crossai-output] [--auto] [--update] [--deepen=D-XX] [--override-reason=<text>] [--skip-env-preference] [--reset-env-preference] [--env-preference=<mode>] [--allow-decisions-untraced] [--force] [--non-interactive]"
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
    # Layer 3: flat concat (legacy compat for grep validators + blueprint consumer)
    - path: "${PHASE_DIR}/CONTEXT.md"
      content_min_bytes: 500
      content_required_sections: ["D-"]
    # Layer 2: index TOC of decisions
    - "${PHASE_DIR}/CONTEXT/index.md"
    # Layer 1: per-decision split (small files for partial vg-load)
    - path: "${PHASE_DIR}/CONTEXT/D-*.md"
      glob_min_count: 1
    # Append-only Q&A trail (single file, no split)
    - "${PHASE_DIR}/DISCUSSION-LOG.md"
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_deep_discussion"
    # Step 3 (env preference) — single declared marker for the env-preference ref.
    # Naming kept as `1b_env_preference` for compat with scripts/emit-tasklist.py
    # CHECKLIST_DEFS["vg:scope"] (S2-owned). Nit #2 deferred (rename would
    # require coordinated S2 update).
    - "1b_env_preference"
    - "2_artifact_generation"
    - "3_completeness_validation"
    - "5_commit_and_next"
    # Flag-gated markers — CrossAI step + its sub-markers all skip together
    # when the user passes --skip-crossai (with --override-reason debt entry).
    - name: "4_crossai_review"
      required_unless_flag: "--skip-crossai"
    - name: "4_5_bootstrap_reflection"
      required_unless_flag: "--skip-crossai"
    - name: "4_6_test_strategy"
      required_unless_flag: "--skip-crossai"
  must_emit_telemetry:
    - event_type: "scope.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
    - "--skip-crossai-output"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1 through STEP 7 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 runs emit-tasklist.py.
The PreToolUse Bash hook will block all subsequent step-active calls
until signed evidence (HMAC) exists at `.vg/runs/<run>/tasklist-evidence.json`.

For each of the 5 discussion rounds (inside STEP 2), you MUST invoke:
  (a) per-answer adversarial challenger via the Agent tool
      (subagent_type=general-purpose, model=Opus default), AND
  (b) per-round dimension expander via the Agent tool
      (subagent_type=general-purpose, model=Opus default).
The wrappers `vg-challenge-answer-wrapper.sh` + `vg-expand-round-wrapper.sh`
build the prompts. DO NOT skip rounds, DO NOT skip challenger/expander —
hooks will not catch this, but Codex consensus blocked omission as
adversarial-suppression risk.

Three documented skip paths (Important-3 r2 — entry-refs alignment):
1. **Trivial answers** (Y/N, single-word) — `challenger_is_trivial`
   helper auto-returns rc=2 from the wrapper. NO override needed; this is
   a built-in noise filter, not a skip of meaningful adversarial review.
2. **Per-phase loop guard** — challenger auto-skips after
   `${config.scope.adversarial_max_rounds:-3}` triggers per phase;
   expander after `${config.scope.dimension_expand_max:-6}`. Hard cap
   prevents runaway cost.
3. **Config-level disable** — `config.scope.adversarial_check: false`
   and/or `config.scope.dimension_expand_check: false` in
   `.claude/vg.config.md`. Intended for rapid-prototyping phases ONLY;
   any phase using these flags emits override-debt at scope.completed.

Outside these 3 paths, skipping is FORBIDDEN.

Tool name is `Agent`, NOT `Task` (Codex correction #1).
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "User answered clearly, skip challenger this round" | Challenger is per-answer trigger; skipping = miss adversarial check |
| "All 5 rounds done, skip expander on R5" | Expander runs once per round end; missing = miss critical_missing detection |
| "R4 UI seems irrelevant for backend phase" | R4 has profile-aware skip — let the profile branch decide, don't manually skip |
| "Fast mode: write CONTEXT.md after R1 only" | Steps 2-5 build incremental decisions; partial = downstream phases ungrounded |
| "CrossAI review takes time, --skip-crossai" | --skip-crossai requires --override-reason; gate enforces override-debt entry |
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Tôi đã hiểu, không cần đọc reference" | Reference contains step-specific bash commands not in entry |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex correction #1) |
| "Per-decision split overkill" | UX baseline R1 — blueprint already consumes via vg-load.sh; missing = build context overflow |
| "Sẵn ngữ cảnh, sinh luôn API-CONTRACTS / TEST-GOALS / PLAN cho nhanh" | Rule 4: scope = DISCUSSION only. Sinh artifact đó là job của /vg:blueprint — write từ scope = lệch contract, blueprint sẽ overwrite gây mất công |

## Steps (7 checklist groups — wired into native tasklist via emit-tasklist.py CHECKLIST_DEFS["vg:scope"])

### STEP 1 — preflight
Read `_shared/scope/preflight.md` and follow it exactly.
This step parses args, validates SPECS.md exists, runs emit-tasklist.py,
and includes the IMPERATIVE TodoWrite call after evidence is signed.

### STEP 2 — deep discussion (HEAVY, INLINE — interactive UX)
Read `_shared/scope/discussion-overview.md` first (sources wrappers,
loads bug-detection-guide). Then loop through 5 rounds:
- R1: Read `_shared/scope/discussion-round-1-domain.md`
- R2: Read `_shared/scope/discussion-round-2-technical.md` (multi-surface gate)
- R3: Read `_shared/scope/discussion-round-3-api.md`
- R4: Read `_shared/scope/discussion-round-4-ui.md` (profile-aware skip)
- R5: Read `_shared/scope/discussion-round-5-tests.md`
- After R5: Read `_shared/scope/discussion-deep-probe.md` (mandatory min 5 probes)

For EACH user answer in EACH round:
1. Build challenger prompt:
   ```bash
   PROMPT=$(bash commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
            "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft")
   ```
2. Spawn challenger:
   ```bash
   bash scripts/vg-narrate-spawn.sh scope-challenger spawning "round-$ROUND answer #$N"
   ```
   Then `Agent(subagent_type="general-purpose", prompt=<PROMPT>)`.
   On return: `bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"`.

For EACH round end (after all answers + challengers):
1. Build expander prompt via `vg-expand-round-wrapper.sh`.
2. Spawn expander (same Agent + narrate pattern).

DO NOT skip rounds. DO NOT skip challenger or expander.

### STEP 3 — env preference
Read `_shared/scope/env-preference.md` and follow it exactly.
Captures sandbox/staging/prod target for downstream commands.

### STEP 4 — artifact generation
Read `_shared/scope/artifact-write.md` and follow it exactly.
Atomic group commit: writes CONTEXT.md (Layer 3 flat) + CONTEXT/D-NN.md
per decision (Layer 1) + CONTEXT/index.md (Layer 2) + DISCUSSION-LOG.md
(append-only). MUST emit `2_artifact_generation` step marker.

### STEP 5 — completeness validation
Read `_shared/scope/completeness-validation.md` and follow it exactly.
Runs 4 checks (decision count, endpoint coverage, UI components,
test scenarios) and surfaces warnings.

### STEP 6 — CrossAI review (skippable with --skip-crossai + --override-reason)
Read `_shared/scope/crossai.md` and follow it exactly.
Async dispatch via crossai-invoke.sh + bootstrap reflection (4_5) +
TEST-STRATEGY draft (4_6). Skipping requires override-debt entry.

### STEP 7 — close
Read `_shared/scope/close.md` and follow it exactly.
Writes contract pin, runs decisions-trace gate, marks `5_commit_and_next`,
emits `scope.completed`, calls run-complete.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).

## UX baseline (R1a inheritance — mandatory cross-flow)

This flow honors the 3 UX requirements baked into R1a blueprint pilot:
- **Per-decision artifact split** — STEP 4 writes CONTEXT/D-NN.md
  (Layer 1) + CONTEXT/index.md (Layer 2) + CONTEXT.md flat concat
  (Layer 3). Blueprint consumes via `scripts/vg-load.sh --phase N --artifact context --decision D-NN`.
- **Subagent spawn narration** — every Agent() call (challenger, expander,
  reflector, vg-crossai inside crossai.md) wrapped with
  `bash scripts/vg-narrate-spawn.sh <name> {spawning|returned|failed}`.
- **Compact hook stderr** — success silent, block 3 lines + file pointer.
  Full diagnostic in `.vg/blocks/{run_id}/{gate_id}.md`.
