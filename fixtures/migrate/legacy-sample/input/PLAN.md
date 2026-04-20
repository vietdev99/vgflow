# Plan — Phase X.Y

## Wave 1: Foundation

### Task 01: Set up storage layer
Implement persistent storage for items entity.

### Task 02: Create item handler
POST /api/items endpoint with validation.

### Task 03: Read item handler
GET /api/items + GET /api/items/:id endpoints.

## Wave 2: Mutations

### Task 04: Update item handler
PUT /api/items/:id endpoint with optimistic concurrency.

### Task 05: Delete item handler
DELETE /api/items/:id endpoint with soft-delete option.

### Task 06: List pagination
Add page/page_size query params to GET /api/items.

## Wave 3: UI

### Task 07: Item form component
Create form with validation feedback.

### Task 08: Item list page
Display paginated table with edit/delete actions.
