# Codex Audit — Feature-Chain Plan B62-B64

**Date:** 2026-05-16
**Auditor:** codex adversarial tier (proxied via opus-4.7 reviewer; codex CLI 9router 404)
**Verdict:** PASS-WITH-NOTES — 2 BLOCKERs, 5 MAJORs, 4 MINORs. Plan is sound directionally but two concrete schema/pipeline mismatches will silently no-op B62 if not fixed first.

---

## Critical findings (BLOCKER)

### ID-1 [BLOCKER]: `goal_class` is not the dispatch key for stage selection — B62 stage injection will silently no-op
`scripts/generate-lifecycle-specs.py` line 64 `_stages_for_goal(goal)` dispatches on `goal.get("goal_type")`, NOT `goal_class`. The plan says: "*when `goal_class == feature_chain`, emit RCRURDR stages + new `visibility_check` stage*" (lines 896-930 patch). But the existing pipeline at lines 64-88 never reads `goal_class`. If B62 only adds `feature_chain` to the enum in `TEST-GOAL-enriched-template.md` line 111 (which is the `goal_class` enum, NOT `goal_type`), then `_stages_for_goal` falls into the `gtype` empty branch and infers RCRURDR from HTTP-verb evidence — completely bypassing the chain_steps[]-aware staging.

**Concrete failure:** AI emits `goal_class: feature_chain` with `chain_steps[S1..S8]`. Pipeline reads `goal_type` (which AI may legitimately leave as `mutation` or empty since contracts-delegation.md line 246 says "set `goal_type` or `goal_class`"). `_stages_for_goal` returns default RCRURDR. The new `visibility_check` stage is never emitted. LIFECYCLE-SPECS.json has the right title but the wrong staging.

**Mitigation (must do BEFORE B62 coding):**
1. Either (a) extend `GOAL_TYPE_STAGES` dict in `generate-lifecycle-specs.py` line 50-61 to add `"feature-chain": FEATURE_CHAIN_STAGES` AND have `_stages_for_goal` read BOTH `goal_class` and `goal_type` (precedence: `goal_class` wins for `feature_chain`); OR (b) collapse the two fields — deprecate `goal_class` and migrate the enum to `goal_type`. Decision must be documented in dev-phases plan before coding.
2. Add a unit test that asserts `_stages_for_goal({"goal_class": "feature_chain"})` returns stages containing `visibility_check`.

### ID-2 [BLOCKER]: `enables[]` semantics undefined for orchestrator-side dedup / cycle detection — FLOW-SPEC walker will loop or double-count
`contracts-overview.md` lines 549-602 already does a DFS over `Dependencies:` (backward edges) with cycle protection via `visited` list. Plan says "extend Dependencies[] traversal to ALSO follow `enables[]` downstream." But `enables[]` is a forward edge; if AI populates `enables[G-12]` on G-05 AND `Dependencies: [G-05]` on G-12 (semantically identical), the walker will double-traverse the same edge in two directions and either (a) emit duplicate chains or (b) confuse the dedup at line 599 (`key = tuple(chain[:2])` which assumes single direction).

**Concrete failure:** Phase has G-01 → G-02 → G-03 chain. AI emits `Dependencies: [G-01]` on G-02 AND `enables: [G-02]` on G-01 (both true). FLOW-SPEC walker finds chain twice; the second pass with reversed-direction edges may build [G-01, G-02, G-03] AND [G-03, G-02, G-01]. Dedup key `(G-01, G-02)` vs `(G-03, G-02)` are different → both saved → FLOW-SPEC.md generated with two copies of the same logical flow.

**Mitigation (must do BEFORE B62 coding):**
1. Specify a single-direction normalization step: before walker runs, dedupe edges so `enables[]` and `Dependencies[]` represent the SAME directed graph. Recommended: treat `Dependencies[]` as canonical (already widely used); `enables[]` is only consumed by `verify-feature-chain-coverage.py` to assert "for each `enables[G-X]` claim, there exists a goal G-X with `Dependencies` containing this goal".
2. Add `verify-enables-deps-symmetry.py` validator (one of the 12 B62 tests) that BLOCKS if `A.enables = [B]` but `B.Dependencies` doesn't include A. Without symmetry enforcement the two truth sources will drift within 2-3 phases.

---

## Major concerns (FIX-BEFORE-MERGE)

### ID-3 [MAJOR]: Validator threshold `chain_steps ≥ 4` is too low; AI will pad with no-op steps to bypass
The plan says `verify-feature-chain-coverage.py` enforces chain_steps ≥4 + distinct expected_state per step + target_view differs from source_view. Counterexample: AI emits 4 steps where S1=open list view, S2=open create form, S3=fill form, S4=submit. `expected_state` distinct ✓. `target_view` differs (list → form) ✓. But this is the OLD shallow goal pattern — no actual *downstream cascade* observed. The validator passes but the user pain ("click button → modal opens → done") is NOT fixed.

**Mitigation:**
1. Raise `min_steps[feature_chain]` to 8 (already in plan — good) AND require at least one step where `target_view` is NOT in `[source_view, source_view_modal, source_view_form]`. I.e. the chain MUST traverse to a structurally different view (dashboard, sibling list, audit log).
2. Validator MUST check `chain_steps[i].downstream_effects[]` is non-empty for at least 2 steps. If all `downstream_effects: []`, the chain is shallow → BLOCK.

### ID-4 [MAJOR]: Cross-view scanner cost is unbounded in worst case — 50 mutations × N=3 = 150 navigations × 10s budget = 25 minutes per phase
Plan defaults `VG_CROSS_VIEW_N=3` with 10s budget per probe. Worst case phase has 50 mutations (B2B billing phases have hit this); cost = 150 cross-view navigations × ~6s actual avg = 15min added to scanner runtime. Compounds with existing Persistence Probe cost (lines 322-329 SKILL.md sub-steps A-F already cost ~8s each).

**Mitigation:**
1. Cap TOTAL cross-view nav budget per phase at 60s (env `VG_CROSS_VIEW_TOTAL_BUDGET_S`); over budget → WARN + skip remaining (not BLOCK).
2. Dedupe by `(entity_slug, target_view)` — if scanner already observed "site → dashboard" propagation for entity-A, skip for entity-B unless entity-B has different schema family. Heuristic key: first segment of entity slug (`sites`, `users`, `orders`).
3. Make cross-view scan opt-in per phase via `scanner-overrides.yaml: cross_view_scan: enabled|disabled|sample`. Default `sample` (only scan top-3 highest-priority CREATE mutations).

### ID-5 [MAJOR]: UPDATE/DELETE cross-view cascade entirely missing from plan
Plan focuses on "CREATE → list-visibility" only. But user pain explicitly says "*từ khi có data sẽ lại sinh ra cả 1 núi tính năng khác*" — after data EXISTS, more features unlock. DELETE has its own cascade (archive count++, audit-log entry, dependent records orphaned). UPDATE has its own (status flip propagates to dashboard summary cards, badge counts). The plan ignores these entirely.

**Mitigation:**
1. Scanner schema `cross_view_propagation_observations[]` MUST include `action` ∈ {`create`, `update`, `delete`} — already in plan, GOOD. But the enrichment in `enrich-test-goals.py` only emits `G-AUTO-{entity}-visibility-...` (create-shaped). Extend to also emit `G-AUTO-{entity}-archive-{source}-to-{target}` for DELETE and `G-AUTO-{entity}-status-cascade-{source}-to-{target}` for UPDATE.
2. Validator `verify-cross-view-coverage.py` must check ALL three actions per CRUD endpoint set, not just CREATE.

### ID-6 [MAJOR]: Idempotent goal-id `(entity + source_view + target_view)` drifts on view rename
Plan note 6 (idempotency) calls this out as a "concern". It IS a concrete bug. If user renames `/sites` to `/properties` mid-phase, all `G-AUTO-sites-visibility-sites-to-dashboard` goals reroll to `G-AUTO-properties-visibility-properties-to-dashboard`. Old goal IDs orphan in TEST-GOALS.md → bind to dead tests via TS-XX markers (template line 64). Tests stay green but verify nothing.

**Mitigation:**
1. Goal-id should derive from `(entity_canonical_id, target_view_class)` NOT from view path. `target_view_class` ∈ {`primary_list`, `dashboard_summary`, `audit_log`, `sibling_list`} from a small enumerated set. View rename changes the path but not the class.
2. Add migration: `vg:migrate-state` step that detects goal-id drift via SHA of normalized inputs and emits a rename map.

### ID-7 [MAJOR]: Multi-tenant + async cascade scenarios unaddressed; will produce false negatives in production phases
Scanner navigates as one role/tenant. Cross-tenant visibility cascade (entity created by tenant-A appears only in tenant-A's dashboard) is INVISIBLE to a single-role scan. Same for webhook→notification→audit-log chains that propagate after delay (scanner navigates immediately).

**Mitigation:**
1. Document this as a known gap in the scanner SKILL.md cross_view section. Add `cross_view_propagation_observations[].limitations: ["single_role_scan", "no_delayed_propagation"]` so downstream enrichment can flag affected goals with `coverage_note: partial`.
2. Defer multi-tenant + async to B65 (explicit out-of-scope for B62-B64). Acceptable for now if documented; NOT acceptable to ship without acknowledgement.

---

## Minor concerns (note + proceed)

### ID-8 [MINOR]: Synthetic-fixture-only acceptance — no real-prompt dogfood
User explicitly excluded real-project dogfood. Risk: synthetic fixtures in `tests/fixtures/feature_chain/` pass because they hand-craft compliant input. The real AI emitting via contracts-delegation.md prompt may still produce shallow chains because the prompt-engineering surface is what actually drives drift. Recommend adding ONE smoke test that calls the actual prompt-rendering pipeline against a captured CRUD-SURFACES.md fixture and asserts that emitted goals contain `goal_class: feature_chain` with ≥1 valid chain.

### ID-9 [MINOR]: Legacy phase regression mode unspecified — VG_TRACEABILITY_MODE pattern not extended
Template line 71-72 shows precedent: pre-2026-05-01 phases run validators in WARN mode via `VG_TRACEABILITY_MODE=warn`. Plan does NOT specify analogous `VG_FEATURE_CHAIN_MODE=warn|block` env override for pre-B62 phases. Without it, re-running review on legacy phases will BLOCK on missing chain goals. Add the env var + document the cutoff date.

### ID-10 [MINOR]: `feature_chain_waiver` in CONTEXT.md is overpowered without registry
Waiver path mentioned in audit concern 2. Without a central registry that tracks waiver usage per phase, AI will use it as a default escape hatch. Mitigation: log waiver usage to `override-debt.md` (existing infra at `vg:_shared:override-debt`) with reason; gate review pass on waiver count ≤ 20% of CRUD-creating endpoints per phase.

### ID-11 [MINOR]: `consumes_state` / `produces_state` keys collide with potential future state-machine fields
The current template (lines 67-148) does not use `produces_state` / `consumes_state` keywords but `goal_grounding: flow` references state-machine semantics. Reserve namespacing: rename to `chain_consumes_state` / `chain_produces_state` to avoid collision when FLOW-SPEC matures.

---

## Recommended plan adjustments

1. **Insert B62-pre task** (before any other B62 work): resolve `goal_class` vs `goal_type` dispatch (ID-1) AND `enables[]` vs `Dependencies[]` symmetry rule (ID-2). One commit, ≤3 files, no behavior change. Without this, B62 is a no-op.
2. **Move scanner heuristic tuning out of B63 into a new B63a tuning pass** after first real-phase usage. B63 ships the schema + nav primitives + default `sample` mode. B63a refines N, budget, top-N selection rules from production telemetry.
3. **Add B64 smoke that exercises the actual contracts-delegation.md prompt** (not synthetic fixture). Use a frozen CRUD-SURFACES.md fixture as input. Asserts prompt-rendered output contains valid `feature_chain` goals. Closes the "synthetic passes, real AI doesn't" gap (ID-8).
4. **Add UPDATE/DELETE cascade tests to B63's 13** (ID-5). Test count rises to 15-16.
5. **Document multi-tenant + async deferrals** in `dev-phases/feature-chain-design/OUT-OF-SCOPE.md` (ID-7).

---

## Audit checklist coverage

| Concern | Status |
|---|---|
| Schema collision (`goal_class` dispatch, `enables[]`/Deps symmetry) | BLOCK (ID-1, ID-2) |
| Validator soundness (chain_steps ≥4 too low, downstream_effects gap) | RISK (ID-3) |
| AI prompt drift (rename-without-chain cheat) | RISK (ID-3) |
| Scanner cost (50×3×10s = 25min worst case) | RISK (ID-4) |
| `enables` vs `Dependencies` truth | BLOCK (ID-2) |
| Idempotency (view rename → goal-id drift) | RISK (ID-6) |
| UPDATE/DELETE cross-view (missing entirely) | RISK (ID-5) |
| Multi-tenant (single-role scan limitation) | DEFER + DOCUMENT (ID-7) |
| Async propagation (webhook→notification delay) | DEFER + DOCUMENT (ID-7) |
| Legacy no-regression (no warn-mode env) | RISK (ID-9) |
| Real-prompt dogfood gap | NOTE (ID-8) |
| Waiver abuse | NOTE (ID-10) |

**Bottom line:** Plan direction is correct and addresses the user pain. Two BLOCKERs are concrete pipeline bugs that will make B62 a silent no-op if shipped as-currently-spec'd. Fix ID-1 and ID-2 in a 1-commit B62-pre. Then proceed with B62 → B63 → B64 with the 4 plan adjustments above.
