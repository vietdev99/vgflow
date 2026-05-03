---
name: flow-spec
description: Generate FLOW-SPEC.md from FLOW-REGISTRY.md — test steps, 3 checkpoint types, condition-based waits, mutation assertions with regression verify
user-invocable: false
---

# Flow Spec — Test Step Generation

Convert FLOW-REGISTRY.md into an ordered test specification with checkpoint types, condition-based waits, and 3-layer mutation assertions.

**Called by:** `/rtb:test-specs` Step 9b
**Input:** ONLY `{phase}-FLOW-REGISTRY.md` — does NOT read source code
**Output:** `.planning/phases/{phase}/{phase}-FLOW-SPEC.md`

## Context Budget

This skill reads ~200 lines of structured data (FLOW-REGISTRY). It does NOT read any source code, React components, or planning artifacts beyond FLOW-REGISTRY.

## Process

### Step 1: Read FLOW-REGISTRY.md

Parse the registry. For each flow, extract: states list, transitions table, data assertions, cross-page navigation.

### Step 2: Generate Step Sequence (per flow)

Convert transitions into ordered test steps:

1. **Order transitions** by lifecycle sequence (not table order)
2. **Assign roles** — if transition requires different role than previous step, insert role switch
3. **Set wait conditions** — NEVER `waitForTimeout`. Use:
   | Trigger Type | Wait Pattern |
   |-------------|-------------|
   | POST/PUT/DELETE mutation | `waitForResponse(url, status < 400)` |
   | Page navigation | `waitForSelector('[data-page="..."]')` |
   | Badge/status change | `expect(badge).toHaveText(expected, { timeout: 5000 })` |
   | Data load (table/list) | `waitForResponse(GET url) + waitForSelector('table tbody tr')` |
   | Mutation + UI update | `Promise.all([waitForResponse, click])` |

4. **Assign checkpoint type** per step:
   | CP Type | Default For | Auto-mode |
   |---------|------------|-----------|
   | `auto-verify` | Standard UI changes, data assertions, navigation | Auto-pass if assertions pass |
   | `human-verify` | Role switches, payment flows, visual complexity | Auto-approve (skip) |
   | `human-action` | Email verify, Stripe card, cron trigger needing manual mock | Still STOPS |

5. **Generate 3-layer mutation assertions** for steps with API calls:
   - **UI Layer:** Toast/badge text contains expected value
   - **API Layer:** Console has no 4xx/5xx after action
   - **Data Layer:** GET endpoint confirms data changed
   - **Regression Verify (NEW):** Previous state indicators are GONE (not just new state present)

6. **Mark unreachable steps** — transitions triggered by cron/worker (no UI action):
   - Workaround A: Direct API call (bypass UI)
   - Workaround B: Skip step, verify end state via API only
   - Workaround C: Admin endpoint trigger if available

### Step 3: Estimate Duration

Per flow: `total_steps x 5 seconds` average (with condition-based waits, not fixed delays).

### Step 4: Validate Completeness

Every transition in FLOW-REGISTRY must have at least 1 test step. If any transition is uncovered → add it or mark as gap with reason.

### Step 5: Write FLOW-SPEC.md

```markdown
---
phase: {phase}
type: flow-spec
flows_count: {N}
total_steps: {total across all flows}
total_checkpoints: {same as total_steps}
checkpoint_types: { auto: N, human_verify: N, human_action: N }
generated_from: {phase}-FLOW-REGISTRY.md
---

# Flow Spec: Phase {phase} — {Name}

## Flow: {flow-name}

- **Priority:** P0/P1/P2
- **Steps:** N
- **Roles:** role1, role2
- **Estimated duration:** ~Ns
- **Gates:** pre-flight (FLOW-REGISTRY exists), revision (CrossAI), escalation (3-strike)

### Step Sequence

| Step | Role | Page | Action | Wait Condition | Assert | CP | CP Type |
|------|------|------|--------|---------------|--------|-----|---------|

### Mutation Assertions (3-layer + regression verify)

| Step | UI Layer | API Layer | Data Layer | Regression Verify |
|------|----------|-----------|------------|-------------------|

### Role Switch Points

| After Step | From | To | Method | CP Type |
|-----------|------|-----|--------|---------|

### Unreachable Steps

| Step | Trigger | Workaround | Fallback |
|------|---------|-----------|----------|
```

## Anti-Patterns

- DO NOT read source code — FLOW-REGISTRY is your only input
- DO NOT use `waitForTimeout` in any wait condition — always condition-based
- DO NOT assign `human-action` to steps that can be automated — reserve for truly manual actions
- DO NOT skip regression verify — checking old state is GONE prevents false-positive badge rendering
- DO NOT create steps for simple CRUD toggles — only multi-step state machine transitions
