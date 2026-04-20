# Context — Phase X.Y (VG enriched format)

## D-01: Use HTTP REST API for items CRUD
Standard RESTful conventions: POST/GET/PUT/DELETE on `/api/items`. Stateless server.

**Endpoints:**
- POST /api/items (create)
- GET /api/items (list)
- GET /api/items/:id (read)
- PUT /api/items/:id (update)
- DELETE /api/items/:id (delete)

**UI Components:**
- ItemForm (create + edit)
- ItemListTable
- ItemDeleteDialog

**Test Scenarios:**
- Create with valid body → 201 + new item returned
- Read by id → 200 + item data
- Update → 200 + new values reflected on subsequent GET
- Delete → 204 + subsequent GET returns 404

## D-02: Validate request body với schema
Reject malformed input with 400 + error array. Schema defined per endpoint.

**Endpoints:**
- POST /api/items (validation applied)
- PUT /api/items/:id (validation applied)

**UI Components:**
- ItemForm (inline error display per field)

**Test Scenarios:**
- Missing required field → 400 + `errors: [{field, message}]`
- Invalid type (number expected, string sent) → 400
- Extra unknown field → 400 (strict mode)

## D-03: Single-tenant data model (initial scope)
No multi-tenant isolation in this phase. All items in shared collection.

**Endpoints:** none (data model decision)

**UI Components:** none

**Test Scenarios:**
- All authenticated users see same items list
- No tenant_id field in items collection
- Shared index on id only (no compound tenant index)

## D-04: Pagination via query params
List endpoint uses `?page=1&page_size=20`. Max page_size 100.

**Endpoints:**
- GET /api/items?page=N&page_size=M

**UI Components:**
- ItemListTable (pagination controls)

**Test Scenarios:**
- Default page=1, page_size=20 returns first 20 items
- page_size > 100 → clamped to 100
- page beyond total → returns empty array, total field intact

## D-05: Form-based UI for create/edit
Browser form sends JSON to API. Validation feedback inline per field.

**Endpoints:**
- POST /api/items (consumed by ItemForm)
- PUT /api/items/:id (consumed by ItemForm in edit mode)

**UI Components:**
- ItemForm (form layout + submit + validation display)

**Test Scenarios:**
- Submit valid form → API call + success toast + redirect
- Submit invalid → inline errors per field, no API call
- Edit mode pre-fills form with existing data
