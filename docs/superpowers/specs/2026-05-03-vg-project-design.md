# VG Project — Slim Surface + Async Scan Subagent

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R4 (with scope and accept; depends on R1-R3 pattern proven)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/project.md` is **1,590 lines, 14 steps**. Initialization command — runs once per project, drives 7-round adaptive discussion to produce PROJECT.md + FOUNDATION.md + vg.config.md.

### 1.1 Heavy steps

| Step | Lines | Refactor approach |
|---|---|---|
| `4_mode_first_time` | **544** | Stays inline (interactive UX requirement — 7-round discussion loop) |
| `0c_scan_existing_docs` | **342** | **Subagent: `vg-project-scanner`** (Python-heavy, latency-tolerant, no user input) |

### 1.2 Why most heavy steps stay inline

Project is **CONVERSATIONAL-HEAVY** (13 AskUserQuestion across 7 rounds). Like accept's interactive UAT, the discussion loop must stay in main agent because:
- AskUserQuestion is tool with UI presentation; subagent breaks UX continuity
- Per-answer challenger + per-round expander already use Task tool subagents (preserve)
- Conversation fluency requires real-time main-agent control

Only `0c_scan_existing_docs` (342 lines, Python codebase scan across 9 categories) is latency-tolerant batch work — appropriate for subagent extraction.

### 1.3 Existing patterns to preserve

- **Adversarial challenger (R1-R7)** — Task tool, `general-purpose`, model=Haiku (or config), zero parent context, per-answer dispatch via `vg-challenge-answer-wrapper.sh`
- **Dimension expander (R1-R5 end)** — Task tool, model=Opus, per-round dispatch via `vg-expand-round-wrapper.sh`
- **Loop guards** — `adversarial_max_rounds` (default 3), `dimension_expand_max` (default 6)
- **Atomic write** — PROJECT.md + FOUNDATION.md + vg.config.md + .project-draft.json
- **Mode routing** — 7 modes (first_time, view, update, milestone, rewrite, migrate, init_only)

### 1.4 Audit findings

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | Adversarial challenger per-answer | PASS | Preserve as-is |
| 2 | Dimension expander per-round | PASS | Preserve as-is |
| 3 | Loop guards (max_rounds, expand_max) | PASS | Preserve as-is |
| 4 | Atomic write (PROJECT.md + FOUNDATION.md + vg.config.md) | PASS | Preserve as-is |
| 5 | `project.native_tasklist_projected` emission | **FAIL** (no project.* events in dogfood — never run yet) | **Strengthen** (inherit blueprint pilot fix) |
| 6 | Runtime contract minimal (only 2 events declared) | **PARTIAL** | Strengthen — add project.tasklist_shown + .native_tasklist_projected to must_emit |

**Summary:** 4/6 PASS, 1/6 FAIL, 1/6 PARTIAL.

### 1.5 Goals

- Reduce `commands/vg/project.md` from 1,590 → ≤500 lines
- Apply imperative + HARD-GATE + Red Flags
- Extract `0c_scan_existing_docs` to subagent
- Strengthen runtime_contract (add tasklist events, must_write PROJECT.md + FOUNDATION.md, must_touch_markers for 14 steps)

### 1.6 Non-goals

- Refactor of 7-round discussion loop (interactive UX)
- Refactor of challenger/expander pattern (already correct)
- Codex skill mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build/test/review/accept. All 4 hooks + diagnostic + meta-skill base.

---

## 3. File and directory layout

```
commands/vg/
  project.md                                REFACTOR: 1,590 → ~500 lines
  _shared/project/                          NEW dir
    preflight.md                            ~250 lines (parse args, print state, scan delegation)
    scan/                                   nested for subagent delegation
      overview.md                           ~100 lines (entry, instructs spawn vg-project-scanner)
      delegation.md                         ~150 lines (input/output for scanner)
    routing.md                              ~150 lines (1_route_mode + mode menu)
    modes/                                  nested for 7 mode handlers
      first-time.md                         ~400 lines (7-round discussion, INLINE — interactive UX)
      view.md                               ~50 lines
      update.md                             ~80 lines
      milestone.md                          ~80 lines
      rewrite.md                            ~80 lines
      migrate.md                            ~80 lines
      init-only.md                          ~70 lines
    close.md                                ~100 lines (10_complete)

agents/                                     EXTEND
  vg-project-scanner/SKILL.md               ~200 lines, codebase scan + manifest extraction
```

---

## 4. Components

### 4.1 Slim `commands/vg/project.md` (~500 lines)

```markdown
---
name: vg:project
description: Project identity + foundation + auto-init via 7-round adaptive discussion
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion]
runtime_contract:
  must_write:
    - "${PLANNING_DIR}/PROJECT.md"
    - "${PLANNING_DIR}/FOUNDATION.md"
    - "${PLANNING_DIR}/.vg/config.md"
  must_touch_markers:
    - "0_parse_args"
    - "0c_scan_existing_docs"
    - "1_route_mode"
    - "4_mode_first_time"   # only if mode=first_time
    - "10_complete"
  must_emit_telemetry:
    - "project.tasklist_shown"
    - "project.native_tasklist_projected"
    - "project.started"
    - "project.completed"
---

<HARD-GATE>
You MUST follow the routing logic. If mode=first_time, run all 7 discussion
rounds with adversarial challenger + dimension expander per round. DO NOT
skip rounds. DO NOT auto-derive without user confirmation in R6+R7.
</HARD-GATE>

## Red Flags (project-specific)

| Thought | Reality |
|---|---|
| "User just wants quick init, skip discussion rounds"  | Each round locks F-XX foundation decision; skip = downstream phases lack context |
| "Scan existing docs is overkill for new project"      | Step 0c detects existing artifacts; skip = re-prompt for already-known facts |
| "Challenger/expander only on 'big' rounds, skip small" | Both are already configurable via max_rounds + expand_max — manual skip violates contract |

## Steps (mode-routed)

### STEP 1 — preflight
Read `_shared/project/preflight.md`. Parse args, print state, run scan
(delegated to vg-project-scanner subagent).

### STEP 2 — routing
Read `_shared/project/routing.md`. Detect mode (first_time / view / update /
milestone / rewrite / migrate / init_only).

### STEP 3 — mode handler
Read `_shared/project/modes/<mode>.md`. Follow exactly.
- For `first_time`: 7-round discussion (INLINE — UX critical)
- For others: targeted updates per mode spec

### STEP 4 — close
Read `_shared/project/close.md`. Atomic write all output files. Emit
project.completed.
```

### 4.2 Custom subagent `vg-project-scanner/SKILL.md`

```markdown
---
name: vg-project-scanner
description: Scan codebase for existing project artifacts. Input: project root path. Output: manifest of detected files + categories. ONLY this task.
tools: [Read, Bash, Glob, Grep]
model: opus
---

<HARD-GATE>
You scan the codebase for existing project artifacts across 9 categories
(planning docs, code structure, tests, deployment, design, etc.). You return
a manifest. You do NOT modify files. You do NOT ask user questions.
</HARD-GATE>

## Categories to scan
1. Planning artifacts (PROJECT.md, FOUNDATION.md, ROADMAP.md, vg.config.md)
2. Phase artifacts (.vg/phases/, .planning/phases/)
3. Code structure (src/, app/, packages/, lib/)
4. Tests (tests/, __tests__/, *.spec.*, *.test.*)
5. Deployment (Dockerfile, docker-compose, .github/workflows, fly.toml)
6. Design (.pen, design/, mockups/)
7. Documentation (README*, docs/)
8. Configuration (package.json, tsconfig.json, requirements.txt, etc.)
9. Git state (recent commits, branches, .gitignore)

## Output JSON
{
  "categories": [
    { "name": "planning", "files": [...], "summary": "..." },
    ...
  ],
  "detected_stack": { "language": "...", "framework": "...", ... },
  "completeness": { "has_planning": bool, "has_tests": bool, ... }
}
```

### 4.3 Hooks (SHARED)

No new hooks.

### 4.4 Project-specific Red Flags addendum to `vg-meta-skill.md`

```markdown
## Project-specific Red Flags
| Thought | Reality |
|---|---|
| "Skip 7 rounds, user already knows what they want" | Each round produces F-XX foundation decision; skip = downstream phases ungrounded |
| "Scan delegation is overhead, just glob inline"    | vg-project-scanner has narrow context, returns structured manifest faster |
| "User said 'just init', skip mode menu"            | Mode menu state-aware; skip = wrong mode handler runs |
```

---

## 5. Error handling, migration, testing, exit criteria

### 5.1 Error handling

All blocks follow blueprint pilot §4.5. Project-specific:
- **Mode mismatch** (existing PROJECT.md but mode=first_time) → block with: "Project already initialized. Use mode=update or mode=rewrite. See routing logic."
- **Atomic write fail** (partial files written) → cleanup + retry; if 2 retries fail, escalate AskUserQuestion

### 5.2 Migration

- Existing projects with PROJECT.md: stand as-is.
- Defer: Codex mirror.

### 5.3 Testing

**Static (pytest):**
- `test_project_slim_size.py` — assert ≤ 600 lines
- `test_project_references_exist.py` — all `_shared/project/*.md` + nested
- `test_project_subagent_definition.py` — vg-project-scanner valid

**Empirical dogfood:**
- Run `/vg:project` on a fresh test directory
- Assert: PROJECT.md + FOUNDATION.md + vg.config.md all written, project.native_tasklist_projected event present

### 5.4 Exit criteria — project pilot PASS requires ALL of:

1. Tasklist visible immediately
2. `project.native_tasklist_projected` event ≥ 1
3. All applicable step markers touched (mode-dependent)
4. PROJECT.md + FOUNDATION.md + vg.config.md written
5. vg-project-scanner subagent invocation event present
6. 7-round discussion happens INLINE for mode=first_time (verify via tool log — challenger/expander Task events present, but NOT replaced by single subagent doing all 7 rounds)
7. Stop hook fires without exit 2

---

## 6. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Existing project.md: `commands/vg/project.md` (1,590 lines)
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
