# VG Blueprint Pilot — Progressive Disclosure + Hook-Based Forcing Function

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Author:** Brainstorm session via superpowers brainstorming skill
**Pilot scope:** `vg:blueprint` only. 8 other pipeline commands replicate template after pilot passes.

---

## 1. Background

### 1.1 Problem

VGFlow is a workflow harness that wraps Claude CLI and Codex to enforce strict step-by-step phase development. Despite extensive enforcement design (125 validators, hash-chained event store, contract pinning), dogfood evidence on PrintwayV3 shows the harness is not being followed in practice:

- `commands/vg/blueprint.md` is 3,970 lines / ~90,000 tokens — **18x over Anthropic's official SKILL.md ceiling of 500 lines**.
- `blueprint.tasklist_shown` event fires 28 times across runs, but `blueprint.native_tasklist_projected` fires **only 1 time** (3.5% adherence).
- 35 of 57 blueprint runs aborted (61% abort rate).
- Phase 3.2 RUNTIME-MAP.md missing despite review phase claiming completion.

### 1.2 Root cause (evidence-based)

Three reinforcing failures:

1. **Command file too large.** Instructions buried 500+ lines into a 3,970-line file. AI skips by reading lazily.
2. **Descriptive instead of imperative language.** "The first action IS a TodoWrite call" rather than "You MUST call TodoWrite NOW".
3. **Validators check events, not reality.** AI can satisfy contract by emitting events without performing the side-effect (e.g., calling TodoWrite). Harness verifies AI's claim, not the action.

### 1.3 Industry research (2026)

- **Anthropic official:** SKILL.md ≤ 500 lines, progressive disclosure pattern (entry SKILL.md + references/ on-demand). Orchestrator-worker pattern recommended for complex workflows. PreToolUse hooks are the primary gatekeeping mechanism. ([Source](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices))
- **AGENTIF benchmark (Tsinghua):** Best LLM models follow fewer than 30% of instructions in agentic scenarios. VGFlow's 3.5% is below even the empirical floor.
- **AgentSpec (ICSE 2026):** Runtime hook-based enforcement outperforms prose-based enforcement. "Cognitive load" of safety principles drops Task Success Rate; positive framing ("Always do X") has highest adherence.
- **AI Agent Anti-Patterns (Medium 2026):** "Instructions are guidance, not enforcement... No LLM can reliably execute hundreds of deterministic steps from memory. The fundamental issue is architectural."

### 1.4 Goals

- Reduce VG blueprint command file from 3,970 → ≤500 lines via progressive disclosure
- Add hook-based forcing functions (Anthropic-aligned) for hard gates
- Spawn custom subagents for heavy steps to enforce narrow context
- Empirically prove on PrintwayV3 dogfood that AI adherence improves
- Establish a replicable template for the other 8 pipeline commands

### 1.5 Non-goals (this round)

- A3 validator-reality refactor (defer; touches 125 entries, scope too large)
- Codex skill mirror regen (defer; verify Claude path first)
- 8 other pipeline commands (defer; pilot blueprint as canary)
- Migration of existing 16 completed PrintwayV3 blueprint runs (let them stand as-is)

---

## 2. Architecture

### 2.1 End-to-end flow (revised after Codex review)

```
User types: /vg:blueprint 2 in PrintwayV3 Claude Code
   ↓
[UserPromptSubmit hook] (NEW per Codex fix #1)
   detects /vg: invocation in prompt text
   creates .vg/active-runs/<session>.json BEFORE model executes
   prevents bypass: Stop hook would otherwise no-op without active run
   ↓
[SessionStart hook] (matchers: startup|resume|clear|compact)
   inject vg-meta-skill.md content + open diagnostics list (Layer 4)
   ↓
Claude reads commands/vg/blueprint.md (slim, ≤500 lines, imperative)
   ↓
SKILL.md STEP 1: Bash emit-tasklist.py
   → writes .vg/runs/<id>/tasklist-contract.json (6 groups, 18 steps)
   ↓
SKILL.md STEP 2: "Call TodoWrite NOW with these items..."
   ↓
Claude calls TodoWrite (tool) → tasklist visible in UI
   ↓
[PostToolUse hook on TodoWrite]
   captures payload via vg-orchestrator-emit-evidence-signed.py
   writes HMAC-signed .tasklist-projected.evidence.json
   (NOT direct write — protected path; PreToolUse on Write would block)
   ↓
For each step (loop):
   Claude calls Bash: vg-orchestrator step-active <step>
      ↓
   [PreToolUse hook on Bash] (vg-pre-tool-use-bash.sh)
      reads evidence file + verifies HMAC signature + checksum
      missing/invalid/mismatch → exit 2 with §4.5 Layer 1 diagnostic
   ↓
   IF Claude attempts Write to protected path (e.g., fake .step-markers):
      [PreToolUse hook on Write/Edit] (NEW per Codex fix #2)
         exit 2 with: "Use vg-orchestrator helper, not direct Write"
      Closes evidence-forgery bypass.
   ↓
   IF light step: Claude follows reference file inline (Read tool)
   IF heavy step (2a_plan, 2b_contracts):
      Main Claude calls Agent(subagent_type="vg-blueprint-planner", prompt={...})
      (Tool name: "Agent" per Claude Code docs, NOT "Task" — Codex fix #3)
      ↓
      [PreToolUse hook on Agent] (NEW per Codex fix #3)
         spawn-count check vs plan
      ↓
      Subagent narrow context + tools whitelist → cannot skim → returns artifact + checksum
      Main Claude validates → marks step done via signed helper
   ↓
   Claude calls Bash: vg-orchestrator mark-step blueprint <step>
   ↓
End: Claude calls Bash: vg-orchestrator run-complete
   ↓
[Stop hook] (vg-stop.sh)
   1. If no active VG run, exit 0
   2. Verify must_write paths + content_min_bytes
   3. Query events.db for must_emit_telemetry counts
   4. Check must_touch_markers
   5. NEW (Codex fix #5): invoke vg-state-machine-validator.py
      verifies events emitted in expected ORDER (semantic check beyond count)
   6. Check vg.block.fired paired with vg.block.handled (Layer 2)
   any failure → exit 2 + explicit missing list
   complete → allow stop
   ↓
Claude outputs summary, tasklist clears (close-on-complete)
```

### 2.2 Layered enforcement model

| Layer | Mechanism | Failure mode without it |
|---|---|---|
| 1. Surface | Slim SKILL.md ≤500 lines | AI reads 30% of file, skips rest |
| 2. Imperative language | HARD-GATE tags, "MUST", Red Flags | AI rationalizes around descriptive instructions |
| 3. Context bootstrap | SessionStart hook injects meta-skill | AI starts session without VG awareness |
| 4. Start-of-run gate | **UserPromptSubmit hook** detects `/vg:` invocation, force-creates active run state BEFORE model execution | AI answers without active run → all 4 below hooks no-op (Codex-caught bypass #1) |
| 5. Tool gate | PreToolUse hook on critical Bash AND `Write`/`Edit` for protected paths | AI skips TodoWrite, calls step-active OR fakes evidence file via Write (Codex-caught bypass #2) |
| 6. Evidence capture | PostToolUse hook on TodoWrite | No proof TodoWrite was called with right content |
| 7. Subagent isolation | Custom agents with narrow tools/system prompt; PreToolUse on **`Agent`** tool name (NOT `Task` — see §4.4 hook matchers) | Heavy step gets skimmed by lazy main agent |
| 8. Completion gate | Stop hook validates runtime contract + state-machine ordering | AI ends turn before contract satisfied OR emits events out-of-order |

Removing any layer reverts to a known failure mode. All 8 layers required for pilot. **Layers 4, 5, and the state-machine portion of 8 added per Codex review (2026-05-03) — original 7-layer design left bypass vectors unaddressed.**

---

## 3. File and directory layout

### 3.1 Canonical (`vgflow-bugfix` repo)

```
commands/vg/
  blueprint.md                              REFACTOR: 3,970 → ~450 lines
  _shared/blueprint/                        NEW dir — FLAT structure (Codex review: Anthropic recommends 1-level refs)
    preflight.md                            ~300 lines (5 light steps)
    design.md                               ~250 lines (4 UI steps)
    plan-overview.md                        ~100 lines (entry for plan group, instructs subagent spawn)
    plan-delegation.md                      ~150 lines (input/output contract for vg-blueprint-planner)
    contracts-overview.md                   ~100 lines (entry for contracts group)
    contracts-delegation.md                 ~150 lines (input/output for vg-blueprint-contracts)
    verify.md                               ~250 lines (7 grep/path check steps)
    close.md                                ~150 lines (bootstrap + complete)
    # Note: NO nested subdirs (plan/, contracts/) per Codex review fix #4.
    # Entry SKILL.md must directly list ALL leaf refs above.

agents/                                     NEW canonical dir
  vg-blueprint-planner/SKILL.md             ~200 lines, narrow task
  vg-blueprint-contracts/SKILL.md           ~200 lines, narrow task

scripts/hooks/                              NEW
  vg-user-prompt-submit.sh                  NEW (Codex fix #1) — detect /vg:* invocation, create active-run state file before model runs
  vg-session-start.sh                       inject meta-skill content (matchers: startup|resume|clear|compact)
  vg-pre-tool-use-bash.sh                   gate before step-active
  vg-pre-tool-use-write.sh                  NEW (Codex fix #2) — deny Write/Edit on protected paths (.vg/runs/*evidence*, .step-markers/*, events.db, .tasklist-projected.evidence.json) unless via signed orchestrator helper
  vg-pre-tool-use-agent.sh                  NEW (Codex fix #3) — match tool name "Agent" (NOT "Task"); spawn-count check (build spec strengthen)
  vg-post-tool-use-todowrite.sh             capture + checksum evidence
  vg-stop.sh                                run-complete contract check + state-machine order verify
  vg-meta-skill.md                          text injected by SessionStart
  install-hooks.sh                          merge hooks block into target settings.json

scripts/
  vg-orchestrator-emit-evidence-signed.py   NEW (Codex fix #2) — only path that writes protected evidence files; signs with HMAC stored in .vg/.evidence-key (mode 0600)
  vg-state-machine-validator.py             NEW (Codex fix #5) — verifies events emitted in expected ORDER per command (e.g., tasklist_shown → native_tasklist_projected → step.active → mark-step → run-complete)

scripts/tests/
  test_blueprint_pilot_*.py                 NEW test files
```

### 3.2 PrintwayV3 install (via `sync.sh`)

```
.claude/commands/vg/blueprint.md
.claude/commands/vg/_shared/blueprint/...
.claude/agents/vg-blueprint-planner/SKILL.md
.claude/agents/vg-blueprint-contracts/SKILL.md
.claude/scripts/hooks/...
.claude/settings.json                       hooks block merged idempotently
```

---

## 4. Components

### 4.1 Slim entry SKILL.md (`commands/vg/blueprint.md`, ~450 lines)

Structure:

```markdown
---
name: vg:blueprint
description: ...
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Task, TodoWrite]
runtime_contract:
  must_write: [...]            # unchanged from current — Stop hook authority
  must_touch_markers: [...]
  must_emit_telemetry: [...]
  forbidden_without_override: [...]
---

<HARD-GATE>
You MUST follow steps 1-6 in exact order. Skipping ANY step will be blocked
by the PreToolUse hook. You CANNOT rationalize past these gates.
</HARD-GATE>

## Red Flags

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau"        | Hook BLOCK ngay tool call kế tiếp |
| "Step này đơn giản, bỏ qua"                | Marker thiếu = run-complete fail |
| "Subagent overkill cho step này"           | Heavy step PHẢI dùng subagent. Đo: AI lười 96.5% nếu không có |
| "Tôi đã hiểu, không cần đọc reference"     | Reference có instruction cụ thể không có ở entry |

## Steps

### STEP 1 — preflight
Read `_shared/blueprint/preflight.md`. Follow it exactly.

### STEP 2 — design
Read `_shared/blueprint/design.md`. Follow it exactly.

### STEP 3 — plan (HEAVY)
Read `_shared/blueprint/plan-overview.md` AND `_shared/blueprint/plan-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-planner", ...)` per delegation contract.
(Tool name is `Agent`, not `Task` — verified per Claude Code hook docs.)
DO NOT plan inline.

### STEP 4 — contracts (HEAVY)
Read `_shared/blueprint/contracts-overview.md` AND `_shared/blueprint/contracts-delegation.md`.
Then call `Agent(subagent_type="vg-blueprint-contracts", ...)` per delegation contract.
DO NOT generate contracts inline.

### STEP 5 — verify
Read `_shared/blueprint/verify.md`. Follow it exactly.

### STEP 6 — close
Read `_shared/blueprint/close.md`. Follow it exactly.
```

Imperative language rules applied throughout:
- "MUST" / "Do NOT" / "STEP X" instead of "should" / "may" / "will"
- Reference load instructions are imperative: "Read X. Follow it exactly. Do not continue until complete."
- Numbered steps with explicit ordering

### 4.2 Reference files (6 group + 2 nested sub-refs)

Each ref ≤500 lines (Anthropic ceiling). Imperative throughout.

For `plan/overview.md` (entry of heavy group):

```markdown
# Plan group — STEP 3

## Why this is delegated to subagent

The 2a_plan step requires reading CONTEXT.md (often 5,000+ lines), design refs,
and INTERFACE-STANDARDS, then producing PLAN.md. Empirical data from blueprint
dogfood shows main agent skims this step due to context length. Therefore:

<HARD-GATE>
You MUST spawn the `vg-blueprint-planner` subagent for this step.
You MUST NOT generate PLAN.md inline.
</HARD-GATE>

## How to spawn

1. Bash: vg-orchestrator step-active 2a_plan
2. Read `delegation.md` for the exact input/output contract
3. Call Task with:
   - subagent_type: "vg-blueprint-planner"
   - prompt: <as defined in delegation.md>
4. On return, validate artifact path + checksum
5. Bash: vg-orchestrator mark-step blueprint 2a_plan
```

### 4.3 Custom subagents

**`agents/vg-blueprint-planner/SKILL.md`:**

```markdown
---
name: vg-blueprint-planner
description: Generate PLAN.md for one phase. Input: phase context. Output: PLAN.md path + sha256 + summary. ONLY this task.
tools: [Read, Write, Bash, Grep]   # narrow whitelist — no Edit, no AskUserQuestion, no Task
model: opus
---

<HARD-GATE>
You are a planner. Your ONLY output is PLAN.md.
Return JSON: { "path": "...", "sha256": "...", "summary": "..." }.
You MUST NOT browse other files outside your input.
You MUST NOT modify files except writing PLAN.md.
You MUST NOT ask the user questions — your input is the contract.
</HARD-GATE>

## Input contract
- phase_dir: ${PHASE_DIR}
- context_path: ${PHASE_DIR}/CONTEXT.md
- interface_standards: ${PHASE_DIR}/INTERFACE-STANDARDS.md
- design_refs: list of paths

## Steps
1. Read all input paths
2. Apply ORG 6-dimension framework (Infra, Env, Deploy, Smoke, Integration, Rollback)
3. Generate PLAN.md per template
4. Compute sha256 of PLAN.md
5. Return JSON

## Failure modes
- Missing input → return error JSON, do NOT write partial PLAN.md
- Cannot satisfy ORG 6-dim → return error JSON with which dim failed
```

**`agents/vg-blueprint-contracts/SKILL.md`** follows the same pattern, output: API-CONTRACTS.md + INTERFACE-STANDARDS.{md,json}.

### 4.4 SEVEN hook scripts (revised after Codex review)

| Hook | Matcher | Script | Block? | Purpose |
|---|---|---|---|---|
| **UserPromptSubmit** (NEW, Codex fix #1) | empty (fires every prompt) | `vg-user-prompt-submit.sh` | YES if invalid | Detect `/vg:<cmd> <args>` in prompt text. If detected, create `.vg/active-runs/<session>.json` BEFORE model executes. If user already has active run + tries different `/vg:<cmd>`, block + ask resolution. Closes Codex bypass #1 (Stop hook no-op without active run). |
| SessionStart | `startup\|resume\|clear\|compact` (added `resume` per Codex) | `vg-session-start.sh` | No | Inject `vg-meta-skill.md` content as `additionalContext`. On `compact`/`resume`, also inject open diagnostics list per §4.5 Layer 4. |
| PreToolUse on Bash | `Bash` (regex match `vg-orchestrator step-active` in command) | `vg-pre-tool-use-bash.sh` | YES (exit 2) | Read `.vg/runs/<run_id>/.tasklist-projected.evidence.json` (HMAC-signed). If missing/invalid signature/checksum mismatch, block + diagnostic stderr. |
| **PreToolUse on Write/Edit** (NEW, Codex fix #2) | `Write\|Edit` matching protected paths via regex on tool input `file_path` | `vg-pre-tool-use-write.sh` | YES (exit 2) | Block direct write to protected paths: `.vg/runs/*/evidence*`, `.vg/runs/*/.tasklist-projected.evidence.json`, `**/.step-markers/**`, `.vg/events.db`, `.vg/events.jsonl`. Stderr: "Use vg-orchestrator-emit-evidence-signed.py instead — direct writes forge evidence." Closes Codex bypass #2 (forgeable evidence). |
| **PreToolUse on Agent** (NEW, Codex fix #3 — name was wrong in original spec) | `Agent` (verified per Claude Code docs — NOT `Task`) | `vg-pre-tool-use-agent.sh` | YES if shortfall | Spawn-count check (per build spec). Reads active wave plan, verifies subagent_type matches allow-list, increments spawn counter. |
| PostToolUse on TodoWrite | `TodoWrite` | `vg-post-tool-use-todowrite.sh` | No | Read tool input payload, diff against `tasklist-contract.json`, write evidence via `vg-orchestrator-emit-evidence-signed.py` (NOT direct write — see §4.5b). |
| Stop | empty matcher | `vg-stop.sh` | YES (exit 2) | (1) If no active VG run, exit 0. (2) Verify `runtime_contract.must_write` paths + content_min_bytes. (3) Query events.db for `must_emit_telemetry` counts. (4) Check `must_touch_markers`. (5) **NEW (Codex fix #5)** invoke `vg-state-machine-validator.py` to verify event ORDER matches expected sequence. (6) Check `vg.block.fired` paired with `vg.block.handled` per §4.5 Layer 2. Any failure → exit 2 + explicit missing list. |

### 4.4b Signed evidence helper (NEW per Codex fix #2)

`scripts/vg-orchestrator-emit-evidence-signed.py`:
- The ONLY path that writes to protected paths (.vg/runs/*evidence*, .step-markers, events.db).
- Signs payload with HMAC-SHA256 using key at `.vg/.evidence-key` (mode 0600, gitignored).
- Hooks (PostToolUse on TodoWrite, PreToolUse step-active) verify signature before trusting evidence.
- Direct AI Write/Edit to these paths blocked by `vg-pre-tool-use-write.sh`.
- Pattern adopted from `allow_flag_gate.py` HMAC pattern already in VG.

### 4.4c State-machine validator (NEW per Codex fix #5)

`scripts/vg-state-machine-validator.py`:
- Defines per-command expected event ORDER (state machine).
- Example for blueprint:
  1. `blueprint.tasklist_shown` (1×)
  2. `blueprint.native_tasklist_projected` (1×)
  3. `blueprint.step_active` events (≥18×, in step order)
  4. `blueprint.plan_written` (1×, after 2a_plan step.active)
  5. `blueprint.contracts_generated` (1×, after 2b_contracts step.active)
  6. `crossai.verdict` (1×, unless --skip-crossai)
  7. `blueprint.completed` (1×, last)
- Stop hook invokes this before allowing run-complete.
- Catches: events emitted but in wrong order (semantic violation) — closes Codex bypass #5.

**Hook installation strategy:** sync via `install-hooks.sh` which idempotently merges the hooks block into target `.claude/settings.json`. Existing user hooks preserved. Re-running install does not duplicate.

### 4.5 Diagnostic flow when blocked (5 layers, prevents silent fail / context loss)

When a hook blocks (PreToolUse exit 2, Stop exit 2), AI must NOT silently retry. The design enforces 5 layers:

#### Layer 1 — Block message is a structured diagnostic prompt, not an error

Hook stderr is formatted as an imperative prompt that obligates AI to do 3 things in order:

```
═══════════════════════════════════════════
DIAGNOSTIC REQUIRED — Gate: <gate_id>
═══════════════════════════════════════════

CAUSE:
  <human-readable explanation, e.g.: "TodoWrite has not been called for run
  abc-123. tasklist-contract.json was written at .vg/runs/abc-123/ with
  checksum X, but evidence file .tasklist-projected.evidence.json does not
  exist.">

REQUIRED FIX:
  1. Read .vg/runs/abc-123/tasklist-contract.json
  2. Call TodoWrite with each checklist group as one todo item
  3. Verify PostToolUse hook wrote evidence file
  4. Retry the blocked Bash call

YOU MUST DO ALL THREE BEFORE CONTINUING:
  A) Tell user using this narrative template (in session language):
     "[VG diagnostic] Bước <step> đang bị chặn. Lý do: <one-sentence cause>.
      Đang xử lý: <one-sentence fix>. Sẽ tiếp tục sau khi xong."
  B) Bash: vg-orchestrator emit-event vg.block.handled \
            --gate <gate_id> --resolution "<summary>"
  C) Retry the original tool call

If this gate has blocked ≥3 times this run, you MUST call AskUserQuestion
instead of retrying.
═══════════════════════════════════════════
```

AI cannot silently retry — the message contractually requires narration + event emission + retry, in that order.

#### Layer 2 — Block event tracking (no silent skip)

- Hook script, before exit 2, emits event `vg.block.fired` (gate_id, run_id, timestamp, cause).
- Diagnostic acknowledgement = event `vg.block.handled` with same gate_id (emitted by AI bash after narrating to user).
- **Stop hook compares**: `count(vg.block.fired) == count(vg.block.handled)`. Mismatch → exit 2 with list of unhandled blocks.

If AI retries without narrating, Stop hook BLOCKs run-complete with: "3 blocks fired, only 1 handled. Missing diagnostic for: [PreToolUse-tasklist, ...]". Run cannot end.

#### Layer 3 — Escalation after N blocks on same gate (prevents infinite loop)

- Hook counts `block-per-gate-per-run` (read from events.db at hook time).
- Block 1, 2: stderr = diagnostic prompt as Layer 1.
- Block 3+: stderr appends: "**This gate has blocked 3 times. You MUST call AskUserQuestion before retrying.**"
- AI tries to retry on block 4 → hook blocks again with same escalation message.

Forces user-in-the-loop when a gate cannot resolve automatically.

#### Layer 4 — Re-inject open diagnostics on context compaction (AI cannot forget)

- SessionStart hook fires on `startup`, `clear`, AND `compact` events.
- Hook script, when fired, does TWO things:
  1. Inject base `vg-meta-skill.md` content
  2. Query events.db for active run, find `vg.block.fired` without paired `vg.block.handled`, inject inline:
     ```
     OPEN DIAGNOSTICS for current run <run_id>:
       - Gate: <gate_id_1> blocked at <timestamp> — cause: <...>
       - Gate: <gate_id_2> blocked at <timestamp> — cause: <...>
     You MUST complete diagnostic for each before continuing other work.
     ```
- `vg-meta-skill.md` has section "Open diagnostic threads" explaining the mechanism.

After context compaction, AI immediately re-sees pending diagnostics. Cannot "forget" them.

#### Layer 5 — User narrative requirement (prevents silent fail toward user)

- `vg-meta-skill.md` (SessionStart-injected) contains rule:
  ```
  WHEN a hook blocks your tool call, you MUST narrate to the user in
  session language what is happening BEFORE retrying. Use the template
  provided in the block message. NEVER retry silently.

  WHY: User must understand workflow state. Silent retry causes user to
  think the tool is hung or AI is confused. This violates the workflow
  transparency contract.
  ```
- Layer 1's diagnostic prompt **inline provides the narrative template** AI must use → no need for AI to invent format.

A non-tech user reads: `[VG diagnostic] Bước 2a_plan đang bị chặn. Lý do: chưa gọi TodoWrite. Đang xử lý: project tasklist-contract. Sẽ tiếp tục sau khi xong.` Understandable immediately.

### 4.6 SessionStart meta-skill content (`vg-meta-skill.md`)

Injected as `additionalContext` per Anthropic SessionStart hook spec. Content:

```markdown
<EXTREMELY-IMPORTANT>
You have entered a VGFlow workflow session.

VGFlow is a deterministic harness. Steps are not suggestions. They are
contracts validated by hooks. You CANNOT skip a step by claiming it is
"obvious" or "already done" — every step has a marker file and an event
record that the Stop hook verifies.

If a tool call is blocked by PreToolUse hook, read the stderr message,
fulfill the missing prerequisite, then retry. Do not work around the gate.
</EXTREMELY-IMPORTANT>

## Red Flags (you have used these before — they will not work)

| Thought | Reality |
|---|---|
| "I already understand the structure, no need to read references" | References contain step-specific instructions absent from entry |
| "Subagent overkill for this small step" | Heavy step has empirical 96.5% skip rate without subagent |
| "TodoWrite is just UI, the contract is in events" | Hook checks TodoWrite payload against contract checksum |
| "I can mark step done now and finish content later" | Stop hook reads must_write content_min_bytes; placeholder fails |
| "The block was a one-off, retrying should work" | Each block emits vg.block.fired; Stop hook blocks if unhandled |
| "I'll just retry, no need to tell the user" | Layer 5 rule: narrate in session language using template, never retry silently |

## Open diagnostic threads (Layer 4 mechanism)

If this injected context contains "OPEN DIAGNOSTICS for current run", you
have unresolved blocks from earlier in this run (possibly across context
compactions). For each open diagnostic, you MUST:

1. Read the cause + required fix from the original block message (still in
   events.db, query: `vg-orchestrator query-events --event-type vg.block.fired`)
2. Apply the fix
3. Narrate to user in session language using the template from the original block
4. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`

You CANNOT do other work until all open diagnostics are closed. Stop hook
will refuse run-complete if any vg.block.fired is unpaired with vg.block.handled.

## Pipeline commands governed by VGFlow

project, roadmap, specs, scope, blueprint, build, review, test, accept

When the user invokes `/vg:<cmd>`, follow the slim entry SKILL.md exactly.
Read references when instructed. Spawn subagents when instructed.
```

---

## 5. Error handling, migration, testing, exit criteria

### 5.1 Error handling

All block messages follow the diagnostic flow defined in §4.5 (5-layer mechanism). Specifics:

- **Hook script crash** — exit code passed to Claude, stderr visible. Hook scripts use `set -euo pipefail`. Crashes still emit `vg.block.fired` so they are tracked.
- **Missing evidence (PreToolUse fail)** — block with stderr formatted per §4.5 Layer 1 (CAUSE / REQUIRED FIX / 3-step obligation). Cause text: "TodoWrite has not been called for run `<run_id>`."
- **Checksum mismatch (TodoWrite payload differs from contract)** — block with diff output showing expected vs actual checklist items, formatted per §4.5 Layer 1.
- **Subagent failure (Task tool returns error)** — main Claude retries up to 2 times (Layer 3 escalation: 3rd failure forces AskUserQuestion). Each failure emits `vg.subagent.failed` event.
- **Subagent returns invalid artifact** — step-end validator checks artifact format. If invalid, mark step incomplete, force re-do. Counts toward Layer 3 escalation.
- **Stop hook violation** — exit 2 with explicit list of missing artifacts/markers/events AND list of unhandled `vg.block.fired` events. Format: `MISSING: must_write/PLAN.md (file does not exist)\nMISSING: must_touch_markers/2c_verify\nMISSING: must_emit_telemetry/blueprint.contracts_generated (count 0, expected ≥1)\nUNHANDLED DIAGNOSTIC: gate=PreToolUse-tasklist-checksum (fired at <ts>, no vg.block.handled paired)`.

### 5.2 Migration / backward compat

- **16 completed PrintwayV3 blueprint runs (existing):** No migration. They stand as-is.
- **138 existing tests:** Must continue to pass. New tests added alongside, do not break old.
- **Codex skill mirror:** Defer to round 2 (after Claude path verified).
- **7 orphan runs in PrintwayV3:** Cleanup via existing `vg-orchestrator quarantine` (out of scope for this design).

### 5.3 Testing

**Static (pytest):**
- `test_blueprint_slim_size.py` — assert `commands/vg/blueprint.md` ≤ 600 lines
- `test_blueprint_references_exist.py` — assert 6 group refs + 2 nested sub-refs exist with min content size
- `test_blueprint_imperative_language.py` — grep for "MUST", "Do NOT", "STEP X" in instruction context; fail if "should", "may", "will" found in instruction context
- `test_subagent_definitions_exist.py` — assert 2 agent SKILL.md files with valid frontmatter (name, description, tools, model)
- `test_hook_scripts_executable.py` — assert +x bit on all 4 hook scripts
- `test_hook_pretooluse_blocks.py` — simulate run with missing evidence file, assert hook exits 2 with stderr matching §4.5 Layer 1 format (CAUSE / REQUIRED FIX / 3-step obligation)
- `test_hook_posttooluse_writes_evidence.py` — simulate TodoWrite tool input, assert evidence file written with correct schema and checksums
- `test_install_hooks_idempotent.py` — run install-hooks.sh twice, assert settings.json hooks block has no duplicate entries
- `test_hook_emits_block_event.py` — simulate PreToolUse exit 2, assert `vg.block.fired` event written to events.db with gate_id, run_id, cause
- `test_stop_hook_requires_block_handled_pair.py` — simulate run with 1 vg.block.fired and 0 vg.block.handled, assert Stop hook exits 2 with "UNHANDLED DIAGNOSTIC" line
- `test_repeated_block_escalation.py` — simulate 3 blocks on same gate, assert 3rd stderr contains "MUST call AskUserQuestion before retrying"
- `test_session_start_reinjects_open_diagnostics.py` — simulate run with unhandled block + compact event, assert SessionStart hook output contains "OPEN DIAGNOSTICS for current run" with the block listed
- **NEW (Codex fix #1)** `test_user_prompt_submit_creates_run.py` — simulate `/vg:blueprint 2` prompt submission, assert hook creates `.vg/active-runs/<session>.json` BEFORE model invocation
- **NEW (Codex fix #2)** `test_pre_tool_use_write_blocks_protected.py` — for each protected path pattern, simulate Write/Edit, assert hook exits 2 with stderr referencing signed helper
- **NEW (Codex fix #2)** `test_evidence_helper_signs_hmac.py` — simulate orchestrator emit-evidence call, assert evidence file has valid HMAC signature; tampered evidence rejected by hook
- **NEW (Codex fix #3)** `test_pre_tool_use_agent_matcher.py` — assert hook config uses tool name `Agent` (not `Task`); spawn-count enforcement works
- **NEW (Codex fix #5)** `test_state_machine_validator.py` — for blueprint command, simulate events emitted out of order (mark-step before step.active), assert validator returns FAIL with explicit ordering violation
- **NEW (Codex fix #4)** `test_blueprint_refs_flat_structure.py` — assert `_shared/blueprint/` has FLAT structure (no nested subdirs), entry SKILL.md directly lists all leaf refs

**Empirical dogfood (manual run + automated metric query):**
- Sync to PrintwayV3 via `DEV_ROOT=".../PrintwayV3" ./sync.sh --no-global`
- Open fresh Claude Code session in PrintwayV3 working directory (restart required for command text reload)
- Invoke `/vg:blueprint 2`
- After completion, run `scripts/query-pilot-metrics.py --run-id <latest>` which queries `.vg/events.db` and asserts the 8 exit criteria below

### 5.4 Exit criteria — pilot PASS requires ALL of:

1. Tasklist visible in Claude Code UI immediately after invocation
2. `blueprint.native_tasklist_projected` event count = 1 in this run (baseline 1/28 = 3.5%)
3. All 18+ step markers touched without override flag
4. PLAN.md and API-CONTRACTS.md exist with non-placeholder content (content_min_bytes met)
5. Two `Agent` tool invocation events present (one per heavy step) — tool name verified `Agent` not `Task`
6. Manual test: simulate skipping TodoWrite, PreToolUse hook blocks with diagnostic stderr formatted per §4.5 Layer 1
7. User (sếp) reads workflow narration end-to-end and reports understanding each step's purpose (qualitative)
8. Stop hook fires without exit 2 (run-complete contract satisfied)
9. Manual test: triggered block produces user-facing narration in session language using §4.5 Layer 5 template (not silent retry)
10. Stop hook fails closed if `vg.block.fired` events are not paired with `vg.block.handled` (verify with manual induce-and-skip test)
11. **NEW (Codex fix #1)**: UserPromptSubmit hook fires on `/vg:blueprint 2` invocation, creates active-run state file BEFORE first model response (verify via filesystem timestamp)
12. **NEW (Codex fix #2)**: simulate AI Write to `.vg/runs/<id>/.tasklist-projected.evidence.json` directly → PreToolUse on Write/Edit blocks with stderr "Use vg-orchestrator-emit-evidence-signed.py instead"
13. **NEW (Codex fix #5)**: state-machine validator catches event emitted in wrong order (e.g., `mark-step` before `step.active`) → Stop hook blocks

Pilot FAILS if any criterion missed. Failure path: return to design phase. **Do not scale to other commands.**

### 5.5 Multi-canary R1 strategy (NEW per Codex review)

Codex flagged: "Blueprint R1 passing is insufficient for R2-R5. You need separate canaries for parallel build waves, interactive UAT/scope/project flows, review/roam lens dispatch, and phase parent-tasklist mode."

R1 is now a **multi-canary phase** with 4 sub-pilots, each verifying a distinct pattern:

| Canary | Spec | Verifies pattern |
|---|---|---|
| **R1a — blueprint** | this spec | slim+refs+hooks+diagnostic baseline |
| **R1b — phase** | `2026-05-03-vg-phase-design.md` | parent-tasklist coordination (VG_PARENT_RUN_ID) |
| **R1c — scope** | `2026-05-03-vg-scope-design.md` | interactive UX with challenger/expander Agent invocations (5 rounds) |
| **R1d — review** | `2026-05-03-vg-review-design.md` | lens dispatch + parallel Haiku scanners + per-lens telemetry |

R2-R5 only proceed after ALL 4 canaries pass. R1a is sequential first (blueprint is canonical template); R1b/c/d can run in parallel after R1a.

Rationale: each pattern dimension has unique failure modes. Blueprint passing doesn't validate that interactive UX (scope) or parallel scanners (review) work. Single-pilot extrapolation is the trap.

---

## 6. Replication template (8 other pipeline commands)

### 6.1 Shared vs per-command split

| Component | Shared/Per-command | Built once or N times |
|---|---|---|
| 4 hook scripts (SessionStart, PreToolUse, PostToolUse, Stop) | SHARED infrastructure | 1× (in pilot) |
| `vg-meta-skill.md` (text injected) | SHARED | 1× base, append Red Flags section per command |
| `install-hooks.sh` | SHARED | 1× |
| Slim SKILL.md (≤500 lines, imperative) | PER-COMMAND | Each command refactored |
| Reference files `_shared/<cmd>/*` | PER-COMMAND | Each command has own dir |
| Custom subagents | PER-HEAVY-STEP | Only for steps with current spec >300 lines (the threshold for "AI cannot reliably hold the step in working context") |

→ Hook code written for blueprint pilot is reused for all 8 other commands. Per-command work after pilot is (a) shrink + refs and (b) optional subagents for heavy steps.

### 6.2 Mapping table — 9 V5 pipeline commands

| # | Command | Lines | Treatment | Heavy steps needing subagent | Replication round |
|---|---|---|---|---|---|
| 0 | `project` | 1,590 | Slim + refs | 0 (mostly Q&A) | 4 |
| 1 | `roadmap` | 377 | Hooks + imperative cleanup only (already <500) | 0 | 5 |
| 2 | `specs` | 457 | Hooks + imperative cleanup only | 0 | 5 |
| 3 | `scope` | 1,380 | Slim + refs | 1 (`scope_round_synthesis`) | 4 |
| 4 | **`blueprint`** | **3,970** | **PILOT — full treatment** | **2** (`2a_plan`, `2b_contracts`) | **1 (this round)** |
| 5 | `build` | 4,571 | Slim + refs + subagents | 2-3 (`wave_execution`, `crossai_build_verify`, possibly `api_truthcheck_loop`) | 2 |
| 6 | `review` | 7,413 | Slim + refs + subagents + lens-as-plugin | 4-5 (`code_scan`, `browser_discovery`, `lens_dispatch`, `findings_merge`, `crossai_review`) | 3 |
| 7 | `test` | 4,188 | Slim + refs + subagents | 3-4 (`runtime_smoke`, `codegen`, `regression`, `security_audit`) | 2 |
| 8 | `accept` | 2,429 | Slim + refs | 1-2 (`uat_narrative_autofire`, `security_baseline`) | 4 |

### 6.3 Sequencing strategy

Rounds are sequential (each waits for previous to ship + dogfood-verify):

- **Round 1 (this pilot):** blueprint full treatment + shared infrastructure (hooks + meta-skill + install). Verify dogfood `/vg:blueprint 2` on PrintwayV3.
- **Round 2 (after R1 passes):** build + test (heavy execution + verification, exercise multi-subagent pattern).
- **Round 3 (after R2 passes):** review (heaviest at 7,413 lines, riskiest, most lens injection complexity — last because pattern needs 2 rounds of validation first).
- **Round 4 (after R3 passes):** project + scope + accept (medium, fewer heavy steps).
- **Round 5 (after R4 passes):** roadmap + specs (small, cleanup only — hooks reused, imperative pass, no shrink needed).

Rationale:
- Round 1 builds infrastructure once for all
- Round 2 proves subagent pattern scales beyond pilot
- Round 3 tackles the heaviest only after pattern validated twice
- Round 4 medium difficulty, low risk
- Round 5 essentially "free" — hooks already installed, just imperative cleanup

### 6.4 Per-command checklist (rounds 2-5)

For each command after pilot:
1. Identify checklist groups from `emit-tasklist.py` output
2. Identify heavy steps (>300 lines current spec) → enumerate subagents needed
3. Refactor entry SKILL.md to ≤500 lines, imperative, reference load instructions
4. Create `_shared/<cmd>/` directory with one file per checklist group
5. Create `agents/vg-<cmd>-<step>/SKILL.md` per heavy step
6. Append Red Flags section to `vg-meta-skill.md` for command-specific rationalizations
7. Sync to PrintwayV3, run dogfood, measure metrics
8. Static tests: slim size, refs exist, imperative language, subagent valid

### 6.5 Hook architecture stability (point of no return)

Pilot blueprint PASS → 8 other commands replicate template. Hook architecture frozen.

Pilot blueprint FAIL → STOP. Return to forcing function design. Do not touch other commands.

The pilot is the gate that decides the entire roadmap.

---

## 7. References

- Anthropic, "Equipping agents for the real world with Agent Skills" — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Anthropic, "Effective harnesses for long-running agents" — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, "Building Effective AI Agents" — https://www.anthropic.com/research/building-effective-agents
- Anthropic, "How we built our multi-agent research system" — https://anthropic.com/engineering/built-multi-agent-research-system
- Claude API Docs, "Skill authoring best practices" — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Claude Code Docs, "Hooks reference" — https://code.claude.com/docs/en/hooks
- Claude Code Docs, "Create custom subagents" — https://docs.anthropic.com/en/docs/claude-code/sub-agents
- AGENTIF benchmark (Tsinghua) — https://keg.cs.tsinghua.edu.cn/persons/xubin/papers/AgentIF.pdf
- AgentSpec (ICSE 2026) — https://cposkitt.github.io/files/publications/agentspec_llm_enforcement_icse26.pdf
- AI Agent Anti-Patterns Part 1 (Medium) — https://achan2013.medium.com/ai-agent-anti-patterns-part-1-architectural-pitfalls-that-break-enterprise-agents-before-they-32d211dded43
- Superpowers plugin (reference for SessionStart context injection pattern) — `/Users/dzungnguyen/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/`
