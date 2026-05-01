# RFC: Test-data prerequisites for review/test workflow

**Status:** Direction chosen 2026-05-02, design questions remain
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

## What still needs design (open questions)

These are genuine unknowns the chosen direction surfaces. Each blocks some part of implementation.

### Q1 — Recipe schema specifics

```yaml
# Strawman shape, not final
goal: G-10
description: Admin approves tier2 topup → row must exist in pending tier2 state
setup:
  - kind: api_call
    role: merchant-owner
    method: POST
    endpoint: /api/v1/wallet/topup-requests
    body:
      amount: 100
      currency: USD
      gateway: sunrate
      reference: "vgflow-fixture-G10-{run_id}"
    capture:
      request_id: $.id
expects:
  invariant: "topup_requests.where(status=pending, tier=tier2).count >= 1"
  capture_into:
    EXPECTED_ROW_ID: $request_id
```

Open: should `endpoint` be relative (vgflow resolves base URL from env) or absolute? Should `role` be a string lookup into `vg.config.credentials[env]` (current pattern) or a typed enum? How are auth tokens captured/refreshed inside multi-step recipes? Does `capture` use JSONPath, jq syntax, or YAML-native? Each impacts portability.

### Q2 — Multi-step recipe support

Some goals need 2+ steps to set up state — G-23 admin reset cooling period needs (a) merchant exists, (b) merchant performed N failed withdraws, (c) cooling-period flag was raised. Three sequential API calls, each capturing IDs the next uses. Recipe schema must support `steps: [...]` not just one `setup:`.

But chained recipes have failure modes — if step 2 fails, what happens to step 1's created entity? With "no cleanup" rule (Decision 2), nothing — leave the orphan. Is that acceptable, or do we need at least best-effort cleanup on partial recipe failure?

### Q3 — Recipe runtime — vgflow-side or project-side?

Two architectures:

**(a) vgflow ships a generic recipe runner** (`scripts/run-fixture.py`) that reads YAML, makes HTTP calls, captures IDs. Project provides only the YAML content. Most portable — projects don't write code.

**(b) vgflow ships only the schema; projects provide their own runner** in their `scripts/fixtures/` dir. Projects can use whatever language/HTTP lib fits their stack.

Option (a) means vgflow has to handle every project's auth pattern (cookie? JWT header? SSO? OAuth? mTLS?). Option (b) duplicates runner code across projects but keeps vgflow language-agnostic.

Probably (a) with a pluggable auth strategy. But pluggable how — Python entrypoints? Sub-shell scripts? YAML-declarative auth blocks?

### Q4 — Time-driven state (option E re-entry)

Decision rejected E (time-travel) for v1, but Phase 3.2 has goals like G-22 (cooling period blocks new withdraw — needs merchant with `last_failed_withdraw_at < 1h ago`), G-42 (7-day chargeback deadline), G-58 (BullMQ retry — needs job at retry attempt N).

These cannot be solved by API calls alone. Either:
- Backend exposes a `X-Sandbox-Time-Advance: 8d` header that fast-forwards
- Recipe creates entity with backdated timestamp directly via raw DB write (bypasses domain logic)
- Defer those goals — mark them "needs time-travel infrastructure", separate RFC, accept SUSPECTED for now

Which path? If we defer, ~5 of 36 dogfood goals stay SUSPECTED indefinitely.

### Q5 — `data_invariants` schema in ENV-CONTRACT.md

Decision 3 says invariants live there. But the schema isn't designed yet. Strawman:

```yaml
data_invariants:
  - resource: topup_requests
    where: { status: pending, tier: tier2 }
    count: ">=1"
    setup_recipe: G-10  # which goal's recipe creates this
```

Multiple goals may share an invariant (G-10 and G-12 both need tier2 pending). Whose recipe is "owner"? First in alphabetical order? First declared in TEST-GOALS? Manual `owner: G-10` field?

### Q6 — `/vg:test` codegen consumption format

Recipe is YAML. Playwright spec is TypeScript. Two paths:

**(a) Codegen transpiles YAML → TS at codegen time** — every recipe becomes inline TS in the `.spec.ts` file. Spec is self-contained.

**(b) Codegen emits import + call** — `await runFixture('G-10')` in the spec, the runtime imports a TS helper that reads YAML at test-run time. Spec depends on runtime + YAML files at runtime.

Option (a) is simpler for users running the spec standalone. Option (b) is DRY — change YAML once, both review and test see new behavior. Probably (b) but adds runtime dependency.

### Q7 — Preflight verifier architecture

Phase 2c-pre already runs `verify-env-contract.py` (preflight checks for app reachable + login works). The new `data_invariants` check fits naturally there as a third check. But:

- Current verifier is "smoke a thing, fail or pass" — invariant check is "query state, run recipe if missing, re-query, fail if still missing". Different shape.
- If invariant fails AND its setup recipe also fails, what's the user-facing error? "Fixture for G-10 failed — see runs/G-10.fixture-error.json"?
- Preflight runs once before all scanners. Should each scanner also run its own goal's recipe just-before-spawn (in case prior scanners' actions invalidated the invariant — e.g., G-11 reject removed the row G-10 needs)?

### Q8 — `/vg:fixture-prune` cleanup command spec

Decision 2 puts cleanup in a separate command. Spec needed:

- What does prune delete? Only entities tagged with `vgflow-fixture-{run_id}` reference? Anything older than N days? Anything matching naming convention?
- When does user run it? Manual after each `/vg:accept`? Scheduled? Tied to sandbox-reset?
- How does it know which entities are fixture-created vs real test data the user wants to keep?
- Auth: which role runs the prune? Admin with hard-delete? Or a dedicated `fixture-cleanup` role to limit blast radius?

This is its own mini-RFC. For now, accept that it's TBD.

---

## Out of scope (explicit non-goals)

- Production data — never. Sandbox only.
- Performance testing fixtures (different shape — 100K rows, not 1 row per state).
- Visual regression baselines (separate concern).
- Migration test data (handled by schema-verify profile).
- Time-travel infrastructure (deferred to separate RFC per Q4).
- Sandbox reset / database snapshot mechanics — outside vgflow's responsibility, project's deploy pipeline handles.

---

## Implementation plan (after questions resolved)

Once Q1-Q8 are answered, split into PRs:

1. **PR-A: Recipe schema + JSON-Schema validator** — write the canonical YAML schema, ship as `schemas/fixture-recipe.schema.yaml`, add validator script. No runtime yet.
2. **PR-B: `/vg:build` fixture-write step** — executor writes `FIXTURES/{G-XX}.yaml` for every goal with `mutation_evidence`. New wave-verify validator: build incomplete if mutation goal lacks fixture.
3. **PR-C: ENV-CONTRACT.md `data_invariants` block + preflight verifier** — declarative invariant schema, runner that reads recipes + queries state + reports gaps.
4. **PR-D: `/vg:review` scanner preflight integration** — orchestrator runs invariant check, runs missing recipes, captures IDs, injects into Haiku prompt.
5. **PR-E: `/vg:test` codegen integration** — Playwright spec emits `runFixture(G-XX)` calls in `beforeEach`, runtime helper reads YAML.
6. **PR-F (separate)** — `/vg:fixture-prune` cleanup command (Q8).
7. **PR-G (separate, future)** — time-travel test-mode infrastructure (Q4).

Estimated 5-7 small PRs over 2-3 weeks once Q1-Q8 land.

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
