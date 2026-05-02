---
name: lens-table-interaction
description: Table/list interaction — filter, sort, paginate, search, bulk-select. Capture every interaction's pre/post state + URL state sync + network payload.
bug_class: state-coherence
applies_to_element_classes:
  - table_root
  - list_view
  - filter_bar
  - pagination_control
applies_to_phase_profiles:
  - feature
  - hotfix
strix_reference: VG-specific roam table-interaction lens
severity_default: warn
estimated_action_budget: 40
output_schema_version: 3
runtime: roam
---

# Lens: Table Interaction

## Mục đích

Drive a list/table surface through every interactive control (filter, sort, paginate, search, bulk-select) and capture state coherence between **UI display ↔ URL query string ↔ network request payload ↔ response body**.

## Threat model

- **Filter applied** but URL query string didn't update → not bookmarkable, breaks back-button restore
- **Sort clicked** but network sent stale sort param → server returns wrong order, UI shows wrong order, both lie
- **Paginate next** but URL stays at page=1 → refresh resets pagination silently
- **Search typed** but no debounce → flood of in-flight requests, last-write-wins races (R-duplicate-submit)
- **Bulk-select all** in paginated list → user thinks "all 200 rows", actually only current page selected → bulk action partial-applies silently
- **Filter persistence**: applied filter dropped on navigate-away-and-back without warning

## Action protocol

### Step 1 — Read baseline
- Navigate to surface URL
- Snapshot DOM
- Capture: row count visible, total count claim (if shown), pagination indicator state, filter values, sort indicator
- Capture network: list GET endpoint, response body (count, rows[0..3])
- Read URL query string — note all params

### Step 2 — Apply each filter (one at a time)
For EACH filter control in the filter bar:
- Click/select filter value (pick first non-default option)
- Capture: snapshot after filter, URL query string change, network request payload (which params sent to server), response body row count
- Verify URL contains filter param — log even if missing
- Reset filter (click "clear" or select default), capture network refetch

### Step 3 — Apply sort (every sortable column)
For EACH column header that's clickable for sort:
- Click once (asc), capture
- Click again (desc), capture
- For each click, check: header indicator, URL `sort=` param, network request `sort` field, response body order (first 3 rows)

### Step 4 — Paginate
- Click "next page" button — capture URL, network, response, visible rows
- Click "next" 3 more times if available — log each
- Click "previous" — capture
- Jump to page N=3 directly via input (if exists) — capture
- Refresh browser (F5 simulation: navigate to current URL) — verify page param survives or resets

### Step 5 — Search
- Type one character into search box — capture every keystroke's network call (or coalesced debounced call)
- Type 4 more characters — capture
- Clear search (Backspace × N) — capture re-fetches
- Submit search via Enter (vs auto-debounce) — log both behaviors if both supported

### Step 6 — Bulk select
- Click "select all visible" checkbox — capture: which rows highlighted, URL state, action button enablement
- Scroll/paginate while selection active — verify selection persists or drops
- Click bulk action button (e.g., bulk delete, bulk export) — capture confirmation modal text, network payload (does it send IDs from current page only or all matched?)
- DO NOT actually confirm the bulk action — close confirmation. Log the request payload that WOULD have been sent. Exception: if brief explicitly says "execute bulk delete on test data", proceed and capture.

### Step 7 — Combined state stress
- Apply filter + sort + page > 1 simultaneously
- Capture URL, network, response
- Refresh page (navigate to current URL fresh)
- Verify all 3 dimensions survive — log result either way

### Step 8 — Sub-view discovery
- If row click opens detail/edit modal, emit `spawn-child` event but DO NOT enter the sub-view. Continue table interaction lens.
- If filter dropdown opens a complex picker (date range, multi-select), capture its DOM state.

## Capture contract

Same JSONL format as form-lifecycle lens, with `step` indicating filter/sort/paginate/search variant. Always capture URL query string in `ui_before.url` and `ui_after.url` so commander can detect URL-state sync drift (R-url-state).

## ⛔ HARD RULES

[Same 9 hard rules as lens-form-lifecycle — refer to that lens for verbatim text. CLI MUST embed all 9 in its execution context.]
