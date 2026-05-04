# Universal Tasklist Enforcement (Bug L) — Audit + Hybrid Validator Design

**Date:** 2026-05-04
**Source:** Sếp Dũng dogfood feedback during Track A execution. Discovered Task 34 (single-layer projection enforcement, just shipped) is insufficient: AI bypasses tasklist creation in multiple flows (review, blueprint, build), leading to E2E step skipped, hook BLOCK evaded with `vg.block.handled` emit but no real TodoWrite call (PV3 4.1: 15 bypass instances).
**Status:** v1 — pre-implementation. Audit-first approach approved.

---

## Goal

Make tasklist creation a **hard prerequisite** for all 8 pipeline flows (review, blueprint, build, test, accept, scope, deploy, roam). The tasklist must be:

1. **Created** (not just declared) before any execution step
2. **Detailed**: minimum 2-layer hierarchy (parent steps + sub-steps)
3. **Bypass-resistant**: hook gates close all currently-known loopholes

Universal enforcement extends Task 34's surface (review-only, single-layer) to all flows + hierarchical content shape.

## Non-goals

- Replace TodoWrite native API (still uses `[{content, status, activeForm}]`)
- Force template adoption on flows that don't have one yet (graceful migration via syntactic floor)
- Block ad-hoc / manual TodoWrite usage outside slim-entry pipeline contexts

---

## Architecture (NEW Track D — 2 tasks)

### Task 44a — Audit (~30-45min subagent)

Dedicated audit phase: read review.md / blueprint.md / build.md slim entries + `scripts/hooks/vg-pre-tool-use-bash.sh` + events.db PV3 4.1 historical data. Identify all bypass patterns + hook gaps.

**Inputs:**
- 3 slim entries (review, blueprint, build) — full read
- Existing hook: `scripts/hooks/vg-pre-tool-use-bash.sh`
- Task 34 work: `commands/vg/_shared/lib/tasklist-projection-instruction.md` + tests
- PV3 events.db: query `vg.block.fired` + `vg.block.handled` event pairs for review runs (15 historical bypasses)

**Output:** `docs/superpowers/audits/2026-05-04-tasklist-enforcement-audit.md`
- Bypass pattern catalog (each pattern: trigger, evidence, fix path)
- Per-flow gap matrix: which slim entries enforce, which don't, where the holes are
- Recommended Task 44b implementation scope (concrete validator + template list)

### Task 44b — Implementation (~3-4h)

Based on audit findings:

**Hybrid validator:** `scripts/lib/tasklist_validator.py`
- Syntactic floor (universal, all flows):
  - ≥3 parent items
  - ≥2 sub-items per parent
  - ≥20 chars per `content` field (catches "do thing" / "check thing")
  - Detects parent-child via prefix convention: parents start with `[Phase N]` / `[STEP N]` / `[TASK N]`; subs use `  →` / `  -` / `[Phase N.M]`
- Template ceiling (per slim entry that opts in):
  - Slim entry frontmatter declares `tasklist_template:` block listing required parent prefixes
  - Validator checks AI's TodoWrite output contains all declared parents (in any order; matching by prefix string)

**Hook upgrade:** `scripts/hooks/vg-pre-tool-use-bash.sh`
- Replace simple file-exists check with `tasklist_validator.py` call
- BLOCK output routes through Task 33 wrapper (`scripts/lib/blocking-gate-prompt.sh`):
  - `[a]` autofix: spawn AI to regenerate tasklist with template hint
  - `[s]` skip-with-override: `tasklist-debt` entry logged
  - `[r]` route to /vg:amend (rare — should not happen for tasklist gate)
  - `[x]` abort

**Slim entry templates** (declared in frontmatter, ≤20 lines per entry):
- `commands/vg/review.md`: `tasklist_template:` listing all required Phase entries (1, 2, 2a.5, 2.5, 3, 4, 5)
- `commands/vg/blueprint.md`: STEP 1-6 parents
- `commands/vg/build.md`: STEP 1-7 parents
- 5 other flows: opt-in template later (syntactic floor only initially)

**Integration:** Task 33 wrapper handles BLOCK presentation (4-option AskUserQuestion).
**Telemetry:** new event `tasklist_enforcement_blocked` (warn, declared in each slim entry).

---

## Cross-task contracts (locked)

- **Validator exit codes**: 0 = pass, 1 = BLOCK (route through wrapper)
- **Tasklist content min chars**: 20 (configurable per slim entry via `tasklist_validator_min_content_chars`)
- **Parent prefix regex**: `^\[(?:Phase|STEP|TASK|Pha)\s+\d+(?:\.\d+)?\]` (multi-language tolerant)
- **Sub-item detection**: indent ≥2 spaces OR prefix `→` / `↳` / `[Phase N.M]`
- **Template-match rule**: AI tasklist must contain ALL declared parents (subset match by prefix); extra parents OK (AI can decompose further)
- **Override-debt severity vocab**: `tasklist-incomplete` → `medium` debt level
- **Telemetry event format**: `<command>.tasklist_enforcement_blocked` (e.g., `review.tasklist_enforcement_blocked`)

## Backward compat

- Task 34 surface unchanged. Task 44b extends, doesn't replace
- Slim entries without `tasklist_template:` frontmatter fall through to syntactic-floor-only check (same enforcement, weaker contract)
- Existing TodoWrite call sites keep working (validator runs alongside existing checks)

## Sequencing (where Task 44 inserts in plan)

```
Track A (DONE, 5 tasks): 34 → 33 → 35 → 36a → 36b ✅

Track D (NEW, 2 tasks):
  44a (audit) → 44b (implement) ← inserts HERE, before Track B

Track B (4 tasks): 39 ‖ 38 → 37 ‖ 40
Track C (3 tasks): 41 → 42 + 43
```

Rationale: Track B/C executor subagents (Tasks 37-43) will themselves benefit from Task 44b enforcement when they write their own tasklists. Insert before Track B = upstream improvement.

## Open questions (for audit phase)

1. Are there existing hook bypass paths beyond `vg.block.handled` emit-without-TodoWrite? Audit identifies via events.db replay.
2. Do test/accept/scope/deploy/roam slim entries already have native tasklist contracts? If yes, syntactic floor is sufficient initially.
3. What's the minimum viable template set for review/blueprint/build to make rollout meaningful?
