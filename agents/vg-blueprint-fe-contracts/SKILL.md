---
name: vg-blueprint-fe-contracts
description: Generate BLOCK 5 FE consumer contracts for each API endpoint (Task 38 Pass 2). Reads BE 4 blocks + UI-MAP + VIEW-COMPONENTS, emits 16-field FE contract per endpoint.
tools: Read, Bash, Grep
model: sonnet  # 2026-05-04 audit (Tier 2 Fix #109): explicit sonnet pin.
               # FE consumer contract generation = template-driven (16-field
               # schema per endpoint), reading BE 4 blocks + UI-MAP. Mechanical
               # synthesis, not designer-level architecture. Was implicit default;
               # sonnet ~5× cheaper than opus for this bounded transformation.
---

# vg-blueprint-fe-contracts (Pass 2)

You generate **BLOCK 5: FE consumer contract** for each endpoint declared
in `${PHASE_DIR}/API-CONTRACTS/<slug>.md`. Pass 1 (vg-blueprint-contracts)
already wrote BLOCKs 1–4 (BE: auth/middleware, Zod schemas, error responses,
test sample). You append BLOCK 5.

## Input artifacts

You will receive a delegation prompt with explicit `@${PATH}` references:
- `${PHASE_DIR}/API-CONTRACTS.md` (or `${PHASE_DIR}/API-CONTRACTS/index.md` + per-endpoint files)
- `${PHASE_DIR}/UI-MAP.md`
- `${PHASE_DIR}/VIEW-COMPONENTS.md`
- `${PHASE_DIR}/PLAN.md` (for context_refs / consumer hints)

## Output (return as JSON to orchestrator)

```json
{
  "endpoints": [
    {
      "slug": "post-api-sites",
      "block5_body": "export const PostSitesFEContract = { ...16 fields... } as const;"
    }
  ]
}
```

The orchestrator appends each `block5_body` to the matching
`API-CONTRACTS/<slug>.md` file under heading `## BLOCK 5: FE consumer contract`.

## BLOCK 5 schema (16 fields, ALL required)

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | always | Canonical, FE typed client imports verbatim |
| `consumers` | string[] | always | Glob patterns preferred (`apps/web/src/sites/**/*.tsx`); literal component names ok |
| `ui_states` | object | always | Keys: `loading`, `error`, `empty`, `success` (all 4) |
| `query_param_schema` | object | always | `{}` for endpoints with no query params |
| `invalidates` | string[] | always | Cache keys to invalidate post-mutation; `[]` for read-only endpoints |
| `optimistic` | boolean | always | FE update strategy |
| `toast_text` | object | always | `{ success, error_<status> }` keys |
| `navigation_post_action` | string \| null | always | Must be consistent with BE `Location` header |
| `auth_role_visibility` | string[] | always | Roles allowed to render UI; `[]` = public |
| `error_to_action_map` | object | always | HTTP status → FE action |
| `pagination_contract` | object \| null | matrix | Required NON-NULL for `GET` list endpoints (`{type: cursor\|offset, ...}`) |
| `debounce_ms` | number \| null | always | For search/filter only; null otherwise |
| `prefetch_triggers` | string[] | always | `[]` if none |
| `websocket_correlate` | string \| null | always | WS event topic that invalidates this query |
| `request_id_propagation` | boolean | always | FE must propagate response.request_id to follow-ups |
| `form_submission_idempotency_key` | string \| null | matrix | Required NON-NULL for `POST/PUT/PATCH` |

Per-method matrix (validator enforces):
- `GET <list>` (path has no `{id}` / `:id`) ⇒ `pagination_contract` non-null
- `POST/PUT/PATCH` ⇒ `form_submission_idempotency_key` non-null

## Field derivation guidance

- `url` ← `# <METHOD> <path>` heading of contract file (verbatim, no paraphrase)
- `consumers` ← grep VIEW-COMPONENTS.md + UI-MAP.md for component names referencing the endpoint slug; emit glob `apps/web/src/<resource>/**/*.tsx` if no specific components found
- `ui_states` ← read UI-MAP.md per-route entry; map `loading-skeleton` → `loading: 'spinner-with-skeleton'`, etc.
- `invalidates` ← BE 4-block analysis: which `GET` endpoints share resource path with this mutation
- `auth_role_visibility` ← BLOCK 1 `requires:` field
- `error_to_action_map` ← BLOCK 3 error responses; map 401→`navigate:/login`, 403→`modal:contact-admin`, 422→`form-error-banner`, 429→`show-retry-after`

## Anti-laziness rules

- DO NOT invent URLs — copy verbatim from BLOCK 1 heading
- DO NOT skip fields — all 16 are required (use `null` / `[]` / `false` where not applicable)
- DO NOT paraphrase BLOCK 1 `requires:` into `auth_role_visibility` (must match exactly)
- If UI-MAP.md lacks a route entry for an endpoint's consumer page, emit empty `consumers: []` + flag in return JSON `notes` field
