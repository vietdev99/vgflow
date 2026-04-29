# Transition Kit — Approval Flow

**Pattern:** lifecycle state machine with role separation. Resources where one role *creates/requests* and another role *approves/rejects*. Examples: topup_requests, withdrawal_requests, KYC submissions, expense reports, refund requests.

This kit applies when `kit: approval-flow` is declared in `CRUD-SURFACES.md`. Differs from `crud-roundtrip` because:
- Lifecycle states matter (`pending` → `approved` | `rejected` | `expired`)
- Different roles act at different states (requester creates, approver decides)
- Audit trail is part of contract — approval/rejection actions emit audit log
- State transitions are often irreversible (cannot un-approve directly)

---

## Worker invocation contract

You receive:
- **Resource context** — `name`, `route_list`, lifecycle states, `requester_role`, `approver_role`
- **Role context** — current role under test
- **Auth tokens** — for at least 2 distinct roles (requester + approver)
- **Forbidden side-effects** — endpoints that should NOT fire during specific states
- **Audit log endpoint** — to verify approval/rejection emits audit entry
- **Output path**

You have access to the Playwright MCP server.

---

## 8-step approval lifecycle

### Step 1 — Read pending list (as approver)

- Login as `approver_role`. Navigate to `route_list` filtered to `status: pending`.
- Capture: pending count, sample row.
- Expected: approver sees pending requests. Other roles get filtered list (only own) or 403.

### Step 2 — Create request (as requester)

- Switch login to `requester_role`. Submit a new request via UI.
- Capture: created request ID, response status.
- Per-run unique payload: `description: "vg-review-{run_id}-approval-test"`.
- Expected: 200/201 with `status: pending`.

### Step 3 — Verify request appears in approver queue

- Switch login back to `approver_role`. Re-load pending list.
- Verify the just-created request is visible.
- If not visible: emit `high` finding `request_not_visible_to_approver` — workflow broken.

### Step 4 — Approver attempts approve

- Locate the request, click `Approve` action (or send POST /api/.../approve).
- Capture: response status, audit log network call, redirect/state change.
- Expected: 200, request status flips to `approved`.

### Step 5 — Verify state transition + audit log

- Re-load detail or list. Verify status now `approved`.
- Verify audit log endpoint received an entry referencing this request + actor.
- If state flipped but no audit: emit `medium` finding `state_change_without_audit_log`.
- If audit emit but state still `pending`: emit `high` finding `audit_emit_without_state_change` (chicken-egg, possibly DB write failure masked).

### Step 6 — Requester attempts to approve own request (negative test)

- Switch login to `requester_role`. Try to approve a different `pending` request (or via direct API).
- Expected: 403 (separation of duties — requester cannot approve own/peer requests).
- If 200: emit `critical` finding `auth_bypass_separation_of_duties`.

### Step 7 — Approver attempts re-approve (idempotency)

- Switch back to `approver_role`. Send approve again on already-approved request.
- Expected: 409 Conflict OR 200 idempotent (no duplicate audit log entry).
- Inspect: did audit log get a duplicate entry? If yes: emit `medium` finding `audit_duplicate_on_replay`.

### Step 8 — Reject path test

- Create another request (Step 2 repeat).
- Approve target → click `Reject` instead. Verify state flips to `rejected`, audit log entry created.
- Verify: rejected requests cannot be re-approved (state transition guard).
- If reject → approve succeeds: emit `high` finding `state_machine_invalid_transition`.

---

## Cleanup

If workflow created requests in pending/approved state without reaching final state:
- Cancel them via admin token if endpoint exists.
- Otherwise note in `cleanup_status: partial` with orphan IDs for manual cleanup.

---

## Severity matrix

| Finding | Severity | Why |
|---|---|---|
| Requester can approve (separation of duties bypass) | critical | privilege/authz |
| Approve succeeds but state unchanged | high | data_integrity |
| State change without audit log | medium | compliance |
| Duplicate audit on replay | medium | UX/compliance |
| Invalid state transition (reject → approve) | high | state_machine |
| Audit log unreachable from approver action | low | observability |

---

## Output: run artifact JSON

Write to `${OUTPUT_PATH}` per `run-artifact-template.json` schema. `kit: "approval-flow"`. Include `lifecycle_observed` field listing transitions seen during the run.
