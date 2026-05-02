# VG Scope — Slim Surface + Per-Round Inline (Discussion UX)

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R4 (with project and accept)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/scope.md` is **1,380 lines, 9 steps**. Phase discussion command — produces enriched CONTEXT.md + DISCUSSION-LOG.md via 5 structured rounds.

### 1.1 Heavy steps

| Step | Lines | Refactor approach |
|---|---|---|
| `1_deep_discussion` | **416** | Stays inline (interactive UX — 5-round discussion with per-answer challenger + per-round expander) |
| `4_crossai_review` | 136 | Inline (already async dispatches CrossAI external system) |
| `2_artifact_generation` | 139 | Inline (write CONTEXT.md + DISCUSSION-LOG.md) |
| Other steps | <150 each | Inline |

### 1.2 No subagent extraction needed

Scope is **pure interactive UX** — 21 AskUserQuestion across 5 rounds, with per-answer challenger + per-round expander already using Task tool subagents. The discussion loop CANNOT be extracted to a single subagent because:
- AskUserQuestion requires main agent UI control
- Per-round flow has user-driven branching (Address/Acknowledge/Defer)
- Challenger/expander are ALREADY subagents — extracting again is wrong

→ Scope refactor = **pure-surface (slim+refs+hooks+diagnostic) + imperative cleanup**. NO new subagents.

### 1.3 Existing patterns to preserve

- **Adversarial challenger (R1-R5)** — Task tool, model=Opus default, per-answer dispatch via `vg-challenge-answer-wrapper.sh`. Output JSON `{has_issue, issue_kind, evidence, follow_up_question, proposed_alternative}`. User choice: Address / Acknowledge / Defer
- **Dimension expander (R1-R5 end)** — Task tool, model=Opus, per-round dispatch via `vg-expand-round-wrapper.sh`. Output JSON `{critical_missing, nice_to_have_missing}`. User choice: Address critical / Acknowledge / Defer
- **Loop guards** — `adversarial_max_rounds` (3), `dimension_expand_max` (6)
- **Multi-surface gate** — R2 if `config.surfaces` declared, lock `P{phase}.D-surfaces` decision
- **Profile-aware skip** — R4 skipped for web-backend-only / cli-tool / library
- **CrossAI dispatch (step 4)** — async via `crossai-invoke.sh`
- **Bootstrap rules injection** — via `bootstrap-inject.sh`

### 1.4 Audit findings

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | Adversarial challenger per-answer | PASS | Preserve as-is |
| 2 | Dimension expander per-round | PASS | Preserve as-is |
| 3 | Loop guards (max_rounds, expand_max) | PASS | Preserve as-is |
| 4 | Multi-surface gate (R2) | PASS | Preserve as-is |
| 5 | Profile-aware R4 skip | PASS | Preserve as-is |
| 6 | CrossAI async dispatch | PASS | Preserve as-is |
| 7 | Bootstrap rules injection | PASS | Preserve as-is |
| 8 | Atomic write CONTEXT.md + DISCUSSION-LOG.md | PASS | Preserve as-is |
| 9 | `scope.native_tasklist_projected` emission | **FAIL** (no scope events in dogfood — never run yet) | **Strengthen** (inherit blueprint pilot fix) |

**Summary:** 8/9 PASS, 1/9 FAIL.

### 1.5 Goals

- Reduce `commands/vg/scope.md` from 1,380 → ≤500 lines
- Apply imperative + HARD-GATE + Red Flags
- NO new subagents (challenger + expander already correct)
- Strengthen runtime_contract (already has must_write + must_touch_markers; add native_tasklist_projected fix from inheritance)

### 1.6 Non-goals

- Refactor 5-round discussion (interactive UX)
- Refactor challenger/expander (already correct)
- Codex skill mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build/test/review/accept/project. All 4 hooks + diagnostic + meta-skill base.

---

## 3. File and directory layout

```
commands/vg/
  scope.md                                  REFACTOR: 1,380 → ~500 lines
  _shared/scope/                            NEW dir
    preflight.md                            ~150 lines (parse + validate)
    discussion/                             nested for HEAVY 1_deep_discussion (416 lines)
      overview.md                           ~100 lines (entry, 5-round loop summary)
      round-1-domain.md                     ~150 lines (R1 Domain & Business)
      round-2-technical.md                  ~150 lines (R2 Technical Approach + multi-surface gate)
      round-3-api.md                        ~150 lines (R3 API Design)
      round-4-ui.md                         ~150 lines (R4 UI/UX, profile-skip aware)
      round-5-tests.md                      ~150 lines (R5 Test Scenarios)
      challenger-expander.md                ~150 lines (per-answer challenger + per-round expander pattern)
    env-preference.md                       ~150 lines (1b_env_preference)
    artifact-write.md                       ~150 lines (2_artifact_generation)
    completeness-validation.md              ~150 lines (3_completeness_validation)
    crossai.md                              ~150 lines (4_crossai_review + 4_5 + 4_6)
    close.md                                ~100 lines (5_commit_and_next)
```

---

## 4. Components

### 4.1 Slim `commands/vg/scope.md` (~500 lines)

```markdown
---
name: vg:scope
description: Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion]
runtime_contract:
  must_write:
    - path: "${PHASE_DIR}/CONTEXT.md"
      content_min_bytes: 500
      content_required_sections: ["D-"]
    - "${PHASE_DIR}/DISCUSSION-LOG.md"
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_deep_discussion"
    - "2_artifact_generation"
  must_emit_telemetry:
    - "scope.tasklist_shown"
    - "scope.native_tasklist_projected"
    - "scope.started"
    - "scope.completed"
  forbidden_without_override:
    - "--skip-crossai"
---

<HARD-GATE>
You MUST follow 5 rounds in order. Each round MUST invoke per-answer
adversarial challenger (Task subagent) AND per-round dimension expander
(Task subagent). DO NOT skip rounds even if user seems confident — the
challenger/expander pattern catches blind spots.
</HARD-GATE>

## Red Flags (scope-specific)

| Thought | Reality |
|---|---|
| "User answered clearly, skip challenger this round"   | Challenger is per-answer trigger; skipping = miss adversarial check |
| "All 5 rounds done, skip expander on R5"              | Expander is per-round end; missing = miss critical_missing detection |
| "R4 UI seems irrelevant for backend phase"            | R4 has profile-aware skip — let the profile branch decide, don't manually skip |
| "Fast mode: write CONTEXT.md after R1 only"           | Steps 2-5 build incremental decisions; partial = downstream phases ungrounded |
| "CrossAI review takes time, --skip-crossai"           | --skip-crossai requires override-debt entry; gate enforces |

## Steps

### STEP 1 — preflight
Read `_shared/scope/preflight.md`. Parse args, validate phase context.

### STEP 2 — deep discussion (HEAVY, INLINE due to interactive UX)
Read `_shared/scope/discussion/overview.md`. Loop through 5 rounds:
- Each round: Read `_shared/scope/discussion/round-N-<topic>.md`, follow exactly
- Each round: invoke challenger (Task tool) per user answer
- Each round end: invoke expander (Task tool) before advancing

### STEP 3 — env preference
Read `_shared/scope/env-preference.md`. Capture deployment env preference.

### STEP 4 — artifact generation
Read `_shared/scope/artifact-write.md`. Atomic write CONTEXT.md +
DISCUSSION-LOG.md.

### STEP 5 — completeness validation
Read `_shared/scope/completeness-validation.md`. Cross-check sections.

### STEP 6 — CrossAI review
Read `_shared/scope/crossai.md`. Async dispatch unless --skip-crossai.

### STEP 7 — close
Read `_shared/scope/close.md`. Commit + emit scope.completed.
```

### 4.2 No new subagents

Existing challenger + expander Task subagents preserved as-is. Per-round inline pattern preserved (not extracted to subagent).

### 4.3 Hooks (SHARED)

No new hooks.

### 4.4 Scope-specific Red Flags addendum to `vg-meta-skill.md`

```markdown
## Scope-specific Red Flags
| Thought | Reality |
|---|---|
| "Skip challenger to speed up round"           | Per-answer trigger, skipping = blind spot risk |
| "Skip expander on small round"                | Per-round end gate; missing = critical_missing undetected |
| "Auto-accept all challenger findings"         | User must choose Address/Acknowledge/Defer per finding (not blanket) |
| "Profile branch is suggestion"                | Profile branch enforces R4 skip for backend-only — don't override |
```

---

## 5. Error handling, migration, testing, exit criteria

### 5.1 Error handling

All blocks follow blueprint pilot §4.5. Scope-specific:
- **CONTEXT.md content_min_bytes fail** (500B threshold) → block with: "CONTEXT.md too thin (X bytes < 500). Re-run discussion rounds to capture more decisions."
- **Missing D- section** → block: "CONTEXT.md missing required `D-` section. Each round must contribute D-XX decisions."
- **Challenger/expander Task fail** → main agent retries 1×, then logs as "challenger inconclusive" (does not block round)

### 5.2 Migration

- Existing CONTEXT.md from prior scope runs: stand as-is.
- Defer: Codex mirror.

### 5.3 Testing

**Static (pytest):**
- `test_scope_slim_size.py` — ≤ 600 lines
- `test_scope_references_exist.py` — all `_shared/scope/*.md` + 5 round refs
- `test_scope_no_new_subagents.py` — assert no new agent SKILL.md added (pattern uses existing wrappers)

**Empirical dogfood:**
- Run `/vg:scope <phase>` on PrintwayV3 phase
- Assert: CONTEXT.md + DISCUSSION-LOG.md written, scope.native_tasklist_projected ≥ 1, all 3 step markers touched

### 5.4 Exit criteria — scope pilot PASS requires ALL of:

1. Tasklist visible immediately
2. `scope.native_tasklist_projected` event ≥ 1
3. 3 step markers touched (0_parse, 1_deep_discussion, 2_artifact_generation)
4. CONTEXT.md (≥500B, with D- section) + DISCUSSION-LOG.md written
5. Per-round challenger Task events present (one per user answer in each of 5 rounds)
6. Per-round expander Task events present (one per round end, R1-R5)
7. CrossAI review event present (or --skip-crossai with override-debt entry)
8. Stop hook fires without exit 2

---

## 6. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Sibling: `2026-05-03-vg-project-design.md` (similar interactive UX pattern)
- Existing scope.md: `commands/vg/scope.md` (1,380 lines)
- Challenger wrapper: `commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh`
- Expander wrapper: `commands/vg/_shared/lib/vg-expand-round-wrapper.sh`

---

## Appendix — Codex review corrections (2026-05-03)

External review by Codex (gpt-5.5) flagged 5 spec-wide issues:

1. **Tool name `Agent`, not `Task`** — Claude Code current docs use tool name `Agent` for subagent invocations (verified via [hooks reference](https://code.claude.com/docs/en/hooks)). Any reference in this spec to `Task(...)` invocation or PreToolUse matcher `Task` MUST be implemented as `Agent`. Both `SubagentStart`/`SubagentStop` events available for additional observability.

2. **UserPromptSubmit hook needed** — Per blueprint pilot spec amendment §4.4. This spec inherits the start-of-run gate that creates `.vg/active-runs/<session>.json` BEFORE model executes. Otherwise Stop hook no-ops bypass entire enforcement.

3. **PreToolUse on Write/Edit for protected paths** — Per blueprint pilot spec amendment §4.4. AI cannot directly Write to `.vg/runs/*evidence*`, `.step-markers/*`, `events.db` etc. Must use signed orchestrator helper.

4. **Flat references (1-level)** — Anthropic guidance: keep refs ONE level from SKILL.md. Any nested `_shared/<cmd>/<group>/overview.md + delegation.md` chain in this spec should be flattened to `_shared/<cmd>/<group>-overview.md + <group>-delegation.md`.

5. **State-machine validator** — Per blueprint pilot spec amendment §4.4c. Stop hook invokes `vg-state-machine-validator.py` to verify event ORDER matches expected sequence per command — beyond mere event count.

Implementation plans for this command MUST incorporate all 5 corrections.
