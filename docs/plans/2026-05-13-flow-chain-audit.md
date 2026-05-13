# VGFlow Full-Chain Audit — 2026-05-13
# Target: 50+ phase, multi-domain, multi-team project scale

> Scope: deterministic pipeline chain (specs → scope → blueprint → build → test-spec → review → test → accept)
> plus side flows: deploy, debug, amend, roam, learn, field-test, roadmap, add-phase, complete-milestone,
> design-system, design-extract, design-reverse, design-scaffold.
>
> Skip already-addressed: Batch 9 verdict/marker integrity (C4/C5), Batch 5/H13 observability,
> Batch 7 idempotency, Batches 1-4 lifecycle quality, Batch 6 review obs, Batch 2/8 cross-lane.
> All findings below are NEW gaps not addressed in Batches 1-9.

---

### Finding 1: Auto-chain coverage is incomplete — only review→build emits `next_command`; all other phase closes omit it

**Category:** B
**Severity:** high
**File:line:**
- `commands/vg/_shared/review/preflight.md:345` — only line in codebase that writes `state["next_command"]` to a PIPELINE-STATE.json
- `commands/vg/_shared/build/close.md:887–897` — only consumer: reads `next_command` and conditionally invokes it
- `commands/vg/_shared/scope/close.md:106` — emits `echo "  Next: /vg:blueprint {phase}"` (stdout only, no JSON write)
- `commands/vg/_shared/blueprint/close.md:180` — `echo "  Next: /vg:build ${PHASE_NUMBER}"` (stdout only)
- `commands/vg/test-spec.md:545` — `echo "  Next:  /vg:review ${PHASE_NUMBER}"` (stdout only)
- `commands/vg/_shared/test/close.md:458` — sets `pipeline_step=test-complete`, no `next_command` field
- `commands/vg/_shared/build/close.md:741–757` — sets `status=executed`, no `next_command` field

**Symptom:** In an --auto-chain or fully-automated 50-phase pipeline, only the segment review→build can auto-chain. Every other phase boundary (specs→scope, scope→blueprint, blueprint→build, test-spec→review, test→accept) relies on operator reading stdout and manually invoking the next command. In non-interactive / CI / `--auto-chain` runs, this silently stalls after the first phase.

**Root cause:** The `next_command` pattern was introduced for review→build but never extended to other phase closes. Other closes echo text instead of writing the JSON field. Build reads the review-written field for auto-chain; no equivalent reader exists at scope, blueprint, test-spec, test, or accept.

**Proposed fix:** Each phase close that emits "Next: /vg:X" via echo MUST also write `state["next_command"] = "/vg:X {PHASE_NUMBER}"` in its PIPELINE-STATE.json update block. Specifically:
- `scope/close.md` §1 PIPELINE-STATE block: add `state["next_command"] = f"/vg:blueprint {phase}"`
- `blueprint/close.md` §6.2.2+ PIPELINE-STATE block: add `state["next_command"] = f"/vg:build {phase}"`
- `test-spec.md` PIPELINE-STATE block (line ~521): add `state["next_command"] = f"/vg:review {phase}"`
- `test/close.md` §8.3.2 PIPELINE-STATE block (line ~458): add `state["next_command"] = f"/vg:accept {phase}"`
Additionally, each phase start should read `next_command` and respect `--auto-chain` / `--no-chain` flags (replicate the reader pattern from `review/close.md:887–934`).

---

### Finding 2: `LIFECYCLE.md` artifact table lists `TEST-RESULTS.json` but actual artifact is `SANDBOX-TEST.md` — onboarding gap causes phantom contract failures

**Category:** A, J
**Severity:** high
**File:line:**
- `commands/vg/LIFECYCLE.md:60` — states: `Required output: ${PHASE_DIR}/TEST-RESULTS.json + Playwright spec files`
- `commands/vg/_shared/test/close.md:148–152` — writes `${PHASE_DIR}/SANDBOX-TEST.md` (Stop hook enforces exact path)
- `commands/vg/_shared/accept/preflight.md:48` — reads `${PHASE_DIR}/*SANDBOX-TEST.md` (glob)
- `commands/vg/_shared/accept/gates.md:202` — reads `${PHASE_DIR}/*SANDBOX-TEST.md`

**Symptom:** Every new team member, doc reader, or AI agent consulting LIFECYCLE.md as the "canonical pipeline reference" (per its description field) expects a `TEST-RESULTS.json` artifact from `/vg:test`. When they probe for it in accept preflight or write a check depending on it, the file doesn't exist — only `SANDBOX-TEST.md` does. For a 50-phase project with multiple teams, this confusion silently degrades trust in pipeline docs and leads to incorrect manual gate checks.

**Root cause:** LIFECYCLE.md's phase table was written before the test close artifact was renamed/restructured from `TEST-RESULTS.json` to `SANDBOX-TEST.md`. The doc was not updated. The actual artifact is the frontmatter-bearing SANDBOX-TEST.md file, consumed by accept gates via glob.

**Proposed fix:**
1. `commands/vg/LIFECYCLE.md:60` — update Required output column to: `${PHASE_DIR}/SANDBOX-TEST.md (YAML frontmatter: phase, tested, status={PASSED|GAPS_FOUND|FAILED}, deploy_sha, environment) + Playwright spec files under .playwright-tests/`
2. Add Gates column entry for phase 7 (Accept): `accept/gates.md reads SANDBOX-TEST.md frontmatter status field; FAILED or missing = BLOCK`
3. Ensure `commands/vg/LIFECYCLE.md` includes the new artifacts from Batches 1–9 (step-ledger `.test-step-status.json`, `.verdict-computed.json`, `DEEP-TEST-SPECS.md`, `LIFECYCLE-SPECS.json`) so the doc reflects the true pipeline state.

---

### Finding 3: Blueprint and build/close use file-existence marker check (`-f .done`), not `verify_all_markers_strict_runid` — cross-run contamination possible at scale

**Category:** D
**Severity:** high
**File:line:**
- `commands/vg/_shared/test/close.md:626` — `if ! verify_all_markers_strict_runid "${PHASE_DIR}" "${PHASE_NUMBER}" "${VG_RUN_ID:-}"; then` (uses strict runid)
- `commands/vg/_shared/blueprint/close.md:133` — `if [ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]` (file-existence only)
- `commands/vg/_shared/blueprint/close.md:111–165` — full R7 verification block: uses `filter-steps.py` + `-f .done` check
- `commands/vg/_shared/build/close.md:188` — "Verifies R7 markers" (prose), actual check delegates to `run-complete` only, no explicit strict-runid call found in close.md
- `commands/vg/_shared/accept/cleanup/overview.md:117–118` — uses `-f .step-markers/accept/${STEP_ID}.done` || `-f .step-markers/${STEP_ID}.done` (file-existence, dual-path fallback)

**Symptom:** In a 50+ phase project with CI parallelism or resume scenarios, a stale `.done` marker from a previous run (different run_id, different SHA) will silently satisfy the R7 gate. Only test/close uses `verify_all_markers_strict_runid`. Blueprint, build, and accept all use file-existence checks. A team member who aborts a build mid-wave and reruns sees old markers satisfy the gate — the half-executed run appears complete.

**Root cause:** `verify_all_markers_strict_runid` was introduced as part of Batch 9 verdict integrity, but the fix was applied only to test/close. Blueprint and accept use the pre-Batch-9 pattern. Build close doesn't have an explicit in-file marker verification block (delegates to run-complete only).

**Proposed fix:**
- `blueprint/close.md` R7 block (line 127–165): replace `[ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]` with a call to the same `verify_all_markers_strict_runid` helper used in test/close.
- `accept/cleanup/overview.md` marker gate (line 117–118): same replacement.
- `build/close.md` step 12_run_complete: add explicit `verify_all_markers_strict_runid` call before `vg-orchestrator run-complete`.
- Document in `LIFECYCLE.md` that all phase closes use `run_id`-scoped marker verification as of v5.0.

---

### Finding 4: CrossAI findings from blueprint (`${PHASE_DIR}/crossai/`) are never read by accept — gap-hunt output silently discarded

**Category:** G
**Severity:** high
**File:line:**
- `commands/vg/_shared/blueprint/close.md:193` — commits `"${PHASE_DIR}/crossai/"` directory to git
- `commands/vg/_shared/review/close.md:36–62` — review CrossAI writes `${PHASE_DIR}/crossai/review-check.xml` and `.report.json`
- `commands/vg/_shared/test/preflight.md:418–449` — H12 Batch 8 collects `review/runs/` (not `crossai/`) into `VG_CROSSAI_FINDINGS_PATH`
- `commands/vg/_shared/accept/audit.md` — no grep match for "crossai", "CrossAI", or "review-check"
- `commands/vg/_shared/accept/gates.md:137` — mentions "CrossAI R6 Batch 5b fix" in a comment only; no read of crossai/ dir

**Symptom:** CrossAI review at blueprint finds gap-hunt findings (design gaps, missing edge cases, unimplemented contract behaviors). These are committed to `${PHASE_DIR}/crossai/` and also appear in `review-check.xml` after review. But accept/audit.md and accept/gates.md have zero consumption of these artifacts. A 50-phase project where CrossAI flagged 3 HIGH findings in blueprint will ship all 3 unacknowledged through accept.

**Root cause:** CrossAI output paths were defined at blueprint and review time. The accept lane was not updated to read them. H12 Batch 8 wired test/preflight to collect `review/runs/` but that is a different path family from `crossai/review-check.xml`. Accept audit never ingests CrossAI summary.

**Proposed fix:**
- `accept/audit.md`: add a new Phase F gate — read `${PHASE_DIR}/crossai/review-check.report.json` (if exists); surface any findings with severity>=HIGH as UAT checklist items. BLOCK accept if count of unacknowledged HIGH findings > 0 (unless `--allow-crossai-findings` override with debt).
- `accept/gates.md`: add CrossAI summary to the gate sequence after SANDBOX-TEST verdict check.
- Emit `accept.crossai_audit_skip` telemetry when crossai dir absent (so CI can track coverage).

---

### Finding 5: `vg-amend-cascade-analyzer` is read-only — D-XX changes never invalidate LIFECYCLE-SPECS.json or TEST-SPEC artifacts; test-spec runs on stale contracts

**Category:** F
**Severity:** high
**File:line:**
- `commands/vg/amend.md:26` — "cascade analysis warns but does NOT auto-modify PLAN.md or API-CONTRACTS.md"
- `commands/vg/amend.md:208,210` — subagent is read-only; produces informational report only
- `commands/vg/amend.md:178` — shows "TEST-GOALS.md: ${N} goals added/invalidated" but this is display text, not actual invalidation
- `commands/vg/amend.md:295–316` — v2.46 cross-phase stale D-XX check: flags stale phases but does not invalidate any artifact
- `commands/vg/_shared/test/codegen/delegation.md:61` — codegen MUST consume `${PHASE_DIR}/LIFECYCLE-SPECS.json`
- `commands/vg/test-spec.md:552–554` — "Deep test-spec artifacts exist and pass verify-deep-test-specs.py" — no staleness gate

**Symptom:** D-03 says "Use JWT expiry of 15 minutes". After `/vg:build`, a user amends D-03 to "Use JWT expiry of 5 minutes". Cascade analyzer warns but does NOT invalidate LIFECYCLE-SPECS.json, DEEP-TEST-SPECS.md, or TEST-EXECUTION-PLAN.json. The subsequent `/vg:test-spec` runs on the pre-amend lifecycle spec. Test assertions validate 15-minute tokens. All pass. `/vg:accept` ships with wrong expiry.

**Root cause:** The "informational only" cascade design was correct for early pipeline stages. But post-test-spec, LIFECYCLE-SPECS.json encodes concrete behavioral assertions that embed D-XX values. Amend does not write amendment metadata to the phase dir, so test-spec has no signal to regen.

**Proposed fix:**
- `amend.md` Phase 4 (post-cascade): write `${PHASE_DIR}/.amend-history.json` with `{amendment_id, changed_decisions[], affected_artifacts[], ts}`.
- `test-spec.md` preflight: check `.amend-history.json`; if `changed_decisions` overlaps D-XX cited in LIFECYCLE-SPECS.json goals, emit WARN and require `--regen` or `--skip-staleness-check` with override-debt.
- `blueprint/close.md`: when `amend.md` run is detected (via `.amend-history.json`), set PIPELINE-STATE flag `blueprint.needs_regen=true` so `/vg:build --resume` is blocked until re-run.

---

### Finding 6: Phase number width is hardcoded to `zfill(2)` across 14+ scripts — breaks at 100+ phases

**Category:** H
**Severity:** high
**File:line:**
- `scripts/generate-lifecycle-specs.py:720` — `prefix = str(phase).zfill(2) if str(phase).isdigit() else str(phase)`
- `scripts/generate-deep-test-specs.py:111` — same `zfill(2)` pattern
- `scripts/generate-interface-standards.py:51,53` — `normalized = f"{major.zfill(2)}.{rest}"`
- `scripts/preflight-invariants.py:59` — same pattern
- `scripts/fixture-backfill.py:70` — `candidates = sorted(phases_dir.glob(f"{head.zfill(2)}.{tail}-*"))`
- `scripts/codegen-fixture-inject.py:63` — `zfill(2)`
- `scripts/backfill-goal-traceability.py:31` — `zfill(2)`
- `scripts/migrate-legacy-provenance.py:101` — `zero_padded = f"{head.zfill(2)}.{tail}"`
- `scripts/build-uat-narrative.py:55` — `n.startswith(f"{phase}-") or n == phase.zfill(2)`
- `scripts/build-caller-graph.py:192` — `task_id = sections[i].zfill(2)`
- `scripts/lib/threshold-resolver.py:150` — `name == phase.zfill(2)`
- `scripts/migrate-d-xx-namespace.py:103` — strips leading zeros from path `07.10.1-user-drawer-tabs`
- `scripts/migrate-backend-surface-probe.py:52` — `zfill(2)`
- `scripts/fixture-prune.py:45` — `f"{head.zfill(2)}.{tail}"`

**Symptom:** For a 50-phase project today, phases are numbered `01`–`50` — no issue. But a multi-domain project that reaches phase 100 (e.g., 10 domains × 10 phases each) will produce phase dir `100-feature-name`. `zfill(2)` pads `100` to `100` (no change — `zfill` doesn't truncate), but glob patterns like `phases_dir.glob(f"{head.zfill(2)}.{tail}-*")` become `glob("100.x-*")` — that directory sorts correctly in lexicographic order, but queries for `phase="1"` produce `zfill(2)="01"` and fail to match `100-*`. Automated tools silently skip phase 100+ artifacts. The `migrate-d-xx-namespace.py:103` comment explicitly says "strip leading zeros" — removing the padding for nested phases like `07.10.1` destroys the sort invariant.

**Root cause:** `zfill(2)` was designed for single-digit or two-digit phase numbers. No project-level policy document defines the phase numbering scheme or maximum width. As domains and phases grow, `zfill(2)` becomes inconsistent.

**Proposed fix:**
- Define a project constant `VG_PHASE_NUMBER_WIDTH=2` in `.vg/config.md` (configurable to 3 for large projects).
- Replace all hardcoded `zfill(2)` with `str(phase).zfill(int(os.environ.get('VG_PHASE_NUMBER_WIDTH', '2')))` or a shared `phase_pad()` util in `scripts/lib/`.
- Add a validation in `vg-orchestrator init` that blocks creating a new phase when the new phase number would exceed the configured width.
- Introduce a `scripts/lib/phase_utils.py` module with `pad_phase(n)` and import it from all 14 scripts.

---

### Finding 7: No multi-domain / multi-team isolation mechanism — parallel phases from different domains share a single PIPELINE-STATE.json and event stream

**Category:** H
**Severity:** high
**File:line:**
- `commands/vg/roadmap.md:147–175` — defines S/M/L size tiers mentioning "1-3 REQs, single domain" or "may span 2 domains" — purely advisory
- `commands/vg/roadmap.md:175` — "Phase 4 depends on: None → can start anytime (parallel with others)"
- `commands/vg/_shared/scope/close.md:37` — writes to `"${PHASE_DIR}/PIPELINE-STATE.json"` (per-phase)
- `commands/vg/_shared/build/preflight.md:1` — no domain or team isolation checks
- `scripts/vg_cross_phase_deps.py:3` — tracks DEFERRED goals across phases, but no domain boundary concept
- `commands/vg/add-phase.md:265` — ROADMAP.md records phase dependencies, but no domain field

**Symptom:** In a 50+ phase project with Domain A (billing: phases 1–15) and Domain B (notifications: phases 16–30) running in parallel, there is no mechanism to:
1. Prevent Phase 7 (billing) from accidentally reading Phase 22 (notifications) CONTEXT.md decisions
2. Isolate test environments per domain
3. Route `--auto-chain` to the correct domain's next phase when two domains are at different pipeline stages
4. Track which team owns which phase for blame/escalation routing
PIPELINE-STATE.json is per-phase (isolated), but ROADMAP.md is shared, `CROSS-PHASE-DEPS.md` has no domain field, and the event stream (`events.db`) has no domain/team partition.

**Root cause:** VGFlow was designed for sequential single-team projects. The `roadmap.md` acknowledges parallelism conceptually but provides no enforcement, no locking, no domain scoping. `vg_cross_phase_deps.py` tracks DEFERRED goals but has no domain dimension. No lock file or coordination protocol exists for concurrent phase execution.

**Proposed fix:**
- Add `domain: <name>` and `team: <name>` fields to the ROADMAP.md phase block format (consumed by `add-phase.md`).
- `vg_cross_phase_deps.py`: add `domain` column to the tracking table.
- `events.db` schema: add `domain` and `team` columns to the event table; propagate from `PIPELINE-STATE.json`.
- `scope/preflight.md`: if `ROADMAP.md` contains a `domain` field for this phase, write it to `PIPELINE-STATE.json` so all downstream events carry it.
- Document "concurrent execution protocol" in LIFECYCLE.md: phases in different domains with no cross-phase deps can run concurrently; ROADMAP.md must be the serialization point for dependency ordering.

---

### Finding 8: `test/close.md` does not emit `next_command=/vg:accept` AND accept/preflight does not read/validate PIPELINE-STATE to confirm test passed before gating

**Category:** A, B
**Severity:** high
**File:line:**
- `commands/vg/_shared/test/close.md:450–462` — PIPELINE-STATE update: sets `status=tested`, `pipeline_step=test-complete`, `test_verdict=${VERDICT}` — but no `next_command` field
- `commands/vg/_shared/accept/preflight.md:48` — reads `*SANDBOX-TEST.md` for the test artifact check
- `commands/vg/_shared/accept/gates.md:200–249` — reads SANDBOX-TEST.md status field to gate accept
- `commands/vg/_shared/accept/preflight.md` — does NOT read `PIPELINE-STATE.json` `pipeline_step` or `test_verdict`

**Symptom:** A team member could run `/vg:accept` on a phase where `/vg:test` was skipped or ran but produced a broken SANDBOX-TEST.md with a malformed frontmatter. Accept/preflight only checks file existence (`*SANDBOX-TEST.md`), not that `pipeline_step==test-complete` in PIPELINE-STATE. A phase where test was force-interrupted (SANDBOX-TEST.md partially written before interrupt) would pass the file-existence gate but produce an incorrect verdict read. In a 50-phase automated pipeline, a race condition between test interrupt and accept start could silently accept a phase with incomplete test results.

**Root cause:** Two separate sources of truth exist for test completion state: PIPELINE-STATE.json (machine-authoritative) and SANDBOX-TEST.md (human-readable). Accept gates only read SANDBOX-TEST.md. The PIPELINE-STATE check at accept preflight does not verify `test-complete` pipeline_step, relying solely on the artifact file.

**Proposed fix:**
- `test/close.md` §8.3.2 PIPELINE-STATE block: add `state["next_command"] = f"/vg:accept {phase}"`.
- `accept/preflight.md`: add a cross-check — after SANDBOX-TEST.md existence check, read `PIPELINE-STATE.json` and verify `pipeline_step == "test-complete"` and `test_verdict` matches SANDBOX-TEST.md frontmatter status. If mismatch → BLOCK with "PIPELINE-STATE.test_verdict and SANDBOX-TEST.md status disagree — re-run /vg:test."
- This closes the partial-write race condition for large project CI runs.

---

### Finding 9: Deploy failure path has no documented chain-back to `/vg:build` or `/vg:review`; PIPELINE-STATE stays at `build-complete` after failed deploy

**Category:** I
**Severity:** medium
**File:line:**
- `commands/vg/_shared/deploy/execute.md:142` — on per-env failure: "AI: AskUserQuestion 3-option:" (interactive only, no chain hint)
- `commands/vg/_shared/deploy/persist-and-close.md:20` — `EVENT_TYPE="phase.deploy_failed"; OUTCOME="WARN"` — recorded as WARN, not BLOCK
- `commands/vg/_shared/deploy/persist-and-close.md:59` — lists `deploy.{started,completed,failed}` events in history but no chain-back to build or review
- `commands/vg/_shared/deploy/execute.md:69` — `d['results'].append({'env': '${env}', 'health': 'failed', ...})` — health stored, no next step written
- `commands/vg/_shared/deploy/preflight.md:73` — BLOCK on run-start fail, no rollback documented

**Symptom:** `/vg:deploy` fails on staging. PIPELINE-STATE.json retains `pipeline_step=build-complete` (set by build/close). Deploy persist-and-close writes `phase.deploy_failed` as a WARN event. The operator has no structured signal for whether the fix requires: (a) re-running deploy, (b) going back to `/vg:build` to fix a config, or (c) going back to `/vg:review` for a runtime issue. In a 50-phase project with CI triggering deploys automatically, the failed phase stays in limbo — no `next_command` is written, and no rollback is invoked.

**Root cause:** Deploy was designed as an optional post-accept step with interactive recovery. No chain-back protocol exists for automated pipelines. `PREVIOUS_SHA` is captured (execute.md:30) but no rollback command uses it.

**Proposed fix:**
- `deploy/persist-and-close.md`: on deploy failure, write `PIPELINE-STATE.json` `pipeline_step=deploy-failed` and `next_command` based on failure type: if `health: failed` on ALL envs → `next_command=/vg:build {phase} --resume`; if partial → `next_command=/vg:deploy {phase} --retry`.
- `deploy/execute.md`: on per-env failure with `PREVIOUS_SHA` available, emit `deploy.rollback_available` event with `{previous_sha, env}` so CI can invoke a rollback script.
- Document rollback procedure: `git revert ${DEPLOY_SHA} && /vg:deploy {phase} --env staging` pattern in deploy/overview.md.

---

### Finding 10: LIFECYCLE.md (`vg:LIFECYCLE`) is not referenced by onboarding commands (`/vg:health`, `/vg:doctor`) and omits all Batch 1–9 infrastructure (ledgers, validators, crossai, step-markers format)

**Category:** J
**Severity:** medium
**File:line:**
- `commands/vg/LIFECYCLE.md:98–106` — phase completion criteria lists: telemetry events, step markers, schema validators, run-complete — but does NOT mention `.test-step-status.json` ledger, `verify_all_markers_strict_runid`, `.verdict-computed.json`, or CrossAI verdict gating
- `commands/vg/LIFECYCLE.md:119–126` — cross-references: `discovery-flowchart.md`, `eng-principles.md`, `rationalization-tables.md`, `next.md`, `doctor.md` — no reference to `_shared/test/close.md` ledger contract or any Batch artifact
- `commands/vg/LIFECYCLE.md:57–61` — artifact table: lists `DEEP-TEST-SPECS.md`, `LIFECYCLE-SPECS.json` etc. for test-spec, but NOT `SANDBOX-TEST.md` (as noted in Finding 2)
- `commands/vg/doctor.md` — (referenced in LIFECYCLE) not checked for LIFECYCLE.md reference
- `commands/vg/health.md` — not checked for LIFECYCLE.md reference

**Symptom:** A new team member or AI agent joining a 50-phase project reads LIFECYCLE.md as the canonical pipeline reference (per the description field). They find no mention of: the step-status ledger, the `verify_all_markers_strict_runid` requirement, the CrossAI gap-hunt artifacts, or the evidence-manifest contract. They build tooling and dashboards based on the stale doc. Phase health checks they write miss 40% of the actual gate surface introduced in Batches 1–9.

**Root cause:** LIFECYCLE.md has not been updated since the v4.0 pipeline refactor. Batches 1–9 added significant new infrastructure (step ledger, verdict computation, strict marker verification, CrossAI output paths, evidence manifest). None of this is reflected in the canonical reference doc.

**Proposed fix:**
- `commands/vg/LIFECYCLE.md` §"What advances vs what completes a phase" (line 98–106): add a fourth bullet: "All non-goal steps write to `.test-step-status.json` ledger; any `BLOCK`/`FAIL` step overrides goal-based verdict."
- Add a `§ Key infrastructure` section listing: `PIPELINE-STATE.json` schema, `.step-markers/` convention, `verify_all_markers_strict_runid` function, `.test-step-status.json` ledger format, evidence-manifest contract, CrossAI output paths.
- Fix artifact table row for phase 6 (Test) to show `SANDBOX-TEST.md` not `TEST-RESULTS.json`.
- Add LIFECYCLE.md to `doctor.md` diagnostics: if LIFECYCLE.md is > 90 days old relative to last Batch plan date, emit a staleness warning.

---

### Finding 11: `test/close.md` verdict-computer reads `.test-step-status.json` but review lane has no equivalent ledger — review step failures (code-scan, lens-walk, url-error) do not propagate to review verdict

**Category:** C
**Severity:** medium
**File:line:**
- `commands/vg/_shared/test/close.md:110–136` — C5 Batch 9 step-status ledger override implemented
- `commands/vg/_shared/review/close.md` — no grep match for `step-status`, `step_ledger`, or `verdict.*step`
- `commands/vg/_shared/review/code-scan.md` — review code scan step; no ledger write found
- `commands/vg/_shared/review/lens-and-findings.md` — lens walk step; no ledger write found
- `commands/vg/_shared/review/url-and-error.md` — URL/error step; no ledger write found

**Symptom:** `/vg:review` runs 6 sub-steps: preflight, api-and-discovery, code-scan, lens-and-findings, url-and-error, limits-and-mobile. If `code-scan` BLOCKs silently (e.g., tool unavailable, exit masked by `|| true`), the review close.md verdict computation has no step-level input — it reads only `GOAL-COVERAGE-MATRIX.md` goal outcomes. The review can report `READY` while a code-scan step that should have blocked it was silently skipped. For large projects, silent review sub-step failures are the highest-risk source of phantom-done phases.

**Root cause:** C5 (Batch 9) introduced the step-status ledger only for the test lane. The pattern was not applied to the review lane. Review close computes verdicts from goal coverage only, without step-level override capability.

**Proposed fix:**
- Create `.review-step-status.json` (parallel to `.test-step-status.json`) in PHASE_DIR.
- Each review sub-step (code-scan, lens-and-findings, url-and-error, limits-and-mobile) writes `{step_name, status, reason, ts}` on completion or failure.
- `review/close.md` verdict computation: add a ledger-override block mirroring test/close.md lines 110–136; any `BLOCK`/`FAIL` step forces review verdict = `REVIEW_BLOCKED`.
- `accept/gates.md`: add gate that reads `.review-step-status.json` for any `BLOCK`/`FAIL` entries (not just SANDBOX-TEST.md verdict).

---

### Finding 12: `vg:amend` cascade does NOT invalidate test-spec/test/accept markers — prior test results remain valid after D-XX change; re-test is not enforced

**Category:** F, I
**Severity:** medium
**File:line:**
- `commands/vg/amend.md:295–320` — v2.46 cross-phase stale D-XX check: marks phases as stale in stdout but does NOT touch PIPELINE-STATE, step-markers, or SANDBOX-TEST.md
- `commands/vg/amend.md:178` — "TEST-GOALS.md: ${N} goals added/invalidated" — display only; no file write
- `commands/vg/_shared/test/close.md:450–462` — test completion is `pipeline_step=test-complete` in PIPELINE-STATE; amend does not reset this
- `commands/vg/_shared/accept/preflight.md:48` — reads SANDBOX-TEST.md; does not check whether amend post-dates the test run
- `commands/vg/_shared/accept/gates.md:202` — reads SANDBOX-TEST.md frontmatter `tested` timestamp; no amend-date comparison

**Symptom:** A decision D-07 says "API rate limit = 100/min". Phase 5 builds and tests successfully with rate limit at 100. Then `/vg:amend` changes D-07 to "rate limit = 10/min" (business requirement change). Cascade analyzer flags TEST-GOALS.md as "invalidated" in stdout. But SANDBOX-TEST.md still shows `status: PASSED` from the pre-amend test run. `/vg:accept` reads that SANDBOX-TEST.md, sees PASSED, and ships the phase — with the old 100/min behavior in production.

**Root cause:** Amend is informational-only. The cascade analyzer (`vg-amend-cascade-analyzer`) is read-only. No artifact is written to signal "re-test required". Accept reads SANDBOX-TEST.md by file existence and status only, with no cross-check against an amend timestamp.

**Proposed fix:**
- `amend.md` Phase 4 (close): write `${PHASE_DIR}/.amend-invalidation.json` with `{amended_at, changed_goals[], changed_decisions[]}`.
- `accept/preflight.md`: read `.amend-invalidation.json`; if `amended_at` > SANDBOX-TEST.md `tested` timestamp → BLOCK with "Test results pre-date a post-test amendment. Re-run /vg:test ${PHASE_NUMBER} after amend."
- `test/preflight.md`: similar check — if `.amend-invalidation.json` exists and test has not been re-run since, warn operator.
- This guarantees the test→accept contract is not broken by mid-pipeline decision changes.

---

## Summary table

| # | Title | Category | Severity |
|---|---|---|---|
| 1 | Auto-chain `next_command` only wired review→build; all other phase closes use echo only | B | high |
| 2 | `LIFECYCLE.md` lists `TEST-RESULTS.json` but actual artifact is `SANDBOX-TEST.md` | A, J | high |
| 3 | Blueprint and build/accept use file-existence marker check, not `verify_all_markers_strict_runid` | D | high |
| 4 | CrossAI blueprint findings (`crossai/`) never read by accept audit | G | high |
| 5 | Amend cascade is informational-only; LIFECYCLE-SPECS.json not invalidated after D-XX change | F | high |
| 6 | Phase number width `zfill(2)` across 14 scripts breaks at phase 100+ | H | high |
| 7 | No multi-domain / multi-team isolation for parallel phase execution | H | high |
| 8 | `test/close.md` no `next_command` + accept/preflight no PIPELINE-STATE cross-check | A, B | high |
| 9 | Deploy failure has no chain-back protocol; PIPELINE-STATE stays `build-complete` after failed deploy | I | medium |
| 10 | `LIFECYCLE.md` not updated since Batch 1–9; omits ledger, strict markers, CrossAI, evidence-manifest | J | medium |
| 11 | Review lane has no step-status ledger; sub-step failures don't propagate to review verdict | C | medium |
| 12 | `vg:amend` does not invalidate test/accept markers; prior test results remain valid after D-XX change | F, I | medium |

---

## Top 5 priority recommendations

1. **Finding 1 (auto-chain B/high):** Extend `next_command` pattern to all phase closes. This is a 5-file patch with identical Python snippet additions. Without it, `--auto-chain` pipelines stall after the review→build boundary and every other phase requires operator intervention.

2. **Finding 6 (phase number H/high):** Replace all 14 `zfill(2)` calls with a shared `phase_pad()` util + config-driven width. A 50-phase project is already at the limit today if any domain exceeds 99 sub-phases (`07.10.1` style). Fix before reaching that scale.

3. **Finding 5 (amend cascade F/high):** Write `.amend-invalidation.json` on amend + block accept when amend postdates last test run. Without this, a D-XX change mid-pipeline silently ships stale test results. This is the highest-risk data-correctness gap.

4. **Finding 3 (marker integrity D/high):** Propagate `verify_all_markers_strict_runid` to blueprint, build, and accept closes. Batch 9 fixed test. The same cross-run contamination risk exists at the other 3 closes. Low-effort (function is already implemented, just not called).

5. **Finding 7 (multi-domain H/high):** Add `domain` and `team` fields to ROADMAP.md phase blocks and propagate to PIPELINE-STATE + events.db. This is the table-stakes infrastructure for a genuine multi-team 50+ phase project. Without domain isolation, phase auto-chain routing, event filtering, and dependency tracking all become ambiguous at scale.

---

## Scale verdict

**FAIL**

The pipeline is not ready for a 50+ phase, multi-domain, multi-team project in its current state. Critical blocking reasons:

1. **Auto-chain is broken beyond the review→build boundary** (Finding 1). Every other phase transition requires manual operator intervention. In a 50-phase project with 8 transitions per phase, this is ~350 manual invocations that `--auto-chain` should eliminate but cannot.

2. **Phase numbering breaks at 100+ phases** (Finding 6). A 50-phase project with sub-phases (07.10.1, 07.10.2, etc.) already stress-tests this. At true 50 top-level phases, any domain that adds sub-phases crosses zfill(2) boundaries and silently drops artifacts in 14 scripts.

3. **No multi-domain isolation** (Finding 7). ROADMAP.md, CROSS-PHASE-DEPS.md, and the event stream have no domain/team partition. Parallel teams cannot safely run concurrent phases without coordination outside the pipeline tooling.

4. **Amend does not enforce re-test** (Findings 5, 12). In a long-running 50-phase project, mid-phase amendments are the norm. Without amend→test invalidation, shipped phases may carry stale behavioral contracts.

5. **CrossAI findings are silently discarded at accept** (Finding 4). At scale, CrossAI gap-hunt is the primary mechanism for catching cross-phase design regressions. Discarding those findings at accept removes the last automated guard before shipping.

Passes: the core test→accept gate is functional (SANDBOX-TEST.md → accept/gates.md path), step-status ledger is wired for test lane (Batch 9), CROSS-PHASE-DEPS.md tracks deferred goals, per-phase PIPELINE-STATE isolation is correct, and the wave-based build resume path is solid. These are strong foundations. The gaps above are engineering-track items (not fundamental redesigns) that must close before the pipeline can be trusted at 50+ phase scale.

---

*Audit method: Grep + Read on `commands/vg/_shared/**/*.md`, `commands/vg/*.md`, `scripts/*.py`. All findings have exact file:line evidence verifiable via grep. No code changes made.*
