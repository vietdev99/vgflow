# Transition Kit — CRUD Round-Trip

**Pattern:** state transition with invariants. Given (role, resource, scope), execute Read → Create → Read → Update → Read → Delete → Read with persistence verification between every mutation.

This kit applies to resources where `kit: crud-roundtrip` is declared in `CRUD-SURFACES.md`. For workflows that don't fit (approvals, bulk actions, settings, dashboards), use a different kit.

---

## Worker invocation contract

You are a worker spawned per `(resource × role)` pair. You will receive:

- **Resource context** — `name`, `route_list`, `route_create`, `route_detail`, `route_update`, `route_delete`, `form.fields[]`, `table.columns[]`, `scope` (`global` | `owner-only` | `tenant-scoped` | `self-service`)
- **Role context** — `role_name`, `auth_token`, `expected_behavior` matrix per operation
- **Forbidden side-effects list** — endpoints that MUST NOT be called for this operation
- **Output path** — where to write the run artifact JSON
- **Run ID** — unique identifier for this workflow run (used for unique payload generation, evidence refs, cleanup)

You have access to the Playwright MCP server for browser interaction. Use it for every step that touches the UI.

---

## 8-step round-trip

For each step, observe the actual response, compare to expected behavior for this role + scope, and emit a finding if observed ≠ expected.

### Step 1 — Read list (baseline)

- Navigate to `route_list` with `auth_token`.
- Capture: row count, column headers, sample row values, filter UI presence.
- Expected for role:
  - `admin` (global scope): 200, full row count
  - `user` (owner-only scope): 200, only owner's rows
  - `user` (admin-scoped resource): 403 or empty list (per app convention)
  - `anon`: 401 or login redirect
- If 200 + rows visible: capture `baseline_row_count`. Continue.
- If denied as expected: emit `step.status: skipped`, reason `denied_by_role`, skip remaining steps.
- If response diverges from expected: emit finding (severity per matrix below), continue ONLY if Read returned data (else skip).

### Step 2 — Create

- If `expected_behavior.create` denies for this role: verify the create affordance is hidden (no button/link visible) AND a direct POST returns the expected denial code. If either condition fails (button visible OR mutation succeeds), emit a `critical` finding (`auth_bypass`).
- If `expected_behavior.create` allows: open create form via UI affordance.
- Generate payload with **per-run unique values** to avoid collisions:
  - `name: "vg-review-{run_id}-create"`
  - `email: "vg-review-{run_id}@test.local"`
  - other fields: minimal valid values from `form.fields[].default_test_value` if declared, else type-appropriate fixtures
- Submit. Capture: response status, redirect target, network calls, screenshot.
- Track: every API call this step triggered. Cross-reference against `forbidden_side_effects[]`. If any forbidden endpoint hit (e.g. `POST /api/billing/charge` during create of a draft) → emit `high` finding.
- Capture the created entity ID (from response body, redirect URL, or list refresh).

### Step 3 — Read list (verify Create persisted)

- Navigate back to `route_list` (force reload, no cache).
- Verify `row_count == baseline_row_count + 1`.
  - **Caveat**: if the list is filtered/paginated and the new row falls outside view, this assertion is unreliable. Try filtering by the unique payload value (e.g. `name=vg-review-{run_id}-create`) before asserting.
- Verify the new row contains the submitted values.
- If row not visible: emit `high` finding `persistence_broken_or_optimistic_ui`, evidence = full request/response of Step 2 + this list query.

### Step 4 — Read detail

- If `route_detail` declared: navigate to `route_detail` for the created entity.
- Verify all submitted fields are persisted with submitted values.
- Capture: detail view structure (which fields shown, edit/delete affordance presence per role).
- If detail view doesn't exist for this resource: emit `step.status: skipped`, reason `no_detail_view`, continue to Step 5.

### Step 5 — Update

- If `expected_behavior.update` denies: verify edit affordance is hidden AND direct PATCH/PUT returns denial code. Emit finding if either bypass exists.
- If allowed: modify a non-id, non-immutable field. Use a per-run unique new value (`updated_value: "vg-review-{run_id}-updated"`) to avoid clock-skew false positives.
- Submit. Capture: response status, network calls.
- Cross-reference against `forbidden_side_effects[]`.

### Step 6 — Read detail (verify Update applied)

- Re-load the detail view (or list if no detail view).
- Verify the modified field shows the new unique value.
- Verify other fields unchanged.
- DO NOT rely on `updated_at` timestamp comparison — clock skew, async writes, second-level resolution all cause false positives. Compare the actual changed value instead.
- If unchanged: emit `high` finding `update_not_persisted`, evidence = Step 5 request/response + this read.

### Step 7 — Delete

- If `expected_behavior.delete` denies: verify delete affordance is hidden AND direct DELETE returns denial code.
- If allowed: trigger delete via UI (handle confirm dialog if present). Capture confirm dialog presence/absence — soft-delete UX often differs from hard-delete.
- Capture response status, network call, redirect.
- Cross-reference against `forbidden_side_effects[]`.

### Step 8 — Read (verify deletion)

- Determine soft vs hard delete from `CRUD-SURFACES.delete_policy`.
- **Hard delete**: list view should not contain the entity; detail URL should 404.
- **Soft delete**: entity should be flagged archived in the list (or hidden from default filter); detail URL should show archived banner; entity may still be reachable via "include archived" filter.
- If observed != expected per `delete_policy`: emit `medium` finding `delete_policy_mismatch`.

---

## Cleanup (mandatory — runs even on failure)

If the workflow created entities but didn't reach Step 7 successfully:
- Attempt cleanup via direct DELETE on captured entity ID using admin token.
- If cleanup fails: emit `cleanup_status: partial` in run artifact, list orphan IDs.

If the workflow created via UI but failed before capturing the ID:
- Search list for entities matching `name=vg-review-{run_id}-*` and delete them via admin token.
- Emit `cleanup_status: best_effort` if any matches deleted.

---

## Severity matrix

| Finding | Severity | Why |
|---|---|---|
| Mutation succeeds for role denied by matrix | critical | auth_bypass |
| Mutation triggers forbidden side-effect (email, billing, audit) | high | scope_violation |
| Persistence broken (Read after Create/Update doesn't reflect change) | high | data_integrity |
| Delete policy mismatch (hard when should be soft, or vice versa) | medium | UX/compliance |
| Detail view exists but missing submitted fields | medium | data_loss |
| Cleanup partial (orphan test data left in DB) | low | hygiene |

---

## Output: run artifact JSON

Write to `${OUTPUT_PATH}` exactly this shape (see `commands/vg/_shared/templates/run-artifact-template.json` for canonical schema):

```json
{
  "run_id": "<provided>",
  "resource": "<from context>",
  "role": "<from context>",
  "kit": "crud-roundtrip",
  "scope": "<from context>",
  "started_at": "<ISO 8601>",
  "completed_at": "<ISO 8601>",
  "steps": [
    {
      "name": "read_list_baseline",
      "status": "pass | fail | blocked | skipped",
      "expected": {"...": "..."},
      "observed": {"...": "..."},
      "evidence_ref": "evidence/run-{run_id}/step-1.json",
      "blocked_reason": null
    }
    // ... 8 steps total
  ],
  "coverage": {
    "attempted": 8,
    "passed": 0,
    "failed": 0,
    "blocked": 0,
    "skipped": 0
  },
  "findings": [
    {
      "id": "F-<incremental>",
      "title": "<short>",
      "severity": "critical | high | medium | low",
      "security_impact": "auth_bypass | scope_violation | data_integrity | tenant_leakage | none",
      "confidence": "high | medium | low",
      "dedupe_key": "<resource>-<role>-<step>-<short_desc>",
      "actor": {"role": "<role>", "user_id": "<from auth>", "tenant": "<if applicable>"},
      "environment": "<from config>",
      "step_ref": "step-<idx>",
      "request": {"...": "..."},
      "response": {"...": "..."},
      "trace_id": "<if available from response headers>",
      "data_created": [{"resource": "...", "id": "..."}],
      "cleanup_status": "completed | partial | skipped",
      "remediation_steps": ["..."],
      "cwe": "CWE-<id> | null"
    }
  ],
  "cleanup_status": "completed | partial | skipped"
}
```

Findings are derived from steps with `status: fail`. Steps with `status: blocked` (couldn't execute due to upstream failure) do NOT emit findings — they document why coverage is incomplete.

A clean pass produces zero findings and `coverage.passed == coverage.attempted`. The run artifact's existence proves execution; the verdict gate uses `coverage.attempted >= 1` and `evidence_ref` populated per non-skipped step.
