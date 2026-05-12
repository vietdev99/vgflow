# Pipeline flow audit — review / test-spec / test (2026-05-13)

> **Trigger:** user reported test execution lost browser visibility post-v4.0 (headed/headless gap). Codex consult attempted but `gpt-5.5` model output empty (PONG smoke pass, 5KB prompt fail). Audit run manually via Grep/Read on canonical sources. Goal: enumerate same-class gaps (visibility / silence / correctness / drift / failure-path / config-skew / provenance / skip-holes) across 3 lanes.

**Status:** Audit only. NOT planned for execution yet. Each gap tagged with batch fit for the v5.0 plan (`docs/plans/2026-05-13-lifecycle-specs-redesign-plan.md`).

---

## Gap H1: Trace/video preservation in test/close.md is dead code

**Lane:** test
**Severity:** HIGH
**File:line:** `commands/vg/_shared/test/close.md:363-388`
**Symptom:** Plan Batch 5 will configure Playwright to retain trace/video/screenshot on failure. But `test/close.md` cleanup runs **before** that conditional and deletes the dirs containing them.
**Root cause:**
- Line 363 unconditionally `find . -type d -name "test-results" -exec rm -rf` (also `playwright-report`, `.playwright-mcp`).
- Line 382 then attempts `if VERDICT != PASSED → keep videos/traces`. But the directories holding `*.webm` / `trace.zip` are **already deleted** by step 1.
- Step 1 is unconditional, step 5 is conditional. Order is wrong.
**Proposed fix:** Move the FAILURE-branch preservation BEFORE step 1; or change step 1 to skip `test-results/` when VERDICT == FAILED; or move trace/video to a non-`test-results` path before cleanup.
**Batch fit:** **Batch 5** (must co-ship with headed config — otherwise headed work is wasted on the FAIL path)

---

## Gap H2: FE-BE drift advisory always silent — exit code masked by `|| true`

**Lane:** review
**Severity:** HIGH
**File:line:** `commands/vg/_shared/review/preflight.md:547-559`
**Symptom:** v4.1 wired `verify-fe-be-call-graph.py` as discovery-only advisory. Designed to emit WARN + `review.fe_be_drift_warn` event when FE calls reference BE endpoints that don't exist. In practice it **never fires**.
**Root cause:**
```bash
"${PYTHON_BIN:-python3}" "$FE_BE_VAL" \
  ... > ".../fe-be-call-graph-advisory.diag" 2>&1 || true   # line 547
FE_BE_RC=$?                                                    # line 548
if [ "$FE_BE_RC" -ne 0 ]; then                                # line 549 — dead
```
`cmd || true` always returns 0. `$?` captured next line = 0. The `if [ "$FE_BE_RC" -ne 0 ]` block (echo WARN, emit event) is dead.
**Proposed fix:** Remove the `|| true`, or capture `$?` from a subshell BEFORE the `||`:
```bash
"${PYTHON_BIN:-python3}" "$FE_BE_VAL" ... > out 2>&1
FE_BE_RC=$?
```
**Batch fit:** **New Batch 6** (review observability bug — independent fix)

---

## Gap H3: Validator output redirected to `.tmp/` — silent success/failure detail

**Lane:** test (via review verdict path)
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/fix-loop-and-verdict.md:1003-1019` + ~9 validator calls below
**Symptom:** 9 validators (verify-interface-standards, verify-goal-security, verify-goal-perf, verify-security-baseline, verify-haiku-scan-completeness, verify-runtime-map-coverage, verify-crud-runs-coverage, verify-error-message-runtime, verify-route-inventory) all run with `> "$VAL_OUT" 2>&1`. Output goes to `${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic-input.txt`. User sees nothing unless BLOCK happens.
**Root cause:** `.tmp/` not in evidence-manifest, not committed, gets nuked in close.md cleanup. Diagnostic content invisible mid-flow even on PASS.
**Proposed fix:**
- Emit a `.tmp/${VALIDATOR}-result.json` summary alongside (verdict + evidence count + 3 sample findings).
- Tail-print last 5 lines on PASS so user knows what was checked.
- Add evidence-manifest entry for each `.diag` so provenance survives.
**Batch fit:** **Batch 3** (G13 validator semantic checks — same area)

---

## Gap H4: Idempotency check in 5b_runtime_contract_verify pollutes target

**Lane:** test
**Severity:** CRITICAL
**File:line:** `commands/vg/_shared/test/runtime.md:77-104`
**Symptom:** Auto-ON when `critical_domains=billing,auth,payout,payment,transaction` (default!). Step double-submits POST/PUT/DELETE to real `${BASE_URL}` with real `Bearer ${AUTH_TOKEN}`. When two 201s create distinct IDs, logs IDEMPOTENCY_FAILS. **Never cleans up the duplicate records.** Real billing/payment rows committed in target env.
**Root cause:** Lines 82-89 fire `curl -sf -X $METHOD` twice. Lines 90-96 detect dup IDs but no rollback / DELETE. Defaults include `billing` + `payment` + `payout`. Auto-on with $BASE_URL set means any phase with billing endpoint pollutes target.
**Proposed fix:**
- Auto-OFF by default; opt-in via `config.test.idempotency.enabled: true`.
- When enabled, require `ENVIRONMENT != production` HARD-GATE.
- Track created IDs in `${VG_TMP}/idempotency-cleanup.json`; emit DELETE for each post-check.
- Emit `test.idempotency_polluted` event when cleanup DELETE returns non-2xx.
**Batch fit:** **New Batch 7** (safety/security — must ship before next dogfood)

---

## Gap H5: vg-test-codegen subagent transcript not in evidence-manifest

**Lane:** test-spec
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/codegen/overview.md:27, 136` (subagent spawn) + close path
**Symptom:** Spawns `Agent(subagent_type="vg-test-codegen", prompt=<delegation.md>)`. Subagent generates `${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts`. When generated spec is wrong (e.g. references nonexistent selector), there's no way to inspect WHAT the subagent received as input and WHY it produced that selector — no transcript path in manifest.
**Root cause:** Output `.spec.ts` files are referenced as deliverables but the subagent's input prompt + reasoning are not preserved. `vg-narrate-spawn.sh` writes a narration line but full prompt context is gone after the subagent returns.
**Proposed fix:** Before spawn, write the rendered prompt to `${PHASE_DIR}/.codegen/{goal}-prompt.txt`. After return, write the subagent's structured output to `${PHASE_DIR}/.codegen/{goal}-output.json`. Emit evidence-manifest entries for both. Allows post-mortem debugging of "why did codegen produce wrong selector".
**Batch fit:** **Batch 5** (observability) or **Batch 3** (semantic provenance)

---

## Gap H6: emit-evidence-manifest uses --quiet — partial failures swallowed

**Lane:** review
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/fix-loop-and-verdict.md:969, 976`
**Symptom:** Two evidence-manifest emit calls for RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md (issue #175 fix). Both use `--quiet || true`. If RUNTIME-MAP emit succeeds but COVERAGE-MATRIX emit fails (or vice versa), run-complete will block with "manifest missing for X" but user has no idea WHICH emit failed during review.
**Root cause:** `--quiet || true` swallows both stdout AND non-zero exit. Combined with shell `||`, error becomes invisible.
**Proposed fix:** Drop `--quiet`. Capture exit code per call. On non-zero, echo `⚠ manifest emit failed for ${PATH}` + emit `review.manifest_emit_failed` event. Still don't hard-fail (advisory), but make visible.
**Batch fit:** **New Batch 6** (review observability — same as H2)

---

## Gap H7: HARD-GATE skip without symmetric audit downstream

**Lane:** cross-lane (test ↔ accept)
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/regression-security.md:69, 233, 380, 555` + test/runtime.md:24, 128, 164, 264
**Symptom:** 8+ HARD-GATE skip directives like `mobile-* MUST skip ... use 5f_mobile_security_audit instead` and `web-frontend-only + mobile-* MUST skip this step`. Pipeline relies on the SKIPPED step having a SUBSTITUTE step or being intentionally NA. No audit that downstream `/vg:accept` checks the substitute ran.
**Root cause:** Skip directives are local to each step file. No central skip-manifest. `accept/audit.md` may or may not verify the substitute path.
**Proposed fix:** Each HARD-GATE skip emits a `test.step_skipped_by_profile` event with `{step, profile, substitute_step}`. `/vg:accept` reads events, verifies each skipped step has substitute event present. Block accept if substitute missing.
**Batch fit:** **New Batch 8** (cross-lane skip integrity — needs research)

---

## Gap H8: codex-spawn fix-agent failure → stderr only, no event

**Lane:** test
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/fix-loop-and-verdict.md:184-194`
**Symptom:** When `VG_RUNTIME=codex`, fix-loop iteration shells out to `codex-spawn.sh --tier executor`. On failure: `echo "⚠ codex-spawn fix-agent failed ..." >&2`. Pure stderr warning, no event, no marker, no manifest entry. In CI / `--auto-chain`, this gets lost.
**Root cause:** Pre-v4.0 fix-loop was Claude-only (Agent tool). v4.0 added Codex path but error surfacing wasn't ported.
**Proposed fix:** Emit `test.codex_fix_failed` event with `{err_id, attempt, exit_code}`. Append entry to REVIEW-FEEDBACK.md OR a dedicated `${PHASE_DIR}/CODEX-FIX-FAILURES.json`.
**Batch fit:** **New Batch 6** (observability — same family as H2/H6)

---

## Gap H9: playwright-config terminology collision

**Lane:** cross-lane
**Severity:** LOW
**File:line:** `commands/vg/_shared/test/fix-loop-and-verdict.md:311` (`--config .claude/vg.config.md`) vs `test/regression-security.md:42-43` (`playwright.config.generated.ts`)
**Symptom:** Two different "config" concepts use the same flag/wording. `vg.config.md` is harness config. `playwright.config.generated.ts` is test runner config. New contributor or doc reader will confuse them.
**Root cause:** Pre-v4.0 only had vg.config. Batch 5 introduces playwright config. Documentation hasn't disambiguated.
**Proposed fix:** Rename inline references to `--vg-config` flag where it's the harness config. Keep `--config` for Playwright. Add a one-liner in test/runtime.md explaining the two.
**Batch fit:** **Batch 5** (ships with playwright config introduction)

---

## Gap H10: Review subagent (vg-reflector) output not surfaced

**Lane:** test (close)
**Severity:** LOW
**File:line:** `commands/vg/_shared/test/close.md:211-272`
**Symptom:** End-of-test reflection spawns `vg-reflector` (isolated Haiku general-purpose subagent). Output is reflection/lesson summary. Where it lands: ambiguous. Line 272 says "Read .claude/skills/vg-reflector/SKILL.md and follow workflow exactly" — but the spawn doesn't capture stdout into an artifact tied to the phase.
**Root cause:** Reflection meant to be transient. But if user wants to see what AI reflected on, no easy path.
**Proposed fix:** Reflector subagent writes `${PHASE_DIR}/REFLECTION.md`. Add to evidence-manifest. Optional `--skip-reflection` flag.
**Batch fit:** **Batch 4** (cleanup quality — nice-to-have)

---

## Gap H11: 5b runtime contract verify uses `> "$VAL_OUT" 2>&1` for curl results

**Lane:** test
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/runtime.md:46-47, 82-104`
**Symptom:** Curl probing endpoints prints `Contract verify: ${TOTAL} endpoints from vg-load index` — single counter line. Per-endpoint check results (status code, response keys diff, mismatch detail) are NOT surfaced to stdout. Only aggregate `5b Runtime Contract Verify: ... Result: {PASS|BLOCK}` displays.
**Root cause:** Per-endpoint logic exists inline but suppresses individual results. User can't see WHICH endpoint failed contract during the run.
**Proposed fix:** Per-endpoint line like `  POST /api/projects → status=201 ✓ fields=8/8 ✓` and on mismatch `  GET /api/users → status=200 ✓ fields=7/9 ✗ missing[email, role]`. Persist full list to `${PHASE_DIR}/.contract-verify-detail.json` + evidence-manifest.
**Batch fit:** **Batch 5** (observability theme) or **Batch 3** (semantic detail)

---

## Gap H12: CrossAI prompt/runs path drift between review & test lanes

**Lane:** cross-lane
**Severity:** LOW
**File:line:** `commands/vg/_shared/review/preflight.md:646` describes drop scan results into `runs/{tool}/`. No corresponding consumer in test lane.
**Symptom:** If user runs codex/gemini CLI externally and drops results into `.vg/phases/{phase}/review/runs/{tool}/`, the test-spec/test lanes don't import or reference them. Output stranded.
**Root cause:** Pattern designed for review only; not extended.
**Proposed fix:** test-spec preflight scans `.vg/phases/{phase}/review/runs/` and includes any CrossAI findings as additional context for codegen subagent.
**Batch fit:** **New Batch 8** (cross-lane integration)

---

## Summary

| # | Title | Lane | Severity | Batch fit |
|---|---|---|---|---|
| H1 | Trace/video preservation dead code (close cleanup order) | test | HIGH | 5 (co-ship) |
| H2 | FE-BE drift advisory dead (RC masked by `\|\| true`) | review | HIGH | 6 (new) |
| H3 | Validator output silent in `.tmp/` | test | MEDIUM | 3 |
| H4 | Idempotency check pollutes target with real records | test | **CRITICAL** | 7 (new safety) |
| H5 | vg-test-codegen subagent transcript not in manifest | test-spec | MEDIUM | 5 or 3 |
| H6 | `--quiet` on manifest emit swallows partial failure | review | MEDIUM | 6 (new) |
| H7 | HARD-GATE skip without downstream substitute audit | cross-lane | MEDIUM | 8 (new) |
| H8 | codex-spawn fix-agent failure stderr-only | test | MEDIUM | 6 (new) |
| H9 | "config" terminology collision (vg.config vs playwright) | cross-lane | LOW | 5 |
| H10 | vg-reflector output not surfaced | test | LOW | 4 |
| H11 | 5b contract verify suppresses per-endpoint detail | test | MEDIUM | 5 or 3 |
| H12 | CrossAI runs/ path not consumed by test-spec | cross-lane | LOW | 8 (new) |

## Top 3 to fix next (priority order)

1. **H4 (idempotency pollution) — CRITICAL.** Real billing/payment records duplicated in target env on every test run with default config. Ship before any dogfood on production-like env. Trivial fix: auto-OFF by default + non-prod HARD-GATE + cleanup-DELETE pass.
2. **H1 (trace/video cleanup race).** Must co-ship with Batch 5. Otherwise Batch 5 work is wasted — headed config emits artifacts that get nuked before user can see them on FAIL.
3. **H2 (FE-BE drift advisory dead).** v4.1 shipped this as advisory but it never fires. Documented but invisible = false confidence in pipeline.

## Proposed new batches

| Batch | Theme | Gaps |
|---|---|---|
| **Batch 6** | Review observability bug fixes | H2, H6, H8 |
| **Batch 7** | Test safety (idempotency, target pollution) | H4 |
| **Batch 8** | Cross-lane integration | H7, H12 |

Original v5.0 batches (2/3/4/5) unchanged. H1/H5/H9/H11 absorbed into Batch 5 (co-ship with headed observability). H3 absorbed into Batch 3 (G13 validator semantics). H10 absorbed into Batch 4 (cleanup quality).

---

**Audit method:** Grep + Read on `commands/vg/_shared/{review,test}/*.md` + `commands/vg/_shared/test/{codegen,goal-verification}/*.md`. No assumptions — every gap has explicit file:line evidence verifiable via `grep -n`.

**Codex consult (3rd attempt SUCCESS):** Earlier 2 attempts failed (empty output). Root cause: VGFlow's working `codex-spawn.sh` uses `--output-last-message FILE` + `--sandbox workspace-write`. Adding both flags + waiting ~12 min for `gpt-5.5` xhigh reasoning produced 11 distinct gaps below. Pattern: `codex exec --sandbox workspace-write --cd PATH --output-last-message FILE - < PROMPT`.

---

# Codex second-opinion findings (2026-05-13, 11 gaps)

> Independent audit by Codex `gpt-5.5` 9router xhigh reasoning. Different methodology than mine — Codex read deeper into TRUST_REVIEW path + marker schema + verdict computation. Confirmed in-source before accept.

## Gap C1: Deploy step marks complete with NO evidence

**Lane:** test
**Severity:** HIGH
**File:line:** `commands/vg/_shared/test/deploy.md:29, 51`
**Symptom:** `5a_deploy` step body is prose comments + unconditional marker write. User can see `{sha}`, `{health}`, `{services}` display contract but zero artifact proves deploy happened.
**Root cause:** No machine-readable deploy artifact required. Marker write is `touch ... .done` unconditional.
**Proposed fix:** Require `test-deploy-report.json` or `DEPLOY-STATE.json` with local/target SHA, restart result, health checks, service status + evidence-manifest binding. Block marker if missing.
**Batch fit:** **Batch 5** (observability)

## Gap C2: Smoke check (5c_smoke) marker without artifact

**Lane:** test
**Severity:** HIGH
**File:line:** `commands/vg/_shared/test/runtime.md:130, 153`
**Symptom:** 5c_smoke prose says "stratified sample 5 views, browser_snapshot, compare fingerprint" but step can be marked done with no run, no screenshot, no `{matches}/5` persistence. Same user-blind effect as headless but step may not execute at all.
**Root cause:** Display prose without artifact contract. Marker fires regardless.
**Proposed fix:** Step writes `smoke-check.json` with per-view sample + screenshot/log paths. Gate marker on schema validation + count.
**Batch fit:** **Batch 5**

## Gap C3: URL runtime validator checks param presence, not semantic correctness

**Lane:** review
**Severity:** HIGH
**File:line:** `commands/vg/_shared/review/url-and-error.md:177` + `scripts/validators/verify-url-state-runtime.py:412`
**Symptom:** Filter "passes" when `?status=pending` appears in URL even if table still shows wrong rows. Phase 2.8 prose REQUIRES `result_semantics` but validator only checks URL param exists post-interaction.
**Root cause:** Validator scope mismatch with documented intent.
**Proposed fix:** Validate `result_semantics.passed == true` + type-specific evidence (filter row-set, sort order, pagination window change, search result match). Missing semantic evidence = BLOCK.
**Batch fit:** **Batch 3** (G13 validator semantics family)

## Gap C4: review `READY` → test `PASSED` without replay (TRUST REVIEW)

**Lane:** cross-lane
**Severity:** **CRITICAL**
**File:line:** `commands/vg/_shared/review/matrix-intent.md:5` + `commands/vg/_shared/test/goal-verification/delegation.md:231-232`
**Symptom:** Goal becomes `TEST-PASSED` without actual test execution if review observed endpoint + selectors. Structural scan auto-promotes to behavioral success.
**Root cause:** Review `READY` = "endpoint observed + selectors resolved" (structural). `TRUST_REVIEW=true` mode (Step D point 4 in delegation.md) maps READY → PASSED by policy:
```
4. Skip READY goals:
   - Emit status: "PASSED", source: "trust-review — review 100% gate".
```
**Proposed fix:** Split verdict: `READY_STRUCTURAL` (current) vs `READY_BEHAVIORAL` (review persisted per-goal assertion evidence). TRUST REVIEW only auto-passes BEHAVIORAL; STRUCTURAL must replay in test.
**Batch fit:** **New Batch 9** (verdict integrity — critical correctness)

## Gap C5: Final VERDICT ignores contract/security/smoke/regression blockers

**Lane:** cross-lane
**Severity:** **CRITICAL**
**File:line:** `commands/vg/_shared/test/close.md:71` + `commands/vg/_shared/test/regression-security.md:98`
**Symptom:** Critical non-goal failures omitted from computed VERDICT + Next routing + SANDBOX-TEST.md status if goal result buckets look good. User misrouted to `/vg:accept` despite security/contract failures.
**Root cause:** Verdict script reads `goal-*-result.json` + priority buckets only. Step-level outcomes from deploy/runtime contract verify/smoke/regression/security/traceability/flow compliance NOT ingested.
**Proposed fix:** Introduce `.test-step-status.json` step-status ledger. Final verdict = max(goal coverage, hard-blocking step outcomes). Any BLOCK/FAIL on contract/security/traceability overrides goal-only PASS.
**Batch fit:** **New Batch 9** (verdict integrity)

## Gap C6: Goal-verifier subagent return shape-only check

**Lane:** test
**Severity:** HIGH
**File:line:** `commands/vg/_shared/test/goal-verification/overview.md:159, 183`
**Symptom:** Subagent returns non-empty `goals_verified[]` + `baseline_console_check_pass:bool` and harness rewrites GOAL-COVERAGE-MATRIX.md + emits telemetry even if goal IDs wrong, statuses invalid, evidence files non-existent.
**Root cause:** Post-spawn validation = array length + boolean presence. No reconciliation against vg-load index, no `evidence_ref` existence check.
**Proposed fix:** Strict schema validation — exact goal ID set match, status enum, screenshot/evidence path existence, baseline artifact existence, per-goal provenance trace.
**Batch fit:** **Batch 4** (cleanup quality)

## Gap C7: Codegen subagent return shape-only check

**Lane:** test-spec
**Severity:** HIGH
**File:line:** `commands/vg/_shared/test/codegen/overview.md:163, 183`
**Symptom:** One dummy spec + `bindings_satisfied: true` satisfies orchestration even if files missing on disk, READY goals silently dropped, no actual binding check ran.
**Root cause:** Validation = `spec_files.length > 0` + `bindings_satisfied` presence. No file-exists check, no binding header parse, no reconciliation vs review intent.
**Proposed fix:** Validate every returned file exists, parse headers for goal/rule bindings, reconcile READY/MANUAL/DEFERRED goals vs generated outputs, require persisted binding report artifact.
**Batch fit:** **Batch 4**

## Gap C8: Phase 2a proof reuse skips OTHER mandatory gates

**Lane:** review
**Severity:** HIGH
**File:line:** `commands/vg/_shared/review/api-and-discovery.md:29, 47, 81`
**Symptom:** Fresh `.contract-runtime-report.json` skips not just live API probe, but ALSO interface-standards validation + API-docs coverage. Review proceeds to browser discovery on stale docs/semantics.
**Root cause:** Proof shortcut exits Phase 2a early — one artifact gates multiple distinct subgates with different inputs.
**Proposed fix:** Split Phase 2a into proof domains. Contract probe reuses fresh proof. Interface standards + API-docs coverage each need their own fresh proof or live run.
**Batch fit:** **Batch 2** (high prio — fits review hardening)

## Gap C9: Terminal marker gate checks existence only, not run_id

**Lane:** cross-lane
**Severity:** **CRITICAL**
**File:line:** `commands/vg/_shared/lib/marker-schema.sh:4` (defines hardened schema) + `commands/vg/_shared/test/close.md:532` (checks existence only)
**Symptom:** Empty/stale `.done` files satisfy terminal marker gate. Forged or old marker makes step appear complete without current-run execution provenance.
**Root cause:** Harness defines marker schema `phase|step|git_sha|iso_ts|run_id` (marker-schema.sh:9) with `verify_marker()` strict check (line 106-165 with forgery detection line 165). But close gates only check file existence + many steps still use `touch ... .done` fallback + `mark-step ... || true`.
**Proposed fix:** Close gates call `verify_marker`/`verify_all_markers` strict mode + require run_id match active run. Stop accepting bare `touch` markers (or accept only as explicit `inconclusive` markers).
**Batch fit:** **New Batch 9** (verdict + marker integrity)

## Gap C10: `GAPS_FOUND` cleanup deletes the very traces needed (overlap with H1)

**Lane:** test
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/test/close.md:382-388`
**Symptom:** When verdict = `GAPS_FOUND`, videos + traces deleted even though unresolved issues remain. User gets less debug evidence precisely when needed.
**Root cause:** Cleanup treats `GAPS_FOUND` same as `PASSED` — line 383 condition `[ "$VERDICT" = "PASSED" ] || [ "$VERDICT" = "GAPS_FOUND" ]`.
**Proposed fix:** Keep failure artifacts for ANY verdict ≠ PASSED. Even for GAPS_FOUND retain traces for failed/blocked goals + print preserved paths into SANDBOX-TEST.md.
**Batch fit:** **Batch 5** (extends H1 fix — same cleanup block)

## Gap C11: URL runtime fragmented skip/waive knobs, no shared status

**Lane:** cross-lane
**Severity:** MEDIUM
**File:line:** `commands/vg/_shared/review/url-and-error.md:41, 110, 196` + `scripts/validators/verify-url-state-runtime.py:303`
**Symptom:** Same concept bypassed 3 different ways: declaration waiver (`--allow-no-url-sync`), runtime suppression (`--skip-runtime`), drift waiver (`--allow-runtime-drift`). Downstream lanes can't distinguish "passed" vs "not executed".
**Root cause:** Bypass semantics across multiple flags + WARN-only validator path. No canonical status artifact for consumers.
**Proposed fix:** Emit single `url-runtime-status.json` with explicit state enum: `passed | drift | skipped | unexecuted | waived`. Collapse to one canonical override path with structured debt metadata.
**Batch fit:** **Batch 2** (cross-lane integration)

---

## Combined gap inventory (Hn manual + Cn Codex = 23 total)

Codex's 3 CRITICAL findings are NEW — not in my manual audit:
- **C4** READY → PASSED without replay (verdict integrity)
- **C5** Final VERDICT ignores non-goal blockers (verdict integrity)
- **C9** Marker existence ≠ marker verification (provenance)

These 3 form basis of **proposed Batch 9 — verdict + marker integrity**, the most consequential correctness work.

## Updated Top 3 (revised after Codex)

1. **C4 + C5 + C9 (Batch 9 family)** — Verdict integrity. Without these, READY goals auto-pass + non-goal failures invisible + markers forgeable. Pipeline can report PASSED when reality is broken.
2. **H4** (idempotency target pollution) — still critical, ships before any production-like dogfood.
3. **C8 + H2** (Phase 2a proof split + FE-BE advisory dead) — review observability fixes.

## Updated batch summary

| Batch | Theme | Gaps |
|---|---|---|
| **2** (deferred) | + Phase 2a proof split + URL fragmented flags | G2, G14, C8, C11 |
| **3** | + URL semantic validation + verdict step-status | G8, G11, G13, G3, H3, C3 |
| **4** | + subagent shape-vs-semantic checks | G1, G4, G5, G6, H10, C6, C7 |
| **5** | + GAPS_FOUND trace preservation | (existing 5.1-5.6), H1, H5, H9, H11, C1, C2, C10 |
| **6** (new) | review observability bugs | H2, H6, H8 |
| **7** (new) | test safety / idempotency cleanup | H4 |
| **8** (new) | cross-lane integration | H7, H12 |
| **9** (new) | **verdict + marker integrity (CRITICAL)** | **C4, C5, C9** |

Batches 6/7/8/9 are new vs original v5.0 design. Batch 9 is highest priority (3 CRITICAL findings).
