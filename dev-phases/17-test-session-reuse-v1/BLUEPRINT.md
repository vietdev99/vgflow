# Phase 17 — Test Session Reuse — BLUEPRINT v1

**Lock date:** 2026-04-27
**Total tasks:** 10 across 5 waves
**Estimated effort:** 8–10h (revised after audit: helper-only file extension + small validator)
**Source:** `SPECS.md` (this folder)
**Pattern:** atomic commit per task with message `feat(phase-17-T<wave>.<task>): <subject>`.

---

## Wave plan

| Wave | Theme | Tasks | Effort | Parallelism | Depends on |
|------|-------|-------|--------|-------------|------------|
| 0 | Foundation: validator slot + i18n keys + audit fixtures | T-0.1, T-0.2 | 1.5h | parallel | — |
| 1 | Helper template extension (loginOnce + useAuth + types) | T-1.1, T-1.2 | 2.5h | sequential | W0 |
| 2 | Helper smoke fixtures + tests | T-2.1 | 1h | — | W1 |
| 3 | Update 10 P15 D-16 templates + validator scan | T-3.1, T-3.2 | 1.5h | parallel | W1 |
| 4 | Global-setup + vg.config + init.md wiring | T-4.1, T-4.2, T-4.3 | 2h | parallel | W1 |
| 5 | Acceptance + extend Phase 15 acceptance suite + integration smoke | T-5.1 | 1.5h | — | W3, W4 |

**Critical path:** W0 → W1 → (W2 || W3 || W4) → W5
**Wall-clock min:** 1.5h + 2.5h + max(1, 1.5, 2) = 6h with full parallelism
**Wall-clock max (sequential):** 8.5h

---

## Wave 0 — Foundation (1.5h)

### T-0.1 — Register validator slot in registry.yaml (D-06)
- **File:** `scripts/validators/registry.yaml`
- **Action:** Append entry for `test-session-reuse` (severity: warn, domain: test, added_in: v2.11.0-phase-17)
- **Validation:** YAML parses cleanly; `/vg:validators list` shows new entry.
- **Commit:** `feat(phase-17-T0.1): register test-session-reuse validator slot`
- **Effort:** 0.5h

### T-0.2 — Audit fixtures + tests scaffold (Wave 2 prereq)
- **Files:**
  - `fixtures/phase17/specs/legacy-loginas.spec.ts.fixture` — sample spec using old pattern
  - `fixtures/phase17/specs/modern-useauth.spec.ts.fixture` — sample spec using new pattern
- **Action:** Create both fixtures (copy minimal Phase 15 D-16 spec shape; one with old `beforeEach loginAs`, one with `test.use(useAuth)`).
- **Validation:** Files exist; both syntactically valid TypeScript when copied to project.
- **Commit:** `test(phase-17-T0.2): fixtures for legacy + modern test session patterns`
- **Effort:** 1h

---

## Wave 1 — Helper extension (2.5h)

### T-1.1 — Add loginOnce + useAuth + types to interactive-helpers.template.ts (D-01 + D-02)
- **File:** `commands/vg/_shared/templates/interactive-helpers.template.ts`
- **Action:** Append new section "AUTH SESSION REUSE — Phase 17 D-01/D-02" with:
  - `LoginOnceOptions` interface (`storagePath?`, `strategy?`)
  - `loginOnce(role, opts?): Promise<string>` — full implementation per SPECS D-02
  - `useAuth(role): { storageState: string }` — sync fixture override
  - YAML config parser helper (lightweight inline; ~30 LOC)
  - File hashing for `config_hash` field (Node `crypto.createHash`)
- **Constraints:**
  - Total file LOC ≤ 500 (was 295; +200 budget).
  - Existing 7 helpers UNCHANGED (diff regression check).
  - TypeScript strict-mode clean.
- **Validation:**
  - `npx tsc --noEmit` against the file (use stub `@playwright/test` types).
  - Diff line 1-295 unchanged from pre-commit version.
- **Commit:** `feat(phase-17-T1.1): interactive-helpers — loginOnce + useAuth (D-01/02)`
- **Effort:** 2h

### T-1.2 — Storage state TTL + config_hash logic
- **File:** Same file, helper functions inside `loginOnce`.
- **Action:** Implement:
  - `_readMetaJson(path)` → returns `{config_hash, created_at, ttl_hours}` or null
  - `_isFresh(meta, configHash, ttlHours)` → bool
  - `_writeMetaJson(path, meta)` → writes sidecar
- **Validation:** Unit-tested in T-2.1.
- **Commit:** `feat(phase-17-T1.2): storage state TTL + config_hash invalidation`
- **Effort:** 0.5h

---

## Wave 2 — Helper smoke tests (1h)

### T-2.1 — Pytest test_phase17_helpers.py
- **File:** `scripts/tests/root_verifiers/test_phase17_helpers.py`
- **Action:** 6 tests via Node subprocess invoking helper exports:
  1. `loginOnce` creates `.auth/<role>.json` + `.meta.json`
  2. Re-call within TTL → no new login (verify by absence of network call attempt)
  3. Modify config password → call → regenerate (config_hash mismatch path)
  4. Stale TTL (file mtime back-dated) → regenerate
  5. `useAuth(role)` returns `{ storageState: "<full path>" }`
  6. Strategy `auto`: API path tried first, falls back to UI on 404
- **Approach:** mock fetch via `--no-network` env or skip-if-no-baseurl pattern.
- **Validation:** All 6 pass on Windows + Linux.
- **Commit:** `test(phase-17-T2.1): helper smoke — loginOnce TTL + config_hash + strategy`
- **Effort:** 1h

---

## Wave 3 — Update P15 templates + validator (1.5h)

### T-3.1 — Update 10 P15 D-16 templates: useAuth replaces beforeEach loginAs (D-03)
- **Files (10):**
  - `commands/vg/_shared/templates/filter-{coverage,stress,state-integrity,edge}.test.tmpl`
  - `commands/vg/_shared/templates/pagination-{navigation,url-sync,envelope,display,stress,edge}.test.tmpl`
- **Action per file:**
  - Replace import line: `import { loginAs } from '../helpers';` → `import { useAuth } from '../helpers/interactive';`
  - Add `test.use(useAuth(ROLE));` line right after `test.describe(...)` opening.
  - Remove `await loginAs(page, ROLE);` line from `test.beforeEach`.
- **Validation:**
  - Re-run matrix smoke: `node skills/vg-codegen-interactive/filter-test-matrix.mjs` against canonical fixture; `grep -c 'loginAs(' rendered/*.spec.ts` returns 0; `grep -c 'test.use(useAuth(' rendered/*.spec.ts` returns 10.
  - Phase 15 acceptance smoke still PASS.
- **Commit:** `feat(phase-17-T3.1): 10 D-16 templates — test.use(useAuth) replaces beforeEach loginAs`
- **Effort:** 1h

### T-3.2 — Implement verify-test-session-reuse.py validator (D-06)
- **File:** `scripts/validators/verify-test-session-reuse.py`
- **Action:** Per SPECS D-06 logic.
  - argparse: `--phase`, `--tests-glob`, `--strict`
  - Use `_common.py` Output / Evidence helpers (consistency with Phase 15 validators)
  - Phase dir resolution via `find_phase_dir`
  - Logic: scan glob for `loginAs(` outside comments; aggregate; emit per-file evidence
- **Validation:** Phase 15 acceptance test class extends to assert this validator registered + executable.
- **Commit:** `feat(phase-17-T3.2): verify-test-session-reuse.py validator (D-06)`
- **Effort:** 0.5h

---

## Wave 4 — Global setup + config + init wiring (2h)

### T-4.1 — Create playwright-global-setup.template.ts (D-04)
- **File:** `commands/vg/_shared/templates/playwright-global-setup.template.ts`
- **Action:** Per SPECS D-04 contract; add docstring header explaining auto-install + customize freely.
- **Commit:** `feat(phase-17-T4.1): playwright-global-setup template (D-04)`
- **Effort:** 0.5h

### T-4.2 — Create playwright-config.partial.ts merge instructions (D-04)
- **File:** `commands/vg/_shared/templates/playwright-config.partial.ts`
- **Action:** Per SPECS D-04 fragment with merge instructions in comments.
- **Commit:** `feat(phase-17-T4.2): playwright-config.partial.ts merge guide (D-04)`
- **Effort:** 0.25h

### T-4.3 — Extend vg.config.template.md with test: block (D-05) + init.md detection
- **Files:**
  - `vg.config.template.md` — append `test:` block per SPECS D-05
  - `commands/vg/init.md` — extend Playwright detection step to copy 2 templates from W4.1+W4.2 + show merge instructions
- **Validation:**
  - YAML lint vg.config.template.md.
  - `/vg:init` against fresh project with playwright.config.ts → 2 files copied to e2e/, console shows merge hint.
- **Commit:** `feat(phase-17-T4.3): vg.config test: block + init.md Playwright detection (D-05)`
- **Effort:** 1.25h

---

## Wave 5 — Acceptance + integration (1.5h)

### T-5.1 — Phase 17 acceptance smoke + extend Phase 15 acceptance
- **Files:**
  - `scripts/tests/root_verifiers/test_phase17_acceptance.py` — new file
  - `scripts/tests/root_verifiers/test_phase15_acceptance.py` — EXTEND `TestPhase15Templates` class with assertions for D-03 changes (each .test.tmpl contains `useAuth`, no `loginAs`)
- **Action — `test_phase17_acceptance.py` covers:**
  - 6 D-XX deliverables present (validator script, 2 templates, vg.config block, helper exports, init.md hooks)
  - Helper file LOC ≤ 500
  - 10 P15 templates updated (no `loginAs`, has `useAuth`)
  - Validator regression test (legacy fixture WARN; modern fixture PASS)
  - integration smoke: render 10 templates → grep counts → assert
- **Validation:** Run `pytest scripts/tests/root_verifiers/test_phase15_*.py scripts/tests/root_verifiers/test_phase17_*.py -v` → all green.
- **Commit:** `test(phase-17-T5.1): acceptance suite + extend Phase 15 template assertions`
- **Effort:** 1.5h

---

## Goal-backward verification

**Phase 17 goal:** Test wall-clock down ≥50% on RTB Phase 7.14.3 dogfood; browser process count = workers count (4) instead of per-spec spike.

| Metric | Pre-Phase 17 | Post-Phase 17 | Mechanism |
|---|---|---|---|
| Login flows per `/vg:test` run | O(N spec files) ~10-180 | O(M roles) ~1-5 | D-04 global-setup runs `loginOnce` once per role; D-03 specs use `useAuth` (no per-test login) |
| Browser context churn | 1 per spec file (default isolation) | 4 (workers pool) | D-05 `playwright.workers: 4 + fully_parallel: true` |
| Wall-clock test time on enriched phase (3 views × 2 controls × 3 roles ≈ 180 specs) | ~25-40 min (5s login × 180 + test bodies) | ~5-15 min (5s × 5 logins + parallel test bodies) | combined effect |
| Stale codegen drift | silent (consumer doesn't know to regen) | WARN per `/vg:test` | D-06 validator |

Goal achieved if T-5.1 acceptance test passes AND consumer dogfood (separate manual run) shows ≥50% wall-clock improvement.

---

## Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Consumer's existing `loginAs` differs from new `loginOnce` semantics → migration confusion | MED | LOW | Keep `loginAs` legacy export; `MIGRATION-helpers.md` doc; D-06 validator at WARN (not BLOCK) for 2 cycles |
| Playwright API auth strategy fails for projects with CSRF / OAuth flows | MED | MED | `loginOnce` strategy=`auto` falls back to UI; documented; consumer can force `strategy=ui` |
| `.auth/` files leaked to git → secret exposure | LOW | HIGH | `/vg:init` appends to `.gitignore` + WARN if `.auth/` already tracked |
| Phase 15 acceptance regression (10 templates extension) | LOW | MED | T-5.1 extends assertions; smoke run at every commit; rollback plan = revert T-3.1 commit |
| Storage state shape drift (Playwright version bump) | LOW | LOW | Version-pin Playwright in vg.config dependency hint; sidecar `.meta.json` records Playwright major version |

---

## Out-of-blueprint follow-ups (Phase 18 candidates)

- Multi-browser storage state (Firefox + WebKit each format) — defer.
- Encrypted storage state (auth tokens at rest) — defer; `.gitignore` + dev-only is sufficient now.
- Auto-detect API auth shape (CSRF token harvesting) — defer; manual `strategy=ui` works for now.
- D-06 validator escalation WARN → BLOCK after 2 release cycles — track as Phase 19.x candidate.
