# Context — Phase X.Y (legacy GSD format)

## D-01: Use HTTP REST API for items CRUD
Standard RESTful conventions: POST/GET/PUT/DELETE on `/api/items`. Stateless server.

## D-02: Validate request body với schema
Reject malformed input with 400 + error array. Schema defined per endpoint.

## D-03: Single-tenant data model (initial scope)
No multi-tenant isolation in this phase. All items in shared collection.

## D-04: Pagination via query params
List endpoint uses `?page=1&page_size=20`. Max page_size 100.

## D-05: Form-based UI for create/edit
Browser form sends JSON to API. Validation feedback inline per field.
