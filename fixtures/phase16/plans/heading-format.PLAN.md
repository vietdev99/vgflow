# Plan — Phase fixture (heading format, legacy)

## Task 1: Add POST /api/sites endpoint

<file-path>apps/api/src/sites/sites.controller.ts</file-path>
<edits-endpoint>POST /api/sites</edits-endpoint>
<goals-covered>[G-01]</goals-covered>
<contract-ref>API-CONTRACTS.md#post-api-sites lines 10-50</contract-ref>

Implement the create-site handler.
Body validates against PostApiSitesRequest (see contract Block 2).
Auth: requireAuth + requireRole('publisher') from contract Block 1.

## Task 2: Add SitesList view

<file-path>apps/web/src/sites/SitesList.tsx</file-path>
<goals-covered>[G-02, G-03]</goals-covered>
<design-ref>sites-list.default</design-ref>

Render sites list with filter by status + pagination.

## Task 3: Add SiteDetail view

<file-path>apps/web/src/sites/SiteDetail.tsx</file-path>
<goals-covered>[G-04]</goals-covered>

Detail view for a single site. Read-only.
