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
**Codex consult:** attempted twice with `gpt-5.5` model on 9router provider. Both runs produced empty assistant output (PONG smoke worked, 5KB audit prompt failed silently). Workaround: manual audit. Future: try `gpt-5-codex` model + explicit `--reasoning-summary none` if codex audit needed.
