# VG R6b — Amend + Debug Workflows Batch Spec (REVISED 2026-05-03)

**Status:** Design (revised against actual amend.md / debug.md state, ready for plan execution)
**Date:** 2026-05-03 (revised from earlier same-day idealized version)
**Replication round:** R6b (cross-cutting workflow #2 + #3, paired with R6a deploy)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md` (UX baseline)
**Depends on:** R5.5 hooks-source-isolation (merged: `d932710`)
**Covers:** `commands/vg/amend.md` + `commands/vg/debug.md` + 2 new subagents

> **Revision note:** The earlier version of this spec proposed extracting an
> `RIPPLE-ANALYSIS.json` artifact from amend, a `DEBUG-CLASSIFY.json` artifact
> from debug, and a hard-cap of 3 on the debug fix loop. All three were wrong:
>
> - amend already writes `AMENDMENT-LOG.md` (append-only markdown) and Step 5
>   does cascade analysis as informational text only (rule 6: warns, does NOT
>   auto-modify). No JSON artifact needed.
> - debug Step 0 already does deterministic heuristic classification via regex
>   signals (rule 3) — fast, correct, no subagent needed.
> - debug rule 2 explicitly states "AskUserQuestion-driven loop — no max
>   iterations". The cap-at-3 was wrong.
>
> The REAL refactor opportunities are narrower:
> - amend Step 5 (cascade impact) → extract to `vg-amend-cascade-analyzer`
>   subagent (read PLAN/API-CONTRACTS/TEST-GOALS, output markdown report).
> - debug Step 1 `runtime_ui` branch has pseudo-code "Spawn Haiku agent..."
>   that was never implemented → fill the gap with `vg-debug-ui-discovery`
>   subagent (browser MCP wrapper).
>
> This spec is rewritten against the verified file structure.

---

## 1. Background

### 1.1 Why batched

`/vg:amend` and `/vg:debug` are two cross-cutting non-pipeline workflows. Both have a single **judgement-heavy step that benefits from subagent isolation**:

- amend Step 5 (cascade impact analysis): reads downstream artifacts (PLAN, API-CONTRACTS, TEST-GOALS, SUMMARY, RUNTIME-MAP), greps for references to changed decisions, produces an informational impact report.
- debug Step 1 `runtime_ui` branch: needs to inspect a single UI view via browser MCP. Today it's pseudo-code; needs an actual implementation.

Batching them in one round (R6b) shares pytest infrastructure cost. Each gets its own subagent (no shared executor — they analyze different domains).

### 1.2 Current state (verified 2026-05-03)

| Skill | Lines | Steps | Subagent today | Output artifact |
|---|---|---|---|---|
| `commands/vg/amend.md` | 323 | Step 0 → Step 6 (7 sections) | none | `AMENDMENT-LOG.md` (append-only markdown) + surgical CONTEXT.md edits |
| `commands/vg/debug.md` | 399 | Step 0 → Step 4 (5 sections) | none (pseudo-code Haiku spawn in Step 1, not implemented) | `.vg/debug/<id>/DEBUG-LOG.md` (append-only markdown) |

Both already follow good patterns (slim entry, focused Steps). The R6b refactor is **narrow extraction**, not full restructuring.

### 1.3 What stays UNCHANGED in both skills

**amend** (UNCHANGED):
- All 7 `<rules>` (VG-native, config-driven, AMENDMENT-LOG append-only, CONTEXT.md surgical-patch-not-regenerate, git tag before modify, impact informational only, etc.).
- All 7 Step headings (Step 0 → Step 6) and their primary responsibilities.
- AMENDMENT-LOG.md structure (Trigger / Phase step / Change type / Changes list / Impact analysis / Rollback point).
- CONTEXT.md edit semantics (modify D-XX / add D-XX / strikethrough remove / footer reference).
- Telemetry events (`amend.started`, `amend.completed`).
- Git tag + commit pattern in Step 6.

**debug** (UNCHANGED):
- All 7 `<rules>` (standalone session, AskUserQuestion-driven loop, auto-classify heuristic, spec-gap auto-routes to /vg:amend, browser MCP fallback, atomic commits, no destructive actions).
- All 5 Step headings (Step 0 → Step 4).
- Heuristic classification in Step 0 (regex signals, no subagent).
- DEBUG-LOG.md structure (header + Iterations + Final).
- Spec-gap auto-route to /vg:amend (already implemented).
- Telemetry events (`debug.parsed`, `debug.classified`, `debug.fix_attempted`, `debug.user_confirmed`, `debug.completed`).
- Iteration loop with NO max (rule 2 — AskUserQuestion-driven).
- Atomic commits per fix (rule 6).

### 1.4 What this round CHANGES

**amend Step 5 (cascade impact analysis)** — currently inline grep + analysis (lines 204–246, ~37 lines). Refactor to spawn `vg-amend-cascade-analyzer` subagent, which:
- Reads phase artifacts (PLAN.md, API-CONTRACTS.md, TEST-GOALS.md, SUMMARY.md, RUNTIME-MAP.json) under the phase dir.
- Receives changed decision IDs (D-XX list) from amend Step 2.
- Outputs an impact report as **markdown text** (last block of stdout) — orchestrator displays it to user inline.
- Does NOT modify any file (preserves rule 6: "impact is informational, does NOT auto-modify").

**debug Step 1 `runtime_ui` branch** — currently pseudo-code (lines 176–197, "Spawn Haiku agent..." comment with no actual Agent() call). Refactor to spawn `vg-debug-ui-discovery` subagent, which:
- Receives bug description + suspected route + browser MCP available flag.
- Uses MCP Playwright tools (if available) to navigate, screenshot, snapshot, capture console + network.
- If MCP unavailable, writes a structured request as fallback (per rule 5).
- Returns findings as **markdown text** — orchestrator appends to DEBUG-LOG.md iteration block.

### 1.5 Scope summary

**In scope:**
- Create `vg-amend-cascade-analyzer` subagent (.claude/agents/).
- Create `vg-debug-ui-discovery` subagent (.claude/agents/).
- Refactor `amend.md` Step 5 to spawn cascade-analyzer (replace inline grep block).
- Refactor `debug.md` Step 1 `runtime_ui` branch to spawn ui-discovery (replace pseudo-code).
- Add narrate-spawn calls per spec UX baseline R2.
- Pytest suite for delegation + slim size + telemetry preservation + rule preservation (especially rule 2 "no max iterations" and rule 6 "informational only").

**Out of scope:**
- amend Steps 0/1/2/3/4/6 — UNCHANGED.
- debug Steps 0/2/3/4 — UNCHANGED.
- amend telemetry events expansion (just `amend.started`/`amend.completed` is sufficient).
- debug telemetry events expansion.
- Adding fix-applier subagent for debug (Step 2 fix stays in orchestrator — atomic commits per rule 6 require user-visible Edit calls).
- Slim+refs split (both files stay under 500 lines).
- Codex mirrors — defer.
- Cross-phase amend (current scope: single-phase only — UNCHANGED).
- Auto-applying ripple to artifacts (rule 6 in amend explicitly forbids this).

### 1.6 Goals

- 2 new subagents with explicit input/output contracts.
- amend Step 5 delegates cascade analysis to subagent; output is markdown report displayed inline (no new file artifact).
- debug Step 1 `runtime_ui` branch implements browser MCP discovery via subagent; output appended to existing DEBUG-LOG.md.
- Both skills' frontmatter telemetry events PRESERVED.
- Both skills' `<rules>` PRESERVED (especially amend rule 6 + debug rule 2).
- Both skills' line count stays ≤ 500 (no slim+refs needed; current 323 + 399).
- Subagent spawns narrated.
- Mock dogfood: 1 amend + 1 debug iteration on a test phase succeed end-to-end.

### 1.7 Non-goals

- Re-architecting CONTEXT.md decisions schema.
- Adding cross-phase amend (multi-phase ripple).
- Auto-applying fix from debug subagent.
- Replacing `vg-reflector` for end-of-step learning.
- Capping debug fix loop (rule 2 explicitly forbids cap).
- Introducing JSON artifact files for amend or debug analysis (current markdown-based approach is correct).

---

## 2. Inheritance from blueprint pilot

This round inherits from `_shared-ux-baseline.md`:

- **Per-task artifact split** — N/A (no large new artifacts produced by R6b). amend AMENDMENT-LOG.md and debug DEBUG-LOG.md are append-only markdown of small per-iteration blocks; no per-unit split needed.
- **Subagent spawn narration** — MANDATORY. Every `Agent(vg-amend-cascade-analyzer)` and `Agent(vg-debug-ui-discovery)` wraps with `bash scripts/vg-narrate-spawn.sh ... {spawning|returned|failed}`.
- **Compact hook stderr** — no new hooks added; existing inherited.

---

## 3. Architecture

### 3.1 amend flow (refactored Step 5 only)

```
/vg:amend <phase>
   │
   ├── ENTRY SKILL (commands/vg/amend.md, ≤500 lines)
   │
   │   ## Step 0 — Parse phase + detect current step    [UNCHANGED]
   │   ## Step 1 — What to change?                      [UNCHANGED]
   │   ## Step 2 — Discuss change details               [UNCHANGED]
   │   ## Step 3 — Write AMENDMENT-LOG.md (APPEND)      [UNCHANGED]
   │   ## Step 4 — Update CONTEXT.md                    [UNCHANGED]
   │
   │   ## Step 5 — Cascade impact analysis              [REFACTORED]
   │     - narrate green: vg-amend-cascade-analyzer spawning
   │     - Agent(vg-amend-cascade-analyzer, prompt={...changed_decisions, phase_dir})
   │     - narrate cyan/red on return
   │     - subagent returns markdown impact report on last stdout
   │     - orchestrator displays report to user (read-only)
   │     - rule 6 PRESERVED: report is informational, NO auto-modify
   │
   │   ## Step 6 — Git tag + commit                     [UNCHANGED]
   │
   └── SUBAGENT (.claude/agents/vg-amend-cascade-analyzer.md)
         - Receives: {phase_dir, changed_decision_ids, change_summary}
         - Reads: PLAN.md, API-CONTRACTS.md, TEST-GOALS.md, SUMMARY.md, RUNTIME-MAP.json (if exist)
         - Greps for D-XX references + decision-text keywords
         - Returns: markdown impact report (sections per artifact)
         - Tool restrictions: Read/Grep/Bash (read-only) — NO Write, NO Edit, NO Agent
```

### 3.2 debug flow (refactored Step 1 runtime_ui branch only)

```
/vg:debug "<bug>" [--phase=<N>] [--no-amend-trigger]
   │
   ├── ENTRY SKILL (commands/vg/debug.md, ≤500 lines)
   │
   │   ## Step 0 — Parse + classify (heuristic)         [UNCHANGED]
   │     - regex signals → BUG_TYPE ∈ {static, runtime_ui, network, infra, spec_gap, ambiguous}
   │     - emit debug.classified
   │     - if spec_gap → auto-route to /vg:amend
   │
   │   ## Step 1 — Discovery                            [PARTIAL REFACTOR]
   │     branch on BUG_TYPE:
   │       static       → grep + read (UNCHANGED)
   │       runtime_ui   → [REFACTORED — was pseudo-code]
   │                       - check MCP Playwright availability
   │                       - if available:
   │                           narrate green: vg-debug-ui-discovery spawning
   │                           Agent(vg-debug-ui-discovery, prompt={bug, suspected_route, debug_id})
   │                           narrate cyan/red
   │                           append findings to DEBUG-LOG.md iteration block
   │                       - if unavailable (rule 5 fallback):
   │                           write findings request as amendment to phase
   │       network      → curl + tail logs (UNCHANGED)
   │       infra        → config + env inspect (UNCHANGED)
   │
   │   ## Step 2 — Generate hypothesis + apply fix      [UNCHANGED]
   │     - 3-5 hypotheses; pick top; apply via Edit; atomic commit
   │     - emit debug.fix_attempted
   │
   │   ## Step 3 — AskUserQuestion verify loop          [UNCHANGED]
   │     - rule 2: NO max iterations
   │     - emit debug.user_confirmed
   │
   │   ## Step 4 — Finalize                             [UNCHANGED]
   │
   └── SUBAGENT (.claude/agents/vg-debug-ui-discovery.md)
         - Receives: {bug_description, suspected_route, debug_id}
         - Uses MCP Playwright tools: navigate, snapshot, console_messages, network_requests, take_screenshot
         - Returns: markdown findings block (route navigated, console warnings, network errors, screenshot path)
         - Tool restrictions: Read, Grep, Bash, plus mcp__playwright*__ tools
         - NO Write, NO Edit, NO Agent (orchestrator appends to DEBUG-LOG.md)
```

### 3.3 Slim entry constraints

| Skill | Current lines | Target after refactor | Reason |
|---|---|---|---|
| `amend.md` | 323 | ~330 (slight increase from spawn boilerplate) | Below 500 ceiling; no slim+refs needed |
| `debug.md` | 399 | ~410 (slight increase from spawn boilerplate) | Below 500 ceiling; no slim+refs needed |

Both well below the 500-line cap. R6b does NOT introduce `_shared/amend/` or `_shared/debug/` directories — the contract refs live inline in the subagent definitions themselves.

---

## 4. Subagent contracts

### 4.1 `vg-amend-cascade-analyzer`

**Frontmatter:**
```markdown
---
name: vg-amend-cascade-analyzer
description: Read-only cascade impact analyzer for /vg:amend Step 5. Reads phase artifacts (PLAN, API-CONTRACTS, TEST-GOALS, SUMMARY, RUNTIME-MAP), greps for references to changed decisions, returns markdown impact report. Does NOT modify any file (preserves /vg:amend rule 6: informational only).
tools: Read, Grep, Bash
model: claude-sonnet-4-6
---
```

**Input contract:**
- `phase_dir` — absolute path to phase directory
- `changed_decision_ids` — list of D-XX strings (e.g. `["D-03", "D-07"]`)
- `change_summary` — one-line summary from amend Step 2

**Output contract:**
Markdown report on stdout (LAST contiguous block, after any debug stderr). Structure:

```markdown
# Cascade Impact Report — Phase <phase>

**Change:** <change_summary>
**Decisions affected:** <comma-sep D-XX>

## PLAN.md impact
- Task N: <reason>
- Task M: <reason>
(none if PLAN.md absent or no matches)

## API-CONTRACTS.md impact
- POST /endpoint: <reason>
(none if file absent or no matches)

## TEST-GOALS.md impact
- G-XX: <reason>
(none if file absent or no matches)

## SUMMARY.md impact
- Gap-closure build may be needed (if SUMMARY.md exists)

## RUNTIME-MAP.json impact
- Re-review recommended (if RUNTIME-MAP.json exists)

## Suggested next action
<one of: "/vg:blueprint <phase>", "/vg:blueprint <phase> --from=2a", "/vg:build <phase> --gaps-only", etc. — based on current pipeline step>
```

**Tool restrictions:**
- ALLOWED: Read, Grep, Bash (read-only — `cat`, `grep`, `wc`, `find`).
- FORBIDDEN: Write, Edit, Agent, WebSearch.

Subagent MUST NOT modify any file. Orchestrator owns all writes (CONTEXT.md, AMENDMENT-LOG.md). This preserves amend rule 6.

### 4.2 `vg-debug-ui-discovery`

**Frontmatter:**
```markdown
---
name: vg-debug-ui-discovery
description: Browser MCP wrapper for /vg:debug Step 1 runtime_ui branch. Navigates to suspected route, captures snapshot + console + network, returns markdown findings. Implements rule 5 fallback if MCP unavailable. Does NOT modify code or write to DEBUG-LOG.md (orchestrator appends).
tools: Read, Grep, Bash, mcp__playwright1__browser_navigate, mcp__playwright1__browser_snapshot, mcp__playwright1__browser_console_messages, mcp__playwright1__browser_network_requests, mcp__playwright1__browser_take_screenshot, mcp__playwright1__browser_close
model: claude-sonnet-4-6
---
```

(Tool list uses `mcp__playwright1__*` — the first available MCP Playwright instance. If multiple instances exist, subagent may use any; orchestrator does not specify.)

**Input contract:**
- `bug_description` — verbatim from user
- `suspected_route` — best-guess URL path from Step 0 classification (or "unknown")
- `debug_id` — debug session ID (for filename hint, NOT for writing)
- `mcp_available` — boolean from orchestrator's MCP availability check

**Output contract:**
Markdown findings block on stdout LAST contiguous block. Structure:

```markdown
## UI Discovery Findings — <iso8601>

**Route navigated:** <url>
**MCP available:** true | false (fallback)

### Snapshot
<2-line summary of accessibility tree relevant to bug>

### Console messages
- [ERROR] message (file:line if available)
- [WARN] message
(none if console clean)

### Network errors
- GET /api/x → 500
(none if no errors)

### Screenshot
<path to screenshot file under .vg/debug/<debug_id>/screenshots/>

### Hypothesis seed
<one-line: most likely root cause given UI evidence>
```

If `mcp_available == false` (rule 5 fallback):

```markdown
## UI Discovery Findings — <iso8601>

**Route navigated:** N/A (MCP unavailable)
**MCP available:** false (fallback per /vg:debug rule 5)

### Fallback action taken
Wrote investigation request to phase amendment trigger:
<one-line description of what was written and where>

### Hypothesis seed
<one-line based on bug_description alone>
```

**Tool restrictions:**
- ALLOWED: Read, Grep, Bash, mcp__playwright1__* tools.
- FORBIDDEN: Write (subagent does NOT touch DEBUG-LOG.md — orchestrator appends), Edit, Agent.

Note: subagent MAY use `Bash` to run `mkdir` for screenshot dir + write screenshot via `mcp__playwright1__browser_take_screenshot` (which writes the file as a side-effect of the MCP call, not via Write tool). The screenshot file IS a write but it's via the MCP tool, which is intended for this purpose.

---

## 5. File and directory layout

```
commands/vg/
  amend.md                              REFACTOR Step 5 only — delegate cascade to subagent
  debug.md                              REFACTOR Step 1 runtime_ui branch only — implement Agent() spawn

.claude/agents/
  vg-amend-cascade-analyzer.md          NEW — subagent definition
  vg-debug-ui-discovery.md              NEW — subagent definition

scripts/hooks/
  vg-meta-skill.md                      EXTEND — append amend + debug Red Flags

tests/skills/                           (created in R6a or R5.5; reuse)
  test_amend_subagent_delegation.py     NEW — assert Step 5 spawns cascade-analyzer
  test_amend_telemetry_preserved.py     NEW — assert frontmatter retains amend.started + amend.completed
  test_amend_within_500.py              NEW — assert ≤500 lines
  test_amend_rules_preserved.py         NEW — assert all 7 rules present (especially rule 6)
  test_debug_subagent_delegation.py     NEW — assert Step 1 runtime_ui spawns ui-discovery
  test_debug_telemetry_preserved.py     NEW — assert frontmatter retains 5 events
  test_debug_within_500.py              NEW — assert ≤500 lines
  test_debug_no_loop_cap.py             NEW — assert NO hard cap on Step 3 fix loop (rule 2)
  test_debug_rules_preserved.py         NEW — assert all 7 rules present (especially rule 2)
```

NO `_shared/amend/` or `_shared/debug/` directories — both refs are inline in the subagent definitions themselves.

NO new fixture files — schemas are unchanged (AMENDMENT-LOG.md and DEBUG-LOG.md continue to be append-only markdown produced by the entry skills).

---

## 6. Telemetry events (UNCHANGED)

**amend** (UNCHANGED):
```yaml
must_emit_telemetry:
  - event_type: "amend.started"
  - event_type: "amend.completed"
```

**debug** (UNCHANGED):
```yaml
must_emit_telemetry:
  - event_type: "debug.parsed"
  - event_type: "debug.classified"
  - event_type: "debug.fix_attempted"
  - event_type: "debug.user_confirmed"
  - event_type: "debug.completed"
```

R6b does NOT introduce new events. Subagent spawn lifecycle is observable via narrate-spawn (chip UX) and the orchestrator's existing telemetry — no per-subagent event needed.

R6b's pytest tests assert these events remain in `must_emit_telemetry` after refactor.

---

## 7. Error handling, migration, testing

### 7.1 Error handling

**amend cascade-analyzer failure** → orchestrator narrates red pill, displays "Cascade analysis failed: <cause>" to user, asks: "Continue to Step 6 without impact report? (yes/no)". On yes, proceeds without report (degraded but functional). On no, abort.

**debug ui-discovery failure** → orchestrator narrates red pill, falls back to amendment-trigger path (rule 5: "if browser MCP unavailable + UI bug, write findings as amendment to phase"). Continue to Step 2 (hypothesize) with limited evidence.

All blocks follow R1a 3-line stderr pattern.

### 7.2 Migration

- Existing `commands/vg/amend.md` and `commands/vg/debug.md` continue to work until refactor lands.
- Existing AMENDMENT-LOG.md and DEBUG-LOG.md files continue to parse identically — schemas unchanged.
- No data migration.
- Codex mirrors defer.

### 7.3 Testing

**Pytest static** (9 tests):

- `test_amend_subagent_delegation.py` — grep `amend.md` for `Agent(subagent_type="vg-amend-cascade-analyzer"`; assert ≥1 in Step 5 section.
- `test_amend_telemetry_preserved.py` — assert `amend.started` + `amend.completed` in `must_emit_telemetry`.
- `test_amend_within_500.py` — assert ≤500 lines.
- `test_amend_rules_preserved.py` — assert all 7 rules present in `<rules>` block (especially rule 6: "impact is informational, does NOT auto-modify").
- `test_debug_subagent_delegation.py` — grep `debug.md` Step 1 for `Agent(subagent_type="vg-debug-ui-discovery"`; assert ≥1 in `runtime_ui` branch.
- `test_debug_telemetry_preserved.py` — assert all 5 events in `must_emit_telemetry`.
- `test_debug_within_500.py` — assert ≤500 lines.
- `test_debug_no_loop_cap.py` — grep Step 3 body for forbidden patterns (`max 3`, `iteration < 3`, `iteration_count <= 3`, etc.); assert NONE present (rule 2 enforcement).
- `test_debug_rules_preserved.py` — assert all 7 rules present (especially rule 2: "AskUserQuestion-driven loop — no max iterations").

**Mock dogfood** (manual):

1. **amend** — pick a phase with PLAN.md + API-CONTRACTS.md. Run `/vg:amend <phase>`; describe a change ("rename endpoint X → Y"); verify cascade-analyzer spawn (chip narration), report shown inline lists ≥2 affected artifacts, CONTEXT.md updated after user confirm.
2. **debug** — describe a UI bug ("modal does not close on ESC at /admin"). Verify Step 0 classifies as `runtime_ui`. Verify Step 1 spawns ui-discovery (chip narration). If MCP available, verify findings include screenshot path. If MCP unavailable, verify fallback to amendment-trigger.

### 7.4 Exit criteria

R6b PASSES when ALL of:

1. `commands/vg/amend.md` and `commands/vg/debug.md` both ≤ 500 lines.
2. `.claude/agents/vg-amend-cascade-analyzer.md` and `.claude/agents/vg-debug-ui-discovery.md` exist with valid frontmatter.
3. All 9 pytest tests pass.
4. Mock dogfood: 1 amend + 1 debug iteration succeed end-to-end without false blocks.
5. R5.5 hook patches merged (already merged: `d932710`).
6. amend rule 6 (informational only) and debug rule 2 (no max iterations) verified preserved.

---

## 8. Round sequencing

R6b depends on R5.5 (merged). Independent of R6a; may execute in parallel.

---

## 9. References

- Inherits UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r5.5-hooks-source-isolation-design.md` (merged)
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r6a-deploy-design.md` (revised companion)
- Existing skill bodies:
  - `commands/vg/amend.md` (323 lines, source for Step 5 refactor)
  - `commands/vg/debug.md` (399 lines, source for Step 1 runtime_ui implementation)
- Investigation report (verified 2026-05-03): structure of all 3 commands.
- Codex mirrors `.codex/skills/vg-amend/` and `.codex/skills/vg-debug/`: defer.
- vg-reflector reuse: end-of-step learning capture (NO changes; consumed as-is).

---

## 10. UX baseline (mandatory cross-flow)

Per `_shared-ux-baseline.md`, R6b honors:

- **Per-task artifact split** — N/A (no large artifacts produced). AMENDMENT-LOG and DEBUG-LOG are append-only markdown small per-iteration blocks.
- **Subagent spawn narration** — every `Agent(vg-amend-cascade-analyzer)` and `Agent(vg-debug-ui-discovery)` wraps with `vg-narrate-spawn.sh`. amend Step 5 and debug Step 1 runtime_ui branch show the canonical pre/post pattern.
- **Compact hook stderr** — no new hooks added. Schema validation failures (orchestrator-side, on subagent return) emit blocks following R1a 3-line pattern.
