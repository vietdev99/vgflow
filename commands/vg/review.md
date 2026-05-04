---
name: vg:review
description: Post-build review — code scan + browser discovery + lens dispatch + fix loop + goal comparison → RUNTIME-MAP
argument-hint: "<phase> [--target-env=local|staging|sandbox|prod | --local | --sandbox | --staging | --prod] [--mode=full|delta|regression|schema-verify|link-check|infra-smoke] [--scanner=haiku-only|codex-inline|codex-supplement|gemini-supplement|council-all] [--with-deepscan] [--non-interactive] [--skip-scan] [--skip-discovery] [--fix-only] [--skip-crossai] [--evaluate-only] [--retry-failed] [--re-scan-goals=G-XX,G-YY] [--dogfood] [--force] [--full-scan] [--allow-no-crud-surface] [--skip-lens-plan-gate] [--override-reason=<text>]"
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
  # OHOK Batch 2 C4 (2026-04-22): full-coverage contract.
  # R3 review pilot (2026-05-04): refactor to slim entry + 14 refs +
  # 1 subagent. Step IDs unchanged — markers + telemetry preserved verbatim.
  must_write:
    - "${PHASE_DIR}/RUNTIME-MAP.json"
    - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
    - path: "${PHASE_DIR}/api-docs-check.txt"
      content_min_bytes: 60
      required_unless_flag: "--skip-discovery"
      must_be_created_in_run: true
      check_provenance: true
    # v2.47.2 — mandatory API precheck before browser discovery. Must be
    # created by the CURRENT run so force-review cannot reuse stale probe.
    - path: "${PHASE_DIR}/api-contract-precheck.txt"
      content_min_bytes: 60
      required_unless_flag: "--skip-discovery"
      must_be_created_in_run: true
      check_provenance: true
    - path: "${PHASE_DIR}/REVIEW-LENS-PLAN.json"
      content_min_bytes: 120
      required_unless_flag: "--skip-discovery"
    # CrossAI review evidence (LABEL=review-check, not stale blueprint xml).
    - path: "${PHASE_DIR}/crossai/review-check.xml"
      content_min_bytes: 80
      required_unless_flag: "--skip-crossai"
    # v2.5.1 anti-forge: Haiku scan JSON proves browser discovery actually ran.
    - path: "${PHASE_DIR}/scan-*.json"
      glob_min_count: 1
      required_unless_flag: "--skip-discovery"
    # Task 36b — lens dispatch chain artifacts
    - path: "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"
      content_min_bytes: 200
      required_unless_flag: "--probe-mode-skip"
    - path: "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
      content_min_bytes: 100
      required_unless_flag: "--probe-mode-skip"
  must_touch_markers:
    # ─── Hard gates (block) — foundational, always run ───
    - "00_gate_integrity_precheck"
    - "0_parse_and_validate"
    - "0b_goal_coverage_gate"
    - "complete"
    # ─── Session lifecycle + planning (warn) — advisory ───
    - name: "00_session_lifecycle"
      severity: "warn"
    - name: "create_task_tracker"
      severity: "warn"
    # v2.42.1 — env+mode+scanner gate: HARD block.
    - name: "0a_env_mode_gate"
      required_unless_flag: "--non-interactive"
    - name: "phase_profile_branch"
      severity: "warn"
    - name: "0c_telemetry_suggestions"
      severity: "warn"
    # ─── Profile-exclusive phaseP_* (exactly one fires per profile) ───
    - name: "phaseP_infra_smoke"
      severity: "warn"
    - name: "phaseP_delta"
      severity: "warn"
    - name: "phaseP_regression"
      severity: "warn"
    - name: "phaseP_schema_verify"
      severity: "warn"
    - name: "phaseP_link_check"
      severity: "warn"
    # ─── Full-profile discovery pipeline (warn — short-circuited by phaseP) ───
    - name: "phase1_code_scan"
      severity: "warn"
    - name: "phase1_5_ripple_and_god_node"
      severity: "warn"
    - name: "phase2a_api_contract_probe"
      severity: "warn"
      required_unless_flag: "--skip-discovery"
    - name: "phase2_browser_discovery"
      severity: "warn"
    - name: "phase2_5_recursive_lens_probe"
      severity: "warn"
    - name: "phase2b_collect_merge"
      severity: "warn"
    - name: "phase2c_enrich_test_goals"
      severity: "warn"
    - name: "phase2c_pre_dispatch_gates"
      severity: "warn"
    - name: "phase2d_crud_roundtrip_dispatch"
      severity: "warn"
    - name: "phase2e_findings_merge"
      severity: "warn"
    - name: "phase2e_post_challenge"
      severity: "warn"
    - name: "phase2f_route_auto_fix"
      severity: "warn"
    - name: "phase2_exploration_limits"
      severity: "warn"
    - name: "phase2_mobile_discovery"
      severity: "warn"
    - name: "phase2_5_visual_checks"
      severity: "warn"
    - name: "phase2_5_mobile_visual_checks"
      severity: "warn"
    - name: "phase2_7_url_state_sync"
      severity: "warn"
    - name: "phase2_8_url_state_runtime"
      severity: "warn"
    - name: "phase2_9_error_message_runtime"
      severity: "warn"
    - name: "phase3_fix_loop"
      severity: "warn"
    - name: "phase4_goal_comparison"
      severity: "warn"
    # ─── Post-discovery (warn) ───
    - name: "unreachable_triage"
      severity: "warn"
    - name: "crossai_review"
      severity: "warn"
      required_unless_flag: "--skip-crossai"
    - name: "write_artifacts"
      severity: "warn"
    - name: "bootstrap_reflection"
      severity: "warn"
  must_emit_telemetry:
    - event_type: "review.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.env_mode_confirmed"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--non-interactive"
    - event_type: "review.api_precheck_completed"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "review.lens_plan_generated"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "review.completed"
      phase: "${PHASE_NUMBER}"
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
    # rcrurd runtime gates
    - event_type: "review.rcrurd_runtime_passed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.rcrurd_runtime_failed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # v2.41.2 — Phase 2b-2.5 enforcement
    - event_type: "review.recursive_probe.preflight_asked"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--non-interactive"
    - event_type: "review.recursive_probe.eligibility_checked"
      phase: "${PHASE_NUMBER}"
    # ─── Conditional gate-fail events (severity=warn) ───
    - event_type: "review.api_precheck_started"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.api_precheck_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.preflight_invariants_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.matrix_staleness_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.matrix_evidence_link_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.evidence_provenance_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.asserted_drift_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.mutation_submit_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.rcrurd_preflight_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.rcrurd_depth_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.rcrurd_post_state_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # P1 v2.49+ — edge case variant evidence
    - event_type: "review.edge_case_variant_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.edge_cases_unavailable"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 34 — tasklist projection enforcement (Bug B)
    - event_type: "review.tasklist_projection_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 33 — 2-leg blocking-gate wrapper (Bug A)
    - event_type: "review.gate_skipped_with_override"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.gate_autofix_attempted"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.gate_autofix_unresolved"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.routed_to_amend"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.aborted_by_user"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.aborted_non_interactive_block"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 35 — finding-ID namespace validator (Bug C)
    - event_type: "review.finding_id_invalid"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # Task 36b — lens dispatch chain (Bug D part 2)
    - event_type: "review.lens_dispatch_emitted"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens_coverage_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # R6 Task 10 — per-lens dispatch telemetry (silent-skip detector).
    # Plan-level review.lens_plan_generated proves a plan was BUILT, but not
    # that each individual lens was actually DISPATCHED. spawn_recursive_probe.py
    # now emits review.lens.<name>.{dispatched,completed,crashed} per worker so
    # Stop hook can detect "plan listed lens-idor but worker never spawned"
    # silent-skip bugs. Severity=warn — surface the skip without hard-blocking
    # (the lens might be legitimately filtered by env_policy/budget cap).
    # Three representative critical lenses enumerated here; remaining 16 lenses
    # follow the same review.lens.<name>.{dispatched,completed,crashed} pattern
    # at runtime (see LENS_MAP in scripts/spawn_recursive_probe.py for the
    # complete list).
    - event_type: "review.lens.lens-idor.dispatched"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-idor.completed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-idor.crashed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-business-coherence.dispatched"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-business-coherence.completed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-business-coherence.crashed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-form-lifecycle.dispatched"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-form-lifecycle.completed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.lens.lens-form-lifecycle.crashed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
  forbidden_without_override:
    - "--override-reason"
    - "--skip-scan"
    - "--skip-discovery"
    - "--fix-only"
    - "--allow-empty-hotfix"
    - "--allow-orthogonal-hotfix"
    - "--allow-no-bugref"
    - "--allow-empty-bugfix"
    - "--skip-crossai"
    - "--skip-lens-plan-gate"  # NEW R3 audit FAIL #13 (Codex review)
---


<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

File paths, code identifiers (G-04, lens-csrf, scan-*.json), commit
messages, CLI commands stay English. AskUserQuestion title + options +
question prose: ngôn ngữ config.
</LANGUAGE_POLICY>


<HARD-GATE>
You MUST follow STEP 1 through STEP 8 in profile-filtered order. Each step
is gated by hooks. Skipping ANY step will be blocked by PreToolUse + Stop
hooks. You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 (`create_task_tracker`)
runs `emit-tasklist.py` — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The
PostToolUse TodoWrite hook auto-writes that signed evidence.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

**Payload ordering (Bug D2 2026-05-04):** Claude Code TodoWrite UI renders
in payload-array order — does NOT auto-sort. On every TodoWrite call
REORDER `todos[]` so active group header + its `in_progress` sub-step
appear FIRST, remaining pending next, completed items LAST. Hierarchy
preserved (group header still precedes its own sub-steps).

For HEAVY step (STEP 3 browser discovery, 947-line source), you MUST
spawn the named subagent via the `Agent` tool (NOT `Task` — Codex
correction #3). DO NOT crawl inline.

Lens phase (STEP 4) is NOT optional unless `--skip-discovery` flag
WITH override-debt entry. AI cannot cherry-pick lens — `LENS_MAP` in
`spawn_recursive_probe.py` is hardcoded; eligibility gate automatic.
Skipping silently detected by Stop hook (review.lens_phase events).
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Subagent overkill cho phase2" | Heavy step empirical 96.5% skip rate without subagent (Codex round-2 confirmed) |
| "Tôi đã hiểu, không cần đọc reference" | References contain step-specific bash commands not in entry |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "Spawn `Task()` như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |
| "Skip lens phase trên small phase" | LENS_MAP hardcoded; eligibility gate auto; Stop hook detects miss |
| "phase4 cần subagent cho gọn" | Audit confirmed phase4 = binary lookup (no formula). Stays inline. |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: vg.block.fired must pair with vg.block.handled or Stop blocks |

## Tasklist policy

Read `_shared/lib/tasklist-projection-instruction.md` and follow it
exactly for the canonical 2-layer projection contract (group headers
+ ↳ sub-items, adapter='claude' for Claude Code sessions, signed
evidence at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`).

Summary: `emit-tasklist.py` writes the profile-filtered
`.vg/runs/<run_id>/tasklist-contract.json` (schema `native-tasklist.v2`).
The slim entry STEP 1 calls it; this skill IMPERATIVELY calls TodoWrite
right after with one todo per `projection_items[]` entry (group headers
+ sub-steps with `↳` prefix). Then calls
`vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`
so `review.native_tasklist_projected` event fires.

Lifecycle:
- `replace-on-start`: first projection replaces stale list. Never append.
- `close-on-complete`: mark all checklist items completed; clear native
  list or replace with sentinel `vg:review phase ${PHASE_NUMBER} complete`.
- `payload-ordering` (Bug D2 2026-05-04): Claude Code TodoWrite UI renders
  in payload-array order, NOT auto-sorted by status. On every TodoWrite
  call REORDER `todos[]` so the active group header + its `in_progress`
  sub-step appear FIRST, remaining pending next, completed items LAST.
  Hierarchy preserved (group header before its own sub-steps).

## Steps (8 STEP sections)

### STEP 1 — preflight (5 light steps)

Read `_shared/review/preflight.md` and follow it exactly.

This step covers:
- `00_gate_integrity_precheck` — T8 gate precheck
- `00_session_lifecycle` — config + run-start
- `0_parse_and_validate` — frontmatter audit + arg validation
- `0a_env_mode_gate` — 3-axis env+mode+scanner HARD gate (v2.42.1)
- `0b_goal_coverage_gate` — TEST-GOALS coverage check
- `0c_telemetry_suggestions` — pull weekly telemetry summary
- `create_task_tracker` — IMPERATIVE TodoWrite + tasklist-projected

After STEP 1.create_task_tracker bash runs, you MUST call TodoWrite
IMMEDIATELY with the projection items from
`.vg/runs/<run_id>/tasklist-contract.json`.

### STEP 2 — code scan + API precheck

Read `_shared/review/code-scan.md` and follow it exactly.

This step covers:
- `phase1_code_scan` — static contract verify + element inventory
- `phase1_5_ripple_and_god_node` — ripple analysis + complexity check
- `phase2a_api_contract_probe` — API endpoint live-call probe (writes
  `${PHASE_DIR}/api-contract-precheck.txt` — must be created in current run)

Use `vg-load --artifact contracts --endpoint <slug>` for per-endpoint
contract slices, NOT flat `cat API-CONTRACTS.md` (audit doc 2026-05-04
line 783 migration).

### STEP 3 — browser discovery (HEAVY, subagent)

Read `_shared/review/discovery/overview.md` AND
`_shared/review/discovery/delegation.md`.

Wrap the spawn with narration (UX baseline req 2):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-review-browser-discoverer spawning "phase ${PHASE_NUMBER} browser scan ${SCOPE_COUNT} routes × ${ROLE_COUNT} roles"
```

Then call:
```
Agent(subagent_type="vg-review-browser-discoverer", prompt=<built from delegation>)
```

Post-return (success):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-review-browser-discoverer returned "<count> views, <slot_count> slots"
```

DO NOT crawl inline. The subagent partitions scope across ≤5 parallel
Haiku scanners via Task tool, aggregates per-view scan-*.json into
RUNTIME-MAP.json, returns DONE / DONE_WITH_CONCERNS / BLOCKED status.

### STEP 4 — lens dispatch (architectural enforcement)

Read `_shared/review/lens-dispatch.md` and follow it exactly.

This step covers:
- `phase2_5_recursive_lens_probe` — eligibility gate (6-precondition),
  3-axis preflight (RECURSION_MODE/PROBE_MODE/TARGET_ENV), manager
  dispatch via `spawn_recursive_probe.py`, aggregation, per-lens telemetry

Lens injection is ARCHITECTURALLY enforced — `LENS_MAP` is hardcoded
in `spawn_recursive_probe.py`; eligibility gate checks 6 preconditions
automatically. AI cannot cherry-pick. Skipping the entire phase requires
`--skip-discovery` flag WITH `--override-reason="<text>"`.

### STEP 4.5 — runtime checks (web/mobile profile)

Read `_shared/review/runtime-checks.md` and follow it exactly.

This step covers 7 sub-steps:
- `phase2_exploration_limits` — exploration boundary enforcement
- `phase2_mobile_discovery` — mobile-profile-specific discovery
- `phase2_5_visual_checks` — visual regression vs design fingerprints
- `phase2_5_mobile_visual_checks` — mobile visual gates
- `phase2_7_url_state_sync` — URL ↔ component-state sync verification
- `phase2_8_url_state_runtime` — runtime URL state coherence
- `phase2_9_error_message_runtime` — error message UX validation

Profile-aware: web-fullstack / web-frontend-only run all 7;
mobile-* substitutes mobile variants; web-backend-only skips entirely.
All markers severity=warn — emit telemetry but don't block run.

### STEP 5 — findings collect + fix loop

Read `_shared/review/findings/collect.md` then `_shared/review/findings/fix-loop.md`.

This step covers:
- `phase2b_collect_merge` — aggregate per-lens findings into FINDINGS.md
- `phase2e_post_challenge` — finding adversarial challenger (audit FAIL #11)
- `phase3_fix_loop` — auto-fix routing per finding severity, exploration
  limits, scope-fix-loop subagent dispatch

### STEP 6 — goal comparison + verdict (inline ref split, NO subagent)

Read `_shared/review/verdict/overview.md` first to determine branch:
- UI_GOAL_COUNT == 0 → `verdict/pure-backend-fastpath.md`
- profile == web-fullstack → `verdict/web-fullstack.md`
- other web profiles → `verdict/profile-branches.md`

This step covers `phase4_goal_comparison`. Audit confirmed (2026-05-03):
binary lookup (READY/BLOCKED), no weighted formula. Therefore stays
inline-split across 4 sub-refs, NOT delegated to a subagent. `agents/
vg-review-goal-scorer/` MUST NOT exist (test enforces this).

### STEP 7 — CrossAI review (UNCHANGED behavior)

Read `_shared/review/crossai.md` and follow it exactly.

This step covers `crossai_review` — invokes shared CrossAI helper with
LABEL=`review-check`. Writes `${PHASE_DIR}/crossai/review-check.xml`.
Verdict (PASS/CONCERNS/FAIL) emitted via `crossai.verdict` event.

### STEP 8 — close (artifacts + reflection + run-complete + tasklist clear)

Read `_shared/review/close.md` and follow it exactly.

This step covers `complete` (588-line super-step in backup):
- PIPELINE-STATE.json update (status=reviewed)
- v2.6.1 auto-resolve hotfix debt entries from prior phases
- vg-reflector subagent spawn (HEAVY — narrate-spawn wrapper)
- Run-complete orchestrator gate (validates contract)
- Tasklist clear via close-on-complete sentinel

## Profile shortcut branches (when --mode=infra-smoke / regression / schema-verify / link-check)

Read `_shared/review/profile-shortcuts.md`.

Mode flag short-circuits to one of `phaseP_*` steps that bypasses the
full discovery pipeline. Example: `--mode=infra-smoke` runs only HTTP
liveness checks; `--mode=schema-verify` checks DB schema vs migration
files. Each profile has own marker; body has internal REVIEW_MODE gate.

## Delta mode (when --mode=delta)

Read `_shared/review/delta-mode.md`.

Change-only mode for `phaseP_delta`: scans only files changed since
last review-passed run. Faster than full but may miss regressions in
unchanged code paths. Auto-fallback to full on first review of a phase.

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

## Architectural rationale (R3 pilot)

This slim entry replaces a 7,803-line monolithic review.md. The 39 step
markers + must_emit_telemetry events are unchanged — only on-disk layout
changed. HEAVY step phase2_browser_discovery (947 lines) is extracted
to subagent `vg-review-browser-discoverer` to fight the empirical 96.5%
inline-skip rate. phase4_goal_comparison (829 lines) is split inline
across `verdict/{overview, pure-backend-fastpath, web-fullstack,
profile-branches}.md` — audit confirmed binary lookup (no formula).
All consumer reads of PLAN/API-CONTRACTS/TEST-GOALS use `vg-load`
(closes Phase F Task 30 for vg:review).

Companion artifacts:
- Spec: `docs/superpowers/specs/2026-05-03-vg-review-design.md`
- Plan: `docs/superpowers/plans/2026-05-03-vg-r3-review-pilot.md`
- Backup: `commands/vg/.review.md.r3-backup` (full pre-refactor 7803 lines)
- Subagent: `agents/vg-review-browser-discoverer/SKILL.md`
- Token impact: ~25-30K tokens saved per review session vs monolithic
