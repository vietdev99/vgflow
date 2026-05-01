# RFC: Test-data prerequisites for review/test workflow

**Status (v4, 2026-05-02):** Direction + decisions D1-D10 chosen, cross-AI reviewed (Codex GPT-5.5 + Claude Sonnet 4.6), 5 HIGH findings baked in, ready to bundle with wave-3.2.3 hotfix and split into implementation PRs.
**Surfaced by:** PrintwayV3 Phase 3.2 dogfood (2026-05-01) on wave-3.2.x dogfood run
**Cross-AI review:** see [`test-data-prerequisites-crossai-review.md`](test-data-prerequisites-crossai-review.md) for full synthesis
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

### D1 (was Q3) — Runtime: generic Python runner, declarative auth + escape hatch + Docker

Vgflow ships `scripts/run-fixture.py` (Python 3.11+) that reads recipe YAML, performs HTTP calls, captures responses. Also ships `Dockerfile` so JS-only / Python-less CI environments can run it as a container — solves "stack pollution" objection.

**Auth pluggability — three layers, declarative-first:**

```yaml
# Layer 1: declarative (covers ~80% — built into runner)
auth:
  kind: cookie | bearer | api-key | oauth-client-credentials
  login_endpoint: /api/v1/auth/login
  body_template:
    email: "{role.email}"
    password: "{role.password}"
  capture:
    cookie: connect.sid
    # or: token_path: $.token
  # NEW: token lifecycle (Claude review — solves mid-recipe 401 on JWT expiry)
  token_ttl_hint_seconds: 900           # optional, runner re-auths when TTL < 10%
  refresh_endpoint: /api/v1/auth/refresh # optional

# Layer 2: command escape hatch (covers exotic stacks — SAML/mTLS/HMAC/MFA)
auth:
  kind: command
  run: scripts/auth-plugin.sh           # local plugin, NOT upstream PR
  expected_output: json                 # must return {"headers": {...}, "cookies": [...]}
  refresh_run: scripts/auth-plugin.sh --refresh   # optional

# Layer 3: vendor-deep (only if both above don't fit)
# Project forks runner. Tracked as adoption signal — drives roadmap.
```

**Rationale (revised after cross-AI review):**
- Codex flagged 4 declarative kinds insufficient for SAML/mTLS/MFA/HMAC at framework scale → escape hatch added
- Claude flagged auth escape via upstream PR blocks fast adoption → local plugin path (project's own `scripts/auth-plugin.sh`)
- Claude flagged JWT mid-recipe expiry silent failure → `token_ttl_hint_seconds` + auto-refresh logic
- Claude flagged Python-only runner blocks JS shops → Dockerfile shipped from PR-A

**Rejected:**
- Project-side runner (duplicates code, defeats framework)
- Python entrypoint plugins (couples language)

### D2 (was Q1) — Recipe schema (cross-AI revisions baked in)

```yaml
schema_version: "1.0"                    # NEW: mandatory; runner rejects unknown majors
goal: G-10
description: Admin approves tier2 topup — row must exist in pending tier2 state
fixture_intent:                          # NEW: cross-ref to TEST-GOALS.md mutation_evidence
  declared_in: TEST-GOALS.md#G-10
  validates: "tier2 topup row visible in admin queue, approve button shown"

steps:
  - id: create_tier2_topup
    kind: api_call
    role: merchant-owner                 # lookup into vg.config.credentials[env]
    method: POST
    endpoint: /api/v1/wallet/topup-requests
    body:
      amount: 0.01                       # NEW: must use sandbox-safe sentinel (D9)
      currency: USD
      gateway: sunrate
      reference: "VG_FIXTURE_{run_id}_{step.id}"   # NEW: standardized prefix (D8)
    side_effect_risk: money_like         # NEW: gate via D9 sandbox safety
    capture:
      request_id:
        path: $.id                        # JSONPath (RFC 9535)
        cardinality: scalar               # NEW: scalar | array | optional_scalar
        on_empty: fail                    # NEW: fail | skip | null
    validate_after:                       # NEW: read-only assertion (Claude review)
      kind: api_call
      method: GET
      endpoint: /api/v1/admin/topup-requests/{request_id}
      expect_status: 200
      assert_jsonpath:
        - path: $.tier
          equals: tier2
        - path: $.status
          equals: pending

  # NEW: loop step type (Claude review — covers CRUD goals like G-52 IMAP)
  - id: create_imap_configs
    kind: loop
    over: ["primary", "secondary", "fallback"]   # or: count: 3
    each:
      kind: api_call
      role: admin
      method: POST
      endpoint: /api/v1/admin/imap-configs
      body:
        name: "{loop.value}"
        host: "test-{loop.index}.fixture.vgflow.test"
    capture:
      config_ids:
        path: $.id
        from_each: true                   # NEW: collect into array

expects:
  capture_into:
    EXPECTED_ROW_ID: "{steps.create_tier2_topup.request_id}"
```

**Decisions baked in (with cross-AI revisions):**
- `schema_version` **mandatory** at top. Runner rejects recipes whose major version it doesn't support. Hard error, not silent. Closes Codex+Claude convergent concern about schema evolution.
- `endpoint`: **relative**, runner resolves `api_base` from `vg.config.environments.{env}.api_base`.
- `role`: string lookup into `vg.config.credentials[env]`.
- `capture` cardinality rules (Claude review):
  - `scalar` — exactly 1 match required (`on_empty: fail` default)
  - `array` — collect all matches (zero matches OK if `on_empty: skip`)
  - `optional_scalar` — 0 or 1 match, null if 0
- `kind: loop` step type (Claude review) — `over: [...]` for explicit values OR `count: N` for indexed; capture supports `from_each: true` to collect array.
- `body` template variables: `{run_id}`, `{step.id}`, `{steps.<id>.<name>}`, `{role.email}`, `{loop.value}`, `{loop.index}` — minimal interpolation, documented set, no templating engine.
- `validate_after` block (Claude review) — read-only assertion runs after step. Catches partial-orphan inconsistent state at recipe time, not at scanner time. Optional but recommended for multi-step recipes.
- `fixture_intent` block (Codex review) — cross-references TEST-GOALS.md `mutation_evidence` declaration. Separate validator can compare blueprint intent vs fixture reality.
- `side_effect_risk: money_like | volume_change | external_call | none` — gates via D9 sandbox safety. Runner refuses risky steps on non-sandbox envs.
- `reference` field is **standardized**: `VG_FIXTURE_{run_id}_{step.id}`. Becomes basis for D8 tag-based prune.
- `run_id` format: **mandatory** `{timestamp_ms}-{random_4hex}` (e.g. `1714683724891-a3f2`). Closes Claude's concurrency concern.
- `.fixture-cache.json` writes are **atomic** (write tmp + rename) OR per-run files `.fixture-cache-{run_id}.json`. Closes Claude's concurrent-runs race.
- Auth tokens: handled by runtime per D1 (not in recipe).

**Rejected alternatives:** absolute URLs (breaks portability), typed role enums (premature), jq syntax (tool dep), in-recipe secrets (security smell), unbounded templating engine (Jinja-class — feature creep).

### D3 (was Q2) — Multi-step failure: no rollback, validate-after + orphan log

Step N fails → recipe overall fails → goal marked BLOCKED in matrix with reason `fixture step N/M failed: <error>`. Steps 1..N-1 already executed leave their entities behind (per Decision 2 "no cleanup").

**Cross-AI addition (Claude review):** orphans alone are insufficient. Inconsistent partial state can satisfy invariant queries → false-pass at preflight → scanner finds broken row → unexplained SUSPECTED. Mitigation: `validate_after` block on each step (D2) acts as a checkpoint. If validate_after fails, recipe fails AT that step with a clear "step N produced invalid state" error, not "step N+1 timed out and we don't know why."

**Concrete output on partial failure:**
- `runs/G-{XX}.fixture-orphans.json`: IDs captured before failure
- `runs/G-{XX}.fixture-error.json`: error context — which step failed, why, validate_after assertion that triggered if any
- Goal status: BLOCKED with reason linking to error file
- Recovery path: `/vg:doctor recovery` shows "fix recipe step N, re-run /vg:review --retry-failed"

**Rationale:** transactional rollback per entity type is engineering cost we don't justify for sandbox-disposable model. validate_after + orphan log + error context cover the diagnostic gap at ~50 lines runner code total.

### D4 (was Q4) — Time-driven goals deferred to parallel RFC (open immediately)

Goals requiring backdated timestamps or fast-forward (cooling period, 7-day chargeback deadline, BullMQ retry-attempt-N) are NOT solved by recipes in v1. They need backend cooperation (test-only headers, sandbox-only env detection) — separate multi-week design.

**Cross-AI revision (Codex):** open the time-travel RFC **immediately as design-only**, not "after first non-3.2 phase blocks." Both reviewers flagged that 8% won't stay constant — billing/fraud/SLA/lifecycle workflows accumulate time-driven goals. After 5 phases possibly 15-20% DEFERRED. Designing in parallel (even if implementation ships later) lets time-travel goal authors know what's coming.

**For now:** affected goals declare `requires_time_travel: true` in TEST-GOALS frontmatter. Matrix classifies as **DEFERRED** with cross-AI revision: also carry `blocked_since_phase: 3.2` field (Claude review) so health checks can surface long-DEFERRED goals as technical debt.

```markdown
## Goal G-22: Withdraw cooling period blocks new request
**Surface:** ui
**Requires time travel:** true
**Blocked since phase:** 3.2
**Time travel reason:** Need merchant with last_failed_withdraw_at < 1h ago
```

**Affected from Phase 3.2 dogfood:** G-22, G-42, G-58 — 3 of 36 (~8%). Expected to grow.

**Follow-up:** open `RFC: time-travel test infrastructure` **as part of this RFC bundle**, design-only, separate document. Implementation tracked as PR-G with no firm date.

### D5 (was Q5) — `data_invariants` schema (REVISED for N-consumer + cycle detection)

**Major revision after both reviewers flagged D7 non-convergence.** Original "≥1 row" semantics fails when N goals each consume one trigger entity. Now: invariants declare per-consumer entity creation, not per-invariant.

```yaml
# In ENV-CONTRACT.md
data_invariants:
  - id: tier2_topup_pending
    resource: topup_requests
    where:
      status: pending
      tier: tier2
    consumers:                           # NEW: list of goals that NEED a row
      - goal: G-10
        recipe: G-10                     # owning recipe
        consume_semantics: destructive   # NEW: scanner mutation removes the row
      - goal: G-11
        recipe: G-10                     # inherits same recipe template
        consume_semantics: destructive
      - goal: G-15                       # hypothetical edit goal
        recipe: G-10
        consume_semantics: read_only     # scanner mutates but doesn't remove from query
    isolation: per_consumer              # NEW: per_consumer | shared_when_read_only
    # Preflight rule: count consumers with consume_semantics=destructive,
    # create that many entities. Each entity ID stored separately keyed by goal.

  - id: linked_account_exists
    resource: linked_accounts
    where: { status: active }
    consumers:
      - goal: G-34
        recipe: G-34
        consume_semantics: read_only     # scanner reads but doesn't delete
    isolation: shared_when_read_only     # 1 entity, all read-only consumers share
```

**Decisions baked in (CROSS-AI REVISIONS — D7 algorithm fix):**
- `consumers` block lists every goal that depends on this invariant + each goal's consume semantics
- `consume_semantics`: `destructive` (scanner mutation removes/transitions entity) | `read_only` (scanner observes only)
- `isolation`: `per_consumer` (preflight creates N entities, each goal gets unique ID) | `shared_when_read_only` (one entity, multiple read-only consumers share)
- Preflight algorithm: count `destructive` consumers in matrix, create that many entities, store each in `.fixture-cache.json` keyed by `G-XX` (not by invariant)
- Inheritance with cycle detection: runner walks `recipe` chain, detects cycles via DFS visited-set, fails build if depth > 5 OR cycle found
- Diamond inheritance: same-owner = OK (dedup), different-owner = build error
- `where` is conjunction-only (AND). OR → separate invariants.
- `count` removed from schema — implicit from `len(consumers)`. Hard-coded counts were the source of the non-convergence bug.

**Rationale:** Both reviewers independently flagged "1 row for N consumers" as a correctness bug. Original D5 had `count: ">=1"` semantics that satisfied invariant query but starved sequential scanners. Now: invariant declares its consumers, preflight creates entities per-consumer, scanner cache is per-goal, ping-pong eliminated by construction.

**Side benefit:** `consume_semantics` annotation makes the matrix self-documenting — anyone reading ENV-CONTRACT.md sees which goals destroy state vs only observe.

### D6 (was Q6) — Codegen emits `runFixture()` runtime call + semantics field

`/vg:test` Playwright codegen emits:

```typescript
test.beforeEach(async ({ request, page }) => {
  await runFixture(request, page, 'G-10', { semantics: 'isolated' });
});
```

`runFixture` is a TS helper (~30 LOC) shipped with vgflow as `@vgflow/fixture-runtime` (or vendor-copied at PR-E time). Reads YAML, makes HTTP calls, returns capture map.

**Cross-AI revision (Claude review):** review and test have different protocol semantics (review = once-per-phase shared state, test = once-per-test isolated state). Hiding both in one schema makes "no drift" superficially true but structurally fragile. Solution: explicit `semantics` field on `runFixture` call OR top-level `consumer_modes` block in recipe YAML acknowledging both modes.

```yaml
# Recipe declares which semantics it supports
consumer_modes:
  review:
    semantics: shared
    cache_key: G-10
  test:
    semantics: isolated_per_test
    cache_key: "{test_uuid}"
```

**Cross-AI revision (Claude review) — Playwright context:** `runFixture(request, page, ...)` accepts both APIRequestContext (for HTTP calls) AND Page (for cookie sync). Helper auto-syncs cookies between contexts when fixture login sets cookies that test must use. Avoids silent auth-context-mismatch bug.

**Cross-AI revision (Codex+Claude convergent) — schema versioning:**
- `schema_version: "1.0"` in every YAML (already mandated in D2)
- `runFixture` rejects YAML whose major version it doesn't support — hard error with clear message
- Vendor-copied runtime + vgflow schema bump = clear failure, not silent drift

**Rationale:** option (a) transpile-to-inline-TS = drift waiting to happen. Option (b) keeps YAML single source of truth. Trade-off accepted: specs depend on runtime helper + YAML files. Vendor folder OK because schema_version + runtime version both pinned.

### D7 (was Q7) — Preflight runs once, creates entities per-consumer (REVISED)

**Major revision after both reviewers flagged non-convergence ping-pong.** Original "≥1 row" preflight + `--retry-failed` loop was claimed to converge "in 1-2 iterations." Both reviewers proved it doesn't converge when 2+ retry-set goals share a destructive trigger entity (G-10 + G-15 example, A2 in cross-AI synthesis).

Phase 2c-pre adds `verify-data-invariants` step (revised algorithm):

1. Read all `data_invariants` from ENV-CONTRACT.md
2. For each invariant: count `destructive` consumers from `consumers[]` block (D5)
3. Query sandbox state for current matching entity count
4. If `(destructive_consumer_count - matching_count) > 0`: run owning recipe N times, where N = the gap. Each run captures a fresh ID.
5. Store IDs in `.fixture-cache.json` keyed by **goal_id**, not invariant_id:
   ```json
   {
     "G-10": { "EXPECTED_ROW_ID": "abc123", "created_at": "2026-05-02T..." },
     "G-11": { "EXPECTED_ROW_ID": "def456", "created_at": "2026-05-02T..." },
     "G-15": { "EXPECTED_ROW_ID": "ghi789", "created_at": "2026-05-02T..." }
   }
   ```
6. Re-query invariant. If still failed (rare — recipe broken or auth wrong): BLOCK with actionable error.

Each Haiku scanner reads cache for **its own goal's** EXPECTED_ROW_ID. No more "all scanners share one row."

**Concurrent-runs safety (Claude review):** preflight writes cache atomically (tmp file + rename) OR per-run files `.fixture-cache-{run_id}.json`. Either approach prevents last-writer-wins races between two `/vg:review` processes.

**No re-check before each scanner spawn.** Per-consumer entities mean prior scanner mutations don't invalidate later scanners — each has its own. Convergence guaranteed by construction, not by retry loop.

**Rationale:** original D7 was correct in spirit (preflight-once is right architecture) but wrong in algorithm (1 row for N consumers). Per-consumer creation is cost-equivalent (preflight N HTTP calls instead of 1) but algorithmically convergent.

**Order matters:** invariant gap = BLOCK at preflight, not silent SUSPECTED later. This is what prevents the "scanner ran but had nothing to test" failure that started this RFC.

### D8 (was Q8) — `/vg:fixture-prune` spec (REVISED — registry-first, tag-second)

**Major revision after both reviewers flagged "tag-based assumes metadata column."** Many real schemas (ledger rows, immutable audit, join tables, external payment objects) cannot accept arbitrary `vgflow_fixture_run_id` field. Original D8 baked an assumption that breaks adoption.

**Three-layer prune mechanism (in priority order):**

```yaml
# In vg.config.md
fixtures:
  entity_types:
    topup_requests:
      tag_strategy: registry_first       # registry → reference_field → time_window
      reference_field: reference         # field name in this entity type
      time_window_field: created_at      # for fallback

    ledger_entries:
      tag_strategy: registry_only        # immutable, can't tag
      # only deletable via registry lookup; if registry lost, never deletable
      retention_policy: keep_forever

    transfer_groups:
      tag_strategy: tag_field_first      # entity supports metadata
      tag_field: metadata.vgflow_fixture_run_id
```

**Layer 1 — Registry (primary):** `runs/fixture-registry.jsonl` accumulates one line per fixture-created entity:
```json
{"resource":"topup_requests","id":"abc123","run_id":"1714683724891-a3f2","created_at":"...","goal":"G-10"}
```
Prune reads registry, deletes entries by `run_id` age + reference pattern match.

**Layer 2 — Reference field (fallback):** if entity has standardized `reference: VG_FIXTURE_{run_id}_{step.id}` (mandated in D2), prune queries `WHERE reference LIKE 'VG_FIXTURE_%' AND created_at > N days ago`. Used when registry lost or for entity types without metadata support.

**Layer 3 — Time window (last resort):** for entity types that have neither metadata nor reference field, prune deletes by time window only. Requires explicit `tag_strategy: time_window_only` opt-in per entity type — high-blast-radius, ops must approve.

**Other contracts (preserved from v3):**
- Manual trigger v1, no cron
- Default age threshold 7 days, configurable
- Scoped role `vgflow-fixture-cleaner` with hard-delete privilege limited to tagged entities only
- Reads `runs/G-{XX}.fixture-orphans.json` (from D3) for partial-failure cleanup

**Cross-AI addition:** prune dry-run mode (`/vg:fixture-prune --dry-run`) prints what WOULD be deleted before doing it. Mandatory first run on new env, optional after.

**Follow-up:** full `RFC: vg:fixture-prune cleanup command` after D1-D7 ship. v4 RFC commits to the registry-first contract so PR-A doesn't bake wrong tagging assumptions.

### D9 (NEW) — Sandbox safety guardrails (closes "fixture creates real money" risk)

Cross-AI both flagged HIGH: Phase 3.2 is BILLING. Fixture POST creates real wallet balance, gateway webhooks fire externally, reconciliation reports see fixture amounts. RFC v3 had no coverage. v4 commits to:

**Hard environment gate (runner refuses unless ALL pass):**
1. `vg.config.environments.{env}.kind` must be `sandbox` (not `local|staging|prod`)
2. Server must respond to health probe with header `X-VGFlow-Sandbox: true` (project adds this to sandbox deploy; absent on prod)
3. Recipe steps with `side_effect_risk` ∈ `{money_like, external_call}` blocked unless `kind: sandbox` + `X-VGFlow-Sandbox` header confirmed

**Sentinel value requirements (validator at recipe schema time):**
- Currency-amount fields must use sandbox-safe values: `amount ≤ 0.01` for any field whose name matches `amount|balance|price|fee|cost`
- Email fields must use domain `@fixture.vgflow.test`
- `reference` field must start with `VG_FIXTURE_` (already standardized in D2)
- Names should include `[FIXTURE]` prefix (warn-level, not block)

**Example block in recipe:**
```yaml
steps:
  - id: create_tier2_topup
    kind: api_call
    role: merchant-owner
    method: POST
    endpoint: /api/v1/wallet/topup-requests
    body:
      amount: 0.01                       # sentinel — would be flagged if 100
      currency: USD
      gateway: sunrate
      reference: "VG_FIXTURE_{run_id}_{step.id}"   # mandatory prefix
    side_effect_risk: money_like         # gates D9 sandbox check
```

**Build-time validator** `verify-fixture-sandbox-safety.py`:
- Walks every `FIXTURES/G-XX.yaml`
- Reports schema-violations: amount > 0.01 in money fields, email domain != fixture.vgflow.test, missing reference prefix
- Severity: BLOCK (build wave fails)

**Runtime gate** in runner:
- Refuses execution unless env kind + sandbox header both confirm
- Refuses any `side_effect_risk: money_like` step on env without confirmed sandbox status
- Logs every refusal to telemetry (`fixture.refused_unsafe_env`) so user gets clear "I'm not running on prod" feedback

**Rationale:** "richer = easier" was right for sandbox volume but wrong for safety. Hard gates + sentinel values let projects opt into sandbox-only fixtures with confidence the runner won't accidentally pollute prod.

### D10 (NEW) — Evidence provenance (closes wave-3.2.2 hotfix gap, bundled with this RFC)

Cross-AI both flagged HIGH: wave-3.2.2 bidirectional sync (currently shipped in PR #79) promotes SUSPECTED → READY when goal_sequence has `submit + 2xx`. Goal_sequence JSON is writable by executor agents, scanner agents, and orchestrator code. Executor can hand-write fake submit + 2xx → auto-promote → trust model has back door.

**Fix bundled into this RFC** (was originally going to be standalone wave-3.2.3):

Add `evidence_source` field to every step in `goal_sequence`:
```json
{
  "do": "click",
  "target": "Approve button",
  "evidence_source": "scanner",          // NEW
  "scanner_run_id": "haiku-G10-1714683724",  // NEW
  "captured_at": "2026-05-02T...",       // NEW (already partial)
  "network": [...]
}
```

**Allowed values for `evidence_source`:**
- `scanner` — Haiku scanner spawned by `/vg:review` Phase 2b-2 wrote this
- `executor` — `/vg:build` executor wrote this (informational only — never triggers status change)
- `orchestrator` — orchestrator code path (preflight, recovery, smoke) wrote this
- `manual` — user/AI hand-edited (explicitly informational, never triggers)

**Promotion rule (revised wave-3.2.2 logic):**
- SUSPECTED → READY ONLY when ALL submit + 2xx steps in goal_sequence have `evidence_source: scanner`
- Mixed-provenance sequences (some scanner, some executor) → READY downgraded to PARTIAL or stays SUSPECTED
- Hand-written fake → never promotes, even if structurally valid

**Validator** `verify-evidence-provenance.py`:
- Walks every goal_sequence
- Asserts every mutation step has `evidence_source` field
- Asserts `scanner` claims have matching `scanner_run_id` that exists in events.db
- BLOCKs review-complete if any submit step has unverified provenance

**Migration path:**
- Existing goal_sequences from PR #79 era lack the field — backfill validator marks them `evidence_source: legacy_pre_provenance`, treats as informational only
- Dogfood phases (3.2 specifically) re-run scanner for proper attribution
- New goal_sequences MUST carry `evidence_source` from PR-A onward

**Why bundle into this RFC, not separate hotfix:**
- PR-A's fixture runtime writes goal_sequence steps with `evidence_source: orchestrator`
- Without provenance field defined, PR-A's writes would be indistinguishable from scanner output
- Bundling avoids "PR-A inherits broken trust model, then PR-B fixes it" sequence

**Implementation:** ships in same PR as RFC v4 schema definitions (PR-pre-A). Lands BEFORE PR-A.

---

## Out of scope (explicit non-goals)

- Production data — never. Sandbox only.
- Performance testing fixtures (different shape — 100K rows, not 1 row per state).
- Visual regression baselines (separate concern).
- Migration test data (handled by schema-verify profile).
- Time-travel infrastructure (deferred to separate RFC per Q4).
- Sandbox reset / database snapshot mechanics — outside vgflow's responsibility, project's deploy pipeline handles.

---

## Implementation plan (revised after cross-AI review)

D1-D10 resolved. Splits into PRs in dependency order, with PR-pre-A bundle landing first:

### PR-pre-A: Foundation bundle — schema + provenance hotfix + sandbox safety contract
**Lands before PR-A. Bundles wave-3.2.3 hotfix per user direction "revise RFC trước rồi gộp."**

- `schemas/fixture-recipe.schema.yaml` (JSON-Schema for D2 — full schema spec, no runtime yet)
- `schemas/data-invariants.schema.yaml` (JSON-Schema for D5)
- `verify-evidence-provenance.py` validator (D10) — adds `evidence_source` field requirement to goal_sequence steps
- Update `verify-matrix-staleness.py` (PR #79 wave-3.2.2) — bidirectional sync only triggers on `evidence_source: scanner`
- Backfill mode: legacy goal_sequences without provenance marked `legacy_pre_provenance`, never auto-promote
- **No runner code yet** — schema + provenance contract only
- **Tests:** schema validation + provenance contract + legacy backfill behavior

This closes the wave-3.2.2 trust model hole live in PR #79 BEFORE PR-A's runner inherits it.

### PR-A: Recipe runner + auth + sandbox safety enforcement (D1, D2, D3, D9)
- `scripts/run-fixture.py` — reads YAML, walks `steps[]`, captures via JSONPath with cardinality rules (scalar/array/optional_scalar)
- 4 declarative auth-kind handlers: cookie, bearer, api-key, oauth-client-credentials
- `kind: command` escape hatch handler — invokes local plugin (`scripts/auth-plugin.sh` per project)
- Token refresh logic: track `token_ttl_hint_seconds`, re-auth when TTL < 10%
- `kind: loop` step type with `over: [...]` and `count: N` semantics
- `validate_after` block execution — read-only assertion after each step
- Orphan logger writes `runs/G-{XX}.fixture-orphans.json` on partial failure
- **Sandbox safety enforcement:**
  - Refuses execution unless `vg.config.environments.{env}.kind: sandbox`
  - Refuses unless server responds with `X-VGFlow-Sandbox: true`
  - Refuses `side_effect_risk: money_like|external_call` steps on non-sandbox
  - Sentinel-value validator at schema parse time
- `Dockerfile` for runner — universal portability layer
- **Mock consumer (Codex+Claude review):** `test/mock-scanner-consumer.py` reads `.fixture-cache.json` and validates contract that PR-D will rely on. Acts as contract test.
- **Tests:** unit (schema, JSONPath, interpolation, auth, capture), integration (fake HTTP app), sandbox safety enforcement

### PR-B: `/vg:build` fixture-write step + smoke-execute gate (D2 authoring)
- Executor sub-step: after implementing goal with `mutation_evidence`, write `FIXTURES/{G-XX}.yaml`
- Wave-verify validator: `verify-build-fixtures-present.py` — build incomplete if mutation goal lacks fixture YAML
- **Smoke-execute gate (Claude review):** wave-verify also runs `run-fixture.py` against sandbox at build time. Catches semantic errors (wrong endpoint, wrong payload shape) immediately at build, not 3 PRs later at preflight. Adds ~30s/goal.
- `requires_time_travel: true` recognition — skip fixture requirement, mark DEFERRED in matrix with `blocked_since_phase`

### PR-C: ENV-CONTRACT.md `data_invariants` + preflight verifier (D5, D7)
- Schema for `data_invariants` with `consumers[]` block + `consume_semantics` per consumer
- `verify-data-invariants.py`:
  - Reads `data_invariants` from ENV-CONTRACT.md
  - Counts destructive consumers per invariant from matrix
  - Queries current state, runs owning recipe N times to fill gap
  - Stores per-goal entries in `.fixture-cache.json` (atomic write or per-run file)
  - Hooks into `phase2c_pre_dispatch_gates` step
- Inheritance cycle detection (DFS visited-set) + diamond resolution
- Recovery paths in `recovery_paths.py` extended with `validator:data-invariants` entries

### PR-D: `/vg:review` scanner integration (D5, D7 consumer side)
**Split per Codex review — scanner skill changes are non-trivial:**
- **PR-D.1:** Cache file contract + prompt injection plumbing (orchestrator side)
- **PR-D.2:** Haiku scanner skill changes — read `.fixture-cache.json`, inject `EXPECTED_ROW_ID` env var into scanner prompt
- Matrix-staleness validator gets `requires_time_travel` filter
- Recovery paths extended with fixture-failure entries

### PR-E: `/vg:test` codegen integration (D6)
- Playwright codegen emits `await runFixture(request, page, 'G-XX', { semantics: 'isolated' })`
- `@vgflow/fixture-runtime` TS helper (~30 LOC + auth context sync)
- Schema-version compatibility check at runtime — hard fail on major mismatch
- Validator: `verify-codegen-fixture-binding.py`

### PR-Z: Backend staleness validator (Codex review — addresses backend goals exempt from D2 scope)
**Parallel to wave-3.2.1 surface filter. Currently backend goals "trusted" — Codex flagged need parallel validator.**
- `verify-backend-mutation-evidence.py` — for goals with `surface: api|data|integration|time-driven`
- Asserts: route handler hit (grep), mutation request observed (server log), 2xx/expected-error status, state changed (DB query)
- Closes the gap where backend mutations claimed READY without verification

### PR-F (followup, after D1-E ship): `/vg:fixture-prune` (D8)
- Registry-first + reference-pattern + time-window fallback (3-layer)
- `vg.config.fixtures.entity_types[]` per-entity-type strategy mapping
- Dry-run mode mandatory first run
- Scoped role `vgflow-fixture-cleaner`

### PR-G (parallel design RFC, immediate per Codex): time-travel infrastructure (D4)
**Open as RFC alongside this one, design-only.** Both reviewers flagged 8% won't stay constant.
- Backend test-only header contract (`X-Sandbox-Time-Advance`)
- Sandbox-only env detection enforcement
- Recipe extension: `kind: time_advance` step type
- Implementation deferred until first non-Phase-3.2 phase blocks

### PR-Y (separate, recovery-paths-as-code per Codex): recovery command test coverage
**Codex flagged: recovery commands rot into cargo-cult without tests.**
- Each entry in `recovery_paths.py` gets a fixture asserting the command actually changes the violation state, OR explicitly marks itself manual-only
- Runs as part of CI

**Sequencing rationale (revised):**
- PR-pre-A first — closes live PR #79 hole + ships schemas without runtime, so reviewers see contract intent
- PR-A is the foundation — runner standalone with mock consumer + Dockerfile + sandbox safety
- PR-B adds upstream producer (build writes YAML, smoke-executes immediately)
- PR-C adds downstream consumer (preflight reads YAML, creates per-consumer entities)
- PR-D wires preflight into review scanner spawn (split D.1 + D.2)
- PR-E extends to test layer with semantics field
- PR-Z parallel to PR-D (backend validator)
- PR-F + PR-G + PR-Y are independent follow-ups

**Revised estimate (Claude review caught optimism):**
- PR-pre-A: 3-5 days (schemas + provenance hotfix + tests)
- PR-A: 1.5-2 weeks (full runner + auth + sandbox safety + Docker + tests + mock consumer)
- PR-B: 1 week (executor sub-step + smoke-execute gate)
- PR-C: 1 week (preflight verifier + cache file + recovery paths)
- PR-D.1 + D.2: 1.5 weeks (scanner skill changes are architecture-invasive)
- PR-E: 1 week (codegen + TS helper + validator)
- PR-Z: 5-7 days (parallel to PR-D)

**Total: 5-7 weeks for D1-D10 implementation.** PR-F + PR-G + PR-Y open-ended follow-ups.

Honest revision from RFC v3's "2-3 weeks" — that estimate ignored scanner skill modification + sandbox safety + provenance hotfix scope. Claude's "5-7 weeks" projection accepted as realistic.

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
