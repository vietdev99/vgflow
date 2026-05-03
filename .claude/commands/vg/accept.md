---
name: vg:accept
description: Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)
argument-hint: "<phase> [--allow-uat-skips] [--allow-empty-uat] [--allow-unreachable] [--override-reason=<text>]"
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
  # OHOK Batch 3 (2026-04-22): full-coverage contract + UAT quorum gate.
  # R4 Accept Pilot (2026-05-03): refactor to slim entry + 10 refs + 2 subagents.
  # Step IDs unchanged — markers + telemetry preserved verbatim.
  must_write:
    # v2.5.1 anti-forge: UAT.md must have Verdict: line — prevents
    # empty/stub UAT without human decision recorded.
    - path: "${PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
      content_min_bytes: 200
      content_required_sections: ["Verdict:"]
    - "${PHASE_DIR}/.uat-responses.json"
  must_touch_markers:
    # Hard gates — foundational + verdict enforcement
    - "0_gate_integrity_precheck"
    - "0_load_config"
    - "create_task_tracker"
    - "0c_telemetry_suggestions"
    - "1_artifact_precheck"
    - "2_marker_precheck"
    - "3_sandbox_verdict_gate"
    - "3b_unreachable_triage_gate"
    - "3c_override_resolution_gate"
    - "4_build_uat_checklist"
    - "4b_uat_narrative_autofire"
    - "5_interactive_uat"
    - "5_uat_quorum_gate"
    - "6b_security_baseline"
    - "6c_learn_auto_surface"
    - "6_write_uat_md"
    # Advisory / post-accept
    - "7_post_accept_actions"
  must_emit_telemetry:
    # v2.5.1 anti-forge: tasklist visibility at flow start
    - event_type: "accept.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    # AUDIT FAIL #9 (R4 fix inherited from R1a blueprint pilot): baseline 0 events.
    # Slim entry's STEP 1 IMPERATIVE TodoWrite + PostToolUse hook auto-projects.
    - event_type: "accept.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "accept.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "accept.completed"
      phase: "${PHASE_NUMBER}"
  # forbidden flags (each MUST be paired with --override-reason="<text>" — the
  # override mechanism itself, NOT listed because it IS what makes the others
  # acceptable). Each accepted bypass MUST also call:
  #   vg-orchestrator override --flag <flag> --reason "<text>"
  # so override.used fires for run-complete contract + OVERRIDE-DEBT.md entry.
  # --allow-uat-skips:    Batch 3 B4 — log when UAT quorum breached
  # --allow-empty-uat:    Batch 3 B4 — log when .uat-responses.json absent
  # --allow-unreachable:  existing (3b gate)
  # --allow-deferred:     belongs to /vg:next (DEFERRED bypass), NOT accept —
  #                        removed from this contract (was undeclared bypass surface).
  forbidden_without_override:
    - "--allow-uat-skips"
    - "--allow-empty-uat"
    - "--allow-unreachable"
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
You MUST follow STEP 1 through STEP 8 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 (`create_task_tracker`)
runs `emit-tasklist.py` — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The
PostToolUse TodoWrite hook auto-writes that signed evidence. This fixes
audit FAIL #9 (`accept.native_tasklist_projected` baseline 0 events).

For HEAVY steps (STEP 3 UAT checklist build, STEP 8 cleanup), you MUST
spawn the named subagent via the `Agent` tool (NOT `Task` — Codex
confirmed correct tool name per Claude Code docs). DO NOT build the
checklist or run cleanup inline.

STEP 5 (interactive UAT) MUST execute INLINE in the main agent — DO NOT
spawn a subagent for it. AskUserQuestion is a UI-presentation tool;
subagent context handoff breaks UX continuity. `.uat-responses.json`
MUST be written after EACH of the 6 sections (anti-theatre, OHOK Batch 3
B4). Quorum gate (STEP 6) blocks if the file is missing or any required
section is empty. Override-resolution gate (STEP 2) blocks unresolved
blocking-severity entries from the override-debt register.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "User trust me, skip interactive UAT" | Quorum gate blocks if `.uat-responses.json` missing/empty (Batch 3 B4) |
| "Override-debt is just warning, accept anyway" | Gate 3c hard-blocks unresolved critical-severity entries |
| "Greenfield design overrides are nominal" | Form B block treats `no-asset:greenfield-*` as critical |
| "UAT-NARRATIVE.md skip, ask user directly" | Narrative autofire deterministic; skip = miss anti-theatre check |
| "Cleanup defer to next phase" | `7_post_accept_actions` has bootstrap hygiene; skip = drift to next phase |
| "Final verdict = accept by default" | Quorum gate verifies actual responses; default-accept = theatre |
| "Subagent overkill for STEP 3 / STEP 8" | Heavy step empirical 96.5% skip rate without subagent (Codex review confirmed) |
| "Step 5 cũng nên là subagent cho gọn" | UX requirement (spec §1.2): AskUserQuestion needs main-agent presence |
| "Spawn `Task()` như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: `vg.block.fired` must pair with `vg.block.handled` or Stop blocks |

## Tasklist policy (summary)

`emit-tasklist.py` writes the profile-filtered
`.vg/runs/<run_id>/tasklist-contract.json` (schema `native-tasklist.v2`).
The slim entry STEP 1 calls it; this skill IMPERATIVELY calls TodoWrite
right after with one todo per `projection_items[]` entry (5 group headers
+ sub-steps with `↳` prefix). Then calls
`vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>` so
`accept.native_tasklist_projected` event fires.

Lifecycle: `replace-on-start` (first projection replaces stale list) +
`close-on-complete` (final clear or completed sentinel).

## Steps (5 checklist groups → 8 STEP sections)

### STEP 1 — preflight (4 light steps)

Read `_shared/accept/preflight.md` and follow it exactly.

This step covers:
- `0_gate_integrity_precheck` — T8 gate (xung đột) precheck
- `0_load_config` — config-loader + phase resolution
- `create_task_tracker` — IMPERATIVE TodoWrite + tasklist projection
- `0c_telemetry_suggestions` — pull weekly telemetry summary

After STEP 1.create_task_tracker bash runs, you MUST call TodoWrite
IMMEDIATELY with the projection items from
`.vg/runs/<run_id>/tasklist-contract.json`.

### STEP 2 — gates (3-tier preflight gates)

Read `_shared/accept/gates.md` and follow it exactly.

This step covers:
- `1_artifact_precheck` — pipeline artifacts present
- `2_marker_precheck` — every profile-applicable step has `.done`
- `3_sandbox_verdict_gate` — SANDBOX-TEST.md verdict ∈ {PASSED, GAPS_FOUND}
- `3b_unreachable_triage_gate` — UNREACHABLE goals classified
- `3c_override_resolution_gate` — override-debt register clean

Each gate is fail-fast. Override only with `--override-reason="<text>"`
(logs to override-debt register).

### STEP 3 — UAT checklist build (HEAVY, subagent)

Read `_shared/accept/uat/checklist-build/overview.md` AND
`_shared/accept/uat/checklist-build/delegation.md`.

Wrap the spawn with narration (overview.md spells out the same lifecycle).
Pre-spawn:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder spawning "phase ${PHASE_NUMBER} UAT checklist"
```

Then call:
```
Agent(subagent_type="vg-accept-uat-builder", prompt=<built from delegation>)
```

Post-return (success):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder returned "<count> items across 6 sections"
```

DO NOT build the checklist inline. The subagent uses `vg-load --list` for
goals (Section B) + design-refs (Section D); other artifacts are KEEP-FLAT
(small single-doc files: CONTEXT.md, FOUNDATION.md, CRUD-SURFACES.md,
RIPPLE-ANALYSIS.md, SUMMARY*.md, build-state.log).

After return, validate output JSON contract + present section counts to
user (proceed/abort prompt).

### STEP 4 — UAT narrative autofire

Read `_shared/accept/uat/narrative.md` and follow it exactly.

This step covers `4b_uat_narrative_autofire` — deterministic
(Sonnet-free) generation of `${PHASE_DIR}/UAT-NARRATIVE.md` from
TEST-GOALS frontmatter (`entry_url`, `navigation_steps`, `precondition`,
`expected_behavior`) + design-ref blocks. Strings come ONLY from
`narration-strings.yaml` (D-18 strict enforcement).

### STEP 5 — interactive UAT (INLINE, NOT subagent)

Read `_shared/accept/uat/interactive.md` and follow it exactly.

<HARD-GATE>
This step MUST execute INLINE in the main agent. DO NOT spawn a subagent.
AskUserQuestion is a UI-presentation tool; subagent context handoff
breaks UX continuity (spec §1.2). Write `.uat-responses.json` after EACH
of the 6 sections (anti-theatre, OHOK Batch 3 B4).
</HARD-GATE>

This step covers `5_interactive_uat` — 50+ AskUserQuestion items across
6 sections (Decisions, Goals, Ripple HIGH callers, Design refs,
Deliverables, Mobile gates). User decisions persisted per-section.

### STEP 6 — UAT quorum gate

Read `_shared/accept/uat/quorum.md` and follow it exactly.

This step covers `5_uat_quorum_gate` — quorum math + rationalization
guard. Counts SKIPs on critical items (Section A decisions, Section B
READY goals); blocks unless `--allow-uat-skips` AND rationalization-guard
passes.

### STEP 7 — audit (security + learn + UAT.md write)

Read `_shared/accept/audit.md` and follow it exactly.

This step covers 3 sub-steps:
- `6b_security_baseline` — `verify-security-baseline.py` subprocess
- `6c_learn_auto_surface` — `/vg:learn --auto-surface` y/n/e/s gate
- `6_write_uat_md` — write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with
  Verdict line. content_min_bytes=200 + content_required_sections enforced
  by must_write contract (anti-forge).

Use `vg-load --priority` (NOT flat TEST-GOALS.md) when enumerating goals
for UAT.md (Phase F Task 30 absorption).

### STEP 8 — cleanup (HEAVY, subagent + post-spawn gates)

Read `_shared/accept/cleanup/overview.md` AND
`_shared/accept/cleanup/delegation.md`.

Wrap the spawn with narration (overview.md spells out the same lifecycle).
Pre-spawn:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup spawning "post-accept ${PHASE_NUMBER}"
```

Then call:
```
Agent(subagent_type="vg-accept-cleanup", prompt=<built from delegation>)
```

Post-return (success):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup returned "<count> actions"
```

DO NOT cleanup inline. The subagent runs 8 subroutines (scan-cleanup,
screenshot cleanup, worktree prune, bootstrap outcome attribution,
PIPELINE-STATE update, ROADMAP flip, CROSS-PHASE-DEPS flip,
DEPLOY-RUNBOOK lifecycle). It branches on `UAT_VERDICT` — short-circuits
for non-ACCEPTED verdicts.

After return, the MAIN AGENT runs 3 hard-exit gates (in `overview.md`):
- Gate A: traceability chain (`verify-acceptance-traceability.py`)
- Gate B: profile marker contract (filter-steps + .step-markers check)
- Gate C: marker write + emit `accept.completed` + `run-complete`

The Stop hook then verifies all 17 markers, must_write paths, and
must_emit_telemetry events.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message
   (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3
escalation). After context compaction, SessionStart hook re-injects open
diagnostics (Layer 4).

## Architectural rationale (R4 pilot)

This slim entry replaces a 2,429-line monolithic accept.md. The 17 step
markers + must_emit_telemetry events are unchanged — only the on-disk
layout changed. Heavy steps (4: 291 lines, 7: 306 lines) are extracted
to subagents to fight the empirical 96.5% inline-skip rate. Light steps
move to flat refs in `_shared/accept/`. Interactive UAT (213 lines) stays
INLINE — UX requirement (spec §1.2). Companion artifacts:

- Spec: `docs/superpowers/specs/2026-05-03-vg-accept-design.md`
- Plan: `docs/superpowers/plans/2026-05-03-vg-r4-accept-pilot.md`
- Backup: `commands/vg/.accept.md.r4-backup` (full pre-refactor)
- Tests: `scripts/tests/test_accept_*.py` (5 static tests)
