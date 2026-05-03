---
name: write-test-spec
description: Write comprehensive E2E test specifications for a phase — reads existing test docs (TEST-STRATEGY, BUSINESS-FLOW-SPECS, WIDE-VIEW-AUDIT), scans HTML prototypes for hidden modals, cross-references React+API, cross-AI verifies specs with Codex+Gemini+Sonnet
user-invocable: true
---

# Skill: Write Test Spec

Create comprehensive E2E test specifications for a phase BEFORE coding begins.

**Pipeline position:** This runs BEFORE build, not after.

```
/write-test-spec {X}    <- Specs FIRST (this skill)
        |
/vg:build {X}           <- Code to pass specs
        |
/vg:test {X}            <- Run specs on target env
        |
/vg:accept {X}          <- Human UAT
```

## Arguments
```
/write-test-spec <phase>              -- Full spec for a phase
/write-test-spec <phase> --page <name> -- Spec for one page only
/write-test-spec <phase> --audit-only  -- Gap audit only, no spec output
```

## Process

### Step 0: Read Existing Test Documentation (MUST READ FIRST)

The project has a comprehensive test documentation system. Read ALL of these BEFORE writing anything.

**0a. TEST-STRATEGY.md — the foundation (CRITICAL):**

```bash
cat {config.paths.planning}/TEST-STRATEGY.md
```

This file contains:
- **Per-phase test audit** — what tests are ALREADY recommended for this phase
- **Specific test file names + test case descriptions** — don't reinvent, USE THESE
- **Critical Business Flows** — end-to-end paths that MUST be tested
- **Test conventions** — file structure, naming, patterns
- **Coverage targets** — per-app coverage requirements
- **Gaps sorted by severity** — CRITICAL, HIGH, MEDIUM

Extract the section for THIS phase. The recommended test files ARE the spec.

**0b. BUSINESS-FLOW-SPECS.md — the test methodology:**

```bash
cat {config.paths.phases}/BUSINESS-FLOW-SPECS.md
```

Defines:
- **Wide-View rule** — mandatory checklist per page visit
- **Data Validation Rules** — column headers, forbidden patterns, badges, dates, numbers
- **Business Flows** — step-by-step with field values, expected results
- **Session strategy** — seamless, no re-login
- **Helper functions** — assertTableColumns, assertTableDataValid, etc.

**0c. Phase-specific artifacts:**

```bash
PHASE_DIR=$(ls -d {config.paths.phases}/${PHASE}*)

cat "$PHASE_DIR"/CONTEXT.md         # Decisions (D-XX) -> each = test assertion
cat "$PHASE_DIR"/PLAN.md            # must_haves.truths -> each = test step
cat "$PHASE_DIR"/SPECS.md 2>/dev/null # Phase spec if exists
```

**0d. Existing test results and audits:**

```bash
cat {config.paths.planning}/TEST-REPORT-VI.md 2>/dev/null
cat "$PHASE_DIR"/SANDBOX-TEST.md 2>/dev/null
```

**0e. ROADMAP success criteria:**

```bash
grep -A 20 "Phase ${PHASE}" {config.paths.planning}/ROADMAP.md
```

**0f. Existing E2E infrastructure:**

```bash
ls {config.paths.flow_tests}/                # Which flow test files exist
cat {config.paths.e2e_tests}/helpers.ts      # Available helper functions
```

**0g. Build the Goal Matrix from ALL sources:**

Combine goals from: TEST-STRATEGY recommended tests + CONTEXT decisions + PLAN must_haves + ROADMAP criteria + BUSINESS-FLOW-SPECS overlapping flows.

```markdown
## Phase {X} Test Goals

### From TEST-STRATEGY.md (recommended test files for this phase)
| Test File | Test Cases | Already Implemented? |
|-----------|-----------|---------------------|
| {path from TEST-STRATEGY} | {test descriptions} | yes/no |

### From CONTEXT.md Decisions
| Decision | What to Test | Priority |
|----------|-------------|----------|
| D-XX | {assertion} | CRITICAL/HIGH |

### From PLAN must_haves
| Truth | Test Step | Covered? |
|-------|-----------|----------|

### From ROADMAP Success Criteria
| Criterion | Test Step | Covered? |
|-----------|-----------|----------|

### From BUSINESS-FLOW-SPECS (overlapping flows)
| Flow | Steps | Status |
|------|-------|--------|
| Flow {N} | Step {X.Y}-{X.Z} | extend/rewrite/new |
```

This goal matrix is the SPEC'S ACCEPTANCE CRITERIA. Every row must have a test by the end.

### Step 1: Identify Pages in Scope

From the goal matrix, determine which pages/features need testing.

Map each to its 3 sources:

| Feature | HTML Prototype | React Component | API Module |
|---------|---------------|-----------------|------------|
| (from plans) | html/.../*.html | {config.code_patterns.web_pages}/*.tsx | {config.code_patterns.api_routes}/* |

### Step 2: Deep HTML Scan (CRITICAL — hidden modals)

For each HTML page in scope, extract EVERYTHING including hidden elements.

**2a. Surface elements (visible):**
```bash
# Extract: tables, KPI cards, toolbar, buttons, tabs, nav
grep -n "class=\".*table\|<th\|<td\|card\|stat\|kpi\|btn\|button\|tab\|filter\|search\|dropdown" "$HTML_FILE"
```

**2b. Hidden modals (MUST NOT SKIP):**
```bash
# Find ALL modal-overlay or modal containers
grep -n "modal-overlay\|id=\".*[Mm]odal\|class=\".*modal" "$HTML_FILE"
```

For EACH modal found:
1. Read the full modal HTML (from modal-overlay to its closing div)
2. Extract modal title (`modal-title` or `h3`)
3. Extract ALL form fields inside:
   - `<input>` — name, type, placeholder, value
   - `<select>` — name, options (read ALL `<option>` tags)
   - `<textarea>` — name, placeholder
   - `<button>` — text, onclick action
4. Extract tables inside modals (columns, data patterns)
5. Extract tabs inside modals (tab names, tab panels)
6. Extract conditional sections (sections that show/hide based on state)

**2c. Hidden elements outside modals:**
```bash
# Elements with display:none, hidden attribute, or JS-controlled visibility
grep -n "display:none\|display: none\|hidden\|style=\".*visibility" "$HTML_FILE"
```

Check for:
- Dropdown menus with options list
- Tooltip content
- Inactive tab panels
- Conditional form sections (show/hide based on select value)
- Confirmation dialogs
- Context menus (right-click)

**2d. Inline JS event handlers:**
```bash
# Extract onclick, onchange, onsubmit handlers — they reveal hidden workflows
grep -n "onclick=\"\|onchange=\"\|onsubmit=\"" "$HTML_FILE" | head -30
```

Map each handler to the function it calls — that function often shows/hides modals or updates state.

### Step 3: React Component Audit

For each React component (.tsx) that implements the HTML page:

**3a. Columns config:** Look for `columns` array, `ColumnDef`, `createColumnHelper`. Extract exact header text.

**3b. Modal/Drawer components:** Look for `<Dialog>`, `<Modal>`, `<Sheet>`, `<Drawer>`, `useState(open/show/visible)`. Extract trigger, title, fields, submit.

**3c. KPI/Stat cards:** Look for `StatsCard`, `KpiCard`, grid patterns. Extract labels, value sources.

**3d. Form fields:** Look for `<Input>`, `<Select>`, `<Textarea>`, react-hook-form `register()`. Extract names, validation rules.

**3e. Query hooks:** Look for `useQuery`, `useMutation`. Extract endpoint URLs, methods, shapes.

### Step 4: Cross-Reference Gap Analysis (CRITICAL)

Build a comparison matrix for each page:

```markdown
## Gap Analysis: [PageName]

### Surface Widgets
| Widget | HTML Prototype | React Component | Status |
|--------|---------------|-----------------|--------|
| {widget} | {HTML detail} | {React detail} | OK / GAP: {what's missing} |

### Modals (field-level -- NOT modal-level)
| Modal | HTML fields | React fields | Missing |
|-------|------------|-------------|---------|
| {modal} | {count} | {count} | {list missing fields} |

### API Endpoints
| Action | HTML onclick | API Route | React Hook | Status |
|--------|-------------|-----------|------------|--------|
| {action} | {handler} | {route} | {hook} | OK / GAP |
```

### Step 5: Write Test Spec Document

Output: `{config.paths.phases}/{phase}/{phase}-TEST-SPEC.md`

**Structure per page:**

```markdown
---
phase: {phase}
type: test-spec
goals_from_context: {count D-XX decisions}
goals_from_roadmap: {count success criteria}
goals_from_business_flow: {count flow steps}
modals_found: {count}
modals_covered: {count}
gaps_found: {count}
---

# Test Spec: Phase {X} -- {Name}

## Goal Coverage Matrix
(copy from Step 0g -- every row must now have a test step filled in)

## Gap Summary
(from Step 4 -- sorted by severity)

## SESSION SETUP
| Session | Domain | Credentials | Start Page |
|---------|--------|-------------|------------|

## PAGE: {PageName}

### Wide-View Checklist
(h1, screenshot, KPI, toolbar, table columns, Rules 1-5, pagination, CTA, empty state)

### Modals -- ALL fields listed
(for EACH modal: trigger, title, every field with type/name/validation/test-value, tabs, submit, post-submit checks)

### Business Flow Steps
(session, page, wide-view check, action table, API verify, expected result, screenshot, save entityId)

### Data Validation Rules
(per column: which of Rules 1-5 apply, expected format, example)

### Screenshot Capture Points
(page load, modal open, after submit, before leave)

### Parallel Group Assignment
(A/B/C/D, session, mutation risk, run timing)
```

### Step 6: Verify Completeness

**6a. Goal matrix check:** Every row from Step 0g has a test step? Any uncovered goal = FAIL.

**6b. Modal coverage:** Every HTML modal has fields listed in spec? Missing modal = FAIL.

**6c. Field coverage:** Every `<input>`, `<select>`, `<textarea>` in HTML has a test value? Missing field = flag.

**6d. Action coverage:** Every `onclick` handler in HTML has a test step? Missing action = flag.

**6e. Table column coverage:** Every `<th>` in HTML has a column in assertTableColumns()? Missing column = flag.

### Step 7: Output Summary

```markdown
## Spec Complete

Phase: {X}
Goals covered: {G} (from CONTEXT + ROADMAP + BUSINESS-FLOW-SPECS)
Pages covered: {N}
Modals scanned: {M} (HTML) -> {M'} (React) -> {M''} gaps
Fields scanned: {F} (HTML) -> {F'} (React) -> {F''} gaps
Test steps: {S}
Assertions: {A}

### Implementation Gaps (code changes needed before tests pass)
{gaps that need new React components or API endpoints}

### Test Gaps (Playwright code needed)
{spec items that need test implementation}

### Deferred (out of phase scope per CONTEXT.md)
{explicitly excluded items}
```

### Step 8: Cross-AI Spec Verification (MANDATORY)

Specs MUST be verified by external AI CLIs (config.crossai_clis) before they're considered final.

**8a. Prepare review bundle:**

```bash
cat \
  {config.paths.phases}/${PHASE}/TEST-SPEC.md \
  {config.paths.phases}/${PHASE}/CONTEXT.md \
  {config.paths.phases}/${PHASE}/PLAN.md \
  > /tmp/spec-review-bundle.txt
```

**8b. Review prompt — goals + fields + modals:**

```
# Test Spec Review -- Adversarial Audit

Review this TEST SPEC for the project.
Cross-reference against CONTEXT.md decisions, PLAN must_haves, and BUSINESS-FLOW-SPECS goals.

## Check (in order of priority):
1. GOAL COVERAGE: Every D-XX decision -> has a test step?
2. MUST_HAVES: Every must_have truth -> has a test assertion?
3. SUCCESS CRITERIA: Every ROADMAP criterion -> has a verification point?
4. MODAL COMPLETENESS: Every modal field from HTML -> listed in spec?
5. WIDE-VIEW: Every page visit -> full checklist (KPI, toolbar, table, pagination)?
6. API CONTRACT: Every mutation -> watchApi + assertApiResponse?
7. DATA RULES: Every table -> Rules 1-5 applied?
8. CROSS-ROLE: Sessions seamless, no unnecessary re-login?

## Output: Verdict (PASS/GAPS_FOUND), gaps by severity, score X/10
```

**8c. Run CLIs in parallel (from config.crossai_clis):**

Each configured CLI reviews the bundle with the prompt. Commands use `{context}` and `{prompt}` placeholders.

**8d. Consensus matrix -> fix gaps -> re-verify (max 3 cycles).**

**8e. APPROVED when: average score >= 8/10 AND zero CRITICAL gaps.**

## Key Principles

1. **Goals first, HTML second** — read CONTEXT decisions + ROADMAP criteria BEFORE scanning HTML
2. **HTML is source of truth for UI** — if HTML has it and React doesn't, it's a gap
3. **Every modal MUST be tested** — hidden modals are the #1 source of missed coverage
4. **Every field inside every modal MUST be listed** — field-level, not modal-level
5. **Wide-view is mandatory** — no "click and check" without page-level validation first
6. **API contract must match** — form field name <> Zod schema key <> API response field
7. **Screenshots are evidence** — every state change gets captured
8. **Sessions are seamless** — no re-login between steps

## Anti-Patterns

- DO NOT skip Step 0 — jumping to HTML scan without reading CONTEXT/PLAN/ROADMAP = blind spec
- DO NOT write specs based on React only — you will miss hidden HTML modals
- DO NOT list modals at modal-level — list EVERY FIELD inside
- DO NOT skip inactive tabs inside modals — each tab panel has its own fields
- DO NOT assume select options — read ALL `<option>` tags from HTML
- DO NOT skip conditional form sections — Banner shows size dropdown, Native shows asset fields
