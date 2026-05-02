# VG Roam — Slim Surface + Mega-Gate Decomposition

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R3.5 (after R3 review pass — roam shares lens-prompts/ with review)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/roam.md` is **1,103 lines, 11 steps**. Exploratory CRUD-lifecycle pass with state-coherence assertion. Lens-driven, post-confirmation (runs AFTER `/vg:review` + `/vg:test` PASS). Generates new .spec.ts proposals from findings.

Distinct from review: roam is a **janitor** (line 62 of existing roam.md) catching state-mismatches that review (shape-only) and test (deterministic specs) cannot.

### 1.1 Heavy steps

| Step | Lines | Refactor approach |
|---|---|---|
| `0a_env_model_mode_gate` | **355** | **Decompose into 5 sub-steps** (mega-gate, 9 sub-prompts inline) |
| `3_spawn_executors` | 200 | Inline (already branched: spawn/self/manual) |
| `0aa_resume_check` | 138 | Inline |

### 1.2 Decomposition of step 0a (the mega-gate)

Per recon, step 0a contains 9 sub-prompts inline:
1. Pre-prompt 1 (env preference backfill, 90 lines)
2. Pre-prompt 1.5 (platform + tool detection, 73 lines)
3. Pre-prompt 2 (enrich env from DEPLOY-STATE, 32 lines)
4. AskUserQuestion 3-question batch (env + model + mode, 42 lines)
5. After-answers branch (resolve + validate + persist, 91 lines)

→ Decompose into:
- `0a_backfill_env_pref`
- `0a_detect_platform_tools`
- `0a_enrich_env_options`
- `0a_confirm_env_model_mode`
- `0a_persist_config`

Each sub-step becomes its own ref file ≤150 lines. No subagent extraction (interactive UX requires main agent for AskUserQuestion).

### 1.3 Existing patterns to preserve

- **Lens architecture** — 19 lens files in `_shared/lens-prompts/` (SHARED with review)
- **Auto-pick lens** — by phase profile + entity types (Q9 default)
- **Per-surface composition** — INSTRUCTION-{surface}-{lens}.md files (Cartesian product)
- **3 dispatch branches (step 3)** — Branch A spawn subprocess (throttle 5 parallel), Branch B self via Playwright MCP, Branch C manual paste-prompt
- **Evidence-based state coherence** — executor logs facts, commander judges via R1-R8 deterministic Python rules
- **Vocabulary validator** — banned tokens (bug, broken, critical, should fix) tagged `vocabulary_violation: true`
- **Spec.ts proposal generation** — `roam-analyze.py` outputs to `proposed-specs/`
- **Staged spec merge** — `--merge-specs` flag separately gates merge into project test suite
- **Auto-fix loop (step 7)** — Task tool subagent dispatch, max 5 fixes/session

### 1.4 Audit findings

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | Lens auto-pick by profile + entity types | PASS | Preserve as-is |
| 2 | Per-surface composition (Cartesian) | PASS | Preserve as-is |
| 3 | 3 dispatch branches (spawn/self/manual) | PASS | Preserve as-is |
| 4 | Evidence-based state coherence (R1-R8 rules) | PASS | Preserve as-is |
| 5 | Vocabulary validator | PASS | Preserve as-is |
| 6 | Staged spec merge (--merge-specs flag) | PASS | Preserve as-is |
| 7 | Auto-fix loop subagent | PASS | Preserve as-is |
| 8 | Hard gate: post-review-test-PASS | PASS | Preserve as-is |
| 9 | Per-tool subdir isolation for parallel | PASS | Preserve as-is |
| 10 | Step 0a mega-gate (355 lines, 9 sub-prompts) | **FAIL** | **Decompose** — see §1.2 |
| 11 | `roam.native_tasklist_projected` emission | **PARTIAL** (5 events declared but projection not in current set) | **Strengthen** (inherit blueprint pilot fix) |

**Summary:** 9/11 PASS, 1/11 FAIL, 1/11 PARTIAL. Architecture is excellent; only ergonomics fix needed.

### 1.5 Goals

- Reduce `commands/vg/roam.md` from 1,103 → ≤500 lines
- Decompose step 0a mega-gate into 5 sub-steps
- Apply imperative + HARD-GATE + Red Flags
- Strengthen tasklist projection (inherit fix)

### 1.6 Non-goals

- Refactor lens architecture (already correct, shared with review)
- Refactor R1-R8 state coherence rules (in roam-analyze.py, separate concern)
- Refactor 3 dispatch branches (already cohesive)
- Codex mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build/test/review/accept/project/scope/phase. All 4 hooks + diagnostic + meta-skill base.

---

## 3. File and directory layout

```
commands/vg/
  roam.md                                   REFACTOR: 1,103 → ~500 lines
  _shared/roam/                             NEW dir
    preflight.md                            ~150 lines (0_parse_and_validate + 0aa_resume_check)
    config-gate/                            nested for HEAVY 0a (decomposed into 5 sub-steps)
      overview.md                           ~100 lines (entry, 5 sub-step sequence)
      backfill-env.md                       ~100 lines (pre-prompt 1)
      detect-platform.md                    ~100 lines (pre-prompt 1.5)
      enrich-env.md                         ~100 lines (pre-prompt 2)
      confirm-env-model-mode.md             ~100 lines (AskUserQuestion 3-question batch)
      persist-config.md                     ~100 lines (after-answers branch)
    discovery.md                            ~150 lines (1_discover_surfaces + 2_compose_briefs)
    spawn-executors.md                      ~250 lines (3_spawn_executors with 3 branches)
    aggregate-analyze.md                    ~150 lines (4_aggregate_logs + 5_analyze_findings)
    artifacts.md                            ~150 lines (6_emit_artifacts + spec.ts proposal)
    fix-loop.md                             ~100 lines (7_optional_fix_loop)
    close.md                                ~100 lines (complete + merge-specs invocation note)
```

---

## 4. Components

### 4.1 Slim `commands/vg/roam.md` (~500 lines)

```markdown
---
name: vg:roam
description: Exploratory CRUD-lifecycle pass with state-coherence assertion (post-review/test janitor)
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion]
runtime_contract:
  must_write:
    - "${PHASE_DIR}/roam/SURFACES.md"
    - "${PHASE_DIR}/roam/RAW-LOG.jsonl"
    - "${PHASE_DIR}/roam/ROAM-BUGS.md"
    - "${PHASE_DIR}/roam/RUN-SUMMARY.json"
  must_touch_markers:
    - "0_parse_and_validate"
    - "0a_persist_config"   # last sub-step of decomposed mega-gate
    - "1_discover_surfaces"
    - "2_compose_briefs"
    - "3_spawn_executors"
    - "4_aggregate_logs"
    - "5_analyze_findings"
    - "6_emit_artifacts"
    - "complete"
    - name: "7_optional_fix_loop"
      severity: "warn"
      required_unless_flag: "--auto-fix"
  must_emit_telemetry:
    - "roam.tasklist_shown"
    - "roam.native_tasklist_projected"
    - "roam.session.started"
    - "roam.session.completed"
    - "roam.analysis.completed"
    - event_type: "roam.resume_mode_chosen"
      required_unless_flag: "--non-interactive"
    - event_type: "roam.config_confirmed"
      required_unless_flag: "--non-interactive"
---

<HARD-GATE>
Roam is post-confirmation (runs AFTER /vg:review + /vg:test PASS). You MUST
verify both passes BEFORE any roam step. Lens auto-pick by phase profile +
entity types — DO NOT manually override unless --lens flag explicit. Spec.ts
proposals stage to proposed-specs/ — DO NOT auto-merge (requires --merge-specs).
</HARD-GATE>

## Red Flags (roam-specific)

| Thought | Reality |
|---|---|
| "Review passed, skip lens dispatch in roam"             | Roam catches state-mismatches review missed; skipping = leaks |
| "Lens irrelevant for this phase, skip"                 | Lens auto-pick by profile + entities; manual skip = blind spot |
| "Auto-merge spec.ts proposals to save time"            | Staged merge via --merge-specs is intentional (validation gate) |
| "RAW-LOG.jsonl optional, just write summary"           | Evidence-completeness validator HARD-blocks; missing = run fail |
| "Fix loop in same session is fine"                     | Auto-fix loop max 5 fixes/session by design (config); enforce |
```

### 4.2 No new subagents (decomposition only)

Step 0a decomposed into 5 sub-steps (still inline, interactive UX for AskUserQuestion). Existing auto-fix loop subagent (step 7) preserved.

### 4.3 Hooks (SHARED)

No new hooks.

### 4.4 Roam-specific Red Flags addendum to `vg-meta-skill.md`

```markdown
## Roam-specific Red Flags
| Thought | Reality |
|---|---|
| "Skip resume check, fresh run faster"          | 0aa_resume_check detects partial state; fresh = lose work |
| "Env/model/mode default fine, skip 3-question gate" | Anti-forge guard refuses launch if all empty + not in CI |
| "Vocabulary validator pedantic, ignore"        | Banned tokens tagged vocabulary_violation; commander deprioritizes |
| "Roam = review v2, skip steps"                | Roam is JANITOR, not primary verifier — different role |
```

---

## 5. Error handling, migration, testing, exit criteria

### 5.1 Error handling

All blocks follow blueprint pilot §4.5. Roam-specific:
- **Pre-roam gate fail** (review or test not PASSED) → block: "Roam requires /vg:review and /vg:test both PASSED. Run them first or use --skip-pre-check (override-debt)."
- **Evidence completeness fail** (step 4 HARD gate) → block with: "observe-*.jsonl missing required tier fields per scanner-report-contract. Re-run executor for affected briefs."
- **Vocabulary violation** → tag report `vocabulary_violation: true`, do NOT block (commander deprioritizes)

### 5.2 Migration

- Existing roam runs (5 events in PrintwayV3): stand as-is.
- Existing proposed-specs/: not auto-merged, stand as-is.
- Defer: Codex mirror.

### 5.3 Testing

**Static (pytest):**
- `test_roam_slim_size.py` — ≤ 600 lines
- `test_roam_references_exist.py` — all `_shared/roam/*.md` + 5 config-gate sub-refs
- `test_roam_step_0a_decomposed.py` — assert 5 sub-step markers replace single 0a marker
- `test_roam_no_new_subagents.py` — assert no new agent SKILL.md (auto-fix loop preserved as-is)

**Empirical dogfood:**
- Run `/vg:roam <phase>` on a phase where review + test both PASSED
- Assert: 9 step markers touched, RAW-LOG.jsonl + ROAM-BUGS.md written, roam.native_tasklist_projected ≥ 1

### 5.4 Exit criteria — roam refactor PASS requires ALL of:

1. Tasklist visible immediately
2. `roam.native_tasklist_projected` event ≥ 1
3. 9 step markers touched (8 hard + persist_config sub-step)
4. SURFACES.md + RAW-LOG.jsonl + ROAM-BUGS.md + RUN-SUMMARY.json all written
5. roam.session.started + roam.session.completed + roam.analysis.completed events present
6. Lens dispatch happened (verify INSTRUCTION-{surface}-{lens}.md files generated)
7. Stop hook fires without exit 2

---

## 6. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Sibling: `2026-05-03-vg-review-design.md` (lens architecture shared)
- Existing roam.md: `commands/vg/roam.md` (1,103 lines)
- Lens definitions: `commands/vg/_shared/lens-prompts/` (19 lenses, shared)
- State coherence rules: `roam-analyze.py` (R1-R8)
