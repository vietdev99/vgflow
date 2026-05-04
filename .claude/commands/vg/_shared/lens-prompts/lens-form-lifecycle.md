---
name: lens-form-lifecycle
description: Form RCRURD lifecycle — Read empty → Create → Read populated → Update → Read updated → Delete → Read empty. Capture every step's UI/network/console/toast state for commander coherence analysis.
bug_class: state-coherence
applies_to_element_classes:
  - form_root
  - submit_button
  - mutation_action
applies_to_phase_profiles:
  - feature
  - hotfix
  - bugfix
strix_reference: VG-specific roam form-lifecycle lens
severity_default: warn
estimated_action_budget: 60
output_schema_version: 3
runtime: roam

# Task 26 / Task 36a additions:
recommended_worker_tier: sonnet
worker_complexity_score: 4
fallback_on_inconclusive: opus
min_actions_floor: 10
min_evidence_steps: 8
required_probe_kinds: [create_then_read, update_then_read, delete_then_read]
---

# Lens: Form Lifecycle (RCRURD)

## Mục đích

Drive a form through its **full Create-Read-Update-Delete lifecycle** and capture every observable signal. This is the canonical roam lens — most CRUD-bearing surfaces fit this pattern. Goal is NOT to assert correctness; goal is to **log every fact** so the commander can run coherence rules (R1-R8 in ROAM-RFC).

## Threat model

- **R1 silent_state_mismatch**: UI says "saved" but network returned 4xx/5xx
- **R2 toast_inconsistency**: toast says error but mutation succeeded server-side
- **R5 orphan_state**: Create returned 201 but new row missing from immediate list refresh
- **R7 delete_did_not_persist**: Delete returned 204 but GET still returns the row
- **R8 update_did_not_apply**: PATCH returned 200 but follow-up read shows stale value

These bugs are invisible to /vg:review (UI shape only) and to /vg:test (deterministic specs against pre-defined goals). Roam catches them by **comparing each step's pre-state, action, post-state, network truth, and follow-up read** as raw evidence.

## Action protocol (RCRURD sequence — DO NOT SKIP)

You execute this protocol against a SINGLE form surface. The brief specifies the URL, auth role, payload schema. You drive Playwright MCP, log every event to JSONL, never judge.

### Step 1 — Auth + navigate
- Navigate to surface URL (login first if not authed for the role specified)
- Capture: redirect URL, cookie status, console messages

### Step 2 — Read (empty / pre-existing list)
- Snapshot DOM
- Capture network: GET request to list endpoint (status, response body up to 50KB, duration)
- Note the entity IDs already present (if any) — store as `pre_existing_ids`
- Capture console (any error/warning at page load)

### Step 3 — Open create form
- Find and click "Create" / "New" / "+" button (selectors from brief)
- Snapshot form DOM after open
- Capture: modal state, form field list, default values, console errors
- If form opens in modal vs inline page, log the variant

### Step 4 — Fill form with valid payload from brief
- For each field in brief.payload, fill via `browser_fill_form` or `browser_type`
- Capture form state after each field (snapshot hash diff)
- Drain `window.__ws_frames` (if WS capture injected)

### Step 5 — Submit Create
- Click submit button (selector from brief)
- Capture network: full POST request body + response body (status, headers if redirect, duration)
- Capture: toast text + type (success/error/info), redirect URL change, modal close behavior
- Capture console (any uncaught errors)
- Drain WS frames

### Step 6 — Read after Create (verify visibility)
- Navigate back to list (or wait if auto-refresh)
- Snapshot DOM
- Capture network: GET list endpoint
- From response body, extract IDs → store as `post_create_ids`
- Diff vs `pre_existing_ids` — emit `new_id` event with the new entity ID(s)
- If no new ID found in list response, emit `precondition-missing` event but DO NOT skip remaining steps — try opening the entity by guessing ID from create response if possible

### Step 7 — Open the new entity (drill-down)
- Click the new row OR use direct route from create response
- Snapshot DOM (modal or detail page)
- Capture network: GET /api/{entity}/{id}
- Capture: form fields current values, console errors

### Step 8 — Update one field
- Pick first writable field from brief.payload, change to `<original>_updated`
- Click submit/save
- Capture network: full PATCH/PUT request body + response, status, duration
- Capture: toast, modal close behavior, redirect, console errors

### Step 9 — Read after Update
- Re-navigate or wait for refresh
- Snapshot DOM
- Capture network: GET /api/{entity}/{id}
- Read response body, find the updated field — log its current value
- Drain WS frames

### Step 10 — Delete the entity
- Find delete button/menu (selector from brief)
- Click delete
- If confirmation dialog appears, capture it, then click confirm (NEVER bail out — log even if dialog text seems destructive)
- Capture network: DELETE /api/{entity}/{id}, status, response body if any
- Capture: toast, redirect, modal close, console

### Step 11 — Read after Delete (verify removal)
- Navigate back to list
- Snapshot DOM
- Capture network: GET list endpoint
- Verify the entity ID is NOT in response body — log result either way
- Try direct GET /api/{entity}/{id} — capture status (expect 404, but log whatever you see)

### Step 12 — Sub-view discovery
- Throughout steps 3-10, if you see modal, drill-down route, or sub-section open, emit `spawn-child` event with sub-view URL/handle. Do NOT recurse yourself — let the commander spawn child task.

## Capture contract per step

Every step emits ONE event:

```json
{
  "ts": "ISO8601",
  "lens": "form-lifecycle",
  "surface": "<surface_id>",
  "step": "step5_submit_create",
  "action": {"tool": "browser_click", "selector": "[data-testid=submit-btn]"},
  "ui_before": {"snapshot_hash": "...", "toast": null, "url": "..."},
  "ui_after":  {"snapshot_hash": "...", "toast": "Tạo thành công", "url": "...", "modal_visible": false},
  "network": [
    {"url": "/api/invoices", "method": "POST", "status": 201, "req": {...}, "resp": {...}, "duration_ms": 234}
  ],
  "console": [],
  "ws_frames": []
}
```

## ⛔ HARD RULES (verbatim from roam protocol)

1. You DO NOT judge whether anything is a bug. Just log facts.
2. You DO NOT skip any RCRURD step, even if previous step seemed to fail.
3. You DO NOT stop early on errors. Log the error, continue to next step.
4. You DO NOT classify severity. The commander reads your log later.
5. You DO NOT add commentary. Output is JSONL only, one event per line.
6. If you observe a sub-view (modal, drilldown, child route) you didn't expect, emit `spawn-child` event with the URL/handle, then continue parent RCRURD.
7. If a Playwright MCP call fails (timeout, server error), log the failure as an event and continue. Do NOT retry.
8. Capture full network payloads (request body + response body) verbatim. Do NOT redact, summarize, or truncate. PII redaction happens in commander phase.
9. If a step's preconditions are not met (e.g., expected button missing), log a `precondition-missing` event and SKIP only that step's mutation; continue with the rest of RCRURD.
