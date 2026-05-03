# Build In-Scope Warning Fix-Loop + Pre-Test Gate + Diagnostic-v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task is a separate file in `2026-05-03-vg-build-in-scope-fix-loop/` — implementer subagent reads ONLY its assigned task file (self-contained), NOT this index.

**Goal:** Stop false-green builds. When `/vg:build` finishes a phase that contains FE-calls-missing-BE-endpoints, contract-shape mismatches, or executor-vs-spec drift, the build MUST block (not silently move to "Forward deps"). Build self-validates — never defers in-scope issues to `/vg:review` (would be circular: review can't run before build completes). Add deterministic detectors, an evidence-based classifier (4-tier severity), an auto-fix loop with phase-ownership boundaries, a forward-dep disposition gate in `/vg:scope`, and a pre-test gate (STEP 6.5) that runs before STEP 7 close.

**Diagnostic-v2 extension goal:** The diagnostic substrate that the fix-loop relies on (vg.block.fired/handled pairing, recovery telemetry, block correlation) had silent gaps surfaced by Codex GPT-5.5 cross-AI review of the stale-run BLOCK fix. Tasks 27-32 close those gaps so the fix-loop's classifier + auto-fix events land in events.db reliably, and recurring blocks become visible across runs (without which the fix-loop's "BLOCK once vs BLOCK every run" cost is invisible).

**Architecture (Codex round 2 confirmed):** L4-core (BLOCK on deterministic violations) FIRST → L2 classifier → L3 auto-fix → L1 rule resolver (parallel). Build STEP 5 gains 3 deterministic gates (FE→BE call graph, contract shape, spec drift). STEP 5.5 classifies + auto-fixes IN_SCOPE within phase-owned files. STEP 6.5 (Pre-Test Gate) runs T1 (static — typecheck/lint/secret scan/debug-leftover grep) + T2 (local unit/integration tests) + optional T4/T6 deploy via `/vg:deploy --pre-test`. Forward-deps route to `/vg:scope` of next phase with disposition gate (accepted/deferred/backlog/invalid), never silently dropped.

**Tech Stack:** Python 3 (validators + classifier + extractors + lib modules), Bash (orchestrator inline), JSON Schema (evidence persistence), pytest, jsonschema. No new runtime dependencies.

**Plan structure (split into per-task files for AI context budget):**
- This index = navigation only (~150 lines, fits in any subagent's preamble).
- Per-task files at `2026-05-03-vg-build-in-scope-fix-loop/task-NN-<slug>.md` are self-contained: code + tests + commands + commit step. Subagent reads ONLY its target file.
- Task files for 15-19 have Codex Round 2 corrections inlined at the bottom (no separate corrections section to cross-reference).

---

## Pre-shipped diagnostic foundation (already merged on `feat/rfc-v9-followup-fixes`)

These two commits are PREREQUISITES for Tasks 27-32 below. They land before any executor picks up this plan; do **not** re-implement them.

| Commit | Title | Why it matters |
|---|---|---|
| `41a4931` | `fix(stop-hook): modernize stale-run BLOCK format (color + diagnostic + block-file)` | Ships the modern emit pattern (orange ANSI 3-line stderr + `.vg/blocks/{run_id}/{gate_id}.md` + `vg.block.fired` payload) that Tasks 28-30 build on. Helper: `scripts/vg-verify-claim.py::_emit_stale_block`. |
| `ae498ed` | `fix(emit-event): accept --gate/--cause/--resolution/--block-file flags` | P0 surfaced by Codex GPT-5.5 review: hooks called `emit-event vg.block.fired --gate X --cause Y` but parser rejected → exit 2 swallowed by `\|\| true` → events.db had ZERO `vg.block.*` rows across hundreds of runs → Stop hook pairing gate (`scripts/hooks/vg-stop.sh:20-29`) silently bypassed. Fix extended `emit-event` parser + payload merge + widened `--outcome` choices for FAIL. New test `scripts/tests/test_emit_event_block_flags.py` (6 tests). |

If you are an executor and see these commits absent, STOP and report — Tasks 27-32 cannot be implemented on a tree where the pairing contract is still broken.

---

## Task index — 27 tasks total

| # | Title | File | Depends on |
|---|---|---|---|
| 1 | Severity taxonomy + evidence schema (4-tier: BLOCK / TRIAGE_REQUIRED / FORWARD_DEP / ADVISORY) | [task-01-severity-taxonomy.md](2026-05-03-vg-build-in-scope-fix-loop/task-01-severity-taxonomy.md) | – |
| 2 | B1 FE call + BE route extractors (grep-based) | [task-02-fe-be-extractors.md](2026-05-03-vg-build-in-scope-fix-loop/task-02-fe-be-extractors.md) | – |
| 3 | L4a-i FE→BE call graph BLOCK gate | [task-03-fe-be-call-graph-gate.md](2026-05-03-vg-build-in-scope-fix-loop/task-03-fe-be-call-graph-gate.md) | 1, 2 |
| 4 | B2/L4a-ii Contract shape validator (method match) | [task-04-contract-shape-validator.md](2026-05-03-vg-build-in-scope-fix-loop/task-04-contract-shape-validator.md) | 1, 2 |
| 5 | L4a-iii Spec drift validator (status code heuristic) | [task-05-spec-drift-validator.md](2026-05-03-vg-build-in-scope-fix-loop/task-05-spec-drift-validator.md) | 1 |
| 6 | Wire L4a gates into build STEP 5 post-execution | [task-06-wire-l4a-gates.md](2026-05-03-vg-build-in-scope-fix-loop/task-06-wire-l4a-gates.md) | 3, 4, 5 |
| 7 | L2 Evidence-based classifier (deterministic-first, 4-tier output) | [task-07-classifier.md](2026-05-03-vg-build-in-scope-fix-loop/task-07-classifier.md) | 1 |
| 8 | B6 Phase ownership allowlist | [task-08-phase-ownership.md](2026-05-03-vg-build-in-scope-fix-loop/task-08-phase-ownership.md) | – |
| 9 | B7 Regression smoke runner (post-fix verification) | [task-09-regression-smoke.md](2026-05-03-vg-build-in-scope-fix-loop/task-09-regression-smoke.md) | – |
| 10 | L3 Auto-fix loop STEP 5.5 (HARD-GATE: max 3 attempts, ownership respect, NO AskUserQuestion) | [task-10-auto-fix-loop.md](2026-05-03-vg-build-in-scope-fix-loop/task-10-auto-fix-loop.md) | 7, 8, 9 |
| 11 | L1 Rule resolver (scope-matched, not dump-all) + capsule wiring | [task-11-rule-resolver.md](2026-05-03-vg-build-in-scope-fix-loop/task-11-rule-resolver.md) | – |
| 12 | Forward-dep disposition gate in /vg:scope | [task-12-forward-deps-disposition.md](2026-05-03-vg-build-in-scope-fix-loop/task-12-forward-deps-disposition.md) | 7 |
| 13 | Integration golden fixture + E2E test (FE→BE gap → classifier → ownership) | [task-13-integration-test.md](2026-05-03-vg-build-in-scope-fix-loop/task-13-integration-test.md) | 3, 7, 8 |
| 14 | Sync mirrors + final verify (sync.sh + vg_sync_codex.py) | [task-14-sync-mirrors.md](2026-05-03-vg-build-in-scope-fix-loop/task-14-sync-mirrors.md) | 1-13 |
| **Pre-Test Gate (extension — Codex round 2 corrections inlined into each file)** |
| 15 | Pre-test T1 (static: typecheck/lint/debug-leftover/**secret scan**) + T2 (local tests); BLOCK on missing-expected-tooling per ENV-BASELINE | [task-15-pre-test-runner.md](2026-05-03-vg-build-in-scope-fix-loop/task-15-pre-test-runner.md) | 1 |
| 16 | Deploy decision policy reader (ENV-BASELINE-driven) + deterministic schema-change detection | [task-16-deploy-decision.md](2026-05-03-vg-build-in-scope-fix-loop/task-16-deploy-decision.md) | – |
| 17 | Post-deploy smoke (total deadline + auth headers + Playwright storageState) + PRE-TEST-REPORT writer | [task-17-post-deploy-smoke.md](2026-05-03-vg-build-in-scope-fix-loop/task-17-post-deploy-smoke.md) | 1 |
| 18 | Wire STEP 6.5 pre-test gate into build (Skill-tool deploy invocation, config-driven UX, classifier-routed failures) | [task-18-wire-pre-test-gate.md](2026-05-03-vg-build-in-scope-fix-loop/task-18-wire-pre-test-gate.md) | 7, 15, 16, 17, 20 |
| 19 | Pre-test gate integration test (deadline + redaction + schema-detect + DEPLOY-STATE path) | [task-19-pre-test-integration-test.md](2026-05-03-vg-build-in-scope-fix-loop/task-19-pre-test-integration-test.md) | 15, 16, 17, 18 |
| 20 | `/vg:deploy --pre-test` mode (allow pre-close invocation; mode='pre-test' in DEPLOY-STATE) | [task-20-deploy-pre-test-mode.md](2026-05-03-vg-build-in-scope-fix-loop/task-20-deploy-pre-test-mode.md) | – |
| **RCRURD coverage extension (Codex GPT-5.5 rounds 3-5 — prerequisite to Task 21 PV3 sync)** |
| 22 | RCRURD invariant schema + parser (Single Source of Truth) — structured YAML, schema validator, blueprint Rule 3b extension | [task-22-rcrurd-invariant-schema.md](2026-05-03-vg-build-in-scope-fix-loop/task-22-rcrurd-invariant-schema.md) | – |
| 23 | Review mandatory RCRURD verification per mutation goal (runtime gate) — read invariant, exec write+read, BLOCK on R8 | [task-23-review-rcrurd-mandatory.md](2026-05-03-vg-build-in-scope-fix-loop/task-23-review-rcrurd-mandatory.md) | 22 |
| 24 | Codegen `expectReadAfterWrite` helper + AST gate (build-side) — generated specs MUST call helper; AST validator | [task-24-codegen-rcrurd-helper.md](2026-05-03-vg-build-in-scope-fix-loop/task-24-codegen-rcrurd-helper.md) | 22 |
| 25 | R9 ui_render_truth_mismatch — UI ↔ API render coherence (10 ops; ui_assert.settle independent; stable selector policy) | [task-25-ui-render-truth-mismatch.md](2026-05-03-vg-build-in-scope-fix-loop/task-25-ui-render-truth-mismatch.md) | 22, 24 |
| 26 | Lens dispatch enforcement (AI-trust-by-design) — LENS-DISPATCH-PLAN.json trust anchor, generalized coverage gate, M1 tier-aware spawn (Haiku not allowed for complexity ≥ 4), M2 MCP trace cross-check, 7-state matrix | [task-26-lens-dispatch-enforcement.md](2026-05-03-vg-build-in-scope-fix-loop/task-26-lens-dispatch-enforcement.md) | 22-25 |
| **Diagnostic-v2 extension (Codex GPT-5.5 cross-review of stale-run BLOCK fix — prerequisites already shipped: commits `41a4931` + `ae498ed`)** |
| 27 | Recovery telemetry audit — every auto-fire path emits `hook.recovery_attempted` + `hook.recovery_succeeded`/`hook.recovery_failed` (currently `vg-recovery.py --auto` logs to stdout only; failures are silent) | [task-27-recovery-telemetry-audit.md](2026-05-03-vg-build-in-scope-fix-loop/task-27-recovery-telemetry-audit.md) | – |
| 28 | Block dedupe via `vg.block.refired` — same `gate_id` × `run_id` with no intervening `handled` should NOT create N obligations; emit `refired` with count, Stop hook treats one open obligation per gate | [task-28-block-dedupe-refired.md](2026-05-03-vg-build-in-scope-fix-loop/task-28-block-dedupe-refired.md) | – |
| 29 | Severity routing functional — `severity: warn\|error\|critical` actually changes hook behavior (warn = log no-block, error = exit 2 default, critical = exit 2 + force AskUserQuestion banner). Currently severity is cosmetic | [task-29-severity-routing.md](2026-05-03-vg-build-in-scope-fix-loop/task-29-severity-routing.md) | 28 |
| 30 | Skill attribution in block payload — `skill_path` / `command` / `step` / `hook_source` keys auto-populated by emit-block helper so AI navigates to source instantly via SKILL.md path | [task-30-skill-attribution.md](2026-05-03-vg-build-in-scope-fix-loop/task-30-skill-attribution.md) | – |
| 31 | Cross-session block awareness — SessionStart hook queries unhandled blocks across ALL active-runs (not just same session); reinjects with `owner_session` label so a session B can see session A's stuck blocks | [task-31-cross-session-block-awareness.md](2026-05-03-vg-build-in-scope-fix-loop/task-31-cross-session-block-awareness.md) | – |
| 32 | Block correlator CLI (`vg-orchestrator block-correlate`) — read-only events.db query, detect recurring (same gate × N runs in window) / causal-chain (≤30s temporal proximity, repeated) / high-velocity (>2σ above 7-day mean). Wire into `/vg:doctor diagnostic` | [task-32-block-correlator.md](2026-05-03-vg-build-in-scope-fix-loop/task-32-block-correlator.md) | 27, 28, 29, 30 |
| 21 | Sync VGFlow harness changes to PrintwayV3 dogfood target (now includes RCRURD coverage 22-25 + lens enforcement 26 + diagnostic-v2 27-32) | [task-21-sync-to-printwayv3.md](2026-05-03-vg-build-in-scope-fix-loop/task-21-sync-to-printwayv3.md) | 1-20, 22-26, 27-32 |

---

## Critical principles (Codex rounds 1-5 confirmed)

1. **Build self-validates, never defers to review.** FE→BE gap, contract shape mismatch, spec drift → catch in build STEP 5 (BLOCK). Review only post-validates what build shipped. Circular review-after-broken-build is the bug we're fixing.
2. **4-tier severity, not 2.** `BLOCK` (deterministic violation), `TRIAGE_REQUIRED` (ambiguous — never silent forward), `FORWARD_DEP` (confirmed not in scope), `ADVISORY` (informational).
3. **Deterministic-first classifier.** Regex/path matching, not LLM. LLM = advisory fallback (P3, not now).
4. **Auto-fix bounded.** Max 3 attempts, stop early on no-progress / out-of-scope / cross-phase impact. NO AskUserQuestion mid-build.
5. **Phase ownership respected.** Auto-fix subagent gets allowlist; touching outside files = `OUT_OF_SCOPE` error + reclassify to NEEDS_TRIAGE.
6. **Rule resolver scope-matched.** L1 capsule injection picks rules per task file extension/path/keywords — not dump every memory rule into every spawn.
7. **Forward-dep disposition.** Next phase `/vg:scope` requires user to pick: accepted/deferred/backlog/invalid. Gate on disposition recorded, not on resolution.
8. **Skills are controller-invoked.** Inside build orchestration, invoke `/vg:deploy` via the Skill tool directly. NOT via `Agent(general-purpose, "Run /vg:deploy ...")` subagent prompt.
9. **Pre-test gate non-interactive by default.** Build is non-interactive. STEP 6.5 reads decision from `vg.config.md` `pre_test.default_env` → ENV-BASELINE.md proposal → `/vg:scope` env-pref. `--interactive` flag opt-in only.
10. **RCRURD single source of truth (Codex round 3).** Task 22 owns the structured YAML schema + parser. Tasks 23 (review runtime) and 24 (codegen helper + AST gate) READ from Task 22 — never independently infer mutation invariants. Existing `**Persistence check:**` Markdown block stays for human readability but the `yaml-rcrurd` fence is the machine contract.
11. **Read-your-writes by default.** RCRURD invariant default: `cache_policy: no_store` + `settle.mode: immediate`. Eventual consistency requires EXPLICIT `settle.mode: poll` + `timeout_ms` declared in the invariant — implicit eventual is forbidden.
12. **R9 UI ↔ API render coherence (Codex round 4).** Task 25 extends Task 22 schema with `ui_assert` block (10 ops covering array/scalar/conditional/attribute layers). DOM render clock independent from API read clock — ui_assert has its own `settle` (poll-based via Playwright `expect.toPass`). Stable selectors required (`data-testid`); text fallback only when text IS the contract.
13. **Lens dispatch is enforced, not trusted (Codex round 5 + sếp's AI-trust concern).** Task 26 makes lens injection auditable end-to-end: `LENS-DISPATCH-PLAN.json` is the trust anchor; coverage gate verifies every applicable (lens × goal) dispatch produced a matching artifact with structural integrity. Worker fabrication caught by M2 MCP action-trace cross-check (external log vs self-reported actions). Capability matched to complexity via M1 tier-aware spawn (Haiku not allowed for complexity ≥ 4 — lens-form-lifecycle / lens-business-coherence require Sonnet+).

14. **Diagnostic events MUST land in events.db (Codex GPT-5.5 round 6 finding).** Hooks emit with `\|\| true` to avoid blocking on telemetry failure; pre-fix this swallowed the `argparse error: unrecognized arguments` exit code from `--gate/--cause/--resolution/--block-file` flags → 0 `vg.block.*` rows ever recorded → Stop hook pairing gate compared 0=0 = PASS forever. Lesson: diagnostic emission is a contract, not a courtesy. Tasks 27-32 close the silent-failure surface — every auto-fire emits attempted+result events (Task 27), every block has structured payload via Task 30 attribution helper, every recurring pattern surfaces via Task 32 correlator. Empirical proof gate (added by Task 27 test): pytest verifies events.db NEVER has `vg.block.*` count = 0 after a run that hit a documented block path.

15. **Pairing gate is empirical contract, not aspirational (Codex GPT-5.5 round 6).** The `vg.block.fired` vs `vg.block.handled` count comparison in `scripts/hooks/vg-stop.sh:20-29` only enforces what reaches events.db. Tasks 28 (dedupe) + 29 (severity routing) extend the contract: same gate × run with no intervening handled ≠ multiple obligations (Task 28 — `vg.block.refired` increments count without creating new pair); severity routing (Task 29) makes warn-tier blocks accumulate without exit 2 but error/critical-tier still hard-block. Without these, the fix-loop's "this gate fires every run" cost is invisible to the pairing gate.

---

## Execution

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task. Implementer prompt: provide the full task file path. Implementer reads ONLY that file (self-contained — code, tests, commands, commit, all in one place). After return, dispatch spec-reviewer + code-quality-reviewer per superpowers:subagent-driven-development workflow. ~30-40 min wall-clock per task × 32 tasks = ~16-21 hours total. **Execution order**: 1-14 (in-scope-fix-loop) → 15-19 (pre-test gate) → 20 (deploy --pre-test) → 22 (RCRURD schema) → 23 (review runtime) → 24 (codegen helper) → 25 (R9 ui_assert) → 26 (lens dispatch enforcement) → 27 (recovery telemetry) → 28 (block dedupe) → 29 (severity routing) → 30 (skill attribution) → 31 (cross-session awareness) → 32 (block correlator) → 21 (PV3 sync, last so dogfood gets the full coverage including diagnostic-v2).

**2. Inline Execution** — execute tasks in this session via superpowers:executing-plans. Faster but loses per-task review isolation.

---

## File structure created by this plan

**New files** (created across tasks 1-20 + 27-32):
```
schemas/build-warning-evidence.schema.json
scripts/lib/severity_taxonomy.py
scripts/lib/phase_ownership.py
scripts/lib/regression_smoke.py
scripts/lib/rule_resolver.py
scripts/lib/pre_test_runner.py            (Task 15 + Correction A)
scripts/lib/deploy_decision.py            (Task 16 + Correction B)
scripts/lib/post_deploy_smoke.py          (Task 17 + Correction C)
scripts/lib/recovery_telemetry.py         (Task 27)
scripts/lib/block_dedupe.py               (Task 28)
scripts/lib/block_severity.py             (Task 29)
scripts/lib/block_context.py              (Task 30)
scripts/validators/audit-recovery-telemetry.py  (Task 27)
scripts/extractors/extract-fe-api-calls.py
scripts/extractors/extract-be-route-registry.py
scripts/validators/verify-fe-be-call-graph.py
scripts/validators/verify-contract-shape.py
scripts/validators/verify-spec-drift.py
scripts/validators/verify-pre-test-tier-1-2.py
scripts/validators/write-pre-test-report.py
scripts/classify-build-warning.py
commands/vg/_shared/build/in-scope-fix-loop.md
commands/vg/_shared/build/in-scope-fix-loop-delegation.md
commands/vg/_shared/build/pre-test-gate.md            (Task 18 + Correction D)
tests/test_severity_taxonomy.py
tests/test_fe_be_call_graph.py
tests/test_contract_shape_validator.py
tests/test_spec_drift_validator.py
tests/test_classify_build_warning.py
tests/test_phase_ownership.py
tests/test_rule_resolver.py
tests/test_pre_test_runner.py
tests/test_deploy_decision.py
tests/test_post_deploy_smoke.py
tests/test_pre_test_gate_integration.py
tests/test_deploy_pre_test_mode.py
tests/test_build_fix_loop_integration.py
tests/test_recovery_telemetry.py          (Task 27)
tests/test_block_dedupe.py                (Task 28)
tests/test_block_severity_routing.py      (Task 29)
tests/test_block_context.py               (Task 30)
tests/test_session_start_cross_session.py (Task 31)
tests/test_block_correlate.py             (Task 32)
tests/fixtures/build-fix-loop-golden/
```

**Modified files**:
```
commands/vg/build.md                                (must_touch_markers + must_emit_telemetry + STEPs 5.5/6.5 wiring)
commands/vg/deploy.md                               (Task 20: --pre-test flag)
commands/vg/_shared/build/post-execution-overview.md  (insert L4a gates)
commands/vg/_shared/build/waves-delegation.md       (capsule bootstrap_rules)
commands/vg/_shared/deploy/overview.md              (Task 20: --pre-test bypass build-complete check)
commands/vg/scope.md                                (forward-dep disposition gate)
commands/vg/_shared/scope/preflight.md
agents/vg-build-task-executor/SKILL.md              (read bootstrap_rules from envelope)
```

**Sync targets** (Task 14 + Task 21):
- `.claude/` mirror (auto via `sync.sh`)
- `codex-skills/` (auto via `vg_sync_codex.py`)
- PrintwayV3 dogfood target: `/Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.claude/` + `.codex/`

---

## Self-review checklist (per superpowers:writing-plans)

**Spec coverage** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| L4a-i FE→BE call graph BLOCK | 3 + 6 |
| L4a-ii Contract shape BLOCK | 4 + 6 |
| L4a-iii Spec drift BLOCK | 5 + 6 |
| L2 Evidence-based classifier (4-tier) | 7 |
| L3 Auto-fix loop STEP 5.5 | 10 |
| L4b Measured rollout for soft baselines | Deferred — opens once telemetry from L4a + L3 lands (post-implementation) |
| L1 Rule resolver | 11 |
| B1 FE call + BE route extractors | 2 |
| B2 Contract shape (method match) | 4 |
| B6 Phase ownership allowlist | 8 |
| B7 Regression smoke runner | 9 |
| Forward-dep disposition gate | 12 |
| Severity taxonomy + evidence schema | 1 |
| Integration test (in-scope-fix-loop) | 13 |
| Mirror sync | 14 + 21 |
| **Pre-Test Gate** | |
| T1 static + T2 local tests + secret scan | 15 |
| Deploy decision (ENV-BASELINE-driven + schema detection) | 16 |
| Post-deploy smoke (total deadline + auth + storageState) + report writer | 17 |
| STEP 6.5 wiring (Skill-invoked deploy + classifier-routed failures) | 18 |
| Pre-test integration test | 19 |
| `/vg:deploy --pre-test` mode | 20 |
| **RCRURD coverage (Codex GPT-5.5 rounds 3-4)** | |
| Structured RCRURD invariant schema + parser (single source of truth) | 22 |
| Mandatory runtime verification per mutation goal in /vg:review | 23 |
| Codegen `expectReadAfterWrite` helper + AST gate | 24 |
| R9 ui_render_truth_mismatch — UI ↔ API render coherence (10 ops) | 25 |
| **AI-trust enforcement (Codex GPT-5.5 round 5 + sếp concern)** | |
| Lens dispatch enforcement: LENS-DISPATCH-PLAN.json + coverage gate + M1 tier-aware + M2 MCP trace cross-check + 7-state matrix | 26 |
| **Diagnostic-v2 (Codex GPT-5.5 round 6 — closes pairing-gate silent-failure surface)** | |
| Recovery telemetry audit (every auto-fire emits attempted+result events) | 27 |
| Block dedupe via `vg.block.refired` (one obligation per gate × run) | 28 |
| Severity routing functional (warn/error/critical change hook behavior) | 29 |
| Skill attribution in payload (auto-populate skill_path/command/step/hook_source) | 30 |
| Cross-session block awareness (SessionStart sees other sessions' unhandled) | 31 |
| Block correlator CLI (recurring/causal/high-velocity detection over events.db) | 32 |
| PV3 dogfood sync (now includes RCRURD 22-25 + lens enforcement 26 + diagnostic-v2 27-32) | 21 |

**Codex feedback coverage** — round 1 + round 2 corrections all inlined into per-task files (Tasks 15-19 each contain "Codex Round 2 Correction X" section at the bottom of their file).

**Type consistency** — `BuildWarningEvidence` schema (Task 1) → produced by Tasks 3/4/5 → consumed by Task 7 → consumed by Tasks 10, 18. `Severity` enum consistent. Path normalization (`:param`) consistent. `phase_dir` argument shape consistent across all validators.

---

## Plan history

- 2026-05-03 v1: original 14-task in-scope-fix-loop plan (Codex round 1 review → APPROVE_WITH_CHANGES)
- 2026-05-03 v2: 14 tasks revised + Pre-Test Gate extension (5 tasks 15-19) added
- 2026-05-03 v3: Codex round 2 review → 9 corrections + Task 20 NEW (`/vg:deploy --pre-test`)
- 2026-05-03 v4: split into per-task files + Task 21 NEW (PV3 sync). Codex round 2 corrections inlined into Tasks 15-19. Plan index slim (~150 lines).
- 2026-05-03 v5: Diagnostic-v2 extension merged (this version). Adds Tasks 27-32 closing the pairing-gate silent-failure surface that Codex GPT-5.5 round 6 surfaced during stale-run BLOCK fix review. Pre-shipped foundation (commits `41a4931` + `ae498ed`) called out as prerequisite. Task 21 dependency expanded to 27-32. Two new principles (14, 15) on diagnostic emission as contract.

Source archive of monolithic v3 (4824-line flat file) available at git history: `git show HEAD~1:docs/superpowers/plans/2026-05-03-vg-build-in-scope-fix-loop.md`.
