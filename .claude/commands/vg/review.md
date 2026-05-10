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


<step name="phase2_7_url_state_sync" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.7: URL state sync declaration check (Phase J)

→ `narrate_phase "Phase 2.7 — URL state sync" "Kiểm tra interactive_controls trong TEST-GOALS"`

**Purpose:** validate every list/table/grid view goal in TEST-GOALS.md
declares `interactive_controls` block (filter/sort/pagination/search +
URL sync assertion). This is the static-side complement to runtime
browser probing — declaration must exist before runtime can verify.

**CRUD surface precheck (v2.12):** before URL-state checks, validate
`${PHASE_DIR}/CRUD-SURFACES.md`. Review compares runtime observations against
the resource/platform contract first, then uses `interactive_controls` as the
web-list extension pack. Missing CRUD contract means the reviewer has no
authoritative list of expected headings, filters, columns, states, row actions,
delete confirmations, or security/abuse expectations.

```bash
CRUD_FLAGS=""
[[ "${ARGUMENTS:-}" =~ --allow-no-crud-surface ]] && CRUD_FLAGS="--allow-missing"
CRUD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" ${CRUD_FLAGS} \
    > "${PHASE_DIR}/.tmp/crud-surface-review.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD surface contract missing/incomplete — see ${PHASE_DIR}/.tmp/crud-surface-review.json"
    echo "   Fix blueprint artifact CRUD-SURFACES.md or rerun /vg:blueprint."
    exit 2
  fi
fi
```

**Why:** modern dashboard UX baseline (executor R7) requires list view
state synced to URL search params. Without declaration, AI executors
build local-state-only filters and ship apps that lose state on refresh.
This validator catches the gap at /vg:review time, before user sees it.

**Severity:** config-driven via `vg.config.md → ui_state_conventions.severity_phase_cutover`
(default 14). Phase number < cutover → WARN (grandfather). Phase ≥ cutover
→ BLOCK (mandatory). Override with `--allow-no-url-sync` to log soft OD
debt entry.

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-sync.py \
  --phase "${PHASE_NUMBER}" \
  --enforce-required-lenses \
  > "${PHASE_DIR}/.tmp/url-state-sync.json" 2>&1
URL_SYNC_RC=$?

if [ "${URL_SYNC_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-no-url-sync"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-sync \
      --reason "URL state sync waived for ${PHASE_NUMBER} via --allow-no-url-sync (soft debt logged)"
    echo "⚠ URL state sync gate waived via --allow-no-url-sync"
  else
    echo "⛔ URL state sync declarations missing — see ${PHASE_DIR}/.tmp/url-state-sync.json"
    cat "${PHASE_DIR}/.tmp/url-state-sync.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_sync" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-sync.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Add interactive_controls blocks to TEST-GOALS.md per goal."
    echo "     Schema: .claude/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md (Phase J section)."
    echo "  2. If state is genuinely local-only, declare url_sync: false + url_sync_waive_reason."
    echo "  3. Override (last resort): re-run with --allow-no-url-sync (logs soft OD debt)."
    exit 2
  fi
fi
```

**Future runtime probe (deferred to v2.9):** once RUNTIME-MAP.json is
populated by phase 2 browser discovery, a follow-up validator can click
each declared control via MCP Playwright + snapshot URL pre/post +
assert reload-survives. Static declaration check is the foundation that
makes runtime probe meaningful.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_7_url_state_sync" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_7_url_state_sync.done"`
</step>

<step name="phase2_8_url_state_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.8: URL state runtime probe (v2.7 Phase A)

→ `narrate_phase "Phase 2.8 — URL state runtime probe" "Click từng control + snapshot URL để verify declaration vs implementation"`

**Purpose:** verify that the static `interactive_controls` declarations
(checked at phase 2.7) match actual application behaviour. AI drives MCP
Playwright through every declared control, captures URL params before/after
each interaction, writes the result to
`${PHASE_DIR}/url-runtime-probe.json`. Validator reads that artifact and
flags coverage gaps (WARN) or declaration drift (BLOCK).

**Why:** static declarations close ~50% of URL-state bugs; runtime probe
catches the remaining drift class — declaration says `?status=...` but
the route handler ships `?state=...`, or the filter pretends to sync but
no `pushState` actually fires.

**Skip conditions:**
- No goal in TEST-GOALS.md has `interactive_controls.url_sync: true` → skip silently.
- `${RUN_ARGS}` contains `--skip-runtime` → run validator with the same flag (logs OD debt).
- Browser environment unavailable (no MCP Playwright) → invoke validator with `--skip-runtime`.

### 2.8a Drive the probe (AI agent task)

For every goal in `${PHASE_DIR}/TEST-GOALS.md` that declares
`interactive_controls.url_sync: true`:

1. Determine the goal's route from `${PHASE_DIR}/RUNTIME-MAP.json` (key
   matching the goal id) or, when the goal frontmatter carries an explicit
   `route:` field, prefer that.
2. Authenticate as `goal.actor` (default `admin`) using the standard
   review-phase auth helper.
3. Navigate to the route. Wait for the list/table/grid to be visible.
4. For every entry in the goal's `interactive_controls`:
   - **filter** — pick the first declared `values[0]`, click the filter
     control, snapshot URL, then prove visible rows and/or network response
     match the selected value. Example: `status=pending` must not show flagged,
     approved, rejected, or failed rows unless the contract explicitly says
     flagged is an orthogonal boolean.
   - **sort** — apply the first declared column, snapshot URL, then prove row
     order matches the declared direction.
   - **pagination** — click page 2 (or scroll once for `infinite-scroll`),
     snapshot URL, then prove the result window changed without duplicated
     first-page rows.
   - **search** — type a representative query, wait `debounce_ms + 100ms`,
     snapshot URL, then prove returned rows contain/match the query.
5. Also compare the observed route against `${PHASE_DIR}/CRUD-SURFACES.md`
   `platforms.web.list`: heading/description presence, declared table columns,
   row actions, empty/loading/error/unauthorized states where reachable, and
   delete confirmation if a delete action is declared.
6. Append one entry per goal to `url-runtime-probe.json`.

**Artifact schema** (`${PHASE_DIR}/url-runtime-probe.json`):

```json
{
  "generated_at": "2026-04-26T10:30:00Z",
  "goals": [
    {
      "goal_id": "G-01",
      "url": "/admin/campaigns",
      "controls": [
        {
          "kind": "filter",
          "name": "status",
          "value": "active",
          "url_before": "https://app.local:5173/admin/campaigns",
          "url_after": "https://app.local:5173/admin/campaigns?status=active",
          "url_params_after": {"status": "active"},
          "result_semantics": {
            "passed": true,
            "rows_checked": 20,
            "violations": []
          }
        }
      ]
    }
  ]
}
```

`kind` is one of `filter | sort | pagination | search`. `name` matches the
declared control name (or normalised — `page` for pagination, `search` for
search, `sort` for sort). `url_params_after` is the parsed search-param
dict. For filters, `result_semantics` is mandatory; URL-only success is not
enough because it misses the class where a Pending tab still renders Flagged
records.

### 2.8b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"

EXTRA_FLAGS=""
if [[ "${RUN_ARGS:-}" == *"--skip-runtime"* ]] || [[ -z "${VG_BROWSER_AVAILABLE:-1}" ]]; then
  EXTRA_FLAGS="--skip-runtime"
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-runtime.py \
  --phase "${PHASE_NUMBER}" ${EXTRA_FLAGS} \
  > "${PHASE_DIR}/.tmp/url-state-runtime.json" 2>&1
URL_RUNTIME_RC=$?

if [ "${URL_RUNTIME_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-runtime-drift"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-runtime \
      --reason "URL state runtime drift waived for ${PHASE_NUMBER} via --allow-runtime-drift (soft debt logged)"
    echo "⚠ URL state runtime drift waived via --allow-runtime-drift"
  else
    echo "⛔ URL state runtime drift detected — see ${PHASE_DIR}/.tmp/url-state-runtime.json"
    cat "${PHASE_DIR}/.tmp/url-state-runtime.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_runtime" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-runtime.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Implementation drift — fix the route handler / UI so declared url_param actually appears in URL after interaction."
    echo "  2. Declaration drift — declared url_param is wrong; update TEST-GOALS.md interactive_controls block."
    echo "  3. Override (last resort): re-run with --allow-runtime-drift (logs soft OD debt)."
    exit 2
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_8_url_state_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_8_url_state_runtime.done"`
</step>

<step name="phase2_9_error_message_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.9: API error-message runtime lens

→ `narrate_phase "Phase 2.9 — API error-message runtime lens" "Trigger API error paths and prove toast/form errors show API body messages, not HTTP transport text"`

**Purpose:** catch the P3.2 class of bug where the backend returns a useful
domain/validation message but the frontend toast shows `Request failed with
status 403`, `statusText`, or another generic transport message.

This is a plugin/lens inside review, not a second full browser discovery pass.
Reuse the authenticated browser session and routes already discovered by
Phase 2. For each API+UI mutation or protected action that can safely fail,
drive one negative path and record API body + visible UI message.

### 2.9a Drive the probe

For API+UI phases:

1. Read `${PHASE_DIR}/INTERFACE-STANDARDS.md`, `${PHASE_DIR}/API-DOCS.md`,
   `${PHASE_DIR}/API-CONTRACTS.md`, and `${PHASE_DIR}/RUNTIME-MAP.json`.
2. Pick safe negative paths in this order:
   - validation error on create/update form
   - unauthorized/forbidden path for a role-gated action
   - domain rule error that does not mutate durable data
3. Capture the network response JSON for the failed request.
4. Capture visible toast/banner/form error text from the UI.
5. Compare using the standard message priority:
   `error.user_message -> error.message -> message -> network_fallback`.
6. Write `${PHASE_DIR}/error-message-probe.json`.

**Artifact schema**:

```json
{
  "generated_at": "2026-05-02T10:30:00Z",
  "checks": [
    {
      "goal_id": "G-01",
      "route": "/admin/billing/topup-queue",
      "action": "submit invalid filter or mutation",
      "request": {"method": "POST", "path": "/api/example"},
      "status": 400,
      "api_error": {
        "code": "VALIDATION_ERROR",
        "message": "Amount is required",
        "user_message": "Amount is required"
      },
      "api_user_message": "Amount is required",
      "visible_message": "Amount is required",
      "passed": true
    }
  ]
}
```

If a phase has API contracts and UI goals but no reachable negative path, write
the artifact with `checks: []` plus `blocked_reason`, then run the diagnostic.
Do not silently skip.

### 2.9b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null

"${PYTHON_BIN}" .claude/scripts/validators/verify-error-message-runtime.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/error-message-runtime.json" 2>&1
ERROR_MESSAGE_RC=$?

if [ "${ERROR_MESSAGE_RC}" != "0" ]; then
  echo "⛔ API error-message runtime lens failed — see ${PHASE_DIR}/.tmp/error-message-runtime.json"
  cat "${PHASE_DIR}/.tmp/error-message-runtime.json"
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.error_message_runtime" \
      --phase-dir "$PHASE_DIR" \
      --input "${PHASE_DIR}/.tmp/error-message-runtime.json" \
      --out-md "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" 2>/dev/null || true
  fi
  echo ""
  echo "Fix options:"
  echo "  1. Backend drift — return the standard API error envelope from INTERFACE-STANDARDS.md."
  echo "  2. Frontend drift — use shared error adapter: error.user_message || error.message, never statusText/AxiosError.message."
  echo "  3. Probe gap — rerun full review with a safe negative path and write error-message-probe.json."
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_9_error_message_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_9_error_message_runtime.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_9_error_message_runtime 2>/dev/null || true
```
</step>

<step name="phase3_fix_loop" mode="full">
## Phase 3: FIX LOOP (max 5 iterations)

**Iteration cap (v2.65.0 A4):** `MAX_ITER=5`. Bumped from 3 → 5 because multi-class
violation buckets (e.g. 1 SPEC_GAP + 2 CODE_BUG together) typically need 4–5 passes
to fully resolve. Each iteration emits `review.fix_iteration_started` so operators
have mid-loop telemetry instead of a black box.

→ `narrate_phase "Phase 3 — Fix loop (iteration ${I}/${MAX_ITER:-5})" "Sửa bug MINOR, escalate MODERATE/MAJOR"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase3_fix_loop >/dev/null 2>&1 || true

# v2.65.0 A4 — fix-loop iteration cap (max_iter=5)
# Each iteration body MUST emit review.fix_iteration_started with
# {iter, max_iter, violations} metadata so progress is observable mid-loop.
MAX_ITER=5
export MAX_ITER
```

**If no errors found in Phase 2 → skip to Phase 4.**
**If --fix-only → load RUNTIME-MAP, find errors, fix them.**

### 3a: Error Summary

Collect errors from ALL sources:
- RUNTIME-MAP.json: `errors[]` array + per-view `issues[]` + failed `goal_sequences` + `free_exploration` issues
- `${PHASE_DIR}/REVIEW-FEEDBACK.md` (if exists — written by /vg:test when MODERATE/MAJOR issues found):
  Parse issues table → add to error list with severity from test classification
  These are issues test couldn't fix — review MUST address them in this fix loop
- `${PLANNING_DIR}/KNOWN-ISSUES.json`: issues matching current phase/views (already loaded at init)

### 3b: Classify Errors

For each error:
- **CODE BUG** → fix immediately (wrong logic, missing validation, UI mismatch)
- **INFRA ISSUE** → escalate to user (service unavailable, config wrong)
- **SPEC GAP** → record in SPEC-GAPS.md (see 3b-spec-gaps) — feature not built, decision missing from CONTEXT/PLAN
- **PRE-EXISTING** → don't fix, write to `${PLANNING_DIR}/KNOWN-ISSUES.json` (see below)

### 3b-spec-gaps: Feed SPEC_GAPS back to blueprint (fixes G9)

When ≥3 SPEC_GAP errors accumulate, or any critical-priority goal maps to SPEC_GAP, emit `${PHASE_DIR}/SPEC-GAPS.md` and surface to user with a concrete re-plan command:

```markdown
# Spec Gaps — Phase {phase}

Detected during /vg:review phase 3b. Listed issues trace to missing CONTEXT decisions or un-tasked PLAN items — not code bugs. Review cannot fix these; blueprint must re-plan.

## Gaps
| # | Observed Issue | Related Goal | Likely Missing | Source Evidence |
|---|----------------|--------------|----------------|-----------------|
| 1 | Site delete has no confirmation modal | G-08 (delete site) | D-XX: "delete requires confirmation" decision | screenshot {phase}-sites-delete-error.png |
| 2 | Bulk import UI absent | G-12 (bulk import) | Task for CSV upload handler + FE form | grep "bulk" in code returns 0 matches |
...

## Recommended action

This is NOT a code bug. Re-run blueprint in patch mode to append tasks covering these gaps:

    /vg:blueprint {phase} --from=2a

This spawns planner with the gap list as input. Existing tasks preserved; missing ones appended. Then re-run build → review.

Do NOT attempt to fix these in the review fix loop — the fix loop targets code bugs, not missing scope.
```

Threshold + auto-suggestion:
```bash
SPEC_GAP_COUNT=$(count of SPEC_GAP-classified errors)
CRITICAL_SPEC_GAPS=$(count where related goal is priority:critical)

if [ $SPEC_GAP_COUNT -ge 3 ] || [ $CRITICAL_SPEC_GAPS -ge 1 ]; then
  echo "⚠ ${SPEC_GAP_COUNT} spec gaps detected (${CRITICAL_SPEC_GAPS} critical)."
  echo "See: ${PHASE_DIR}/SPEC-GAPS.md"
  echo ""
  echo "This is a planning gap, not a code bug. Recommended:"
  echo "   /vg:blueprint ${PHASE} --from=2a   (re-plan with gap feedback)"
  echo ""
  echo "Review fix loop will continue for code bugs only; spec gaps stay open until blueprint re-run."
fi
```

Do NOT block review — let fix loop handle code bugs. Just surface spec gaps with the right next command.

### 3b-known: Write PRE-EXISTING to KNOWN-ISSUES.json

Shared file across all phases: `${PLANNING_DIR}/KNOWN-ISSUES.json`

```
Read existing KNOWN-ISSUES.json (create if missing)

For each PRE-EXISTING error:
  Check if already recorded (match by view + description)
  IF new → append:
    {
      "id": "KI-{auto_increment}",
      "found_in_phase": "{current phase}",
      "view": "{view_path where observed}",
      "description": "{what's wrong}",
      "evidence": { "network": [...], "console_errors": [...], "screenshot": "..." },
      "affects_views": ["{list of views where this issue appears}"],
      "suggested_phase": "{phase that owns this area — AI infers from code_patterns}",
      "severity": "low|medium|high",
      "status": "open"
    }

Write back KNOWN-ISSUES.json
```

**Future phases auto-consume:** At the start of every review (Phase 2, before discovery), read KNOWN-ISSUES.json → filter issues where `suggested_phase` matches current phase OR `affects_views` overlaps with views being reviewed → display to AI as "known issues to verify/fix in this phase".

### 3c: Fix + Ripple Check + Redeploy

**🎯 3-tier fix routing (tightened 2026-04-17 — cost + context isolation):**

Sau khi bug classified ở 3a/3b (MINOR/MODERATE/MAJOR + size metadata), route tới model phù hợp theo config. Main model KHÔNG tự fix mọi thứ — MODERATE phải spawn để isolate context và save main-model tokens.

**Config (pure user-side, workflow không giả định model vendor/tier):**

```yaml
# vg.config.md
models:
  # Existing keys: planner, executor, debugger
  review_fix_inline: <model-id>    # model cho MINOR inline (thường = main/planner tier)
  review_fix_spawn:  <model-id>    # model cheaper cho MODERATE + MINOR-big-scope

review:
  fix_routing:
    minor:
      inline_when:
        max_files: <int>
        max_loc_estimate: <int>
      else: "spawn"                # route to models.review_fix_spawn
    moderate:
      action: "spawn"              # always route to models.review_fix_spawn
      parallel: <bool>
      max_concurrent: <int>
    major:
      action: "escalate"           # REVIEW-FEEDBACK.md, không auto-fix
    tripwire:
      minor_bloat_loc: <int>
      action: "warn|rollback"
```

Workflow CHỈ đọc model id từ `config.models.review_fix_inline` / `review_fix_spawn`. Không hardcode tên vendor (Claude/GPT/Gemini), tier (Opus/Sonnet/Haiku, o3/gpt-4o), hay capability.

Thiếu config → fallback: inline = main model hiện tại, spawn = cùng model (degraded — không có cost optimization nhưng vẫn có context isolation).

**Algorithm per CODE BUG:**

```
1. Load severity từ error classification (step 3b)
2. Estimate fix scope trước khi fix:
   - files_to_touch = heuristic từ error location + related callers
   - loc_estimate = peek file around error line, count context
3. Route theo severity:
```

**MINOR + small scope → inline (fast path, main model):**
```
If severity == MINOR AND files <= config.review.fix_routing.minor.inline_when.max_files
                   AND loc_estimate <= config.review.fix_routing.minor.inline_when.max_loc_estimate:
  Main model reads file + edits inline (current behavior)
  narrate_fix "[inline] MINOR ${bug_title} (${files} files, ~${loc} LOC)"
```

**MINOR big scope OR MODERATE → spawn (config-driven model):**

**Runtime branching (v2.65.0 A6) — Claude vs Codex spawn primitives:**

Fix-agent spawn site is dual-path: Claude Code uses the native `Agent` tool;
Codex (`VG_RUNTIME=codex`) does NOT have the `Agent` tool, so it MUST shell
out to `codex-spawn.sh --tier executor` (write access required because fixes
edit code). See `codex-skills/vg-build/SKILL.md` "Codex spawn precedence"
table — `/vg:review` fix agents map to `--tier executor` with
`workspace-write` sandbox.

```bash
SPAWN_MODEL="${config.models.review_fix_spawn:-${config.models.executor}}"
PROMPT_FILE="${PHASE_DIR}/.fix-prompt-${ERR_ID:-$idx}.md"
# (Render the structured prompt below into $PROMPT_FILE before spawning.)

if [ "${VG_RUNTIME:-claude}" = "codex" ]; then
  # Codex path (v2.65.0 A6) — no Agent tool; use codex-spawn.sh executor tier.
  # Sandbox=workspace-write because fix-agents edit code/tests.
  bash commands/vg/_shared/lib/codex-spawn.sh \
       --tier executor \
       --task "fix-${ERR_ID:-$idx}" \
       --sandbox workspace-write \
       --prompt-file "${PROMPT_FILE}" \
       --out "${PHASE_DIR}/.fix-out-${ERR_ID:-$idx}.json" \
    || { echo "⚠ codex-spawn fix-agent failed for ${ERR_ID:-$idx} — escalate to REVIEW-FEEDBACK.md" >&2; }
else
  # Claude path — preserve existing Agent tool spawn (narrate first, then call).
  bash scripts/vg-narrate-spawn.sh general-purpose spawning "fix-${ERR_ID:-$idx}" 2>/dev/null || true
  # Then invoke the Agent tool with the prompt body below; model/$SPAWN_MODEL
  # is passed as the model parameter (provider-native).
fi
```

Prompt body (rendered into `${PROMPT_FILE}` for Codex, or passed inline to
the `Agent(...)` tool call on Claude):

```
Agent(
  model="$SPAWN_MODEL",
  description="[fix ${idx}/${total}] ${severity} ${file}:${line} — ${bug_type}"
):
  prompt = """
  Fix this reviewed bug. Focused scope — no tangent changes.

  ## BUG
  Severity: ${severity}
  Observed: ${error_description}
  Expected: ${expected_behavior}
  View: ${view_url}
  File hint: ${suspected_file}
  Evidence: ${console_errors}, ${network_failures}, ${screenshot}

  ## CONSTRAINTS
  - Touch only files related to this bug
  - No refactor/rename unless required for fix
  - Write test if missing (project convention)
  - Commit: fix(${phase}): ${short description}
  - Per CONTEXT.md D-XX OR Covers goal: G-XX in commit body

  ## RETURN
  - Files changed (list)
  - LOC delta
  - One-line summary
  """

narrate_fix "[spawn:${SPAWN_MODEL}] ${severity} ${bug_title}"
```

**MAJOR → escalate (no auto-fix):**
```
Append to REVIEW-FEEDBACK.md:
| bug_id | view | severity | description | why_escalated |

narrate_fix "[escalated] MAJOR ${bug_title} → REVIEW-FEEDBACK.md"
```

**Parallel spawning:**

Nếu `config.review.fix_routing.moderate.parallel: true` và có >1 MODERATE bugs độc lập (no shared files):
- Group bugs by affected file → spawn Sonnet parallel per group
- Max `config.review.fix_routing.moderate.max_concurrent` at once
- Wait all → aggregate commits

**Post-fix tripwire (catch misclassification):**

```bash
TRIPWIRE_LOC="${config.review.fix_routing.tripwire.minor_bloat_loc:-0}"
TRIPWIRE_ACTION="${config.review.fix_routing.tripwire.action:-warn}"

if [ "$TRIPWIRE_LOC" -gt 0 ]; then
  # Check each MINOR-routed-inline fix
  for commit in $MINOR_INLINE_COMMITS; do
    ACTUAL_LOC=$(git show --stat "$commit" | tail -1 | grep -oE '[0-9]+ insertion' | grep -oE '^[0-9]+')
    if [ "${ACTUAL_LOC:-0}" -gt "$TRIPWIRE_LOC" ]; then
      case "$TRIPWIRE_ACTION" in
        rollback)
          echo "⛔ MINOR inline fix bloated ($ACTUAL_LOC > $TRIPWIRE_LOC LOC) — rolling back, re-route Sonnet"
          git reset --hard "${commit}^"
          # Re-queue bug với severity upgrade → MODERATE → spawn Sonnet
          ;;
        warn|*)
          echo "⚠ MINOR fix ($commit) bloated: $ACTUAL_LOC LOC > $TRIPWIRE_LOC threshold. Consider re-classify."
          echo "tripwire: $commit actual_loc=$ACTUAL_LOC severity=MINOR" >> "${PHASE_DIR}/build-state.log"
          ;;
      esac
    fi
  done
fi
```

**Narration format:**

```
  ▶ Fix 1/5: [inline] MINOR edit button label mismatch
       ✓ Fixed 1 file, 2 LOC

  ▶ Fix 2/5: [spawn] MODERATE form validation missing on /sites/new
       ✓ Agent completed: 3 files, 24 LOC  (model: ${SPAWN_MODEL})

  ▶ Fix 3/5: [escalated] MAJOR bulk import UI absent
       → REVIEW-FEEDBACK.md

  ▶ Fix 4/5: [inline] MINOR CSS overflow on mobile
       ⚠ Tripwire hit: 45 LOC > 15 threshold — flagged for re-classify
```

Narrator chỉ hiển thị model id user đã config, KHÔNG hardcode "Sonnet"/"GPT-4o"/etc.

**Then for each fixed bug (inline OR via Sonnet):**

1. Read the relevant source file
2. Fix the issue
3. **Ripple check (graphify-powered, if active):**
   ```bash
   if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
     # Get files changed by this fix
     FIXED_FILES=$(git diff --name-only HEAD)
     echo "$FIXED_FILES" > "${PHASE_DIR}/.fix-ripple-input.txt"

     # Run ripple analysis on fixed files
     ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
       --changed-files-input "${PHASE_DIR}/.fix-ripple-input.txt" \
       --config .claude/vg.config.md \
       --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
       --output "${PHASE_DIR}/.fix-ripple.json"

     # Check if fix affects callers outside the fixed file
     RIPPLE_COUNT=$(${PYTHON_BIN} -c "
     import json
     d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
     callers = d.get('affected_callers', [])
     print(len(callers))
     ")

     if [ "$RIPPLE_COUNT" -gt 0 ]; then
       echo "⚠ Fix ripple: ${RIPPLE_COUNT} callers may be affected by this change"
       echo "  Adding caller views to re-verify list (step 3d)"
       # Map caller files → views for re-verification in step 3d
       RIPPLE_VIEWS=$(${PYTHON_BIN} -c "
       import json
       d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
       for c in d.get('affected_callers', []):
         print(c)
       ")
     fi
   fi
   ```
   Without graphify: step 3d re-verifies affected views by git diff only (may miss indirect callers).
4. Commit with message: `fix({phase}): {description}`

After all fixes:
```
Redeploy using env-commands.md deploy(env)
Health check → if fail → rollback
```

### 3d: Re-verify (Sonnet parallel — focused on fixed zones)

After fix+redeploy, spawn Sonnet agents to re-verify affected views + ripple zones:

```
1. Get new SHA: git rev-parse HEAD
2. git diff old_sha..new_sha → list changed files
3. Map changed files to views (using code_patterns from config):
   - Changed API routes → views that call those endpoints
   - Changed page components → those specific views
   - Graphify ripple callers (from step 3c) → views importing those callers
4. Group affected views + ripple views into zones

5. Spawn Sonnet agents (parallel) for affected zones ONLY:
   Agent prompt: "Re-verify these fixed actions in {zone}.
     Previous errors: {error list from 3a}
     Expected: errors should be resolved.
     Test each previously-failed action.
     Also check: did the fix break anything else on this view?
     Report: {action, was_broken, now_works, new_issues}"

6. Wait all → merge results:
   - Fixed errors → update matrix: ❌ → 🔍 REVIEW-PASSED
   - Still broken → keep ❌, increment iteration
   - New errors from fix → add to error list
   - Update RUNTIME-MAP with corrected observations
   - Log current build SHA in PIPELINE-STATE.json `steps.review.last_fix_sha`
```

### 3d.5: QA-Checker meta-verification (v2.68.0 C2, hardened v2.69.0)

**v2.69.0 T3 escape hatch:** `SKIP_QA_CHECK=1` short-circuits this step
(set by parse loop when `--skip-qa-check` is passed; logs override-debt).
When unset, full QA-Checker spawn runs.

After Phase 3 fix-loop converges (verdict=ok or max_iter reached), spawn QA-Checker
to verify each fix commit ACTUALLY addresses the original review finding it was
meant to fix — not just makes tests pass. Detects suppression hacks, false fixes,
and test reverts.

```bash
if [ "${SKIP_QA_CHECK:-0}" = "1" ]; then
  echo "▸ Phase 3d.5: --skip-qa-check set (debt-tracked); skipping QA-Checker meta-verification" >&2
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/phase3d_5_qa_checker.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase3d_5_qa_checker 2>/dev/null || true
else
  bash scripts/vg-narrate-spawn.sh vg-review-qa-checker spawning "QA-check ${PHASE_NUMBER} fix commits"
  # Then: Agent(subagent_type="vg-review-qa-checker",
  #             prompt=<rendered with phase_dir + fix_commits list>)
fi
```

Marker: `phase3d_5_qa_checker` (v2.69.0:
`required_unless_flag: --skip-qa-check` — hard-block flipped from
v2.68.0 advisory severity=warn).

The QA-Checker returns PASS|PARTIAL|FAIL per fix and a cumulative verdict.
On PARTIAL/FAIL (v2.69.0 onward), review BLOCKs unless
`--skip-qa-check --override-reason=<text>` was passed. Operators must
either fix the underlying issue, route to /vg:amend, or log debt via the
escape hatch.

### 3e: Iterate

Repeat 3a-3d until:
- RUNTIME-MAP is **stable** (no new errors between 2 iterations)
- Zero CODE BUG errors remaining
- `MAX_ITER=5` iterations reached (v2.65.0 A4 bump from 3 → 5 for multi-class buckets)

**Per-iteration telemetry (v2.65.0 A4):** at the top of every iteration body, emit
`review.fix_iteration_started` so operators can watch progress mid-loop:

```bash
# Emit at the start of each iteration (after ITER + VIOLATION_COUNT are known).
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.fix_iteration_started" --actor "review" --outcome "INFO" \
  --metadata "{\"iter\":${ITER},\"max_iter\":${MAX_ITER:-5},\"violations\":${VIOLATION_COUNT:-0}}" \
  >/dev/null 2>&1 || true
```

Display after each iteration:
```
Fix iteration {N}/${MAX_ITER:-5}:
  Errors fixed: {N}
  Errors remaining: {N} (infra: {N}, spec-gap: {N}, pre-existing: {N})
  Sonnet agents spawned: {N} (re-verified {M} views)
  New errors found: {N}
  Matrix coverage: {review_passed}/{total} goals
  Map stable: {YES|NO}
```

### 3e: Iter limit fallback — Diagnostic L2 (RFC v9 D11 + D26, PR-E)

When the final iteration (`ITER == MAX_ITER`, default 5) exits with errors STILL
remaining (loop hit cap without self-resolving), do NOT silent-BLOCK. Spawn
diagnostic_l2 single-advisory fallback:

1. Capture residual evidence: list of unresolved error rows from
   RUNTIME-MAP + scan-*.json + recipe_executor logs.
2. Spawn isolated Haiku subagent (zero parent context — RFC v9 D11) to
   classify root cause `block_family` ∈ {schema_drift, validation_bug,
   auth_issue, db_constraint, business_logic, integration_failure,
   unknown}.
3. L2 generates `L2Proposal.json` with confidence + proposed_fix.
4. Present to user via single-advisory pattern (D26):
     - confidence ≥ 0.7  → "Đề xuất: <fix>. [Yes / chi tiết]"
     - confidence < 0.7  → 3-option block_resolve_l3_present (legacy)
5. **User gate is mandatory** — never auto-apply (per project policy).
6. User accept → apply fix → re-run one extra iteration grace (ITER+1).
7. User reject → BLOCK with full audit trail in
   `.l2-proposals/{proposal_id}.json` + DEFECT-LOG entry referencing
   the proposal.

```bash
if [ "${ITER:-1}" -eq "${MAX_ITER:-5}" ] && [ -n "${REMAINING_ERRORS}" ] && \
   { [ -f "${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py" ] || [ -f "${REPO_ROOT}/scripts/spawn-diagnostic-l2.py" ]; }; then
  echo "━━━ Phase 3e — Diagnostic L2 fallback (iter ${ITER} hit cap=${MAX_ITER:-5}) ━━━"
  DIAGNOSTIC_L2="${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py"
  [ -f "$DIAGNOSTIC_L2" ] || DIAGNOSTIC_L2="${REPO_ROOT}/scripts/spawn-diagnostic-l2.py"
  L2_ARGS=(
    --phase "${PHASE_NUMBER}"
    --gate-id "review.fix_loop"
    --evidence-file "${PHASE_DIR}/.fix-loop-evidence.json"
  )
  L2_OUT=$("${PYTHON_BIN:-python3}" "$DIAGNOSTIC_L2" \
    "${L2_ARGS[@]}" 2>&1)
  L2_PROPOSAL_ID=$(echo "$L2_OUT" | ${PYTHON_BIN:-python3} -c "
import json, sys
try: print(json.loads(sys.stdin.read()).get('proposal_id',''))
except: print('')
")
  if [ -n "$L2_PROPOSAL_ID" ]; then
    echo "  L2 proposal generated: $L2_PROPOSAL_ID"
    # Open DEFECT-LOG entry referencing the proposal
    TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
    [ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
    if [ -f "$TESTER_PRO_CLI" ]; then
      "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" defect new \
        --phase "${PHASE_NUMBER}" \
        --title "[ITER-LIMIT] Fix loop hit max=${MAX_ITER:-5}, L2 proposal $L2_PROPOSAL_ID" \
        --severity major --found-in review \
        --notes "L2 proposal at .l2-proposals/${L2_PROPOSAL_ID}.json — user decision pending" \
        2>&1 | sed 's/^/  /' || true
    fi
    # User gate is provider-native after spawn-diagnostic-l2.py:
    # Claude Code uses AskUserQuestion; Codex asks in the main thread/UI.
    # On accept → run-complete sees applied; on reject → BLOCK below.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.diagnostic_l2_spawned" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"proposal_id\":\"$L2_PROPOSAL_ID\"}" \
      >/dev/null 2>&1 || true
  fi
fi
```

> **Tại sao không tự apply L2 fix**: L2 đã sai trong dogfood 3.2
> (propose fix giả mà có vẻ hợp lý). User gate là single source of truth
> cho fix correctness. Audit trail (`.l2-proposals/`) cho phép trace
> sau-incident: proposal nào được accept/reject, fix tham chiếu commit nào.
</step>

<step name="phase4_goal_comparison" mode="full">
## Phase 4: GOAL COMPARISON

→ `narrate_phase "Phase 4 — Goal comparison" "So khớp ${N} goals từ TEST-GOALS với views đã khám phá"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase4_goal_comparison >/dev/null 2>&1 || true
```

### 4.0: RCRURD runtime verification (Task 23 — Codex GPT-5.5 review 2026-05-03)

For every TEST-GOALS/G-NN.md with `goal_type: mutation`, run the runtime
gate. BLOCK review on assertion fail (R8 update_did_not_apply, etc).
Action payload comes from per-phase fixture (`FIXTURES/G-NN.action.json`).

```bash
EVIDENCE_DIR="${PHASE_DIR}/.rcrurd-evidence"
mkdir -p "$EVIDENCE_DIR"
RCRURD_FAILED=0
RCRURD_RAN=0

if [ -d "${PHASE_DIR}/TEST-GOALS" ]; then
  for goal in "${PHASE_DIR}/TEST-GOALS"/G-*.md; do
    [ -f "$goal" ] || continue
    grep -qE "goal_type:[[:space:]]*mutation" "$goal" || continue
    RCRURD_RAN=$((RCRURD_RAN+1))
    ev_out="${EVIDENCE_DIR}/$(basename "$goal" .md).json"

    payload="{}"
    fixture="${PHASE_DIR}/FIXTURES/$(basename "$goal" .md).action.json"
    [ -f "$fixture" ] && payload=$(cat "$fixture")

    "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rcrurd-runtime.py \
      --goal-file "$goal" \
      --phase "${PHASE_NUMBER}" \
      --action-payload "$payload" \
      --auth-header "$(vg_config_get review.rcrurd_auth_header '')" \
      --evidence-out "$ev_out" || RCRURD_FAILED=1
  done
fi

if [ "$RCRURD_RAN" -gt 0 ]; then
  if [ "$RCRURD_FAILED" = "1" ]; then
    echo "⛔ Phase 4.0 RCRURD runtime — at least one mutation goal failed (of ${RCRURD_RAN} run)"
    echo "   Evidence: ${EVIDENCE_DIR}/*.json"
    echo "   Route through classifier (Task 7) — most are IN_SCOPE for current phase"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.rcrurd_runtime_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\",\"goals_run\":${RCRURD_RAN}}" \
      2>/dev/null || true
    exit 1
  fi

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.rcrurd_runtime_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_run\":${RCRURD_RAN}}" \
    2>/dev/null || true
fi
```

### 4a: Load Goals + edge cases

Read `${PHASE_DIR}/TEST-GOALS.md` (generated by /vg:blueprint).
If missing → generate from CONTEXT.md + API-CONTRACTS.md (fallback).

**P1 v2.49+ — Edge case variants:** also load `${PHASE_DIR}/EDGE-CASES/G-NN.md`
per goal. Status format extended:
- Old: `G-04: PASS` / `G-04: FAIL` / `G-04: NOT_TESTED`
- New: `G-04: PASS (5/6 variants — G-04-c1 NOT_TESTED [needs concurrency harness])`

For each variant in EDGE-CASES/G-NN.md:
- Replay `start_view` (per RUNTIME-MAP) with variant's input
- Verify expected_outcome matches actual UI/API response
- Mark per-variant: PASS | FAIL | NOT_TESTED (with reason)
- Aggregate to goal status (goal PASS only when all critical/high variants PASS)

Skip variants when:
- EDGE-CASES file missing (legacy phase pre-v2.49) → emit
  `review.edge_cases_unavailable` (severity=warn) + treat goal as 1-variant
- Variant priority=low + `--skip-low-edge-cases` flag set
- No-CRUD phase (CRUD-SURFACES.resources empty) → no variants expected

Emit per gate-blocked variant: `review.edge_case_variant_blocked` with
`{goal_id, variant_id, reason}` payload.

Parse goals: ID, description, success criteria, mutation evidence, dependencies, priority.

**Surface classification (v1.9.1 R1 — lazy migration, runs BEFORE browser discover decisions):**

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
# rc=2 → provider-native cheap classifier
#        Claude: Haiku Task per row; Codex: read-only scanner adapter over pending TSV
# rc=3 → provider-native prompt (surface list from config), then classify_goals_apply
```

Parse `**Surface:** <name>` per goal.

**Surface-aware routing (tightened v1.9.1 R1):**

For each goal:
- `surface == "ui"` / `"ui-mobile"` → proceed with existing browser RUNTIME-MAP lookup below.
- `surface ∈ { api, data, time-driven, integration, custom }` → skip browser discover for this goal; instead run lightweight **surface probe**:
  * `api`        → grep `apps/**/src/**` for route handler matching contract path → READY if present.
  * `data`       → grep migrations + `config.infra_deps` for table/collection → READY if present; INFRA_PENDING if service unavailable.
  * `time-driven`→ grep cron/scheduler registration in `apps/workers/**`/`apps/api/**` → READY if handler wired.
  * `integration`→ check `${PHASE_DIR}/test-runners/fixtures/${gid}.integration.sh` exists AND downstream caller found → READY.

Result feeds GOAL-COVERAGE-MATRIX with `(status, surface, probe_evidence)`.

**Pure-backend fast-path:**
```bash
UI_GOAL_COUNT=$(grep -c '^\*\*Surface:\*\* ui' "${PHASE_DIR}/TEST-GOALS.md" || echo 0)
if [ "$UI_GOAL_COUNT" -eq 0 ]; then
  echo "🧭 Pure-backend phase (không có goal UI) — bỏ qua browser discovery (khám phá trình duyệt), dùng surface probes." >&2
  # Emit empty RUNTIME-MAP if not written yet, skip to 4b
  [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || echo '{"views":{},"goal_sequences":{}}' > "${PHASE_DIR}/RUNTIME-MAP.json"
  # Issue #120: runtime_contract still requires one root scan-*.json artifact
  # even when backend-only review legitimately skips browser discovery. Emit a
  # synthetic backend scan so run-complete does not false-block on must_write.
  BACKEND_SCAN_JSON="${PHASE_DIR}/scan-backend-surface-probes.json"
  if [ ! -f "$BACKEND_SCAN_JSON" ]; then
    "${PYTHON_BIN:-python3}" - "$BACKEND_SCAN_JSON" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "view": "backend://surface-probes",
    "surface": "backend",
    "generated_by": "phase4_goal_comparison.pure_backend_fastpath",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "results": [],
    "forms": [],
    "tables": [],
    "modal_triggers": [],
    "sub_views_discovered": [],
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  fi
fi
```

**Mixed-phase surface probe execution (v1.9.2.3 P3):**

For phases có CẢ UI goals (cần browser) VÀ backend goals (api/data/integration/time-driven), browser phase chỉ cover UI goals. Backend goals PHẢI được probe SEPARATELY để avoid rơi vào NOT_SCANNED branch.

```bash
# Run surface probes cho goals có surface ≠ ui
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-probe.sh" 2>/dev/null || true
if type -t run_surface_probe >/dev/null 2>&1; then
  PROBE_RESULTS_JSON="${PHASE_DIR}/.surface-probe-results.json"
  echo '{"probed_at":"'"$(date -u +%FT%TZ)"'","results":{' > "$PROBE_RESULTS_JSON"
  FIRST=true

  # Extract goal_id + surface pairs from TEST-GOALS.md
  ${PYTHON_BIN} -c "
import re
tg = open('${PHASE_DIR}/TEST-GOALS.md', encoding='utf-8').read()
for gid, surface in re.findall(r'^## Goal (G-[\w]+):.*?^\*\*Surface:\*\* (\w[\w-]*)', tg, re.M|re.S):
    print(f'{gid} {surface}')
" | while read -r gid surface; do
    surface="${surface%$'\r'}"
    # Skip UI — browser phase handles them
    [ "$surface" = "ui" ] || [ "$surface" = "ui-mobile" ] && continue

    PROBE=$(run_surface_probe "$gid" "$surface" "$PHASE_DIR" 2>/dev/null)
    STATUS=$(echo "$PROBE" | cut -d'|' -f1)
    EVIDENCE=$(echo "$PROBE" | cut -d'|' -f2- | sed 's/"/\\"/g')

    [ "$FIRST" = "true" ] && FIRST=false || echo "," >> "$PROBE_RESULTS_JSON"
    printf '"%s":{"surface":"%s","status":"%s","evidence":"%s"}' \
           "$gid" "$surface" "$STATUS" "$EVIDENCE" >> "$PROBE_RESULTS_JSON"
  done

  echo '}}' >> "$PROBE_RESULTS_JSON"

  # Summary narration
  PROBED=$(${PYTHON_BIN} -c "
import json
d = json.load(open('$PROBE_RESULTS_JSON'))['results']
from collections import Counter
c = Counter(r['status'] for r in d.values())
print(f'Phase 4a surface probes: {len(d)} backend goals probed → {dict(c)}')")
  echo "▸ $PROBED"

  # v2.48.1 (Issue #85) — backfill synthetic goal_sequences[gid] for non-UI
  # goals from probe results so verify-matrix-evidence-link.py (which only
  # inspects RUNTIME-MAP goal_sequences[]) sees backend evidence. Closes the
  # surface-probe schema gap that BLOCKed Phase 3.2 dogfood with 32 non-UI
  # READY goals flagged matrix_status_without_runtime_sequence.
  # Idempotent: re-runs overwrite synthetic entries by gid, never overwrites
  # real browser-recorded sequences.
  if [ -f "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" \
      --phase-dir "$PHASE_DIR" 2>&1 | sed 's/^/▸ /' || true
  fi
fi
```

**Phase 4b integration:** Khi check goal_sequences cho backend goals (surface ≠ ui), trước khi mark NOT_SCANNED hãy check `.surface-probe-results.json`:
- Nếu probe READY → map → STATUS: READY với evidence từ probe (handler path, migration file, caller reference).
- Nếu probe BLOCKED → map → STATUS: BLOCKED với evidence là probe reason.
- Nếu probe INFRA_PENDING → map → STATUS: INFRA_PENDING.
- Nếu probe SKIPPED (can't parse criteria) → fallthrough to NOT_SCANNED branch → buộc user cải thiện TEST-GOALS hoặc override.

**Infra dependency filter (config-driven):**

If goal has `**Infra deps:**` field (e.g., `[clickhouse, kafka, pixel_server]`):
```bash
# Check each infra dep against current environment
for dep in goal.infra_deps:
  SERVICE_CHECK=$(read config.infra_deps.services[dep].check_${ENV})
  if ! eval "$SERVICE_CHECK" 2>/dev/null; then
    goal.status = "INFRA_PENDING"
    goal.skip_reason = "${dep} not available on ${ENV}"
  fi
done
```

Goals classified as `INFRA_PENDING` are **excluded from gate calculation** (when `config.infra_deps.unmet_behavior == "skip"`). They don't count as BLOCKED or FAIL — they're simply not testable on current environment.

Display: `INFRA_PENDING ({dep})` in matrix with distinct icon.

**Console noise filter (config-driven):**

When evaluating console errors from Phase 2 discovery, filter against `config.console_noise.patterns`:
```bash
if [ "${config_console_noise_enabled}" = "true" ]; then
  for pattern in config.console_noise.patterns:
    # Remove matching errors from bug list — classify as INFRA_NOISE
    REAL_ERRORS=$(echo "$ALL_CONSOLE_ERRORS" | grep -viE "$pattern")
  done
  NOISE_COUNT=$((TOTAL_ERRORS - REAL_ERROR_COUNT))
  echo "Console: ${REAL_ERROR_COUNT} real errors, ${NOISE_COUNT} infra noise (filtered)"
fi
```

Only REAL_ERRORS (not matching noise patterns) count as view failures.

### 4b: Map Goals to RUNTIME-MAP

For each goal, check goal_sequences in RUNTIME-MAP.json:

```
For each goal:
  IF goal_sequences[goal_id] exists AND result == "passed":
    → STATUS: READY (goal was verified during Pass 2a)

  IF goal_sequences[goal_id] exists AND result == "failed":
    → STATUS: BLOCKED (with specific failure steps from goal_sequence)

  IF goal_sequences[goal_id] does NOT exist:
    # Before marking UNREACHABLE, verify code presence to distinguish
    # true "not built" from "built but not scanned"
    code_exists = check via grep against config.code_patterns:
      - Does goal's expected page file exist? (e.g., FloorRulesListPage.tsx)
      - Is the route registered? (e.g., /floor-rules in router)
      - Do related API endpoints have handlers? (grep API-CONTRACTS vs apps/api/)

    IF code_exists == FALSE:
      → STATUS: UNREACHABLE (feature not built — fix with /vg:build --gaps-only)

    IF code_exists == TRUE:
      → STATUS: NOT_SCANNED (intermediate only — MUST resolve before review exits)
      Root cause likely one of:
        - Multi-step wizard/mutation needs dedicated browser session
        - Goal path not reachable from discovered sidebar (orphan route)
        - Review ran --retry-failed but this goal wasn't in retry set
        - Haiku agent timed out or skipped
        - Goal has no UI surface but TEST-GOALS didn't mark infra_deps
      → RESOLUTION (tightened 2026-04-17 — NOT_SCANNED không được defer sang /vg:test):
        NOT_SCANNED là trạng thái TRUNG GIAN, KHÔNG phải kết luận hợp lệ.
        Review PHẢI resolve thành 1 trong 4 status kết luận: READY | BLOCKED | UNREACHABLE | INFRA_PENDING
        Cách resolve (pick 1):
          a) /vg:review {phase} --retry-failed với deeper probe (nếu timeout/depth issue)
          b) Goal không có UI surface → update TEST-GOALS với `**Infra deps:** [<user-defined no-ui tag>]` → re-classify INFRA_PENDING (tag value do user định nghĩa trong config.infra_deps, workflow không hardcode)
          c) Orphan/hidden route → verify config.code_patterns.frontend_routes đã cover pattern đó
          d) Genuinely unreachable (feature đã build nhưng UX path không exist) → manually mark UNREACHABLE with reason note
```

**Status semantics (tightened 2026-04-17):**

4 **status kết luận hợp lệ** (chỉ 4 status này được write vào GOAL-COVERAGE-MATRIX final):

| Status | Meaning | Fix command |
|---|---|---|
| READY | Goal verified, evidence in goal_sequences | none |
| BLOCKED | View found, scan ran, criteria failed | fix code → `--retry-failed` |
| UNREACHABLE | Code not in repo / UX path không exist | `/vg:build --gaps-only` |
| INFRA_PENDING | Goal needs service/infra not available on ENV | deploy infra or sandbox |

2 **status trung gian** (PHẢI resolve trước khi exit Phase 4):

| Status | Meaning | Action BẮT BUỘC |
|---|---|---|
| NOT_SCANNED | Code exists, review didn't replay | `--retry-failed` HOẶC re-classify thành 1 trong 4 status trên |
| FAILED | Scan timeout/exception | check logs → `--retry-failed` |

**⛔ GLOBAL RULE: KHÔNG được defer NOT_SCANNED sang /vg:test.**

Lý do: `/vg:test` codegen LẤY steps từ `goal_sequences[]` mà review ghi. NOT_SCANNED = review không ghi sequence = codegen không có input. Test không phải fallback cho review miss.

Goals không có UI surface đúng ra phải mark `infra_deps: [<no-ui tag>]` trong TEST-GOALS (tag value do project config quy ước) → skip ở review (INFRA_PENDING) → test qua integration/unit layer ở build phase, KHÔNG qua /vg:test E2E.

### 4c-pre: ⛔ NOT_SCANNED resolution gate (tightened 2026-04-17)

Trước khi chạy weighted gate, PHẢI resolve mọi `NOT_SCANNED` + `FAILED` thành 1 trong 4 kết luận.

```bash
# OHOK-8 round-4 Codex fix: replace pseudocode with real bash grep.
# Previously `count goals where status == "NOT_SCANNED"` was not executable
# → gate couldn't run → NOT_SCANNED goals slipped through unresolved.
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
NOT_SCANNED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*NOT_SCANNED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
FAILED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*FAILED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
INTERMEDIATE=$((NOT_SCANNED_COUNT + FAILED_COUNT))
# Build the list of intermediate goal IDs (used later in override auto-convert)
INTERMEDIATE_GOALS=$(grep -oE '^\| (G-[0-9]+)[^|]*\|[^|]*\|[^|]*\|[[:space:]]*(NOT_SCANNED|FAILED)[[:space:]]*\|' "$MATRIX" 2>/dev/null \
  | grep -oE 'G-[0-9]+' | sort -u | tr '\n' ' ')

if [ "$INTERMEDIATE" -gt 0 ]; then
  echo "⛔ Review cannot exit Phase 4 — ${INTERMEDIATE} intermediate goals:"
  echo "   NOT_SCANNED: ${NOT_SCANNED_COUNT}"
  echo "   FAILED:      ${FAILED_COUNT}"
  echo ""
  echo "Intermediate ≠ conclusion. Resolve before exit:"
  echo "  a) /vg:review ${PHASE_NUMBER} --retry-failed  (deeper probe)"
  echo "  b) Update TEST-GOALS with 'Infra deps: [backend_only]' nếu goal không có UI"
  echo "     → re-classify INFRA_PENDING"
  echo "  c) Fix config.code_patterns.frontend_routes nếu route ẩn khỏi sidebar"
  echo "  d) Manual re-classify UNREACHABLE (feature không tồn tại) với reason note"
  echo ""
  echo "⛔ KHÔNG ĐƯỢC defer sang /vg:test để 'cover' NOT_SCANNED goals."
  echo "   Test codegen lấy input từ goal_sequences review ghi. NOT_SCANNED = no input."
  echo ""
  echo "Override (NOT RECOMMENDED — creates debt):"
  echo "  /vg:review ${PHASE_NUMBER} --allow-intermediate"
  echo "  → Auto-convert remaining NOT_SCANNED → UNREACHABLE với reason='review-skip'"
  echo "  → Logged to GOAL-COVERAGE-MATRIX.md 'Debt' section"

  if [[ ! "$ARGUMENTS" =~ --allow-intermediate ]]; then
    # v1.9.1 R2+R4: block-resolver — try L1 auto-fix (re-scan failed goals) before demanding user override.
    # If L1 fails, L2 architect proposal is presented through provider-native L3 prompt.
    # L4 only when L2 proposal rejected AND no user direction.
    # See _shared/lib/block-resolver.sh
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.4c-pre"
      BR_GATE_CONTEXT="NOT_SCANNED/FAILED goals block review exit. ${INTERMEDIATE} intermediate goals need conclusion (READY/BLOCKED/UNREACHABLE/INFRA_PENDING)."
      BR_EVIDENCE=$(printf '{"not_scanned":%d,"failed":%d,"total_intermediate":%d}' "$NOT_SCANNED_COUNT" "$FAILED_COUNT" "$INTERMEDIATE")
      BR_CANDIDATES='[{"id":"retry-failed-scan","cmd":"echo retry-failed auto-fix would re-trigger scanner for FAILED goals only; skipping in safe mode","confidence":0.5,"rationale":"retry-failed probe may reclassify goals without human override"}]'
      BR_RESULT=$(block_resolve "not-scanned-defer" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LEVEL" = "L1" ]; then
        echo "✓ Block resolver L1 self-resolved — intermediate goals auto-fixed"
      elif [ "$BR_LEVEL" = "L2" ]; then
        block_resolve_l2_handoff "not-scanned-defer" "$BR_RESULT" "$PHASE_DIR"
        echo "  Để proceed sau khi user chấp nhận proposal: re-run /vg:review ${PHASE_NUMBER} --allow-intermediate --reason='<applied proposal>'" >&2
        exit 2
      else
        # L4 truly stuck — print human-direction message
        block_resolve_l4_stuck "not-scanned-defer" "L1 failed + L2 produced no actionable proposal"
        exit 1
      fi
    else
      exit 1
    fi
  else
    # v1.9.0 T1: rationalization guard — NOT_SCANNED defer is a classic rationalization surface.
    RATGUARD_RESULT=$(rationalization_guard_check "not-scanned-defer" \
      "NOT_SCANNED = review didn't replay the goal sequence. Deferring = test codegen has no input. Auto-UNREACHABLE hides coverage debt." \
      "intermediate_goals=${INTERMEDIATE_GOALS} not_scanned=${NOT_SCANNED_COUNT} failed=${FAILED_COUNT}")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "not-scanned-defer" "--allow-intermediate" "$PHASE_NUMBER" "review.4c-pre" "${INTERMEDIATE} intermediate goals"; then
      exit 1
    fi
    # OHOK-8 round-4 Codex fix: update_goal_status was undefined function.
    # Replaced with real bash sed that rewrites matrix row in-place.
    # Auto-convert intermediate → UNREACHABLE với audit trail.
    TS=$(date -u +%FT%TZ)
    for gid in $INTERMEDIATE_GOALS; do
      # Match row `| G-XX |...|...|...| (NOT_SCANNED|FAILED) |`, replace
      # status column only. Preserve other columns. Use | delimiter in sed
      # to avoid conflicts with pipe chars in evidence.
      sed -i -E "s|^(\| ${gid} \|[^|]+\|[^|]+\|[^|]+\|)[[:space:]]*(NOT_SCANNED\|FAILED)[[:space:]]*\|(.*)$|\1 UNREACHABLE |review-skip-\2 @${TS}\3|" \
        "$MATRIX" 2>/dev/null || true
    done
    echo "intermediate-override: ${INTERMEDIATE} goals auto-converted UNREACHABLE ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/build-state.log"
  fi
fi
```

### 4c: Write GOAL-COVERAGE-MATRIX.md (v1.9.2.4 runnable merger)

```bash
# Call matrix-merger.sh helper — reads RUNTIME-MAP + probe-results + TEST-GOALS,
# computes per-goal status with priority precedence (browser > probe > code_exists),
# writes canonical GOAL-COVERAGE-MATRIX.md with summary + by-priority + details + gate.
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/matrix-merger.sh" 2>/dev/null || true
if type -t merge_and_write_matrix >/dev/null 2>&1; then
  MERGE_OUTPUT=$(merge_and_write_matrix "$PHASE_DIR" \
    "${PHASE_DIR}/TEST-GOALS.md" \
    "${PHASE_DIR}/RUNTIME-MAP.json" \
    "${PHASE_DIR}/.surface-probe-results.json" \
    "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>&1)

  # Extract machine-readable counts + verdict
  VERDICT=$(echo "$MERGE_OUTPUT" | grep '^VERDICT=' | cut -d= -f2)
  READY=$(echo "$MERGE_OUTPUT" | grep '^READY=' | cut -d= -f2)
  BLOCKED=$(echo "$MERGE_OUTPUT" | grep '^BLOCKED=' | cut -d= -f2)
  NOT_SCANNED=$(echo "$MERGE_OUTPUT" | grep '^NOT_SCANNED=' | cut -d= -f2)
  INTERMEDIATE=$(echo "$MERGE_OUTPUT" | grep '^INTERMEDIATE=' | cut -d= -f2)
  export VERDICT READY BLOCKED NOT_SCANNED INTERMEDIATE

  echo "✓ GOAL-COVERAGE-MATRIX.md: VERDICT=$VERDICT (ready=$READY blocked=$BLOCKED not_scanned=$NOT_SCANNED)"
else
  echo "⚠ matrix-merger.sh missing — falling back to manual matrix write (legacy path)"
  # Legacy path: orchestrator writes matrix directly using template below
fi

# Defense-in-depth: matrix-merger now downgrades shallow mutation sequences, but
# keep an explicit validator so legacy/hand-written RUNTIME-MAP files cannot
# mark create/update/delete goals READY from list-only evidence.
CRUD_DEPTH_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-runtime-map-crud-depth.py"
if [ -f "$CRUD_DEPTH_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_DEPTH_VAL" --phase "${PHASE_NUMBER}" \
    > "${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json" 2>&1
  CRUD_DEPTH_RC=$?
  if [ "$CRUD_DEPTH_RC" != "0" ]; then
    echo "⛔ Runtime map CRUD depth gate failed — see ${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json"
    echo "   Mutation goals require observed POST/PUT/PATCH/DELETE + persistence proof."
    echo "   Re-run /vg:review ${PHASE_NUMBER} with deeper CRUD interaction before /vg:test."
    exit 1
  fi
fi

# v2.35.0 verdict gate hardening (closes #51) — 3 invariants replacing path-existence checks
# Override per-phase: --skip-content-invariants=<reason> logs OVERRIDE-DEBT
if [[ ! "$ARGUMENTS" =~ --skip-content-invariants ]]; then
  for VALIDATOR in verify-interface-standards verify-goal-security verify-goal-perf verify-security-baseline verify-haiku-scan-completeness verify-runtime-map-coverage verify-crud-runs-coverage verify-error-message-runtime; do
    VAL_PATH="${REPO_ROOT}/.claude/scripts/validators/${VALIDATOR}.py"
    if [ -f "$VAL_PATH" ]; then
      mkdir -p "${PHASE_DIR}/.tmp"
      VAL_OUT="${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic-input.txt"
      case "$VALIDATOR" in
        verify-interface-standards)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" > "$VAL_OUT" 2>&1
          ;;
        verify-error-message-runtime)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-goal-security|verify-goal-perf)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-security-baseline)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --scope all > "$VAL_OUT" 2>&1
          ;;
        *)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase-dir "$PHASE_DIR" > "$VAL_OUT" 2>&1
          ;;
      esac
      VAL_RC=$?
      cat "$VAL_OUT"
      if [ "$VAL_RC" -ne 0 ]; then
        echo ""
        echo "⛔ Verdict gate invariant FAILED: ${VALIDATOR}"
        echo "   v2.35.0 hardened gate: review cannot PASS with empty/incomplete artifacts."
        echo "   Either re-run /vg:review ${PHASE_NUMBER} with proper scanner/dispatch coverage,"
        echo "   or pass --skip-content-invariants=\"<reason>\" to log OVERRIDE-DEBT."
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.${VALIDATOR}" \
            --phase-dir "$PHASE_DIR" \
            --input "$VAL_OUT" \
            --out-md "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" 2>/dev/null || true
        fi
        emit_telemetry_v2 "review_verdict_invariant_failed" "${PHASE_NUMBER}" \
          "review.4-verdict" "${VALIDATOR}" "BLOCK" "{}" 2>/dev/null || true
        exit 1
      fi
    fi
  done
fi

LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ] && [[ ! "$ARGUMENTS" =~ --skip-lens-plan-gate ]]; then
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --validate-only \
    --json \
    > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1
  LENS_GATE_RC=$?
  if [ "$LENS_GATE_RC" -ne 0 ]; then
    echo ""
    echo "⛔ Review lens plan gate FAILED — required checklist plugins lack evidence."
    echo "   See ${PHASE_DIR}/.tmp/review-lens-plan-validation.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.lens_plan_gate" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
        --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
    fi
    echo "   Re-run /vg:review ${PHASE_NUMBER} --mode=full --force so API docs, browser inventory, URL-state/filter/paging, error-message, visual, and findings lenses execute."
    exit 1
  fi
fi

```

**Generated matrix format (canonical, from matrix-merger):**

```markdown
# Goal Coverage Matrix — Phase {phase}
**Generated:** {ISO-timestamp}
**Source:** RUNTIME-MAP.json + .surface-probe-results.json
**Merger:** _shared/lib/matrix-merger.sh v1.9.2.4

## Summary
- Total goals: {N}
- READY: {N}
- BLOCKED: {N}
- NOT_SCANNED: {N} (intermediate)
- UNREACHABLE: {N}
- INFRA_PENDING: {N}
- FAILED: {N} (intermediate)

## By Priority
| Priority | Ready | Blocked | Other | Total | Threshold | Pass % | Status |
|----------|-------|---------|-------|-------|-----------|--------|--------|
| critical | {N} | {N} | {N} | {N} | 100% | {X%} | ✅ PASS/⛔ BLOCK |
| important | {N} | {N} | {N} | {N} | 80% | {X%} | ... |
| nice-to-have | {N} | {N} | {N} | {N} | 50% | {X%} | ... |

## Goal Details
| Goal | Priority | Surface | Status | Evidence |
|------|----------|---------|--------|----------|
| G-01 | critical | api | READY | handler=apps/api/src/... |

## Gate: ✅/⛔/⚠️ {VERDICT}
{PASS|BLOCK|INTERMEDIATE message with next-action hints}
```

### 4d: Inline triage + apply scope-tag actions (v1.14.0+ A.2)

Triage chạy **inline** ngay sau matrix ghi, TRƯỚC 100% gate. Mục đích: đọc scope tag (`depends_on_phase`, `verification_strategy`) từ CONTEXT.md, phân loại mỗi UNREACHABLE thành verdict + action_required, rồi áp dụng action nào autonomous được (mark_deferred/mark_manual). Các action cần người quyết định (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) sẽ ghi vào hàng đợi nhưng vẫn BLOCK gate — **không có đường thoát ngụỵ trang**.

```bash
session_mark_step "4d-inline-triage"
echo ""
echo "🔍 Triage + áp dụng action cho UNREACHABLE goals (v1.14.0+)..."

# v1.14.3 H3 — pre-scan test source for @deferred markers so triage sees them
# alongside scope tags. Fixes gap where executor-written it.skip('@deferred X')
# was ignored (tests were skipped but matrix still BLOCKED).
DEFER_SCANNER=".claude/scripts/scan-deferred-tests.py"
if [ -f "$DEFER_SCANNER" ]; then
  echo "▸ Pre-scan: @deferred markers in test source..."
  ${PYTHON_BIN:-python3} "$DEFER_SCANNER" \
    --phase-dir "${PHASE_DIR}" --repo-root "${REPO_ROOT:-.}" 2>&1 | tail -12 || true
  # Writes .deferred-tests.json — consumed by unreachable-triage below
fi

# Chạy triage (sinh .unreachable-triage.json + UNREACHABLE-TRIAGE.md)
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
if type -t triage_unreachable_goals >/dev/null 2>&1; then
  triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
else
  echo "⚠ unreachable-triage.sh missing — triage bị bỏ qua, 100% gate sẽ hard-block mọi UNREACHABLE." >&2
fi

TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

if [ -f "$TRIAGE_JSON" ] && [ -f "$MATRIX" ]; then
  # Áp dụng action_required autonomous: mark_deferred, mark_manual
  # Những action còn lại (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) ghi log + để BLOCK.
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$TRIAGE_JSON" "$MATRIX" "$PHASE_DIR" "$PHASE_NUMBER" <<'PY'
import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

triage_path = Path(sys.argv[1])
matrix_path = Path(sys.argv[2])
phase_dir   = Path(sys.argv[3])
phase_num   = sys.argv[4]

try:
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
except Exception as e:
    print(f"⚠ Không đọc được triage JSON: {e}")
    sys.exit(0)

verdicts = triage.get("verdicts", {})

# v1.14.3 H3 — merge .deferred-tests.json as additional deferral source
# (test files with it.skip('@deferred X') markers that aren't in CONTEXT.md scope tags).
deferred_tests_path = phase_dir / ".deferred-tests.json"
test_deferrals = {}  # ts_id → {reason, kind}
if deferred_tests_path.exists():
    try:
        dt = json.loads(deferred_tests_path.read_text(encoding="utf-8"))
        for entry in dt.get("deferred_tests", []):
            ts = entry.get("ts_id")
            if ts:
                test_deferrals[ts] = entry
    except Exception as e:
        print(f"⚠ Không đọc được .deferred-tests.json: {e}")

if not verdicts and not test_deferrals:
    print("ℹ Không có UNREACHABLE cần triage — skip.")
    sys.exit(0)

matrix_text = matrix_path.read_text(encoding="utf-8")
pending_queue = []   # cho các action chờ user / destructive
applied       = {"mark_deferred": [], "mark_manual": [], "pending": []}

def update_status_in_matrix(text, gid, new_status, note=""):
    # Tìm dòng trong ## Goal Details có `| G-XX | ... | UNREACHABLE | ... |`
    # Thay UNREACHABLE → new_status; append note vào evidence nếu có.
    pat = re.compile(r'^(\| *' + re.escape(gid) + r' *\|[^|]*\|[^|]*\|) *UNREACHABLE *(\|[^\n]*)', re.M)
    def _repl(m):
        prefix = m.group(1)
        suffix = m.group(2)
        if note:
            suffix = suffix.rstrip("|").rstrip() + f" ({note})|"
        return f"{prefix} {new_status} {suffix}"
    return pat.sub(_repl, text, count=1)

for gid, v in verdicts.items():
    action   = v.get("action_required")
    params   = v.get("action_params", {})
    verdict  = v.get("verdict", "")

    if action == "mark_deferred":
        target = params.get("target_phase", "?")
        matrix_text = update_status_in_matrix(matrix_text, gid, "DEFERRED", f"depends_on_phase: {target}")
        applied["mark_deferred"].append((gid, target))
    elif action == "mark_manual":
        strat = params.get("strategy", "manual")
        matrix_text = update_status_in_matrix(matrix_text, gid, "MANUAL", f"verification: {strat}")
        applied["mark_manual"].append((gid, strat))
    elif action in ("spawn_fix_agent", "draft_amendment_ask", "prompt_scope_tag"):
        # Giữ UNREACHABLE — gate sẽ block; ghi vào pending queue
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": verdict,
            "action":  action,
            "params":  params,
            "title":   v.get("title", "(no title)"),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, action))

# v1.14.3 H3 — apply test-level deferrals (fills gap where scope tags missing
# but test source has it.skip('@deferred X')). Status depends on defer_kind:
#   depends_on_phase + test-codegen → DEFERRED
#   manual + faketime               → MANUAL
#   unknown                         → log as pending, leave as UNREACHABLE
for ts_id, entry in test_deferrals.items():
    # ts_id is "TS-XX"; matrix may have goal_ids like "TS-16" or "G-XX" — try TS- first
    gid = ts_id
    kind = entry.get("defer_kind", "unknown")
    reason = entry.get("defer_reason", "")
    if kind in ("depends_on_phase", "test-codegen"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "DEFERRED",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_deferred"].append((gid, f"test-marker:{kind}"))
    elif kind in ("manual", "faketime"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "MANUAL",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_manual"].append((gid, kind))
    else:
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": "test-level @deferred with unknown kind",
            "action":  "review_test_defer_reason",
            "params":  {"reason": reason, "source": entry.get("source_file", "")},
            "title":   entry.get("test_title", ""),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, "test-defer-unknown"))

# Re-sync header counts trong "## Summary" block nếu có thay đổi
def recount_summary(text):
    details = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
    if not details:
        return text
    body = details.group(1)
    counts = {"READY":0, "BLOCKED":0, "UNREACHABLE":0, "INFRA_PENDING":0,
              "DEFERRED":0, "MANUAL":0, "NOT_SCANNED":0, "FAILED":0}
    for line in body.splitlines():
        for k in counts:
            # Status cell đứng giữa 2 dấu | — tránh match keyword trong evidence
            if re.search(r'\|\s*' + k + r'\s*\|', line):
                counts[k] += 1
                break
    def _rewrite_summary(m):
        total = sum(counts.values())
        new = [
            "## Summary",
            f"- Total goals: {total}",
            f"- READY: {counts['READY']}",
            f"- DEFERRED: {counts['DEFERRED']} (tagged depends_on_phase)",
            f"- MANUAL: {counts['MANUAL']} (tagged verification_strategy)",
            f"- BLOCKED: {counts['BLOCKED']}",
            f"- UNREACHABLE: {counts['UNREACHABLE']}",
            f"- INFRA_PENDING: {counts['INFRA_PENDING']}",
            f"- NOT_SCANNED: {counts['NOT_SCANNED']} (intermediate)",
            f"- FAILED: {counts['FAILED']} (intermediate)",
            ""
        ]
        return "\n".join(new)
    new_text = re.sub(r'^## Summary\n(?:[-*].*\n)+', _rewrite_summary, text, count=1, flags=re.M)
    return new_text

matrix_text = recount_summary(matrix_text)
matrix_path.write_text(matrix_text, encoding="utf-8")

# Ghi pending queue vào .vg/PENDING-USER-REVIEW.md (append-only)
if pending_queue:
    pending_file = Path(".vg/PENDING-USER-REVIEW.md")
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not pending_file.exists()
    with pending_file.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("# Pending user review — hàng đợi quyết định đang chờ\n\n")
            f.write("Mỗi mục là một goal cần quyết định (scope tag / fix / amendment). ")
            f.write("User review xong → duyệt queue thay vì bị hỏi từng cái.\n\n")
            f.write("| Phase | Goal | Verdict | Action cần | Tiêu đề | Queued at |\n")
            f.write("|---|---|---|---|---|---|\n")
        for p in pending_queue:
            f.write(f"| {p['phase']} | {p['goal_id']} | {p['verdict']} | {p['action']} | "
                    f"{p['title'][:60]} | {p['queued_at']} |\n")

# Narration
print(f"▸ Triage applied: "
      f"{len(applied['mark_deferred'])} → DEFERRED, "
      f"{len(applied['mark_manual'])} → MANUAL, "
      f"{len(applied['pending'])} → chờ người duyệt")
for gid, tgt in applied["mark_deferred"]:
    print(f"  🔁 {gid} → DEFERRED (depends_on_phase: {tgt})")
for gid, strat in applied["mark_manual"]:
    print(f"  ✋ {gid} → MANUAL ({strat})")
for gid, act in applied["pending"]:
    print(f"  ⏳ {gid} → {act} (giữ UNREACHABLE, gate sẽ BLOCK đến khi giải quyết)")
PY
else
  [ -f "$TRIAGE_JSON" ] || echo "ℹ Không có triage JSON (không UNREACHABLE goal nào) — skip apply."
fi
```

### 4e: Cổng 100% (hard, v1.14.0+ A.3)

Thay gate trọng số (critical/important/nice-to-have) cũ bằng quy tắc đơn giản:

- **ĐẠT (PASS)** khi `BLOCKED == 0` VÀ `UNREACHABLE == 0` (goals ở trạng thái kết thúc: READY + DEFERRED + MANUAL + INFRA_PENDING).
- **BỊ CHẶN (BLOCK)** khi còn bất kỳ goal `BLOCKED` hoặc `UNREACHABLE`.

Không còn grey zone — DEFERRED và MANUAL là hai đường thoát hợp lệ nhưng phải declare ở `/vg:scope`, không phải review tự gắn.

```bash
session_mark_step "4e-100pct-gate"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

# Đọc config gate threshold (default 100, legacy-mode fallback 80)
GATE_THRESHOLD=$(${PYTHON_BIN} -c "
import re, sys
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold\s*:\s*(\d+)', c)
    print(m.group(1) if m else '100')
except Exception:
    print('100')
")

# Legacy-mode override: --legacy-mode flag hoặc config review.gate_threshold_legacy
if [[ "$ARGUMENTS" =~ --legacy-mode ]]; then
  GATE_THRESHOLD_LEGACY=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold_legacy\s*:\s*(\d+)', c)
    print(m.group(1) if m else '80')
except Exception:
    print('80')
")
  echo "⚠ --legacy-mode: dùng ngưỡng ${GATE_THRESHOLD_LEGACY}% (pre-v1.14). Flag này sẽ hết hạn sau 2 milestones."
  GATE_THRESHOLD="$GATE_THRESHOLD_LEGACY"
fi

# Count statuses từ matrix
if [ -f "$MATRIX" ]; then
  GATE_COUNTS=$(PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$MATRIX" <<'PY'
import re, sys, json
text = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
body = m.group(1) if m else ""
buckets = ["READY","DEFERRED","MANUAL","BLOCKED","UNREACHABLE","INFRA_PENDING","NOT_SCANNED","FAILED"]
counts = {b:0 for b in buckets}
for line in body.splitlines():
    for b in buckets:
        if re.search(r'\|\s*' + b + r'\s*\|', line):
            counts[b] += 1
            break
print(json.dumps(counts))
PY
)
  READY=$(echo "$GATE_COUNTS"        | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['READY'])")
  DEFERRED=$(echo "$GATE_COUNTS"     | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['DEFERRED'])")
  MANUAL=$(echo "$GATE_COUNTS"       | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['MANUAL'])")
  BLOCKED=$(echo "$GATE_COUNTS"      | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['BLOCKED'])")
  UNREACHABLE=$(echo "$GATE_COUNTS"  | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['UNREACHABLE'])")
  INFRA_PENDING=$(echo "$GATE_COUNTS"| ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['INFRA_PENDING'])")

  TOTAL=$((READY + DEFERRED + MANUAL + BLOCKED + UNREACHABLE + INFRA_PENDING))
  # Goals được tính là "kết thúc": READY + DEFERRED + MANUAL + INFRA_PENDING
  PASS_COUNT=$((READY + DEFERRED + MANUAL + INFRA_PENDING))
  FAIL_COUNT=$((BLOCKED + UNREACHABLE))

  if [ "$TOTAL" -gt 0 ]; then
    PASS_PCT=$(( PASS_COUNT * 100 / TOTAL ))
  else
    PASS_PCT=0
  fi

  echo ""
  echo "━━━ Cổng kiểm tra (${GATE_THRESHOLD}%) ━━━"
  echo "  Tổng goals:    $TOTAL"
  echo "  ✅ READY:      $READY"
  echo "  🔁 DEFERRED:   $DEFERRED (tagged depends_on_phase)"
  echo "  ✋ MANUAL:     $MANUAL (tagged verification_strategy)"
  echo "  ♻ INFRA:      $INFRA_PENDING (ngoài ENV hiện tại)"
  echo "  ⛔ BLOCKED:    $BLOCKED"
  echo "  ❓ UNREACHABLE:$UNREACHABLE"
  echo "  Tỉ lệ đạt:    ${PASS_PCT}% (yêu cầu ≥${GATE_THRESHOLD}%)"
  echo ""

  export GATE_THRESHOLD PASS_COUNT FAIL_COUNT PASS_PCT TOTAL
  export READY DEFERRED MANUAL BLOCKED UNREACHABLE INFRA_PENDING
else
  echo "⚠ GOAL-COVERAGE-MATRIX.md không tồn tại — không tính được gate."
  export FAIL_COUNT=999 PASS_PCT=0 GATE_THRESHOLD=100
fi
```

### 4f: Quyết định cổng (100% hard)

```bash
session_mark_step "4f-gate-decision"

# Quy tắc:
#   GATE_THRESHOLD == 100 (default)  → PASS iff FAIL_COUNT == 0
#   GATE_THRESHOLD <  100 (legacy)   → PASS iff PASS_PCT >= threshold
if [ "$GATE_THRESHOLD" = "100" ]; then
  GATE_PASS=$([ "$FAIL_COUNT" -eq 0 ] && echo "true" || echo "false")
else
  GATE_PASS=$([ "$PASS_PCT" -ge "$GATE_THRESHOLD" ] && echo "true" || echo "false")
fi

if [ "$GATE_PASS" = "true" ]; then
  echo "✅ Cổng ĐẠT — phase sẵn sàng cho /vg:test ${PHASE_NUMBER}"
  echo ""

  # v1.14.0+ A.4 — write trigger cho CROSS-PHASE-DEPS aggregator
  # Nếu có goal DEFERRED → append vào .vg/CROSS-PHASE-DEPS.md (idempotent)
  if [ "$DEFERRED" -gt 0 ]; then
    CPD_SCRIPT="${REPO_ROOT}/.claude/scripts/vg_cross_phase_deps.py"
    if [ -f "$CPD_SCRIPT" ]; then
      PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$CPD_SCRIPT" append "$PHASE_NUMBER" 2>&1 | sed 's/^/  /'
    else
      echo "⚠ vg_cross_phase_deps.py missing — DEFERRED entries không được aggregate." >&2
    fi
    echo "ℹ Có $DEFERRED goal DEFERRED (chờ phase phụ thuộc). Xem .vg/CROSS-PHASE-DEPS.md"
  fi
  if [ "$MANUAL" -gt 0 ]; then
    echo "ℹ Có $MANUAL goal MANUAL. /vg:accept sẽ prompt checklist người dùng."
  fi
  if [ "$INFRA_PENDING" -gt 0 ]; then
    echo "ℹ Có $INFRA_PENDING goal chờ infra (ngoài ENV). Re-run với --sandbox nếu cần."
  fi
else
  echo "⛔ Cổng BỊ CHẶN — còn $FAIL_COUNT goal chưa kết thúc."
  echo ""

  # Gợi ý hành động theo loại fail
  if [ "$BLOCKED" -gt 0 ]; then
    echo "  🛠 $BLOCKED goal BLOCKED (scan chạy nhưng criteria fail):"
    echo "     → Sửa code → re-run /vg:review ${PHASE_NUMBER} --fix-only"
  fi
  if [ "$UNREACHABLE" -gt 0 ]; then
    echo "  ❓ $UNREACHABLE goal UNREACHABLE (không reach được UI hoặc chưa build):"
    echo "     → Đọc ${PHASE_DIR}/UNREACHABLE-TRIAGE.md — mỗi goal có verdict + action gợi ý"
    echo "     → cross-phase-pending    → /vg:amend ${PHASE_NUMBER} thêm depends_on_phase tag"
    echo "     → bug-this-phase         → /vg:build ${PHASE_NUMBER} --gaps-only"
    echo "     → scope-amend destructive→ user confirm amendment rồi re-run review"

    # Nếu có pending queue, nhắc
    if [ -f ".vg/PENDING-USER-REVIEW.md" ]; then
      PENDING_CNT=$(grep -c "^| ${PHASE_NUMBER} " ".vg/PENDING-USER-REVIEW.md" 2>/dev/null || echo 0)
      [ "$PENDING_CNT" -gt 0 ] && echo "     → $PENDING_CNT mục đang chờ người duyệt (.vg/PENDING-USER-REVIEW.md)"
    fi
  fi

  echo ""
  echo "Không còn đường thoát tự động — scope tag phải declare ở /vg:scope (không phải review tự gán)."

  # Exit với mã lỗi để caller biết gate fail
  exit 1
fi
```
</step>

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
