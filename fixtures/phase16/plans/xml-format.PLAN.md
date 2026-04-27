# Plan — Phase fixture (Phase 16 D-02 XML + frontmatter format)

<task id="1">
---
acceptance:
  - "POST /api/sites returns 201 with created site.id"
  - "Validator allows valid domain rejects malformed URL"
edge_cases:
  - "Domain with > 4 subdomain levels rejected with 400"
  - "Concurrent POST same domain returns 409 DUPLICATE_DOMAIN"
decision_refs: ["P15.D-04", "P15.D-05"]
design_refs: []
body_max_lines: 200
---

# Description

Implement the create-site handler.
Body validates against PostApiSitesRequest (Block 2).
Auth: requireAuth + requireRole('publisher') from Block 1.

<file-path>apps/api/src/sites/sites.controller.ts</file-path>
<contract-ref>API-CONTRACTS.md#post-api-sites lines 10-50</contract-ref>
<goals-covered>[G-01]</goals-covered>
</task>

<task id="2">
---
acceptance:
  - "Sites table renders with at least one row"
  - "Filter by status updates URL ?status=active"
  - "Pagination next/prev navigates page=N param"
edge_cases:
  - "Empty result shows empty-state component"
  - "Filter with malformed status value rejected"
decision_refs: ["P15.D-12c"]
design_refs: ["sites-list.default"]
---

# Description

Render sites list with status filter + offset pagination.
Use vg-codegen-interactive matrix for test rigor (P15 D-16).

<file-path>apps/web/src/sites/SitesList.tsx</file-path>
<goals-covered>[G-02, G-03]</goals-covered>
</task>

<task id="3">
---
acceptance:
  - "Detail view renders site name + domain + status"
edge_cases:
  - "404 when site_id not found"
decision_refs: []
design_refs: []
---

Detail view for a single site. Read-only.

<file-path>apps/web/src/sites/SiteDetail.tsx</file-path>
<goals-covered>[G-04]</goals-covered>
</task>
