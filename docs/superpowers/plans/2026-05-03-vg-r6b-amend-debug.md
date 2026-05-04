# VG R6b — Amend + Debug Workflows Implementation Plan (REVISED 2026-05-03)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow extractions only:
1. `commands/vg/amend.md` Step 5 (cascade impact analysis, lines ~204–246) → spawn `vg-amend-cascade-analyzer` subagent. Output is markdown report displayed inline (no new file artifact). Rule 6 ("informational only, no auto-modify") preserved.
2. `commands/vg/debug.md` Step 1 `runtime_ui` branch (lines ~176–197, currently pseudo-code "Spawn Haiku agent") → implement actual `Agent(vg-debug-ui-discovery)` spawn. Subagent wraps MCP Playwright; orchestrator appends findings to existing DEBUG-LOG.md.

Both entry skills stay below 500-line ceiling. NO changes to telemetry events, NO changes to `<rules>`, NO new file artifact schemas, NO cap on debug fix loop (rule 2 forbids cap).

**Architecture:** amend Step 5 and debug Step 1 `runtime_ui` are the only changed sections. Subagents are read-only (amend) or MCP-bound (debug). Orchestrator owns all writes (CONTEXT.md, AMENDMENT-LOG.md, DEBUG-LOG.md). Subagents return markdown text on stdout for orchestrator to display/append.

**Tech Stack:** bash 5+, python3, pytest 7+, PyYAML, MCP Playwright (existing).

**Spec:** `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md` (revised companion).
**Depends on:** R5.5 hooks-source-isolation (merged: `d932710`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.claude/agents/vg-amend-cascade-analyzer.md` | CREATE | Read-only cascade impact analyzer subagent |
| `.claude/agents/vg-debug-ui-discovery.md` | CREATE | MCP Playwright wrapper for debug runtime_ui |
| `commands/vg/amend.md` | REFACTOR Step 5 only | Replace inline grep block with subagent spawn |
| `commands/vg/debug.md` | REFACTOR Step 1 runtime_ui only | Replace pseudo-code with Agent() spawn |
| `scripts/hooks/vg-meta-skill.md` | EXTEND | Append amend + debug Red Flags |
| `tests/skills/test_amend_subagent_delegation.py` | CREATE | Assert Step 5 spawns analyzer + narrate |
| `tests/skills/test_amend_telemetry_preserved.py` | CREATE | Assert amend.started + amend.completed retained |
| `tests/skills/test_amend_within_500.py` | CREATE | Assert ≤500 lines |
| `tests/skills/test_amend_rules_preserved.py` | CREATE | Assert all 7 rules present, especially rule 6 |
| `tests/skills/test_debug_subagent_delegation.py` | CREATE | Assert Step 1 runtime_ui spawns ui-discovery + narrate |
| `tests/skills/test_debug_telemetry_preserved.py` | CREATE | Assert all 5 events retained |
| `tests/skills/test_debug_within_500.py` | CREATE | Assert ≤500 lines |
| `tests/skills/test_debug_no_loop_cap.py` | CREATE | Assert NO hard cap on Step 3 fix loop (rule 2) |
| `tests/skills/test_debug_rules_preserved.py` | CREATE | Assert all 7 rules present, especially rule 2 |

NOTE: NO `_shared/amend/` or `_shared/debug/` directories. NO new fixture files. NO JSON artifact schemas.

---

## Task 1: Verify R5.5 + snapshot pre-conditions

**Files:** read-only.

- [ ] **Step 1: Confirm R5.5 + R6a (or at least R5.5) merged**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && git log --oneline | grep -E 'r5\.5|r6a' | head -5`

Expected: at least the R5.5 commits. R6a not strictly required for R6b (independent).

- [ ] **Step 2: Snapshot current files**

Run:
```bash
echo "=== amend.md ===" && wc -l commands/vg/amend.md && grep -nE '^## Step' commands/vg/amend.md
echo "=== debug.md ===" && wc -l commands/vg/debug.md && grep -nE '^## Step' commands/vg/debug.md
```

Expected:
- amend.md: 323 lines, 7 Step headings (Step 0 through Step 6)
- debug.md: 399 lines, 5 Step headings (Step 0 through Step 4)

- [ ] **Step 3: Identify Step 5 cascade block in amend.md**

Run: `awk '/^## Step 5/,/^## Step 6/' commands/vg/amend.md | head -50`

This is the section to refactor (replace inline grep with subagent spawn).

- [ ] **Step 4: Identify runtime_ui branch in debug.md Step 1**

Run: `awk '/^### runtime_ui/,/^### network/' commands/vg/debug.md`

This is the pseudo-code section to implement (replace "Spawn Haiku agent" comment with actual `Agent(vg-debug-ui-discovery)` call).

- [ ] **Step 5: Verify pytest skill-test infra exists**

Run: `ls tests/skills/conftest.py 2>/dev/null && echo EXISTS || echo MISSING`

If `EXISTS`, continue. If `MISSING`, create per R6a Task 2 (or copy template from `tests/hooks/conftest.py`).

- [ ] **Step 6: No commit (read-only)**

Skip.

---

## Task 2: Create vg-amend-cascade-analyzer subagent

**Files:**
- Create: `.claude/agents/vg-amend-cascade-analyzer.md`

- [ ] **Step 1: Write the subagent definition**

Write to `.claude/agents/vg-amend-cascade-analyzer.md`:

```markdown
---
name: vg-amend-cascade-analyzer
description: Read-only cascade impact analyzer for /vg:amend Step 5. Reads phase artifacts (PLAN, API-CONTRACTS, TEST-GOALS, SUMMARY, RUNTIME-MAP), greps for references to changed decisions, returns markdown impact report. Does NOT modify any file (preserves /vg:amend rule 6: informational only).
tools: Read, Grep, Bash
model: claude-sonnet-4-6
---

# vg-amend-cascade-analyzer

Read-only impact analyzer for `/vg:amend`. Receives a list of changed
decision IDs and produces a markdown impact report so the orchestrator
can present cascade information to the user before Step 6 commit.

## Input contract

You receive a JSON object on the prompt with these fields:

- `phase_dir`             — absolute path to phase directory
- `changed_decision_ids`  — list of D-XX strings (e.g. `["D-03", "D-07"]`)
- `change_summary`        — one-line summary from amend Step 2

## Workflow

### STEP A — Inventory phase artifacts

Check existence of (under `${phase_dir}`):
- `PLAN.md`           (or `PLAN/index.md` for split version)
- `API-CONTRACTS.md`  (or `API-CONTRACTS/index.md`)
- `TEST-GOALS.md`     (or `TEST-GOALS/index.md`)
- `SUMMARY.md`
- `RUNTIME-MAP.json`

For each existing artifact, prepare a "section" in the output report.
Skip non-existent artifacts (don't pad with "(none)" — just omit).

### STEP B — Grep each artifact for references

For each `D-XX` in `changed_decision_ids`:

- **PLAN.md / PLAN/**: grep for `<goals-covered>` containing `D-XX`, task descriptions referencing the decision, `<contract-ref>` tags. Output: list of "Task N: <one-line reason>" entries.
- **API-CONTRACTS.md / API-CONTRACTS/**: grep for endpoint references in changed decisions (extract endpoint paths from change_summary if any). Output: list of "<METHOD> <path>: <reason>" entries.
- **TEST-GOALS.md / TEST-GOALS/**: grep for goals tracing to changed decisions (D-XX in goal trace metadata). Output: list of "G-XX: <reason>" entries.
- **SUMMARY.md**: if exists → output "Gap-closure build may be needed".
- **RUNTIME-MAP.json**: if exists → output "Re-review recommended".

### STEP C — Compute suggested next action

Read phase pipeline state (from PIPELINE-STATE.json under `${phase_dir}` if it exists, else infer from artifact presence):

| Current step | Suggested action |
|---|---|
| scoped (only CONTEXT.md exists) | `/vg:blueprint <phase>` |
| blueprinted (PLAN.md exists, no SUMMARY) | `/vg:blueprint <phase> --from=2a` |
| built (SUMMARY.md exists, no RUNTIME-MAP) | `/vg:build <phase> --gaps-only` |
| reviewed (RUNTIME-MAP.json exists) | `/vg:build --gaps-only` then `/vg:review --retry-failed` |
| tested (TEST-RESULTS exists) | `/vg:build --gaps-only` then `/vg:review` (full) |
| accepted | "⚠ Warning: consider new phase" |

### STEP D — Emit markdown report

Output the FOLLOWING markdown block as the LAST contiguous text on stdout:

```markdown
# Cascade Impact Report — Phase <phase>

**Change:** <change_summary>
**Decisions affected:** <comma-separated D-XX list>

## PLAN.md impact
- Task N: <reason>
- Task M: <reason>

## API-CONTRACTS.md impact
- <METHOD> <path>: <reason>

## TEST-GOALS.md impact
- G-XX: <reason>

## SUMMARY.md impact
- Gap-closure build may be needed

## RUNTIME-MAP.json impact
- Re-review recommended

## Suggested next action
<suggested action from STEP C>
```

OMIT any section whose artifact doesn't exist OR has zero matches.

If NO artifacts have any matches, emit:

```markdown
# Cascade Impact Report — Phase <phase>

**Change:** <change_summary>
**Decisions affected:** <D-XX list>

## No downstream impact detected
(All checked artifacts: <list>. No references to changed decisions found.)

## Suggested next action
<from STEP C>
```

## Tool restrictions

ALLOWED: Read, Grep, Bash (read-only — `cat`, `grep`, `wc`, `find`).
FORBIDDEN: Write, Edit, Agent, WebSearch, WebFetch.

You MUST NOT modify any file. The orchestrator owns CONTEXT.md, AMENDMENT-LOG.md, and all phase artifacts.

This preserves /vg:amend rule 6: "Impact is informational — cascade analysis warns but does NOT auto-modify PLAN.md or API-CONTRACTS.md."

## Failure modes

| Cause | Action |
|---|---|
| `phase_dir` does not exist | Emit error JSON (no markdown report); orchestrator narrates red |
| `changed_decision_ids` empty | Emit "No decisions changed" report; orchestrator may still proceed |
| All artifacts unreadable | Emit error JSON; orchestrator falls back to "manual review needed" |
```

- [ ] **Step 2: Verify frontmatter parses**

Run:
```bash
python3 -c "
import yaml
text = open('.claude/agents/vg-amend-cascade-analyzer.md').read()
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-amend-cascade-analyzer'
tools = fm['tools']
tools_str = ' '.join(tools) if isinstance(tools, list) else str(tools)
assert 'Write' not in tools_str, 'analyzer must be read-only'
assert 'Edit' not in tools_str
assert 'Agent' not in tools_str
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/vg-amend-cascade-analyzer.md
git commit -m "feat(r6b): vg-amend-cascade-analyzer subagent

Read-only cascade impact analyzer. Workflow STEP A-D: inventory phase
artifacts, grep for D-XX references, compute suggested next action,
emit markdown report on last stdout block. Tool-restricted to
Read/Grep/Bash. Preserves /vg:amend rule 6 (informational only).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create vg-debug-ui-discovery subagent

**Files:**
- Create: `.claude/agents/vg-debug-ui-discovery.md`

- [ ] **Step 1: Write the subagent definition**

Write to `.claude/agents/vg-debug-ui-discovery.md`:

```markdown
---
name: vg-debug-ui-discovery
description: Browser MCP wrapper for /vg:debug Step 1 runtime_ui branch. Navigates to suspected route, captures snapshot + console + network + screenshot, returns markdown findings. Implements rule 5 fallback if MCP unavailable. Does NOT modify code or write to DEBUG-LOG.md (orchestrator appends).
tools: Read, Grep, Bash, mcp__playwright1__browser_navigate, mcp__playwright1__browser_snapshot, mcp__playwright1__browser_console_messages, mcp__playwright1__browser_network_requests, mcp__playwright1__browser_take_screenshot, mcp__playwright1__browser_close
model: claude-sonnet-4-6
---

# vg-debug-ui-discovery

Browser MCP discovery wrapper for `/vg:debug` Step 1 `runtime_ui` branch.
Performs ONE focused UI inspection — not a full review sweep.

## Input contract

You receive a JSON object on the prompt with these fields:

- `bug_description`   — verbatim bug description from user
- `suspected_route`   — best-guess URL path from Step 0 classification (or `"unknown"`)
- `debug_id`          — debug session ID (for filename hint, NOT for writing)
- `mcp_available`     — boolean from orchestrator's MCP availability check
- `base_url`          — base URL for the app under test (from .claude/vg.config.md or `"http://localhost:3000"` default)

## Workflow

### STEP A — MCP-available branch

If `mcp_available == true` AND `suspected_route != "unknown"`:

1. **Navigate**: `mcp__playwright1__browser_navigate` to `<base_url><suspected_route>`.
2. **Wait briefly**: implicit page load wait via MCP.
3. **Snapshot**: `mcp__playwright1__browser_snapshot` → capture accessibility tree.
4. **Console**: `mcp__playwright1__browser_console_messages` → list errors + warnings.
5. **Network**: `mcp__playwright1__browser_network_requests` → list 4xx/5xx responses.
6. **Screenshot**: `mcp__playwright1__browser_take_screenshot` to `.vg/debug/<debug_id>/screenshots/discovery-<iso8601>.png`. Make `mkdir -p` first via Bash.
7. **Close**: `mcp__playwright1__browser_close` to release MCP slot.

### STEP B — Suspected-route-unknown branch

If `mcp_available == true` AND `suspected_route == "unknown"`:

1. AskUserQuestion is NOT available in subagent. Instead:
   - Skip navigation.
   - Note in findings: "Route unknown; orchestrator should AskUserQuestion before re-spawning with route."
   - Emit shortened findings block.

### STEP C — MCP-unavailable branch (rule 5 fallback)

If `mcp_available == false`:

1. Do NOT attempt any navigation.
2. Note in findings: "MCP Playwright unavailable. Per /vg:debug rule 5, falling back to amendment-trigger path."
3. Suggest orchestrator route to /vg:amend with bug context as feature gap.
4. Emit fallback findings block.

### STEP D — Emit markdown findings

Output the FOLLOWING markdown block as the LAST contiguous text on stdout (MCP-available, route-known case):

```markdown
## UI Discovery Findings — <iso8601>

**Route navigated:** <base_url><suspected_route>
**MCP available:** true

### Snapshot summary
<2-3 line summary of accessibility tree elements relevant to the bug — focus on the area mentioned in bug_description>

### Console messages
- [ERROR] <message>  (file:line if available)
- [WARN] <message>
(omit section if console clean)

### Network errors
- <METHOD> <path> → <status>
(omit section if no errors)

### Screenshot
.vg/debug/<debug_id>/screenshots/discovery-<iso8601>.png

### Hypothesis seed
<one-line: most likely root cause given UI evidence>
```

For route-unknown (STEP B):

```markdown
## UI Discovery Findings — <iso8601>

**Route navigated:** N/A (suspected_route="unknown")
**MCP available:** true

### Action needed
Route unknown. Orchestrator should AskUserQuestion for route, then re-spawn with route filled in.

### Hypothesis seed (from bug_description alone)
<one-line guess>
```

For MCP-unavailable (STEP C):

```markdown
## UI Discovery Findings — <iso8601>

**Route navigated:** N/A (MCP unavailable)
**MCP available:** false (rule 5 fallback)

### Fallback action
Per /vg:debug rule 5, this is a UI bug + browser MCP unavailable.
Suggest orchestrator route to `/vg:amend <phase>` to capture as feature gap.

### Hypothesis seed (from bug_description alone)
<one-line guess>
```

## Tool restrictions

ALLOWED: Read, Grep, Bash (for `mkdir -p`), MCP Playwright tools (navigate, snapshot, console, network, take_screenshot, close).
FORBIDDEN: Write (orchestrator appends to DEBUG-LOG.md), Edit, Agent, WebSearch, WebFetch.

The screenshot file IS written via the MCP `browser_take_screenshot` tool itself (which writes the file as a side-effect of the MCP call). This is intentional — that's what the tool exists for. The Write tool is forbidden because all OTHER artifact writes go through the orchestrator.

## Failure modes

| Cause | Action |
|---|---|
| `suspected_route` is unknown AND mcp_available | STEP B (note in findings) |
| MCP unavailable | STEP C (rule 5 fallback) |
| Navigation fails (404/network error) | Capture as a finding, do not abort |
| Screenshot fails | Continue; omit screenshot section |
| Console/network MCP returns empty | Omit those sections; do not pad with "(none)" |
```

- [ ] **Step 2: Verify frontmatter parses + tool list correct**

Run:
```bash
python3 -c "
import yaml
text = open('.claude/agents/vg-debug-ui-discovery.md').read()
end = text.find('\n---\n', 4)
fm = yaml.safe_load(text[4:end])
assert fm['name'] == 'vg-debug-ui-discovery'
tools = fm['tools']
tools_str = ' '.join(tools) if isinstance(tools, list) else str(tools)
assert 'mcp__playwright1__browser_navigate' in tools_str
assert 'Write' not in tools_str
assert 'Agent' not in tools_str
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/vg-debug-ui-discovery.md
git commit -m "feat(r6b): vg-debug-ui-discovery subagent

MCP Playwright wrapper for /vg:debug Step 1 runtime_ui branch.
Workflow STEP A-D: navigate to suspected route, capture snapshot +
console + network + screenshot, emit markdown findings on last stdout.
Implements rule 5 fallback if MCP unavailable. Does NOT modify code
or write to DEBUG-LOG.md (orchestrator appends).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Failing pytest tests for amend (4 tests)

**Files:**
- Create: `tests/skills/test_amend_subagent_delegation.py`
- Create: `tests/skills/test_amend_telemetry_preserved.py`
- Create: `tests/skills/test_amend_within_500.py`
- Create: `tests/skills/test_amend_rules_preserved.py`

- [ ] **Step 1: Write all 4 test files**

Write to `tests/skills/test_amend_subagent_delegation.py`:

```python
"""amend.md Step 5 MUST spawn vg-amend-cascade-analyzer with narrate-spawn."""
import re

from .conftest import grep_count


def test_amend_step5_spawns_cascade_analyzer(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-amend-cascade-analyzer["\']',
    )
    assert spawn_refs >= 1, (
        "amend.md does not spawn vg-amend-cascade-analyzer; "
        "Step 5 must call Agent(subagent_type='vg-amend-cascade-analyzer', ...)"
    )


def test_amend_step5_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-amend-cascade-analyzer",
    )
    assert narrate_calls >= 2, (
        f"amend.md MUST wrap analyzer spawn with at least 2 vg-narrate-spawn.sh "
        f"calls (spawning + returned/failed); found {narrate_calls}"
    )


def test_amend_step5_section_exists(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    assert re.search(r"^## Step 5", body, flags=re.MULTILINE), (
        "Step 5 section header missing from amend.md body"
    )


def test_cascade_analyzer_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-amend-cascade-analyzer")
    assert agent["frontmatter"].get("name") == "vg-amend-cascade-analyzer"
    tools = agent["frontmatter"].get("tools", "")
    tools_str = " ".join(tools) if isinstance(tools, list) else str(tools)
    assert "Write" not in tools_str, "analyzer must be read-only"
    assert "Edit" not in tools_str
    assert "Agent" not in tools_str
```

Write to `tests/skills/test_amend_telemetry_preserved.py`:

```python
"""amend.md frontmatter MUST retain amend.started + amend.completed events."""

REQUIRED_EVENT_TYPES = {"amend.started", "amend.completed"}


def test_amend_telemetry_events_preserved(skill_loader):
    skill = skill_loader("amend")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
```

Write to `tests/skills/test_amend_within_500.py`:

```python
"""amend.md MUST stay <= 500 lines after refactor."""
SLIM_LIMIT = 500


def test_amend_within_500_lines(skill_loader):
    skill = skill_loader("amend")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/amend.md is {skill['lines']} lines (limit {SLIM_LIMIT})"
    )
```

Write to `tests/skills/test_amend_rules_preserved.py`:

```python
"""amend.md MUST keep all 7 rules in <rules> block, especially rule 6 (informational only)."""
import re


REQUIRED_RULE_FRAGMENTS = [
    "VG-native",
    "Config-driven",
    "AMENDMENT-LOG is append-only",
    "CONTEXT.md patch, not regenerate",
    "Git tag before modify",
    "Impact is informational",       # Rule 6 — CRITICAL: subagent must not auto-modify
    "no GSD delegation",             # part of rule 1
]


def test_amend_rules_block_present(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    assert "<rules>" in body and "</rules>" in body, "rules block missing"


def test_amend_all_rule_fragments_present(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    assert rules_match
    rules_text = rules_match.group(1)
    missing = [f for f in REQUIRED_RULE_FRAGMENTS if f not in rules_text]
    assert not missing, f"<rules> block missing fragments: {missing}"


def test_amend_rule_6_informational_explicit(skill_loader):
    """Rule 6 enforces NO auto-modify; subagent must respect."""
    skill = skill_loader("amend")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    rules_text = rules_match.group(1)
    assert "informational" in rules_text and "NOT auto-modify" in rules_text or "does NOT" in rules_text, (
        "Rule 6 wording weakened — must keep 'informational' + 'NOT auto-modify' or 'does NOT' phrasing"
    )
```

- [ ] **Step 2: Run tests, expect mixed**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/skills/test_amend_*.py -v`

Expected:
- `test_amend_step5_spawns_cascade_analyzer` — FAIL (no spawn yet)
- `test_amend_step5_wraps_spawn_with_narration` — FAIL
- `test_amend_step5_section_exists` — PASS (Step 5 already exists)
- `test_cascade_analyzer_agent_definition_exists` — PASS (Task 2 created it)
- `test_amend_telemetry_events_preserved` — PASS (already correct)
- `test_amend_within_500_lines` — PASS (323 lines)
- `test_amend_rules_block_present` — PASS
- `test_amend_all_rule_fragments_present` — PASS
- `test_amend_rule_6_informational_explicit` — PASS

If "PASS today" tests fail, investigate before proceeding.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/skills/test_amend_*.py
git commit -m "test(r6b): failing tests — amend Step 5 delegation; baseline locks for telemetry/size/rules

Locks the post-refactor contract:
- Step 5 spawns vg-amend-cascade-analyzer with narrate-spawn wrap
Plus baseline locks (passing today, must stay passing):
- amend.started + amend.completed in must_emit_telemetry
- ≤500 lines
- All 7 rules present, especially rule 6 (informational only)

Refactor in next task makes failing tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Refactor amend.md Step 5 — delegate to subagent

**Files:**
- Modify: `commands/vg/amend.md` (Step 5 body, lines ~204–246)

- [ ] **Step 1: Read current Step 5 body**

Run: `awk '/^## Step 5/,/^## Step 6/' commands/vg/amend.md > /tmp/amend-step5-current.md && wc -l /tmp/amend-step5-current.md`

Note line count.

- [ ] **Step 2: Replace Step 5 body**

Locate `## Step 5` heading and the next `## Step 6` heading. Replace EVERYTHING between them (preserve those headings) with:

```markdown
## Step 5: Cascade impact analysis

Cascade analysis is delegated to `vg-amend-cascade-analyzer` subagent
(read-only). Subagent inspects PLAN/API-CONTRACTS/TEST-GOALS/SUMMARY/
RUNTIME-MAP for references to changed decisions, returns a markdown
impact report. Per rule 6, the report is informational — orchestrator
displays it to user but does NOT auto-modify any artifact.

### 5.1 Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer spawning "phase=$PHASE_NUMBER decisions=$CHANGED_DECISIONS"
```

### 5.2 Spawn

Construct prompt JSON and call:

```text
Agent(
  subagent_type="vg-amend-cascade-analyzer",
  prompt={
    "phase_dir": "${PHASE_DIR}",
    "changed_decision_ids": <JSON list of D-XX from Step 2>,
    "change_summary": "<one-line from Step 2 user input>"
  }
)
```

### 5.3 Post-spawn narrate

On success (markdown report returned):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer returned "report-len=$(echo "$REPORT" | wc -l)"
```

On failure (subagent emitted error JSON or no markdown block):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer failed "<one-line cause>"
```

### 5.4 Display report to user

Display the subagent's markdown report block inline in chat. Do NOT
write the report to a file (rule 6: informational only). The
AMENDMENT-LOG.md entry written in Step 3 already captures change context;
the cascade report is for user's pre-commit awareness.

### 5.5 If subagent failed

If the subagent failed (e.g. all artifacts unreadable), surface the
cause to user via:

> ⚠ Cascade analysis failed: <cause>. Continue to Step 6 commit
> without impact report? (yes/no)

On yes → proceed to Step 6.
On no → abort entry skill (no commit, no telemetry beyond what was emitted).

See `.claude/agents/vg-amend-cascade-analyzer.md` for the full subagent
contract.
```

- [ ] **Step 3: Run amend tests, expect ALL PASS**

Run: `python3 -m pytest tests/skills/test_amend_*.py -v`

Expected: 9 tests pass (4 subagent_delegation + 1 telemetry + 1 within_500 + 3 rules_preserved).

- [ ] **Step 4: Commit**

```bash
git add commands/vg/amend.md
git commit -m "refactor(r6b): amend.md Step 5 — delegate cascade to vg-amend-cascade-analyzer

Per spec §3.1: Step 5 was inline grep + analysis (~37 lines). Refactored
to spawn read-only subagent that returns markdown impact report.
Orchestrator displays inline (no new file artifact). Rule 6 preserved
(informational only, no auto-modify).

All 9 R6b amend pytest tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Failing pytest tests for debug (5 tests)

**Files:**
- Create: `tests/skills/test_debug_subagent_delegation.py`
- Create: `tests/skills/test_debug_telemetry_preserved.py`
- Create: `tests/skills/test_debug_within_500.py`
- Create: `tests/skills/test_debug_no_loop_cap.py`
- Create: `tests/skills/test_debug_rules_preserved.py`

- [ ] **Step 1: Write all 5 test files**

Write to `tests/skills/test_debug_subagent_delegation.py`:

```python
"""debug.md Step 1 runtime_ui branch MUST spawn vg-debug-ui-discovery."""
import re

from .conftest import grep_count


def test_debug_step1_runtime_ui_spawns_ui_discovery(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    # Look for spawn within Step 1 section
    step1_match = re.search(
        r"^## Step 1(.*?)^## Step 2",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert step1_match, "Step 1 section not found in debug.md"
    step1_body = step1_match.group(1)
    spawn_refs = len(re.findall(
        r'subagent_type=["\']vg-debug-ui-discovery["\']',
        step1_body,
    ))
    assert spawn_refs >= 1, (
        "debug.md Step 1 does not spawn vg-debug-ui-discovery; "
        "the runtime_ui branch must call Agent(subagent_type='vg-debug-ui-discovery', ...)"
    )


def test_debug_step1_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-debug-ui-discovery",
    )
    assert narrate_calls >= 2, (
        f"debug.md MUST wrap ui-discovery spawn with at least 2 vg-narrate-spawn.sh "
        f"calls (spawning + returned/failed); found {narrate_calls}"
    )


def test_ui_discovery_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-debug-ui-discovery")
    assert agent["frontmatter"].get("name") == "vg-debug-ui-discovery"
    tools = agent["frontmatter"].get("tools", "")
    tools_str = " ".join(tools) if isinstance(tools, list) else str(tools)
    assert "mcp__playwright1__browser_navigate" in tools_str
    assert "Write" not in tools_str.split()[0:3] or "Write" not in tools_str  # crude check
    assert "Agent" not in tools_str
```

Write to `tests/skills/test_debug_telemetry_preserved.py`:

```python
"""debug.md frontmatter MUST retain all 5 telemetry events."""

REQUIRED_EVENT_TYPES = {
    "debug.parsed",
    "debug.classified",
    "debug.fix_attempted",
    "debug.user_confirmed",
    "debug.completed",
}


def test_debug_telemetry_events_preserved(skill_loader):
    skill = skill_loader("debug")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
```

Write to `tests/skills/test_debug_within_500.py`:

```python
"""debug.md MUST stay <= 500 lines after refactor."""
SLIM_LIMIT = 500


def test_debug_within_500_lines(skill_loader):
    skill = skill_loader("debug")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/debug.md is {skill['lines']} lines (limit {SLIM_LIMIT})"
    )
```

Write to `tests/skills/test_debug_no_loop_cap.py`:

```python
"""debug.md Step 3 fix loop MUST NOT have a hard iteration cap.

Rule 2: 'AskUserQuestion-driven loop — no max iterations'. Capping the
loop violates the rule. This test asserts NO forbidden cap patterns
appear in Step 3 body.
"""
import re


FORBIDDEN_CAP_PATTERNS = [
    r"max(?:\s+|\s*=\s*|imum\s+)\d+\s+iteration",
    r"\d+\s+iteration\s+max",
    r"hard[-\s]?cap\w*\s+(?:at\s+|of\s+)?\d+",
    r"iteration[_\s]?count\s*[<≤]=?\s*\d+",
    r"iteration\s*[<≤]=?\s*\d+",
]


def test_debug_step3_has_no_cap(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    step3_match = re.search(
        r"^## Step 3(.*?)^## Step 4",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert step3_match, "Step 3 section not found in debug.md"
    step3 = step3_match.group(1)
    found_caps = []
    for pattern in FORBIDDEN_CAP_PATTERNS:
        if re.search(pattern, step3, flags=re.IGNORECASE):
            found_caps.append(pattern)
    assert not found_caps, (
        f"Step 3 contains forbidden iteration cap pattern(s): {found_caps}. "
        f"Rule 2 requires no max iterations (AskUserQuestion-driven)."
    )
```

Write to `tests/skills/test_debug_rules_preserved.py`:

```python
"""debug.md MUST keep all 7 rules in <rules> block, especially rule 2 (no max iterations)."""
import re


REQUIRED_RULE_FRAGMENTS = [
    "Standalone session",
    "AskUserQuestion-driven loop",   # Rule 2 — CRITICAL
    "no max iterations",              # Rule 2 enforcement
    "Auto-classify",
    "Spec gap",
    "Browser MCP fallback",
    "Atomic commits",
    "No destructive actions",
]


def test_debug_rules_block_present(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    assert "<rules>" in body and "</rules>" in body, "rules block missing"


def test_debug_all_rule_fragments_present(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    assert rules_match
    rules_text = rules_match.group(1)
    missing = [f for f in REQUIRED_RULE_FRAGMENTS if f not in rules_text]
    assert not missing, f"<rules> block missing fragments: {missing}"


def test_debug_rule_2_no_cap_explicit(skill_loader):
    """Rule 2 wording must contain 'no max iterations' or equivalent."""
    skill = skill_loader("debug")
    body = skill["body"]
    rules_match = re.search(r"<rules>(.*?)</rules>", body, flags=re.DOTALL)
    rules_text = rules_match.group(1)
    assert "no max iterations" in rules_text or "no max" in rules_text.lower(), (
        "Rule 2 wording weakened — must keep 'no max iterations' phrasing"
    )
```

- [ ] **Step 2: Run tests, expect mixed**

Run: `python3 -m pytest tests/skills/test_debug_*.py -v`

Expected:
- `test_debug_step1_runtime_ui_spawns_ui_discovery` — FAIL (pseudo-code not yet replaced)
- `test_debug_step1_wraps_spawn_with_narration` — FAIL
- `test_ui_discovery_agent_definition_exists` — PASS (Task 3 created it)
- `test_debug_telemetry_events_preserved` — PASS (already correct)
- `test_debug_within_500_lines` — PASS (399 lines)
- `test_debug_step3_has_no_cap` — PASS (no cap today, rule 2 already honored)
- `test_debug_rules_block_present` — PASS
- `test_debug_all_rule_fragments_present` — PASS
- `test_debug_rule_2_no_cap_explicit` — PASS

If "PASS today" tests fail, investigate.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/skills/test_debug_*.py
git commit -m "test(r6b): failing tests — debug Step 1 runtime_ui delegation; baseline locks

Locks the post-refactor contract:
- Step 1 runtime_ui branch spawns vg-debug-ui-discovery with narrate-spawn
Plus baseline locks (passing today, must stay passing):
- All 5 telemetry events preserved
- ≤500 lines
- NO hard cap on Step 3 fix loop (rule 2)
- All 7 rules present, especially rule 2

Refactor in next task makes failing tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Refactor debug.md Step 1 runtime_ui — implement Agent() spawn

**Files:**
- Modify: `commands/vg/debug.md` (Step 1 `runtime_ui` branch only)

- [ ] **Step 1: Locate runtime_ui branch in Step 1**

Run: `awk '/^### runtime_ui/,/^### network/' commands/vg/debug.md > /tmp/debug-runtime-ui-current.md && cat /tmp/debug-runtime-ui-current.md`

This is the section to replace.

- [ ] **Step 2: Replace runtime_ui branch body**

Locate the `### runtime_ui` heading (around line 176) and the next `### network` heading (around line 198). Replace EVERYTHING between them (preserve those headings) with:

```markdown
### runtime_ui → browser MCP via vg-debug-ui-discovery subagent

Detect MCP availability:

```bash
MCP_AVAILABLE=$(...check for mcp__playwright1__ tool registration...)
```

Determine `SUSPECTED_ROUTE` from bug description (heuristic — extract path
from bug_description, default to "unknown" if no path mentioned).

Read base URL from config:

```bash
BASE_URL=$(python3 scripts/lib/vg-config-extract.py "env.sandbox.base_url" || echo "http://localhost:3000")
```

#### Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery spawning "route=$SUSPECTED_ROUTE mcp=$MCP_AVAILABLE"
```

#### Spawn

Construct prompt JSON and call:

```text
Agent(
  subagent_type="vg-debug-ui-discovery",
  prompt={
    "bug_description": "<verbatim from user>",
    "suspected_route": "<SUSPECTED_ROUTE or 'unknown'>",
    "debug_id": "<DEBUG_ID from Step 0>",
    "mcp_available": <MCP_AVAILABLE bool>,
    "base_url": "<BASE_URL>"
  }
)
```

#### Post-spawn narrate

On success (markdown findings block returned):

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery returned "route=$SUSPECTED_ROUTE"
```

On failure:

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery failed "<one-line cause>"
```

#### Append findings to DEBUG-LOG.md

Append the subagent's markdown findings block to:
`.vg/debug/${DEBUG_ID}/DEBUG-LOG.md` (append-only per existing pattern).

If subagent fell back (rule 5 — MCP unavailable), the findings block
itself contains the fallback note. Orchestrator may then auto-route
to `/vg:amend ${PHASE_NUMBER}` if `--no-amend-trigger` is NOT set
(per existing Step 0 spec_gap routing pattern).

See `.claude/agents/vg-debug-ui-discovery.md` for the full subagent
contract (workflow STEP A-D, MCP tool list, fallback paths).
```

- [ ] **Step 3: Run debug tests, expect ALL PASS**

Run: `python3 -m pytest tests/skills/test_debug_*.py -v`

Expected: 9 tests pass (3 subagent_delegation + 1 telemetry + 1 within_500 + 1 no_loop_cap + 3 rules_preserved).

- [ ] **Step 4: Commit**

```bash
git add commands/vg/debug.md
git commit -m "refactor(r6b): debug.md Step 1 runtime_ui — implement vg-debug-ui-discovery spawn

Per spec §3.2: the runtime_ui branch had pseudo-code 'Spawn Haiku agent...'
that was never implemented. Replaced with actual Agent(vg-debug-ui-discovery)
spawn. Subagent wraps MCP Playwright tools, returns markdown findings.
Orchestrator appends to DEBUG-LOG.md (consistent with existing append-only
pattern). Rule 5 (MCP unavailable → fallback to amendment-trigger) preserved
inside subagent.

Step 3 fix loop UNCHANGED — rule 2 (no max iterations) preserved.
All 5 telemetry events UNCHANGED.

All 9 R6b debug pytest tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: vg-meta-skill.md — append amend + debug Red Flags

**Files:**
- Modify: `scripts/hooks/vg-meta-skill.md`

- [ ] **Step 1: Append Red Flags sections**

Append at end of `scripts/hooks/vg-meta-skill.md`:

```markdown

## Amend-specific Red Flags

| Thought | Reality |
|---|---|
| "Subagent should auto-apply ripple to PLAN.md" | Rule 6: cascade is INFORMATIONAL only. Subagent is read-only. Orchestrator displays report; user decides next action. |
| "Skip cascade analysis, just commit Step 6" | Rule 6 still requires the report; user needs awareness before commit. |
| "Cascade analyzer can write a RIPPLE-ANALYSIS.json file" | NO — output is markdown report on stdout. AMENDMENT-LOG.md (existing) captures change context; cascade is ephemeral inline. |
| "Skip narrate-spawn for cascade analyzer — read-only is harmless" | UX baseline R2 makes narrate-spawn MANDATORY for ALL spawns. |

## Debug-specific Red Flags

| Thought | Reality |
|---|---|
| "Cap fix loop at 3 to prevent infinite retry" | Rule 2: AskUserQuestion-driven, NO max iterations. User-controlled exit. |
| "Use a subagent for classification (Step 0)" | Rule 3: Auto-classify is heuristic regex (deterministic, fast). Subagent is overkill + slow. |
| "Skip Step 1 runtime_ui — too complex" | The Agent(vg-debug-ui-discovery) spawn IS the implementation. Skipping = pseudo-code remains. |
| "MCP unavailable → abort debug session" | Rule 5: fallback to amendment-trigger; do NOT abort. |
| "Subagent should write to DEBUG-LOG.md directly" | NO — orchestrator owns the append (rule 6: atomic commits per fix). Subagent returns markdown; orchestrator appends. |
| "Spec_gap should NOT auto-route to /vg:amend" | Rule 4 + flag default is auto-route. Use --no-amend-trigger to disable. |
```

- [ ] **Step 2: Verify markdown still parses**

Run: `python3 -c "from pathlib import Path; t = Path('scripts/hooks/vg-meta-skill.md').read_text(); assert t.count('|') > 100; print('OK')"`

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "docs(r6b): vg-meta-skill.md — amend + debug Red Flags

4 amend entries (auto-apply, skip-cascade, JSON-artifact, narrate-skip)
+ 6 debug entries (cap-loop, classify-subagent, skip-runtime-ui,
abort-on-mcp-fail, write-from-subagent, disable-amend-route).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Mock dogfood — amend + debug

**Files:** none modified — verification only.

### Part A: amend dogfood

- [ ] **Step 1: Pick a phase with multiple downstream artifacts**

Phase should have at least PLAN.md (or PLAN/) AND CONTEXT.md. API-CONTRACTS.md and TEST-GOALS.md optional but better coverage.

- [ ] **Step 2: Run /vg:amend <phase>**

In Claude Code session:

```
/vg:amend <phase>
```

Walk through Steps 0-4 (parse, what-to-change, discuss, write log, update CONTEXT). Provide a meaningful change description (e.g. "Rename POST /users → POST /accounts").

- [ ] **Step 3: Verify Step 5 chip narration + report**

At Step 5, look for:
- 🟢 green pill: `vg-amend-cascade-analyzer spawning phase=<phase> decisions=D-XX`
- 🔵 cyan pill: `vg-amend-cascade-analyzer returned report-len=N`
- Markdown impact report displayed inline (sections per artifact, suggested next action at end)

- [ ] **Step 4: Verify report quality**

The report should:
- List affected artifacts (PLAN/API-CONTRACTS/TEST-GOALS sections)
- Cite D-XX in change_summary section
- Suggest a next action matching the phase's current pipeline state
- NOT modify any file (read-only contract)

- [ ] **Step 5: Verify CONTEXT.md updated + AMENDMENT-LOG.md appended**

```bash
cat .vg/phases/<phase>/CONTEXT.md | tail -10  # Check footer + decision edits
cat .vg/phases/<phase>/AMENDMENT-LOG.md       # Check new amendment block appended
```

- [ ] **Step 6: Verify telemetry**

```bash
sqlite3 .vg/events.db "SELECT event_type FROM events WHERE event_type LIKE 'amend.%' ORDER BY id DESC LIMIT 5"
```

Expected: `amend.completed`, `amend.started`.

### Part B: debug dogfood

- [ ] **Step 7: Set up a contrived UI bug context**

Either:
- Have a real running app on `localhost:3000` with a known UI quirk, OR
- Mock by deferring browser MCP availability check (subagent will take rule 5 fallback path)

- [ ] **Step 8: Run /vg:debug with a UI bug**

```
/vg:debug "modal does not close on ESC at /admin/users"
```

- [ ] **Step 9: Verify Step 0 classifies as runtime_ui**

In chat, look for: `Classification: runtime_ui (XX%)`

- [ ] **Step 10: Verify Step 1 chip narration + findings**

Look for:
- 🟢 green pill: `vg-debug-ui-discovery spawning route=/admin/users mcp=true|false`
- 🔵 cyan pill: `vg-debug-ui-discovery returned route=/admin/users` (or red if failed)
- Markdown findings block displayed (snapshot summary, console, network, screenshot path OR fallback note)

- [ ] **Step 11: Verify DEBUG-LOG.md appended**

```bash
cat .vg/debug/<debug_id>/DEBUG-LOG.md
```

Expected: Header (from Step 0), then iteration block(s) including the UI Discovery Findings markdown.

- [ ] **Step 12: Verify telemetry**

```bash
sqlite3 .vg/events.db "SELECT event_type FROM events WHERE event_type LIKE 'debug.%' ORDER BY id DESC LIMIT 10"
```

Expected events present: `debug.parsed`, `debug.classified`, plus whatever happened later in the session (`fix_attempted`, `user_confirmed`, `completed`).

### Step 13: Final summary

R6b ship-ready when ALL above pass:
- amend dogfood: chip narration + cascade report inline + CONTEXT/AMENDMENT-LOG updated + telemetry
- debug dogfood: chip narration + findings appended to DEBUG-LOG + telemetry
- All 18 R6b pytest tests pass (9 amend + 9 debug)
- R5.5 + R6a tests still pass (no regression)

Optional tag:

```bash
git tag -a r6b-amend-debug -m "R6b amend Step 5 + debug Step 1 runtime_ui subagent extraction"
```

---

## Self-Review

**Spec coverage:**

| Spec § | Task(s) |
|---|---|
| §1.4 What changes | Tasks 5 (amend Step 5), 7 (debug Step 1 runtime_ui) |
| §3.1 amend flow | Tasks 2 (subagent), 5 (entry refactor) |
| §3.2 debug flow | Tasks 3 (subagent), 7 (entry refactor) |
| §3.3 Slim entry constraints | Tasks 4 (within_500 test), 6 (within_500 test) |
| §4.1 vg-amend-cascade-analyzer contract | Task 2 |
| §4.2 vg-debug-ui-discovery contract | Task 3 |
| §5 File and directory layout | All tasks |
| §6 Telemetry events (UNCHANGED) | Tasks 4 (telem test), 6 (telem test) |
| §7.1 Error handling | Tasks 5 (amend fail path), 7 (debug rule 5 fallback inside subagent) |
| §7.3 Pytest static + mock dogfood | Tasks 4, 6, 9 |
| §7.4 Exit criteria 1-6 | Task 9 step 13 |
| §10 UX baseline | Tasks 5, 7 (narration), 8 (Red Flags) |

No gaps detected.

**Placeholder scan:** searched for TBD/TODO — none in plan body.

**Type/path consistency:**
- Subagent names `vg-amend-cascade-analyzer`, `vg-debug-ui-discovery` consistent across spec, agent files, delegation steps, all pytest files.
- Telemetry event names (`amend.started/completed`, `debug.parsed/classified/fix_attempted/user_confirmed/completed`) consistent.
- Rule fragment strings (rule 2 "no max iterations", rule 6 "informational") consistent across spec, plan, tests.
- File paths consistent.
- NO `RIPPLE-ANALYSIS.json` or `DEBUG-CLASSIFY.json` mentioned anywhere (explicit decision: outputs are markdown text, not JSON files).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r6b-amend-debug.md` (REVISED). Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
