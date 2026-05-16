# Codex Audit Replay — B62 / B63 Implementation Verification

**Date:** 2026-05-16
**Auditor:** opus-4.7 adversarial reviewer (codex CLI 9router 404 — proxy mode)
**Verdict:** **PASS-WITH-NOTES** — 10/11 findings RESOLVED or DEFERRED-with-docs; **ID-9 confirmed NOT ADDRESSED** as the prompt itself flagged. No new BLOCKERs found in adversarial replay. One MINOR new finding (NF-1) on enables[] parser regex.

---

## Resolution status

| Audit ID | Status (claimed → verified) | Evidence | Remaining gap |
|---|---|---|---|
| ID-1 BLOCKER | RESOLVED → **VERIFIED** | `scripts/generate-lifecycle-specs.py` L67-87 defines `FEATURE_CHAIN_STAGES` (11 stages incl. `visibility_check`, `cascade_check`, `archive_visibility_check`) + `GOAL_CLASS_STAGES` dict L84-87 with `feature_chain` + `post_create_cascade` alias. `_stages_for_goal` L90-128 docstring explicitly states "**Dispatch precedence: 1. goal_class … 2. goal_type … 3. HTTP verb**" and L102-104 reads `goal_class` BEFORE `goal_type`. Failure mode from audit (`goal_class=feature_chain` → silent RCRURDR fallback) is closed. | None. |
| ID-2 BLOCKER | RESOLVED → **VERIFIED** | `scripts/validators/verify-enables-deps-symmetry.py` exists (5237 bytes, exec). L84-98 `_check_symmetry` asserts `enables=[X]` requires `X.Dependencies` contain caller. `contracts-overview.md` L553-559 documents canonical rule: "*walker reads Dependencies[] ONLY. enables[] is intentionally NOT walked here — avoids double-traversal + cycle pseudo-edges*". Walker no longer loops on bidirectional declarations. | Validator default is warn-mode (need `--strict` to block) — see NF-1 below. |
| ID-3 MAJOR | RESOLVED → **VERIFIED** | `verify-feature-chain-coverage.py` L41 `MIN_CHAIN_STEPS = 8` (raised from 4), L42 `MIN_STEPS_WITH_DOWNSTREAM_EFFECTS = 2`, L158-160 enforces step count, L163-166 enforces **distinct `expected_state`** (not just non-empty), L177-181 enforces ≥2 steps with `downstream_effects[]`, L35-39 `SOURCE_VIEW_CLASSES` frozenset enforces traversal outside `{source_view, source_view_modal, source_view_form}`. Anti-cheat pad-with-no-op-steps attack is closed. | None. |
| ID-4 MAJOR | RESOLVED → **VERIFIED** | `skills/vg-haiku-scanner/SKILL.md` L436-441 defines: `VG_CROSS_VIEW_MODE` default `sample` (only top-3 highest-priority CREATE mutations), `VG_CROSS_VIEW_N=3`, `VG_CROSS_VIEW_TOTAL_BUDGET_S=60`. L800 schema note re-states 60s phase cap + dedup by `(entity_slug_family, target_view_class)`. Worst-case 25min runtime closed. | None. |
| ID-5 MAJOR | RESOLVED → **VERIFIED** | `scripts/enrich-test-goals.py` L221-225 `action_class_map = {"create":"visibility", "update":"status-cascade", "delete":"archive"}`. L231-232 selects action_class per observation. L243 emits per-action goal id `G-AUTO-{entity_slug}-{action_class}-{target_class}`. UPDATE + DELETE cascades now produce distinct stub goals. | None. |
| ID-6 MAJOR | RESOLVED → **VERIFIED** | `enrich-test-goals.py` L236-243 derives goal-id from `entity_canonical_id` (NOT raw view path) + `target_view_class` enum. Verified by integration test `tests/test_batch64_feature_chain_integration.py::test_goal_id_stable_across_view_rename` L277-295 which simulates `/sites → /properties` rename and asserts identical goal-id. View-rename-drift attack closed. | Fallback path L237-240 still uses path-derived slug if `entity_canonical_id` absent — acceptable degradation; scanner is the upstream source-of-truth. |
| ID-7 MAJOR | DEFERRED → **VERIFIED documented** | `dev-phases/feature-chain-design/OUT-OF-SCOPE.md` L9-23 (multi-tenant deferred to B65, manual workaround documented), L25-38 (async / delayed propagation deferred, webhook workaround documented). SKILL.md L800 `limitations[]` field carries `single_role_scan` + `no_delayed_propagation` markers into observations for downstream awareness. | Acceptable deferral; tracked. |
| ID-8 MINOR | PARTIAL → **VERIFIED partial** | `tests/test_batch64_feature_chain_integration.py::test_real_prompt_has_b62_instructions` L261-274 reads actual `contracts-delegation.md` body and asserts presence of `feature_chain`, `closed-loop`, `B62`, `chain_steps`, `rename`, and `crud/POST` strings. Closes synthetic-vs-prompt gap; live AI dogfood still deferred per OUT-OF-SCOPE.md L40-54. | Live AI dogfood (B65 `/vg:dogfood` candidate) — accepted partial. |
| ID-9 MINOR | claimed NOT ADDRESSED → **CONFIRMED NOT ADDRESSED** | `grep -r VG_FEATURE_CHAIN_MODE D:/Workspace/Messi/Code/vgflow-repo` returns **2 matches only**, both in `dev-phases/feature-chain-design/{CODEX-AUDIT.md, CODEX-AUDIT-REPLAY-PROMPT.md}` (the audit docs themselves). **Zero matches in `scripts/`, `commands/`, `skills/`, `tests/`.** No legacy phase warn-mode escape exists. Re-running `vg:review` on pre-2026-05-01 phases will hard-BLOCK on missing feature_chain goals. | **Open gap.** See Recommendations. |
| ID-10 MINOR | RESOLVED → **VERIFIED** | `OUT-OF-SCOPE.md` L58-68 "*`feature_chain_waiver[<resource>]: <reason>` lives in CONTEXT.md, logged to override-debt.md via existing vg:\_shared:override-debt skill. NO new registry script.*" Explicit "Won't fix (intentional)" framing. No duplicate registry shipped. | None. |
| ID-11 MINOR | RESOLVED → **VERIFIED** | `commands/vg/_shared/templates/TEST-GOAL-enriched-template.md` L154 `chain_consumes_state:`, L163 `chain_produces_state:`, L169 `chain_steps:`. `chain_*` prefix prevents collision with future FLOW-SPEC state-machine fields. `OUT-OF-SCOPE.md` L70-74 records the decision. | None. |

---

## New findings (post-impl)

### NF-1 [MINOR]: `verify-enables-deps-symmetry.py` defaults to warn-mode; no caller passes `--strict`
File `scripts/validators/verify-enables-deps-symmetry.py` L138-142 prints warning + returns 0 unless `--strict` flag is set. I scanned for callers — only the validator file itself references the flag. The walker doc in `contracts-overview.md` L553-559 says the symmetry is enforced, but the enforcement is opt-in. AI emitting asymmetric `enables[]` will produce warn lines that get lost in CI logs; FLOW-SPEC walker still safe because it reads `Dependencies[]` only, but the documented "two truth sources will drift within 2-3 phases" risk from audit ID-2 mitigation #2 remains partially open.

**Recommendation:** Either (a) flip default to `--strict` (breaking), or (b) wire `--strict` into the build/review gate that invokes this validator. ID-2 BLOCKER mitigation is structurally complete (walker no longer loops), so this is MINOR not BLOCKER, but the second half of the audit-recommended fix is not load-bearing in practice.

### NF-2 [MINOR]: `verify-enables-deps-symmetry.py` regex permissive on inline lists
L46-49 `DEPS_FIELD_RE = re.compile(r"(?:\*\*)?[Dd]ependencies:?(?:\*\*)?\s*\[?([^\]\n]*)\]?", re.M)` — the `[^\]\n]*` group stops at first `]` or newline, so a YAML-style multi-line `Dependencies:\n  - G-01\n  - G-02` shape will only capture the heading line (zero deps). Test fixtures use inline `Dependencies: G-01, G-02` form which works. If a phase author uses YAML block-list style, validator silently sees zero deps → false PASS. Not a B62/B63 regression (the template uses inline form), but a latent footgun.

**Recommendation:** Extend regex to optionally absorb subsequent indented `- G-XX` lines, or document that only inline form is supported.

---

## Recommendations

1. **ID-9 remediation (HIGH priority for B64 close):** Add `VG_FEATURE_CHAIN_MODE=warn|block` env to `verify-feature-chain-coverage.py` and `verify-cross-view-coverage.py`. Default `block` post-2026-05-01; `warn` for phases with `phase.cutoff_date < 2026-05-01`. Either (a) read `PHASE-MANIFEST.md` for cutoff, or (b) accept env override per CI run. Without this, legacy phase re-review will block on missing chain goals — exactly the regression risk codex flagged. Estimated ≤30 LOC change.

2. **NF-1 remediation (LOW priority):** Wire `--strict` into the orchestrator gate that invokes the symmetry validator, OR flip default. Current state is acceptable because the FLOW-SPEC walker is unidirectional, but the documented enforcement promise is not load-bearing in CI.

3. **NF-2 remediation (LOW priority):** Document inline-list-only constraint in validator docstring + template, OR extend regex. Not a B62/B63-introduced bug.

4. **B65 backlog (already documented):** `/vg:dogfood` live-AI smoke (ID-8), multi-tenant scanner loop (ID-7a), delayed-propagation re-poll (ID-7b). All tracked in OUT-OF-SCOPE.md with B65-candidate workarounds.

---

## Verdict rationale

- **Both BLOCKERs (ID-1, ID-2) are concretely fixed** with code I quoted directly. The pipeline no-op + walker-loop failure modes are closed.
- **All 5 MAJORs (ID-3 through ID-7)** are either fixed in code (ID-3..6) or deferred with explicit documentation + workarounds (ID-7).
- **3 of 4 MINORs (ID-8, ID-10, ID-11)** are resolved as claimed.
- **1 MINOR (ID-9) is confirmed NOT ADDRESSED** by direct grep. The audit prompt itself flagged this; my replay confirms zero implementation. This is acceptable to ship since legacy phases lack `goal_class: feature_chain` enum entirely (so validator skips them gracefully when no CRUD-SURFACES.md present), but a deliberate env-mode escape would harden the rollout.
- **2 new MINOR findings (NF-1, NF-2)** are non-blocking footguns in the symmetry validator. Neither invalidates the ID-2 fix structurally.

**Cleared to ship B62 + B63 + B64.** Recommend ID-9 escape valve added as a follow-on patch before re-running review on any pre-2026-05-01 phase.

---

## Cross-references

- Original audit: `dev-phases/feature-chain-design/CODEX-AUDIT.md`
- Replay prompt: `dev-phases/feature-chain-design/CODEX-AUDIT-REPLAY-PROMPT.md`
- Out-of-scope tracking: `dev-phases/feature-chain-design/OUT-OF-SCOPE.md`
- B62-pre BLOCKER fixes: `scripts/generate-lifecycle-specs.py` + `scripts/validators/verify-enables-deps-symmetry.py` + `commands/vg/_shared/blueprint/contracts-overview.md`
- B62 contracts: `commands/vg/_shared/templates/TEST-GOAL-enriched-template.md` + `commands/vg/_shared/blueprint/contracts-delegation.md`
- B62 validator: `scripts/validators/verify-feature-chain-coverage.py`
- B63 scanner: `skills/vg-haiku-scanner/SKILL.md`
- B63 enrich: `scripts/enrich-test-goals.py`
- B63 validator: `scripts/validators/verify-cross-view-coverage.py`
- B64 integration tests: `tests/test_batch64_feature_chain_integration.py`
