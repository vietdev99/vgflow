---
name: vg:_shared:eng-principles
description: Engineering principles cross-cut reference cited by VG skills. SRE / production-grade concepts (Hyrum's Law, Beyonce Rule, Shift Left, Test Pyramid, Trunk-Based Development) baked into VG gate design. Skills cite these instead of re-deriving.
---

# Engineering Principles — VG Cross-Cut Reference

VG's gate / contract / artifact design encodes a small set of well-established engineering principles. Skills cite this doc instead of re-deriving the rationale each time. Inspired by [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) (38k stars) which baked similar references into its 22 lifecycle skills.

---

## 1. Hyrum's Law

> "With a sufficient number of users of an API, it does not matter what you promise in the contract: all observable behaviors of your system will be depended on by somebody."  — Hyrum Wright

**VG application:**
- `commands/vg/_shared/build/in-scope-fix-loop-delegation.md` ripple analysis treats every API/UI/state change as observable. Even "internal" endpoints get contract checks.
- `/vg:review` Phase 3 fix loop assumes any prior shape leak is depended on; deprecation requires backwards-compat shim.
- `_shared/rationalization-tables.md` C-row "Ripple analysis không cần, change isolated" rebuts directly.

**Implication for AI:** "Internal-only" is a promise about intent, not behavior. Treat every change as potentially observed.

---

## 2. Beyonce Rule

> "If you liked it, you should have put a test on it."  — Google SRE

**VG application:**
- Every `/vg:test` goal must have a test. `must_emit_telemetry: test.goal_verified` enforces.
- Bug fix without `repro_test` field → `/vg:debug` step `2_hypothesize_and_fix` BLOCKs.
- Coverage ratchet: monotonic increase only (per-phase TEST-GOALS.md count check).

**Implication for AI:** No test = no proof = not done. "Manual verification" doesn't persist.

---

## 3. Shift Left

> "Move quality activities (security, performance, accessibility) earlier in the lifecycle. Bugs caught at design cost 1×; production cost 100×." — Capers Jones / Microsoft SDL

**VG application:**
- `/vg:specs` (Phase 1) gathers requirements before any code.
- `/vg:scope` 5 rounds catch ambiguity before `/vg:blueprint`.
- `/vg:blueprint` validates API contracts before `/vg:build` begins.
- `/vg:review` security lens runs BEFORE `/vg:test` deploy step (catches OWASP issues pre-deploy).
- Pre-test gate (`_shared/build/pre-test-gate.md`) blocks `/vg:test` if `/vg:review` had unresolved high-severity findings.

**Implication for AI:** Every step caught at the earlier phase saves 10-100× cost. Don't defer security/perf/a11y to "post-launch".

---

## 4. Test Pyramid

> "Many unit tests, fewer integration, very few E2E. Inverted pyramid (E2E-heavy) is fragile and slow."  — Mike Cohn / Martin Fowler

**Distribution targets:**

| Layer | Share | Speed | VG mapping |
|---|---|---|---|
| Unit | ~70-80% | <100ms each | `/vg:test` codegen for pure-function goals |
| Integration | ~15-25% | <2s each | `/vg:test` API contract probes (`scripts/review-api-contract-probe.py`) |
| E2E | ~5-10% | <60s each | `/vg:test` Playwright runtime via `flow-runner` skill |

**VG application:**
- `_shared/test/codegen/overview.md` enforces layer ratios. E2E-heavy plans get pushed back to integration.
- Cost: E2E retry budget 3× (slower) vs unit retry budget 0× (deterministic).

**Implication for AI:** When writing tests, default to unit. Reach for integration only when boundaries matter. E2E only for critical user flows.

---

## 5. Trunk-Based Development

> "Short-lived branches (<2 days), small frequent integrations, master always green."  — Google / Facebook / Netflix

**VG application:**
- `commands/vg/build.md` waves commit per task (atomic, fast trunk integrations).
- `/vg:accept` step 0 verifies branch divergence ≤ 200 commits before accepting (catches stale branches).
- Phase artifacts (SPECS, CONTEXT, PLAN) committed with code — no out-of-band approval queues.

**Implication for AI:** Don't accumulate 50-commit feature branches. Commit per atomic step (per `_shared/build/waves-overview.md`).

---

## 6. Fail-Closed by Default

> "When safety logic errors, refuse the action. When safety logic succeeds, allow the action. Never inverse."  — Standard security principle

**VG application:**
- Every gate: missing marker / failed schema / unparseable artifact → BLOCK (not WARN).
- `_shared/rationalization-guard.md` ESCALATE verdict = BLOCK; never demote to WARN.
- `vg-orchestrator run-complete` requires positive evidence, not absence of complaint.

**Implication for AI:** When in doubt, block + ask. Don't proceed on "should work".

---

## 7. Provenance Binding

> "Every artifact must trace to the run that produced it. Reused-from-prior-run = state shortcut = unaudited."

**VG application:**
- `runtime_contract.must_be_created_in_run: true` enforces fresh creation per `/vg:review` run.
- `_verify_artifact_run_binding` checks `creator_run_id` matches current run.
- `merged_event` payload includes `phase_context` for deploy state.

**Implication for AI:** Don't reuse stale RUNTIME-MAP.json from prior run. Regenerate per fresh contract execution.

---

## 8. Idempotency

> "Re-running the same operation produces the same result. F(F(x)) = F(x)."

**VG application:**
- `vg-migrate-v3.sh` idempotent — re-run = no-op when already at target.
- `vg_install` (dispatcher) writes marker, then re-runs detect existing marker.
- `_shared/migrate/generate-gitignore-v3.py` skips append when marker present.
- DB writes use `INSERT ... ON CONFLICT DO NOTHING` for hash-chained events.

**Implication for AI:** When writing migration/install/setup scripts, ALWAYS test re-run. If second run breaks, ship is broken.

---

## How skills cite this doc

Skills reference these principles without re-explaining. Example pattern in skill body:

```markdown
**Why this gate exists:** Hyrum's Law — every observable behavior is depended on,
even when documented as "internal". See `_shared/eng-principles.md` §1.
```

When adding a new gate or contract requirement, cite the principle. Reviewer knows the rationale lineage in 5 seconds.

---

## Cross-references

- Runtime guard: `_shared/rationalization-guard.md`
- Static rationalizations: `_shared/rationalization-tables.md`
- Skill discovery: `_shared/discovery-flowchart.md`
- Pipeline taxonomy: `commands/vg/LIFECYCLE.md`
