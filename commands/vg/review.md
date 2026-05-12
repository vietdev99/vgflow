---
name: vg:review
description: Post-build review — code scan + browser discovery + matrix INTENT → RUNTIME-MAP (discovery-only)
argument-hint: "<phase> [--target-env=local|staging|sandbox|prod | --local | --sandbox | --staging | --prod] [--mode=full|delta|regression|schema-verify|link-check|infra-smoke] [--scanner=haiku-only|codex-inline|codex-supplement|gemini-supplement|council-all] [--skip-deepscan] [--with-deepscan] [--non-interactive] [--skip-scan] [--skip-discovery] [--fix-only] [--skip-crossai] [--skip-qa-check] [--evaluate-only] [--retry-failed] [--re-scan-goals=G-XX,G-YY] [--dogfood] [--force] [--full-scan] [--allow-no-crud-surface] [--skip-lens-plan-gate] [--auto-chain] [--no-chain]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - TodoWrite
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
  - BashOutput
runtime_contract:
  # OHOK Batch 2 C4 (2026-04-22): full-coverage contract.
  # Previously contract listed only 3 markers (0_parse, 0b_goal, complete) —
  # 19 other steps could silently skip without orchestrator detection.
  # Now every tasklist-visible step is declared; optional / profile-specific / already-
  # internally-guarded ones use severity=warn so missing emits telemetry
  # without blocking run (body has own enforcement).
  must_write:
    # Issue #142: these are review-specific outputs, not phase artifacts
    # subject to profile filter. profile_aware: false ensures missing →
    # BLOCK regardless of phase profile (was silent profile_skip WARN).
    - path: "${PHASE_DIR}/RUNTIME-MAP.json"
      profile_aware: false
      content_min_bytes: 80
      must_be_created_in_run: true
      check_provenance: true
    - path: "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
      profile_aware: false
      content_min_bytes: 80
      must_be_created_in_run: true
      check_provenance: true
    - path: "${PHASE_DIR}/api-docs-check.txt"
      content_min_bytes: 60
      required_unless_flag: "--skip-discovery"
      must_be_created_in_run: true
      check_provenance: true
    # v2.47.2 — mandatory API precheck before browser discovery. This must
    # be created by the CURRENT run so force-review cannot reuse a stale
    # probe/report from an earlier Codex session.
    - path: "${PHASE_DIR}/api-contract-precheck.txt"
      content_min_bytes: 60
      required_unless_flag: "--skip-discovery"
      must_be_created_in_run: true
      check_provenance: true
    - path: "${PHASE_DIR}/REVIEW-LENS-PLAN.json"
      content_min_bytes: 120
      required_unless_flag: "--skip-discovery"
    # CrossAI review evidence. Review sets LABEL="review-check" and the
    # shared invoker writes `${OUTPUT_DIR}/${LABEL}.xml`. This must be
    # specific to review-check so stale blueprint result-*.xml files cannot
    # satisfy the review gate.
    - path: "${PHASE_DIR}/crossai/review-check.xml"
      content_min_bytes: 80
      required_unless_flag: "--skip-crossai"
    # v2.5.1 anti-forge: Haiku scan JSON files prove step 2b-2 actually
    # spawned scanners instead of just touching marker. Waived for
    # non-web profiles (no browser discovery needed).
    - path: "${PHASE_DIR}/scan-*.json"
      glob_min_count: 1
      required_unless_flag: "--skip-discovery"
    # Task 36b — lens dispatch chain artifacts (waived if --probe-mode skip).
    # v2.67.0 #158: tightened guards — content_min_bytes raised + structural
    # content_required_sections added, so a stub plan/matrix cannot satisfy
    # the gate when the probe ran. Required keys come from
    # `lens-dispatch/emit-dispatch-plan.py` (always emits "phase",
    # "dispatches", "plan_hash") and `aggregators/lens-coverage-matrix.py`
    # (always emits "Coverage Matrix" title + "Plan hash:" header).
    - path: "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"
      content_min_bytes: 500
      content_required_sections: ['"dispatches"', '"phase"', '"plan_hash"']
      required_unless_flag: "--probe-mode-skip"
    - path: "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
      content_min_bytes: 300
      content_required_sections: ["Coverage Matrix", "Plan hash"]
      required_unless_flag: "--probe-mode-skip"
  must_touch_markers:
    # ─── Hard gates (block) — foundational, always run ───
    - "00_gate_integrity_precheck"
    - "0_parse_and_validate"
    - "0b_goal_coverage_gate"
    - "complete"

    # ─── Session lifecycle + planning (warn) — advisory, not blocking ───
    - name: "00_session_lifecycle"
      severity: "warn"
    - name: "create_task_tracker"
      severity: "warn"
    # v2.42.1 — env+mode+scanner gate: HARD block. AI MUST run provider-native prompt
    # for env/mode/scanner before proceeding. Closes silent-default gap on phases
    # 3.3/3.4a/3.4b where review ran without user choosing env or scanner depth.
    # Waiver: --non-interactive flag OR (--target-env + --mode + --scanner all on CLI).
    - name: "0a_env_mode_gate"
      required_unless_flag: "--non-interactive"
    - name: "phase_profile_branch"
      severity: "warn"
    - name: "0c_telemetry_suggestions"
      severity: "warn"

    # ─── Profile-exclusive phaseP_* (warn) — exactly one fires per profile ───
    # Body has own enforcement via REVIEW_MODE gate. Missing marker on
    # non-matching profile = expected; emits contract.marker_warn telemetry.
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
    # v2.68.0 C2 — QA-Checker meta-verification (vg-review-qa-checker).
    # The dedicated fix-loop tail spawn checks that fix commits actually
    # address the original review finding (not suppression hacks / false
    # fixes). v2.69.0 T3: marker added to frontmatter (was doc-only) +
    # flipped to required_unless_flag. Review BLOCKs when QA-Checker
    # FAILs and --skip-qa-check absent. Escape hatch logs override-debt.
    - name: "phase3d_5_qa_checker"
      required_unless_flag: "--skip-qa-check"

    # ─── Post-discovery (warn) ───
    - name: "phase2.5_matrix_intent"
      severity: "warn"
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
    # v2.5.1 anti-forge: tasklist visibility at flow start
    - event_type: "review.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    # Native task UI must be a visible projection of tasklist-contract.json.
    # This is emitted only through `vg-orchestrator tasklist-projected`,
    # not generic emit-event, so Claude/Codex must bind their native UI to
    # the harness contract before execution continues.
    - event_type: "review.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.started"
      phase: "${PHASE_NUMBER}"
    # v2.42 — env+mode confirmation. Required unless --non-interactive
    # OR all axes (--target-env + --mode) already on CLI.
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
    # Task 23 (rcrurd) — runtime gate per mutation goal.
    # rcrurd_runtime_passed = informational; rcrurd_runtime_failed = warn-fire
    # so the Stop hook can detect silent-skip on phases with mutation goals.
    - event_type: "review.rcrurd_runtime_passed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.rcrurd_runtime_failed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    # v2.41.2 — Phase 2b-2.5 enforcement (closes regression from v2.40.0
    # that nested 2b-2.5 inside phase2_browser_discovery without contract)
    - event_type: "review.recursive_probe.preflight_asked"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--non-interactive"
    - event_type: "review.recursive_probe.eligibility_checked"
      phase: "${PHASE_NUMBER}"
    # ─── Conditional gate-fail events (severity=warn — only fire on specific
    # blocked paths; declared so Stop hook can validate emission on those
    # paths and detect silent-skip when expected gate didn't fire) ───
    - event_type: "review.api_precheck_started"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.api_precheck_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.preflight_invariants_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.deep_test_spec_blocked"
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
    # P1 v2.49+ — edge case variant evidence (per-goal × variant loop)
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
    # v2.69.0 T3 (C2) — escape hatch for QA-Checker meta-verification (Phase fix-loop tail)
    - "--skip-qa-check"
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

### Tasklist projection (REQUIRED before any step-active)

Read `_shared/lib/tasklist-projection-instruction.md` and follow it
verbatim. The PreToolUse-bash hook will BLOCK every `step-active` call
in this slim entry until `.vg/runs/${RUN_ID}/.tasklist-projected.evidence.json`
exists.

Claude TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by PostToolUse depth
check (Task 44b Rule V2).

Codex MUST keep the visible plan compact. Do not paste the full hierarchy
into Codex `update_plan`; use `codex_plan_window` from the contract and show
at most 6 rows: active group/step first, next 2-3 pending steps, completed
groups collapsed, and `+N pending`.

<TASKLIST_POLICY>
**Native task UI projection is REQUIRED.**

Source of truth:
1. `.vg/runs/{run_id}/tasklist-contract.json` — canonical checklist for this run.
2. `.vg/events.db` — `review.tasklist_shown`, `review.native_tasklist_projected`, `step.active`, `step.marked`.
3. `${PHASE_DIR}/.step-markers/...` — durable completion markers.

Provider adapters:
- **Claude CLI:** use native Claude tasklist projection. Prefer `TodoWrite`
  with the full two-layer hierarchy from `projection_items[]`; each todo
  `content` MUST start with the contract checklist/step id or title. If this
  Claude runtime exposes `TaskCreate`/`TaskUpdate`, that adapter is also
  acceptable. Do not create ad-hoc todos outside `tasklist-contract.json`.
- **Codex CLI:** project only a compact plan window from `codex_plan_window`;
  preserve current active group/step identity, but do not create one visible
  item per `projection_items[]` row. Update the compact window before/after
  each step and keep it at 6 visible rows or fewer.
- **Fallback:** only if the runtime exposes no native task UI, use `vg-orchestrator run-status --pretty` before and after each step and record adapter `fallback`.

Lifecycle:
- `replace-on-start`: the first native projection MUST replace any stale task
  list from a previous workflow. Never append current review items onto a
  previous workflow's list.
- `close-on-complete`: before reporting success, mark all review checklist
  items completed. Then clear the native list if supported; otherwise replace
  it with one completed sentinel item: `vg:review phase ${PHASE_NUMBER} complete`.

Mandatory binding:
1. After `emit-tasklist.py` prints the taskboard and `Tasklist contract: ...`, read that contract.
2. Project to the runtime-native task UI before phase execution continues:
   Claude full hierarchy; Codex compact window only.
3. Immediately call:
   ```bash
   "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator tasklist-projected --adapter auto
   # auto locks to claude, codex, or fallback from runtime env
   ```
4. At each step start, update the native UI to show the active step and call `vg-orchestrator step-active <step_name>`.
5. At each step end, write the marker, update the native UI to show completion, and call `vg-orchestrator mark-step review <step_name>`.

Do not improvise a separate checklist. The native UI is a projection of `tasklist-contract.json`; the harness contract remains authoritative.

Long-running work still needs visible narration: run Bash jobs over 30s in background and poll with `BashOutput`; summarize Task subagent progress before and after spawning.

**Dynamic sub-task append (RULE)** — projection từ emit-tasklist là baseline,
KHÔNG cứng. Khi AI execute group/step phức tạp (e.g. `phase2_browser_discovery`
với nhiều view, `phase2_5_recursive_lens_probe` với nhiều lens), AI PHẢI append
child todos vào group đó để user thấy real-time progress.

Pattern for Claude native task UI (tolerant hook B11.6+):
- Initial: 1 todo per group header
- During execution: TodoWrite update — keep group header, append children
  với title `  ↳ <id>: <one-line desc>` (status: pending → in_progress → completed)
- Examples cho review:
  - `  ↳ View /campaigns: 12 actions captured`
  - `  ↳ Lens lens-modal-state: 3 modals probed (1 BLOCKED — focus trap)`
  - `  ↳ phase2c G-04: enriched with success criteria`

Cho operator visibility "AI sẽ làm gì tiếp / tiến độ tới đâu" mà không phải
đọc Bash log dài.

Codex exception: keep these dynamic details folded into the active compact
plan row or the next row. Do not exceed the 6-row `codex_plan_window` budget.

**Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `BLOCK (chặn)`, `Foundation (nền tảng) drift detected (phát hiện lệch hướng)`, `legacy-v1 (định dạng cũ v1)`, `UNREACHABLE (không tiếp cận được)`. Không áp dụng: file path, code identifier (`D-XX`, `git`, `pnpm`), config tag values, lần lặp lại trong cùng message.
</TASKLIST_POLICY>

<rules>
1. **Phase profile drives prerequisites (P5, v1.9.2)** — `detect_phase_profile` chooses WHICH artifacts are required:
   - `feature` (default) → SPECS + CONTEXT + PLAN + API-CONTRACTS + TEST-GOALS + SUMMARY
   - `infra` → SPECS + PLAN + SUMMARY (no TEST-GOALS, no API-CONTRACTS — goals from SPECS success_criteria)
   - `hotfix` / `bugfix` → SPECS + PLAN + SUMMARY (reuse parent goals or issue ref)
   - `migration` → SPECS + PLAN + SUMMARY + ROLLBACK
   - `docs` → SPECS only
   Missing required artifact → BLOCK via `block_resolve` (L2 architect proposal), NOT anti-pattern "list 3 options".
2. **Review mode branches on profile** — `feature=full` (browser + surfaces) | `infra=infra-smoke` (parse + run success_criteria bash) | `hotfix=delta` | `bugfix=regression` | `migration=schema-verify` | `docs=link-check`.
3. **Discovery-first** — AI explores the running app organically. No hardcoded checklists. No pre-scripted paths.
4. **Bấm → Nhìn → List → Đánh giá** — at every view: snapshot, evaluate data + actions, click each, observe result.
5. **Fix in review, verify in test** — review handles discovery + fix. Test handles clean goal verification only.
6. **RUNTIME-MAP is ground truth** — produced from actual browser interaction, not code guessing.
7. **Flexible format** — AI chooses best representation per page (tree, list, flow). No mandated table structure.
8. **Exploration limits (hard-enforced, v1.14.4+)** — max 50 actions/view, 200 total, 30 min wall time. Counted by `phase2_exploration_limits` step after discovery. Threshold breach → WARN + log to PIPELINE-STATE.json metrics (not block; discovery already done, but signals noisy RUNTIME-MAP). Thresholds overridable via `config.review.max_actions_per_view|max_actions_total|max_wall_minutes`.
9. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
10. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    `create_task_tracker` preflight runs filter-steps.py to count expected steps for `$PROFILE`.
    Browser-based steps (phase 2 discovery) carry `profile="web-fullstack,web-frontend-only"` — skipped for backend-only/cli/library.
11. **Resume model (v1.14.4+)** — no mid-phase-2 resume. Step-level idempotency via `.step-markers/*.done` + per-view atomic `scan-*.json` is sufficient. If discovery dies mid-run, re-run `/vg:review {phase}` from scratch OR `/vg:review {phase} --retry-failed` (requires RUNTIME-MAP already written).
12. **Post-build test-spec gate (v3.6.6)** — first full review requires `/vg:test-spec {phase}` artifacts (`DEEP-TEST-SPECS.md`, `LIFECYCLE-SPECS.json`, `TEST-FIXTURE-DAG.json`, `TEST-EXECUTION-PLAN.json`, `TEST-SPEC-LOCALIZER/PROMPT.md`, `PLAYWRIGHT-SPEC-PLAN.md`). Review consumes them as the lifecycle contract; it does not invent deep test specs late.
</rules>

<objective>
Step 4 of V5.1 pipeline. Replaces old "audit" step. Combines static code scan + live browser discovery + iterative fix loop + goal comparison.

Pipeline: specs → scope → blueprint → build → test-spec → **review** → test → accept

4 Phases:
- Phase 1: CODE SCAN — grep contracts + count elements (fast, automated, <10 sec)
- Phase 2: BROWSER DISCOVERY — MCP Playwright organic exploration → RUNTIME-MAP
- Phase 3: FIX LOOP — errors found → fix → redeploy → re-discover (max 5 iterations, v2.65.0 A4)
- Phase 4: GOAL COMPARISON — map TEST-GOALS to discovered paths → weighted gate
</objective>

<process>

**Config:** Read ${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/config-loader.md first.

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

<CRITICAL_MCP_RULE>
**BEFORE any browser interaction**, you MUST run the Playwright lock claim:
```bash
SESSION_ID="vg-${PHASE}-review-$$"
PLAYWRIGHT_SERVER=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
# Auto-release lock on exit (normal/error/interrupt). Prevents leak if process dies mid-scan.
trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
```
Then use `mcp__${PLAYWRIGHT_SERVER}__` as prefix for ALL browser tool calls.

**NEVER call `plugin:playwright:playwright` directly.** Other sessions (Codex, other tabs) may be using it.
If claim returns `playwright3`, your tools are `mcp__playwright3__browser_navigate`, `mcp__playwright3__browser_snapshot`, etc.
If ALL 5 servers locked → BLOCK. The lock manager auto-sweeps stale locks (TTL 1800s + dead-PID check)
on every claim — if still no slot free, it's genuinely contended. Do NOT manually cleanup other sessions' locks.
</CRITICAL_MCP_RULE>

### Preflight section (extracted v2.70.0)

Read `_shared/review/preflight.md` and follow it exactly.
Includes 7 steps: 00_gate_integrity_precheck, 00_session_lifecycle, 0_parse_and_validate, 0a_env_mode_gate, 0b_goal_coverage_gate, 0c_telemetry_suggestions, create_task_tracker.

### Phase profile branch (Section 2 — extracted v2.70.0)

Read `_shared/review/phase-p-variants.md` and follow it exactly.
Includes 6 steps: phase_profile_branch, phaseP_infra_smoke, phaseP_delta, phaseP_regression, phaseP_schema_verify, phaseP_link_check.


### Code scan section (extracted v2.70.0 T3)

Read `_shared/review/code-scan.md` and follow it exactly.
Includes 2 steps: phase1_code_scan, phase1_5_ripple_and_god_node.


### API contract probe + browser discovery (extracted v2.70.0 T4)

Read `_shared/review/api-and-discovery.md` and follow it exactly.
Includes 2 steps: phase2a_api_contract_probe, phase2_browser_discovery.


### Lens probe + findings derivation (extracted v2.70.0 T5)

Read `_shared/review/lens-and-findings.md` and follow it exactly.
Includes 8 steps: phase2_5_recursive_lens_probe, phase2b_collect_merge, phase2c_enrich_test_goals, phase2c_pre_dispatch_gates, phase2d_crud_roundtrip_dispatch, phase2e_findings_merge, phase2e_post_challenge, phase2f_route_auto_fix.


### Exploration limits + mobile + visual checks (extracted v2.70.0 T6)

Read `_shared/review/limits-and-mobile.md` and follow it exactly.
Includes 4 steps: phase2_exploration_limits, phase2_mobile_discovery, phase2_5_visual_checks, phase2_5_mobile_visual_checks.


### URL state + error message runtime (extracted v2.70.0 T7)

Read `_shared/review/url-and-error.md` and follow it exactly.
Includes 3 steps: phase2_7_url_state_sync, phase2_8_url_state_runtime, phase2_9_error_message_runtime.

### Matrix INTENT (discovery-only, v4.0)

Compute 3-verdict intent: `READY` / `BLOCKED` / `NOT_SCANNED`. Fix-loop + final verdict deferred to `/vg:test` (Step 3 + Step 5).

Read `_shared/review/matrix-intent.md` and follow it exactly.

### Close section (extracted v2.70.0 T9 — final extraction)

Read `_shared/review/close.md` and follow it exactly.
Includes 5 steps: unreachable_triage, crossai_review, write_artifacts, bootstrap_reflection, complete.

</process>

<success_criteria>
- Code scan completed (contract verify + element inventory)
- Browser discovery explored all reachable views organically
- RUNTIME-MAP.json produced with actual runtime observations (canonical JSON)
- RUNTIME-MAP.md derived from JSON (human-readable)
- Matrix INTENT computed (READY/BLOCKED/NOT_SCANNED)
- TEST-GOALS mapped to discovered paths
- GOAL-COVERAGE-MATRIX.md shows weighted goal readiness
- Gate passed (weighted: 100% critical, 80% important, 50% nice-to-have)
- Discovery state saved (resumable)
</success_criteria>
