# Discussion: Test-data prerequisites for review/test workflow

**Status:** RFC — discussion only, no code yet
**Surfaced by:** PrintwayV3 Phase 3.2 dogfood (2026-05-01) on wave-3.2.x dogfood run
**Related:** PR #79 (recovery paths + matrix-staleness), PR #74 (anti-performative-review)

## The problem in one paragraph

`/vg:review` and `/vg:test` need realistic application **state** to verify mutation goals. Phase 3.2 G-10 says "Admin approves tier2 topup request"; sandbox seed has 12 tier1 rows and 0 tier2 rows. Scanner navigates to `/billing/topup-queue`, sees only tier1 rows showing "Auto via webhook" placeholder, can't click an Approve button that doesn't exist for tier1, and reports `no_submit_step`. The matrix-staleness validator correctly flags SUSPECTED. But the **root cause is missing data**, not missing UI or missing code. We can re-run scanners forever without ever creating the data they need to exercise.

This is the meta-bug behind ~21 of the 36 mutation goals flagged in the dogfood run: not "scanner missed it" but "nothing to scan because the trigger entity doesn't exist in seed".

## Concrete failure modes observed in Phase 3.2

| Goal | Needs | Sandbox has | Result |
|---|---|---|---|
| G-10 admin approve tier2 topup | tier2 topup row in `pending` | only tier1 rows | scanner sees no Approve button → SUSPECTED |
| G-19 merchant cancels pending withdraw | merchant has pending withdraw | empty wallet, no withdraws | route renders empty state → SUSPECTED |
| G-20 admin approve withdraw | admin sees withdraw queue with rows | (TypeError on the route, separate bug) | unrelated infra fail |
| G-23 admin resets cooling period | merchant currently cooling | no cooling-period state | reset button never appears → SUSPECTED |
| G-31 admin transfer group CRUD | existing transfer group OR new-group flow | empty list, no groups | only "create" path testable, edit/delete dead → partial submit only |
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

## Six options for the discussion

### Option A: Data factories baked into seed.ts

**Idea:** Extend `apps/api/src/modules/auth/seed/sampleUsers.seed.ts` (and add similar for other modules) so the sandbox seed creates ONE of every interesting state combination — 1 tier1 topup row in pending, 1 tier2 in pending, 1 approved, 1 rejected, 1 flagged; 1 merchant in cooling period; 1 frozen wallet; etc.

Pros:
- Simple, runs once at deploy
- Deterministic, scanner just reads what's there
- Easy to debug ("why is row X like this? grep seed.ts")

Cons:
- Seed file balloons (one row per state × tier × role × edge case → hundreds of records)
- Time-driven states still hard (a "1 hour ago" row needs the seed to backdate timestamps)
- Cross-entity relationships fragile (delete one row → cascades break)
- Test pollution: side-effects from other tests mutate seed; G-11 reject in this dogfood run rejected one of the 12 tier1 rows, leaving 11 — next run sees inconsistent state

Verdict: works for static reference data, fails for dynamic/lifecycle states.

### Option B: Per-goal `**Required data:**` field in TEST-GOALS.md

**Idea:** Each mutation goal declares the data it needs as a setup recipe in TEST-GOALS.md frontmatter or body section:

```markdown
## Goal G-10: Admin approve tier2 topup request

**Surface:** ui
**Required data:**
  - kind: api_call
    description: Create a pending tier2 topup as merchant
    role: merchant-owner
    method: POST
    endpoint: /api/v1/wallet/topup-requests
    body: { amount: 100, currency: "USD", gateway: "sunrate", reference: "test-G-10-{run_id}" }
    capture: { request_id: "$.id" }
**Cleanup:**
  - kind: api_call
    description: Revert via admin reject (so re-runs don't accumulate)
    role: admin
    method: POST
    endpoint: /api/v1/admin/topup-requests/{request_id}/reject
    body: { reason: "test cleanup", internal_note: "G-10 cleanup" }
```

Before the Haiku scanner spawns for that goal, orchestrator runs the recipe → captures IDs → injects into Haiku prompt as `EXPECTED_ROW_ID=...`. After scanner completes, cleanup recipe runs.

Pros:
- Explicit, traceable, version-controlled with the goal
- Goal-scoped — no global seed bloat
- Cleanup keeps sandbox clean across runs
- Recipes can chain (G-23 cooling period needs G-22 first)

Cons:
- One more authoring burden per goal
- Recipes need a runtime to execute (curl harness or thin Python lib)
- Cross-goal dependencies (graph) must be tracked
- If recipe is wrong, you get "scanner failed" but root cause is in TEST-GOALS

Verdict: most explicit; aligns with how /vg:test will eventually want recipes for codegen anyway.

### Option C: Persona-based data wallets

**Idea:** Define a small set of "personas" with prebuilt complete state — `merchant-cooling`, `merchant-frozen-wallet`, `admin-with-pending-tier2-queue`. Each persona is a seed package. Test goals declare which persona's state they need.

```yaml
personas:
  admin-tier2-queue:
    description: Admin role, sandbox has ≥1 pending tier2 topup, ≥1 approved, ≥1 rejected
    setup: scripts/personas/admin-tier2-queue.sh
    used_by: [G-10, G-11, G-12]

  merchant-cooling:
    description: Merchant currently in cooling period, with prior failed withdraw
    setup: scripts/personas/merchant-cooling.sh
    used_by: [G-22, G-23]
```

Goals reference persona by name; setup runs once per persona per session.

Pros:
- Reusable across goals
- Mirrors real user states ("a merchant who is cooling")
- Lower per-goal authoring burden than B
- Can be hand-crafted realistic scenarios, not just minimum data

Cons:
- Personas overlap and conflict (admin-tier2-queue creates rows; merchant-cooling deletes them?)
- Order matters — running personas in wrong sequence breaks state
- Not goal-scoped — debugging "which persona broke G-10" indirect

Verdict: good middle ground; closer to how QA teams actually structure test environments.

### Option D: Just-in-time data generation via scanner self-help

**Idea:** Haiku scanner detects "empty state I need to test" (no tier2 rows on /billing/topup-queue), spawns a sub-helper agent that creates the missing row via API as the right role, then continues. No setup recipe declared — scanner figures it out from goal text.

Pros:
- Zero setup overhead per goal
- Scanner handles new goals without recipe maintenance
- Works for unanticipated states

Cons:
- Scanner needs to know API endpoints — couples scanner to API contract knowledge
- Non-deterministic: "Haiku decided to call POST /topup with these fields" — hard to reproduce failure
- No cleanup — sandbox accumulates trash across runs
- LLM creativity = correctness risk (scanner POSTs wrong fields → 422 → flags fake bug)

Verdict: too clever; loses determinism. Reserve for prototype-only paths.

### Option E: Time-travel + fake-clock test mode

**Idea:** Backend exposes a "test-mode time advance" header (`X-Test-Time: 2026-05-08T00:00:00Z`) only when `NODE_ENV=sandbox` (and never in prod). Scanner sets the header to push virtual clock past 7-day deadlines, cooling periods, etc.

Pros:
- Solves the time-driven state problem (G-22, G-42, G-58) elegantly
- No data setup overhead — just rewinds clock
- Real production code paths exercised

Cons:
- Backend has to support fake clocks everywhere (cron jobs, scheduled tasks, retry queues)
- Sandbox-only header risk — if it leaks to prod, time bombs
- Doesn't help for non-time states (frozen wallet, tier2 queue)

Verdict: orthogonal complement to A/B/C, not a replacement. Probably needed eventually, but separate.

### Option F: ENV-CONTRACT.md declares data invariants

**Idea:** Each phase declares in `ENV-CONTRACT.md` what data invariants the sandbox must maintain:

```yaml
data_invariants:
  topup_requests:
    - status: pending, tier: tier2, count: ">=1"
    - status: pending, tier: tier1, count: ">=1"
  withdraws:
    - status: pending, role: merchant-owner, count: ">=1"
  merchants:
    - cooling_period_active: true, count: ">=1"
```

Before review starts, a verifier checks these invariants against the running sandbox. If any miss → emit a clear error: "Data invariant 'topup pending tier2 ≥1' not met. Run: `pnpm seed:fixture topup-tier2-pending`". A separate `pnpm seed:fixture` script library (one fixture per invariant gap) lets dev or CI fill the gap.

Pros:
- Pre-flight gate, fails fast with actionable error
- Decouples "what data must exist" (declared) from "how to create it" (fixture script)
- Goal authors don't write API recipes; they declare data shape
- Fixtures composable, reusable across phases

Cons:
- Two artifacts to maintain (invariants + fixtures) instead of one
- "Run pnpm seed:fixture X" still manual unless wired into deploy

Verdict: closest to how mature QA frameworks work. Invariants are declarative; fixtures are procedural.

## Recommended direction (pre-discussion strawman)

**Hybrid A + F + opt-in B**, in that order of priority:

1. **Baseline (A)** — extend seed.ts to cover the static reference set per phase: 1 row per status × tier combination at minimum. Solves ~50% of cases for low cost.

2. **Phase-level invariants (F)** — every phase declares `data_invariants` block in ENV-CONTRACT.md. `/vg:review` pre-flight verifies them before spawning Haiku. If invariant miss → BLOCK with "run fixture X" hint, not silent SUSPECTED. This is the gate that prevents the "scanner ran but had nothing to test" failure.

3. **Goal-level recipes (B) for stateful goals only** — opt-in per goal where the static seed cannot represent the state (cooling period, frozen wallet, recently-failed payment). Recipe runs as preflight to that one goal's scanner spawn, with cleanup after.

Time-travel (E) deferred to a separate RFC when we hit a goal that genuinely needs it.

Persona model (C) deferred — not needed yet at our scale; revisit when we have 10+ phases sharing setup.

Just-in-time (D) rejected — too non-deterministic for a verification harness.

## Open questions for discussion

1. **Where does the fixture script library live?** `scripts/fixtures/` per project? Or in vgflow as a generic harness with project-supplied recipes?
2. **Is "ENV-CONTRACT.md data_invariants" a new section or replaces CRUD-SURFACES.md `state_matrix`?** They overlap.
3. **Cleanup contract:** if a goal's setup creates a row, is cleanup MUST or SHOULD? What happens when scanner crashes mid-test?
4. **Idempotency:** if `/vg:review --retry-failed` re-runs a goal whose previous setup row still exists from last run — skip, replace, or fail?
5. **Who writes recipes?** Goal author at `/vg:blueprint` time, or executor at `/vg:build` time? Different incentives — author knows intent, executor knows implementation.
6. **Backend test-mode boundary:** if we go (E) time-travel later, what's the contract for sandbox-only test endpoints? `X-Sandbox-*` header pattern? Allow-list of test-only routes?
7. **Cost concern:** option B/F adds a recipe-runtime per goal scanner spawn. For Phase 3.2's 36 mutation goals × 1 setup + 1 cleanup = 72 extra API calls per `/vg:review` run. Acceptable?
8. **Scope creep:** does this RFC also cover `/vg:test` codegen (fixture-aware Playwright tests) or just `/vg:review` scanner runs?

## What this RFC does NOT cover

- Production data — never. Sandbox only.
- Performance testing fixtures (different shape — 100K rows, not 1 row per state).
- Visual regression baselines (separate concern).
- Migration test data (handled by schema-verify profile).

## Next step

Discuss the strawman + open questions, pick a direction, then split into implementation PRs (likely 3-4 small ones across vgflow + PrintwayV3).
