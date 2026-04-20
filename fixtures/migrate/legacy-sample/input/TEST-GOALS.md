# Test Goals — Phase X.Y

## Goals

#### G-01: Create item returns 201 with new item data
**Covers:** D-01, D-02
**Priority:** critical
**Success criteria:**
- POST /api/items với valid body returns 201
- Response includes id + all submitted fields
- Database has new row matching submitted data
**Mutation evidence:**
- Items collection count +1, new row matches request body

#### G-02: Invalid create returns 400 with error array
**Covers:** D-02
**Priority:** important
**Success criteria:**
- POST với missing required field returns 400
- Response body contains `errors: [{field, message}]`
**Mutation evidence:**
- N/A

#### G-03: List endpoint returns paginated data
**Covers:** D-04
**Priority:** important
**Success criteria:**
- GET /api/items returns `{data: [], total, page, page_size}`
- Default page_size = 20
**Mutation evidence:**
- N/A

#### G-04: Update persists changes
**Covers:** D-01
**Priority:** critical
**Success criteria:**
- PUT /api/items/:id với new name updates database
- Subsequent GET returns updated values
**Mutation evidence:**
- Item row updated, name field changed

#### G-05: Delete removes item
**Covers:** D-01
**Priority:** critical
**Success criteria:**
- DELETE /api/items/:id removes row
- Subsequent GET returns 404
**Mutation evidence:**
- Items collection count -1
