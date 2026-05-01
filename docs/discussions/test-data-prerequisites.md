# RFC v9 — Test-data prerequisites + workflow enforcement model

**Status (v9, 2026-05-02):** Final consolidated plan. Ready for implementation start (PR-pre-A bundled hotfix).
**Cross-AI review trail:**
- v4 reviewed by Codex GPT-5.5 + Claude Sonnet 4.6 → 5 HIGH findings baked in
- v7 reviewed by Codex GPT-5.5 effort=high → 3 HIGH + 6 MEDIUM concerns baked into v8 (D17-D23 tester pro lens)
- v9 = v8 + D24-D28 (legacy migration single-advisory, research-augmented blueprint, content depth validators, Diagnostic universal across BLOCK types, aggregate advisory)
**Surfaced by:** PrintwayV3 Phase 3.2 dogfood (2026-05-01)
**Related:** PR #79 (recovery paths + matrix-staleness wave-3.x), PR #74 (anti-performative-review)

---

## 1. The problem in one paragraph

`/vg:review` and `/vg:test` need realistic application **state** to verify mutation goals. Phase 3.2 G-10 "Admin approves tier2 topup" — sandbox seed has 12 tier1 rows + 0 tier2 rows. Scanner sees no Approve button (tier1 hidden), reports `no_submit_step` → SUSPECTED. Re-run mãi cũng vô ích — không có gì để click. 21/36 mutation goals dính lỗi này (~58%). Không phải lỗi code, không phải UI, không phải review. Lỗi **data prerequisite** — workflow chưa biết tự tạo state.

Plus a meta-bug: when validators fire BLOCK, workflow prints generic option menu thay vì advise straight. User loop through retry-failed → fix nothing → menu again. Workflow lacks **diagnostic intelligence + clear single advisory pattern**.

## 2. Concrete failure modes (Phase 3.2)

| Goal | Cần | Sandbox có | Result |
|---|---|---|---|
| G-10 admin approve tier2 topup | tier2 row pending | only tier1 | scanner thấy không nút Approve → SUSPECTED |
| G-19 merchant cancels withdraw | merchant pending withdraw | empty wallet | route render empty state → SUSPECTED |
| G-23 admin reset cooling | merchant cooling | no cooling state | reset button không hiện → SUSPECTED |
| G-31 transfer group CRUD | existing group | empty list | chỉ create test được → PARTIAL |
| G-34/35 linked/bank accounts CRUD | accounts exist | empty | edit/delete unreachable |
| G-44 admin sets FX rate | rate exist gateway×currency | inconsistent seed | sometimes editable |
| G-52 IMAP CRUD | configs exist | only one default | partial CRUD |

Pattern: **list/queue route healthy when empty, mutation goals (approve/reject/edit/delete/cancel) cần entity tồn tại trước, đúng status, đúng tier/role/state**.

## 3. Kinds of data goals need

1. **Trigger entity** — row action operates on (tier2 row to approve)
2. **Lifecycle state** — entity ở status cụ thể (cooling, pending withdraw)
3. **Cross-entity relationship** — A pointing to B (linked account → gateway)
4. **Time-driven state** — timestamp older than X (7-day deadline)
5. **Side-effect setup** — entity created by prior side-effect (chargeback freeze)
6. **Negative-path setup** — entity ở forbidden state (frozen recipient)

RFC v9 covers 1, 2, 3, 5, 6. Loại 4 (time-driven) deferred → parallel RFC G.

---

## 4. Direction chosen — 4 strategic decisions

> **Recipes authored at `/vg:build`, executed before `/vg:review` scanner spawn, reused by `/vg:test` codegen. No inline cleanup — sandbox accumulates; cleanup separate command. Single source-of-truth recipe artifact per mutation goal, public-framework grade.**

**S1.** Recipe authored at `/vg:build` (executor knows API shape)
**S2.** No inline cleanup, sandbox = "richer = easier"
**S3.** Single recipe runtime serves both `/vg:review` preflight và `/vg:test` codegen
**S4.** Public-framework grade — schema portable, runtime pluggable, no project-isms

---

## 5. Design decisions D1-D28

### D1 — Architecture: native Python orchestrator

**Decision:** Vgflow CLI = ~400-500 LOC Python orchestrator + 2 small libs (`requests`, `jsonpath-ng`). Subprocess gọi tools native. **No Docker primary, no MCP wrapper, no Karate/Schemathesis/Zerocode external runtime.**

**Auth pluggable, 3 layer:**
- Layer 1 declarative: cookie | bearer | api-key | oauth-client-credentials
- Layer 2 escape hatch: `auth.kind: command` → invoke `scripts/auth-plugin.sh` (no upstream PR)
- Layer 3 vendor-deep: project forks runner

**Token TTL refresh + auth_verify post-login** (closes Codex auth-silent-wrong-role concern).

**Split PR-A into A1/A2/A3** per Codex sizing review.

Optional Dockerfile alternative for Python-incompatible CI. Not primary.

### D2 — Recipe schema (FIXTURES/{G-XX}.yaml)

```yaml
schema_version: "1.0"                    # mandatory
goal: G-10
description: Admin approves tier2 topup — row must exist in pending tier2 state
fixture_intent:
  declared_in: TEST-GOALS.md#G-10
  validates: "tier2 row visible in admin queue"

# D13 concurrency/isolation
allocation:
  lease_id: "{run_id}"
  expires_at: "+30m"
  owner_session: "{session_id}"

steps:
  - id: create_tier2_topup
    kind: api_call
    role: merchant-owner
    method: POST
    endpoint: /api/v1/wallet/topup-requests
    idempotency_key: "VG_FIXTURE_{run_id}_{step.id}"
    body:
      amount: 0.01                       # D9 sandbox sentinel
      currency: USD
      gateway: sunrate
      reference: "VG_FIXTURE_{run_id}_{step.id}"
    side_effect_risk: money_like
    capture:
      request_id:
        path: $.id
        cardinality: scalar
        on_empty: fail
    validate_after:
      kind: api_call
      method: GET
      endpoint: /api/v1/admin/topup-requests/{request_id}
      assert_jsonpath:
        - { path: $.tier, equals: tier2 }

  - id: create_imap_configs
    kind: loop
    over: ["primary", "secondary", "fallback"]
    each:
      kind: api_call
      role: admin
      method: POST
      endpoint: /api/v1/admin/imap-configs
      idempotency_key: "VG_FIXTURE_{run_id}_imap_{loop.value}"
      body: { name: "{loop.value}", host: "test-{loop.index}.fixture.vgflow.test" }
    capture:
      config_ids: { path: $.id, from_each: true }

# D12 RCRURD lifecycle
lifecycle:
  pre_state:
    role: admin
    method: GET
    endpoint: /admin/topup-requests/{request_id}
    retry: { max_attempts: 3, delay_ms: 200, until_assertion_pass: true }
    assert_jsonpath:
      - { path: $.status, equals: pending }
      - { path: $.tier, equals: tier2 }
  
  action:
    surface: ui_click
    target: "Approve button on row {request_id}"
    expected_network:
      method: POST
      endpoint: /admin/topup-requests/{request_id}/approve
      status_range: [200, 299]
      target_selector_must_include: "{request_id}"
  
  post_state:
    role: admin
    method: GET
    endpoint: /admin/topup-requests/{request_id}
    retry: { max_attempts: 5, delay_ms: 300, until_assertion_pass: true }
    assert_jsonpath:
      - { path: $.status, equals: approved }
      - { path: $.approved_at, not_null: true }
  
  side_effects:
    - role: merchant-owner
      method: GET
      endpoint: /wallet/balance
      retry: { max_attempts: 5, delay_ms: 500, until_assertion_pass: true }
      assert_jsonpath:
        - { path: $.balance_usd, increased_by_at_least: 0.01 }
```

**Schema rules:**
- `endpoint` relative
- `role` lookup `vg.config.credentials[env]`
- `capture` JSONPath RFC 9535
- Interpolation: `{run_id}`, `{step.id}`, `{steps.<id>.<name>}`, `{role.email}`, `{loop.value}`, `{loop.index}`, `{session_id}`
- `run_id` mandate format: `{timestamp_ms}-{random_4hex}`
- `idempotency_key` mandatory cho POST/PUT
- `retry.until_assertion_pass` cho post_state/side_effects
- `target_selector_must_include` cho action (scanner click fixture ID)

### D3 — Multi-step failure: validate_after + orphan log

Step N fail → recipe overall fail → goal BLOCKED.
- `runs/G-XX.fixture-orphans.json` — orphan IDs for prune
- `runs/G-XX.fixture-error.json` — error context
- `validate_after` is primary mitigation against partial-orphan inconsistent state

### D4 — Time-travel goals: declare DEFERRED + parallel RFC G

Affected goals declare:
```markdown
**Requires time travel:** true
**Blocked since phase:** 3.2
**Time travel reason:** Need merchant với last_failed_withdraw_at < 1h ago
```

Matrix classify DEFERRED. Health check surface "blocked since X phases" as technical debt.

`RFC G: time-travel test infrastructure` open immediately design-only.

### D5 — `data_invariants` per-consumer (no count)

```yaml
data_invariants:
  - id: tier2_topup_pending
    resource: topup_requests
    where: { status: pending, tier: tier2 }
    consumers:
      - { goal: G-10, recipe: G-10, consume_semantics: destructive }
      - { goal: G-11, recipe: G-10, consume_semantics: destructive }
      - { goal: G-15, recipe: G-10, consume_semantics: read_only }
    isolation: per_consumer
```

Preflight algorithm: count `destructive` consumers, create N entities, key cache by `goal_id`.

### D6 — Codegen: runFixture() runtime call

```typescript
test.beforeEach(async ({ request, page }) => {
  await runFixture(request, page, 'G-10', { 
    semantics: 'isolated_per_test',
    schema_version: '1.0'
  });
});
```

`@vgflow/fixture-runtime` TS helper rejects unknown major schema_version. Cookie sync between APIRequestContext + Page.

### D7 — Preflight: per-consumer + cross-phase resolver + locks

Phase 2c-pre `verify-data-invariants`:
1. Read invariants from ENV-CONTRACT.md
2. Per invariant: count `destructive` consumers from matrix
3. Walk cross-phase dependency graph từ `.vg/API-INDEX.yaml`
4. Acquire D13 lock (file_lock or Redis advisory)
5. Query state, run owning recipe N times (with idempotency keys)
6. Verify entities exist before reuse cache
7. Store IDs keyed by `goal_id`
8. Release lock
9. Re-query. Still failed → BLOCK với actionable error

### D8 — `/vg:fixture-prune` 3-layer registry

```yaml
fixtures:
  entity_types:
    topup_requests: { tag_strategy: registry_first, reference_field: reference }
    ledger_entries: { tag_strategy: registry_only, retention_policy: keep_forever }
    transfer_groups: { tag_strategy: tag_field_first, tag_field: metadata.vgflow_fixture_run_id }
```

Layer 1 registry primary. Layer 2 reference field fallback. Layer 3 time window opt-in.

Manual trigger v1, dry-run mandatory first run, scoped role `vgflow-fixture-cleaner`.

### D9 — Sandbox safety guardrails

**Hard environment gate:**
1. `vg.config.environments.{env}.kind: sandbox`
2. Server confirms via `/health` returns `X-VGFlow-Sandbox: true`
3. Recipe steps with `side_effect_risk` ∈ {money_like, external_call, volume_change} blocked unless above 2 confirmed

**Graceful migration warn-mode:** projects mới chưa có header → warn 30 days, block sau grace period.

**Sentinel value validator:** amount ≤ 0.01, email `@fixture.vgflow.test`, reference `VG_FIXTURE_*`.

### D10 — Evidence provenance (structured)

```yaml
evidence:
  source: scanner | executor | orchestrator | diagnostic_l2 | manual
  artifact_hash: sha256:...
  scanner_run_id: haiku-G10-1714683724
  captured_at: 2026-05-02T10:30:00Z
  schema_version: "1.0"
  layer2_proposal_id: null
```

**Promotion rule:** SUSPECTED → READY chỉ khi ALL submit + 2xx steps `evidence.source: scanner`. Other sources informational.

Validator `verify-evidence-provenance.py`: BLOCKs review-complete if mutation step missing structured evidence.

### D11 — Diagnostic Layer 2 (UNIVERSAL across pipeline, hybrid approval)

**Activate cho TẤT CẢ Type B BLOCKs across pipeline** (not just /vg:review):

| BLOCK source | Type | Diagnostic? |
|---|---|---|
| /vg:review Haiku scanner fail | B | Yes (existing) |
| Layer 0 RCRURD lifecycle fail | B | Yes |
| D27 content depth fail | B | Yes |
| CrossAI council substance BLOCK | B | Yes |
| Cross-reference orphan (D23) | B | Yes |
| Build wave-verify content fail | B | Yes |
| Stop hook (missing artifact) | A | No, single advisory |
| Schema validator (field type wrong) | A | No, single advisory |
| Hash chain broken | A | No, hard error |
| T8 gate conflicts | C | No, /vg:reapply-patches |
| Legacy schema (D24) | C | No, single advisory |

**Validator output contract** (universal v9):
```yaml
verdict: BLOCK
block_type: A | B | C
validator: ...
artifact: ...
evidence:
  field: ...
  actual: ...
  expected: ...
recovery:
  single_advisory: "..."
  diagnostic_evidence_context: {...}    # for type B
  override_flag: "..."                   # for type C
```

**Hybrid approval flow:**
- Diagnostic parse evidence_context → articulate hypothesis tiếng người
- Propose fix với diff
- Auto-classify complexity:
  - ≤10 LOC, 1 file, no schema change → 1-click
  - >10 LOC, multi-file, schema/contract change → full review
- User: y / n / edit-then-y / skip
- y → apply, re-verify, commit `evidence.source: diagnostic_l2`
- Anti-cycle: 2 reject same class → bypass session

**Cost budget:**
```yaml
diagnostic_layer2:
  max_invocations_per_run: 10
  max_invocations_per_validator: 3
  max_total_cost_usd: 5.00
  on_budget_exhausted: skip_remaining
```

**Granular recovery routing:** `recovery_paths.py` key theo `(validator, evidence_class)`.

### D12 — RCRURD lifecycle Layer 0 automation

Sau Haiku scanner action, orchestrator chạy lifecycle assertion (D2 schema). Tất cả pass → READY automation, KHÔNG user gate.

```
Layer 0 (D12): RCRURD lifecycle (deterministic Python)
   ↓ fail
Layer 1: Auto-recovery (safe paths)
   ↓ fail
Layer 2 (D11): Diagnostic + hybrid user gate
   ↓ decline
Layer 3: Generic menu
```

**Eventual consistency handling:** `retry.until_assertion_pass` ở post_state + side_effects.

Build wave-verify validator `verify-fixture-lifecycle-completeness.py`: mutation goal phải có post_state + side_effects non-empty.

### D13 — Concurrency/isolation model

**3 layer:**
1. **Idempotency key per POST/PUT** (RFC 7240 `Idempotency-Key` header)
2. **Allocation lease per recipe** (lease_id + expires_at + owner_session)
3. **Lock backend** (file_lock single-machine, Redis/Postgres advisory team-shared)

**Scanner targets fixture ID** (không "first visible row") — `target_selector_must_include` mandatory.

### D14 — Schema versioning policy

- **Same major required** — runner refuses different major
- **Minor backward-compatible** — runner v1.2 reads v1.0
- **N-1 minor support 6 months** grace period
- **Unknown fields**: strict (default) fail | lenient warn-only

Migration tool `vgflow fixture migrate FIXTURES/G-10.yaml --target=2.0` ship khi major bump.

### D15 — Fixture security threat model

**Recipe content rules** (validator `verify-fixture-security.py` build-time):
- ❌ No secrets in YAML (regex scan: password|api_key|secret|token|bearer)
- ❌ No absolute URLs trong endpoint
- ❌ No external domains (configurable allowlist)
- ⚠️ Risky verbs (DELETE/DROP/TRUNCATE) require `risk_acknowledged: true`

**Auth log redaction:** Authorization/Cookie/X-API-Key headers redacted, secret regex bodies → `<REDACTED>`.

**Runtime safeguards:** subprocess no shell/eval, safe substitution, file path restricted to `runs/` and `.vg/`.

**Fixture entity ownership** (shared sandbox UI):
- Sentinel email `@fixture.vgflow.test` filterable
- Reference prefix `VG_FIXTURE_` excludable từ reports
- Optional: scoped sandbox tenant `vgflow_test`

### D16 — Multi-developer coordination + run report

**Per-session isolation:** session_id (timestamp + machine + user) interpolated vào reference/email/cache file.

**Lock backend** (D13 layer 3).

**Run report (NEW v7):**
```text
=== /vg:review 3.2 run report ===
Session: 1714683724-a3f2-dev-dzung
Duration: 4m 23s

Fixtures: Created 14, Reused 3, Failed 0, Orphaned 0
Cost: $1.40 (Layer 0/1 free; Layer 2: 3 invocations $0.30 + $0.50)

Recipes:
  G-10..G-52 — all PASS
  G-46 — Layer 2 fix proposed + 1-click approved
  G-20 — Layer 2 fix proposed + 1-click approved

Goals: 51 → 65 READY (12 unchanged, 14 newly verified)
SUSPECTED: 0
DEFERRED: 3 (G-22, G-42, G-58 — requires_time_travel)

Next: /vg:test 3.2
```

### D17 — Test Strategy artifact (NEW v8)

`TEST-STRATEGY.md` mới, generated ở blueprint sub-step 3a (trước PLAN/CONTRACTS/GOALS):

```markdown
# Test Strategy — Phase 3.2

## Test types in scope
- functional, api_contract, ui_ux, data_integrity, security
- (out: performance, exploratory deferred to /vg:roam)

## Risk assessment
- Domain: payment processing → HIGH risk
- New endpoints: 12 (auth boundary), 8 (mutation), 3 (read)
- Cross-phase dependency: P1 merchant + P2 wallet

## Coverage targets
- critical priority: 100% READY required
- important: ≥80%
- nice-to-have: ≥50%

## Exit criteria
- 0 BLOCKED + 0 UNREACHABLE
- ≤3 DEFERRED (with blocked_since_phase tracked)
- All defects severity≥major closed or deferred with justification

## Defect severity classification
- critical: production data loss, security breach
- major: feature broken, no workaround
- minor: cosmetic, workaround exists
- trivial: typo, polish
```

CrossAI council audit at blueprint complete.

### D18 — Test type classification per goal

TEST-GOALS.md schema:
```yaml
## Goal G-10
**Description:** Admin approves tier2 topup
**Test type:** functional + api_contract + ui_ux + data_integrity
**Priority:** critical
**Surface:** ui
**Mutation evidence:** POST .../approve trả 200, balance merchant tăng
**Required data:**                           # D19 merged here
  categories:
    - tier2 topup row in pending status
    - wallet exists for merchant
    - merchant active (not frozen)
  edge_cases:
    - amount = 0.01 (minimum boundary)
    - amount = 999.99 (large boundary)
    - merchant với prior failed topup
  boundaries:
    - currency mismatch (USD vs EUR)
    - timezone-sensitive timestamp
```

**Test types catalog:**
- `functional` — feature work as specified
- `api_contract` — request/response shape match contract
- `ui_ux` — visual + interaction flow
- `data_integrity` — DB state correct after action
- `security` — authz/authn boundary
- `performance` — latency / throughput
- `exploratory` — free-form discovery
- `regression` — existing feature unchanged

Validator `verify-test-types-coverage.py`: every mutation goal phải khai ≥1 test_type.

### D19 — Test Data Spec MERGED into TEST-GOALS (per user direction)

Merge as `required_data` field within each goal (above). NOT separate artifact. Reduces artifact count, keeps spec tied to goal context.

### D20 — Skipped (smoke/sanity stage) per user direction

Existing `--mode=full|delta|regression` đủ. No new modes added.

### D21 — Defect Log structured

`DEFECT-LOG.md` mới, persistent across phases:

```yaml
defects:
  - id: D-3.2-001
    severity: critical | major | minor | trivial
    found_in: phase 3.2 review session 1714683724
    found_by: scanner | layer2 | crossai | manual_uat
    title: Approve button shows on tier-1 row but BE rejects 422
    repro_steps: [...]
    expected: ...
    actual: ...
    related_goals: [G-10, G-11]
    status: open | in_progress | fixed | wontfix | duplicate
    fix_commit: 4eb1c0be
    retest_result: pass | fail | pending
```

REVIEW-FEEDBACK.md vẫn giữ as raw observation; DEFECT-LOG là processed/triaged.

### D22 — Test Summary Report formal

`TEST-SUMMARY-REPORT.md` template per phase, generate at /vg:test complete + /vg:accept entry. Audit-grade for stakeholders. Includes execution metadata, test type pass rate, defect summary, coverage, recommendations, artifacts trail.

### D23 — Bi-directional traceability

Forward: D-XX → G-XX → TS-XX → defect (existing).
**Backward (NEW):** TS-XX → G-XX → D-XX, defect → G-XX → D-XX (root cause traceback).

Validator `verify-rtm-bidirectional.py` build matrix automatically từ artifacts. Reports orphans (TS without G, G without D, defect without traceback). BLOCK build/review/test if orphan detected.

### D24 — Legacy phase migration: SINGLE-ADVISORY (NOT menu)

Auto-detect legacy schema at workflow entry of any /vg:* command:

```
⛔ Phase 3.2 schema pre-v9.

   Chạy:
     /vg:fixture-backfill 3.2

   Sau đó re-run lệnh này.

   Backfill cost: ~2-4 giờ user review one-time.
   Backfill enrich TEST-GOALS với test_type + edge_cases,
   sinh FIXTURES, populate API-INDEX, generate TEST-STRATEGY.

   Override (nếu thực sự muốn skip):
     /vg:review 3.2 --allow-legacy-skip-with-debt --reason="<text>"
     (logs OVERRIDE-DEBT, blocks ở /vg:accept)
```

**No AskUserQuestion 3 options.** Single recommendation, single override path.

`/vg:fixture-backfill <phase>` workflow:
1. Read TEST-GOALS + API-CONTRACTS + RUNTIME-MAP
2. Generate DRAFT fixtures (~70% from scanner-evidence, ~50% partial for SUSPECTED)
3. Dry-run validate (--no-mutate) before promote
4. Generate TEST-STRATEGY.md từ existing CONTEXT.md
5. Generate API-INDEX cross-phase resolve
6. CrossAI council review drafts
7. User accept/edit interactive
8. ONLY DRAFT-VALIDATED promotable

### D25 — Research-augmented blueprint (hybrid)

**Static pattern catalog primary** ship vgflow:
- `.vg/test-patterns/auth-edge-cases.md`
- `.vg/test-patterns/payment-edge-cases.md`
- `.vg/test-patterns/crud-edge-cases.md`
- `.vg/test-patterns/webhook-edge-cases.md`
- `.vg/test-patterns/{auth-jwt,csrf,idor,sql-injection,...}.md` (OWASP coverage)

**Internet research selective** (3 triggers):
1. Domain not in catalog (niche industry)
2. Goal references unfamiliar pattern
3. CrossAI council flag gap

Cache `.vg/research-cache/{domain-hash}.md` reuse across phases. CrossAI council quarterly audit catalog completeness.

### D26 — Single-recommendation advisory pattern

Khi workflow detect clear right answer, advise straight. Menu of alternatives ONLY hiện khi user explicit request `/vg:doctor recovery --show-alternatives`.

Apply across:
- D24 legacy migration (already)
- recovery_paths.py output (BACKPORT to wave-3 PR #79)
- Layer 2 Diagnostic format (already)

`recovery_paths.py` revised:
```python
def render_recovery_block(violation_type, command, phase, evidence_class=None):
    paths = get_recovery_paths(violation_type, command, phase, evidence_class)
    if not paths:
        return generic_fallback()
    
    recommended = paths[0]
    return f"""
⛔ {violation_type} BLOCK

Recommended:
  $ {recommended['command']}

Reason: {recommended['rationale']}

See alternatives: /vg:doctor recovery {phase} --show-alternatives
"""
```

### D27 — Content depth + quality validators

Force AI engage thật, không skim qua schema-pass-but-thin-content:

**a) Word count + specificity per field**
```yaml
description:
  type: string
  min_length: 30
  must_contain_oneof: ["{D-XX}", "{specific entity name}"]
```

**b) Cross-reference completeness**
- Every D-XX → ≥1 G-XX cite
- Every G-XX → ≥1 commit cite
- Every G-XX với mutation_evidence → ≥1 FIXTURES file
- Every G-XX → ≥1 TS-XX bind
- Every defect → trace back D-XX

`verify-cross-reference-completeness.py` orphan-detect.

**c) Edge case substance check**
- Min 3 entries cho critical priority
- Each must reference specific value/state (regex or explicit)
- Generic strings như "edge case 1" → fail

`verify-edge-case-substance.py`.

**d) LLM-as-judge isolated subagent**
Critical artifacts (TEST-STRATEGY, TEST-GOALS) → spawn separate Haiku judge:
- Score 1-10 completeness, specificity, domain-relevance
- < 7 → BLOCK với feedback

Cost: ~$0.30/judge × 2-3 critical artifacts = ~$1/blueprint.

**e) Instruction repetition gate (anti-skim)**
At blueprint entry: AI must paraphrase 3 most important constraints. Validator regex check non-generic. Generic → re-prompt.

### D28 — Aggregate advisory cho multi-Type-A BLOCKs

Khi multiple Type A BLOCKs cùng common root cause:

```
⛔ Multiple structural issues:
  - .vg/phases/3.2/TEST-STRATEGY.md missing
  - .vg/phases/3.2/FIXTURES/ empty
  - .vg/API-INDEX.yaml not created

Recommended (single command):
  /vg:fixture-backfill 3.2

Why: backfill generates all 3 in one run.
```

Aggregator detect common root cause across multiple structural BLOCKs → suggest unified action thay vì 3 single advisories overlap.

---

## 6. Layer architecture cho /vg:review BLOCK handler

```
BLOCK detected
   ↓
Layer 0 (D12): RCRURD lifecycle automation
  - Pre-state + action + post-state + side-effects
  - Deterministic Python, retries với exponential backoff
  - All pass → READY automation, NO user gate
  ↓ assertion fail
Layer 1: Safe auto-recovery (existing wave-3.1)
  - Override flags
  - Re-scan với scope khác
  - Log debt
  ↓ chưa giải quyết
Layer 2 (D11 universal): Diagnostic + hybrid user gate
  - AI parse evidence + articulate hypothesis
  - Granular recovery_paths theo (validator, evidence_class)
  - 1-click vs full review per complexity
  - Cost budget (max invocations + USD cap)
  - Anti-cycle guard
  - ACTIVE for ALL Type B BLOCKs across pipeline
  ↓ user decline hoặc complex
Layer 3: Generic menu (existing) + D26 single-advisory mode
```

---

## 7. Migration workflow map (post-backfill)

```
Legacy phase (pre-v9) — adopt v9 workflow:

Step 1: /vg:fixture-backfill <phase>
  → Enrich TEST-GOALS, generate FIXTURES + TEST-STRATEGY + API-INDEX
  → Cost: 2-4h user time (one-time per phase)
  → Code untouched

Step 2: /vg:review <phase>
  → Use enriched artifacts
  → Layer 0/1/2/3 stack
  → Surface code bugs (if any)

Step 3 (only if Step 2 surface bug): /vg:build <phase> --incremental
  → Apply Layer 2 proposed fix
  → Wave-verify
  → Cost: ~30min - 2h depending on bug

Step 4 (verify): /vg:review <phase> --retry-failed

Step 5: /vg:test <phase> + /vg:accept <phase> (existing)

NOT typically needed:
- /vg:blueprint <phase> (backfill replaces this for enrichment)
- /vg:build <phase> full re-build (existing code reused)
```

`/vg:next` smart routing post-backfill: auto-route tới /vg:review.

---

## 8. Tool inventory final

**Existing (giữ nguyên):**
- Haiku scanner agent + vg-haiku-scanner skill
- Playwright MCP (5 slots với lock manager)
- CrossAI CLIs: codex (gpt-5.5), gemini (gemini-3.1-pro-preview), claude (sonnet)

**New (RFC v9):**
- ~400-500 LOC Python orchestrator code
- 2 small Python deps: `requests`, `jsonpath-ng`
- Optional Dockerfile alternative
- New schemas: `fixture-recipe.schema.yaml`, `data-invariants.schema.yaml`
- New artifacts: `FIXTURES/`, `.vg/API-INDEX.yaml`, `.fixture-cache.json`, `TEST-STRATEGY.md`, `DEFECT-LOG.md`, `TEST-SUMMARY-REPORT.md`
- New validators (15+): provenance, lifecycle, data_invariants, build-fixtures-present, codegen-binding, backend-mutation, sandbox-safety, security, artifact-hash, lock-acquired, test-types-coverage, rtm-bidirectional, cross-reference, edge-case-substance, fixture-lock
- Pattern catalog `.vg/test-patterns/`
- Research cache `.vg/research-cache/`

**Borrow techniques (no dependency):**
- Stagehand DOM chunking → Haiku scanner
- GUI-ReWalk anti-loop → Haiku skill
- Schemathesis stateful-link pattern → schema reference
- OWASP / CVE catalog → pattern files

**Rejected:**
- ❌ Karate, Schemathesis, Zerocode external runtime
- ❌ Docker container as primary
- ❌ MCP wrapper for fixture services
- ❌ Browser Use / Stagehand / Skyvern as Haiku replacement

---

## 9. Implementation roadmap

### PR-pre-A: Foundation bundle (5-7 days) — STARTS NEXT

- D2 + D5 + D10 schemas
- D10 structured provenance contract
- `verify-evidence-provenance.py`
- Update `verify-matrix-staleness.py` bidirectional sync only on `evidence.source: scanner`
- Backfill `legacy_pre_provenance` mode
- Config gate: `provenance.enforcement: warn` initial → `block` next release
- Tests

### PR-A1: Schema parser + interpolation + JSONPath (3-4 days)
- Schema validation engine
- Variable interpolation
- JSONPath cardinality rules
- Loop step type
- Tests: golden + edge cases

### PR-A2: API execution + auth + sandbox safety (3-4 days)
- 4 declarative auth handlers + `kind: command` escape hatch
- Token TTL refresh + auth_verify
- D9 sandbox env gate
- Sentinel value validator

### PR-A3: Cache + orphans + concurrency (3-4 days)
- D13 idempotency keys
- Allocation lease
- Lock backend (file_lock primary)
- D15 security validator
- Atomic cache writes

### PR-A.5: Migration `/vg:fixture-backfill` (5-6 days)
- Read TEST-GOALS + API-CONTRACTS + RUNTIME-MAP
- Generate DRAFT fixtures + dry-run validate
- API-INDEX cross-phase resolve
- TEST-STRATEGY generate from CONTEXT
- CrossAI council review hook
- D24 single-advisory entry detection

### PR-B: `/vg:build` fixture-write step (1 week)
- Executor sub-step + wave-verify
- D12 lifecycle completeness check
- D14 schema_version mandatory
- Optional `vgflow fixture validate --dry-run --no-mutate`

### PR-C: ENV-CONTRACT data_invariants + preflight (1.5 weeks)
- N-consumer algorithm
- Cross-phase dep resolution
- Cycle detection
- Lock acquire/release wrapping
- Granular recovery_paths

### PR-D1: Scanner cache integration (3-4 days)
- Cache file contract
- vg-haiku-scanner skill update
- Scanner targets fixture ID

### PR-D2: Layer 0 RCRURD lifecycle gate (1 week)
- Deterministic Python check
- Retry với eventual consistency

### PR-D3: Layer 2 Diagnostic UX universal (1.5 weeks)
- AI hypothesis parser
- Hybrid 1-click vs full-review
- Cost budget enforcement
- Anti-cycle guard
- D11 universal across BLOCK types
- Validator output contract refactor

### PR-E: `/vg:test` codegen integration (1 week)
- Playwright codegen runFixture()
- @vgflow/fixture-runtime TS helper
- Schema-version compat check

### PR-Z (parallel PR-D): Backend mutation evidence validator (5-7 days)

### Pattern catalog seed (5-7 days, parallel anytime)
- `.vg/test-patterns/` 8-10 domain catalogs
- OWASP Top 10 + CWE-25 reference

### PR-content-depth: D27 validators (1 week)
- verify-edge-case-substance
- verify-cross-reference-completeness
- LLM-as-judge subagent
- Instruction repetition gate

### PR-tester-pro: D17/D18/D21/D22/D23 (1.5 weeks)
- TEST-STRATEGY artifact generation
- test_type field schema
- DEFECT-LOG.md structured
- TEST-SUMMARY-REPORT.md template
- RTM bi-directional validator

### PR-recovery-D26: Single-advisory backport (2-3 days)
- BACKPORT to PR #79 wave-3
- recovery_paths.py render only top recommended
- /vg:doctor recovery --show-alternatives flag

### PR-block-aggregator: D28 (2-3 days)
- Aggregate multi-Type-A BLOCKs
- Common root cause detection

### PR-research-augment: D25 (1.5 weeks)
- WebSearch/WebFetch integration
- Cache layer .vg/research-cache/
- 3 trigger conditions
- CrossAI catalog audit

### PR-F (followup): `/vg:fixture-prune` (1 week)
### PR-G (parallel design RFC): Time-travel infrastructure (1 week design only)
### PR-Y (followup): Recovery-paths-as-code test coverage (5 days)

---

## 10. Total estimate

**~10-13 weeks total** (D1-D28 + tester pro + content depth):

| Phase | Duration |
|---|---|
| PR-pre-A foundation | 5-7 days |
| PR-A1 + A2 + A3 + A.5 | 3 weeks |
| PR-B | 1 week |
| PR-C | 1.5 weeks |
| PR-D1 + D2 + D3 | 2-2.5 weeks |
| PR-E | 1 week |
| PR-Z parallel | 5-7 days |
| PR-content-depth | 1 week |
| PR-tester-pro | 1.5 weeks |
| PR-recovery-D26 backport | 2-3 days |
| PR-block-aggregator | 2-3 days |
| PR-research-augment | 1.5 weeks |
| Pattern catalog seed | 5-7 days |
| **Total** | **~10-13 weeks** |

PR-F + PR-G + PR-Y followups, open-ended.

---

## 11. Risk register (final)

| Risk | Severity | Mitigation |
|---|---|---|
| Backfill quality cho no_sequence goals | MEDIUM | DRAFT-NEEDS-HUMAN-REVIEW + dry-run validate |
| Layer 2 propose wrong fix | MEDIUM | Provenance D10 audit, cost budget, anti-cycle |
| Time-travel goals stuck DEFERRED | LOW | RFC G open immediately |
| Cross-phase entity prune destroys data | LOW | Auto-recreate via recipe |
| Concurrent /vg:review races | **HIGH** | D13 lock backend mandatory + per-session cache |
| Sandbox vs prod confusion | **HIGH** | D9 hard gate + grace migration |
| Wave-3.2.2 fake evidence forge | **HIGH** | D10 structured provenance, scanner-only promotion |
| Recipe YAML contains secrets | **HIGH** | D15 SECURITY validator |
| Eventual consistency false-fail | MEDIUM | D12 retry config |
| Schema breaking change orphans fixtures | MEDIUM | D14 versioning policy + migration tool |
| Auth `kind: command` wrong role | MEDIUM | D1 auth_verify |
| Fixture pollution shared sandbox | MEDIUM | D15 sentinel values + tenant scope |
| Multi-dev coordination | HIGH | D16 lock backend + isolation |
| Layer 2 cost runaway | MEDIUM | D11 cost budget |
| AI content skim despite passing schema | MEDIUM | D27 depth validators (5 sub-mechanisms) |
| Workflow loops menu options | HIGH | D26 single-advisory + D11 Diagnostic universal |
| PR rollback if pre-A bad | MEDIUM | Config gates + warn-mode rollout |

---

## 12. Enforcement model per skill (NEW v9)

19 layer enforcement to minimize AI skim:

### Skill MD frontmatter
- `runtime_contract`: must_write, must_touch_markers, must_emit_telemetry
- `argument-hint`: flag whitelist
- `profile` attribute: which steps required per profile

### Skill body
- `<step>` blocks ordered, profile-filtered
- Each step entry: validator preflight gates
- Each step body: AI work + schema validator + D27 depth check
- Each step exit: marker + telemetry event
- Cross-step: CrossAI council at gate, RTM cross-ref

### Pre-commit hook
- Citation D-XX/API-CONTRACTS required
- --no-verify forbidden

### Stop hook (vg-verify-claim.py)
- Verify all must_write artifacts present
- Verify all markers touched
- Verify all telemetry emitted
- Validate hash-chain integrity
- BLOCK với recovery path nếu gap

### Block type taxonomy (D11 v9)
- Type A: structural BLOCK → single advisory (D26)
- Type B: semantic BLOCK → Diagnostic Layer 2 (D11)
- Type C: process BLOCK → specific recovery + override (D24)

### D27 content depth layers
1. Word count + specificity per field
2. Cross-reference completeness
3. Edge case substance check
4. LLM-as-judge isolated subagent
5. Instruction repetition gate

**Honest limit:** ~5-10% AI semantic skim irreducible. Last backstop = human UAT at /vg:accept.

---

## 13. Cost analysis per phase cycle

| Step | Cost |
|---|---|
| /vg:blueprint (artifacts + CrossAI council) | $5-6 |
| /vg:build (implement + FIXTURES) | $7-12 |
| /vg:review (Haiku scan + Layer 2 + CrossAI) | $5-8 |
| /vg:test (codegen + run) | $2-3 |
| /vg:accept | $0.50 |
| **Total per phase cycle** | **~$20-30** |

So với current (no v9): Phase 3.2 đã loop 2 sessions stuck = ~$10-15 wasted + frustration. v9 spend $20-30 mà converge → value positive.

Migration backfill one-time: ~2-4h user time per legacy phase.

---

## 14. Out of scope

- Production data — never. Sandbox only.
- Performance/load testing fixtures
- Visual regression baselines (separate L4 layer wave-3.x)
- Migration test data (schema-verify profile)
- Time-travel infrastructure (RFC G separate)
- Sandbox database snapshot mechanics (project deploy pipeline)
- Manual tester workflow (vgflow autonomous)

---

## 15. Appendix — Rejected options (final)

- ❌ Build YAML runner from scratch → use Python orchestrator + libs
- ❌ Karate / Schemathesis / Zerocode external runtime → over-engineered
- ❌ Docker container as primary → native install simpler
- ❌ MCP wrapper for fixture services → direct subprocess sufficient
- ❌ Browser Use / Stagehand / Skyvern as Haiku replacement → pipeline integration deep
- ❌ Build-time fixture smoke-execute → user vetoed (project may not have sandbox)
- ❌ Inline fixture cleanup transactional rollback → external /vg:fixture-prune
- ❌ AskUserQuestion 3-options menu → single advisory + override flag
- ❌ Test Data Spec separate artifact → MERGE into TEST-GOALS required_data
- ❌ Smoke / Sanity stage → existing --mode=full|delta|regression sufficient

---

## End of RFC v9

This is the final consolidated plan. Implementation starts with PR-pre-A (foundation bundle).

Cross-AI iterations: v3 (initial) → v4 (Codex+Claude HIGH findings) → v7 (Codex effort=high) → v8 (tester pro lens) → v9 (Diagnostic universal + content depth + single-advisory).

Total decisions: D1-D28 + 4 strategic.
Total enforcement layers: 19 + D27 5 sub-mechanisms.
Total estimate: 10-13 weeks.
