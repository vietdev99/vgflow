# CrossAI M1 Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship infrastructure (config schema, registry helpers, build-loop extraction seam, init/migrate helpers, template docs) for CrossAI multi-stage multi-primary design — WITHOUT changing existing build CrossAI behavior.

**Architecture:** Rename `crossai_skip_validation.py` → `crossai_config.py` and extend it with typed config parsing that stays compatible with the existing anti-rationalization gate. Introduce `crossai_loop.py` as an extraction seam for the CURRENT build loop first: same parallel Codex+Gemini execution, same events, same output paths, same brief semantics, just moved behind a library boundary. Scope/blueprint wrappers may exist in M1 as non-activated helpers only; mainline command integration and lazy migration activation stay additive and route through `/vg:project --init-only` plus shared migration helpers instead of a separate public workflow.

**Tech Stack:** Python 3.12+, pytest, custom YAML-ish parser (extending existing `_parse_crossai_clis`), subprocess for CLI invocation, sqlite3 events.db, existing `/vg:project` config generation pipeline, bash slim entries (stage activation touched in M2/M3 only).

**Spec:** `docs/superpowers/specs/2026-05-06-crossai-multi-stage-multi-primary-design.md`

---

## File Structure

**New files (sources):**
- `scripts/lib/crossai_config.py` — rename target, extends from existing `crossai_skip_validation.py`. Adds typed config parsing (`CLISpec`, `StageConfig`, thresholds) while preserving current CLI-availability validation semantics.
- `scripts/lib/crossai_loop.py` — orchestration library extraction seam. M1 mirrors CURRENT build behavior exactly (parallel Codex+Gemini, build events, findings shape, `crossai-build-verify` path, diff-aware brief). M3 will add generic multi-stage orchestration on top.
- `scripts/vg-scope-crossai-loop.py` — optional non-activated wrapper/helper for scope-stage brief packing. Not wired into mainline M1 command flow.
- `scripts/vg-blueprint-crossai-loop.py` — optional non-activated wrapper/helper for blueprint-stage brief packing. Not wired into mainline M1 command flow.

**Modified files (sources):**
- `scripts/lib/crossai_skip_validation.py` — kept as compatibility shim for current imports; removal explicitly deferred beyond M1.
- `scripts/vg-build-crossai-loop.py` — refactor: keep public CLI signature and all current behavior, but delegate the existing orchestration core to `crossai_loop.py`.
- `scripts/vg-orchestrator/__main__.py` — add shared helper entry points for crossai config rendering/migration planning. Optional `migrate-crossai` helper may exist, but public integration target is `/vg:project --init-only`.
- `scripts/vg_generate_config.py` — extend generated config/template output so `/vg:project --init-only` can include CrossAI sections without bypassing the normal config derivation pipeline.
- `tests/fixtures/phase0-diagnostic-smoke/vg.config.md` — extend with new sections: `crossai.policy`, `crossai.heuristic_thresholds`, `crossai_clis[].role`, `crossai_stages.{scope,blueprint,build}`. Commented defaults to keep the fixture inert and migration-testable.

**Mirror sync (after every source change):**
- `.claude/scripts/lib/crossai_config.py`
- `.claude/scripts/lib/crossai_loop.py`
- `.claude/scripts/vg-scope-crossai-loop.py`
- `.claude/scripts/vg-blueprint-crossai-loop.py`
- `.claude/scripts/vg-build-crossai-loop.py`
- `.claude/scripts/vg-orchestrator/__main__.py`
- (no mirror for `tests/fixtures/...` — fixtures are source-only)

**New tests:**
- `scripts/tests/test_crossai_config_resolve.py` (Tasks 2–4 cover this)
- `scripts/tests/test_crossai_loop_library.py` (Tasks 5–7 cover this)
- `scripts/tests/test_crossai_project_init_crossai.py` (Task 10)
- `scripts/tests/test_crossai_migrate_plan.py` (Task 11)
- `scripts/tests/test_crossai_skip_validation_compat.py` (Task 1)
- `scripts/tests/test_crossai_build_legacy_parity.py` (build behavior freeze before/after extraction)

---

## Task Index

Per-task split files in `2026-05-06-crossai-m1-infrastructure/`:

- [Task 01: Rename `crossai_skip_validation.py` → `crossai_config.py` + import shim](2026-05-06-crossai-m1-infrastructure/task-01-rename-crossai-skip-validation.md)
- [Task 02: Add `CLISpec` + `StageConfig` dataclasses](2026-05-06-crossai-m1-infrastructure/task-02-stageconfig-dataclasses.md)
- [Task 03: Implement `resolve_stage_config(stage, repo_root)`](2026-05-06-crossai-m1-infrastructure/task-03-resolve-stage-config.md)
- [Task 04: Add heuristic thresholds parser](2026-05-06-crossai-m1-infrastructure/task-04-heuristic-thresholds.md)
- [Task 05: Skeleton `scripts/lib/crossai_loop.py` + build-legacy extraction seam](2026-05-06-crossai-m1-infrastructure/task-05-crossai-loop-skeleton.md)
- [Task 06: Implement build-legacy orchestration parity in `crossai_loop.py`](2026-05-06-crossai-m1-infrastructure/task-06-run-loop-single-primary.md)
- [Task 07: Refactor `vg-build-crossai-loop.py` to use library with zero behavior drift](2026-05-06-crossai-m1-infrastructure/task-07-refactor-build-wrapper.md)
- [Task 08: Scope wrapper helper (not activated in M1)](2026-05-06-crossai-m1-infrastructure/task-08-scope-wrapper.md)
- [Task 09: Blueprint wrapper helper (not activated in M1)](2026-05-06-crossai-m1-infrastructure/task-09-blueprint-wrapper.md)
- [Task 10: Integrate CrossAI config generation into `/vg:project --init-only`](2026-05-06-crossai-m1-infrastructure/task-10-init-crossai-config.md)
- [Task 11: Add additive migration planner + optional `migrate-crossai` helper](2026-05-06-crossai-m1-infrastructure/task-11-migrate-crossai-config.md)
- [Task 12: Extend `tests/fixtures/.../vg.config.md` template](2026-05-06-crossai-m1-infrastructure/task-12-extend-vg-config-template.md)
- [Task 13: Final mirror parity sweep + regression run](2026-05-06-crossai-m1-infrastructure/task-13-final-mirror-parity.md)

---

## Acceptance criteria for M1

- All existing `scripts/tests/test_crossai_skip_validation.py` tests still pass (compat shim works)
- All existing build CrossAI behavior tests still pass unchanged, including a new parity test that freezes current outputs/events/paths
- All existing `scripts/tests/test_*` tests pass (full regression suite)
- New tests (Tasks 1–11) all pass; test count may exceed the original rough estimate because extraction parity is now explicit
- `/vg:project --init-only` remains the authoritative config path and emits valid CrossAI sections through the standard generator path
- Optional `python3 .claude/scripts/vg-orchestrator migrate-crossai --dry-run` on a PV3-style project shows additive diff only (no removals, no implicit write)
- `python3 .claude/scripts/vg-build-crossai-loop.py --phase 4.2 --iteration 1` on a sample fixture invokes via library and produces the same events/output shape/path as before refactor
- `.claude/scripts/...` mirrors byte-identical to `scripts/...` after every commit (final sweep Task 13)

---

## Self-Review

**Spec coverage check:**
- Q15 (library + thin wrappers) → Tasks 5, 6, 7, 8, 9 ✅
- Q16 (rename + extend `crossai_config.py`) → Tasks 1, 2, 3, 4 ✅
- Q21 (`/vg:project --init` auto-detect) → Task 10 ✅
- Q22 (lazy migrate at first invocation) → M1 prepares shared migration planner in Task 11; activation path remains deferred until the three stages can use it consistently ✅
- vg.config.md template extension → Task 12 ✅
- Mirror parity discipline → enforced per task + final sweep Task 13 ✅
- Existing build CrossAI tests preserved → Tasks 5–7 explicit extraction-parity gate ✅

**Placeholder scan:** No "TBD"/"TODO"/"implement later" in tasks. All file paths exact. All test code concrete (no "write tests for above").

**Type consistency:** `StageConfig`/`CLISpec` dataclass field names defined in Task 2 are reused verbatim in Tasks 3, 5, 6, 10. `pack_review_brief(phase_dir, phase_num, iteration, max_iter) -> str` signature stays consistent across Tasks 7, 8, 9. The build-library extraction in Tasks 5–7 must preserve existing event names, findings JSON shape, output directory naming, and exit-code semantics from `vg-build-crossai-loop.py`.

**Scope check:** 13 tasks, each producing a green-tested commit. The highest-risk refactor area is constrained to build-loop extraction with parity tests first; scope/blueprint work stays helper-only in M1, and migration wiring stays non-destructive.

---

**Next:** see `task-01-rename-crossai-skip-validation.md` to start.
