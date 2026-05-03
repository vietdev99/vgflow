---
name: test-gen
description: Generate TEST-SPEC.md from structured inputs (COMPONENT-MAP + DEPTH-INPUT) — supports --deepen mode for iterative refinement
user-invocable: false
---

# Test Gen — Structured Spec Generation

Generate TEST-SPEC.md from COMPONENT-MAP.md + DEPTH-INPUT.md. No guessing — every test step traces back to a source (goal, user input, or CrossAI trace).

**Called by:** `/rtb:test-specs` Step 3
**Input:** `{phase}-COMPONENT-MAP.md` + `{phase}-DEPTH-INPUT.md`
**Output:** `.planning/phases/{phase}/{phase}-TEST-SPEC.md`

## Context Budget

Read ONLY COMPONENT-MAP.md and DEPTH-INPUT.md. Do NOT re-read source code, HTML prototypes, or planning artifacts — test-scan already extracted everything needed.

## Process

### 1. Load Structured Inputs

```bash
cat "${PHASE_DIR}/${PHASE}-COMPONENT-MAP.md"   # pages, components, modals, gaps, goals
cat "${PHASE_DIR}/${PHASE}-DEPTH-INPUT.md"      # business flows from user + CrossAI
```

### 2. Generate Per-Page Specs

For each page in COMPONENT-MAP:

**2a. Wide-View Checklist (mandatory per page):**
```
[ ] h1/title — match expected text
[ ] KPI/stat cards — visible, values not NaN/null/undefined
[ ] Toolbar — search + filters present
[ ] Table columns — match COMPONENT-MAP column list
[ ] Table data — no [object Object] / Invalid Date / undefined
[ ] Pagination — visible if applicable
[ ] Primary CTA — visible + enabled
[ ] Empty state — proper message if no data
[ ] Console errors — none unexpected
[ ] Screenshot — capture full page
```

**2b. Component specs by depth:**

| Depth | What to generate |
|-------|-----------------|
| SHALLOW | 1-2 assertions: exists + content correct |
| INTERACTIVE | 3-5 assertions: action + state change + UI update |
| DEEP | Full business flow from DEPTH-INPUT: every step + side effects + error states |

**2c. Modal specs (from COMPONENT-MAP modal inventory):**

For EVERY modal: list ALL fields with type, name, validation, test value.
Include: form submit assertions, error state assertions, close/cancel behavior.

**2d. DataTable row action specs:**

For EVERY row action from COMPONENT-MAP:
```
ACTION: Click [name] on table row
  OPENS: [component] (Modal/Drawer)
  READS: [fields from COMPONENT-MAP]
  CALLS: [secondary API if any]
  ASSERT: renders, no undefined, dates formatted, amounts formatted
```

### 3. Generate Business Flow Specs (from DEPTH-INPUT)

For each DEEP component with business flow trace:

```
## Business Flow: {component name}

### Happy Path
| Step | Action | Assert UI | Assert API | Assert Data |

### Error Paths (from DEPTH-INPUT error states)
| Error | Trigger | Expected UI | Expected API |

### Side Effects (from DEPTH-INPUT)
| Side Effect | Confidence | How to Verify |
| Send email  | HIGH (user) | Check notification list |
| Audit log   | CONFIRMED  | Check audit page |
| Schedule    | DISPUTED   | ⚠ Verify manually |
```

### 4. Source Tracing

Every test step MUST have a source reference:
```
<!-- Source: D-XX from CONTEXT.md -->
<!-- Source: User input for ApproveButton -->
<!-- Source: CrossAI trace CONFIRMED (2/3) -->
<!-- Source: HTML modal scan — adjustmentModal -->
```

This enables: when a spec seems wrong, trace back to WHY it was generated.

### 5. Write TEST-SPEC.md

```markdown
---
phase: {phase}
type: test-spec
goals_covered: {N}/{total}
pages: {N}
modals_covered: {N}/{found}
deep_components: {N}
user_inputs: {N}
crossai_traces: {N}
disputed_items: {N}
---
# Test Spec: Phase {X} — {Name}

## Session Setup
## Goal Coverage Matrix
## PAGE: {name}
  ### Wide-View Checklist
  ### Components (by depth)
  ### Modals
  ### Business Flows
  ### Error Paths
  ### Screenshot Capture Points
```

## --deepen Mode

When existing TEST-SPEC.md exists:

1. Read existing spec as baseline
2. Read NEW DEPTH-INPUT.md (user provided more context)
3. For each new finding in DEPTH-INPUT:
   - Check if already covered in existing spec → skip
   - New finding → append test steps with `<!-- Added by --deepen round {N} -->` marker
4. For DISPUTED items that user confirmed/denied in this round:
   - Confirmed → upgrade to full test steps
   - Denied → remove or mark as out-of-scope
5. Recalculate coverage metrics in frontmatter

**NEVER delete existing test steps during deepen** — only add or upgrade.

## Anti-Patterns
- DO NOT re-scan code — COMPONENT-MAP has everything. Re-scanning = context waste
- DO NOT guess business logic — if not in DEPTH-INPUT, it's not tested (add via --deepen later)
- DO NOT write test steps without source reference — every step must trace to a goal/input/trace
- DO NOT treat all components equally — SHALLOW gets 1 assertion, DEEP gets full flow
- DO NOT skip DISPUTED items — list them as flagged, user decides in --deepen
