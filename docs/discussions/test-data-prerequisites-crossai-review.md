# Cross-AI review synthesis: RFC #80 + Wave-3.x harness

**Date:** 2026-05-02
**Reviewers:** Codex GPT-5.5 (full review), Claude Sonnet 4.6 (full review), Gemini Pro 3.1 (quota exhausted, skipped)
**Scope:** RFC test-data-prerequisites D1-D8 + wave-3.x harness fixes (PR #79)
**Verdict:** RFC direction sound but has 5 HIGH-severity correctness/safety holes that should land BEFORE PR-A is written.

## Convergent findings (both reviewers flagged HIGH)

These show up in both Codex and Claude reviews independently. Treat as load-bearing concerns.

### 1. D7 preflight non-convergence — shared trigger entity (CORRECTNESS BUG)

Both reviewers identified this as a core algorithm bug, not an edge case.

**Scenario:** G-10 (admin approves tier2 topup) and G-11 (admin rejects tier2 topup) both declare `setup_recipe: G-10` invariant "≥1 tier2 pending exists". Preflight creates 1 row. Concurrent scanners run. G-10 approves → row leaves pending. G-11 finds 0 rows → SUSPECTED. `--retry-failed` re-runs preflight, creates another row, G-11 passes. But if G-10 was also in retry set for any reason, scanners ping-pong forever.

**Why it's worse than it looks:** the invariant schema treats "≥1 row" as the success condition, but mutation goals CONSUME their trigger entity. N consumers = need N rows, not 1.

**Fix (both reviewers converged):** preflight counts consumers per invariant from the matrix, creates N entities, stores each in `.fixture-cache.json` keyed by `G-XX` not by invariant. Schema needs `setup_recipe` to express consumer count or per-goal isolation.

**Impact:** changes both D5 schema and D7 algorithm. Must resolve before PR-A is written.

### 2. Wave-3.2.2 evidence provenance hole — already shipped, hotfix needed

Claude flagged HIGH; Codex flagged separately as "spoofable promotion."

**Scenario:** wave-3.2.2 promotes SUSPECTED → READY when `goal_sequence has submit + 2xx`. But the goal_sequence JSON is writable by executor agents, scanner agents, and orchestrator code paths. An executor can hand-write a fake submit step with status 200 — sync flips status to READY, no re-validation, no scanner ever ran.

**Why critical:** this is currently live in PR #79. The matrix-staleness validator we shipped relies on goal_sequence integrity. Without provenance, the verification model PR #79 was supposed to repair has a back door.

**Fix:** add `evidence_source: "scanner" | "executor" | "orchestrator"` field to goal_sequence steps. Bidirectional sync only promotes on `scanner`-sourced evidence. Other sources are informational, never trigger status change.

**Impact:** independent hotfix to PR #79. Not blocked by RFC #80 implementation. Should land before PR-A so PR-A can rely on the trust model.

### 3. Sandbox accumulation + financial side effects

Both reviewers flagged HIGH. RFC's "richer = easier" stance is too optimistic for billing domains.

**Concrete risks:**
- Phase 3.2 fixtures POST to `/wallet/topup-requests` → real wallet balance entries. Even sandbox, accumulates over time. Dashboards see inflated topup volume.
- Live gateway webhooks fire on sandbox topups (common). External side effects.
- Reconciliation jobs see fixture-created amounts.
- Unique constraints, rate limits, pagination degrade after N runs.
- Admin queue UI shows fixture rows mixed with real merchant requests — finance team can't distinguish.

**Fix (both reviewers):**
- Hard environment safety gate in runner: refuse unless `environment.kind: sandbox` + server confirms via `/health` header `X-VGFlow-Sandbox: true`
- Required fixture sentinel values: amount ≤ 0.01 for currency-like fields, email domain `@fixture.vgflow.test`, reference prefix `VG_FIXTURE_`
- Add `side_effect_risk: money_like` field on recipe steps; runner refuses on prod-like envs

**Impact:** schema additions; gate code in runner. Must land in PR-A.

### 4. D8 tag-based delete assumes a metadata column that often doesn't exist

Both reviewers questioned this. Many real schemas — especially financial ledger rows, immutable audit records, join tables, external payment objects — cannot accept arbitrary metadata fields.

**Codex suggestion:** support external tag registries — `.fixture-cache.json` records `{resource, id, run_id}` even when entity can't store metadata. Prune deletes by registry first, optional marker fields second.

**Claude suggestion:** change contract to "creation timestamp + reference pattern + explicit per-entity-type tag-field mapping in `vg.config.fixtures.entity_types`." Project configures which field per entity. Fallback: time-window delete.

**Impact:** D8 contract changes. Schema implications for D2 (`reference` field becomes mandatory + standardized). Must specify before PR-A bakes the schema.

### 5. D2 schema gaps — multi-value capture, loops, run_id collisions

Both flagged that the strawman schema doesn't handle real cases:

- **JSONPath cardinality undefined** (Claude HIGH): `$.items[*].id` returns array. Strawman shows scalars only. What does runner do — first element? Silent truncation? Loop semantics?
- **Loop steps missing** (both): G-52 IMAP CRUD needs N existing configs. No `kind: loop` step type.
- **run_id collision** (Claude MEDIUM): two concurrent `/vg:review` against same sandbox both compute "0 tier2 pending" → both create rows → both write `.fixture-cache.json` → race. Unspecified format.
- **Optional/conditional steps** (Codex): no escape hatch for "create only if doesn't exist."

**Fix:**
- Specify cardinality rules: 0 matches = fail unless `optional: true`; 1 match = scalar; >1 = array
- Add `kind: loop` step with `over: [...]` and `count: N`
- `run_id` format: `{timestamp_ms}-{random_4hex}` mandated
- Atomic file writes for `.fixture-cache.json` (write tmp + rename) OR per-run files `.fixture-cache-{run_id}.json`

**Impact:** schema spec extensions. Must land in PR-A.

## Codex-unique observations worth integrating

- **Auth gaps are bigger than 4 kinds.** Public-framework adoption needs SAML, mTLS, HMAC signing, refresh-token rotation, MFA flows, CSRF, tenant-scoped auth. Recommended escape hatch in v1: `auth.kind: command` returning headers/cookies JSON. Keeps default declarative, unblocks exotic stacks without forcing upstream contributions.
- **Recovery commands need test coverage.** `/vg:doctor recovery` prints recovery commands to user. Each violation→command mapping should have a test fixture asserting the command actually changes the violation state, or explicitly marks itself manual-only. Otherwise commands rot into cargo-cult.
- **Backend goals excluded from matrix-staleness need equivalent backend evidence validation.** Filter to UI-only is necessary; replacing it with "we trust replay-evidence + surface-probe will catch backend gaps" needs a parallel backend-staleness validator, not just exemption.
- **`fixture_intent` cross-reference.** Add a block linking fixture fields back to `mutation_evidence` requirements declared in TEST-GOALS, so a separate validator can compare blueprint intent vs fixture reality (catches "fixture passes scanner but doesn't match test-goal intent").

## Claude-unique observations worth integrating

- **Token refresh inside multi-step recipes.** 15-min JWT expires mid-recipe (step 3 of 5 hits 401). Auth module needs to track issue time + expiry, re-authenticate when TTL < 10% remaining before each step. Currently silent failure mode.
- **Build-time fixture smoke-execution, not just schema validation.** `verify-build-fixtures-present.py` validates YAML structure but not semantic correctness — executor can write a fixture pointing to wrong endpoint. Build wave gate should *execute* the fixture against sandbox at build time. Adds ~30s/goal, catches broken fixtures immediately at build, not 3 PRs later at preflight.
- **Single recipe runtime hides two protocols.** `/vg:review` preflight = once-per-phase shared state. `/vg:test` `beforeEach` = once-per-test isolated state. The YAML works structurally for both, but `EXPECTED_ROW_ID` injection has different lifecycle for each consumer. Add explicit `review_mode` / `test_mode` sections OR `semantics: shared | isolated` field. Hiding two protocols in one schema makes "no drift" superficially true but structurally fragile.
- **Auth escape hatch should be local hook, not upstream PR.** Project with custom OAuth/HMAC modifies vgflow core = fork + PR + review + merge cycle. Blocks dogfood-stage adoption. Local plugin file (`fixture-auth-plugin.{py,sh}` in project root) loaded by runner unblocks fast adoption without forcing upstream contributions.
- **Docker image as universal portability layer.** Solves both "Python in CI" and "JS-only shop" concerns. Ship `Dockerfile` for the runner.
- **Concurrent /vg:review races on .fixture-cache.json.** Two developers on shared sandbox both run preflight, both create rows, last-writer-wins on cache file → first runner's scanner uses wrong ID. Atomic writes or per-run files mandatory.
- **DEFERRED status compounds across phases.** 8% in Phase 3.2 grows as billing-domain phases stack. After 5 phases possibly 15+ DEFERRED goals. Add `blocked_since_phase` field; surface in health checks as technical debt.

## TOP-5 priorities BEFORE PR-A is opened

Synthesizing both reviewer rankings + my own filter:

1. **Fix wave-3.2.2 evidence provenance hole (independent hotfix to PR #79).** Add `evidence_source` field; only `scanner`-sourced evidence triggers READY promotion. Current code is exploitable.
2. **Resolve D7 preflight non-convergence — preflight counts N consumers, creates N entities.** Algorithm bug, must fix before any schema is written.
3. **Specify D2 schema gaps fully** — JSONPath cardinality rules, `kind: loop` step type, `run_id` format, atomic cache writes, optional steps. Schema is foundational; getting it right prevents cascade rework in PR-B/D/E.
4. **Sandbox safety guardrails** — environment kind check, sentinel values, side_effect_risk field. Public-framework grade can't ship a billing fixture runner without safety rails.
5. **D8 tag-based prune contract revision** — registry-based + per-entity-type field mapping + time-window fallback. Schema implications cascade into D2 (reference field becomes mandatory + standardized).

## Items to defer to follow-up (not PR-A blockers)

- Auth escape hatch via local plugin (D1 — addressable in PR-A or PR-B without rework)
- Build-time fixture smoke-execution (refinement to PR-B, not PR-A)
- Token refresh in auth module (PR-A scope, but standard pattern)
- Schema versioning + deprecation policy (PR-A scope, low risk)
- Recovery command test coverage (separate harness PR)
- DEFERRED tracking with `blocked_since_phase` (small wave-3.2.3 patch)
- `fixture_intent` cross-reference (PR-B refinement)

## What both reviewers said WAS solid

- D6 codegen runtime call (vs transpile) — DRY wins, both endorsed
- Authoring at /vg:build is directionally right (executor knows API shape)
- Single source-of-truth YAML is good anti-drift principle if schema boundaries explicit
- Rejecting scanner self-help (option D) is correct — non-deterministic
- D7 making invariant gaps BLOCK (not silent SUSPECTED) directly fixes original failure mode
- Bidirectional sync is necessary; one-way SUSPECTED would trap valid fixes
- Recovery paths are strong UX improvement IF treated as code (validated, tested)

## Reviewer caveats

- **Codex GPT-5.5** delivered the most thorough review (56KB output, full A-E coverage + TOP-3).
- **Claude Sonnet 4.6** delivered detailed review with strong concrete scenarios (G-10/G-15 ping-pong example).
- **Gemini Pro 3.1** quota-exhausted (HTTP 429), no review obtained. Re-run when quota resets if user wants 3rd voice.

## Recommended next move

Open a focused **wave-3.2.3 hotfix PR** for evidence provenance (item 1 above) — fast, independent of RFC. Then revise RFC #80 with items 2-5 baked in (single commit, big diff). Only AFTER that, open PR-A.

Estimated impact on RFC implementation timeline: +1 week pre-PR-A for hotfix + RFC revision; net result is fewer rework PRs later.
