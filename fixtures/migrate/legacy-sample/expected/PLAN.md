# Plan — Phase X.Y (VG attributed)

## Wave 1: Foundation

### Task 01: Set up storage layer
<file-path>src/storage/items.repository.ts</file-path>
<goals-covered>no-goal-impact</goals-covered>

Implement persistent storage for items entity.

### Task 02: Create item handler
<file-path>src/api/routes/items.create.ts</file-path>
<contract-ref>API-CONTRACTS.md#post-api-items lines 1-40</contract-ref>
<goals-covered>G-01, G-02</goals-covered>

POST /api/items endpoint với validation.

### Task 03: Read item handler
<file-path>src/api/routes/items.read.ts</file-path>
<contract-ref>API-CONTRACTS.md#get-api-items lines 41-80</contract-ref>
<goals-covered>G-03</goals-covered>

GET /api/items + GET /api/items/:id endpoints.

## Wave 2: Mutations

### Task 04: Update item handler
<file-path>src/api/routes/items.update.ts</file-path>
<contract-ref>API-CONTRACTS.md#put-api-items-id lines 81-120</contract-ref>
<goals-covered>G-04</goals-covered>

PUT /api/items/:id endpoint với optimistic concurrency.

### Task 05: Delete item handler
<file-path>src/api/routes/items.delete.ts</file-path>
<contract-ref>API-CONTRACTS.md#delete-api-items-id lines 121-160</contract-ref>
<goals-covered>G-05</goals-covered>

DELETE /api/items/:id endpoint với soft-delete option.

### Task 06: List pagination
<file-path>src/api/routes/items.list.ts</file-path>
<contract-ref>API-CONTRACTS.md#get-api-items lines 41-80</contract-ref>
<goals-covered>G-03</goals-covered>

Add page/page_size query params to GET /api/items.

## Wave 3: UI

### Task 07: Item form component
<file-path>src/components/ItemForm.tsx</file-path>
<goals-covered>no-goal-impact</goals-covered>

Create form với validation feedback.

### Task 08: Item list page
<file-path>src/pages/ItemsList.tsx</file-path>
<goals-covered>no-goal-impact</goals-covered>

Display paginated table with edit/delete actions.
