---
name: vg:review
description: Post-build review — code scan + browser discovery + fix loop + goal comparison → RUNTIME-MAP
argument-hint: "<phase> [--target-env=local|staging|sandbox|prod | --local | --sandbox | --staging | --prod] [--mode=full|delta|regression|schema-verify|link-check|infra-smoke] [--scanner=haiku-only|codex-inline|codex-supplement|gemini-supplement|council-all] [--skip-deepscan] [--with-deepscan] [--non-interactive] [--skip-scan] [--skip-discovery] [--fix-only] [--skip-crossai] [--skip-qa-check] [--evaluate-only] [--retry-failed] [--re-scan-goals=G-XX,G-YY] [--dogfood] [--force] [--full-scan] [--allow-no-crud-surface] [--skip-lens-plan-gate]"
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
    - name: "phase3_fix_loop"
      severity: "warn"
    # v2.68.0 C2 — QA-Checker meta-verification (vg-review-qa-checker).
    # The dedicated fix-loop tail spawn checks that fix commits actually
    # address the original review finding (not suppression hacks / false
    # fixes). v2.69.0 T3: marker added to frontmatter (was doc-only) +
    # flipped to required_unless_flag. Review BLOCKs when QA-Checker
    # FAILs and --skip-qa-check absent. Escape hatch logs override-debt.
    - name: "phase3d_5_qa_checker"
      required_unless_flag: "--skip-qa-check"
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
   "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator tasklist-projected --adapter auto
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
</rules>

<objective>
Step 4 of V5.1 pipeline. Replaces old "audit" step. Combines static code scan + live browser discovery + iterative fix loop + goal comparison.

Pipeline: specs → scope → blueprint → build → **review** → test → accept

4 Phases:
- Phase 1: CODE SCAN — grep contracts + count elements (fast, automated, <10 sec)
- Phase 2: BROWSER DISCOVERY — MCP Playwright organic exploration → RUNTIME-MAP
- Phase 3: FIX LOOP — errors found → fix → redeploy → re-discover (max 5 iterations, v2.65.0 A4)
- Phase 4: GOAL COMPARISON — map TEST-GOALS to discovered paths → weighted gate
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `.claude/commands/vg/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

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

### Fix loop + goal comparison (extracted v2.70.0 T8 — largest section)

Read `_shared/review/fix-loop-and-goals.md` and follow it exactly.
Includes 2 steps: phase3_fix_loop (max 5 iterations), phase4_goal_comparison.

<step name="unreachable_triage" mode="full">
## UNREACHABLE Triage — legacy guard (v1.14.0+)

**Từ v1.14.0, triage chạy INLINE trong Phase 4d (ngay trước cổng 100%).** Step này chỉ còn là **guard** cho trường hợp legacy flow đi vòng (ví dụ `--skip-discovery` + `--fix-only` nhảy qua 4d). Nếu `.unreachable-triage.json` đã tồn tại từ 4d → skip; nếu chưa → chạy fallback.

```bash
TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
if [ -f "$TRIAGE_JSON" ]; then
  echo "ℹ Triage đã chạy inline ở Phase 4d — skip legacy guard."
else
  session_mark_step "4f-unreachable-triage-legacy"
  echo ""
  echo "🔍 Legacy path: UNREACHABLE triage fallback (4d bị bỏ qua)..."
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
  if type -t triage_unreachable_goals >/dev/null 2>&1; then
    triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
  else
    echo "⚠ unreachable-triage.sh missing — triage skipped" >&2
  fi
fi
```

**Lưu ý v1.14.0+:** Triage không còn là "report-only cho accept gate". Triage SINH action_required, review 4d ÁP DỤNG autonomous action (mark_deferred/mark_manual) và BLOCK gate cho action cần người duyệt (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag). Xem spec section A.2.
</step>

<step name="crossai_review" mode="full">
## CrossAI Review (mandatory when CLIs are configured)

**If config.crossai_clis is empty, emit an explicit skip note and continue.**
**If --skip-crossai is present, it must have override-debt evidence because
objective review is otherwise a silent quality downgrade.**

Prepare context with RUNTIME-MAP + GOAL-COVERAGE-MATRIX + TEST-GOALS.
Set `$LABEL="review-check"`. Follow crossai-invoke.md exactly: child CLIs run
through the isolated CrossAI runner and the gate consumes normalized
`${PHASE_DIR}/crossai/review-check.xml`, not raw child XML.

Required evidence when not skipped:
- `${PHASE_DIR}/crossai/review-check.xml`
- `crossai.verdict` telemetry event

### v2.66.1 #154 — verdict-gated marker write (Phase 2c)

The `crossai_review.done` marker write is now **verdict-gated + ok_count
checked**. Previously, when all 3 reviewers failed (CLI missing / auth missing
/ path bug / TLS chain) the aggregator emitted `<verdict>inconclusive</verdict>`
with `<ok_count>0</ok_count>` but the orchestrator still wrote
`.step-markers/review/crossai_review.done`. `/vg:next` then skipped re-running
CrossAI because the marker existed.

**Gating rule (condition check):** only write `crossai_review.done` when
`verdict in {pass, flag, ok, partial}` AND `ok_count > 0`. Otherwise write
`crossai_review.inconclusive` (different file name) so `/vg:next` knows to
re-run on the next invocation.

The shared writer enforces this rule in one place:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/crossai-marker-write.py \
  --marker-dir "${PHASE_DIR}/.step-markers/review" \
  --step crossai_review \
  --report-json "${PHASE_DIR}/crossai/review-check.report.json"
# Exit code 0 = .done written (verdict pass/flag, ok_count > 0).
# Exit code 2 = .inconclusive written (verdict inconclusive OR ok_count == 0)
#               — orchestrator must re-run CrossAI on next /vg:next.
# Exit code 1 = IO / argument error.
```

The writer derives verdict + ok_count from the aggregator report JSON
emitted by `crossai-normalize-results.py`, so review.md does not duplicate
the gating logic.
</step>

<step name="write_artifacts" mode="full">
## Write Final Artifacts

**Write order: JSON first, then derive MD from it.**

**1. `${PHASE_DIR}/RUNTIME-MAP.json`** — canonical JSON (source of truth). MUST be written FIRST.
**2. `${PHASE_DIR}/RUNTIME-MAP.md`** — derived from JSON (human-readable). Written AFTER JSON.
**3. `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`** — from Phase 4
**4. `${PHASE_DIR}/element-counts.json`** — from Phase 1b

### MANDATORY ARTIFACT VALIDATION (do NOT skip)

After writing all files, verify they exist before committing:
```
Required files — BLOCK commit if ANY missing:
  ✓ ${PHASE_DIR}/RUNTIME-MAP.json     ← downstream /vg:test reads this, NOT .md
  ✓ ${PHASE_DIR}/RUNTIME-MAP.md
  ✓ ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md

Use Glob to confirm each file exists. If RUNTIME-MAP.json is missing,
you MUST create it before proceeding. The .md alone is NOT sufficient.
```

Commit:
```bash
git add ${PHASE_DIR}/RUNTIME-MAP.json ${PHASE_DIR}/RUNTIME-MAP.md \
       ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md ${PHASE_DIR}/element-counts.json \
       ${SCREENSHOTS_DIR}/
# UNREACHABLE-TRIAGE artifacts (only exist if triage ran — i.e., any UNREACHABLE goal)
[ -f "${PHASE_DIR}/UNREACHABLE-TRIAGE.md" ]   && git add "${PHASE_DIR}/UNREACHABLE-TRIAGE.md"
[ -f "${PHASE_DIR}/.unreachable-triage.json" ] && git add "${PHASE_DIR}/.unreachable-triage.json"
git commit -m "review({phase}): RUNTIME-MAP — {views} views, {actions} actions, gate {PASS|BLOCK}"
```
</step>

<step name="bootstrap_reflection" mode="full">
## End-of-Step Reflection (v1.15.0 Bootstrap Overlay)

Before closing review, spawn the **reflector** subagent to analyze this step's
artifacts + user messages + telemetry and draft learning candidates for user
review. Primary path for project self-adaptation.

**Skip conditions** (reflection does nothing, exit 0):
- `.vg/bootstrap/` directory absent (project hasn't opted in)
- `config.bootstrap.reflection_enabled == false` (user disabled)
- Review verdict = `FAIL` with fatal errors (reflect when next review succeeds)

### Run

```bash
BOOTSTRAP_DIR=".vg/bootstrap"
if [ ! -d "$BOOTSTRAP_DIR" ]; then
  # Bootstrap not opted in — skip silently
  :
else
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-review-${REFLECT_TS}.yaml"
  USER_MSG_FILE="${VG_TMP}/reflect-user-msgs-${REFLECT_TS}.txt"

  # Extract user messages sent during this step from Claude transcript (if accessible).
  # If no transcript API, reflector uses artifacts + telemetry + git log only.
  # Orchestrator may populate USER_MSG_FILE from session context.
  : > "$USER_MSG_FILE"

  # Filter telemetry entries to this phase+step within last 4 hours
  TELEMETRY_SLICE="${VG_TMP}/reflect-telemetry-${REFLECT_TS}.jsonl"
  grep -E "\"phase\":\"${PHASE}\".*\"command\":\"vg:review\"" "${PLANNING_DIR}/telemetry.jsonl" 2>/dev/null \
    | tail -200 > "$TELEMETRY_SLICE" || true

  # Collect override-debt entries created in this step
  OVERRIDE_SLICE="${VG_TMP}/reflect-overrides-${REFLECT_TS}.md"
  grep -E "\"step\":\"review\"" "${PLANNING_DIR}/OVERRIDE-DEBT.md" 2>/dev/null > "$OVERRIDE_SLICE" || true

  echo "📝 Running end-of-step reflection (Haiku, isolated context)..."
fi
```

### Spawn reflector agent (isolated Haiku)

Use Agent tool with skill `vg-reflector`, model `haiku`, fresh context:

```
Agent(
  description="End-of-step reflection for review phase {PHASE}",
  subagent_type="general-purpose",
  prompt="""
Use skill: vg-reflector

Arguments:
  STEP           = "review"
  PHASE          = "{PHASE}"
  PHASE_DIR      = "{PHASE_DIR absolute path}"
  USER_MSG_FILE  = "{USER_MSG_FILE}"
  TELEMETRY_FILE = "{TELEMETRY_SLICE}"
  OVERRIDE_FILE  = "{OVERRIDE_SLICE}"
  ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
  REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
  OUT_FILE       = "{REFLECT_OUT}"

Read .claude/skills/vg-reflector/SKILL.md and follow workflow exactly.
Do NOT read parent conversation transcript — echo chamber forbidden.
Output max 3 candidates with evidence to OUT_FILE.
"""
)
```

### Interactive promote flow (user gates)

After reflector exits, parse OUT_FILE. If candidates found, show to user:

```
📝 Reflection — review phase {PHASE} found {N} learning(s):

[1] {title}
    Type: {type}
    Scope: {scope}
    Evidence: {count} items — {sample}
    Confidence: {confidence}

    → Proposed: {target summary}

    [y] ghi sổ tay  [n] reject  [e] edit inline  [s] skip lần này

[2] ...

User gõ: y/n/e/s cho từng item, hoặc "all-defer" để bỏ qua toàn bộ.
```

For `y` → delegate to `/vg:learn --promote L-{id}` internally (validates schema,
dry-run preview, git commit).

For `n` → append to REJECTED.md with user reason.

For `e` → interactive field-by-field edit loop (not external editor):
```
Editing [1]:
  (1) title: "{current}"
  (2) scope: {current}
  (3) prose: "{current}"
  (4) target_step: {current}
  Field to edit? [1-4/done]: _
```

For `s` → leave candidate in `.vg/bootstrap/CANDIDATES.md`, user reviews later via `/vg:learn --review`.

### Emit telemetry

```bash
emit_telemetry "bootstrap.reflection_ran" PASS \
  "{\"step\":\"review\",\"phase\":\"${PHASE}\",\"candidates\":${CANDIDATE_COUNT:-0}}"
```

### Failure mode

Reflector crash or timeout → log warning, continue to `complete` step. Never block review completion.

```
⚠ Reflection failed — review completes normally. Check .vg/bootstrap/logs/
```
</step>

<step name="complete">
**Update PIPELINE-STATE.json:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'reviewed'; s['pipeline_step'] = 'review-complete'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```

**v2.6.1 (2026-04-26): Auto-resolve hotfix debt entries from prior phases.**

If THIS phase's review ran clean (no `--allow-orthogonal-hotfix` /
`--allow-no-bugref` / `--allow-empty-bugfix` overrides hit), prior phases'
OPEN debt entries with matching gate_id auto-resolve. Closes AUDIT.md D2 H4
(hotfix overrides had no natural resolution path → debt piled up forever).

Each gate_id maps to a specific re-run condition that the current clean
review proves: if review passed without orthogonal-hotfix override, the
"goal-coverage" condition is satisfied for prior phases too.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
if type -t override_auto_resolve_clean_run >/dev/null 2>&1; then
  # Only resolve if THIS phase didn't fall back to the override itself
  if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
    override_auto_resolve_clean_run "review-goal-coverage" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
    override_auto_resolve_clean_run "bugfix-bugref-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
    override_auto_resolve_clean_run "bugfix-code-delta-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
fi
```

**Display — VERDICT-AWARE next steps (MANDATORY format).**

The closing message MUST follow this structure regardless of orchestrator (Claude / Codex / Gemini).
Every finding section MUST end with a concrete actionable command, not just a description.

### When verdict = PASS
```
Review complete for Phase {N} — PASS.
  Goals: {ready}/{total} READY ({pct}%)
  Gate: PASS (critical {C}/{C} 100%, important {I}/{I_total} ≥80%)
  Artifacts: RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md{REVIEW_FEEDBACK_SUFFIX}

Next:
  /vg:test {phase}            # codegen + run regression suite
```

### When verdict = FLAG (passed but with improvements)
```
Review complete for Phase {N} — FLAG ({N} non-blocking findings).
  Goals: {ready}/{total} READY
  Gate: PASS-WITH-FLAGS

Findings (improvements — non-blocking):
  - [Med] {one-line summary} → fix at {file:line}, then commit
  - [Low] {one-line summary} → defer or fix at {file:line}
  ... (full detail in REVIEW-FEEDBACK.md)

Next (pick one):
  /vg:test {phase}                          # proceed — flags are advisory
  edit {file:line}; git commit; /vg:next    # fix flags first, then continue
```

### When verdict = BLOCK (cannot proceed)
```
Review complete for Phase {N} — BLOCK.
  Goals: {ready}/{total} READY ({blocked} BLOCKED, {failed} FAILED, {unreach} UNREACHABLE)
  Gate: BLOCK ({reason — e.g., "critical goal G-03 FAILED" or "infra success_criteria 1/8 READY"})

Findings (severity-grouped — full detail in REVIEW-FEEDBACK.md):
  ⛔ Critical/Nghiêm trọng ({N}):
     1. {one-line summary}
        ↳ Fix: {concrete action — file:line, command, or workflow}
        ↳ Verify: {how to confirm — curl, test, diff}
     2. ...
  ⚠ High/Cao ({N}):
     ... (same format)
  ⓘ Medium/Trung bình ({N}):
     ... (same format)

Next steps (pick the matching path — DO NOT just re-run /vg:review blindly):

  A. Fix code bugs found → re-review:
     # Edit affected files (paths above), then stage + commit as SEPARATE
     # steps (v2.5.2.7: don't chain staging with commit — if commit-msg
     # hook BLOCKs on missing citation, prior `git add` success gets
     # masked by the red "Exit 1" UI label):
     git add path/to/fixed-file.ts              # stage intentional files
     git commit -m "fix({phase}-XX): {summary}

Per CONTEXT.md D-XX OR Per API-CONTRACTS.md"  # body must cite
     /vg:review {phase} --retry-failed      # only re-scan failed goals (faster)
     # OR /vg:review {phase}                # full re-scan if many fixes

  B. If findings need scope discussion (architectural, decision change):
     /vg:amend {phase}                       # mid-phase change request workflow
     # then re-blueprint + re-build before re-review

  C. If findings are infra/env (services down, config missing):
     /vg:doctor                              # diagnose env + service health
     # fix infra → /vg:review {phase}

  D. If finding is BUG in /vg:review tooling itself (not phase code):
     /vg:bug-report                          # surface to vietdev99/vgflow

  E. If you DISAGREE with verdict (false positive):
     # Open REVIEW-FEEDBACK.md, dispute specific finding with evidence
     /vg:review {phase} --override-reason "..." --allow-failed=G-XX
     # Will register in OVERRIDE-DEBT — re-evaluated at /vg:accept
```

### Hard rules for AI orchestrator (Claude/Codex/Gemini)
1. **Never end a BLOCK review without listing per-finding fixes + verify steps.** Bare list of issues = user has to re-derive next action — anti-pattern.
2. **Use RELATIVE paths** in narration (`apps/api/src/plugins/health.ts:23`), NOT absolute (`/D/Workspace/...`). Absolute paths waste 60% of terminal width on repeated prefixes.
3. **Per-finding format MUST be:**
   ```
   {N}. [Severity] {ONE LINE root-cause}
        ↳ Fix:    {file:line edit OR shell command OR workflow}
        ↳ Verify: {1-line check command OR test ID}
        ↳ Refs:   {file:line, file:line}  (only if 2+ refs needed)
   ```
4. **Closing MUST contain "Next:" block** with at least 2 labeled options (A/B/C...) when verdict ≠ PASS.
5. **If executor cannot run something** (bash broken, no internet, missing creds), say so EXPLICITLY and tell user the manual command to run instead. Don't bury it in middle of output.


```bash
# v2.2 — complete step marker + terminal emit + run-complete
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0_parse_and_validate 2>/dev/null || true
READY_COUNT=$(grep -c "READY" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo 0)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_ready\":${READY_COUNT}}" >/dev/null

# v2.38.0 — Flow compliance audit
if [[ "$ARGUMENTS" =~ --skip-compliance=\"([^\"]*)\" ]]; then
  COMP_REASON="${BASH_REMATCH[1]}"
else
  COMP_REASON=""
fi
COMP_SEV=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
COMP_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "review" "--severity" "$COMP_SEV" )
[ -n "$COMP_REASON" ] && COMP_ARGS+=( "--skip-compliance=$COMP_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMP_ARGS[@]}"
COMP_RC=$?
if [ "$COMP_RC" -ne 0 ] && [ "$COMP_SEV" = "block" ]; then
  echo "⛔ Review flow compliance failed. See .flow-compliance-review.yaml or pass --skip-compliance=\"<reason>\"."
  exit 1
fi

# v2.45 fail-closed-validators PR: matrix↔runtime evidence cross-check.
# Phase 3.2 dogfood found GOAL-COVERAGE-MATRIX.md fabricating READY status
# even when goal_sequences[].result == "blocked" or sequence missing entirely.
# This validator catches the fabrication BEFORE review exits, so /vg:test
# never sees a lying matrix.
MATRIX_LINK_VAL=".claude/scripts/validators/verify-matrix-evidence-link.py"
if [ -f "$MATRIX_LINK_VAL" ]; then
  ${PYTHON_BIN:-python3} "$MATRIX_LINK_VAL" --phase-dir "$PHASE_DIR" --severity block
  MATRIX_LINK_RC=$?
  if [ "$MATRIX_LINK_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_evidence_link_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-evidence-link-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_evidence_link",
  "summary": "Review matrix-evidence-link gate failed — GOAL-COVERAGE-MATRIX.md asserts goal status that runtime evidence does not support",
  "fix_hint": "1. Re-run /vg:review ${PHASE_NUMBER} --retry-failed (record real sequences); 2. OR reclassify goals to UNREACHABLE/INFRA_PENDING/DEFERRED with justification"
}
JSON
    blocking_gate_prompt_emit "matrix_evidence_link" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# RFC v9 PR-D2 Codex-HIGH-1 fix: post_state lifecycle gate AFTER scanner ran.
# Pre_state checked at Phase 0.5 (pre-scanner); post_state must verify the
# action actually mutated state correctly. Without this leg, RCRURD is half-
# wired (Codex review found pre-only).
# Re-resolve base URL from config (PRE_BASE local to Phase 0.5; not in scope).
# Codex-R4-HIGH-2 fix: read base_url from ENV-CONTRACT.md (canonical),
# not from vg.config.md step_env (env NAME, not URL).
POST_BASE_RC=$("${PYTHON_BIN:-python3}" -c "
import re
try:
    text = open('${PHASE_DIR}/ENV-CONTRACT.md', encoding='utf-8').read()
    m = re.search(r'^target:\s*\n((?:[ \t].*\n)+)', text, re.MULTILINE)
    if m:
        bm = re.search(r'^\s*base_url:\s*[\"\\']?([^\"\\'\s#]+)', m.group(1), re.MULTILINE)
        if bm: print(bm.group(1))
except FileNotFoundError: pass
" 2>/dev/null)
[ -z "$POST_BASE_RC" ] && POST_BASE_RC="${VG_BASE_URL:-}"
HAS_POST_LIFECYCLE=$(grep -lE '^\s*post_state:' "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
# Codex-HIGH-5-bis fix: post_state setup error blocks even without runner exec
if [ "$HAS_POST_LIFECYCLE" -gt 0 ] && [ -z "$POST_BASE_RC" ] && \
   [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
  echo "⛔ RCRURD post_state setup error — FIXTURES declare post_state"
  echo "   blocks but no sandbox base_url available at run-complete."
  exit 1
fi
VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
[ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
if [ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] && \
   [ -d "${PHASE_DIR}/FIXTURES" ] && [ -n "$POST_BASE_RC" ]; then
  # Codex-HIGH-1-ter fix: snapshot must exist when delta assertions present
  POST_NEEDS_SNAP=$(grep -lE 'increased_by_at_least|decreased_by_at_least' \
    "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
  if [ "$POST_NEEDS_SNAP" -gt 0 ] && [ ! -f "${PHASE_DIR}/.rcrurd-pre-snapshot.json" ] && \
     [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    echo "⛔ RCRURD post_state — pre-snapshot missing but ${POST_NEEDS_SNAP}"
    echo "   fixture(s) declare delta assertions. Pre-mode at Phase 0.5"
    echo "   should have captured it. Re-run /vg:review from scratch."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_snapshot_missing" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  POST_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" \
    --phase "$PHASE_NUMBER" --base-url "$POST_BASE_RC" \
    --mode post --severity "${VG_RCRURD_POST_SEVERITY:-block}" \
    --pre-snapshot "${PHASE_DIR}/.rcrurd-pre-snapshot.json" 2>&1)
  POST_RC=$?
  echo "▸ RCRURD post_state: $(echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} post-state assertions failed)")
    elif v == "WARN":
        print(f"WARN ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed)")
    elif v == "PASS":
        print(f"PASS ({d.get(\"checked\",0)} fixtures)")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
  if [ "$POST_RC" -eq 2 ]; then
    echo "⛔ RCRURD post_state setup error — cannot proceed:"
    echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown\")[:300]}")
except: print("   (could not parse error)")
'
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if [ "$POST_RC" -eq 1 ] && [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_state_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-post-state-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_post_state",
  "summary": "RCRURD post_state gate BLOCK — fixture lifecycle assertions failed after the scanner action. State did not transition as expected.",
  "fix_hint": "Re-run scanner if action genuinely succeeded; or fix the action's expected_network/post_state assertion drift."
}
JSON
    blocking_gate_prompt_emit "rcrurd_post_state" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2 matrix-staleness final gate: after matrix is BUILT (Phase 4),
# re-run staleness validator at review-complete time. Step 0 entry pass catches
# stale entries from PRIOR runs; this catches stale entries created by THIS run
# (e.g. scanner recorded sequence but skipped submit, then matrix wrote READY).
# Phase 3.2 dogfood found 36/39 mutation goals stale despite verdict=PASS.
MATRIX_STALE_VAL=".claude/scripts/validators/verify-matrix-staleness.py"
if [ -f "$MATRIX_STALE_VAL" ]; then
  STALE_SEV="block"
  [[ "${ARGUMENTS}" =~ --allow-stale-matrix ]] && STALE_SEV="warn"
  ${PYTHON_BIN:-python3} "$MATRIX_STALE_VAL" --phase "${PHASE_NUMBER}" --severity "$STALE_SEV"
  STALE_RC=$?
  if [ "$STALE_RC" -ne 0 ] && [ "$STALE_SEV" = "block" ]; then
    SUSPECTED_N=$(${PYTHON_BIN:-python3} -c "
import json
try: print(json.load(open('${PHASE_DIR}/.matrix-staleness.json'))['suspected_count'])
except: print('?')
")
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_staleness_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"suspected\":${SUSPECTED_N}}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-staleness-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_staleness",
  "summary": "Matrix-staleness gate failed — ${SUSPECTED_N} mutation goal(s) marked READY without submit/2xx evidence",
  "fix_hint": "1. /vg:review ${PHASE_NUMBER} --retry-failed; 2. /vg:review ${PHASE_NUMBER} --re-scan-goals=G-XX,G-YY; 3. /vg:review ${PHASE_NUMBER} --dogfood; 4. /vg:review ${PHASE_NUMBER} --allow-stale-matrix --override-reason=... (debt)"
}
JSON
    blocking_gate_prompt_emit "matrix_staleness" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2.3 (RFC v9 D10) — evidence provenance gate. Mutation steps
# claiming success (action + 2xx network) MUST carry structured evidence:
# {source, artifact_hash, captured_at, schema_version, scanner_run_id |
# layer2_proposal_id}. Closes the trust hole where executor agents could
# fabricate evidence to flip matrix-staleness bidirectional sync.
#
# Codex-HIGH-4 fix: default to BLOCK (was warn). Migration grace via
# explicit `review.provenance.enforcement: warn` in vg.config.md OR
# --allow-legacy-provenance flag for phases pre-dating RFC v9.
PROV_VAL=".claude/scripts/validators/verify-evidence-provenance.py"
if [ -f "$PROV_VAL" ]; then
  # Resolve enforcement from config — env var wins, then grep config, default block
  PROV_MODE="${VG_PROVENANCE_ENFORCEMENT:-}"
  if [ -z "$PROV_MODE" ] && [ -n "${CONFIG_RAW:-}" ]; then
    PROV_MODE=$(echo "$CONFIG_RAW" | grep -A2 '^review:' | grep -E '^\s*provenance:' -A2 | \
                grep -E '^\s*enforcement:' | head -1 | sed 's/.*enforcement:\s*//;s/[\"'\'']//g' | tr -d ' ')
  fi
  [ -z "$PROV_MODE" ] && PROV_MODE="block"
  PROV_FLAGS="--severity ${PROV_MODE}"
  # During migration window, allow legacy phases without provenance
  [[ "${ARGUMENTS}" =~ --allow-legacy-provenance ]] && PROV_FLAGS="$PROV_FLAGS --allow-legacy"
  ${PYTHON_BIN:-python3} "$PROV_VAL" --phase "${PHASE_NUMBER}" $PROV_FLAGS
  PROV_RC=$?
  if [ "$PROV_RC" -ne 0 ] && [ "$PROV_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.evidence_provenance_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/evidence-provenance-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "evidence_provenance",
  "summary": "Evidence provenance gate failed — mutation steps claim success without structured provenance object (RFC v9 D10). Possible fabricated evidence.",
  "fix_hint": "1. Re-run scanner: /vg:review ${PHASE_NUMBER} --retry-failed; 2. For legacy phases: --allow-legacy-provenance; 3. Set review.provenance.enforcement: warn in vg.config.md to defer enforcement"
}
JSON
    blocking_gate_prompt_emit "evidence_provenance" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 anti-performative-review: ép scanner phải submit mutation goals,
# không được Cancel modal rồi mark passed. Phase 3.2 dogfood (2026-05-01) tìm
# 5 false-pass goals (G-31/G-34/G-35/G-44/G-52) modal opened nhưng chưa bao giờ
# submit. Validator này check goal_sequences.steps[] có submit click + 2xx
# network entry trước khi cho phép run-complete.
MUT_SUBMIT_VAL=".claude/scripts/validators/verify-mutation-actually-submitted.py"
if [ -f "$MUT_SUBMIT_VAL" ]; then
  MUT_FLAGS="--severity block"
  if [[ "${ARGUMENTS}" =~ --allow-cancel-only-mutations ]]; then
    MUT_FLAGS="--severity block --allow-cancel-only-mutations"
  fi
  ${PYTHON_BIN:-python3} "$MUT_SUBMIT_VAL" --phase "${PHASE_NUMBER}" $MUT_FLAGS
  MUT_RC=$?
  if [ "$MUT_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.mutation_submit_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/mutation-submit-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "mutation_submit",
  "summary": "Review mutation-actually-submitted gate failed — mutation goals marked passed without actual submit click + 2xx network",
  "fix_hint": "Re-run /vg:review ${PHASE_NUMBER} with scanner prompt requiring SUBMIT, or use --allow-cancel-only-mutations override (logs OVERRIDE-DEBT)"
}
JSON
    blocking_gate_prompt_emit "mutation_submit" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 Phase 6 enrichment: traceability + RCRURD enforcement.
# Closes "AI bịa goal/decision/business-rule" + "scanner stops too early".
# Migration: VG_TRACEABILITY_MODE=warn for pre-2026-05-01 phases (set in
# vg.config.md). New phases default to block.
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"

# v2.46 L4 — RCRURD step depth (per goal_class threshold)
RCRURD_VAL=".claude/scripts/validators/verify-rcrurd-depth.py"
if [ -f "$RCRURD_VAL" ]; then
  RCRURD_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-shallow-scans ]] && RCRURD_FLAGS="$RCRURD_FLAGS --allow-shallow-scans"
  ${PYTHON_BIN:-python3} "$RCRURD_VAL" --phase "${PHASE_NUMBER}" $RCRURD_FLAGS
  RCRURD_RC=$?
  if [ "$RCRURD_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_depth_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-depth-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_depth",
  "summary": "RCRURD depth gate failed — scanner stopped too early on mutation goals",
  "fix_hint": "See scanner-report-contract.md 'RCRURD Lifecycle Protocol'. Goal class drives min steps."
}
JSON
    blocking_gate_prompt_emit "rcrurd_depth" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — asserted_quote vs business rule similarity
ASSERTED_VAL=".claude/scripts/validators/verify-asserted-rule-match.py"
if [ -f "$ASSERTED_VAL" ]; then
  ASSERTED_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-asserted-drift ]] && ASSERTED_FLAGS="$ASSERTED_FLAGS --allow-asserted-drift"
  ${PYTHON_BIN:-python3} "$ASSERTED_VAL" --phase "${PHASE_NUMBER}" $ASSERTED_FLAGS
  ASSERTED_RC=$?
  if [ "$ASSERTED_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.asserted_drift_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/asserted-drift-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "asserted_drift",
  "summary": "Asserted-rule-match gate failed — scanner asserted_quote drifts from BR-NN text",
  "fix_hint": "Align scanner asserted_quote fields with the business rule text in BUSINESS-RULES.md or use --allow-asserted-drift override"
}
JSON
    blocking_gate_prompt_emit "asserted_drift" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — replay-evidence (structural + optional curl replay)
REPLAY_VAL=".claude/scripts/validators/verify-replay-evidence.py"
if [ -f "$REPLAY_VAL" ]; then
  REPLAY_FLAGS="--severity warn"  # default warn — auth fixture not always available
  [[ "${ARGUMENTS}" =~ --enable-replay ]] && REPLAY_FLAGS="--severity ${TRACE_MODE} --enable-replay"
  ${PYTHON_BIN:-python3} "$REPLAY_VAL" --phase "${PHASE_NUMBER}" $REPLAY_FLAGS
  REPLAY_RC=$?
  if [ "$REPLAY_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ] && [[ "${ARGUMENTS}" =~ --enable-replay ]]; then
    echo "⛔ Replay-evidence gate failed — scanner network claims can't be verified."
    exit 1
  fi
fi

# v2.46 L4 — cross-phase decision validity (D-XX from earlier phase still active)
CROSS_VAL=".claude/scripts/validators/verify-cross-phase-decision-validity.py"
if [ -f "$CROSS_VAL" ]; then
  CROSS_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-stale-decisions ]] && CROSS_FLAGS="$CROSS_FLAGS --allow-stale-decisions"
  ${PYTHON_BIN:-python3} "$CROSS_VAL" --phase "${PHASE_NUMBER}" $CROSS_FLAGS
  CROSS_RC=$?
  if [ "$CROSS_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Cross-phase decision validity failed — goal cites revoked/missing D-XX."
    exit 1
  fi
fi

# v2.46 L6 — adversarial scanner-business-alignment verifier
# Two-phase: emit prompts → orchestrator spawns Haiku verifier per prompt →
# re-run validator with --verifier-results to gate.
ALIGN_VAL=".claude/scripts/validators/verify-scanner-business-alignment.py"
if [ -f "$ALIGN_VAL" ]; then
  PROMPTS_FILE="${PHASE_DIR}/.tmp/business-alignment-prompts.jsonl"
  RESULTS_FILE="${PHASE_DIR}/.tmp/business-alignment-results.jsonl"
  mkdir -p "$(dirname "$PROMPTS_FILE")" 2>/dev/null
  ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" --prompts-out "$PROMPTS_FILE" 2>&1 | head -3
  PROMPT_COUNT=$(wc -l < "$PROMPTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

  if [ "$PROMPT_COUNT" -gt 0 ]; then
    echo ""
    echo "📋 Business alignment verifier needs ${PROMPT_COUNT} adversarial check(s)."
    echo "   Orchestrator should spawn isolated Haiku per prompt + write JSONL results to:"
    echo "     ${RESULTS_FILE}"
    echo "   Then re-run review with --verifier-results=${RESULTS_FILE}"
    echo ""
    # If results file exists from prior orchestrator pass, gate now
    if [ -f "$RESULTS_FILE" ]; then
      ALIGN_FLAGS="--severity ${TRACE_MODE} --verifier-results ${RESULTS_FILE}"
      [[ "${ARGUMENTS}" =~ --allow-business-drift ]] && ALIGN_FLAGS="$ALIGN_FLAGS --allow-business-drift"
      ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" $ALIGN_FLAGS
      ALIGN_RC=$?
      if [ "$ALIGN_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
        echo "⛔ Business alignment gate failed — adversarial verifier flagged drift."
        exit 1
      fi
    fi
  fi
fi

# RFC v9 D21 — DEFECT-LOG.md generation (tester pro).
# After GOAL-COVERAGE-MATRIX is final, parse the matrix and create one
# Defect entry per goal with status ∈ {BLOCKED, UNREACHABLE, FAILED, SUSPECTED}
# that does NOT already have an open defect in .tester-pro/defects.json.
# Severity inferred from priority + block_family heuristics.
TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ] && [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
  echo "━━━ D21 — Defect log generation ━━━"
  TESTER_PRO_CLI="$TESTER_PRO_CLI" ${PYTHON_BIN:-python3} - <<'PYDEFECT' 2>&1 | sed 's/^/  D21: /' || true
import json, os, re, subprocess, sys
phase_dir = os.environ['PHASE_DIR']
phase_no = os.environ['PHASE_NUMBER']
matrix = open(os.path.join(phase_dir, 'GOAL-COVERAGE-MATRIX.md'),
              encoding='utf-8').read()
cli = os.environ.get(
    'TESTER_PRO_CLI',
    os.path.join(os.environ['REPO_ROOT'], 'scripts', 'tester-pro-cli.py'),
)
# Parse rows `| G-XX | priority | surface | STATUS | evidence |`
row_re = re.compile(
    r"^\|\s*(G-[\w.-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
    r"\s*([A-Z_]+)\s*\|\s*(.+?)\s*\|", re.MULTILINE,
)
fail_states = {"BLOCKED", "UNREACHABLE", "FAILED", "SUSPECTED"}
# Load existing open defects to skip duplicates by (goal, title-prefix)
defects_path = os.path.join(phase_dir, '.tester-pro', 'defects.json')
existing = []
if os.path.exists(defects_path):
    try: existing = json.load(open(defects_path, encoding='utf-8'))
    except: pass
def is_open_for(gid, title_prefix):
    return any(
        d.get('related_goals') and gid in d['related_goals']
        and d.get('title','').startswith(title_prefix)
        and not d.get('closed_at')
        for d in existing
    )
opened = 0
for m in row_re.finditer(matrix):
    gid, prio, surf, status, ev = m.groups()
    if status not in fail_states:
        continue
    title_prefix = f"[{status}]"
    if is_open_for(gid, title_prefix):
        continue
    # Severity heuristic: critical priority → critical; backend mutation → major;
    # else minor.
    prio_l = prio.strip().lower()
    surf_l = surf.strip().lower()
    if prio_l == 'critical':
        sev = 'critical'
    elif any(s in surf_l for s in ('api', 'data', 'integration')):
        sev = 'major'
    else:
        sev = 'minor'
    title = f"[{status}] {gid} — {ev[:80]}"
    cmd = [
        sys.executable, cli, 'defect', 'new',
        '--phase', phase_no, '--title', title,
        '--severity', sev, '--found-in', 'review',
        '--goals', gid,
        '--notes', f"surface={surf} priority={prio} status={status}. Auto-opened from GOAL-COVERAGE-MATRIX.",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        opened += 1
print(f"opened {opened} new defect(s) from matrix")
PYDEFECT
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ review run-complete BLOCK — review orchestrator output + fix before /vg:test" >&2
  exit $RUN_RC
fi
```
</step>

</process>

<success_criteria>
- Code scan completed (contract verify + element inventory)
- Browser discovery explored all reachable views organically
- RUNTIME-MAP.json produced with actual runtime observations (canonical JSON)
- RUNTIME-MAP.md derived from JSON (human-readable)
- Fix loop resolved code bugs (if any)
- TEST-GOALS mapped to discovered paths
- GOAL-COVERAGE-MATRIX.md shows weighted goal readiness
- Gate passed (weighted: 100% critical, 80% important, 50% nice-to-have)
- Discovery state saved (resumable)
</success_criteria>
