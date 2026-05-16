# Feature-Chain Coverage — Out of Scope

Documents intentional deferrals from B62-B64. Reviewer audit (ID-7,
ID-8, ID-10) flagged gaps that we acknowledge but defer to future
batches. Listed here so reviewers/users know what's NOT covered.

## Deferred to B65+

### Multi-tenant cross-view visibility (audit ID-7)

**Gap:** Scanner runs as one role/tenant. Entity created by tenant-A
visible only in tenant-A's dashboard is INVISIBLE to a single-role
scan. Cross-tenant cascade goals will not be auto-generated.

**Workaround:** Multi-tenant projects must manually declare
`goal_class: feature_chain` goals + populate `chain_steps[]` with
explicit tenant-A and tenant-B actors. Mark with comment
`# tenant_isolation: manual` so reviewers don't mistake it for
auto-generated.

**B65 candidate:** Extend scanner with `tenant_context: [{role, label}]`
loop — for each tenant role, run cross-view nav + record per-tenant
observations. Adds ~5min/phase per tenant; budget gate required.

### Async / delayed propagation (audit ID-7)

**Gap:** Webhook → notification → audit-log chains propagate after
delay (seconds to minutes). Scanner navigates immediately
post-mutation — misses delayed effects.

**Workaround:** For phases with webhook/notification flows, declare
`goal_class: webhook` (existing) + add `chain_steps[]` with
`expected_state: notification_arrived_after_delay` markers. Test
codegen will emit `await page.waitForResponse(...)` patterns.

**B65 candidate:** Add `delayed_observations[]` field to scanner
schema. Re-poll target view after configurable delay (default 5s,
10s, 30s). Emit `G-AUTO-{entity}-async-{src}-to-{tgt}` goals.

### Real-prompt dogfood smoke test (audit ID-8)

**Gap:** B64 integration tests use synthetic fixture
(`tests/fixtures/feature_chain/`). The actual AI emitting via
contracts-delegation.md prompt may produce shallow chains because
prompt engineering surface is what actually drives drift. Synthetic
fixture passes != real AI passes.

**Workaround:** B64 includes a smoke test against a captured
CRUD-SURFACES.md fixture (snapshot of real project). Asserts emitted
goals contain valid feature_chain. NOT same as live AI dogfood.

**B65 candidate:** Add `/vg:dogfood` command that spawns real
contracts-delegation prompt against a frozen project snapshot, then
runs validators. Adds ~3min/CI run; gate to nightly.

## Won't fix (intentional)

### Waiver registry vs override-debt (audit ID-10)

**Decision:** `feature_chain_waiver[<resource>]: <reason>` lives in
CONTEXT.md, logged to override-debt.md via existing
vg:_shared:override-debt skill. NO new registry script. Existing
infrastructure handles audit + alerting (override count thresholds).

If waiver abuse becomes a problem (>20% of CRUD resources waived
across multiple phases), the override-debt gate already fires and
review must explain. Adding a separate registry duplicates that
mechanism.

### chain_consumes_state / chain_produces_state namespacing (audit ID-11)

**Decision:** Named `chain_*` prefix (B62 frontmatter) to avoid
collision with potential FLOW-SPEC state-machine fields. Forward
compatible.

## Acknowledged limitations

### CRUD-SURFACES resource detection coverage

`verify-feature-chain-coverage.py` parses CRUD-SURFACES.md flat
format + CRUD-SURFACES/ split directory. Schema is Batch 33-derived.
If a phase uses a different CRUD schema (e.g. handwritten), validator
may not detect resources → false PASS. Mitigation: ensure phases
generate CRUD-SURFACES via blueprint contracts-delegation (standard
path).

### Validator coverage heuristic

Resource→goal matching uses: (1) substring match on goal id, (2)
fallback substring match in TEST-GOALS body. Optimistic. If a phase
has multiple resources with overlapping names (e.g. `site` and
`site_member`), the validator may credit one goal to both. Mitigation
(future): add explicit `covers_resource: [<name>]` frontmatter on
feature_chain goals.

## Cross-references

- Phase 0 audit: `dev-phases/feature-chain-design/CODEX-AUDIT.md`
- Plan: `~/.claude/plans/snappy-brewing-wall.md`
- B62-pre BLOCKER fixes: commit d378bed (v4.51.1)
- B62 implementation: this batch
- B63 scanner cross-view: next batch
- B64 integration smoke: final batch
