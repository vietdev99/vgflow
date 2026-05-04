---
name: lens-business-coherence
description: UI claim ↔ network truth ↔ DB read-after-write ↔ console state coherence. The core silent state-mismatch detector. Pair with form-lifecycle for richest evidence.
bug_class: state-coherence
applies_to_element_classes:
  - mutation_action
  - approval_flow
  - status_transition
applies_to_phase_profiles:
  - feature
  - bugfix
  - migration
strix_reference: VG-specific roam state-coherence lens
severity_default: warn
estimated_action_budget: 50
output_schema_version: 3
runtime: roam

# Task 26 / Task 36a additions:
recommended_worker_tier: sonnet
worker_complexity_score: 4
fallback_on_inconclusive: opus
min_actions_floor: 8
min_evidence_steps: 6
required_probe_kinds: [ui_vs_network, network_vs_db, console_vs_state]
---

# Lens: Business Coherence

## Mục đích

The flagship roam lens. Detects bugs where the **UI tells one story, the network tells another, and the DB tells a third**. These are the silent killers — manual QA never catches them because each layer in isolation looks fine.

## The 4 layers we cross-check

| Layer | Source of truth | Captured via |
|-------|----------------|--------------|
| UI display | DOM after action | `browser_snapshot` + toast text |
| User signal | Toast / modal / redirect | `browser_evaluate` |
| Network truth | HTTP status + response body | `browser_network_requests` |
| DB reality | API GET round-trip post-action | follow-up GET request |

## Threat model (commander rules R1, R2, R4, R5, R7, R8)

| Pattern observed | Rule | Severity |
|------------------|------|----------|
| Toast says "saved", network is 4xx/5xx | R1 silent_state_mismatch | high |
| Toast says "error", network is 2xx, follow-up GET shows mutation persisted | R2 toast_inconsistency | medium |
| Network 4xx/5xx, no toast, no error UI | R4 network_swallowed | high |
| POST 201 with new ID, follow-up GET list missing the ID | R5 orphan_state | critical |
| DELETE 204, follow-up GET /entity/{id} returns 200 | R7 delete_did_not_persist | critical |
| PATCH 200, follow-up GET shows old value | R8 update_did_not_apply | high |

## Action protocol

This lens is **typically combined with lens-form-lifecycle** — same RCRURD steps, but with extra cross-layer assertions captured at each mutation point.

### For each mutation step (Create / Update / Delete / Status-transition):

1. **Pre-state capture** (before user clicks the mutating action):
   - DOM snapshot
   - URL
   - If detail view, the entity's current field values (read directly from form/DOM)
   - Network: pre-flight GET if applicable to confirm baseline

2. **Action**: click the mutating button (per brief)

3. **Network truth capture** (the moment the action returns):
   - HTTP method, URL, status code
   - Request body (full payload)
   - Response body (full, up to 200KB, log oversize as `<truncated_at_200kb>`)
   - Response headers (Location for redirect, Content-Type, etc.)
   - Duration ms

4. **UI signal capture** (within 2s of action return):
   - Toast: text + type (success/error/warning/info)
   - Modal close behavior (auto-close on success, stay open on error?)
   - Redirect URL (if any)
   - Error UI inline (e.g., field-level error message)
   - Loading state cleared?

5. **Console capture**:
   - All console.error / console.warn since action start
   - Uncaught exceptions

6. **DB read-after-write** (the cross-check):
   - Wait 500ms (settle time)
   - Issue follow-up GET to entity endpoint OR list endpoint
   - Capture full response body
   - Compare expected vs actual:
     - For Create: expect new ID present in list
     - For Update: expect changed field value match request payload
     - For Delete: expect 404 on entity GET, ID absent from list

7. **Emit ONE event per mutation** with all 4 layers in a single record:

```json
{
  "ts": "...",
  "lens": "business-coherence",
  "surface": "...",
  "step": "create_invoice_submit",
  "action": {"tool": "browser_click", "selector": "..."},
  "ui_before":  {"snapshot_hash": "...", "field_values": {"customer_id": "c_1", "amount": 100}},
  "ui_after":   {"snapshot_hash": "...", "toast": {"text": "Đã tạo", "type": "success"}, "modal_visible": false, "url": "/admin/invoices"},
  "network": [{
    "url": "/api/invoices",
    "method": "POST",
    "status": 201,
    "request_body": {"customer_id": "c_1", "amount": 100},
    "response_body": {"id": "inv_999", "status": "draft", "amount": 100},
    "duration_ms": 234
  }],
  "console": [],
  "ws_frames": [],
  "follow_up_read": {
    "request": {"url": "/api/invoices?page=1", "method": "GET"},
    "response_status": 200,
    "found_in_list": true,
    "matched_entity": {"id": "inv_999", "amount": 100, "status": "draft"}
  }
}
```

The `follow_up_read` field is what makes this lens distinctive — it's the DB-truth check that lets the commander run R5/R7/R8 detectors.

### Status transitions (workflow lens)

If brief specifies a status field with workflow (draft → pending → approved → paid), execute each transition:
- Snapshot before
- Trigger transition (button or dropdown)
- Capture network mutation
- Capture toast/UI
- Follow-up GET
- Move to next state

Log every illegal transition attempt that gets blocked (e.g., paid → draft) — log the network response (likely 422 or 403) so commander can verify guardrails are present.

## ⛔ HARD RULES

[Same 9 hard rules as lens-form-lifecycle. CLI MUST embed all 9 in its execution context.]
