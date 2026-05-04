---
name: flow-runner
description: Execute flow tests via MCP Playwright with checkpoint-resume, 4-rule deviation classification, 3-strike escalation, evidence-required assertions
user-invocable: false
---

# Flow Runner — Checkpoint-Resume Test Execution

Execute Playwright flow tests with checkpoint persistence, resume from failure, deviation-classified fix loops, and evidence-backed assertions.

**Called by:** `/rtb:sandbox-test` Step 8.5b
**Input:** Test file path + checkpoint.json (if resuming)
**Output:** `.planning/phases/{phase}/{phase}-FLOW-RESULT.md`
**Checkpoint:** `.planning/phases/{phase}/checkpoints/{flow}.checkpoint.json`

## Context Budget

Read ONLY the test file and checkpoint.json. Do NOT read FLOW-SPEC, FLOW-REGISTRY, source code, or any other planning artifacts.

## Execution Flow

### Step 1: Check for Existing Checkpoint

```
checkpoint.json exists?
├── NO  → Fresh run (Step 2a)
└── YES → Resume mode (Step 2b)
```

### Step 2a: Fresh Run

Execute the full flow test via MCP Playwright (visible browser). For each step:

1. Execute action (click, fill, navigate)
2. Wait for condition (response, selector, text — NEVER timeout)
3. Run 3-layer assertion (UI + API + Data) + regression verify
4. Capture evidence (screenshot + console_messages + api_calls)
5. Save checkpoint with evidence
6. Handle CP type:
   - `auto-verify` → continue automatically
   - `human-verify` → pause, show screenshot, wait for user confirm
   - `human-action` → STOP, print instruction for user

### Step 2b: Resume Mode

1. Read `checkpoint.json` → find `resume_from` step
2. Login as `resume_context.logged_in_as` role
3. Navigate to `resume_context.current_page`
4. Verify `prior_data` matches current state:
   - Match → continue from failed step
   - Mismatch → fall back to previous checkpoint
   - No valid fallback → re-run from beginning
5. Continue execution from failed step onwards

### Step 3: On Step Failure — Fix Loop

Classify the failure using 4 rules, then apply fix:

**Rule 1: AUTO-FIX (test code bug)**
- Symptoms: selector not found, text mismatch, element position changed
- Action: Read MCP snapshot → update selector or expected text in test file → re-run step
- Example: Button renamed "Submit" → "Submit for Review"

**Rule 2: AUTO-ENHANCE (missing test logic)**
- Symptoms: timeout waiting for element, assertion incomplete, missing wait
- Action: Add `waitForResponse`, add missing assertion, add retry logic → re-run step
- Example: Missing wait for API response before checking badge text

**Rule 3: AUTO-RETRY (infra/transient)**
- Symptoms: page not loading, login timeout, network error, 502/503
- Action: Wait 10 seconds → retry step (max 2 retries per step)
- Example: VPS PM2 restart mid-test, nginx timeout

**Rule 4: ESCALATE (app bug)**
- Symptoms: API returns 4xx/5xx consistently, data unchanged after mutation, wrong state transition
- Action: STOP fix loop → report to user with full evidence bundle
- Example: POST /campaigns/:id/submit returns 403 due to incorrect RBAC rule

### Step 4: 3-Strike Escalation

```
Same step fails attempt 1 → Classify (Rules 1-4) → apply fix
Same step fails attempt 2 → Re-classify (may upgrade, e.g. Rule 1 → Rule 4) → apply
Same step fails attempt 3 → ESCALATE regardless of classification
  → Present: 3 screenshots, 3 error messages, 3 console logs
  → User decides: fix app code / skip step / abort flow

Different step fails → Reset attempt counter, continue normally
```

### Step 5: Resume Impossibility Rules

| Situation | Action |
|-----------|--------|
| Steps 1-2 fail (setup/login) | Re-run from beginning |
| prior_data verify fails (data corrupt) | Re-run from beginning, log warning |
| Role switch step fails | Re-run from step before the role switch |
| 3 resume attempts on same step | Escalate to human |

### Step 6: On All Steps Pass

1. Write `{phase}-FLOW-RESULT.md`:

```markdown
---
phase: {phase}
type: flow-result
tested: {ISO timestamp}
status: PASSED | GAPS_FOUND | FAILED
flows_tested: {N}
total_steps: {N}
passed: {N}
failed: {N}
skipped: {N}
fix_loop_iterations: {N}
---

# Flow Test Result: Phase {phase}

## Flow: {flow-name}
- Status: PASSED
- Steps: {passed}/{total}
- Duration: {seconds}s
- Fix iterations: {N}

### Step Results
| CP | Action | Status | Evidence |
|----|--------|--------|----------|
| CP-1 | {action} | PASSED | [screenshot](path) |

### Screenshots
| CP | File |
|----|------|
```

2. Clean up checkpoint.json (delete file — flow completed)
3. Report summary to orchestrator

## Evidence Requirement

**Every checkpoint — pass or fail — MUST include evidence. No evidence = no pass.**

| Status | Required | Missing evidence action |
|--------|----------|----------------------|
| passed | screenshot + console_errors (even empty []) + api_calls | Treat as unverified → re-run step |
| failed | screenshot + console_errors + error.message | Treat as unverified → re-run step |
| skipped | reason string | Accepted (unreachable steps only) |

## Auto-Mode

When `--auto` flag is set:
- `auto-verify` checkpoints → auto-pass (default behavior, no change)
- `human-verify` checkpoints → auto-approve (skip human confirmation)
- `human-action` checkpoints → still STOP (cannot be automated)

## Anti-Patterns

- NEVER skip evidence capture — "step passed" without screenshot is unverified
- NEVER fix app code from flow-runner — only fix test code (Rules 1-2). App bugs escalate (Rule 4).
- NEVER retry infinitely — max 2 retries for Rule 3 (transient), max 3 attempts total per step
- NEVER resume without verifying prior_data — stale data causes cascade false-failures
- NEVER delete checkpoint.json on failure — it's the resume mechanism
- NEVER continue after human-action checkpoint — wait for user instruction
