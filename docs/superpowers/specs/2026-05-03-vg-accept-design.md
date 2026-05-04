# VG Accept — Slim Surface + UAT Subagent Refactor

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R4 (after R1 blueprint, R2 build+test, R3 review pass)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/accept.md` is **2,429 lines, 17 steps**. Mid-sized vs build/review but architecturally distinct: it's the **final human gate** with heavy interactive UAT (50+ AskUserQuestion items across 6 sections).

### 1.1 Heavy steps (>200 lines)

| Step | Lines | Role | Refactor approach |
|---|---|---|---|
| `7_post_accept_actions` | **324** | Cleanup + bootstrap hygiene | Subagent: `vg-accept-cleanup` |
| `4_build_uat_checklist` | **291** | Build UAT checklist from VG artifacts (decisions, goals, ripples, designs) | Subagent: `vg-accept-uat-builder` |
| `6c_learn_auto_surface` | **240** | Shadow eval + tier classify + conflict detect | Inline ref (existing 4 subprocesses already orchestrated) |
| `5_interactive_uat` | 213 | AskUserQuestion loop × 50+ items | **NOT subagent — interactive UX must stay in main agent** |
| `5_uat_quorum_gate` | 204 | Quorum math + rationalization-guard | Inline ref |
| `3c_override_resolution_gate` | 189 | Override-debt register integration | Inline ref |
| `6_write_uat_md` | 173 | UAT.md write with Verdict | Inline ref |

Other steps (preflight gates, post-accept) are smaller and stay inline.

### 1.2 Why interactive UAT is special (NOT a subagent candidate)

Step `5_interactive_uat` (213 lines) presents 50+ AskUserQuestion items across 6 sections (decisions, goals, ripples, designs, mobile gates, final verdict). The user interaction loop MUST stay in the main agent because:

- AskUserQuestion is a tool with UI presentation; spawning a subagent to ask user breaks UX continuity
- Response persistence to `.uat-responses.json` (anti-theatre measure) requires per-section commit, easier to manage in main thread
- Interactive UX requires real-time narrative coherence; subagent context handoff would feel disjointed

**Decision:** Step 5 stays inline. The 213 lines refactor down via slim ref + imperative language, not via subagent extraction.

### 1.3 Existing patterns to preserve

- **`.uat-responses.json` mandatory** (anti-theatre, OHOK Batch 3 B4): AI MUST write after each section
- **Quorum gate**: counts SKIPs on critical items (Section A decisions, Section B READY goals); blocks unless `--allow-uat-skips` + rationalization-guard
- **Override-debt integration** (gate 3c): hard gate on unresolved blocking-severity entries
- **Greenfield design Form B block** (line 767-797): `no-asset:greenfield-*` entries critical-severity
- **Design-debt threshold gate** (line 799-830): caps stacked design overrides
- **UAT narrative autofire** (4b): generates UAT-NARRATIVE.md from TEST-GOALS frontmatter, deterministic Sonnet-free
- **Learn auto-surface** (6c): orchestrator hook calls `/vg:learn --auto-surface` for y/n/e/s gate
- **Security baseline** (6b): `verify-security-baseline.py` subprocess, idempotent

### 1.4 Dogfood baseline (PrintwayV3)

| Metric | Value |
|---|---|
| `accept.started` events | 11 |
| `accept.completed` events | 4 (36% — lowest of all commands) |
| `accept.tasklist_shown` events | 4 |
| `accept.native_tasklist_projected` | 0 (recon noted "not in DB" — possibly broken or never emitted) |

→ 36% completion rate is the lowest among all VG commands. Causes per recon: gate failures (artifact precheck, marker precheck, override resolution, quorum) + user fatigue from 50+ AskUserQuestion items.

### 1.5 Goals

- Reduce `commands/vg/accept.md` from 2,429 → ≤500 lines
- Apply imperative + HARD-GATE + Red Flags
- 2 subagents for non-interactive heavy steps (UAT checklist builder + cleanup)
- **Strengthen tasklist projection** (currently 0 events)
- **Mitigate user fatigue** in interactive UAT (narrative autofire already helps, but explore additional UX)
- Empirically prove on PrintwayV3: completion rate ↑ from 36%

### 1.6 Non-goals

- Refactor of interactive UAT step (stays inline — interactive UX requirement)
- Refactor of override-debt register (separate concern)
- New gate types beyond existing 3-tier (artifact / marker / verdict)
- Codex skill mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build/test/review specs §2.

---

## 3. Audit findings

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | `.uat-responses.json` anti-theatre | PASS | Preserve as-is |
| 2 | Quorum gate critical-skip threshold | PASS | Preserve as-is |
| 3 | Override-debt register integration (gate 3c) | PASS | Preserve as-is |
| 4 | Greenfield design Form B block | PASS | Preserve as-is |
| 5 | Design-debt threshold gate | PASS | Preserve as-is |
| 6 | UAT narrative autofire | PASS | Preserve as-is |
| 7 | Learn auto-surface orchestrator hook | PASS | Preserve as-is |
| 8 | Security baseline subprocess | PASS | Preserve as-is |
| 9 | `accept.native_tasklist_projected` emission | **FAIL** | Strengthen (inherited fix) |
| 10 | Interactive UAT response persistence per-section | PASS | Preserve as-is |

**Summary:** 9/10 PASS, 1/10 FAIL (inherited fix from blueprint pilot).

---

## 4. File and directory layout

### 4.1 Canonical (vgflow-bugfix repo)

```
commands/vg/
  accept.md                                 REFACTOR: 2,429 → ~500 lines
  _shared/accept/                           NEW dir
    preflight.md                            ~150 lines (gate integrity, config load, task tracker, telemetry)
    gates.md                                ~300 lines (artifact precheck, marker precheck, sandbox verdict, unreachable triage, override resolution)
    uat/                                    nested for UAT steps
      checklist-build/                      nested for HEAVY 4 (291 lines)
        overview.md                         ~100 lines (entry, instructs spawn vg-accept-uat-builder)
        delegation.md                       ~150 lines (input/output for 6 sections A-F)
      narrative.md                          ~150 lines (4b autofire UAT-NARRATIVE.md)
      interactive.md                        ~250 lines (5 stays inline — slim, imperative)
      quorum.md                             ~200 lines (5_uat_quorum_gate)
    audit.md                                ~250 lines (6b security baseline, 6c learn auto-surface, 6 write_uat_md)
    cleanup/                                nested for HEAVY 7 (324 lines)
      overview.md                           ~100 lines (entry, instructs spawn vg-accept-cleanup)
      delegation.md                         ~150 lines (cleanup steps + bootstrap hygiene)

agents/                                     EXTEND
  vg-accept-uat-builder/SKILL.md            ~250 lines, build 6-section UAT checklist from VG artifacts
  vg-accept-cleanup/SKILL.md                ~200 lines, post-accept cleanup + bootstrap hygiene
```

---

## 5. Components

### 5.1 Slim `commands/vg/accept.md` (~500 lines)

```markdown
---
name: vg:accept
description: Human UAT acceptance — structured checklist driven by VG artifacts
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion]
runtime_contract: { ... }
---

<HARD-GATE>
You MUST follow steps in order. Interactive UAT MUST happen with user input
(AskUserQuestion); .uat-responses.json MUST be written after each section.
Quorum gate enforces critical-skip threshold. Override-resolution gate
blocks if unresolved blocking-severity debt remains.
</HARD-GATE>

## Red Flags (accept-specific)

| Thought | Reality |
|---|---|
| "User trust me, skip interactive UAT"                  | Quorum gate blocks if .uat-responses.json missing/empty |
| "Override-debt is just warning, accept anyway"         | Gate 3c hard-blocks unresolved critical-severity entries |
| "Greenfield design overrides are nominal"              | Form B block treats no-asset:greenfield-* as critical |
| "UAT-NARRATIVE.md skip, ask user directly"             | Narrative autofire deterministic; skip = miss anti-theatre check |
| "Cleanup defer to next phase"                          | 7_post_accept_actions has bootstrap hygiene; skip = drift to next phase |
| "Final verdict = accept by default"                    | Quorum gate verifies actual responses; default-accept = theatre |

## Steps

### STEP 1 — preflight
Read `_shared/accept/preflight.md`. Follow exactly.

### STEP 2 — gates (3-tier)
Read `_shared/accept/gates.md`. Run artifact precheck → marker precheck →
sandbox verdict → unreachable triage → override resolution. Each gate
fail-fast.

### STEP 3 — UAT checklist build (HEAVY, subagent)
Read `_shared/accept/uat/checklist-build/overview.md`. Spawn
vg-accept-uat-builder subagent for sections A-F. DO NOT build inline.

### STEP 4 — UAT narrative autofire
Read `_shared/accept/uat/narrative.md`. Generate UAT-NARRATIVE.md
deterministically from TEST-GOALS frontmatter.

### STEP 5 — interactive UAT (inline, NOT subagent)
Read `_shared/accept/uat/interactive.md`. Loop 50+ AskUserQuestion items
across 6 sections. Write .uat-responses.json after EACH section.

### STEP 6 — UAT quorum gate
Read `_shared/accept/uat/quorum.md`. Verify critical-skip threshold + write
verdict.

### STEP 7 — audit (security + learn + UAT.md write)
Read `_shared/accept/audit.md`. Security baseline → learn auto-surface →
write UAT.md with Verdict line.

### STEP 8 — cleanup (HEAVY, subagent)
Read `_shared/accept/cleanup/overview.md`. Spawn vg-accept-cleanup subagent.
DO NOT cleanup inline.
```

### 5.2 Custom subagents

**`agents/vg-accept-uat-builder/SKILL.md`** (~250 lines):
- Tools: [Read, Write, Bash, Grep]
- HARD-GATE: "Build 6-section UAT checklist (A: decisions, A.1: foundation refs, B: goals, B.1: CRUD surfaces, C: ripple HIGH, D: design refs, E: deliverables, F: mobile gates) by parsing CONTEXT.md / FOUNDATION.md / TEST-GOALS.md / GOAL-COVERAGE-MATRIX.md / CRUD-SURFACES.md / .ripple.json / RIPPLE-ANALYSIS.md / PLAN.md design-refs / SUMMARY*.md / build-state.log. Return: { checklist_path, sections: [{name, items: [{id, summary, source_file, source_line}]}] }"

**`agents/vg-accept-cleanup/SKILL.md`** (~200 lines):
- Tools: [Read, Write, Edit, Bash, Glob, Grep]
- HARD-GATE: "Run post-accept cleanup steps from delegation.md (gather all cleanup tasks: artifact archival, bootstrap hygiene, marker rotation, telemetry consolidation). Return: { cleanup_actions_taken, files_archived: [], markers_rotated: [], summary }"

### 5.3 Hooks (SHARED with blueprint pilot)

No new hooks. The `accept.native_tasklist_projected` audit FAIL is fixed automatically by inheriting blueprint pilot's PostToolUse + slim entry imperative TodoWrite call.

### 5.4 Accept-specific addendum to `vg-meta-skill.md`

```markdown
## Accept-specific Red Flags

| Thought | Reality |
|---|---|
| "Skip interactive UAT, default-accept"                | .uat-responses.json mandatory; quorum gate blocks if missing |
| "Override-debt is yellow flag, proceed"               | Gate 3c hard-blocks blocking-severity entries |
| "User saw output, no need to write UAT.md"            | UAT.md must contain Verdict line; anti-forge content_min_bytes |
| "Cleanup skip, will do next phase"                    | 7_post_accept_actions has bootstrap hygiene per-phase |
```

---

## 6. Error handling, migration, testing, exit criteria

### 6.1 Error handling

All blocks follow blueprint pilot §4.5 (5-layer diagnostic). Accept-specific:

- **Quorum gate fail** → block with: "X critical items skipped (max allowed: Y). Either revisit interactive UAT step 5 to fill responses, or invoke `--allow-uat-skips --reason='...'` (logs to override-debt)."
- **Override resolution fail** → block with list of unresolved entries + 3 resolution paths (re-run gate clean, override-resolve --wont-fix, --allow-unresolved-overrides)
- **Gate 1 artifact precheck fail** → block with missing artifact list + producer command
- **Greenfield Form B block** → block with: "Greenfield no-asset entries are critical. Run /vg:design-scaffold or /vg:override-resolve."

### 6.2 Migration

- Existing 4 PrintwayV3 accept runs: stand as-is.
- Existing tests: pass.
- Defer: Codex mirror.

### 6.3 Testing

**Static (pytest), new for accept:**
- `test_accept_slim_size.py` — assert `commands/vg/accept.md` ≤ 600 lines
- `test_accept_references_exist.py` — all `_shared/accept/*.md` + nested
- `test_accept_subagent_definitions.py` — 2 new subagents valid (NOT 3 — interactive_uat stays inline)
- `test_accept_uat_responses_persisted.py` — simulate UAT, assert .uat-responses.json written per section (existing test, verify still works)
- `test_accept_quorum_blocks_on_missing.py` — simulate missing responses, assert quorum gate blocks (existing test, verify)

**Inherited:** all hook tests, diagnostic tests.

**Empirical dogfood:**
- Sync to PrintwayV3
- Run `/vg:accept <phase>` on a phase with completed build+review+test
- Assert: completion rate up from 36%, `accept.native_tasklist_projected ≥ 1`, `.uat-responses.json` present with all sections

### 6.4 Exit criteria — accept pilot PASS requires ALL of:

1. Tasklist visible in Claude Code UI immediately after invocation
2. `accept.native_tasklist_projected` event count ≥ 1 (baseline 0)
3. All 17 step markers touched without override
4. UAT.md written with Verdict line and content_min_bytes met
5. .uat-responses.json present with all 6 sections + final verdict
6. UAT-builder subagent invocation event present
7. Cleanup subagent invocation event present
8. Interactive UAT happened in main agent (NOT delegated to subagent — verify via tool invocation log)
9. Quorum gate verifies responses (event present)
10. Override-debt resolution gate ran (event present)
11. Stop hook fires without exit 2
12. Stop hook unpaired-block-fails-closed test passes

Accept pilot FAILS if any criterion missed. Critical: criterion 8 (interactive UAT must NOT be delegated — UX requirement).

---

## 7. Round 4 sequencing

This spec is round 4 (after R1 blueprint, R2 build+test, R3 review). Reasons:
- Accept depends on artifacts from build + review + test → must wait for those to stabilize
- Interactive UAT UX is delicate; test on stable downstream first
- Override-debt patterns may emerge from R1-R3 dogfood; refine accept gates afterward

---

## 8. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Siblings: build/test/review specs (R2, R3)
- Existing accept.md: `commands/vg/accept.md` (2,429 lines pre-refactor)
- UAT response anti-theatre (OHOK Batch 3 B4): line 1397-1413 of existing accept.md
- Override-debt: `commands/vg/_shared/override-debt.md`
- Learn auto-surface: `commands/vg/learn.md` (related)

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
