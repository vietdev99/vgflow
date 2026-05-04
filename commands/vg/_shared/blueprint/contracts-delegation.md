# blueprint contracts delegation contract (vg-blueprint-contracts subagent)

<!-- # Exception: contract document, not step ref — H1/HARD-GATE not required.
     This ref describes a JSON envelope + prompt template + return contract
     for the `vg-blueprint-contracts` subagent. It has no `step-active` /
     `mark-step` lifecycle of its own — `contracts-overview.md` STEP 4 owns
     those. The reviewer audit (B1/B2 FAIL) flagged the missing
     `# blueprint <name> (STEP N)` H1 + top HARD-GATE; both are intentionally
     absent because this file is a contract, not an executable step body. -->

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
3c. **Read-after-write invariant (REQUIRED for goal_type: mutation, Codex GPT-5.5 review 2026-05-03):**
    Append a fenced YAML block declaring the structured invariant — single
    source of truth consumed by review (Task 23) + codegen (Task 24).
    Schema: `schemas/rcrurd-invariant.schema.yaml`. Example:

    ````yaml-rcrurd
    goal_type: mutation
    read_after_write_invariant:
      write:
        method: PATCH
        endpoint: /api/users/{userId}/roles
      read:
        method: GET
        endpoint: /api/users/{userId}
        cache_policy: no_store
        settle: {mode: immediate}
      assert:
        - path: $.roles[*].name
          op: contains
          value_from: action.new_role
      side_effects:
        - layer: audit_log
          path: $.events[*].type
          op: contains
          value_from: literal:role_granted
    ````

    `cache_policy: no_store` — read MUST bypass HTTP cache + CDN (default for
    role/permission/billing). `settle.mode: immediate` is the read-your-writes
    default; `poll`/`wait_event` REQUIRE explicit `timeout_ms`. `side_effects[]`
    covers audit log, effective permission, tenant identity, auth cache —
    each side-effect entry needs `layer:` label.

    Mutation goals WITHOUT this structured block fail Rule 3b extended →
    blueprint BLOCKED. The unstructured **Persistence check:** prose still
    required for human readability, but the YAML block is the machine contract.
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

**HARD-GATE — schema strictness (closes review-2 dogfood block where 225
"crud_surface_missing_field" violations fired because base/platforms had
empty `{}` sub-objects):**

Empty dicts (`"business_flow": {}`) are treated as MISSING by validator's
`_truthy()` check. Every required sub-field MUST contain non-empty
content. If a control is intentionally absent for a resource, write
`"none: <reason>"` (string, not `{}`).

Required structure (top-level JSON fenced block):

```json
{
  "version": "1",
  "generated_from": [...],
  "resources": [
    {
      "name": "<resource_name>",
      "domain_owner": "<team or domain>",
      "operations": ["list", "detail", "create", "update", "delete"],
      "base": {
        "roles": ["admin", "merchant", ...],
        "business_flow": {
          "lifecycle_states": ["draft", "active", "archived"],
          "entry_points": ["admin list", "admin detail"],
          "invariants": [
            "<rule 1: e.g., archived → read-only>",
            "<rule 2>"
          ]
        },
        "security": {
          "object_auth": "<e.g., 'tenant_id from session, scope=admin'>",
          "field_auth": "<e.g., 'admins can edit pricing; merchants read-only'>",
          "rate_limit": "<e.g., '60/min/admin' or 'none: trusted internal only'>"
        },
        "abuse": {
          "enumeration_guard": "<e.g., 'cursor-based pagination' or 'none: list publicly indexable'>",
          "replay_guard": "<e.g., 'idempotency key on create' or 'none: read-only'>"
        },
        "performance": {
          "api_p95_ms": <integer, e.g., 500>
        },
        "delete_policy": {  // REQUIRED only if 'delete' in operations
          "confirm": "<e.g., 'modal with type-name confirmation'>",
          "reversible_policy": "<e.g., 'soft-delete via status flag, undeletable after 30d'>",
          "audit_log": true
        }
      },
      "platforms": {
        "backend": {  // REQUIRED for backend phases
          "list_endpoint": {
            "path": "/admin/<resource>",
            "pagination": {"max_page_size": 100, "default_page_size": 20},
            "filter_sort_allowlist": ["created_at", "name", "status"],
            "stable_default_sort": "-created_at",
            "invalid_query_behavior": "400 with field-level error"
          },
          "mutation": {
            "paths": ["POST /admin/<resource>", "PATCH /admin/<resource>/:id", "DELETE /admin/<resource>/:id"],
            "validation_4xx": "zod schema, return field-level errors",
            "object_authz": "tenant_id check + RBAC role check",
            "mass_assignment_guard": "explicit field allowlist (no spread input)",
            "idempotency": "<e.g., 'idempotency-key header on POST' or 'none: PATCH is idempotent by design'>",
            "audit_log": true
          }
        },
        "web": {  // REQUIRED if profile has FE
          "list": { "route": "...", "heading": "...", "description": "...", "states": [...], "data_controls": {...}, "row_actions": [...] },
          "form": { ... },
          "delete": { ... }
        },
        "mobile": { ... }  // REQUIRED if mobile-* profile
      }
    }
  ]
}
```

**Self-validation (RECOMMENDED before return):** run
`python3 .claude/scripts/validators/verify-crud-surface-contract.py --phase ${PHASE_NUMBER}`
locally; if any `crud_surface_missing_field` evidence fires, fill the
specific paths the validator names rather than returning incomplete output.

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

# Part 4 — EDGE-CASES.md + per-goal split (P1 v2.49+)

For each goal in `TEST-GOALS/G-*.md`, generate edge case variants. Skip if
phase has `no_crud_reason` (CRUD-SURFACES.resources empty).

**Inputs:**
- `${PHASE_DIR}/TEST-GOALS/G-*.md` — every goal needs analysis
- `.claude/commands/vg/_shared/templates/edge-cases-${PROFILE}.md` — taxonomy
  template per profile (web-fullstack, web-frontend-only, web-backend-only,
  mobile, cli-tool, library)
- `${PHASE_DIR}/CRUD-SURFACES.md` — resource × operation matrix for context

**Outputs (3-layer split, mirrors API-CONTRACTS / TEST-GOALS pattern):**

Layer 1 (per-goal, primary):
```
${PHASE_DIR}/EDGE-CASES/G-NN.md
```

Layer 2 (TOC):
```
${PHASE_DIR}/EDGE-CASES/index.md
```

Layer 3 (legacy concat):
```
${PHASE_DIR}/EDGE-CASES.md
```

**Per-goal generation (G-NN.md):**

For each goal, choose **3-10 variants** từ template categories. Variant
budget guidance:
- Mutation goal (POST/PATCH/DELETE) → 5-10 variants
- Read-only goal (GET) → 3-5 variants
- Compute-only goal (no persistence) → 2-4 variants
- Trivial (health-check, ping) → 0 variants — explicit skip header

**HARD-GATE — variant_id format strictness:**
- Format: `<goal_id>-<category_letter><N>`
- Categories per profile (see template header for full mapping):
  - web-fullstack/backend: b=boundary, s=state, a=auth, c=concurrency,
    p=pagination, i=idempotency, t=time, r=resources, e=error_propagation,
    d=data_validity
  - web-frontend-only: r=render, s=state, n=network, b=browser, i=input,
    m=modal, f=form, c=component
  - mobile-*: p=permission, l=lifecycle, n=network, d=device, x=notification
  - cli-tool: a=arg, s=stdin, e=env, t=tty, x=exit-code
  - library: a=api, t=threading, l=lifecycle, c=compat
- Examples: `G-04-b1`, `G-04-a2`, `G-12-c1`

**Output format per goal (G-NN.md):**

```markdown
# Edge Cases — G-NN: <goal title>

**Goal source**: ${PHASE_DIR}/TEST-GOALS/G-NN.md
**Profile**: ${PROFILE}
**Skipped categories**: [<list category numbers + reason>]

## <Category Name>
| variant_id | input/scenario | expected_outcome | priority |
|---|---|---|---|
| G-NN-c1 | ... | ... | critical/high/medium/low |
```

**Layer 2 index (EDGE-CASES/index.md):**

```markdown
# Edge Cases — Phase ${PHASE_NUMBER} (Index)

**Profile**: ${PROFILE}
**Template**: edge-cases-${PROFILE}.md
**Total variants**: <N> across <M> goals

| Goal | Title | Variants | Critical | High | Med | Low |
|---|---|---|---|---|---|---|
| [G-04](./G-04.md) | <title> | 6 | 3 | 2 | 1 | 0 |
```

**Layer 3 flat (EDGE-CASES.md):**

```markdown
<!-- vg-binding: TEST-GOALS:goals -->
<!-- vg-binding: CRUD-SURFACES:resources -->
<!-- vg-binding: profile:${PROFILE} -->

# Edge Cases — Phase ${PHASE_NUMBER}

(index content + all per-goal content concatenated)
```

If phase has `no_crud_reason`:
```json
{
  "skipped": true,
  "reason": "phase has no CRUD resources"
}
```
And EDGE-CASES.md = single line: `# Edge Cases — Phase ${PHASE_NUMBER}\n\nSkipped: <reason>`.

# Return JSON envelope (Part 4 only — no lens-walk fields)

After all 3 files written, compute sha256 and return (shape MUST match
`agents/vg-blueprint-contracts/SKILL.md` "Example return"):

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_index_path": "${PHASE_DIR}/API-CONTRACTS/index.md",
  "api_contracts_sub_files": ["${PHASE_DIR}/API-CONTRACTS/post-api-sites.md"],
  "endpoint_count": 1,
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "test_goals_index_path": "${PHASE_DIR}/TEST-GOALS/index.md",
  "test_goals_sub_files": ["${PHASE_DIR}/TEST-GOALS/G-00.md"],
  "goal_count": 1,
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "edge_cases_path": "${PHASE_DIR}/EDGE-CASES.md",
  "edge_cases_index_path": "${PHASE_DIR}/EDGE-CASES/index.md",
  "edge_cases_sub_files": ["${PHASE_DIR}/EDGE-CASES/G-00.md"],
  "edge_cases_skipped": false,
  "edge_cases_skip_reason": null,
  "total_variants": 47,
  "variant_count_per_goal": {"G-04": 6, "G-12": 4},
  "lens_seeds_merged_per_goal": {"G-04": 5, "G-12": 2},
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape", "INTERFACE-STANDARDS:response-envelope"],
  "warnings": []
}
```

If edge cases skipped (no_crud_reason or --skip-edge-cases):
- `edge_cases_skipped: true`
- `edge_cases_skip_reason: "<reason>"`
- `edge_cases_path/index_path/sub_files`: empty/null
- `total_variants: 0`, `variant_count_per_goal: {}`, `lens_seeds_merged_per_goal: {}`

When LENS-WALK/G-NN.md exists at edge-cases time: subagent MUST merge each
seed row (table format described in `_shared/blueprint/lens-walk.md` schema)
into the matching EDGE-CASES/G-NN.md category section. Each merged row
gets a trailing comment `<!-- vg-lens-source: <lens-slug> -->` for downstream
audit. Track count in `lens_seeds_merged_per_goal`. If LENS-WALK/G-NN.md
absent for a goal (lens-walk skipped or zero applicable lenses), proceed
profile-template-only — no error.

`codex_proposal_path` and `codex_delta_path` are owned by the MAIN agent
in STEP 4.4 (separate Codex CLI spawn). Do NOT generate these yourself
and do NOT include their paths in the return JSON.
````

---

# Part 5 — LENS-WALK seeds (Option B v2.50+, runs before Part 4)

This part is invoked by the orchestrator at sub-step `2b5e_a_lens_walk`,
BEFORE `2b5e_edge_cases` (Part 4). It produces `LENS-WALK/G-NN.md` per-goal
plus `LENS-WALK/index.md`. The output becomes seed input for Part 4.

## Inputs (read-only)

- `${PHASE_DIR}/TEST-GOALS/G-*.md` — goal IDs + titles + resources
- `${PHASE_DIR}/CRUD-SURFACES.md` — resource × action × scope × element_class
- `${PHASE_DIR}/UI-SPEC.md` if exists (frontend profiles only)
- `.claude/commands/vg/_shared/lens-prompts/lens-*.md` — canonical lens
  library; load only candidate lenses (use `bug_class` frontmatter to
  filter by profile-applicable bug classes)

## Profile → applicable bug_classes

Orchestrator passes `applicable_bug_classes` env var. Subagent honors it:

| Profile | bug_classes |
|---|---|
| web-fullstack | authz, injection, auth, bizlogic, state-coherence, ui-mechanic, server-side, redirect |
| web-frontend-only | authz, auth, bizlogic, state-coherence, ui-mechanic, redirect |
| web-backend-only | authz, injection, auth, bizlogic, state-coherence, server-side, redirect |
| mobile-* / cli-tool / library | auth, bizlogic, state-coherence |

## Per-goal × per-lens iteration

For each goal G-NN, identify applicable lenses by these rules
(see `_shared/blueprint/lens-walk.md` "Lens applicability rules" for the
full table). Discard lenses whose `bug_class` not in `applicable_bug_classes`.

For each (goal, applicable_lens) pair: read the lens's `## Probe ideas`
section (4-8 bullets). Pick 1-3 probes most relevant to the goal — emit
1 row per pick:

```markdown
| L-04-IDOR-1 | lens-idor | "Replay POST with peer-tenant token" | G-04-a3 | critical |
```

`seed_id` format: `L-<goal_num>-<lens_short>-<N>` where:
- `<goal_num>`: goal id without prefix (G-04 → 04)
- `<lens_short>`: uppercase 2-4 letter mnemonic (idor→IDOR, mass-assignment→MA,
  business-logic→BL, input-injection→II, tenant-boundary→TB, etc.)
- `<N>`: 1, 2, 3 within (goal × lens)

`proposed variant_id` follows the lens→category mapping table in lens-walk.md.

## Skip rule

If a lens lists 0 probe ideas matching the goal's resource/scope, mark it
"considered but skipped" in the per-goal file's "Lenses considered but
skipped" section — do NOT emit empty seed rows.

If a goal is read-only with no auth boundary (e.g., G-99 health check),
mark all lenses skipped and write the per-goal file with empty seed table
plus a `skipped: <reason>` header.

## Output schema (per `_shared/blueprint/lens-walk.md`)

Layer 1: `${PHASE_DIR}/LENS-WALK/G-NN.md` (per-goal, primary).
Layer 2: `${PHASE_DIR}/LENS-WALK/index.md` (matrix TOC).
No Layer 3 flat file (lens-walk is intermediate, not a contract).

## Return JSON (Part 5)

```json
{
  "lens_walk_path": null,
  "lens_walk_index_path": "${PHASE_DIR}/LENS-WALK/index.md",
  "lens_walk_sub_files": [
    "${PHASE_DIR}/LENS-WALK/G-04.md",
    "${PHASE_DIR}/LENS-WALK/G-12.md"
  ],
  "applicable_lens_per_goal": {
    "G-04": ["lens-idor", "lens-mass-assignment", "lens-business-logic", "lens-input-injection", "lens-tenant-boundary"],
    "G-12": ["lens-idor", "lens-bfla", "lens-tenant-boundary"]
  },
  "total_seed_variants": 12,
  "goals_with_lenses_count": 2,
  "lens_walk_skipped": false,
  "lens_walk_skip_reason": null,
  "summary": "<one paragraph: how many goals × lenses, dominant bug classes>",
  "warnings": []
}
```

If skipped (no_crud_reason or --skip-lens-walk):
- `lens_walk_skipped: true`
- `lens_walk_skip_reason: "<reason>"`
- All path/sub_files: empty/null
- `applicable_lens_per_goal: {}`, `total_seed_variants: 0`

---

## Output (subagent returns)

Shape MUST match `agents/vg-blueprint-contracts/SKILL.md` "Example
return" exactly. Codex proposal/delta paths are NOT in the subagent
return — main agent owns + populates them in STEP 4.4 (Codex CLI
spawn happens after this subagent returns).

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_index_path": "${PHASE_DIR}/API-CONTRACTS/index.md",
  "api_contracts_sub_files": [
    "${PHASE_DIR}/API-CONTRACTS/post-api-sites.md"
  ],
  "endpoint_count": 1,
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "test_goals_index_path": "${PHASE_DIR}/TEST-GOALS/index.md",
  "test_goals_sub_files": [
    "${PHASE_DIR}/TEST-GOALS/G-00.md"
  ],
  "goal_count": 1,
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```

---

## Failure modes

| Error JSON | Cause | Action |
|---|---|---|
| `{"error":"missing_input","field":"<name>"}` | Required input missing | Verify file; re-spawn |
| `{"error":"contract_format_unsupported","format":"X"}` | Format not implemented | Manual override or fix config |
| `{"error":"r3b_persistence_missing","goals":[...]}` | Mutation goals without Persistence check | Re-spawn with explicit instruction |
| `{"error":"binding_unmet","missing":[...]}` | Required binding citation absent | Re-spawn with explicit binding |

Retry up to 2 times, then escalate via `AskUserQuestion` (Layer 3).
