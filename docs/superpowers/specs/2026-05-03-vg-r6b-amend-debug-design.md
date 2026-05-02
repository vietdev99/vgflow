# VG R6b — Amend + Debug Workflows Batch Spec

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R6b (cross-cutting workflow #2 + #3, paired with R6a deploy)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md` (UX baseline)
**Depends on:** R5.5 hooks-source-isolation (subagent allow-list)
**Covers:** `commands/vg/amend.md` + `commands/vg/debug.md` + 2 new subagents

---

## 1. Background

### 1.1 Why batched

`/vg:amend` and `/vg:debug` are two cross-cutting workflows that share the same architectural shape:

- Both are **non-pipeline** (do not advance V5 phase state).
- Both follow **classify → action → user verify** structure.
- Both have judgement-heavy analysis steps that benefit from subagent isolation.
- Both fit comfortably under 500 lines (no slim+refs split needed).
- Both use existing `vg-reflector` for end-of-step learning capture.

Batching them in one round (R6b) shares spec inheritance + test infrastructure cost. Each gets its own subagent (no shared executor — they analyze different domains).

### 1.2 Current state

| Skill | Lines | Subagent today | Output artifact |
|---|---|---|---|
| `commands/vg/amend.md` | 323 | none (inline) | `RIPPLE-ANALYSIS.json` (or .md) + CONTEXT.md decisions update |
| `commands/vg/debug.md` | 399 | none (inline) | `DEBUG-CLASSIFY.json` + fix attempt(s) + verify gate |

Both are below the slim+refs threshold but contain **judgement-heavy analysis** that:
- Pollutes orchestrator AI context (full ripple traversal, error pattern matching).
- Is hard to test in isolation (mixed with orchestration).
- Will compound complexity as V5 pipeline adds artifacts (more downstream to ripple, more error patterns to classify).

Per discussion 2026-05-03 with operator: extract subagents now (futureproof) even though current logic fits inline.

### 1.3 Scope

**In scope** (per workflow):
- `vg-amend-impact-analyzer` subagent — read CONTEXT.md decisions + downstream artifacts → RIPPLE-ANALYSIS.json.
- `vg-debug-classifier` subagent — read repro context + grep codebase → DEBUG-CLASSIFY.json with ranked hypotheses.
- Refactor `amend.md` (~280 lines body, ~50 frontmatter/HARD-GATE) — entry orchestrates, subagent analyzes.
- Refactor `debug.md` (~340 lines body, ~50 frontmatter/HARD-GATE) — entry orchestrates fix loop, subagent classifies.
- Telemetry events for both.
- Pytest suite for delegation + fix loop max-3 enforcement.

**Out of scope**:
- Adding fix-applier subagent (debug fix loop stays in entry — uses Edit/Write directly).
- amend cross-phase impact (current scope: single-phase only).
- Codex mirrors (`.codex/skills/vg-amend/`, `.codex/skills/vg-debug/`) — defer.
- Slim+refs split (both files stay under 500 lines).

### 1.4 Goals

- 2 new subagents with explicit input/output contracts.
- `amend.md` and `debug.md` refactored to delegate analysis steps to subagents.
- Both skills emit subagent-related telemetry (`amend.analyzer_*`, `debug.classifier_*`).
- Subagent spawns narrated via `vg-narrate-spawn.sh`.
- Debug fix loop hard-capped at 3 iterations (regression test).
- Dogfood: 1 amend + 1 debug invocation on test project succeed.

### 1.5 Non-goals

- Re-architecting CONTEXT.md decisions schema.
- Adding cross-phase amend (multi-phase ripple).
- Auto-applying fix from debug subagent (fix stays in user-confirmed orchestrator path).
- Replacing `vg-reflector` for end-of-step learning (R6b inherits, does not modify).

---

## 2. Inheritance from blueprint pilot

This round inherits from `_shared-ux-baseline.md`:

- **Per-task artifact split** — RIPPLE-ANALYSIS supports per-affected-artifact split if file >30KB (advisory threshold from R2-phase-G validator). Default flat for small ripples; subagent emits split when applicable. DEBUG-CLASSIFY stays flat (always small, ≤10 hypotheses).
- **Subagent spawn narration** — MANDATORY. Every `Agent(vg-amend-impact-analyzer)` and `Agent(vg-debug-classifier)` wraps with `vg-narrate-spawn.sh`.
- **Compact hook stderr** — no new hooks added; existing hook patterns inherited.

---

## 3. Architecture

### 3.1 `/vg:amend` flow

```
/vg:amend <phase>
   │
   ├── ENTRY SKILL (commands/vg/amend.md, ~330 lines)
   │
   │   STEP 1: User describes change
   │     - AskUserQuestion: "What change do you want to make to phase <P>?"
   │     - Capture free-text into change_description
   │
   │   STEP 2: Spawn vg-amend-impact-analyzer
   │     - Pre-spawn narrate (green)
   │     - Agent(subagent_type="vg-amend-impact-analyzer", prompt={phase, change_description, current_artifacts_manifest})
   │     - Post-spawn narrate (cyan/red)
   │     - Subagent writes .vg/phases/<P>/RIPPLE-ANALYSIS.json
   │
   │   STEP 3: Present ripple to user
   │     - Read RIPPLE-ANALYSIS.json
   │     - Format: affected artifact list + severity + recommended action
   │     - AskUserQuestion: "Apply change? See ripple above."
   │
   │   STEP 4: Update CONTEXT.md decisions
   │     - Append decision block with timestamp, change_description, ripple summary
   │     - User-controlled: model writes draft, user confirms before Write
   │
   │   STEP 5: Emit telemetry + close
   │     - amend.completed event
   │     - Step marker .vg/phases/<P>/.step-markers/amend-{timestamp}.done
```

### 3.2 `/vg:debug` flow

```
/vg:debug
   │
   ├── ENTRY SKILL (commands/vg/debug.md, ~390 lines)
   │
   │   STEP 1: User describes bug
   │     - AskUserQuestion: "Describe the bug, repro steps, error message"
   │     - Capture into bug_context
   │
   │   STEP 2: Spawn vg-debug-classifier
   │     - Pre-spawn narrate (green)
   │     - Agent(subagent_type="vg-debug-classifier", prompt={bug_context, codebase_root})
   │     - Post-spawn narrate (cyan/red)
   │     - Subagent writes .vg/debug/<run_id>/DEBUG-CLASSIFY.json
   │
   │   STEP 3: Present hypotheses
   │     - Read DEBUG-CLASSIFY.json
   │     - Show top-3 ranked hypotheses to user
   │     - AskUserQuestion: "Which hypothesis to try first?"
   │
   │   STEP 4: Fix loop (max 3 iterations)
   │     - For each iteration:
   │       a. Apply candidate fix (orchestrator uses Edit/Write directly — no fix-applier subagent)
   │       b. AskUserQuestion: "Did the fix resolve the bug?"
   │       c. If yes → STEP 5
   │       d. If no AND iteration < 3 → return to top-of-loop with next hypothesis
   │       e. If no AND iteration == 3 → STEP 5 with status=unresolved
   │
   │   STEP 5: User verify + close
   │     - AskUserQuestion: "Confirm bug status: resolved | unresolved | needs-more-info"
   │     - Emit debug.completed event
   │     - Write fix attempt log to .vg/debug/<run_id>/attempts.log
```

### 3.3 Slim entry constraints

| Skill | Body target | Total target | Why no slim+refs |
|---|---|---|---|
| `amend.md` | ~280 lines | ~330 lines | Below 500 ceiling; no obvious split |
| `debug.md` | ~340 lines | ~390 lines | Below 500 ceiling; fix loop is single concern |

---

## 4. Subagent contracts

### 4.1 `vg-amend-impact-analyzer`

**Frontmatter**:
```markdown
---
name: vg-amend-impact-analyzer
description: Analyze cascade impact of a mid-phase change request. Reads CONTEXT.md decisions + downstream artifacts (PLAN, API-CONTRACTS, TEST-GOALS), produces RIPPLE-ANALYSIS.json with affected list + severity + recommended action.
tools: Read, Grep, Bash
model: claude-sonnet-4-6
---
```

**Input contract**:
- `phase` — phase ID
- `change_description` — free-text from user
- `current_artifacts_manifest` — list of paths under `.vg/phases/<P>/` (orchestrator passes; subagent does not enumerate)
- `policy_ref` — pointer to severity-classification rules in `commands/vg/_shared/amend/severity-rules.md` (NEW file)

**Output contract** — JSON written to `.vg/phases/<P>/RIPPLE-ANALYSIS.json`:
```json
{
  "phase": "P1",
  "change_summary": "Add OAuth2 to user-login endpoint",
  "analyzed_at": "2026-05-03T15:00:00Z",
  "affected": [
    {"artifact": "API-CONTRACTS/POST-user-login.md", "severity": "high", "reason": "endpoint signature changes"},
    {"artifact": "PLAN/task-04.md", "severity": "med", "reason": "task references current auth flow"},
    {"artifact": "TEST-GOALS/G-07.md", "severity": "high", "reason": "test goal pre-dates OAuth2"}
  ],
  "recommended_action": "rerun /vg:blueprint for phase, then /vg:test-spec",
  "confidence": "high"
}
```

**Tool restrictions**:
- READ-ONLY: no Write, no Edit (orchestrator is sole writer of CONTEXT.md).
- May Bash for grep/wc/cat-equivalent reads only.

### 4.2 `vg-debug-classifier`

**Frontmatter**:
```markdown
---
name: vg-debug-classifier
description: Classify a bug report into ranked root-cause hypotheses (code|config|env|data). Reads bug context + greps codebase for symptom patterns. Produces DEBUG-CLASSIFY.json with top hypotheses.
tools: Read, Grep, Bash, WebSearch
model: claude-sonnet-4-6
---
```

**Input contract**:
- `bug_context` — `{description, repro_steps, error_message?, file_paths?, recent_commits?}`
- `codebase_root` — absolute path
- `policy_ref` — pointer to classification taxonomy in `commands/vg/_shared/debug/classify-taxonomy.md` (NEW file)

**Output contract** — JSON written to `.vg/debug/<run_id>/DEBUG-CLASSIFY.json`:
```json
{
  "bug_id": "<run_id>",
  "classified_at": "2026-05-03T15:00:00Z",
  "hypotheses": [
    {
      "rank": 1,
      "type": "code",
      "file": "src/auth/login.ts",
      "line": 42,
      "hypothesis": "missing await on token validation; race condition under load",
      "evidence": ["error message matches async-race pattern", "git blame shows recent change to async flow"],
      "confidence": "high",
      "suggested_fix": "add await keyword at line 42"
    },
    { "rank": 2, "type": "config", ... },
    { "rank": 3, "type": "env", ... }
  ],
  "search_queries_run": ["error pattern X site:stackoverflow.com"]
}
```

**Tool restrictions**:
- READ-ONLY against codebase.
- May Bash for grep/wc/find.
- WebSearch allowed for known-error-pattern lookup (max 3 queries per invocation — enforced by subagent prompt).
- No Write, no Edit.

---

## 5. File and directory layout

```
commands/vg/
  amend.md                              REFACTOR: 323 → ~330 lines (delegate STEP 2 to subagent)
  debug.md                              REFACTOR: 399 → ~390 lines (delegate STEP 2 to subagent)
  _shared/amend/                        NEW DIR
    severity-rules.md                   NEW — severity taxonomy referenced by analyzer
  _shared/debug/                        NEW DIR
    classify-taxonomy.md                NEW — root-cause taxonomy referenced by classifier

.claude/agents/
  vg-amend-impact-analyzer.md           NEW — subagent definition
  vg-debug-classifier.md                NEW — subagent definition

scripts/hooks/
  vg-meta-skill.md                      EXTEND — append amend + debug Red Flags sections

tests/skills/
  test_amend_subagent_delegation.py     NEW — assert STEP 2 spawns analyzer
  test_amend_telemetry_events.py        NEW — assert frontmatter must_emit complete
  test_debug_subagent_delegation.py     NEW — assert STEP 2 spawns classifier
  test_debug_fix_loop_max_3.py          NEW — assert fix loop hard-cap == 3
  test_debug_telemetry_events.py        NEW — assert frontmatter must_emit complete
  test_amend_ripple_schema.py           NEW — assert RIPPLE-ANALYSIS.json schema is parseable
  test_debug_classify_schema.py         NEW — assert DEBUG-CLASSIFY.json schema is parseable
```

---

## 6. Telemetry events

### 6.1 amend (must_emit_telemetry additions)

```yaml
- "amend.tasklist_shown"
- "amend.native_tasklist_projected"
- "amend.analyzer_spawned"
- "amend.analyzer_returned"
- "amend.analyzer_failed"
- "amend.ripple_presented"
- "amend.context_updated"
- "amend.completed"
```

### 6.2 debug (must_emit_telemetry additions)

```yaml
- "debug.tasklist_shown"
- "debug.native_tasklist_projected"
- "debug.classifier_spawned"
- "debug.classifier_returned"
- "debug.classifier_failed"
- "debug.fix_attempted"           # one per iteration
- "debug.fix_loop_exhausted"      # iteration == 3 without resolve
- "debug.user_verified"
- "debug.completed"
```

---

## 7. Error handling, migration, testing

### 7.1 Error handling

- Subagent failure → orchestrator narrates red pill, prompts user (retry / abort / manual override).
- Fix loop iteration failure (Edit/Write error) → log to attempts.log, count as one iteration, continue.
- Fix loop exhausted (iteration == 3 without user "yes") → close with status=unresolved; do NOT auto-bump to 4.
- Schema validation failure on RIPPLE-ANALYSIS.json or DEBUG-CLASSIFY.json → orchestrator emits block, requires subagent re-run with corrected output.

All blocks follow R1a 3-line stderr pattern.

### 7.2 Migration

- Existing `commands/vg/amend.md` and `commands/vg/debug.md` runs: stand as-is until R6b executes.
- Pre-R6b RIPPLE-ANALYSIS files (if any) MUST parse under R6b orchestrator. Add fixture-based regression test.
- No data migration required; both artifacts are session-scoped.

### 7.3 Testing

**Pytest static**:
- `test_amend_subagent_delegation.py` — grep `amend.md` for `Agent(subagent_type="vg-amend-impact-analyzer"`; assert exactly 1 match in STEP 2.
- `test_debug_subagent_delegation.py` — same for `vg-debug-classifier` in `debug.md` STEP 2.
- `test_amend_telemetry_events.py` — parse frontmatter, assert all 8 events present.
- `test_debug_telemetry_events.py` — same for 9 events.
- `test_debug_fix_loop_max_3.py` — parse `debug.md` STEP 4, assert loop iterates ≤3 (count `iteration < 3` guard or equivalent).
- `test_amend_ripple_schema.py` — load 2 fixture RIPPLE-ANALYSIS.json files, assert schema validation passes (jsonschema).
- `test_debug_classify_schema.py` — same for DEBUG-CLASSIFY.json.

**Manual dogfood**:
1. **amend** — pick a phase with PLAN.md + API-CONTRACTS. Run `/vg:amend <phase>`; describe a change ("rename endpoint X"); verify analyzer ripple lists ≥2 affected artifacts; verify CONTEXT.md updated after user confirm.
2. **debug** — describe a contrived bug ("login fails with 500 after recent commit"); verify classifier returns ≥1 hypothesis with file:line ref; complete fix loop (mock fix); verify telemetry events emit in order.

### 7.4 Exit criteria

R6b PASSES when ALL of:

1. `commands/vg/amend.md` and `commands/vg/debug.md` both ≤ 500 lines after refactor.
2. `.claude/agents/vg-amend-impact-analyzer.md` and `.claude/agents/vg-debug-classifier.md` exist with valid frontmatter.
3. `commands/vg/_shared/amend/severity-rules.md` and `commands/vg/_shared/debug/classify-taxonomy.md` exist.
4. All 7 pytest tests pass.
5. Manual dogfood: 1 amend + 1 debug run end-to-end without false blocks.
6. R5.5 hook patches merged (prerequisite — subagent allow-list will let `vg-amend-*` and `vg-debug-*` through via `vg-*` glob, but R5.5 must be in place to silence false blocks during dogfood from non-VG sessions).

---

## 8. Round sequencing

R6b depends on R5.5 (same reason as R6a — subagent spawn allow-list).

R6b is independent of R6a. Both may execute in parallel; recommended sequence:

```
R5.5  (hotfix)  ───────────► merged
                                │
                                ├──► R6a (deploy)   ──► merged
                                │
                                └──► R6b (amend+debug) ──► merged
```

---

## 9. References

- Inherits UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- Inherits frontmatter pattern: `docs/superpowers/specs/2026-05-03-vg-blueprint-pilot-design.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r5.5-hooks-source-isolation-design.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r6a-deploy-design.md`
- Existing skill bodies:
  - `commands/vg/amend.md` (323 lines, source for refactor)
  - `commands/vg/debug.md` (399 lines, source for refactor)
- Codex mirrors `.codex/skills/vg-amend/` and `.codex/skills/vg-debug/`: defer.
- vg-reflector reuse: end-of-step learning capture (no changes; R6b consumes existing reflector).
- bug-detection-guide: `vg:_shared:bug-detection-guide` (debug classifier may consult).

---

## 10. UX baseline (mandatory cross-flow)

Per `_shared-ux-baseline.md`, R6b honors:

- **Per-task artifact split** — RIPPLE-ANALYSIS.json: flat by default; per-affected-artifact split when file size exceeds 30 KB advisory threshold (consumer pattern: `vg-load --phase N --artifact ripple-analysis [--affected <path>]`). DEBUG-CLASSIFY.json: always flat (small).
- **Subagent spawn narration** — every `Agent(vg-amend-impact-analyzer)` and `Agent(vg-debug-classifier)` wraps with `vg-narrate-spawn.sh`. Both STEP 2 sections show the canonical pre/post pattern.
- **Compact hook stderr** — no new hooks added by R6b. Subagent failures are narration events, not hook blocks. Schema validation failures (orchestrator-side) emit blocks following R1a 3-line pattern.
