# Codex Audit Replay — Feature-Chain B62→B63 Implementation Verification

You are an adversarial reviewer doing a POST-IMPLEMENTATION replay
of the original Phase 0 audit. Phase 0 (CODEX-AUDIT.md) flagged 2
BLOCKERs + 5 MAJORs + 4 MINORs. Implementation shipped as B62-pre
(v4.51.1), B62 (v4.52.0), B63 (v4.53.0). Confirm each flagged issue
addressed OR document remaining gap.

## Original audit findings recap

**BLOCKERs:**
- ID-1: `goal_class` not dispatch key → silent no-op
- ID-2: `enables[]`/`Dependencies[]` symmetry undefined → walker loops

**MAJORs:**
- ID-3: chain_steps ≥4 too low (AI cheat)
- ID-4: scanner cost explosion (50×3×10s = 25min)
- ID-5: UPDATE/DELETE cascade missing
- ID-6: view rename → goal-id drift
- ID-7: multi-tenant + async deferred

**MINORs:**
- ID-8: synthetic-fixture-only acceptance (no real-prompt dogfood)
- ID-9: legacy phase regression — no VG_FEATURE_CHAIN_MODE warn env
- ID-10: feature_chain_waiver registry abuse risk
- ID-11: chain_*_state namespacing collision

## Implementation summary

Read these files to verify claims:

1. `scripts/generate-lifecycle-specs.py` (B62-pre ID-1):
   - GOAL_CLASS_STAGES + FEATURE_CHAIN_STAGES added (lines ~56-92)
   - `_stages_for_goal` precedence: goal_class > goal_type > HTTP-verb

2. `scripts/validators/verify-enables-deps-symmetry.py` (B62-pre ID-2)

3. `commands/vg/_shared/blueprint/contracts-overview.md` (B62-pre ID-2):
   - FLOW-SPEC walker docs truth-source rule (lines ~550)

4. `commands/vg/_shared/templates/TEST-GOAL-enriched-template.md` (B62 ID-3, ID-6):
   - feature_chain enum + post_create_cascade alias (line 111)
   - chain_steps schema with target_view_class enum (audit ID-6 view-
     rename-stable identity)

5. `commands/vg/_shared/blueprint/contracts-delegation.md` (B62 ID-3):
   - Anti-cheat instruction (~line 252)
   - "DO NOT rename existing mutation" language

6. `scripts/validators/verify-feature-chain-coverage.py` (B62 ID-3):
   - MIN_CHAIN_STEPS=8
   - distinct expected_state check
   - target_view_class out-of-source-family rule
   - MIN_STEPS_WITH_DOWNSTREAM_EFFECTS=2

7. `skills/vg-haiku-scanner/SKILL.md` (B63 ID-4, ID-5, ID-6, ID-7):
   - cross_view_propagation_observations[] schema
   - VG_CROSS_VIEW_TOTAL_BUDGET_S=60s phase cap (ID-4)
   - VG_CROSS_VIEW_MODE=sample default (ID-4)
   - action enum create/update/delete (ID-5)
   - entity_canonical_id field (ID-6 stable)
   - limitations[] documenting single_role + no_delayed (ID-7)

8. `scripts/enrich-test-goals.py` (B63 ID-5, ID-6):
   - Per-action goal class emission (visibility/status-cascade/archive)
   - Idempotent goal-id from entity_canonical_id

9. `scripts/validators/verify-cross-view-coverage.py` (B63):
   - Waiver paths: skip_cross_view + cross_view_scan: disabled

10. `dev-phases/feature-chain-design/OUT-OF-SCOPE.md` (ID-7, ID-8, ID-10, ID-11):
    - Multi-tenant + async deferred to B65
    - Waiver via override-debt skill (no separate registry)
    - chain_*_state namespacing done

11. `tests/test_batch64_feature_chain_integration.py` (ID-8 partial):
    - test_real_prompt_has_b62_instructions asserts actual prompt
      surface AI reads. Closes synthetic-vs-real-AI gap PARTIALLY.

## Audit replay checklist

For each finding, verify:

| ID | Status to confirm |
|---|---|
| ID-1 | RESOLVED — _stages_for_goal reads goal_class with precedence |
| ID-2 | RESOLVED — verify-enables-deps-symmetry.py validator + walker docs |
| ID-3 | RESOLVED — MIN_CHAIN_STEPS=8, downstream_effects gate, distinct state |
| ID-4 | RESOLVED — budget caps, sample mode default, dedup |
| ID-5 | RESOLVED — create/update/delete action enum + per-action enrich |
| ID-6 | RESOLVED — entity_canonical_id + target_view_class enum |
| ID-7 | DEFERRED — documented in OUT-OF-SCOPE.md, limitations[] field |
| ID-8 | PARTIAL — real-prompt test in B64; live AI dogfood deferred |
| ID-9 | NOT ADDRESSED — VG_FEATURE_CHAIN_MODE env not added |
| ID-10 | RESOLVED — uses override-debt (no separate registry) |
| ID-11 | RESOLVED — chain_*_state namespacing |

For any finding marked "ID-9 NOT ADDRESSED", or any RESOLVED claim
you can't verify in the actual files, flag in your output. Suggest
remediation.

## Output

Write `dev-phases/feature-chain-design/CODEX-AUDIT-REPLAY.md` with:

```
# Codex Audit Replay — B62 / B63 Implementation Verification

**Date:** 2026-05-16
**Verdict:** PASS | PASS-WITH-NOTES | BLOCK

## Resolution status

| Audit ID | Status (claimed → verified) | Evidence | Remaining gap |
|---|---|---|---|

## New findings (post-impl)

- IDX [SEVERITY]: ...

## Recommendations

- ...
```

Be concrete. Reference file paths + line numbers. Quote actual code/
prompt fragments when verifying. If a claim is unverifiable, say so.

≤ 1500 words. Save single file.
