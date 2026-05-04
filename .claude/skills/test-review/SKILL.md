---
name: test-review
description: Review TEST-SPEC with adversarial self-review, historical gap patterns, coverage gate, API contract audit, CrossAI verification
user-invocable: false
---

# Test Review — Multi-Layer Spec Verification

Review TEST-SPEC.md through 4 verification layers before approving. Blocks if coverage insufficient or contracts broken.

**Called by:** `/rtb:test-specs` Step 4
**Input:** `{phase}-TEST-SPEC.md` + `{phase}-COMPONENT-MAP.md` + phase artifacts
**Output:** Reviewed TEST-SPEC.md (gaps added) + approval/block decision

## Process

### 1. Adversarial Self-Review ("And Then What?")

For EVERY test step in TEST-SPEC, ask 5 questions:

| # | Question | Catches |
|---|----------|---------|
| 1 | "This action fails — what does UI show?" | Missing error state tests |
| 2 | "This data appears on which OTHER pages?" | Missing cross-page propagation |
| 3 | "User does what AFTER this step?" | Missing next-action tests |
| 4 | "This field is null/empty/zero — what renders?" | Missing empty state tests |
| 5 | "This mutation has side effects in other modules?" | Missing cascade tests |

Add missing test steps directly to TEST-SPEC with marker:
`<!-- Added by adversarial review: {question #} -->`

### 2. Historical Gap Pattern Check

Read ALL GAP-PLAN files from previous phases:
```bash
cat .planning/phases/*/GAP-PLAN*.md 2>/dev/null | head -500
```

Common recurring patterns from this project:
- Missing modal fields (HTML has modal, React partial)
- Field name mismatch (snake_case API vs camelCase React)
- Missing tab content (tab exists but panel empty)
- Missing row action trace (action → drawer → different API)
- Missing error path (form assumes success)
- Missing role-scoped data (admin vs publisher view)

For each pattern: check if TEST-SPEC addresses it. If not → add test step.

### 3. Coverage Gate (BLOCKING)

Count coverage:
```
GOALS_FROM_CONTEXT = count of D-XX lines in CONTEXT.md
GOALS_IN_SPEC = count of D-XX references in TEST-SPEC.md
COVERAGE = GOALS_IN_SPEC / GOALS_FROM_CONTEXT * 100
```

- Coverage >= 85% → PASS
- Coverage < 85% → BLOCK with uncovered decisions list

### 4. API Contract Audit (BLOCKING)

For each page with mutations:
1. Find API endpoint from TEST-SPEC or COMPONENT-MAP
2. Read API route handler → extract response field names
3. Read React component → extract field accessors
4. Cross-reference: snake_case (API) vs camelCase (React)?

Mismatch found → BLOCK with report:
```
API Contract Mismatch:
  Component reads: createdAt
  API returns: created_at
  Fix needed before tests can pass
```

### 5. CrossAI Spec Review

Bundle: TEST-SPEC.md + COMPONENT-MAP.md + CONTEXT.md
Prompt checklist:
1. GOAL COVERAGE: Every D-XX → test step?
2. MODAL COMPLETENESS: Every modal field → listed?
3. WIDE-VIEW: Every page → full checklist?
4. API CONTRACT: Every mutation → watchApi?
5. DATA RULES: Every table → validation rules?
6. DEEP COMPONENTS: Every AGREED path from DEPTH-INPUT → test step?
7. ERROR STATES: Every DEEP component → error path tested?

Use fast-fail consensus (crossai-invoke.md with `$LABEL="spec-review"`).
APPROVED when: avg score >= 8/10 AND zero CRITICAL gaps.

### 6. Final Decision

- All gates pass → APPROVED, proceed to flow testing (Step 5) or crossai-check
- Any gate blocks → report what's missing, user fixes → re-run test-review only

## Anti-Patterns
- DO NOT approve if coverage < 85% — "close enough" leads to gap cycles
- DO NOT skip historical pattern check — same bugs repeat across phases
- DO NOT auto-fix API contract mismatches — report to user, they decide fix approach
- DO NOT run full pipeline on re-review — only re-run THIS skill, not test-scan/test-depth
