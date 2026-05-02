# VG Remaining Commands — Batch Cleanup Spec

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R5 (final round, after R1-R4 dedicated specs proven)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`
**Covers:** All VG commands not addressed by dedicated specs

---

## 1. Background

After R1-R4 dedicated specs (blueprint, build, test, review, accept, project, scope, phase, roam — 9 commands), ~40 VG commands remain. This batch spec covers them with a uniform lightweight cleanup pattern.

### 1.1 Scope of "remaining commands"

**Tier B residual (5 commands, 2,388 lines)** — cross-cutting workflow:
- `debug` (399), `regression` (282), `deploy` (588), `scope-review` (670), `security-audit-milestone` (341), `roadmap` (377), `specs` (457) — wait, roadmap+specs are V5 pipeline residual

Actually let me reorganize per Tier categorization in user discussion:

**V5 pipeline small (2 commands, 834 lines):**
- `roadmap` (377) — derives phases from PROJECT.md requirements
- `specs` (457) — creates SPECS.md for a phase

**Cross-cutting workflow (6 commands, 2,673 lines):**
- `debug` (399) — bug-fix loop targeted
- `regression` (282) — full regression sweep
- `deploy` (588) — multi-env deploy
- `scope-review` (670) — cross-phase scope validation
- `security-audit-milestone` (341) — cross-phase threat audit

**Maintenance & lifecycle (~16 commands, 5,120 lines):**
- `migrate` (1301) — convert legacy GSD to VG
- `update` (640), `recover` (277), `reapply-patches` (407), `extract-utils` (455), `polish` (218)
- `health` (347), `doctor` (147), `integrity` (196), `gate-stats` (181), `telemetry` (206), `validators` (109)
- `complete-milestone` (232), `add-phase` (270), `remove-phase` (243), `insert-phase`, `milestone-summary` (98)
- `migrate-state` (169), `sync` (120)

**Design / bootstrap / learn (10 commands, ~1,693 lines):**
- `design-extract` (367), `design-scaffold` (281), `design-system` (227), `design-reverse` (136)
- `bootstrap` (127), `lesson` (109), `learn` (256)
- `amend` (323), `prioritize` (317), `progress` (329), `override-resolve` (143), `bug-report` (173), `rule` (47), `next` (375)

### 1.2 Common pattern across all remaining

Most are < 500 lines (already at Anthropic ceiling). They need:
1. **Hook integration** (inherited automatically — no per-command code)
2. **Imperative language pass** — replace "should/may/will" with "MUST / Do NOT / STEP X"
3. **HARD-GATE block** at top
4. **Red Flags addendum** to vg-meta-skill.md (1-3 entries per command, batched)
5. **Frontmatter strengthening** — add `<cmd>.tasklist_shown` + `<cmd>.native_tasklist_projected` to must_emit_telemetry if missing

NO subagent extraction needed (most are simple workflows).

### 1.3 Files >500 lines requiring slim+refs (NOT just migrate — Codex review correction)

Original spec claimed migrate was the ONLY remaining file >500 lines. **Codex audit caught this error.** Actual files >500 lines requiring slim+refs treatment:

| Command | Lines | Treatment |
|---|---|---|
| `migrate` | 1,301 | Slim + 4-6 refs (most complex; GSD→VG conversion logic) |
| `scope-review` | 670 | Slim + 3 refs (cross-phase scope validation) |
| `update` | 640 | Slim + 3 refs (3-way merge with park conflicts) |
| `deploy` | 588 | Slim + 3 refs (multi-env: sandbox/staging/prod) |

All 4 require:
- Slim entry SKILL.md (≤500 lines)
- Reference file split for body
- NO subagent (single-task workflows)
- Uniform imperative cleanup
- Per-command audit of unique patterns (idempotency for migrate, conflict-park for update, env-state for deploy, cross-phase scan for scope-review)

Files in 400-500 range (treated as borderline — slim only if obvious split available, else imperative cleanup):
- `extract-utils` (455), `map` (442), `reapply-patches` (407)

All other ~30 commands: imperative cleanup only (no slim+refs).

### 1.4 Goals

- Apply uniform cleanup pattern to ~38 remaining commands
- Reduce `migrate` from 1,301 to ≤500 (with refs)
- Apply imperative + HARD-GATE + Red Flags universally
- Inherit blueprint pilot's tasklist projection fix for ALL
- Add per-command Red Flags to vg-meta-skill.md (batched)
- NO new subagents

### 1.5 Non-goals

- Major architectural changes to any command
- Per-command dedicated specs (this IS the batch)
- Codex mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as all other specs.

---

## 3. Cleanup template (applied uniformly)

For each command in scope:

### 3.1 Frontmatter audit + strengthen

Check `runtime_contract.must_emit_telemetry` — ensure these events listed:
```yaml
- "<cmd>.tasklist_shown"
- "<cmd>.native_tasklist_projected"
- "<cmd>.started"
- "<cmd>.completed"
```

Add if missing. Inherit blueprint pilot's hook fix → projection event will fire.

### 3.2 Top-of-file insert: HARD-GATE + Red Flags

After frontmatter, insert:
```markdown
<HARD-GATE>
You MUST follow the steps below in order. The PreToolUse hook will block
spawning step-active without TodoWrite projected. The Stop hook will block
run-complete if must_write paths are not satisfied.
</HARD-GATE>

## Red Flags
| Thought | Reality |
|---|---|
| (1-3 command-specific entries — see §4 per-command) |
```

### 3.3 Imperative language pass

Search for descriptive verbs and replace:
- "should" → "MUST" (or remove if optional)
- "may" → keep only for genuinely optional, otherwise replace with "MUST"
- "will" (future tense narrative) → imperative directive
- "the first action is X" → "STEP 1: Do X"

Use sed or scripted refactor — do NOT manually edit each file.

### 3.4 Reference file split (only if file >500 lines)

For files >500 lines (only `migrate` in remaining scope):
- Create `_shared/<cmd>/` directory
- Split by checklist group (use existing emit-tasklist.py group structure if exists, else by step)
- Slim entry SKILL.md ≤500 lines with reference load instructions

### 3.5 Red Flags batching to vg-meta-skill.md

Append per-command Red Flags section at end of `vg-meta-skill.md`:
```markdown
## <Command>-specific Red Flags
| Thought | Reality |
|---|---|
| (entries) |
```

---

## 4. Per-command Red Flags (the only command-specific content)

### V5 pipeline small

**roadmap (377):**
| Thought | Reality |
|---|---|
| "Skip phase ordering, blueprint will figure out"      | Roadmap order drives subsequent phase dependencies |
| "Coverage validation optional"                        | Roadmap MUST cover all PROJECT.md requirements |

**specs (457):**
| Thought | Reality |
|---|---|
| "Quick spec, AI-draft is fine"                       | AI-draft mode requires user approval; --user-guided for full discussion |
| "Reuse spec from prior phase"                        | Each phase has own SPECS.md scope; copy = lose phase-specific decisions |

### Cross-cutting workflow

**debug (399):**
| Thought | Reality |
|---|---|
| "Skip classification, jump to fix"                   | Targeted bug-fix requires classify (root cause vs symptom vs config) |
| "Verify with user fast, just confirm"                | User verification gate is mandatory; theatre-confirm = bug returns |

**regression (282):**
| Thought | Reality |
|---|---|
| "Run only changed phase tests"                       | Regression = ALL accepted phases, by definition |
| "Auto-fix loop max 1 iteration"                      | Default 3 iterations; tightening masks real regressions |

**deploy (588):**
| Thought | Reality |
|---|---|
| "Sandbox env enough, skip staging"                   | Multi-env spec: each env has own DEPLOY-STATE block |
| "Reuse last deploy state"                            | DEPLOY-STATE.json must be fresh per invocation |

**scope-review (670):**
| Thought | Reality |
|---|---|
| "Cross-phase conflicts rare, skip detection"         | scope-review catches overlap/conflict undetected by per-phase scope |
| "Just look at recent phases"                         | All scoped phases must be cross-validated, not just recent |

**security-audit-milestone (341):**
| Thought | Reality |
|---|---|
| "Per-phase audit enough, skip milestone aggregate"  | Milestone audit applies decay + correlation across phases |
| "Skip threats with low individual severity"          | Composite risk emerges from low-individual + cross-phase pattern |

### Maintenance & lifecycle

**migrate (1301) — refactored to slim+refs:**
| Thought | Reality |
|---|---|
| "Migration looks done after first phase"             | Idempotent rerun safe; rollback path documented |
| "Skip backup before migrate"                         | --backup MUST run; rollback depends on backup |

**update (640):**
| Thought | Reality |
|---|---|
| "3-way merge auto-resolve all conflicts"             | Conflicts park to /vg:reapply-patches for review |
| "Skip --check before --apply"                        | --check shows dry-run diff; --apply without check = surprise |

**health (347), doctor (147), integrity (196), gate-stats (181), telemetry (206), recover (277), reapply-patches (407), extract-utils (455), polish (218):**

Generic Red Flags for tooling commands:
| Thought | Reality |
|---|---|
| "Tooling output cosmetic, ignore"                    | Tooling commands report state; ignored output = drift undetected |
| "Quick scan enough"                                  | Each tooling has specific gate purpose; quick = miss |

**complete-milestone (232), add-phase (270), remove-phase (243), milestone-summary (98), migrate-state (169), sync (120):**

Lifecycle commands — Red Flags:
| Thought | Reality |
|---|---|
| "Skip security audit before complete-milestone"      | Cross-phase threat correlation required pre-completion |
| "remove-phase without renumber"                      | Subsequent phases reference indices; renumber required |
| "Sync skip --check"                                  | Sync without check = unexpected file replacements |

### Design / bootstrap / learn / misc

**design-extract (367), design-scaffold (281), design-system (227), design-reverse (136):**
| Thought | Reality |
|---|---|
| "Skip design-extract, code from memory"              | Design fidelity gates require structural refs |
| "Auto-pick design tool, no user choice"              | Multi-tool selector requires user decision (Pencil/PenBoard/Figma/etc.) |

**bootstrap (127), lesson (109), learn (256):**
| Thought | Reality |
|---|---|
| "Auto-promote bootstrap candidates"                  | User gate required; auto-promote = unverified rules in production |
| "Skip lesson capture this round"                     | Lessons compound across rounds; skipping = repeated mistakes |

**amend (323):**
| Thought | Reality |
|---|---|
| "Skip cascade impact analysis"                       | Mid-phase change impacts downstream — analysis mandatory |

**prioritize (317), progress (329):**
| Thought | Reality |
|---|---|
| "Just show pending phases"                           | Prioritize ranks by impact + readiness; pending list ≠ priority |
| "Progress = % done, simple"                         | Per-phase artifact status drives progress, not %% |

**override-resolve (143), bug-report (173), rule (47), next (375):**

Routine utilities — minimal Red Flags:
| Thought | Reality |
|---|---|
| "Override-resolve auto-clean"                        | Manual review required — auto-clean violates audit |
| "Skip bug-report opt-in default"                     | Workflow bugs auto-detect; opt-out = lost feedback |

---

## 5. Implementation pattern (uniform)

For each command:
1. Read existing command file
2. Detect frontmatter must_emit_telemetry
3. Add missing tasklist_shown + native_tasklist_projected events if absent
4. Insert HARD-GATE + Red Flags block after frontmatter
5. Run sed-based imperative language pass
6. Append command-specific Red Flags to `vg-meta-skill.md`
7. If file >500 lines (only migrate): split into refs

Total automation possible — most cleanup is mechanical text transformation.

---

## 6. File and directory layout

```
commands/vg/
  <30+ small commands>.md                   IMPERATIVE CLEANUP + frontmatter strengthen
  
  # 4 files >500 lines requiring slim+refs (Codex review correction):
  migrate.md                                REFACTOR: 1,301 → ~500 lines + refs
  scope-review.md                           REFACTOR: 670 → ~400 lines + refs
  update.md                                 REFACTOR: 640 → ~400 lines + refs
  deploy.md                                 REFACTOR: 588 → ~400 lines + refs
  
  _shared/migrate/                          NEW
    overview.md, detection.md, conversion.md, rollback.md, verification.md
  _shared/scope-review/                     NEW
    overview.md, conflict-detection.md, gap-detection.md
  _shared/update/                           NEW
    overview.md, merge-strategy.md, conflict-park.md
  _shared/deploy/                           NEW
    overview.md, env-handling.md, deploy-state.md
  
  _shared/vg-meta-skill.md                  EXTEND — append per-command Red Flags sections (Codex caution: keep command-specific, don't dump globally)

scripts/
  refactor-imperative-pass.sh               NEW utility — sed-based descriptive→imperative replace
```

---

## 7. Error handling, migration, testing, exit criteria

### 7.1 Error handling

All blocks follow blueprint pilot §4.5. Per-command errors handled by inherited Stop hook checking each command's own runtime_contract.

### 7.2 Migration

- All existing command runs: stand as-is.
- Per-command frontmatter additions: backward-compatible (adding new must_emit events; existing runs may have missing events but new runs comply).
- Defer: Codex mirror.

### 7.3 Testing

**Static (pytest), batched:**
- `test_remaining_commands_imperative.py` — for each command in scope, grep for forbidden descriptive verbs ("should/may/will" in instruction context), assert minimum count
- `test_remaining_commands_hard_gate.py` — assert HARD-GATE block present after frontmatter
- `test_remaining_commands_red_flags.py` — assert Red Flags table present
- `test_remaining_commands_telemetry.py` — assert tasklist_shown + native_tasklist_projected in must_emit_telemetry
- `test_meta_skill_extended.py` — assert per-command Red Flags sections appended
- `test_migrate_slim_size.py` — assert migrate.md ≤ 600 lines

**Empirical dogfood (sample):**
- Run 3-4 commands from different tiers (e.g., debug, deploy, design-extract, migrate) on PrintwayV3
- Assert: each emits native_tasklist_projected ≥ 1

### 7.4 Exit criteria — batch cleanup PASS requires ALL of:

1. All ~30+ small commands pass static tests (imperative + hard-gate + red-flags + telemetry frontmatter)
2. **4 large files (migrate, scope-review, update, deploy)** all ≤ 600 lines after slim+refs (Codex review correction — was wrongly only migrate)
3. Sampled commands emit native_tasklist_projected (verified via dogfood subset)
4. `vg-meta-skill.md` extended with per-command Red Flags (count: ~20+ new sections, command-specific NOT global dump per Codex caution)
5. Stop hook fires correctly for sampled commands

Batch PASS = R5 complete = full VG pipeline + all auxiliary commands aligned with new template.

---

## 8. Round 5 sequencing

This batch is R5 (final round). Reasons:
- Pattern proven across R1-R4 dedicated specs
- Most commands need only mechanical cleanup
- migrate is the only larger refactor — handled with same template
- Dogfood verification can sample (not exhaustive) per command

After R5 PASS, full VG harness aligned: 9 dedicated specs + this batch = ~50 commands all using progressive disclosure + imperative + hooks + diagnostic.

---

## 9. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Siblings: All 8 dedicated specs (blueprint, build, test, review, accept, project, scope, phase, roam)
- Imperative pass utility: `scripts/refactor-imperative-pass.sh` (new)
- vg-meta-skill.md: extended with per-command Red Flags appendices

---

## UX baseline (mandatory cross-flow)

This flow MUST honor the 3 UX requirements baked into R1a blueprint pilot:
- **Per-task artifact split** — large artifacts (PLAN, contracts, goals,
  results) write Layer 1 per-unit + Layer 2 index + Layer 3 flat concat.
  Consumers use `scripts/vg-load.sh` for partial loads.
- **Subagent spawn narration** — every `Agent()` call wrapped with
  `bash scripts/vg-narrate-spawn.sh <name> {spawning|returned|failed}` for
  GSD-style green/cyan/red chip UX.
- **Compact hook stderr** — success silent, block 3-line + file pointer.
  Full diagnostic to `.vg/blocks/{run_id}/{gate_id}.md`.

Source: `docs/superpowers/specs/_shared-ux-baseline.md` (full pattern + code).
