---
name: test-depth
description: Interactive depth discovery — present DEEP components to user for business context, CrossAI trace unknowns, output DEPTH-INPUT.md
user-invocable: false
---

# Test Depth — User-Guided Business Flow Discovery

Present DEEP components to user, collect business context they know, CrossAI trace what they don't. Output structured DEPTH-INPUT.md.

**Called by:** `/rtb:test-specs` Step 2
**Input:** `{phase}-COMPONENT-MAP.md` (from test-scan)
**Output:** `.planning/phases/{phase}/{phase}-DEPTH-INPUT.md`

## Philosophy

AI is good at: scanning code, generating technical test steps, cross-referencing.
AI is bad at: guessing hidden business logic, side effects, domain rules.
User is good at: knowing what can go wrong, business rules, edge cases.
User is bad at: writing 100 test steps, remembering all modal fields.

→ **Each side does what they're good at.**

## Process

### 1. Load COMPONENT-MAP.md

Read the map. Extract all DEEP components with their signals and key actions.

### 2. Present DEEP Components to User

Show a numbered list:
```
Phase {X} has {N} DEEP components that trigger business flows.
I need your input on what each one does beyond the obvious.

1. ApproveButton (campaigns) — onClick calls POST /campaigns/:id/approve
   → Beyond status change, what else happens? (notifications? audit? auto-activate?)

2. AddFundsForm (finance) — onSubmit calls POST /funding/deposit
   → Beyond balance increase, what else triggers? (invoice? email? limits?)

3. DeleteSiteButton (sites) — onClick calls DELETE /sites/:id
   → Is this hard delete or soft? Pending period? Cascade to ad units?

For each, tell me:
  (a) What business flow does it trigger?
  (b) Any security risks? (see examples below)

Type "skip" for ones you're unsure about — I'll use CrossAI to trace those.
```

**Security question examples (show 1 per component based on type):**

| Component Type | Security Question |
|---------------|-------------------|
| Mutation with role check | "Can user A trigger this on user B's data? (IDOR)" |
| Financial operation | "Can balance go negative? Double-submit? Race condition?" |
| Role-gated action | "Can a publisher call this admin endpoint? (Privilege escalation)" |
| Data export/view | "Does this leak data from other orgs? (Tenant isolation)" |
| File upload | "Can malicious file be uploaded? Size limit? Type validation?" |
| Auth-related | "Brute force? Session fixation? Token reuse after logout?" |

### 3. Collect User Responses

For each component, user provides one of:
- **Business context:** "Approve also sends email to advertiser, creates audit log, and if campaign has auto_start=true it schedules activation"
- **Security context:** "Yes, IDOR risk — need to verify campaign belongs to caller's org"
- **"skip":** User doesn't know → queue for CrossAI trace
- **Additional edge cases:** "Also check: what if balance insufficient during approval?"

### 4. CrossAI Trace (skipped components only)

For components user skipped, spawn CrossAI depth trace:

Bundle per component: component source + API route + service file.

Prompt each CLI:
```
Trace the COMPLETE business flow triggered by this component.
For EVERY action: API endpoint, middleware, service side effects,
data changes, notifications, audit logs, cross-page impact, error states.
Output as: | # | Layer | Action | Side Effects |
```

Use fast-fail consensus (crossai-invoke.md with `$LABEL="depth-trace"`).

Merge with confidence: AGREED (3/3), CONFIRMED (2/3), DISPUTED (1/3).

### 5. Write DEPTH-INPUT.md

```markdown
---
phase: {phase}
deep_components: {N}
user_provided: {N}
crossai_traced: {N}
disputed_paths: {N}
---

## Component: {name}
- **Source:** user | crossai | both
- **File:** {path}

### Business Flow
| # | Action | Side Effects | Source | Confidence |
|---|--------|-------------|--------|------------|
| 1 | POST /campaigns/:id/approve | Status → approved | user | HIGH |
| 2 | Send email to advertiser | notification.send() | user | HIGH |
| 3 | Create audit log | auditLog.create() | user | HIGH |
| 4 | Schedule activation if auto_start | cron.schedule() | crossai (1/3) | DISPUTED |

### Error States (from user)
- Insufficient balance → 400 + toast
- Already approved → 409 + toast

### Test Implications
- Steps 1-3: MUST test (user confirmed)
- Step 4: VERIFY manually (DISPUTED — only 1 CLI found)
- Error states: MUST test both paths
```

## --deepen Mode

When called with `--deepen`:
1. Read existing DEPTH-INPUT.md
2. Show user which DISPUTED paths are still unverified
3. Ask: "These paths were uncertain last time. Can you confirm or deny?"
4. For NEW components (added since last scan): run full flow (steps 2-4)
5. Append new findings to DEPTH-INPUT.md

## Anti-Patterns
- DO NOT guess business logic — if user doesn't know and CrossAI is uncertain, mark DISPUTED
- DO NOT ask user about SHALLOW/INTERACTIVE components — waste of their time
- DO NOT skip CrossAI for "skip" components — that's the whole point of this step
- DO NOT ask more than 1 question per component — keep it focused
- DO NOT present technical details (hook names, file paths) — ask in business terms
