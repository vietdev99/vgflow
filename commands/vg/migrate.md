---
name: vg:migrate
description: Convert legacy GSD phase artifacts to VG format
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "migrate.started"
    - event_type: "migrate.completed"
---

<rules>
1. **Non-destructive** — never delete GSD originals. Move to `.gsd-backup/` within phase dir.
2. **MERGE, DO NOT OVERWRITE (tightened 2026-04-17)** — any existing artifact with user-authored content must be merged, not replaced. Agent writes to `{file}.staged` (not target). Before promoting staging → target, run preservation gates:
   - **ID preservation**: every `D-XX` (decisions) / `G-XX` (goals) / `Task N` / endpoint path in original MUST exist in staging. Missing = agent dropped content → ABORT, original untouched.
   - **Body preservation**: each element's body text must be ≥ 80% similar to original (`difflib.SequenceMatcher`). Lower ratio = agent rewrote prose → ABORT.
   - **On fail**: staging kept at `{file}.staged` for user inspection; backup at `.gsd-backup/{file}.{original-ext}`.
   Applies to: CONTEXT.md (step 4), API-CONTRACTS.md (step 5), TEST-GOALS.md (step 6), PLAN.md (step 7).
3. **Idempotent** — running migrate twice on same phase produces same result. Skip already-converted artifacts.
4. **Config-driven** — all format decisions from vg.config.md (contract_format, scan_patterns, etc.)
5. **No hardcoded project values** — endpoint paths, file locations, domain names all from config or code scan.
6. **Profile enforcement** — `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "migrate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/migrate.done"` at end.
</rules>

<objective>
Convert a phase that was planned/built using GSD workflows into VG-native format.
Ensures all VG pipeline steps (review, test, accept) can run on the migrated phase.

When to use:
- Project previously used GSD, now switching to VG
- Phase has CONTEXT.md (GSD format) but no API-CONTRACTS.md or TEST-GOALS.md
- Phase has old-style PLAN.md without VG task attributes
- `/vg:next` shows phase as `legacy_gsd` type
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

### Preflight section (extracted v2.72.0 T1)

Read `_shared/migrate/preflight.md` and follow it exactly.
Includes 3 steps: 1_parse_args, 2_detect_artifacts, 3_backup_originals.

### Enrich section (extracted v2.72.0 T2)

Read `_shared/migrate/enrich.md` and follow it exactly.
Includes 2 steps: 4_enrich_context, 5_generate_contracts.

### Goals + plans (extracted v2.72.0 T3)

Read `_shared/migrate/goals-plans.md` and follow it exactly.
Includes 3 steps: 6_generate_goals, 6_5_link_plan_goals, 7_attribute_plans.

### Pipeline + validate (extracted v2.72.0 T4 — final)

Read `_shared/migrate/pipeline-and-validate.md` and follow it exactly.
Includes 3 steps: 8_write_pipeline_state, 8b_backfill_infra, 9_validate_and_report.

</process>

<success_criteria>
- GSD originals backed up to .gsd-backup/
- CONTEXT.md enriched with Endpoints/UI/Test sub-sections per decision
- API-CONTRACTS.md generated from existing code (if not --skip-contracts)
- TEST-GOALS.md generated with goals + infra_deps field (if not --skip-goals)
- PLAN.md tasks attributed with VG task attributes
- PIPELINE-STATE.json written with migrated status
- Validation passes with 0 FAIL items
- Phase routable by /vg:next (shows as review-ready)
</success_criteria>
