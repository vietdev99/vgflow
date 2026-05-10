# v2.72.0 — Codex-skills sync + migrate.md split

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Eliminate codex-skills/claude-commands drift after v2.70.0 (review split) + v2.71.0 (project split). Codex CLI handles review — keeping vg-review/SKILL.md at 7757 lines monolithic is critical context-budget bug. Plus split migrate.md claude-side first so codex side can route through `_shared/migrate/`.

**Architecture:**
1. Split `commands/vg/migrate.md` (1301 lines) into `_shared/migrate/` subdir (4 sub-files), mirror v2.70/v2.71 pattern.
2. Slim `codex-skills/vg-review/SKILL.md` (7757→~500) — route to existing `_shared/review/*` files.
3. Slim `codex-skills/vg-project/SKILL.md` (1728→~500) — route to existing `_shared/project/*` files.
4. Slim `codex-skills/vg-migrate/SKILL.md` (1440→~500) — route to new `_shared/migrate/*` files (created in step 1).

Each codex slim follows `codex-skills/vg-build/SKILL.md` pattern: HARD-GATE-CODEX block (manual mark-step list per A9) + per-step "Read `_shared/X/Y.md` and follow it exactly."

**Tech Stack:** Markdown text manipulation. Mirror byte-identity for `commands/` ↔ `.claude/commands/`. `codex-skills/` canonical-only.

---

## Context

User-flagged drift after v2.70.0/v2.71.0 splits:
> "phần review thì codex cli sẽ đảm nhiệm nên nó rất quan trọng"

Drift table:

| Side | review | project | migrate |
|---|---|---|---|
| Claude (split) | 539 | 222 | 1301 (still monolithic) |
| Codex (still monolithic) | **7757 ⚠** | **1728 ⚠** | **1440** |

`codex-skills/vg-build/SKILL.md` already uses `_shared/build/*` routing pattern — proves codex skills CAN load shared sub-files via "Read X.md and follow it exactly." instruction.

VERSION baseline: 2.71.0. Bump to 2.72.0.

---

## Task 1: Split migrate.md claude-side (preflight + enrich)

migrate.md has 11 steps. Group into 4 sub-files:

| Sub-file | Steps | Lines (approx) |
|---|---|---|
| `_shared/migrate/preflight.md` | 1_parse_args, 2_detect_artifacts, 3_backup_originals | ~180 |
| `_shared/migrate/enrich.md` | 4_enrich_context, 5_generate_contracts | ~300 |
| `_shared/migrate/goals-plans.md` | 6_generate_goals, 6_5_link_plan_goals, 7_attribute_plans | ~360 |
| `_shared/migrate/pipeline-and-validate.md` | 8_write_pipeline_state, 8b_backfill_infra, 9_validate_and_report | ~400 |

**T1 scope:** Extract preflight.md (3 steps).

**Files:**
- Create: `commands/vg/_shared/migrate/preflight.md` + mirror
- Modify: `commands/vg/migrate.md` + mirror (slim routing)
- Test: `tests/test_v2_72_migrate_split_preflight.py` (NEW, 6 tests pattern)

**Slim entry:**

```markdown
### Preflight section (extracted v2.72.0 T1)

Read `_shared/migrate/preflight.md` and follow it exactly.
Includes 3 steps: 1_parse_args, 2_detect_artifacts, 3_backup_originals.
```

**Commit msg:** `refactor(migrate): T1 extract preflight to _shared/migrate/preflight.md (v2.72.0)`

---

## Task 2: Extract enrich

T2: Extract `_shared/migrate/enrich.md` (4_enrich_context, 5_generate_contracts).

**Commit msg:** `refactor(migrate): T2 extract enrich to _shared/migrate/enrich.md (v2.72.0)`

---

## Task 3: Extract goals-plans

T3: Extract `_shared/migrate/goals-plans.md` (6_generate_goals, 6_5_link_plan_goals, 7_attribute_plans).

**Commit msg:** `refactor(migrate): T3 extract goals-plans to _shared/migrate/goals-plans.md (v2.72.0)`

---

## Task 4: Extract pipeline-and-validate (final)

T4: Extract `_shared/migrate/pipeline-and-validate.md` (8_write_pipeline_state, 8b_backfill_infra, 9_validate_and_report).

**Commit msg:** `refactor(migrate): T4 extract pipeline-and-validate to _shared/migrate/pipeline-and-validate.md (v2.72.0)`

---

## Task 5: Ceiling test for migrate split

T5: Add `tests/test_v2_72_migrate_slim_ceiling.py` (NEW, 3 tests). Verify migrate.md ≤ 400 lines + 4 sub-files exist + routing complete.

**Commit msg:** `refactor(migrate): T5 ceiling test + verify slim migrate.md ≤ 400 lines (v2.72.0)`

---

## Task 6: Slim codex-skills/vg-review/SKILL.md

**Source:** 7757 lines monolithic.

**Pattern (mirror `codex-skills/vg-build/SKILL.md` — already slim ~400 lines):**
- Frontmatter + LANGUAGE_POLICY + HARD-GATE-CODEX (preserve current marker list)
- For each STEP: replace inline body with "Read `_shared/review/X.md` and follow it exactly."
- 9 routing entries pointing to existing v2.70.0 `_shared/review/*.md` files

**Files:**
- Modify: `codex-skills/vg-review/SKILL.md` (huge slim, 7757→~500)
- Test: `tests/test_v2_72_codex_review_slim.py` (NEW, 4 tests: line ceiling ≤500, references all 9 _shared/review files, HARD-GATE-CODEX preserved, marker list preserved)

**Commit msg:** `refactor(codex-skills): slim vg-review SKILL.md 7757→~500 routing _shared/review/* (v2.72.0)`

---

## Task 7: Slim codex-skills/vg-project/SKILL.md

**Source:** 1728 lines monolithic.

**Pattern:** Same as T6 but for project. Route to v2.71.0 `_shared/project/*` (5 files).

**Commit msg:** `refactor(codex-skills): slim vg-project SKILL.md 1728→~500 routing _shared/project/* (v2.72.0)`

---

## Task 8: Slim codex-skills/vg-migrate/SKILL.md

**Source:** 1440 lines monolithic.

**Pattern:** Same. Route to NEW v2.72.0 `_shared/migrate/*` (4 files from T1-T4).

**Commit msg:** `refactor(codex-skills): slim vg-migrate SKILL.md 1440→~500 routing _shared/migrate/* (v2.72.0)`

---

## Task 9: VERSION + CHANGELOG + tag + push

VERSION 2.71.0→2.72.0. CHANGELOG entry. Tag `v2.72.0`. Push. GitHub release.

---

## Constraints

- VERBATIM extraction for migrate.md split (T1-T4) — NO behavior change
- Codex slims (T6-T8): preserve HARD-GATE-CODEX manual mark-step blocks (A9 work) + frontmatter contract
- Mirror byte-identity for `commands/` ↔ `.claude/commands/` pairs
- `codex-skills/` canonical-only
- New commit per task. No --amend, no --no-verify

## Execution mode

Subagent-driven. Suggested batches:
- **Batch A:** T1 + T2 (migrate split first half)
- **Batch B:** T3 + T4 (migrate split second half)
- **Batch C:** T5 (ceiling)
- **Batch D:** T6 (codex-review slim — biggest, alone)
- **Batch E:** T7 + T8 (codex-project + codex-migrate slim)
- **Release:** T9
