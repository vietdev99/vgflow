# `/vg:review` Ergonomics + Blueprint Wiring + Multi-actor Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 11 bugs/gaps in `/vg:review` UX, blueprint→build envelope completeness, and multi-actor build coordination — all surfaced during PrintwayV3 (PV3) dogfood + 2 rounds of Codex GPT-5.5 cross-AI verification.

**Architecture:** Three execution tracks landing in parallel. Track A (review pilot, 5 sequential tasks) refactors review.md halt-on-detect → AskUserQuestion 4-option wrapper, forces TodoWrite projection, standardizes finding-ID namespace, wires Task 26 lens dispatch enforcement. Track B (blueprint, 4 partly-parallel tasks) extends per-task slicing to CRUD-SURFACES + LENS-WALK + RCRURD invariants, adds BLOCK 5 FE Contract via 2-pass blueprint, extends RCRURD → RCRURDR full lifecycle, adds multi-actor WORKFLOW-SPECS via Pass 3 subagent. Track C (build coordination, 3 tasks depending on Track B mid-point) extends capsule with actor/workflow awareness, adds cross-wave workflow references, adds subagent `<workflow_context>` prompt block + per-slice size BLOCK validator.

**Tech Stack:** Bash (hooks + wrappers), Python 3.10+ (validators + libs), pytest (tests), tiktoken (token counting — Vietnamese-aware). No new runtime dependencies for FE codegen — all artifacts consumed by existing subagents (`vg-build-task-executor`, `vg-blueprint-contracts`, `vg-test-codegen`).

**Spec:** `docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md` v3.1 (after Codex round-1 89-finding fix + round-2 5-amendment patch).

---

## Track index (11 tasks across 3 tracks)

### Track A — Review pilot (5 sequential tasks)

| Task | Bug | File |
|---|---|---|
| 34 | B — Tasklist projection | [task-34-tasklist-projection.md](./2026-05-04-vg-review-ergonomics/task-34-tasklist-projection.md) |
| 33 | A — 2-leg blocking-gate wrapper | [task-33-blocking-gate-wrapper.md](./2026-05-04-vg-review-ergonomics/task-33-blocking-gate-wrapper.md) |
| 35 | C — Finding-ID namespace | [task-35-finding-id-namespace.md](./2026-05-04-vg-review-ergonomics/task-35-finding-id-namespace.md) |
| 36a | D part 1 — Lens prompt frontmatter migration | [task-36a-lens-frontmatter.md](./2026-05-04-vg-review-ergonomics/task-36a-lens-frontmatter.md) |
| 36b | D part 2 — Wire Task 26 lens dispatch into review | [task-36b-lens-dispatch-wire.md](./2026-05-04-vg-review-ergonomics/task-36b-lens-dispatch-wire.md) |

Sequential because each task references the previous one's surface (Task 33 wrapper consumed by Task 36b coverage gate).

### Track B — Blueprint extensions (4 partly-parallel tasks)

| Task | Bug | File |
|---|---|---|
| 39 | G — RCRURDR full lifecycle | [task-39-rcrurdr-lifecycle.md](./2026-05-04-vg-review-ergonomics/task-39-rcrurdr-lifecycle.md) |
| 38 | F — BLOCK 5 FE Contract + 2-pass blueprint | [task-38-fe-contract-block5.md](./2026-05-04-vg-review-ergonomics/task-38-fe-contract-block5.md) |
| 37 | E — Build envelope per-task slices | [task-37-build-envelope-slices.md](./2026-05-04-vg-review-ergonomics/task-37-build-envelope-slices.md) |
| 40 | H — Multi-actor WORKFLOW-SPECS | [task-40-workflow-specs.md](./2026-05-04-vg-review-ergonomics/task-40-workflow-specs.md) |

Sequencing: 39 ‖ 38 (parallel — different schemas) → 37 ‖ 40 (parallel — depend on schemas).

### Track C — Build coordination mitigations (3 tasks, partial parallel with Track B)

| Task | Bug | File |
|---|---|---|
| 41 | I (M1) — Capsule extension actor/workflow | [task-41-capsule-workflow-fields.md](./2026-05-04-vg-review-ergonomics/task-41-capsule-workflow-fields.md) |
| 42 | J (M2) — wave-context cross-wave workflow refs | [task-42-wave-context-cross-wave.md](./2026-05-04-vg-review-ergonomics/task-42-wave-context-cross-wave.md) |
| 43 | K (M3) — `<workflow_context>` prompt + size BLOCK | [task-43-workflow-prompt-size-validator.md](./2026-05-04-vg-review-ergonomics/task-43-workflow-prompt-size-validator.md) |

Sequencing: 41 (parallel to Track B) → 42 + 43 (depend on Tracks B mid-point + Task 41).

## Cross-task contracts (locked invariants)

These contracts are referenced by multiple tasks. Drift between drafts = bug:

- **Wrapper exit codes** (Task 33 ↔ Task 36b): `0`=fixed, `1`=skip-with-override, `2`=route-to-amend, `3`=abort, `4`=re-prompt-with-repair-packet, `64+`=wrapper internal error (BSD sysexits).
- **Tasklist evidence path** (Task 34 ↔ existing PreToolUse-bash hook): `.vg/runs/<run_id>/.tasklist-projected.evidence.json` (repo-relative, NOT phase-relative).
- **Finding-ID prefixes** (Task 35 ↔ Task 36b lens coverage matrix): `EP|DR|RV|GC|FN|SC|TM` (2-letter), 3-digit zero-padded. Validator regex matches real PV3 format with bracketed severity (Codex round-2 Amendment E).
- **`write_phase` enum** (Task 41 capsule ↔ Task 39 RCRURDR consumer): `create|update|delete|null`. Distinct from RCRURDR `lifecycle_phases` (7 ops).
- **RCRURDR phase names** (Task 39 schema ↔ Task 40 WORKFLOW-SPECS rcrurd_invariant_ref): `read_empty | create | read_populated | update | read_updated | delete | read_after_delete`.
- **BLOCK 5 fields** (Task 38 schema ↔ Task 40 BLOCK 5 reads): 16 fields per spec line 312-326.
- **Capsule schema version** (Task 41): `capsule_version: "2"` for new shape; v1 capsules tolerated for in-flight phases.
- **Per-slice size budget** (Task 43 validator ↔ all per-unit slices): ≤ 5K tokens per per-unit slice (PLAN/task-NN.md, API-CONTRACTS/<slug>.md, TEST-GOALS/G-NN.md, CRUD-SURFACES/<resource>.md, WORKFLOW-SPECS/WF-NN.md). ≤ 1K tokens per index file (with `--allow-oversized-slice` migration window for in-flight phases).

## Self-review (writer's checklist)

**Spec coverage** — every section in spec maps to a task:

| Spec section | Task |
|---|---|
| Bug A — wrapper + 4-option AskUserQuestion + subagent contract + severity vocab + non-interactive | Task 33 |
| Bug B — slim entry positioning + hook diagnostic upgrade + telemetry | Task 34 |
| Bug C — finding-ID namespace + warn-tier rollout + real-format regex | Task 35 |
| Bug D part 1 — lens prompt frontmatter migration (19 files × 6 fields) | Task 36a |
| Bug D part 2 — Task 26 lens dispatch wired into review.md Phase 2.5 | Task 36b |
| Bug E — build envelope CRUD-SURFACES + LENS-WALK + RCRURD slices + per-task | Task 37 |
| Bug F — BLOCK 5 FE Contract + 2-pass blueprint + 16 fields + retroactivity flag | Task 38 |
| Bug G — RCRURDR `lifecycle_phases[]` + Tasks 23/24/25 callsite updates | Task 39 |
| Bug H — multi-actor WORKFLOW-SPECS + Pass 3 subagent + state machine | Task 40 |
| Bug I (M1) — capsule extension actor/workflow/write_phase fields | Task 41 |
| Bug J (M2) — wave-context cross-wave workflow citations | Task 42 |
| Bug K (M3) — `<workflow_context>` prompt block + size BLOCK validator | Task 43 |
| Codex round-2 Amendments A-E | Patched in spec v3.1; tasks reference for implementation |
| Codex round-2 critical gaps F-O | Addressed in per-task acceptance criteria |

**Placeholder scan** — no "TBD", "TODO", "fill in", "similar to" in this index or per-task files (verified in self-review during drafting).

**Type consistency** — wrapper exit codes (Task 33 ↔ 36b), `write_phase` enum (Task 41 ↔ 39), RCRURDR phase names (39 ↔ 40), BLOCK 5 field shape (38 ↔ 40 ↔ 37), capsule version (41 ↔ all callers): all locked above.

## Execution handoff

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task, review between tasks, fast iteration. ~25-32h total wall time across 3 sessions if parallel by ≥2 sessions.

**2. Inline Execution** — execute tasks in this session via executing-plans, batch checkpoints. ~32h sequential.

Recommend subagent-driven + multi-session because Track A alone exceeds typical session length (~6h). Suggested split:
- Session 1: Track A (Tasks 34 → 33 → 35 → 36a → 36b)
- Session 2: Track B parallel (39 ‖ 38) → (37 ‖ 40)
- Session 3 (after Track B mid-point): Track C 41 → 42 → 43

After all 11 tasks land: re-run `/vg:build 4.1 --only=post-execution` on PV3 to validate the chain end-to-end (L4a-i call graph catches `billing-summary` missing handler as IN_SCOPE → STEP 5.5 auto-fix-loop).

Which approach?
