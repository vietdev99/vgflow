# RFC: Test-data prerequisites for review/test workflow

**Status:** Direction + design decisions chosen 2026-05-02, ready to split into implementation PRs
**Surfaced by:** PrintwayV3 Phase 3.2 dogfood (2026-05-01) on wave-3.2.x dogfood run
**Related:** PR #79 (recovery paths + matrix-staleness), PR #74 (anti-performative-review)

---

## The problem in one paragraph

`/vg:review` and `/vg:test` need realistic application **state** to verify mutation goals. Phase 3.2 G-10 says "Admin approves tier2 topup request"; sandbox seed has 12 tier1 rows and 0 tier2 rows. Scanner navigates to `/billing/topup-queue`, sees only tier1 rows showing "Auto via webhook" placeholder, can't click an Approve button that doesn't exist for tier1, and reports `no_submit_step`. The matrix-staleness validator correctly flags SUSPECTED. But the **root cause is missing data**, not missing UI or missing code. We can re-run scanners forever without ever creating the data they need to exercise.

This is the meta-bug behind ~21 of 36 mutation goals flagged in the dogfood run: not "scanner missed it" but "nothing to scan because the trigger entity doesn't exist in seed".

## Concrete failure modes observed in Phase 3.2

| Goal | Needs | Sandbox has | Result |
|---|---|---|---|
| G-10 admin approve tier2 topup | tier2 topup row in `pending` | only tier1 rows | scanner sees no Approve button → SUSPECTED |
| G-19 merchant cancels pending withdraw | merchant has pending withdraw | empty wallet, no withdraws | route renders empty state → SUSPECTED |
| G-23 admin resets cooling period | merchant currently cooling | no cooling-period state | reset button never appears → SUSPECTED |
| G-31 admin transfer group CRUD | existing transfer group OR new-group flow | empty list | only "create" path testable → partial submit |
| G-34 linked accounts CRUD | linked accounts exist | empty | edit/delete unreachable |
| G-35 bank accounts CRUD | bank accounts exist | empty | edit/delete unreachable |
| G-44 admin sets FX rate | rate exists for given gateway×currency | inconsistent seed | sometimes editable, sometimes not |
| G-52 IMAP config CRUD | configs exist | only one default | partial CRUD only |

Pattern: **list/queue routes are healthy when empty, but mutation goals (approve/reject/edit/delete/cancel) need the entity to exist first, in the right status, with the right tier/role/state**.

## What kinds of data does a goal need?

Not all "needs data" cases are equal. From the Phase 3.2 sample:

1. **Trigger entity** — the row the action operates on (tier2 topup row to approve)
2. **Lifecycle state** — entity in a specific status (cooling-period merchant, pending withdraw)
3. **Cross-entity relationship** — entity A pointing to entity B (linked accounts → gateway, transfer between merchants in same group)
4. **Time-driven state** — entity with timestamp older than X (7-day chargeback deadline, cooling period)
5. **Side-effect setup** — entity created by a prior side-effect (chargeback webhook fires → wallet frozen → admin sees frozen banner)
6. **Negative-path setup** — entity in a *forbidden* state to verify the gate (frozen recipient, suspended merchant)

Each needs a different setup mechanism. A "tier2 topup row" might be a single API POST as merchant. A "7-day chargeback timeout" may need time-travel or a fake-clock test mode. A "frozen wallet" needs prior chargeback webhook + freeze logic to have run.

---

## Direction chosen (2026-05-02)

After surveying 6 options (A through F — preserved at the bottom of this doc for context), the chosen path is:

> **Recipes authored at `/vg:build` time, executed before `/vg:review` scanner spawn and reused by `/vg:test` Playwright codegen. No inline cleanup — sandbox accumulates data; cleanup is a separate command users run on their own cadence. Single source-of-truth recipe artifact per mutation goal, public-framework grade.**

### Decision 1 — Authoring lives in `/vg:build`

Executor authors fixture recipe alongside the goal it implements, because that's the only point where the API shape is concrete (handler signed, routes registered, schemas final). Blueprint-time authoring would force the planner to predict API details it hasn't designed yet; review-time authoring would force the scanner to know API shapes it shouldn't care about.

Concretely: when `/vg:build` finishes a goal that has `**Mutation evidence:**` declared in TEST-GOALS.md, an additional executor sub-step writes `FIXTURES/{G-XX}.yaml` next to the goal artifacts. Build is not "done" for a mutation goal until its fixture exists. This becomes a new wave-verify gate in `/vg:build`.

Cost: yes, `/vg:build` grows. We accept it because (a) recipes need API knowledge the executor already has, (b) duplicating this knowledge into a separate `/vg:fixture` step would reorder pipeline and add a new artifact dependency, and (c) tests authored at build-time match the implementation they describe — drift is harder.

### Decision 2 — Cleanup is external, not inline

Sandbox is "richer = easier". A sandbox with 200 rows across all states is more useful for review than one with 12 rows that get rejected and disappear. We don't transactional-cleanup after each scanner run.

Implication: scanner runs are NOT idempotent in the sense of "matrix returns to identical state". Re-running `/vg:review --retry-failed` on the same goal will keep creating new tier2 rows. That's fine — they're cheap. The state space we care about is "≥1 tier2 in pending exists at any given moment", not "exactly 1".

Cleanup is a separate command — call it `/vg:fixture-prune` for now — that runs on user's cadence (after a milestone? Weekly via cron? At sandbox-reset?). It reads run logs, finds fixtures created by VGFlow, deletes them. Out of scope for this RFC; tracked as a follow-up.

This decision **massively simplifies recipe schema** — every recipe is one-shot setup, no rollback, no compensating transaction. We lose nothing real because sandbox = disposable seed by env contract.

### Decision 3 — Recipe runtime serves both `/vg:review` and `/vg:test`

One artifact, two consumers:

- **`/vg:review` scanner preflight** — orchestrator runs the recipe before spawning Haiku for that goal's view. Captures created entity IDs into env vars, injects them into Haiku prompt as `EXPECTED_ROW_ID=...` so scanner targets the right row.
- **`/vg:test` Playwright codegen** — generates `test.beforeEach()` block in the spec file that runs the same recipe (transpiled from YAML to TypeScript at codegen time, OR called via shared HTTP harness — TBD in question 1).

Single recipe = no drift between review's scanner expectations and test's codegen output. If recipe wrong, both fail same way; fix once.

### Decision 4 — Public-framework grade

VGFlow is positioned as a heavy framework other projects will adopt. Implications for this RFC:

- Schema must be portable — no PrintwayV3-isms, no hardcoded auth assumptions
- Recipe runtime must be language-agnostic at the boundary — YAML in, HTTP/CLI calls out, no project-specific Python imports
- Failure modes must be load-bearing — a recipe failure must produce an actionable error, not a silent SUSPECTED
- Every artifact must have a reason to exist — no `FIXTURE.md` doc that just narrates what `FIXTURES.{G-XX}.yaml` already says

This bars option A (extend seed.ts) as the primary mechanism — that's PrintwayV3-specific seed code we can't ship in vgflow. Option F (data_invariants in ENV-CONTRACT.md) survives because it's declarative + portable.

### Final shape: B + F

- **B (per-goal recipes, build-time authored)** is primary
- **F (data_invariants preflight gate)** is the cheap declarative wrapper — phase declares "≥1 tier2 pending must exist before scanner spawns" in ENV-CONTRACT.md; preflight verifier walks recipes from all goals in the phase, computes whether invariant is met, runs missing recipes
- A, C, D, E **rejected for v1** — A is project-specific, C is premature abstraction (revisit after 10+ phases), D is non-deterministic, E is orthogonal (separate time-travel RFC later)

---

## Design decisions (Q1-Q8 resolved 2026-05-02)

The 8 questions surfaced after Decisions 1-4 are now answered. Each decision below has rationale + immediate implication for implementation.

### D1 (was Q3) — Runtime architecture: vgflow ships generic runner, pluggable auth via YAML

Vgflow ships `scripts/run-fixture.py` (or equivalent — language TBD at PR-A time but Python likely) that reads recipe YAML, performs HTTP calls, captures responses. Project supplies only YAML content; no project-side runner code.

Auth pluggability is **YAML-declarative**, not Python entrypoints. Project declares in `vg.config.environments.{env}.auth`:

```yaml
auth:
  kind: cookie       # or: bearer, session, api-key
  login_endpoint: /api/v1/auth/login
  body_template:
    email: "{role.email}"
    password: "{role.password}"
  capture:
    cookie: connect.sid          # for kind=cookie
    # or token_path: $.token     # for kind=bearer
```

Runner supports 4 auth kinds covering ~90% of stacks (cookie session, bearer JWT, header api-key, OAuth client-credentials). Project with exotic auth → upstream contribution to runner.

**Rationale:** matches "public framework" (Decision 4). Python entrypoints would couple recipes to vgflow's language choice. Sub-shell would be portable but ugly to debug.

**Rejected alternatives:**
- (b) project-side runner — duplicates HTTP+auth+capture code per project; defeats framework adoption
- Python entrypoints — coupling vgflow language to recipe consumers

### D2 (was Q1) — Recipe schema

```yaml
goal: G-10
description: Admin approves tier2 topup — row must exist in pending tier2 state
steps:
  - id: create_tier2_topup
    kind: api_call
    role: merchant-owner                 # lookup into vg.config.credentials[env]
    method: POST
    endpoint: /api/v1/wallet/topup-requests   # relative; runner resolves base from config
    body:
      amount: 100
      currency: USD
      gateway: sunrate
      reference: "vgflow-fixture-{run_id}-{step.id}"
    capture:
      request_id: $.id                   # JSONPath syntax (RFC 9535)
expects:
  capture_into:
    EXPECTED_ROW_ID: "{steps.create_tier2_topup.request_id}"
```

**Decisions baked in:**
- `endpoint`: **relative**, runner resolves `api_base` from `vg.config.environments.{env}.api_base`. Portable across local/sandbox/staging.
- `role`: **string lookup** into existing `vg.config.credentials[env]` array. No new typed enum — reuses established pattern.
- `capture`: **JSONPath** (RFC 9535 standard). Not jq — that's a project-side tool dependency we won't ship.
- `body` template variables: `{run_id}`, `{step.id}`, `{steps.<step_id>.<capture_name>}`, `{role.email}` — minimal interpolation, no full templating engine.
- Auth tokens: **handled by runtime, not in recipe**. Recipe declares `role: merchant-owner`; runner logs in once per role per session, attaches creds to subsequent calls.
- Multi-step: `steps: [...]` array, each step has `id`, later steps reference prior captures via `{steps.<id>.<name>}`.

**Rejected alternatives:** absolute URLs (breaks portability), typed role enums (premature abstraction), jq syntax (tool dep), in-recipe secrets (security smell).

### D3 (was Q2) — Multi-step failure: no rollback, log orphans

Step N fails → recipe overall fails → goal marked BLOCKED in matrix with reason `fixture step N/M failed: <error>`. Steps 1..N-1 already executed leave their entities behind (per Decision 2 "no cleanup").

One concession to debugging: orphan IDs captured before failure get logged to `runs/G-{XX}.fixture-orphans.json`. `/vg:fixture-prune` (D8) reads this when cleaning up.

**Rationale:** transactional rollback would require compensating-call infrastructure per entity type — engineering cost too high for sandbox-disposable model. Logging orphans is ~10 lines, gives prune the data it needs.

### D4 (was Q4) — Time-driven goals deferred to separate RFC

Goals requiring backdated timestamps or fast-forward (cooling period, 7-day chargeback deadline, BullMQ retry-attempt-N) are NOT solved by recipes in v1. They need backend cooperation (test-only headers, sandbox-only env detection) — a separate multi-week design.

**For now:** affected goals declare `requires_time_travel: true` in TEST-GOALS frontmatter. Surface filter in `/vg:review` classifies them as **DEFERRED** (not SUSPECTED, not BLOCKED) with reason "needs time-travel infra (separate RFC)". Matrix verdict treats DEFERRED as a valid endpoint per existing v1.14.0+ scope-tag model.

**Affected from Phase 3.2 dogfood:** G-22 (withdraw cooling period), G-42 (chargeback 7d auto-suspend), G-58 (BullMQ retry + DLQ). 3 of 36, ~8%.

**Follow-up:** open `RFC: time-travel test infrastructure` once first non-Phase-3.2 phase blocks on this class.

### D5 (was Q5) — `data_invariants` schema with explicit owner

```yaml
# In ENV-CONTRACT.md
data_invariants:
  - id: tier2_topup_pending
    resource: topup_requests
    where:
      status: pending
      tier: tier2
    count: ">=1"
    setup_recipe: G-10                   # 1:1 case — single goal owns

  - id: linked_account_exists
    resource: linked_accounts
    where: { status: active }
    count: ">=1"
    setup_recipe: [G-34]                 # list form — same syntax as multi-owner
    # When multiple goals share: setup_recipe: [G-34, G-36]
    # First entry = owner, rest declare `inherits: G-34` in their own FIXTURES/{G-XX}.yaml
```

**Decisions baked in:**
- Owner is **explicit**, not auto-derived. First entry in `setup_recipe` list owns the recipe; others reference via `inherits` field in their own fixture YAML.
- `where` is conjunction-only (AND semantics across keys). Disjunction (OR) → multiple invariant entries. Keeps query simple.
- `count` accepts `>=N`, `==N`, `>N` (string syntax — runner parses).

**Rationale:** auto-derived ownership (alphabetical, declaration order, etc.) creates surprise when goals are reordered. Explicit field = grep-able, refactor-safe.

### D6 (was Q6) — Codegen emits `runFixture()` runtime call (option b)

`/vg:test` Playwright codegen emits:

```typescript
test.beforeEach(async ({ request }) => {
  await runFixture(request, 'G-10');     // resolves to FIXTURES/G-10.yaml at test-run time
});
```

`runFixture` is a TS helper (~30 LOC) shipped with vgflow as `@vgflow/fixture-runtime` (or vendor-copied — packaging TBD at PR-E time). Reads YAML, makes HTTP calls via Playwright's `request` fixture, returns capture map.

**Rationale:** option (a) transpile-to-inline-TS means changing YAML doesn't update emitted specs until codegen re-runs — drift waiting to happen. Option (b) keeps YAML as single source of truth; tests pick up changes on next run automatically.

**Trade-off accepted:** specs depend on a runtime helper + YAML files. For projects checking specs into a vendor folder, the helper vendors with them — minimal friction.

### D7 (was Q7) — Preflight runs once, scanner reads cache

Phase 2c-pre adds `verify-data-invariants` step:
1. Walk all `data_invariants` declared in ENV-CONTRACT.md
2. Query sandbox state via API for each (read-only).
3. For each invariant violated: lookup `setup_recipe` (the owning goal), run that goal's `FIXTURES/{G-XX}.yaml`, capture IDs into `${PHASE_DIR}/.fixture-cache.json`.
4. Re-query each violated invariant. Still violated → BLOCK with actionable error referencing recipe path.

Each Haiku scanner reads `${PHASE_DIR}/.fixture-cache.json` for its goal's `EXPECTED_ROW_ID` and other captures. Injects into prompt as env vars.

**No re-check before each scanner spawn.** If prior scanner's mutation invalidated a later goal's invariant (e.g., G-11 rejects the only tier2 row that G-10 needed), G-10's scanner fails with clear error → matrix BLOCKED → next `/vg:review --retry-failed` re-runs preflight which re-creates the missing entity.

**Rationale:** N scanners × M invariants × API roundtrip = excessive cost for marginal correctness. Once-per-run preflight + retry-failed loop converges in 1-2 iterations for hostile cases.

**Order matters:** the preflight check is a first-class verifier, not a soft-warn — invariant gap = BLOCK. This is what prevents the "scanner ran but had nothing to test" failure that started this RFC.

### D8 (was Q8) — `/vg:fixture-prune` spec (own mini-RFC, contracts only)

Full spec deferred to its own RFC, but commits to these contracts:

- **Tag-based delete only.** Every fixture-created entity carries `vgflow_fixture_run_id` field (or analogous metadata per entity type). Prune matches by tag pattern, never deletes untagged entities.
- **Manual trigger for v1** — user runs `/vg:fixture-prune` on their cadence. No cron. Default age threshold: 7 days (configurable).
- **Scoped role** — dedicated `vgflow-fixture-cleaner` credential with hard-delete privilege scoped to fixture-tagged entities only. NOT admin role — limits blast radius if cleaner script bugs out.
- **Includes orphan list** — reads `runs/G-{XX}.fixture-orphans.json` (from D3) to clean partial-recipe-failure leftovers.

These contracts unblock D2, D3, D5 — they don't have to predict prune behavior.

**Follow-up:** `RFC: vg:fixture-prune cleanup command` after D1-D7 ship.

---

## Out of scope (explicit non-goals)

- Production data — never. Sandbox only.
- Performance testing fixtures (different shape — 100K rows, not 1 row per state).
- Visual regression baselines (separate concern).
- Migration test data (handled by schema-verify profile).
- Time-travel infrastructure (deferred to separate RFC per Q4).
- Sandbox reset / database snapshot mechanics — outside vgflow's responsibility, project's deploy pipeline handles.

---

## Implementation plan

D1-D8 resolved. Split into PRs in dependency order:

1. **PR-A: Recipe schema + auth-pluggable runner skeleton** (D1, D2, D3)
   - `schemas/fixture-recipe.schema.yaml` (JSON-Schema for validation)
   - `scripts/run-fixture.py` skeleton — reads YAML, walks `steps[]`, captures via JSONPath, no-op when API base unreachable
   - 4 auth-kind handlers: cookie, bearer, api-key, oauth-client-creds
   - Unit tests on schema validation + JSONPath capture + multi-step variable resolution
   - Orphan logger writes `runs/G-{XX}.fixture-orphans.json` on partial failure
   - **No vgflow consumer yet** — runner runs standalone via `python3 run-fixture.py FIXTURES/G-10.yaml`. Validates the engine before wiring anything.

2. **PR-B: `/vg:build` fixture-write step** (D2 authoring side)
   - New executor sub-step: after implementing a goal with `mutation_evidence`, write `FIXTURES/{G-XX}.yaml`
   - New wave-verify validator: `verify-build-fixtures-present.py` — build wave not done if mutation goal lacks fixture YAML matching schema
   - `requires_time_travel: true` recognition — skip fixture requirement, mark goal DEFERRED in matrix instead (D4)
   - Build can no-op gracefully on phases with no mutation goals (backward compat)

3. **PR-C: ENV-CONTRACT.md `data_invariants` + preflight verifier** (D5, D7)
   - Schema for `data_invariants` block in ENV-CONTRACT.md
   - `verify-data-invariants.py` — queries sandbox per invariant, runs `setup_recipe` if violated, re-queries, BLOCKs if still violated
   - Hooks into `phase2c_pre_dispatch_gates` step in `/vg:review`
   - Writes `${PHASE_DIR}/.fixture-cache.json` for downstream scanners

4. **PR-D: `/vg:review` scanner preflight integration**
   - Haiku scanner prompt extended: reads `.fixture-cache.json`, injects `EXPECTED_ROW_ID` etc. as env vars for scanner agent
   - Matrix-staleness validator gets new `requires_time_travel` filter — those goals never flagged SUSPECTED, classified DEFERRED instead
   - Recovery paths in `recovery_paths.py` extended with `validator:data-invariants` entries

5. **PR-E: `/vg:test` codegen integration** (D6)
   - Playwright codegen emits `await runFixture(request, 'G-XX')` in generated specs
   - `@vgflow/fixture-runtime` package (or vendor copy) — TS helper that reads YAML at test-run time
   - Validator: `verify-codegen-fixture-binding.py` — every codegen test for a mutation goal must include `runFixture()` call

6. **PR-F (separate, after D1-E land)** — `RFC + impl: /vg:fixture-prune` cleanup command (D8)
   - Tag-based scan + delete with `vgflow-fixture-cleaner` role
   - Reads orphan logs from PR-A
   - User-triggered, default 7-day age threshold

7. **PR-G (separate, future)** — `RFC: time-travel test infrastructure` (D4)
   - Backend `X-Sandbox-Time-*` headers contract
   - Sandbox-only env detection
   - Recipe extension: `time_advance:` step kind
   - Lifts ~8% of dogfood goals from DEFERRED to testable

**Sequencing rationale:**
- PR-A is the foundation — runner works standalone, can be tested without other components
- PR-B adds the upstream producer (build writes YAML)
- PR-C adds the downstream consumer (preflight reads YAML)
- PR-D wires preflight into review scanner spawn
- PR-E extends to test layer
- PR-F + PR-G are independent follow-ups

**Estimate:** PR-A through PR-E in 2-3 weeks if no surprises. PR-F + PR-G open-ended.

---

## Appendix: 6 options surveyed (rejected)

For context — preserved from initial RFC.

### Option A: Data factories baked into seed.ts
**Rejected** — project-specific, can't ship in vgflow framework.

### Option B: Per-goal `**Required data:**` recipes in TEST-GOALS.md
**Adopted as primary** (with build-time authoring per Decision 1).

### Option C: Persona-based data wallets
**Rejected for v1** — premature abstraction. Revisit when 10+ phases share setup patterns.

### Option D: Just-in-time scanner self-help
**Rejected** — non-deterministic. Scanner inventing API calls = correctness risk.

### Option E: Time-travel + fake-clock test mode
**Deferred** — orthogonal to recipes. Separate RFC when first goal genuinely blocks (Q4).

### Option F: ENV-CONTRACT.md `data_invariants` + fixture library
**Adopted as preflight gate wrapper** around B.
