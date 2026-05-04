---
name: flow-scan
description: Scan codebase for state machine definitions, extract flows into FLOW-REGISTRY.md — spawns 3 parallel subagents (backend/frontend/business-flow)
user-invocable: false
---

# Flow Scan — State Machine Extraction

Scan codebase for state machine definitions and produce a structured FLOW-REGISTRY.md that downstream skills (flow-spec, flow-codegen, flow-runner) consume.

**Called by:** `/rtb:test-specs` Step 9a
**Input:** Phase number
**Output:** `.planning/phases/{phase}/{phase}-FLOW-REGISTRY.md`

## Context Budget

This skill spawns 3 subagents. Each agent reads ONE source only — no cross-reading.

| Subagent | Reads | Does NOT Read |
|----------|-------|---------------|
| backend-scanner | `apps/api/src/modules/` | React code, BUSINESS-FLOW-SPECS |
| frontend-scanner | `apps/web/src/` | API code, BUSINESS-FLOW-SPECS |
| business-flow-reader | `.planning/BUSINESS-FLOW-SPECS.md` | Source code |

## Process

### Step 1: Determine Phase Modules

Read `{phase}/CONTEXT.md` to identify which API modules belong to this phase.
Example: Phase 07.3 → modules: `billing`, `funding`, `invoices`, `payouts`.

### Step 2: Spawn 3 Subagents in Parallel

**Subagent A — backend-scanner:**
```
Grep apps/api/src/modules/{modules}/ for these patterns:
- *STATES*, *STATUS*, *LIFECYCLE*, *TRANSITIONS*
- Enum-like const objects: const.*=.*{ (with state string values)
- Router files: POST/PUT methods that change a status field

For each state machine found, extract:
- Source file path
- State names (ordered by lifecycle)
- Transition definitions: from → to, trigger name, API endpoint, HTTP method
- Role required for each transition (from middleware/guards)

Output format:
## StateMachine: {name}
- Source: {file path}
- States: state1 → state2 → state3 → ...
### Transitions
| From | To | Trigger | Endpoint | Method | Role |
```

**Subagent B — frontend-scanner:**
```
Grep apps/web/src/ for these patterns:
- StatusBadge, badge, status.*variant, status.*color
- Conditional renders: status === '{value}' or status === "{value}"
- Route definitions in router files
- Buttons/actions conditional on status (disabled, hidden, visible per state)

For each state found, extract:
- Page/component showing this state
- Badge text and variant per state
- UI indicators (buttons enabled/disabled, sections visible/hidden)
- Navigation: which page transitions to which

Output format:
## UI: {state-machine-name}
### Per State
| State | Page | Badge Text | Visible Actions | Hidden Elements |
```

**Subagent C — business-flow-reader:**
```
Read .planning/BUSINESS-FLOW-SPECS.md
Filter flows that match this phase's modules.

For each matching flow, extract:
- Flow name and priority
- Step sequence with actions and expected outcomes
- Business rules not obvious from code (approval thresholds, time limits, auto-triggers)
- Roles involved at each step

Output format:
## BusinessFlow: {name}
- Priority: P0/P1/P2
- Steps: N
### Steps
| # | Role | Action | Expected | Business Rule |
```

### Step 3: Merge Results

**Merge rules:**
1. Backend-scanner = source of truth for states and transitions
2. Frontend-scanner supplements: add Page and UI Indicator columns to each state
3. Business-flow-reader supplements: add business context + detect gaps
4. **Gap detection:** If a flow exists in BUSINESS-FLOW-SPECS but no matching state machine in code → mark as `GAP: not yet implemented`
5. **Conflict resolution:** If frontend shows a state not in backend → mark as `UNVERIFIED: UI-only state`

### Step 4: Write FLOW-REGISTRY.md

Write to `.planning/phases/{phase}/{phase}-FLOW-REGISTRY.md` with this format:

```markdown
---
phase: {phase}
type: flow-registry
flows_found: {N}
total_transitions: {M}
gaps: {K}
scanned_modules: [{module list}]
---

## Flow: {flow-name}

- **Source:** {backend file path}
- **States:** state1 → state2 → state3 → ...
- **Roles involved:** role1 (trigger X), role2 (trigger Y)

### Transitions

| # | From | To | Trigger | API Endpoint | Method | Role | Page |
|---|------|----|---------|-------------|--------|------|------|

### Data Assertions per State

| State | UI Indicator | Badge Text | Key Data |
|-------|-------------|------------|----------|

### Cross-Page Navigation

| Step | Start Page | Action | End Page |
|------|-----------|--------|----------|
```

### Step 5: Report

Print summary: `{N} flows found, {M} transitions, {K} gaps (flows in business-spec not in code)`.

If 0 flows found → print "No state machines detected — skipping flow-spec generation."

## Anti-Patterns

- DO NOT read entire source files — grep patterns then read surrounding 20 lines for context
- DO NOT let 1 subagent read both backend + frontend code
- DO NOT hallucinate states not found in code — if uncertain, mark as `UNVERIFIED`
- DO NOT include simple CRUD status fields (e.g., `active/inactive` toggles) — only multi-step lifecycles with 3+ states
- If grep returns > 20 matches for a pattern → narrow by phase module paths from CONTEXT.md
