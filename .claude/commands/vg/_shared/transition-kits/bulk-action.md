# Transition Kit — Bulk Action

**Pattern:** list view with multi-select + batch operation. Examples: archive selected campaigns, delete selected files, export selected rows, bulk-assign tag.

This kit applies when `kit: bulk-action` is declared in `CRUD-SURFACES.md` (or implicitly when `bulk_actions[]` is non-empty).

Differs from CRUD round-trip because:
- Operates on N rows at once, not 1 entity
- Partial-failure handling matters (5 succeed, 2 fail — what does UI show?)
- Race conditions visible (rows changing while bulk op in flight)
- Batch limits (max 100 rows per op) often have weak enforcement
- Cleanup harder (might affect more than the test created)

---

## Worker invocation contract

You receive:
- **Resource + bulk action** — name + which bulk action to test (e.g. "archive", "delete", "export")
- **Role context** + auth token
- **Batch limit** — declared `bulk_action_limit` from CRUD-SURFACES (default 100 if not declared)
- **Forbidden side-effects**
- **Output path**

You have Playwright MCP access.

---

## 8-step bulk-action workflow

### Step 1 — Seed N rows (as authorized role)

- Create `N = min(5, batch_limit)` rows via API/UI with unique tag `vg-review-{run_id}-bulk-*`.
- Capture: created entity IDs.

### Step 2 — Read list, verify all N rows visible

- Filter list to show `vg-review-{run_id}-bulk-*` rows.
- Verify count == N.

### Step 3 — Select all N rows

- Use UI checkbox-all OR individual checkboxes.
- Capture: bulk action menu becomes visible (usually conditional on selection).

### Step 4 — Execute bulk action

- Click target action (e.g. `Archive`).
- Confirm dialog handling.
- Capture: response status, network calls.
- Track: was it 1 batch API call OR N individual calls? Both patterns exist; just note for evidence.

### Step 5 — Verify all N affected

- Re-load list (un-filter or use archived filter).
- Verify all N rows reflect the action (archived/deleted/tagged).
- If only some affected: emit `high` finding `bulk_partial_silent_success` — server returned 200 but only k of N processed.

### Step 6 — Negative test: unauthorized role bulk action

- Switch to a role that can read but not bulk-mutate.
- Repeat Steps 3-4. Verify denial (button hidden OR API returns 403).
- If bypass: emit `critical` finding `auth_bypass_bulk_action`.

### Step 7 — Batch limit boundary test

- Seed `batch_limit + 5` rows.
- Select all, attempt bulk action.
- Expected: server rejects (413 Payload Too Large or 400 with limit error) OR processes only first `batch_limit` and reports partial.
- If processes all unbounded: emit `medium` finding `batch_limit_not_enforced` (DoS risk).

### Step 8 — Race-condition probe (optional, lower priority)

- Seed rows, select all.
- In parallel: have another browser context delete one of the selected rows.
- Trigger bulk action. Expected: graceful handling (skip deleted row, report partial) OR atomic transaction failure.
- Server crash / 500 / data corruption → emit `high` finding `race_condition_panic`.

---

## Cleanup

- Delete or archive every `vg-review-{run_id}-bulk-*` row via admin token.
- If bulk action was destructive (delete) and Step 5 verified all gone, no cleanup needed.
- If Step 4 partial-failed, list orphans in `cleanup_status: partial`.

---

## Severity matrix

| Finding | Severity | Why |
|---|---|---|
| Bulk auth_bypass (unauthorized role can bulk-mutate) | critical | privilege escalation |
| Bulk partial silent success (claimed success, partially applied) | high | data integrity |
| Race condition causes panic / data corruption | high | availability |
| Batch limit not enforced | medium | DoS risk |
| UX: confirm dialog skipped on bulk delete | medium | safety |

---

## Output

Write to `${OUTPUT_PATH}` per run-artifact-template.json. `kit: "bulk-action"`. Include `batch_size_tested` and `batch_limit_observed` fields.
