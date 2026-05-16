# Codex Audit — Feature-Chain Coverage Plan (B62-B64)

You are an adversarial reviewer auditing a VGFlow harness implementation plan BEFORE coding begins. Your job: find blind spots, schema risks, validator false-positive/false-negative patterns, prompt-drift risks, scope creep, and missed edge cases. Be ruthless. Output ONE file: CODEX-AUDIT.md.

## Context — user pain (verbatim, Vietnamese)

> "test specs còn ít quá, nó phải là khâu gần như nặng nhất cùng với review để tạo ra được những tài liệu test quý giá. tôi thấy phần AI nhìn nhận về các testgoals còn vô cùng nông. gặp dự án có độ liên kết giữa các feature phức tạp là nó hay chỉ viết test specs ở mức độ bấm vào 1 cái nút, show được modal là xong, còn cả 1 quy trình sau đó là từ khi có data sẽ lại sinh ra cả 1 núi tính năng khác. test specs nó cũng phải có tuần tự để thành 1 luồng gần như khép kín tới khi kết thúc 1 chu trình của 1 feature nào đó."

Translation: AI emits shallow test specs ("click button → modal opens → done") but misses full feature lifecycle. After CREATE entity, dozens of downstream features get unlocked elsewhere. Test specs need to be closed-loop sequences walking the full feature journey.

## Phase 1 Explore findings (3 root causes)

**1. Scanner single-view myopia.** `skills/vg-haiku-scanner/SKILL.md` lines 313-329 persistence_probe scope = current view only. After CREATE on `/sites`, scanner does NOT navigate to `/dashboard` to verify visibility. `sub_views_discovered[]` is passive list, never followed.

**2. enrich-test-goals.py inherits shallowness.** `scripts/enrich-test-goals.py` line ~245 G-AUTO form goals have main_steps "S4: Refresh — submitted record persists" scoped to CURRENT view only.

**3. LIFECYCLE/Blueprint missing inverse deps.** `commands/vg/_shared/templates/TEST-GOAL-enriched-template.md` line 111: goal_class enum = {mutation, readonly, crud-roundtrip, wizard, approval, webhook}. NO `feature_chain`. NO frontmatter fields `enables[]` / `produces_state` / `consumes_state`. FLOW-SPEC detection (`commands/vg/_shared/blueprint/contracts-overview.md` lines 506-613) parses upstream `Dependencies:` only.

## Proposed approach — 3 batches + Phase 0 audit (this audit)

### Batch 62 — top-down (blueprint enforce)

- Add `feature_chain` + `post_create_cascade` (alias) to `goal_class` enum at line 111 of TEST-GOAL-enriched-template.md
- New frontmatter fields: `enables: [G-XX]`, `consumes_state: <key>`, `produces_state: <key>`, `chain_steps: [{step_id, expected_state, downstream_effects[]}]`
- min_steps[feature_chain] = 8
- contracts-delegation.md prompt (lines 244-255): add explicit AI instruction for closed-loop journey emission
- close.md STEP 5.5.4: wire `verify-feature-chain-coverage.py` with 3-tier fallback (B61 pattern). BLOCK on missing chain goal for any CRUD-creating endpoint listed in CRUD-SURFACES.md
- contracts-overview.md FLOW-SPEC walker (lines 506-613): extend Dependencies[] traversal to ALSO follow `enables[]` downstream
- generate-lifecycle-specs.py (lines 896-930): when `goal_class == feature_chain`, emit RCRURDR stages + new `visibility_check` stage per chain_step. Echo `chain_steps[]` into LIFECYCLE-SPECS.json
- enrich-test-goals.py (~line 245): when emitting CRUD form G-AUTO goals, ALSO emit feature_chain stub with placeholder chain_steps
- 12 unit tests

### Batch 63 — bottom-up (scanner cross-view)

- Extend scanner SKILL.md schema with `cross_view_propagation_observations[]` shape: `[{source_view, target_view, action, entity_id, observed_in_target: yes|no|partial, evidence_screenshot, observed_count_delta}]`
- New scanner workflow: AFTER persistence_probe success on CREATE/UPDATE/DELETE, navigate to top-N (default N=3, env `VG_CROSS_VIEW_N`) "related sibling views" derived from RUNTIME-MAP.json route_inventory[]. Heuristic priority: (1) shared entity slug, (2) dashboard/summary view, (3) sibling list. 10s budget cap; budget exceeded → WARN + skip (not BLOCK). Default OFF for readonly goals.
- Per target: capture screenshot + DOM text match for entity_id + record observed_count_delta vs pre-mutation
- enrich-test-goals.py: consume `scan.cross_view_propagation_observations[]`. For each `observed_in_target=yes`, emit `G-AUTO-{entity}-visibility-{source}-to-{target}` with `goal_class: feature_chain` + chain_steps S1-S4
- New `verify-cross-view-coverage.py` validator
- seed-chain-status.py (B60): add layer "8. feature_chain coverage (B62-63)"
- 13 unit tests

### Batch 64 — integration smoke + codex replay

- Synthetic phase fixture under `tests/fixtures/feature_chain/` exercises B62+B63 end-to-end
- 10 integration tests: LIFECYCLE → derive → VARIANTS.json chain_steps → cross_view scan → enrich → recipes (B51) → helper-stub (B55) → spec-seed-binding (B52) → seed-chain-status reports green/yellow
- Refine seed-chain-status layer 8 with per-resource chain coverage %
- Phase 0 replay: spawn codex against v4.51..v4.54 diff + this audit. Output CODEX-AUDIT-REPLAY.md

## Critical files referenced (read these before audit)

1. `D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md` (line 111 enum)
2. `D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/blueprint/contracts-delegation.md` (lines 244-255 prompt block)
3. `D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/blueprint/close.md` (STEP 5.5.4 validator gates)
4. `D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/blueprint/contracts-overview.md` (lines 506-613 FLOW-SPEC detection)
5. `D:/Workspace/Messi/Code/vgflow-repo/skills/vg-haiku-scanner/SKILL.md` (lines 313-329 persistence_probe)
6. `D:/Workspace/Messi/Code/vgflow-repo/scripts/enrich-test-goals.py` (line ~245 G-AUTO emission)
7. `D:/Workspace/Messi/Code/vgflow-repo/scripts/generate-lifecycle-specs.py` (lines 896-930 per-goal block)

## Audit instructions

Read the critical files above first. Then for THIS PLAN, identify:

### 1. Schema risks
- Will `enables[]` + `consumes_state` + `produces_state` + `chain_steps[]` collide with existing schema fields? Check TEST-GOAL-enriched-template.md fields.
- Is `chain_steps[]` properly inverse-mappable to LIFECYCLE-SPECS.steps[]?
- Can the validator unambiguously detect "this CRUD endpoint lacks a feature_chain goal" vs false positives (e.g. read-only endpoint flagged)?

### 2. Validator soundness
- `verify-feature-chain-coverage.py` checks chain_steps ≥4. Is that the right threshold? Counterexamples?
- `verify-cross-view-coverage.py` requires ≥1 propagation observation per CREATE form. What about CREATE forms that legitimately produce no cross-view effect (e.g. internal admin action)?
- Waiver paths: `feature_chain_waiver` in CONTEXT.md, `skip_cross_view: true` in scanner-overrides.yaml. Anti-pattern: AI uses waiver to bypass enforcement on EVERY phase.

### 3. AI prompt drift risks
- contracts-delegation.md addendum says "For every CRUD-creating goal, emit ≥1 sibling feature_chain goal". Risk: AI emits feature_chain goal that just RENAMES existing mutation goal without adding actual chain_steps with distinct expected_state.
- Validator counters with: chain_steps ≥4 AND distinct expected_state per step AND target_view differs from source_view. Is that sufficient? Can AI cheat?

### 4. Scanner cost/scope explosion
- Cross-view navigation post-mutation × N=3 × every mutation in a phase = explosion. Worst case: phase has 50 mutations → 150 extra cross-view scans per run.
- 10s budget per persistence_probe — is that enough? Too generous?
- Heuristic for selecting top-N views (shared slug, dashboard, sibling list) — what's the false-positive rate? Could miss true related views.

### 5. enables[] vs Dependencies[] truth source
- enables[] forward, Dependencies[] backward. FLOW-SPEC walker dedupes, prefers enables[] on conflict. What if AI populates both inconsistently?
- Migration: pre-B62 phases have Dependencies[] only. Does FLOW-SPEC still work?

### 6. Idempotency
- Enrich-test-goals deterministic goal-id from (entity + source_view + target_view). Edge case: what if user renames a view? Goal id drifts → duplicate goals.
- Scanner re-run produces new cross_view_propagation_observations[] — does enrich dedupe correctly?

### 7. Missing concerns
- What about UPDATE/DELETE cross-view effects? Plan focuses on CREATE → list-visibility. Doesn't explicitly handle "delete entity → vanishes from list AND archive count++".
- Multi-tenant: entity creates visible to tenant A but not tenant B. Scanner navigates as one role only — false negative for cross-tenant cascade.
- Background async jobs that propagate after delay (webhook → notification → audit log increment). Scanner only navigates immediately post-mutation.

### 8. Test coverage gaps
- 12+13+10 tests planned. Do they cover: legacy phase no-regression? Validator with both --strict and --warn modes? Codex mirror parity for ALL new validators? Edge cases (empty CRUD-SURFACES, empty TEST-GOALS)?

### 9. Out-of-scope items that maybe SHOULD be in scope
- Real project dogfood was explicitly excluded. Risk: synthetic fixtures pass but AI doesn't actually emit feature_chain goals in real prompts. Should we add ONE real-prompt smoke test (vgflow Phase X self-dogfood)?

## Output format

Write `CODEX-AUDIT.md` with sections:

```
# Codex Audit — Feature-Chain Plan B62-B64

**Date:** YYYY-MM-DD
**Auditor:** codex adversarial tier
**Verdict:** PASS | PASS-WITH-NOTES | BLOCK

## Critical findings (BLOCKER)
- ID-1 [BLOCKER]: <description>. Mitigation: <fix>.

## Major concerns (FIX-BEFORE-MERGE)
- ID-2 [MAJOR]: <description>. Mitigation: <fix>.

## Minor concerns (note + proceed)
- ID-3 [MINOR]: <description>.

## Recommended plan adjustments
- ...

## Audit checklist coverage
| Concern | Status |
|---|---|
| Schema collision | OK / RISK / BLOCK |
| Validator soundness | ... |
| AI prompt drift | ... |
| Scanner cost | ... |
| enables vs Deps truth | ... |
| Idempotency | ... |
| UPDATE/DELETE cross-view | ... |
| Multi-tenant | ... |
| Async propagation | ... |
| Legacy no-regression | ... |
```

Be specific. Reference file paths + line numbers. Avoid vague language ("could be better"). State concrete failures + concrete fixes. If you find NO blockers, say so plainly and verdict PASS.

You have 10 minutes. Read the critical files. Audit. Write CODEX-AUDIT.md.
