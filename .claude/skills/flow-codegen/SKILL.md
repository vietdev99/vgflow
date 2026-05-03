---
name: flow-codegen
description: Generate Playwright flow test files from FLOW-SPEC.md — condition-based waits, checkpoint saves, role switches, resume logic, two-stage CrossAI review
user-invocable: false
---

# Flow Codegen — Playwright Test Generation

Generate Playwright test files from FLOW-SPEC.md with condition-based waits, checkpoint persistence, role switch logic, and resume entry points.

**Called by:** `/rtb:sandbox-test` Step 8.5a
**Input:** ONLY `{phase}-FLOW-SPEC.md`
**Reference:** `apps/web/e2e/helpers.ts` (import list only — do NOT read implementation)
**Output:** `apps/web/e2e/flows/{phase}-{flow-name}.flow.spec.ts`

## Context Budget

Read FLOW-SPEC.md only. Do NOT read source code, FLOW-REGISTRY, CONTEXT, PLAN, or any other planning artifacts.

## Process

### Step 1: Read FLOW-SPEC.md

Parse all flows with their step sequences, mutation assertions, role switch points, and checkpoint types.

### Step 2: Generate Test File (per flow)

For each flow, create `apps/web/e2e/flows/{phase}-{flow-name}.flow.spec.ts` with:

**File scaffold:**
```typescript
import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

// Checkpoint directory — set by orchestrator via environment or config
// RTB: .planning/phases/{phase}/checkpoints
// VG: ${PHASES_DIR}/{phase}/checkpoints (from vg.config.md)
const CHECKPOINT_DIR = process.env.FLOW_CHECKPOINT_DIR || '.planning/phases/{phase}/checkpoints';
const CHECKPOINT_FILE = path.join(CHECKPOINT_DIR, '{flow-name}.checkpoint.json');

// Credentials — loaded from config or environment
// Orchestrator should set these from credentials config (rtb: _shared/credentials.md, vg: vg.config.md)
const CREDENTIALS = JSON.parse(process.env.FLOW_CREDENTIALS || '{}');
// Fallback structure: { roleName: { email, password, domain } }

test.describe('{Flow Name} — Multi-Page Flow', () => {
  // ... steps generated below
});
```

**Per step — use these EXACT patterns based on step type:**

**Mutation step (POST/PUT/DELETE):**
```typescript
await test.step('CP-{N}: {Action}', async () => {
  const [response] = await Promise.all([
    page.waitForResponse(resp =>
      resp.url().includes('{api-endpoint}') &&
      resp.request().method() === '{METHOD}' &&
      resp.status() < 400
    ),
    page.getByRole('button', { name: '{button-text}' }).click()
  ]);

  // UI Assert
  await expect(page.getByTestId('{indicator}')).toHaveText('{expected}');
  // Regression — old state GONE
  await expect(page.getByText('{old-state}')).not.toBeVisible();
  // API Assert
  const console = await page.evaluate(() => /* console error check */);
  expect(console.filter(m => /[45]\d{2}/.test(m))).toHaveLength(0);
  // Data Assert
  const data = await page.request.get('{verify-endpoint}');
  expect((await data.json()).{field}).toBe('{expected-value}');

  saveCheckpoint('CP-{N}', 'passed', '{cp-type}', { /* snapshot */ });
  await page.screenshot({ path: 'apps/web/e2e/screenshots/{phase}-{flow}-CP{N}.png' });
});
```

**Navigation step:**
```typescript
await test.step('CP-{N}: Navigate to {page}', async () => {
  await page.goto('{url}');
  await page.waitForSelector('{main-content-selector}');
  // Wide-view assertions as needed
  saveCheckpoint('CP-{N}', 'passed', 'auto-verify', {});
});
```

**Role switch step:**
```typescript
await test.step('CP-{N}: Switch to {role}', async () => {
  const {role}Context = await browser.newContext();
  const {role}Page = await {role}Context.newPage();
  await {role}Page.goto('/login');
  await {role}Page.fill('[name="email"]', CREDENTIALS.{role}.email);
  await {role}Page.fill('[name="password"]', CREDENTIALS.{role}.password);
  await {role}Page.getByRole('button', { name: 'Sign In' }).click();
  await {role}Page.waitForSelector('[data-page="dashboard"]');

  saveCheckpoint('CP-{N}', 'passed', 'human-verify', {});
  await {role}Page.screenshot({ path: '.../{phase}-{flow}-CP{N}-role-switch.png' });
});
```

### Step 3: Generate Checkpoint Helper

```typescript
function saveCheckpoint(stepId: string, status: string, cpType: string, snapshot: object) {
  if (!fs.existsSync(CHECKPOINT_DIR)) fs.mkdirSync(CHECKPOINT_DIR, { recursive: true });
  const cp = fs.existsSync(CHECKPOINT_FILE)
    ? JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf-8'))
    : { flow: '{flow}', phase: '{phase}', steps: {} };

  cp.steps[stepId] = {
    status, cp_type: cpType,
    timestamp: new Date().toISOString(),
    evidence: { screenshot: `{phase}-{flow}-${stepId}.png`, console_errors: [], api_calls: [] },
    snapshot
  };
  cp.updated_at = new Date().toISOString();
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify(cp, null, 2));
}
```

### Step 4: Generate Resume Entry Point

```typescript
test.beforeAll(async ({ browser }) => {
  if (!fs.existsSync(CHECKPOINT_FILE)) return; // fresh run

  const cp = JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf-8'));
  if (!cp.resume_from) return;

  // Login as the role at resume point
  const role = cp.resume_context.logged_in_as;
  // Navigate to saved page
  // Verify prior_data matches current state
  // If mismatch → clear checkpoint, force fresh run
});
```

### Step 5: CrossAI Two-Stage Review

**Stage 1 — Spec Compliance** (runs first):
Prompt the 3 CLIs: "Given FLOW-SPEC.md, verify generated test covers: every step in Step Sequence, every mutation assertion (3-layer), every role switch, every checkpoint save, every wait condition matches spec."
- Verdict: COMPLIANT / GAPS

**Stage 2 — Code Quality** (only if Stage 1 passes):
Prompt the 3 CLIs: "Review Playwright test for: no waitForTimeout, selectors use role/testid not CSS class, descriptive error messages, checkpoint evidence objects complete, role switch uses newContext."
- Verdict: QUALITY_PASS / ISSUES

## Anti-Patterns

- NEVER use `waitForTimeout` or `page.waitForTimeout(ms)` — always condition-based waits
- NEVER use CSS class selectors (`.btn-primary`) — use `getByRole`, `getByTestId`, `getByText`
- NEVER skip checkpoint save — every step must persist state for resume
- NEVER skip evidence capture — screenshot + console required even for passing steps
- NEVER hardcode credentials inline — use CREDENTIALS constant object
- NEVER re-login between steps unless role switch — session persists across steps
