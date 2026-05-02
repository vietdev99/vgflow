# Blueprint Pilot Plan — Reality Sync + Phase F Addendum

**Goal:** Reconcile `docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot.md` with shipped reality (Tasks 1-27 done) and append a new executable Phase F for downstream split-file consumption (build/review/test/roam/accept).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-blueprint-pilot-design.md` (R1a canary pilot baseline).

**Branch:** `feat/rfc-v9-followup-fixes`.

---

## Change Set

Three orthogonal updates to the same plan file:

### 1. Mark Tasks 1-27 complete (audit trail preservation)

For each of the 27 original tasks: tick every `- [ ]` to `- [x]`, and append a **Status:** line at task header level citing the commit SHA(s) that delivered it. Original step content (test code, bash commands) remains intact for future reference / replay.

User confirmed Tasks 25 (pytest), 26 (PrintwayV3 sync), 27 (dogfood) are done despite no explicit commit.

### 2. Append Phase E — Post-pilot follow-on work (history-only, NOT executable)

Six commits landed AFTER the original 27 tasks, all within the same blueprint pilot scope. They became necessary once dogfooding revealed gaps. Documenting them as Phase E tasks (with `Status: ✅ Shipped` markers) makes them discoverable without polluting executable structure.

Commits to document:
- `30c9a05` — Hierarchical tasklist projection (6 group headers + sub-steps `↳`)
- `21b28d7` — Green-tag spawn narration (GSD-style chip)
- `118dc25` — Compact stderr output (silent success + 3-line block)
- `a3f874d` — Phase-profile schema regex bugfix port
- `3c538b7` — Per-task split + `vg-load` helper for context budget
- `86b59c0` — Bake 3 UX requirements into 9 future-flow specs

### 3. Append Phase F — Downstream split-file consumption (NEW EXECUTABLE)

The pilot delivered split files (PLAN/task-NN.md, API-CONTRACTS/<endpoint>.md, TEST-GOALS/G-NN.md) and the `vg-load` helper, but **no downstream command consumes them**. All five (`build`, `review`, `test`, `roam`, `accept`) still `cat $PHASE_DIR/API-CONTRACTS.md` and `Read PLAN.md` — meaning the blueprint output is split, but build executors receive the full 100KB blob and AI-skim risk is unchanged.

Audit findings (grep evidence):
- `vg:build` — 11 references to flat `API-CONTRACTS.md` (lines 162, 501, 596, 783, 1136-1147, 2427, 3465, 3580); 5 to flat `PLAN.md` (595, 824, 2274, 3482)
- `vg:review` — flat reads at 242, 467, 1851
- `vg:test` — flat reads at 553, 572, 589, 614, 788
- `vg:accept` — flat reads at 267-268, 900-908
- `vg:roam` — flat read at 600 (`PLAN.md + CONTEXT.md + RUNTIME-MAP.md` for CRUD surface identification); no `API-CONTRACTS.md` reference

#### Phase F tasks (5)

**Task 28 — Audit downstream consumption (canary scoping).** Per-command grep flat-file reads, classify into migrate-via-vg-load vs keep-flat (deterministic grep-based validators stay flat — they don't trigger AI skim). Output: `docs/audits/2026-05-03-downstream-flat-vs-split.md` with per-command migration list.

**Task 29 — Migrate `vg:build` (HIGH PRIORITY, canary main offender).** Wave executor task capsules use `vg-load --artifact plan --task NN` per task and `vg-load --artifact contracts --endpoint <slug>` per touched endpoint. Each executor receives only the section it touches. Dogfood on PrintwayV3 phase 2, measure context-per-executor delta.

**Task 30 — Migrate `vg:review` + `vg:test` + `vg:roam` + `vg:accept`.** Same pattern: per-goal/per-endpoint lazy loads via vg-load. Backward compat: vg-load `--full` fallback handles legacy flat-only phases automatically. Single bundled task to keep the 4 migrations consistent (chosen by user over per-command split).

**Task 31 — Backward compat + size-warning validator.** Test matrix: flat-only phase, split-only phase, both-present phase — all must work. Add validator emitting `WARN` if `API-CONTRACTS.md > 30KB` AND split files missing → suggests re-running blueprint. Pre-build gate at WARN level (not BLOCK) so legacy phases continue to run.

**Task 32 — Document split-file convention.** Update `.claude/skills/vg-meta-skill.md` with the canon: "downstream MUST prefer vg-load over flat read for blueprint artifacts". CHANGELOG entry. Document the 30KB threshold rationale (~7K tokens — empirical AI-skim boundary).

## Architecture decision

**Hybrid plan structure (preserve audit + history phase + new executable phase)** — chosen over alternatives:

- **Rejected: Rewrite plan from scratch.** Loses Test-Driven step history valuable as replay reference for the upcoming 9-command batch refactor.
- **Rejected: Just tick boxes, ignore post-pilot fixes.** Six post-pilot commits (especially per-task split + vg-load helper) are central findings the next-batch designers must see.
- **Chosen: Hybrid.** Original tasks preserve audit trail. Phase E documents what *had to be added* during dogfood. Phase F adds *what the pilot revealed must be done next*.

Rationale: the R1a pilot is the canary that decides whether the pattern replicates to 9 other VG commands. The plan is therefore both an execution log and a reference template. Treating it purely as one or the other loses fidelity.

## Trade-offs

- **Plan length grows.** From 3016 lines → estimated ~3600 lines after edits. Acceptable: it's a reference doc, not a working file.
- **Phase F blocks future commands.** Until Phase F Task 31 ships, `vg:build` and friends still skim flat files. Mitigation: Task 29 is HIGH priority canary; Tasks 30-32 follow once Task 29 dogfood validates the pattern.
- **vg-load fallback hides drift.** A phase with stale flat file but missing split files would silently use stale content. Task 31's size-warning validator partially mitigates; full mitigation requires blueprint re-run detection (out of scope here).

## Success criteria

1. Plan file shows `[x]` on all Tasks 1-27 with commit SHA on each task header.
2. Phase E section exists with 6 commits documented as `Status: ✅ Shipped` (no executable steps).
3. Phase F section exists with Tasks 28-32 in executable TDD format (`- [ ]` + Step 1-5 pattern matching Phase A/B).
4. Plan still parses as valid Markdown.
5. User reviews and approves before any Phase F task is executed.

## Out of scope

- Actually executing Phase F tasks 28-32 — that's the next session's work after user approves this plan update.
- Reverse-engineering `vg:roam`'s reads — Task 28 will produce that audit.
- Making the 30KB threshold configurable — defer until empirical validation.

## Next step

Update `docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot.md` with the three change sets above, then ask user to review the updated plan before any Phase F execution begins.
