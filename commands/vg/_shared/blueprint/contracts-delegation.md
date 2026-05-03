# blueprint contracts delegation contract (vg-blueprint-contracts subagent)

This file contains the prompt template the main agent passes to
`Agent(subagent_type="vg-blueprint-contracts", prompt=...)`.

Read `contracts-overview.md` for orchestration order. This file describes
ONLY the spawn payload + return contract.

---

## Input contract (JSON envelope)

```json
{
  "phase_dir": "${PHASE_DIR}",
  "phase_number": "${PHASE_NUMBER}",
  "plan_path": "${PHASE_DIR}/PLAN.md",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "interface_standards_md": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_standards_json": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "ui_spec_path": "${PHASE_DIR}/UI-SPEC.md",
  "ui_map_path": "${PHASE_DIR}/UI-MAP.md",
  "view_components_path": "${PHASE_DIR}/VIEW-COMPONENTS.md",
  "must_cite_bindings": [
    "PLAN:tasks",
    "INTERFACE-STANDARDS:error-shape",
    "INTERFACE-STANDARDS:response-envelope"
  ],
  "config": {
    "contract_format_type": "${CONTRACT_TYPE}",
    "code_patterns_api_routes": "${CONFIG_CODE_PATTERNS_API_ROUTES}",
    "code_patterns_web_pages": "${CONFIG_CODE_PATTERNS_WEB_PAGES}",
    "infra_deps_services": "${CONFIG_INFRA_DEPS_SERVICES}",
    "url_param_naming": "${CONFIG_UI_STATE_URL_PARAM_NAMING:-kebab}",
    "url_array_format": "${CONFIG_UI_STATE_ARRAY_FORMAT:-csv}"
  }
}
```

---

## Prompt template (substitute then pass as `prompt`)

````
You are vg-blueprint-contracts. Generate API-CONTRACTS.md, TEST-GOALS.md,
and CRUD-SURFACES.md for phase ${PHASE_NUMBER}. Return JSON envelope. Do
NOT browse files outside input. Do NOT ask user — input is the contract.

<inputs>
@${PHASE_DIR}/CONTEXT.md
@${PHASE_DIR}/INTERFACE-STANDARDS.md
@${PHASE_DIR}/UI-SPEC.md (if exists)
@${PHASE_DIR}/UI-MAP.md (if exists)
@${PHASE_DIR}/VIEW-COMPONENTS.md (if exists)

# PLAN — load via vg-load helper (3-layer split aware). Prefer slim
# index for cross-task scan, then per-task pulls for the endpoints you
# need to ground each contract block:
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact plan --index
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact plan --task NN
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact plan --wave N
# Last-resort full read (legacy):
#   bash scripts/vg-load.sh --phase ${PHASE_NUMBER} --artifact plan --full
</inputs>

<config>
contract_format: ${CONTRACT_TYPE}
url_param_naming: ${CONFIG_UI_STATE_URL_PARAM_NAMING:-kebab}
array_format: ${CONFIG_UI_STATE_ARRAY_FORMAT:-csv}
</config>

# Part 1 — API-CONTRACTS.md

Generate `${PHASE_DIR}/API-CONTRACTS.md`. Strict 4-block format per endpoint.

**Process:**
1. Grep existing schemas (match contract_format type)
2. Grep HTML/JSX forms and tables (if web_pages path exists)
3. Extract endpoints from CONTEXT.md decisions, supporting BOTH formats:
   - VG-native bullet (from /vg:scope):
     `- POST /api/v1/sites (auth: publisher, purpose: create site)`
     Regex: `^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - Legacy header: `### POST /api/v1/sites`
     Regex: `^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
4. Cross-reference endpoints with CONTEXT decisions
5. Draft contract for each endpoint without existing schema

**STRICT 4-BLOCK FORMAT per endpoint** (zod_code_block example):

```markdown
### POST /api/sites

**Purpose:** Create new site (publisher role)

```typescript
// === BLOCK 1: Auth + middleware (COPY VERBATIM to route handler) ===
export const postSitesAuth = [requireAuth(), requireRole('publisher'), rateLimit(30)];
```

```typescript
// === BLOCK 2: Request/Response schemas (COPY VERBATIM) ===
export const PostApiSitesRequest = z.object({
  domain: z.string().url().max(255),
  name: z.string().min(1).max(100),
  categoryId: z.string().uuid(),
});
export type PostApiSitesRequest = z.infer<typeof PostApiSitesRequest>;

export const PostApiSitesResponse = z.object({
  id: z.string().uuid(),
  domain: z.string(),
  status: z.enum(['pending', 'active', 'rejected']),
  createdAt: z.string().datetime(),
});
export type PostApiSitesResponse = z.infer<typeof PostApiSitesResponse>;
```

```typescript
// === BLOCK 3: Error responses (COPY VERBATIM to error handler) ===
// FE reads error.user_message || error.message for toast.
export const PostSitesErrors = {
  400: { ok: false, error: { code: 'VALIDATION_FAILED', message: 'Invalid site data', field_errors: {} } },
  401: { ok: false, error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } },
  403: { ok: false, error: { code: 'FORBIDDEN', message: 'Publisher role required', user_message: 'Publisher role required' } },
  409: { ok: false, error: { code: 'DUPLICATE_DOMAIN', message: 'Domain already registered' } },
} as const;
```

```typescript
// === BLOCK 4: Valid test sample (test.md step 5b-2 idempotency) ===
// Do NOT copy into app code.
export const PostSitesSample = {
  domain: "https://test-idem.example.com",
  name: "Idempotency Test Site",
  categoryId: "00000000-0000-0000-0000-000000000001",
} as const;
```

**Mutation evidence:** sites collection count +1
**Cross-ref tasks:** Task {N} (BE), Task {M} (FE)
```

**Block format per type:**
- `zod_code_block` → typescript with z.object, requireRole, error map, sample const
- `openapi_yaml` → yaml with security schemes, schemas, error responses, examples
- `typescript_interface` → typescript interfaces + error types + sample const
- `pydantic_model` → python BaseModel + FastAPI Depends + HTTPException + sample dict

**Block 4 rules:**
1. Each endpoint MUST have Block 4 with valid sample matching Block 2 schema.
2. Use realistic values: valid email, valid UUID, valid URL, ISO date.
3. Zod/Pydantic validation of Block 4 must pass against Block 2.
4. Block 4 consumed by test.md step 5b-2 — NOT copied to app code.
5. Sample naming: `{Method}{Resource}Sample` (e.g., `PostSitesSample`).
6. Mark `as const` (TS) or freeze (Python) to prevent mutation.
7. GET endpoints do NOT need Block 4.
8. For path params: comment with sample path
   `// path: /api/sites/00000000-0000-0000-0000-000000000001`

**Error response shape** is phase-wide consistent. Use envelope from
INTERFACE-STANDARDS.md `error-shape`:
`{ ok:false, error:{ code, message, user_message?, details?, field_errors?, request_id? } }`.
FE reads `response.data.error.user_message || response.data.error.message`
for toast — never `response.statusText` or HTTP code text.

# Part 2 — TEST-GOALS.md

Generate `${PHASE_DIR}/TEST-GOALS.md` from CONTEXT.md decisions + API-CONTRACTS.md endpoints.

For each decision (`P{phase}.D-XX`, or legacy `D-XX`), produce 1+ goals.
Each goal:
- Has success criteria (what user can do, what system shows)
- Has mutation evidence (for create/update/delete: API response + UI change)
- Has dependencies (which goals must pass first)
- Has priority (critical / important / nice-to-have)

**Rules:**

1. Every decision MUST have ≥1 goal.
2. Goals describe WHAT to verify, not HOW (no selectors, no exact clicks).
3. Mutation evidence specific: "POST returns 201 AND row count +1" not "data changes".
3b. **Persistence check field MANDATORY for mutation goals.** Format:
    ```
    **Persistence check:**
    - Pre-submit: read <field/row/state> value (e.g., role="editor")
    - Action: <what user does> (fill dropdown role="admin", click Save)
    - Post-submit wait: API 2xx + toast
    - Refresh: page.reload() OR navigate away + back
    - Re-read: <where to re-read> (re-open edit modal)
    - Assert: <field> = <new value> AND != <pre value>
    ```
    Why: "ghost save" bug class — toast + 200 + console clean BUT refresh shows
    old data. Only refresh-then-read detects backend silent skip / client
    optimistic rollback. GET-only goals don't need this.
4. Dependencies reference goal IDs (G-XX).
5. Priority assignment (deterministic, evaluate in order):
   a. Endpoints matching config `routing.critical_goal_domains`
      (auth, billing, auction, payout, compliance) → critical
   b. Auth/session/token goals (login, logout, JWT, session) → critical
   c. Data mutation goals (POST/PUT/DELETE) → important (upgrade per a/b)
   d. Read-only goals (GET endpoints, list/detail) → important (default)
   e. Cosmetic/display goals (formatting, sorting, empty states) → nice-to-have
6. Infrastructure dep annotation:
   If goal requires services in config.infra_deps.services NOT in this phase's
   build scope, add `**Infra deps:** [clickhouse, kafka, pixel_server]`.
   Review Phase 4 auto-classifies goals with unmet deps as INFRA_PENDING.
   In-scope services = explicitly provisioned in PLAN tasks.
7. **URL state interactive_controls (MANDATORY for list/table/grid views):**
   If goal has `surface: ui` AND main_steps OR title mentions list/table/grid
   (or trigger is `GET /<plural-noun>`), MUST declare `interactive_controls`
   frontmatter block. Dashboard UX baseline (executor R7) — list view
   filter/sort/page/search state MUST sync to URL search params so
   refresh/share-link/back-forward work.

   Auto-populate based on context:
   - main_steps mention "filter by X" or trigger has `?status=` → emit `filters:`
   - main_steps mention "page through" or list returns >20 rows → emit `pagination:`
   - main_steps mention "search by name" or has search input → emit `search:`
   - main_steps mention "sort by X" or table has sortable cols → emit `sort:`

   Default url_param_naming from `config.ui_state_conventions.url_param_naming`
   (default `kebab` → `?sort-by=`, `?page-size=`).
   Default array_format from `config.ui_state_conventions.array_format`
   (default `csv` → `?tags=a,b,c`).

   Example for campaign list goal:
   ```yaml
   interactive_controls:
     url_sync: true
     filters:
       - name: status
         values: [active, paused, completed, archived]
         url_param: status
         assertion: "rows.status all match selected; URL ?status=active synced; reload preserves"
     pagination:
       page_size: 20
       url_param_page: page
       ui_pattern: "first-prev-numbered-window-next-last"  # MANDATORY locked
       window_radius: 5
       show_total_records: true
       show_total_pages: true
       assertion: "page2 first row != page1; URL ?page=2; reload preserves; UI shows << < numbered-window > >> + Showing X-Y of Z + Page N of M"
     search:
       url_param: q
       debounce_ms: 300
       assertion: "type → debounce → URL ?q=... synced; rows contain query (case-insensitive)"
     sort:
       columns: [created_at, name, status]
       url_param_field: sort
       url_param_dir: dir
       assertion: "click header toggles asc↔desc; URL synced; ORDER BY holds"
   ```

   Override (rare): if state genuinely local-only (modal-internal filter,
   transient drag-sort), declare `url_sync: false` + `url_sync_waive_reason: "<why>"`.
   Validator at /vg:review phase 2.7 logs soft OD debt.

**Output format:**

```markdown
# Test Goals — Phase {PHASE}

Generated from: CONTEXT.md decisions + API-CONTRACTS.md
Total: {N} goals ({critical} critical, {important} important, {nice} nice-to-have)

## Goal G-00: Authentication (F-06 or P{phase}.D-XX)
**Priority:** critical
**Success criteria:**
- User can log in with valid credentials
- Invalid credentials show error message
- Session persists across page navigation
**Mutation evidence:**
- Login: POST /api/auth/login returns 200 + token
**Dependencies:** none (root)
**Infra deps:** none

## Goal G-01: {Feature} (P{phase}.D-XX or F-XX)
**Priority:** critical | important | nice-to-have
**Success criteria:**
- [what user can do]
- [what system shows]
- [error handling]
**Mutation evidence:**
- [Create: POST /api/X returns 201, row +1]
- [Update: PUT /api/X/:id returns 200, row reflects change]
**Persistence check:**
- Pre-submit: read <field>
- Action: <what user does>
- Post-submit wait: API 2xx + toast
- Refresh: page.reload()
- Re-read: <where>
- Assert: <field> = <new> AND != <pre>
**Dependencies:** G-00

## Decision Coverage
| Decision | Goal IDs | Priority |
|---|---|---|
| D-01 | G-01, G-02 | critical |

Coverage: {covered}/{total} decisions → {%}
```

# Part 3 — CRUD-SURFACES.md

Write `${PHASE_DIR}/CRUD-SURFACES.md` using template
`commands/vg/_shared/templates/CRUD-SURFACES-template.md`.

Required structure (top-level JSON fenced block):
- `version: "1"`
- `resources[]` — each has `operations`, `base`, `platforms`
- `base` — cross-platform: roles, business_flow, security, abuse, performance
- `platforms.web` — list/form/delete: heading, description, filter/search/sort/
  pagination URL state, table cols/actions, loading/empty/error states, form
  validation, duplicate-submit guard, delete confirmation
- `platforms.mobile` — deep link state, pull-to-refresh OR load-more/infinite-scroll,
  44px tap target, keyboard avoidance, native picker, offline/network states,
  confirm sheet
- `platforms.backend` — pagination max size, filter/sort allowlist, stable
  default sort, invalid query errors, object authz, field allowlist/mass-assignment,
  idempotency, rate-limit, audit log

If phase has NO CRUD/resource behavior:
```json
{
  "version": "1",
  "generated_from": ["CONTEXT.md", "API-CONTRACTS.md", "TEST-GOALS.md", "PLAN.md"],
  "no_crud_reason": "Phase only changes infrastructure/docs/tooling; no user resource CRUD",
  "resources": []
}
```

Do NOT apply web table rules to mobile screens. Use `base + platform overlay`
so each profile gets only the checks that fit.

# Return JSON envelope

After all 3 files written, compute sha256 and return:

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape", "INTERFACE-STANDARDS:response-envelope"],
  "warnings": []
}
```

`codex_proposal_path` and `codex_delta_path` are populated by main agent
in STEP 4.4 (separate Codex CLI spawn). Do NOT generate these yourself.
````

---

## Output (subagent returns)

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "codex_proposal_path": "${PHASE_DIR}/TEST-GOALS.codex-proposal.md",
  "codex_delta_path": "${PHASE_DIR}/TEST-GOALS.codex-delta.md",
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape", ...],
  "warnings": []
}
```

`codex_*` paths populated by main agent (STEP 4.4 in overview).

---

## Failure modes

| Error JSON | Cause | Action |
|---|---|---|
| `{"error":"missing_input","field":"<name>"}` | Required input missing | Verify file; re-spawn |
| `{"error":"contract_format_unsupported","format":"X"}` | Format not implemented | Manual override or fix config |
| `{"error":"r3b_persistence_missing","goals":[...]}` | Mutation goals without Persistence check | Re-spawn with explicit instruction |
| `{"error":"binding_unmet","missing":[...]}` | Required binding citation absent | Re-spawn with explicit binding |

Retry up to 2 times, then escalate via `AskUserQuestion` (Layer 3).
