---
name: test-scan
description: Scan code + HTML prototypes, classify components (shallow/interactive/deep), build COMPONENT-MAP.md with pages, modals, fields, depth classification
user-invocable: false
---

# Test Scan — Component & Page Inventory

Scan HTML prototypes + React components + API modules for a phase. Classify every component by depth. Output structured COMPONENT-MAP.md.

**Called by:** `/rtb:test-specs` Step 1
**Input:** Phase number + phase artifacts (CONTEXT.md, PLAN*.md, SPECS.md)
**Output:** `.planning/phases/{phase}/{phase}-COMPONENT-MAP.md`

## Process

### 1. Read Phase Context (what to scan)

```bash
PHASE_DIR=$(ls -d .planning/phases/${PHASE}*)
cat "$PHASE_DIR"/CONTEXT.md       # Decisions → what features exist
cat "$PHASE_DIR"/*-PLAN*.md       # Tasks → what pages/components were built
```

Extract: which API modules, which React pages, which HTML prototypes belong to this phase.

### 2. Build Goal Matrix

Combine goals from ALL sources into structured list:

| Source | Pattern | Extract |
|--------|---------|---------|
| CONTEXT.md | `D-XX:` lines | Decision → test assertion |
| ROADMAP.md | Phase success criteria | Criterion → verification point |
| SPECS.md | Success criteria section | Criterion → test step |
| TEST-STRATEGY.md | Phase section | Recommended test files |
| BUSINESS-FLOW-SPECS.md | Overlapping flows | Flow steps to extend |

### 3. Identify Pages + Map to Sources

| Feature | HTML Prototype | React Component | API Module |
|---------|---------------|-----------------|------------|
| (from plans) | `html/.../*.html` | `apps/web/src/pages/*.tsx` | `apps/api/src/modules/*` |

### 4. Deep HTML Scan (hidden modals)

For each HTML page in scope:

**4a. Surface elements:** grep tables, KPI cards, toolbar, buttons, tabs
**4b. Hidden modals (MUST NOT SKIP):**
```bash
grep -n "modal-overlay\|id=\".*[Mm]odal\|class=\".*modal" "$HTML_FILE"
```
For EACH modal: extract title, ALL form fields (input/select/textarea), tables inside, tabs inside, conditional sections.

**4c. Hidden elements outside modals:** dropdown menus, inactive tabs, conditional form sections, confirmation dialogs.

**4d. Inline JS handlers:** `onclick`, `onchange`, `onsubmit` → map to functions that show/hide modals.

### 5. React Component Audit

For each React component (.tsx):
- **Columns:** `ColumnDef`, `createColumnHelper` → exact header text
- **Modals/Drawers:** `<Dialog>`, `<Modal>`, `<Sheet>` → trigger, title, fields, submit
- **KPI cards:** `StatsCard`, grid patterns → labels, value sources
- **Form fields:** `<Input>`, `<Select>`, react-hook-form → names, validation
- **Query hooks:** `useQuery`, `useMutation` → endpoints, methods
- **DataTable row actions:** For EVERY action column → trace what opens, what data it reads, what secondary API it calls

### 6. Classify Components by Depth

```
DEEP (any 1 signal):
  - imports useMutation / api.post/put/delete
  - onSubmit handler calling API
  - useAuth / role-based conditional
  - router.push / navigate (cross-page)
  - dispatch to global store
  - WebSocket/SSE subscription

INTERACTIVE (handlers but no API):
  - onClick/onChange modifying local state
  - Filter/sort/search without API

SHALLOW (everything else):
  - Receives props, renders JSX only
```

### 7. Gap Analysis

Build comparison matrix per page:
```
| Widget | HTML | React | Status |
| Modal  | HTML | React | Status |
| API    | Route exists? | Response shape matches component? |
```

### 8. Write COMPONENT-MAP.md

```markdown
---
phase: {phase}
pages: {N}
components_total: {N}
shallow: {N}
interactive: {N}
deep: {N}
modals_found: {N}
goals_mapped: {N}
---

## Goal Matrix
| ID | Source | Description | Page | Priority |

## Pages
### Page: {name}
- HTML: {path}
- React: {path}
- API: {module}

#### Modals (from HTML scan)
| Modal | Fields | In React? | Status |

#### Components by Depth
| Component | Depth | Signals | Key Actions |

#### Gap Analysis
| Widget/Modal | HTML | React | Gap? |
```

## Anti-Patterns
- DO NOT skip hidden modals — #1 source of missed coverage
- DO NOT skip DataTable row action tracing — #2 source of missed bugs
- DO NOT classify based on component name alone — check actual imports
- DO NOT read component implementation deeply — that's test-depth's job. Just classify.

## HTML Modal Reference

| Page | Modals | IDs |
|------|--------|-----|
| SSP Admin inventory.html | 4 | siteAdUnitsModal, editSiteModal, editAdUnitModal, getTagModal |
| SSP Admin reports.html | 5 | refundModal, videoDetailsModal, publisherSitesModal, siteAdUnitsModal |
| SSP Admin floor-prices.html | 3 | (rule create, rule edit, preview) |
| SSP Admin brand-safety.html | 2 | (category config, domain import) |
| SSP Admin fraud-detection.html | 2 | (alert detail, rule edit) |
| Publisher sites.html | 2 | (create site, site detail) |
| Publisher ad-units.html | 3 | (create ad unit, embed code, edit) |
| Publisher payments.html | 3 | (invoice breakdown, payment method, schedule) |
| Advertiser campaigns.html | 1 | (6-step wizard) |
| Advertiser audiences.html | 2-3 | (create audience, get code, delete confirm) |
