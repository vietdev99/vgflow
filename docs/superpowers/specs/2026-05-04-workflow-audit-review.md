# Workflow audit: /vg:review

**Note:** Codex automated audit hit 480s timeout on large workflow (review.md
slim entry alone is 500 lines + 16 refs in `_shared/review/`). Synthesized
manually from R3 pilot knowledge + integrity audit work done earlier this
session (commits 5c495aa, 1ee4a50, bd3a4df).

## Q1 Gap analysis
**Verdict: Go.** R3 pilot integrity audit (commits 1ee4a50 + bd3a4df) confirmed
all 39 `<step name="...">` blocks from backup `commands/vg/.review.md.r3-backup`
are present across 16 refs in `commands/vg/_shared/review/`:
- preflight.md (8 steps), code-scan.md (3), discovery/{overview,delegation}.md
  (heavy subagent), lens-dispatch.md (1), runtime-checks.md (7 — recovered in
  integrity fix), findings/{collect,fix-loop}.md (5), verdict/* (4 split refs),
  delta-mode.md (1), profile-shortcuts.md (4), crossai.md (1), close.md (3).

Test pin: `scripts/tests/test_review_slim_size.py::test_review_md_step_blocks_in_refs_match_backup` (28 tests, all green).

## Q2 Loop/termination risk
**Verdict: With fixes.** Lens dispatch is hardcoded LENS_MAP (no AI cherry-pick risk).
Phase3 fix loop has explicit max-iter (`commands/vg/_shared/review/findings/fix-loop.md`).
**Risk:** review.md auto-fix loop after STEP 5 findings can call vg-amend recursively
when `--auto-fix` is set; max retries set per finding severity but no global session cap.

## Q3 Hook token cost
**Verdict: Go.** Typical full review (web-fullstack) fires:
- ~37 step.active + 37 mark-step (per `runtime_contract.must_touch_markers`)
- ~12 emit-event sites (tasklist_shown, native_tasklist_projected, started, env_mode_confirmed,
  api_precheck_completed, lens_plan_generated, recursive_probe.preflight_asked,
  edge_case_variant_blocked|edge_cases_unavailable, completed, crossai.verdict)
- Bug D3 already removed taskboard re-render (~285 tokens × 74 transitions = ~21K saved)
- Residual hook noise: ~0 bytes on success path; mid-flow reminder ~300-700 bytes
  per AskUserQuestion answer (≤5 typical)

## Q4 Role-standard compliance (Pro tester per ISTQB CT-AcT)
**Verdict: With fixes — strong on architecture, weak on traceability.**

Strong:
- Static + dynamic discovery dual-track (code-scan + browser-discovery)
- 19-lens dispatch architecturally enforced (LENS_MAP hardcoded in
  `scripts/spawn_recursive_probe.py`; AI cannot cherry-pick)
- 6-precondition eligibility gate prevents inappropriate lens spawns
- Profile shortcuts (delta/regression/schema-verify/link-check/infra-smoke)
  for non-full modes — pro tester knows when fast-path is appropriate
- RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md = traceability artifacts

Weak (per audit FAIL items #9-13 from R3 review design spec):
- Per-lens telemetry not yet emitted — `review.lens_plan_generated` fires but
  no `review.lens.<name>.dispatched` events to verify each of 19 lenses ran
- LENS_MAP coverage may not span all 19 lens files (audit PARTIAL #14)
- `--skip-lens-plan-gate` historically bypassed override-debt — closed in R3
  (commit `87530d3` added to `forbidden_without_override`)

## Q5 Top 3 actionable gaps
1. **Important** Add per-lens telemetry events `review.lens.<name>.dispatched`
   + `.completed` to `scripts/spawn_recursive_probe.py` so Stop hook can
   verify each lens actually ran (not just plan generated). R3 plan §A
   Tasks 1-2 (deferred from initial R3 ship).
2. **Important** Reconcile LENS_MAP element-class → lens mapping vs the 19
   lens files in `commands/vg/_shared/lens-prompts/`; some lens files (e.g.
   `lens-info-disclosure`) may appear in LENS_MAP but several others may be
   unreferenced. R3 plan §A Task 5 (deferred).
3. **Minor** Add lens-plan staleness check — if `API-CONTRACTS.md` mtime
   newer than REVIEW-LENS-PLAN.json, refuse stale plan. R3 plan §A Task 3.

## Verdict
**Production-ready?** Yes (with R3 Phase A tasks 1-3 + 5 as future improvements).

R3 slim refactor + integrity recovery (998 lines from 7 missing steps) +
universal Bug D enforcement + Bug D3 taskboard fix collectively make
/vg:review production-ready. Phase A telemetry/staleness work is enhancement,
not blocker.
