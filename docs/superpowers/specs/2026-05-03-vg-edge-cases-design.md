# VG Edge Cases — Design Spec (DRAFT, awaiting user review)

**Status:** DRAFT — alignment check before implementation
**Date:** 2026-05-03
**Trigger:** User dogfood — "blueprint cần sinh edge cases để review test cùng goal với data khác nhau → kết quả khác nhau"

## Problem statement

Hiện tại `TEST-GOALS.md` chỉ định nghĩa "happy path" criteria per goal. Khi review/test chạy:
- Browser navigation theo `start_view` → 1 trace per goal
- Mutation evidence: 1 form submit → 1 expected outcome
- KHÔNG có structured way để verify cùng goal với input variants khác nhau

Hậu quả: Bug edge-case (off-by-one, boundary overflow, auth-peer leak, race) chỉ phát hiện ở `/vg:roam` lens probe (pen-test-style) hoặc production.

## Proposal

### A. New artifact — `EDGE-CASES.md` (per phase)

Sinh ở blueprint, paired với `TEST-GOALS.md`:

```
${PHASE_DIR}/EDGE-CASES.md                    Layer 3 flat (legacy compat)
${PHASE_DIR}/EDGE-CASES/index.md              Layer 2 TOC by goal
${PHASE_DIR}/EDGE-CASES/G-NN.md               Layer 1 per-goal (primary)
```

**Per-goal structure** (G-NN.md):

```markdown
# Edge Cases — G-04: User creates site with custom domain

## Boundary inputs
| variant_id | input | expected_outcome | priority |
|---|---|---|---|
| G-04-b1 | domain="" (empty) | 400 with field-level error "domain required" | critical |
| G-04-b2 | domain="a"*256 (max-len) | 400 with field-level error "domain ≤ 253 chars" | critical |
| G-04-b3 | domain="invalid space" | 400 with field-level error "invalid hostname format" | high |

## State transitions
| variant_id | precondition | action | expected_outcome | priority |
|---|---|---|---|---|
| G-04-s1 | site exists with same domain | POST same domain | 409 with `error: "domain_taken"` | critical |
| G-04-s2 | site soft-deleted | POST same domain | 201 (resurrects soft-deleted) | medium |

## Auth boundaries
| variant_id | actor | expected_outcome | priority |
|---|---|---|---|
| G-04-a1 | anon | 401 redirect to /login | critical |
| G-04-a2 | peer-tenant publisher | 403 (cannot access other tenant's sites) | critical |

## Concurrency / race
| variant_id | scenario | expected_outcome | priority |
|---|---|---|---|
| G-04-c1 | 2 simultaneous POST same domain | first → 201, second → 409 (atomic uniqueness) | high |
```

### B. Edge case categories per profile (taxonomy)

Pre-built templates trong `commands/vg/_shared/templates/edge-cases-{profile}.md`:

| Profile | Categories |
|---|---|
| **web-fullstack** | boundary inputs, state transitions, auth boundaries, concurrency, data validity, pagination, idempotency, time-based, resource limits, error propagation |
| **web-frontend-only** | render variants (empty/1/many/overflow), state persistence, network (offline/slow/flaky), browser quirks, input UX (paste/IME), modal lifecycle, form fill stages, sub-component fail |
| **web-backend-only** | (subset of web-fullstack — no UI render variants) |
| **mobile-*** | permissions, background/foreground, network handoff (cellular/wifi/airplane), device (storage/memory/battery/dark mode), notification surfaces |
| **cli-tool** | args (empty/malformed/conflicting), stdin (piped/EOF/large), env (missing/wrong-type), TTY (piped/no-color), exit codes |
| **library** | API contract edge inputs, threading (re-entrant/async cancel), resource lifecycle (not-init/double-init/dispose), backwards compat |

Blueprint reads profile from `vg.config.md` → loads matching template → suggests categories per goal.

### C. Injection points

#### Blueprint (NEW step: `2b5e_edge_cases`)
- Runs after `2b5_test_goals`
- Reads TEST-GOALS + profile + EDGE-CASES template
- AI generates per-goal variants (3-10 per goal depending on goal complexity)
- Writes Layer 1 (per-goal) + Layer 2 (index) + Layer 3 (flat)
- New event: `blueprint.edge_cases_generated`
- New must_write: `EDGE-CASES.md` (≥120 bytes), `EDGE-CASES/index.md`, `EDGE-CASES/G-*.md`

#### Build (executor capsule includes edge case input)
- `vg-build-task-executor` capsule materialization adds:
  - `edge_cases_for_goal: vg-load --phase N --artifact edge-cases --goal G-NN`
- Executor MUST handle each variant in implementation
- New marker: `4b_edge_case_coverage_check` (severity=warn — bug if missing)
- Validator checks code references variant_ids in test files (e.g., `// G-04-b1`)

#### Review (test each variant)
- Phase 4 goal_comparison: for each goal, ALSO loop variants
- Per variant: replay `start_view` with input data, verify expected outcome
- New status in goal-coverage matrix:
  ```
  G-04: PASS (3/4 variants — G-04-c1 NOT_TESTED [needs concurrency harness])
  ```
- New event: `review.edge_case_variant_blocked` (severity=warn)

#### Test (regression covers variants)
- Codegen subagent (`vg-test-codegen`) reads EDGE-CASES per goal
- Generates `.spec.ts` with `test.each()` blocks per variant
- Each variant gets its own assertion + expected outcome
- L1/L2 binding gate verifies variant coverage in spec.ts

### D. Skip-if-missing (legacy phase compat)

```yaml
# blueprint.md must_write
- path: "${PHASE_DIR}/EDGE-CASES.md"
  content_min_bytes: 120
  required_unless_flag: "--skip-edge-cases"
  severity: "warn"  # WARN not BLOCK so legacy phases (pre-v2.49) don't fail
```

Legacy phase migration script (optional): `vg-migrate-edge-cases.py --phase N` → AI generates EDGE-CASES.md from existing TEST-GOALS.

### E. New `--skip-edge-cases` flag

For legacy phases or trivial goals (e.g., docs-only):
- Add to blueprint/build/review/test argument-hint
- Pair with `--override-reason="<text>"` (forbidden_without_override)
- Logs to override-debt register

## Open questions for user

1. **Scope**: implement full A+B+C+D, or start with just blueprint generation (skip injection into build/review/test for now)?
2. **Variant count**: 3-10 per goal too many/few? (Auto-suggest by complexity, user can prune.)
3. **Categories per profile**: comprehensive list above OK, or want narrower scope first?
4. **Migration**: write migration script for legacy phases now, or defer?
5. **Brainstorm**: invoke `superpowers:brainstorming` for deeper edge case exploration with you, or proceed with the taxonomy above?

## Estimated effort

| Layer | Lines | Effort |
|---|---|---|
| EDGE-CASES template files (6 profiles) | ~600 | 2 hours |
| Blueprint `2b5e_edge_cases` ref + delegation | ~250 | 1 hour |
| Build capsule injection | ~50 | 30 min |
| Review variant test loop | ~150 | 1 hour |
| Test codegen variant binding | ~100 | 45 min |
| Validator + migration script | ~200 | 1 hour |
| Documentation + tests | ~200 | 1 hour |
| **Total** | **~1550** | **~7 hours** |

## Recommendation

**Phase 1 (immediate, ~3 hours):**
- A: artifact spec
- B: profile taxonomy (templates only)
- D: skip-if-missing flag (backward compat)
- Blueprint step (generates EDGE-CASES per goal)

**Phase 2 (follow-up, ~4 hours):**
- C: injection into build/review/test
- Migration script
- Validator

Sếp confirm direction:
- (a) Proceed full Phase 1+2
- (b) Phase 1 only, see how it works, then Phase 2
- (c) Brainstorm deeper trước khi commit (invoke `superpowers:brainstorming`)
- (d) Modify scope (e.g., narrower categories, skip mobile)
