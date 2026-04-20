# Test Goals — Phase X.Y (VG enriched, with Persistence + Surface)

## Goals

#### G-01: Create item returns 201 with new item data
**Covers:** D-01, D-02
**Priority:** critical
**Surface:** api
**Success criteria:**
- POST /api/items với valid body returns 201
- Response includes id + all submitted fields
- Database has new row matching submitted data
**Mutation evidence:**
- Items collection count +1, new row matches request body
**Persistence check:**
- Pre-submit: count items via GET /api/items?page_size=1 → record total
- Action: POST /api/items với body
- Post-submit wait: 201 response received
- Refresh: re-call GET /api/items?page_size=1
- Re-read: parse total field
- Assert: post total = pre total + 1
**Implemented by:** Task 02

#### G-02: Invalid create returns 400 with error array
**Covers:** D-02
**Priority:** important
**Surface:** api
**Success criteria:**
- POST với missing required field returns 400
- Response body contains `errors: [{field, message}]`
**Mutation evidence:**
- N/A (no state change on validation failure)
**Implemented by:** Task 02

#### G-03: List endpoint returns paginated data
**Covers:** D-04
**Priority:** important
**Surface:** api
**Success criteria:**
- GET /api/items returns `{data: [], total, page, page_size}`
- Default page_size = 20
**Mutation evidence:**
- N/A (read-only)
**Implemented by:** Task 03, Task 06

#### G-04: Update persists changes
**Covers:** D-01
**Priority:** critical
**Surface:** api
**Success criteria:**
- PUT /api/items/:id với new name updates database
- Subsequent GET returns updated values
**Mutation evidence:**
- Item row updated, name field changed to new value
**Persistence check:**
- Pre-submit: GET /api/items/:id → record current name
- Action: PUT /api/items/:id với new name
- Post-submit wait: 200 response
- Refresh: re-call GET /api/items/:id
- Re-read: parse name field
- Assert: post name = new value AND != pre name
**Implemented by:** Task 04

#### G-05: Delete removes item
**Covers:** D-01
**Priority:** critical
**Surface:** api
**Success criteria:**
- DELETE /api/items/:id removes row
- Subsequent GET returns 404
**Mutation evidence:**
- Items collection count -1
**Persistence check:**
- Pre-submit: GET /api/items?page_size=1 → record total + GET /api/items/:id → 200
- Action: DELETE /api/items/:id
- Post-submit wait: 204 response
- Refresh: re-call GET /api/items?page_size=1 + GET /api/items/:id
- Re-read: parse total + status
- Assert: post total = pre total - 1 AND GET /:id returns 404
**Implemented by:** Task 05
