---
name: "vg-blueprint"
description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
metadata:
  short-description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use `codex exec --model <model>` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | `curl -sfL` or `gh api` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning `$vg-blueprint`. Treat all user text after `$vg-blueprint` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **CONTEXT.md required** — must exist before blueprint. No CONTEXT = BLOCK.
2. **4 sub-steps in order** — 2a Plan → 2b Contracts → 2c Verify → 2d CrossAI. No skipping.
3. **API contracts BEFORE build** — contracts are INPUT to build, not POST-build check.
4. **Verify is grep-only** — step 2c uses no AI. Pure grep diff. Fast (<5 seconds).
5. **Max 400 lines per agent** — planner gets ~300, contract gen gets ~200.
6. **ORG 6-dimension gate** — plan MUST answer: Infra, Env, Deploy, Smoke, Integration, Rollback.
7. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action, run:
   `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
   Preflight: `create_task_tracker` runs `filter-steps.py --command blueprint.md --profile $PROFILE --output-ids`
   and MUST create tasks matching exactly that list (count check). Step 3_complete verifies markers.
</rules>

<objective>
Step 2 of V5 pipeline. Heaviest planning step — 4 sub-steps produce PLAN.md + API-CONTRACTS.md, both verified.

Pipeline: specs → scope → **blueprint** → build → review → test → accept

Sub-steps:
- 2a: PLAN — GSD planner creates tasks + acceptance criteria (~300 lines)
- 2b: CONTRACTS — Generate API contracts from code/specs (~200 lines)
- 2c: VERIFY 1 — Grep diff contracts vs code/specs (no AI, <5 sec)
- 2d: CROSSAI REVIEW — 2 CLIs review plan + contracts + context
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

<step name="1_parse_args">
Extract from `$ARGUMENTS`: phase_number (required), plus optional flags:
- `--skip-research`, `--gaps`, `--reviews`, `--text` — pass through to GSD planner
- `--crossai-only` — skip 2a/2b/2c, run only 2d (CrossAI review). Requires PLAN*.md + API-CONTRACTS.md to exist.
- `--skip-crossai` — run full blueprint but skip CrossAI review in 2d-6 (deterministic gate only). Faster + cheaper. Use when phase is small/iterative and CrossAI third-opinion adds little.
- `--from=2b` / `--from=2c` / `--from=2d` — resume from specific sub-step. Skip prior sub-steps (require their artifacts to exist).

Validate: phase exists. Determine `$PHASE_DIR`.

**Skip logic:**
- `--crossai-only` → jump directly to step 2d_crossai_review
- `--from=2b` → skip 2a, start at 2b_contracts (PLAN*.md must exist)
- `--from=2c` → skip 2a+2b, start at 2c_verify (PLAN*.md + API-CONTRACTS.md must exist)
- `--from=2d` → same as `--crossai-only`
</step>

<step name="create_task_tracker">
**Create sub-step task list for progress tracking.**

Create tasks for each sub-step in this command:
```
TaskCreate: "2a. Plan — GSD planner"           (activeForm: "Creating plans...")
TaskCreate: "2b. Contracts — API contracts"     (activeForm: "Generating API contracts...")
TaskCreate: "2b5. Test goals — generate goals"   (activeForm: "Generating TEST-GOALS...")
TaskCreate: "2b7. Flow detect — FLOW-SPEC"      (activeForm: "Detecting business flows...")
TaskCreate: "2c. Verify 1 — grep diff"          (activeForm: "Verifying contracts (grep)...")
TaskCreate: "2d. CrossAI review"               (activeForm: "Running CrossAI review...")
```

Store task IDs for updating status as each sub-step runs.
Each sub-step should: `TaskUpdate: status="in_progress"` at start, `status="completed"` at end.
</step>

<step name="2_verify_prerequisites">
**Phase profile detection (P5, v1.9.2) — done BEFORE prerequisite check.**

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  SKIP_ARTIFACTS=$(phase_profile_skip_artifacts "$PHASE_PROFILE")
  export PHASE_PROFILE SKIP_ARTIFACTS
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"
else
  PHASE_PROFILE="feature"
  SKIP_ARTIFACTS=""
fi
```

**CONTEXT.md required ONLY for feature profile** (other profiles skip scope + CONTEXT).

```bash
needs_context=true
for a in $SKIP_ARTIFACTS; do
  [ "$a" = "CONTEXT.md" ] && needs_context=false
done

if [ "$needs_context" = "true" ] && [ ! -f "${PHASES_DIR}/${phase_dir}/CONTEXT.md" ]; then
  echo "⛔ CONTEXT.md not found for Phase ${PHASE_NUMBER} (profile=${PHASE_PROFILE} requires it)."

  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="blueprint.2-verify-prereq"
    BR_GATE_CONTEXT="Feature profile requires CONTEXT.md (scope decisions). User must run /vg:scope first."
    BR_EVIDENCE=$(printf '{"profile":"%s","missing":"CONTEXT.md"}' "$PHASE_PROFILE")
    BR_CANDIDATES='[]'
    BR_RESULT=$(block_resolve "blueprint-no-context" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    [ "$BR_LEVEL" = "L2" ] && exit 2
  fi
  echo "   Run first: /vg:scope ${PHASE_NUMBER}"
  exit 1
fi

# For non-feature profiles, skip scope and contracts generation.
# Blueprint for infra/hotfix/bugfix/migration/docs only produces PLAN (and ROLLBACK for migration).
if [ "$PHASE_PROFILE" != "feature" ]; then
  echo "ℹ Blueprint profile-aware mode: PHASE_PROFILE=${PHASE_PROFILE} — bỏ qua (skip) sub-steps 2b, 2b5, 2b7 (contracts/test-goals/flow)."
  echo "   Chỉ tạo PLAN.md (+ ROLLBACK.md nếu migration). CrossAI review vẫn áp dụng để kiểm tra PLAN quality."
  export BLUEPRINT_PROFILE_SHORT_CIRCUIT=true
fi
```

**Legacy fallback (profile detection unavailable):** Check `${PHASES_DIR}/{phase_dir}/CONTEXT.md` exists.

Missing → BLOCK:
```
CONTEXT.md not found for Phase {N}.
Run first: /vg:scope {phase}
```

**Design-extract auto-trigger (fixes G1):**

```bash
# If project has design assets configured, ensure they're normalized BEFORE planning
# (so R4 granularity check + executor design_context have something to point at)
if [ -n "${config.design_assets.paths[0]}" ]; then
  DESIGN_OUT="${config.design_assets.output_dir:-${PLANNING_DIR}/design-normalized}"
  DESIGN_MANIFEST="${DESIGN_OUT}/manifest.json"

  # Stale check: any source asset newer than manifest?
  NEEDS_EXTRACT=false
  if [ ! -f "$DESIGN_MANIFEST" ]; then
    NEEDS_EXTRACT=true
    REASON="manifest missing"
  else
    # Compare mtimes — if any asset newer than manifest, re-extract
    for pattern in "${config.design_assets.paths[@]}"; do
      if find $pattern -newer "$DESIGN_MANIFEST" 2>/dev/null | grep -q .; then
        NEEDS_EXTRACT=true
        REASON="assets changed since last extract"
        break
      fi
    done
  fi

  if [ "$NEEDS_EXTRACT" = true ]; then
    echo "Design assets detected, manifest $REASON. Auto-running /vg:design-extract..."
    # --auto flag inherits; manual run lets user approve
    if [[ "$ARGUMENTS" =~ --auto ]]; then
      SlashCommand: /vg:design-extract --auto
    else
      AskUserQuestion: "Extract design assets now? (Required for <design-ref> linkage)"
        Options: [Yes (recommended), Skip — build without design]
      # If Yes → SlashCommand: /vg:design-extract
    fi
  fi
fi
```

Skip gracefully when `design_assets.paths` empty (pure backend phase).
</step>

<step name="2a_plan">
## Sub-step 2a: PLAN

**CONTEXT.md format validation (quick, <5 sec):**

Before planning, verify CONTEXT.md has the enriched format scope.md should have produced:

```bash
CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"
# Check enriched format: at least some P{phase}.D-XX (or legacy D-XX) decisions should have Endpoints or Test Scenarios
HAS_ENDPOINTS=$(grep -c "^\*\*Endpoints:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
HAS_TESTS=$(grep -c "^\*\*Test Scenarios:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
DECISION_COUNT=$(grep -cE "^### (P[0-9.]+\.)?D-" "$CONTEXT_FILE" 2>/dev/null || echo 0)

if [ "$DECISION_COUNT" -eq 0 ]; then
  echo "⛔ CONTEXT.md has 0 decisions. Run /vg:scope ${PHASE_NUMBER} first."
  exit 1
fi

if [ "$HAS_ENDPOINTS" -eq 0 ] && [ "$HAS_TESTS" -eq 0 ]; then
  echo "⚠ CONTEXT.md may be legacy format (no Endpoints/Test Scenarios sub-sections)."
  echo "  Blueprint will proceed but may produce less accurate plans."
  echo "  For best results: /vg:scope ${PHASE_NUMBER} (re-scope with enriched format)"
fi

echo "CONTEXT.md: ${DECISION_COUNT} decisions, ${HAS_ENDPOINTS} with endpoints, ${HAS_TESTS} with test scenarios"
```

Create execution plans using VG-native planner (self-contained, no GSD delegation).

Spawn planner agent with VG-specific rules:
```
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    <specs>
    @${PHASE_DIR}/SPECS.md
    </specs>

    <context>
    @${PHASE_DIR}/CONTEXT.md
    </context>

    <contracts>
    @${PHASE_DIR}/API-CONTRACTS.md (if exists)
    </contracts>

    <goals>
    @${PHASE_DIR}/TEST-GOALS.md (if exists)
    </goals>

    <config>
    profile: ${PROFILE}
    typecheck_cmd: ${config.build_gates.typecheck_cmd}
    contract_format: ${config.contract_format.type}
    phase: ${PHASE_NUMBER}
    phase_dir: ${PHASE_DIR}
    </config>

    Create PLAN.md for phase ${PHASE_NUMBER}. Follow vg-planner-rules exactly.
    Output: ${PHASE_DIR}/PLAN.md with waves, task attributes, goal coverage.
```

Wait for completion. Verify `PLAN.md` exists in `${PHASE_DIR}`.

**Post-plan ORG check** (mandatory):
Read all PLAN*.md files. Check that the 6 ORG dimensions are addressed:

| # | Dimension | How to check |
|---|-----------|-------------|
| 1 | Infra | Any task mentions installing/configuring services? |
| 2 | Env | Any task mentions new env vars, configs, secrets? |
| 3 | Deploy | Is there a task for deploying to target? |
| 4 | Smoke | Is there a task for verifying it's alive? |
| 5 | Integration | Is there a task for testing with existing services? |
| 6 | Rollback | Is there a recovery path documented? |

Missing dimension → add note to plan (auto-fix for minor, ask user for major).

**Post-plan granularity check** (mandatory — execute sát blueprint):

Parse all tasks from PLAN*.md. For each task, validate:

| Rule | Requirement | Severity |
|------|-------------|----------|
| R1: Exact file path | Task specifies `{file-path}` or equivalent (not vague "can be in ...") | HIGH |
| R2: Contract reference | If task touches API (has verb POST/GET/PUT/DELETE OR creates endpoint handler) → must cite `<contract-ref>` pointing to API-CONTRACTS.md line range | HIGH |
| R3: Goals covered | Task has `<goals-covered>[G-XX, G-YY]</goals-covered>` when applicable. If task is pure infra/tooling: `no-goal-impact` acceptable. | MED |
| R4: Design reference | If task builds FE page/component AND config.design_assets is non-empty → must cite `<design-ref>` pointing to design-specs or design-screenshots. | MED |
| R5: Scope size | Estimated LOC delta ≤ 250 lines. If larger → recommend split into sub-tasks. | MED |

**⛔ R2 contract-ref format (tightened 2026-04-17 — MUST match regex, not free-form):**

```
<contract-ref>API-CONTRACTS.md#{endpoint-id} lines {start}-{end}</contract-ref>
```

Regex: `^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$`

Valid examples:
- `<contract-ref>API-CONTRACTS.md#post-api-sites lines 45-80</contract-ref>`
- `<contract-ref>API-CONTRACTS.md#get-api-campaigns-id lines 130-175</contract-ref>`

Invalid (will fail commit-msg Gate 2b and build citation resolver):
- `<contract-ref>API-CONTRACTS.md#post-sites</contract-ref>` — missing line range
- `<contract-ref>API-CONTRACTS.md line 45-80</contract-ref>` — missing #endpoint-id
- `<contract-ref>contracts.md#post-sites lines 45-80</contract-ref>` — wrong filename

Validation (inline in plan checker):
```bash
for ref in $(grep -oE '<contract-ref>[^<]+</contract-ref>' "$PLAN_FILE"); do
  body=$(echo "$ref" | sed 's/<[^>]*>//g')
  if ! echo "$body" | grep -qE '^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$'; then
    echo "⛔ R2 malformed contract-ref: '$body' — expected 'API-CONTRACTS.md#{id} lines X-Y'"
    R2_MALFORMED=$((R2_MALFORMED + 1))
  fi
done
```

Malformed R2 is treated as HIGH (not MED) — downstream build citation check parses this string literally.

**Inject warnings into PLAN.md as HTML comments** (non-intrusive):
```markdown
## Task 04: Add POST /api/sites handler

**Scope:** apps/api/src/modules/sites/routes.ts

<!-- plan-warning:R2 missing <contract-ref> — task creates endpoint but doesn't cite API-CONTRACTS.md line range. Add: <contract-ref>API-CONTRACTS.md#post-api-sites line 45-80</contract-ref> -->

Implementation: ...
```

**Warning budget:**
- > 50% tasks have HIGH warnings → return to planner with feedback for regeneration (loop to 2a)
- > 30% tasks have MED warnings → proceed but surface in step 2d (CrossAI review catches + Auto-fix loop)

Display:
```
Plan granularity check:
  Total tasks: {N}
  R1 file-path missing: {N}
  R2 contract-ref missing: {N}  (HIGH → {block|warn})
  R3 goals-covered missing: {N}
  R4 design-ref missing: {N}
  R5 scope >250 LOC: {N}
  Warnings injected: {total}
```
</step>

<step name="2a5_cross_system_check">
## Sub-step 2a5: CROSS-SYSTEM CHECK (grep, no AI, <10 sec)

Scan the existing codebase and prior phases to detect conflicts/overlaps BEFORE writing contracts and code. This prevents phase isolation blindness.

**Check 1: Route conflicts**
```bash
# Grep all registered routes in existing code
EXISTING_ROUTES=$(grep -r "router\.\(get\|post\|put\|delete\|patch\)" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'/[^']+'" | sort)
# Compare with endpoints planned in CONTEXT.md decisions
# Flag: route already exists → plan must UPDATE, not CREATE
```

**Check 2: Schema/model field conflicts**
```bash
# Grep existing model/schema definitions
EXISTING_SCHEMAS=$(grep -r "z\.object\|Schema\|interface\s" "$API_ROUTES" --include="*.ts" --include="*.js" -l 2>/dev/null)
# For each model this phase touches (from CONTEXT.md):
#   Check if schema already has fields that conflict with planned changes
```

**Check 3: Shared component impact**
```bash
# Grep components this phase's pages import
# For each shared component: find ALL pages that import it
# Flag: shared component change affects N other pages outside this phase
grep -r "import.*from.*components" "$WEB_PAGES" --include="*.tsx" --include="*.jsx" -h 2>/dev/null | sort | uniq -c | sort -rn | head -20
```

**Check 4: Prior phase overlap**
```bash
# Read SUMMARY*.md from recent phases (last 3-5 phases)
# Check if any SUMMARY mentions same files/modules this phase plans to touch
for summary in $(ls ${PHASES_DIR}/*/SUMMARY*.md 2>/dev/null | tail -5); do
  grep -l "$(basename ${PHASE_DIR})" "$summary" 2>/dev/null
done
```

**Check 5: Database collection conflicts**
```bash
# Grep all collection references in existing code
grep -r "collection\(\|\.find\|\.insertOne\|\.updateOne" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'[^']+'" | sort | uniq -c | sort -rn
# Flag: this phase adds fields to collection another phase also modifies
```

**Output:** Inject warnings into PLAN.md as `<!-- cross-system-warning: ... -->` markers.

```
Cross-System Check:
  Routes: {N} potential conflicts
  Schemas: {N} shared fields
  Components: {N} shared, affecting {M} other pages
  Prior phases: {N} overlaps
  Collections: {N} conflicts
  
  Warnings injected into PLAN.md: {count}
```

No block — warnings only. AI planner should address each warning in task descriptions.

### Cross-system check 2: Caller graph (semantic regression)

Build `.callers.json` — maps each PLAN task's `<edits-*>` symbols to all downstream files using them. Build step 4e consumes this; commit-msg hook enforces caller update or citation.

```bash
if [ "${config.semantic_regression.enabled:-true}" = "true" ]; then
  ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
    --phase-dir "${PHASE_DIR}" \
    --config .claude/vg.config.md \
    --output "${PHASE_DIR}/.callers.json"

  # Inject per-task warnings into PLAN.md listing downstream callers
  # Planner should ensure tasks updating shared symbols know their blast radius
  CALLER_COUNT=$(jq '.affected_callers | length' "${PHASE_DIR}/.callers.json")
  echo "Semantic regression: tracked ${CALLER_COUNT} downstream callers across ${PHASE_DIR}/.callers.json"
fi
```

Planner should convert each warning into task annotations: `<edits-schema>X</edits-schema>` so the graph can track changes reliably.
</step>

<step name="2b_contracts">
## Sub-step 2b: CONTRACTS (strict format — executable code block)

Read `.claude/skills/api-contract/SKILL.md` — Mode: Generate.
Read `config.contract_format` from `.claude/vg.config.md`:
- `type`: zod_code_block | openapi_yaml | typescript_interface | pydantic_model
- `compile_cmd`: how to validate syntax (used in 2c2)

**Input:** CONTEXT.md + code at `config.code_patterns.api_routes` and `config.code_patterns.web_pages`

**Process:**
1. Grep existing schemas in codebase (match config.contract_format type)
2. Grep HTML/JSX forms and tables (if web_pages path exists)
3. Extract endpoints from CONTEXT.md decisions — supports both formats:
   - **VG-native bullet format** (from /vg:scope): `- POST /api/v1/sites (auth: publisher, purpose: create site)`
     Match regex: `^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - **Legacy header format** (from manual/older CONTEXT.md): `### POST /api/v1/sites`
     Match regex: `^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - Collect all matched `(method, path)` pairs into endpoint list for contract generation
4. Cross-reference endpoint list with CONTEXT decisions (each decision with data/CRUD → endpoint)
5. AI drafts contract for any endpoint without existing schema

**STRICT OUTPUT FORMAT — each endpoint MUST have executable code block:**

Example for `contract_format.type == "zod_code_block"`:

**4 blocks per endpoint. Blocks 1-3 = executor copies. Block 4 = test consumes.**

````markdown
### POST /api/sites

**Purpose:** Create new site (publisher role)

```typescript
// === BLOCK 1: Auth + middleware (COPY VERBATIM to route handler) ===
// Executor: paste this EXACT line in the route registration
export const postSitesAuth = [requireAuth(), requireRole('publisher'), rateLimit(30)];
```

```typescript
// === BLOCK 2: Request/Response schemas (COPY VERBATIM — same as before) ===
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
// Executor: use these EXACT shapes in catch blocks. FE reads error.message for toast.
export const PostSitesErrors = {
  400: { error: { code: 'VALIDATION_FAILED', message: 'Invalid site data' } },
  401: { error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } },
  403: { error: { code: 'FORBIDDEN', message: 'Publisher role required' } },
  409: { error: { code: 'DUPLICATE_DOMAIN', message: 'Domain already registered' } },
} as const;
// FE toast rule: always show `response.data.error.message` — never HTTP status text
```

```typescript
// === BLOCK 4: Valid test sample (for idempotency + smoke tests) ===
// Executor: do NOT copy this block into app code. Used by test.md step 5b-2.
export const PostSitesSample = {
  domain: "https://test-idem.example.com",
  name: "Idempotency Test Site",
  categoryId: "00000000-0000-0000-0000-000000000001",
} as const;
```

**Mutation evidence:** `sites collection count +1`
**Cross-ref tasks:** Task {N} (BE handler), Task {M} (FE form)
````

**4 blocks per endpoint. Blocks 1-3 = executor copies verbatim. Block 4 = test consumes (step 5b-2). Executor does NOT write auth, schema, or error handling from scratch.**

Format per type (all 4 blocks adapt to format):
- `zod_code_block` → `\`\`\`typescript` with z.object, requireRole, error map, sample const
- `openapi_yaml` → `\`\`\`yaml` with security schemes, schemas, error responses, example values
- `typescript_interface` → `\`\`\`typescript` with interfaces + error types + sample const
- `pydantic_model` → `\`\`\`python` with BaseModel + FastAPI Depends + HTTPException + sample dict

**Rationale:** Billing-403 bug class happens when AI "decides" auth role or error shape instead of
copying from contract. By generating executable code blocks for ALL 3 concerns, the executor has
zero decision points — it copies, it doesn't think. Same principle as Zod schema copy, extended to
auth middleware and error responses. Block 4 eliminates the second bug class: heuristic payload
generation in test.md step 5b-2 producing values that fail Zod validation (e.g. `idempotency-test-domain`
is not a valid URL). Contract author knows the schema best — they provide the valid sample.

**Error response shape** is project-wide consistent. Read `config.error_response_shape` (default:
`{ error: { code: string, message: string } }`) — every endpoint's Block 3 MUST use this shape.
FE code reads `response.data.error.message` for toast — never `response.statusText` or raw code.

**Block 4 rules:**
1. Each endpoint MUST have Block 4 with valid sample payload matching Block 2 schema.
2. Use realistic values: valid email (test@example.com), valid UUID (00000000-...-000001), valid URL (https://test.example.com), ISO date, etc.
3. Zod/Pydantic validation of Block 4 values must pass against Block 2 schema.
4. Block 4 is consumed by test.md step 5b-2 idempotency check — NOT copied into app code.
5. Sample const name convention: `{Method}{Resource}Sample` (e.g. `PostSitesSample`, `PutCampaignSample`).
6. Mark `as const` (TypeScript) or freeze (Python) to prevent accidental mutation.
7. GET endpoints do NOT need Block 4 (no mutation payload).
8. For endpoints with path params, include a comment with sample path: `// path: /api/sites/00000000-0000-0000-0000-000000000001`

**Context budget:** ~500 lines (increased from 400 — 4 blocks per endpoint). Agent reads:
- CONTEXT.md (decisions list, ~50 lines)
- Grep results from code (extracted field hints, ~100 lines)
- Contract format template from config (~150 lines)
- Existing auth middleware patterns in codebase (~100 lines)

**Output:** Write `${PHASE_DIR}/API-CONTRACTS.md`. Must contain at least 1 code block per endpoint.

If no API routes or web pages detected → write minimal contract with CONTEXT-derived endpoints only. Still enforce code block format.
</step>

<step name="2b5_test_goals">
## Sub-step 2b5: TEST GOALS

Generate TEST-GOALS.md from CONTEXT.md decisions + API-CONTRACTS.md endpoints.

**Agent context (~300 lines):**
- CONTEXT.md decisions (`P{phase}.D-01` through `P{phase}.D-XX`, or legacy `D-01..D-XX`) (~100 lines)
- API-CONTRACTS.md endpoints + fields (~100 lines)
- Output format template (~100 lines)

**Agent prompt:**
```
Convert CONTEXT decisions into testable GOALS.

For each decision (`P{phase}.D-XX`, or legacy `D-XX`), produce 1+ goals. Each goal:
- Has success criteria (what the user can do, what the system shows)
- Has mutation evidence (for create/update/delete: API response + UI change)
- Has dependencies (which goals must pass first)
- Has priority (critical = core feature, important = expected feature, nice-to-have = edge case/polish)

CONTEXT decisions:
[P{phase}.D-01 through P{phase}.D-XX — phase-scoped namespace, mandatory prefix]

API endpoints:
[from API-CONTRACTS.md]

RULES:
1. Every decision MUST have at least 1 goal
2. Goals describe WHAT to verify, not HOW (no selectors, no exact clicks)
3. Mutation evidence must be specific: "POST returns 201 AND row count +1" not "data changes"
4. Dependencies must reference goal IDs (G-XX)
5. Priority assignment (deterministic rules, evaluate in order):
   a. Endpoints matching config `routing.critical_goal_domains` (auth, billing, auction, payout, compliance) → priority: critical
   b. Auth/session/token goals (login, logout, JWT refresh, session persist) → priority: critical
   c. Data mutation goals (POST/PUT/DELETE endpoints) → priority: important (minimum — upgrade to critical if also matches rule a/b)
   d. Read-only goals (GET endpoints, list/detail views) → priority: important (default)
   e. Cosmetic/display goals (formatting, sorting, empty states, UI polish) → priority: nice-to-have
6. Infrastructure dependency annotation (config-driven):
   If a goal requires services listed in config.infra_deps.services that are NOT part of this phase's build scope (e.g., ClickHouse, Kafka, pixel server), add:
   ```
   **Infra deps:** [clickhouse, kafka, pixel_server]
   ```
   Review Phase 4 auto-classifies goals with unmet infra_deps as INFRA_PENDING (skipped from gate).
   Determine infra scope by reading PLAN.md — services explicitly provisioned in tasks = in scope.
   Services referenced but not provisioned = external infra dep.

Output format:

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
**Dependencies:** none (root goal)
**Infra deps:** none

## Goal G-01: {Feature} (P{phase}.D-XX — or F-XX if foundation-sourced)
**Priority:** critical | important | nice-to-have
**Success criteria:**
- [what the user can do]
- [what the system shows]
- [error handling]
**Mutation evidence:**
- [Create: POST /api/X returns 201, table row +1]
- [Update: PUT /api/X/:id returns 200, row reflects change]
**Dependencies:** G-00

## Decision Coverage
| Decision | Goal IDs | Priority |
|----------|----------|----------|
| D-01 | G-01, G-02 | critical |
| D-02 | G-03 | important |
| ...  | ... | ... |

Coverage: {covered}/{total} decisions → {percentage}%
```

Write `${PHASE_DIR}/TEST-GOALS.md`.

**Bidirectional linkage with PLAN (mandatory post-gen):**

After TEST-GOALS.md is written, inject cross-references so build step 8 can quickly find context:

1. **Goals → Tasks** (in TEST-GOALS.md): for each G-XX, detect which tasks in PLAN*.md implement it (match by endpoint/file mentions). Add:
   ```markdown
   ## Goal G-03: Create site (D-02)
   **Implemented by:** Task 04 (BE handler), Task 07 (FE form)   ← NEW
   ...
   ```

2. **Tasks → Goals** (in PLAN*.md): for each task, inject `<goals-covered>` attribute if not already present. Auto-detect based on task description mentioning endpoint/feature that maps to goal's mutation evidence.

Algorithm (deterministic, no AI guess):
```
For each goal G-XX in TEST-GOALS.md:
  extract endpoints from "mutation evidence" (e.g., POST /api/sites)
  For each task in PLAN*.md:
    If task description contains matching endpoint OR feature-name from goal:
      append task to goal.implemented_by
      append goal to task.<goals-covered>

For orphan tasks (no goal match):
  inject <goals-covered>no-goal-impact</goals-covered>
  OR <goals-covered>UNKNOWN — review</goals-covered> (flag for user)

For orphan goals (no task match):
  inject **Implemented by:** ⚠ NONE (spec gap — plan regeneration needed)
```

Display:
```
Test Goals: {N} goals generated ({critical} critical, {important} important, {nice} nice-to-have)
Decision coverage: {covered}/{total} ({percentage}%)
Goal ↔ Task linkage:
  Goals linked to tasks: {N}/{total}
  Orphan goals (no task): {N}       ← spec gap, surfaced to 2d validation
  Orphan tasks (no goal): {N}       ← may be infra or spec bloat
```

**Surface classification (v1.9.1 R1 — lazy migration):**

Immediately after TEST-GOALS.md is written (including bidirectional linkage), classify each goal into a **test surface** (ui / ui-mobile / api / data / time-driven / integration / custom). This is what `/vg:review` and `/vg:test` use to pick runners — backend-only phases must not deadlock on browser discovery.

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
```

Behaviour by return code:
- `0` → all goals classified at ≥0.8 confidence (narration prints auto-count).
- `2` → 0.5..0.8 band needs Haiku tie-break. Read `${PHASE_DIR}/.goal-classifier-pending.tsv`, spawn ONE Haiku subagent per goal (pattern identical to `rationalization-guard` — subagent receives goal block + candidate surface + keywords found, returns `{surface, confidence}`). Call `classify_goals_apply` with the resolved TSV.
- `3` → some goals <0.5 confidence. BLOCK until user picks via `AskUserQuestion` (options = configured surface list + "custom"). Call `classify_goals_apply` with user answers.

After classification, include per-goal surface in blueprint narration:
```
🎯 Goal surfaces: 17 ui · 5 api · 3 data · 2 time-driven · 1 integration
```
</step>

<step name="2b6_ui_spec">
## Sub-step 2b6: UI SPEC (FE tasks only)

**Skip conditions:**
- No task has `file-path` matching `config.code_patterns.web_pages` → skip entirely
- `config.design_assets.paths` empty → skip (no visual reference to derive from)
- `${PHASE_DIR}/UI-SPEC.md` already exists and is newer than all PLAN*.md + design manifest → skip (already fresh)

**Purpose:** Produce UI contract executor reads alongside API-CONTRACTS. Answers: layout, component set, spacing tokens, interaction states, responsive breakpoints.

**Input (~600 lines agent context):**
- CONTEXT.md (design decisions if any, ~100 lines)
- Task file-paths of FE tasks + their `<design-ref>` attributes (~100 lines)
- `${DESIGN_OUTPUT_DIR}/manifest.json` — list of available screenshots + structural refs (~50 lines)
- Sample design refs (read 2-3 representative ones — `*.structural.html` + `*.interactions.md`) (~300 lines)

**Agent prompt:**
```
Generate UI-SPEC.md for phase {PHASE}. This is the design contract FE executors copy verbatim.

RULES:
1. Extract visible patterns from design-normalized refs — do NOT invent.
2. For each component used: name, markup structure (from structural.html), states (from interactions.md).
3. Spacing/color tokens only if consistent across refs. If refs conflict, flag for user.
4. Per-page section: layout (grid/flex), slots (header/sidebar/main), interaction patterns.
5. Reference screenshots by slug — executor opens them for pixel truth.

Output format:

# UI Spec — Phase {PHASE}

Source: ${DESIGN_OUTPUT_DIR}/  (screenshots + structural + interactions)
Derived: {YYYY-MM-DD}

## Design Tokens
| Token | Value | Source |
|-------|-------|--------|
| color.primary | #6366f1 | consistent across {slug-a}, {slug-b} |
| spacing.lg | 24px | ... |

## Component Library (observed in design)
### Button
- Variants: primary | secondary | ghost
- States: default | hover | disabled
- Markup: `<button class="btn btn-{variant}">...</button>`  (from {slug}.structural.html#btn-primary)

### Modal
- Pattern: overlay + centered card
- Open/close: `data-modal-open="{id}"` / `data-modal-close` (from {slug}.interactions.md)
...

## Per-Page Layout
### /publisher/sites (Task 07)
- Screenshot: ${DESIGN_OUTPUT_DIR}/screenshots/sites-list.default.png
- Layout: sidebar (fixed 240px) + main (flex-1)
- Sections: toolbar (search + Add button), table (5 cols), pagination footer
- States needed: empty | loading | populated | error
- Interactions: row click → detail drawer; Add button → modal (component ref above)

## Responsive Breakpoints
(only if design has multiple viewport screenshots)

## Conflicts / Ambiguities
(flag anything where design refs disagree — user decides)
```

Write `${PHASE_DIR}/UI-SPEC.md`. Build step 4/8c injects relevant section per FE task.

Display:
```
UI-SPEC:
  FE tasks detected: {N}
  Design refs consumed: {N}
  Tokens: {N} | Components: {N} | Pages: {N}
  Conflicts flagged: {N}
```
</step>

<step name="2b7_flow_detect" profile="web-fullstack,web-frontend-only">
## Sub-step 2b7: FLOW-SPEC AUTO-DETECT (deterministic, no AI for detection)

**Purpose:** Detect goal dependency chains >= 3 in TEST-GOALS.md. When found, auto-generate
FLOW-SPEC.md skeleton so `/vg:test` step 5c-flow has flows to verify. Without this,
multi-page state-machine bugs (login → create → edit → delete) slip through because
per-goal tests verify each step independently but miss continuity failures.

**Skip conditions:**
- TEST-GOALS.md does not exist → skip (blueprint hasn't generated goals yet)
- Profile is `web-backend-only` or `cli-tool` or `library` → skip (no UI flows)

**Step 1: Parse dependency graph from TEST-GOALS.md**

```bash
# Extract goal IDs and their dependencies (deterministic grep, no AI)
CHAIN_OUTPUT=$(${PYTHON_BIN} - "${PHASE_DIR}/TEST-GOALS.md" <<'PYEOF'
import sys, re, json
from pathlib import Path
from collections import defaultdict

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse goals: ID, title, priority, dependencies
goals = {}
current = None
for line in text.splitlines():
    m = re.match(r'^## Goal (G-\d+):\s*(.+?)(?:\s*\(D-\d+\))?$', line)
    if m:
        current = m.group(1)
        goals[current] = {'title': m.group(2).strip(), 'deps': [], 'priority': 'important'}
        continue
    if current:
        dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
        if dm:
            deps_str = dm.group(1).strip()
            if deps_str.lower() not in ('none', 'none (root goal)', ''):
                goals[current]['deps'] = re.findall(r'G-\d+', deps_str)
        pm = re.match(r'\*\*Priority:\*\*\s*(\w+)', line)
        if pm:
            goals[current]['priority'] = pm.group(1).strip()

# Build dependency chains via DFS — find all maximal chains
def find_chains(goal_id, visited=None):
    if visited is None:
        visited = []
    visited = visited + [goal_id]
    deps = goals.get(goal_id, {}).get('deps', [])
    # Find goals that depend on this one (forward chains)
    dependents = [g for g, info in goals.items() if goal_id in info['deps'] and g not in visited]
    if not dependents:
        return [visited]
    chains = []
    for dep in dependents:
        chains.extend(find_chains(dep, visited))
    return chains

# Find root goals (no dependencies or only depend on auth)
roots = [g for g, info in goals.items() if not info['deps']]
all_chains = []
for root in roots:
    all_chains.extend(find_chains(root))

# Filter chains >= 3 goals (these are multi-step business flows)
long_chains = [c for c in all_chains if len(c) >= 3]
# Deduplicate (keep longest chain per root)
seen = set()
unique_chains = []
for chain in sorted(long_chains, key=len, reverse=True):
    key = tuple(chain[:2])  # dedup by first 2 elements
    if key not in seen:
        seen.add(key)
        unique_chains.append(chain)

output = {
    'total_goals': len(goals),
    'total_chains': len(unique_chains),
    'chains': [{'goals': c, 'length': len(c),
                'titles': [goals[g]['title'] for g in c if g in goals]}
               for c in unique_chains],
    'goals': {g: info for g, info in goals.items()}
}
print(json.dumps(output, indent=2))
PYEOF
)
```

**Step 2: Generate FLOW-SPEC.md skeleton (only if chains found)**

```bash
CHAIN_COUNT=$(echo "$CHAIN_OUTPUT" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['total_chains'])" 2>/dev/null || echo "0")

if [ "$CHAIN_COUNT" -eq 0 ]; then
  echo "Flow detect: no dependency chains >= 3 found. Skipping FLOW-SPEC generation."
  # No FLOW-SPEC.md = 5c-flow will skip (expected for simple phases)
else
  echo "Flow detect: $CHAIN_COUNT chains >= 3 goals found. Generating FLOW-SPEC.md skeleton..."

  # Generate skeleton — AI fills in step details from goal success criteria
  Agent(subagent_type="general-purpose", model="${MODEL_TEST_GOALS}"):
    prompt: |
      Generate FLOW-SPEC.md for phase ${PHASE}. This defines multi-page test flows
      for the flow-runner skill.

      Input — detected dependency chains (goals that form sequential business flows):
      ${CHAIN_OUTPUT}

      Input — full TEST-GOALS.md:
      @${PHASE_DIR}/TEST-GOALS.md

      Input — API-CONTRACTS.md (for endpoint details):
      @${PHASE_DIR}/API-CONTRACTS.md

      RULES:
      1. Each chain becomes 1 flow. Flow = ordered sequence of steps.
      2. Each step maps to 1 goal in the chain.
      3. Step has: action (what user does), expected (what system shows), checkpoint (what to save for next step).
      4. Use goal success criteria + mutation evidence as step expected/checkpoint.
      5. Do NOT invent steps outside the chain — only goals in the chain.
      6. Do NOT specify selectors, CSS classes, or exact clicks — describe WHAT, not HOW.
      7. Flow names should describe the business operation: "Site CRUD lifecycle", "Campaign create-to-launch".

      Output format:

      # Flow Specs — Phase {PHASE}

      Generated from: TEST-GOALS.md dependency chains >= 3
      Total: {N} flows

      ## Flow F-01: {Business operation name}
      **Chain:** {G-00 → G-01 → G-03 → G-05}
      **Priority:** critical | important
      **Roles:** [{roles involved}]

      ### Step 1: {Action name} (G-00)
      **Action:** {what the user does}
      **Expected:** {what the system shows — from goal success criteria}
      **Checkpoint:** {state to verify/save for next step — from mutation evidence}

      ### Step 2: {Action name} (G-01)
      **Action:** ...
      **Expected:** ...
      **Checkpoint:** ...
      ...

      ## Flow Coverage
      | Flow | Goals covered | Priority |
      |------|--------------|----------|
      | F-01 | G-00, G-01, G-03, G-05 | critical |

      Write to: ${PHASE_DIR}/FLOW-SPEC.md
fi
```

Display:
```
Flow detection:
  Goals parsed: {N}
  Dependency chains >= 3: {CHAIN_COUNT}
  FLOW-SPEC.md: {generated|skipped (no chains)}
  Flows defined: {N}
```
</step>

<step name="2c_verify">
## Sub-step 2c: VERIFY 1 (grep only, no AI)

Automated contract verification. Must complete in <5 seconds.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
API_ROUTES="${config.code_patterns.api_routes}"
WEB_PAGES="${config.code_patterns.web_pages}"
MISMATCHES=0

# 1. Contract fields vs HTML form fields
if [ -n "$WEB_PAGES" ] && [ -d "$WEB_PAGES" ]; then
  # For each endpoint with request fields in contracts:
  #   grep form field names in web pages
  #   Missing field → mismatch++
fi

# 2. Contract fields vs Zod schema (if backend exists)
if [ -n "$API_ROUTES" ] && [ -d "$API_ROUTES" ]; then
  # For each endpoint with response fields in contracts:
  #   grep field names in Zod schemas
  #   Missing field → mismatch++
fi

# 3. Contract endpoints vs CONTEXT decisions
# Parse endpoints from CONTEXT.md — supports both formats:
#   VG-native bullet: "- POST /api/v1/sites (auth: publisher, purpose: create)"
#     regex: ^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)
#   Legacy header:   "### POST /api/v1/sites"
#     regex: ^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)
# For each matched (method, path) pair:
#   Check at least one endpoint in contracts covers it
#   No endpoint → mismatch++
```

**Results:**
- 0 mismatches → PASS, proceed to 2d
- 1-3 mismatches → WARNING, auto-fix contracts, re-verify once
- 4+ mismatches → BLOCK, show mismatch table, ask user to review contracts

Display:
```
Verify 1 (grep): {N} endpoints checked, {M} field comparisons
Result: {PASS|WARNING|BLOCK} — {N} mismatches
```
</step>

<step name="2c2_compile_check">
## Sub-step 2c2: CONTRACT COMPILE CHECK (no AI, <10 sec)

Extract executable code blocks from API-CONTRACTS.md → compile via `config.contract_format.compile_cmd`.
Catches contract syntax errors BEFORE build consumes them.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
COMPILE_CMD="${config.contract_format.compile_cmd}"
CONTRACT_TYPE="${config.contract_format.type}"

# Select code block language per contract_format.type:
#   zod_code_block / typescript_interface → ```typescript
#   openapi_yaml → ```yaml
#   pydantic_model → ```python
case "$CONTRACT_TYPE" in
  zod_code_block|typescript_interface) FENCE_LANG="typescript" ;;
  openapi_yaml)                        FENCE_LANG="yaml" ;;
  pydantic_model)                      FENCE_LANG="python" ;;
  *)                                   FENCE_LANG="typescript" ;;
esac

# Extract all matching fenced code blocks into tmp file
TMP_DIR=$(mktemp -d)
${PYTHON_BIN} - "$CONTRACTS" "$TMP_DIR" "$FENCE_LANG" "$CONTRACT_TYPE" <<'PYEOF'
import sys, re
from pathlib import Path
contracts, tmpdir, lang, ctype = sys.argv[1:5]
text = Path(contracts).read_text(encoding='utf-8')
pattern = re.compile(r"```" + re.escape(lang) + r"\s*\n(.*?)\n```", re.DOTALL)
blocks = pattern.findall(text)
if not blocks:
    print(f"NO_CODE_BLOCKS: expected ```{lang} blocks, found 0. Contract format violated.")
    sys.exit(3)

# Concatenate with appropriate prelude per type
prelude = ""
if ctype == "zod_code_block":
    prelude = "import { z } from 'zod';\n\n"
elif ctype == "pydantic_model":
    prelude = "from pydantic import BaseModel\nfrom typing import Optional, List, Literal\nfrom datetime import datetime\n\n"

ext = {"typescript": "ts", "yaml": "yaml", "python": "py"}.get(lang, "ts")
out = Path(tmpdir) / f"contracts-check.{ext}"
out.write_text(prelude + "\n\n".join(blocks), encoding='utf-8')
print(out)
PYEOF

COMPILE_INPUT=$(${PYTHON_BIN} ... last line)

# Run compile command on extracted file
if [ -n "$COMPILE_CMD" ]; then
  ACTUAL_CMD=$(echo "$COMPILE_CMD" | sed "s|{FILE}|$COMPILE_INPUT|g")
  # If no {FILE} placeholder, append file path
  [[ "$COMPILE_CMD" == *"{FILE}"* ]] || ACTUAL_CMD="$COMPILE_CMD $COMPILE_INPUT"

  eval "$ACTUAL_CMD" 2>&1 | tee "${PHASE_DIR}/contract-compile.log"
  EXIT=${PIPESTATUS[0]}
  if [ $EXIT -ne 0 ]; then
    echo "CONTRACT COMPILE FAILED — see ${PHASE_DIR}/contract-compile.log"
    echo "Fix contract syntax in ${PHASE_DIR}/API-CONTRACTS.md and re-run /vg:blueprint --from=2b"
    exit 1
  fi
fi
```

**Results:**
- PASS → contracts syntactically valid, proceed to 2d
- FAIL → BLOCK, show compile errors, user must fix API-CONTRACTS.md code blocks

Display:
```
Verify 2 (compile): {N} code blocks extracted
Compile check: {PASS|FAIL} via {config.contract_format.compile_cmd}
```
</step>

<step name="2d_validation_gate">
## Sub-step 2d: VALIDATION GATE + AUTO-FIX RETRY + CROSSAI

**Combined step:** deterministic validation (plan↔SPECS↔goals↔contracts) + auto-fix retry loop + existing CrossAI review.

**Skip conditions:** none — this is the quality gate before commit.

### 2d-1: Load or create blueprint-state.json

```bash
STATE_FILE="${PHASE_DIR}/blueprint-state.json"
if [ -f "$STATE_FILE" ]; then
  # Resume scenario — prompt user
  LAST_STEP=$(jq -r .current_step "$STATE_FILE")
  LAST_ITER=$(jq -r '.iterations | length' "$STATE_FILE")
  LAST_MODE=$(jq -r '.validation_mode_chosen // "unknown"' "$STATE_FILE")
  echo "Blueprint state found for ${PHASE}:"
  echo "  Last step: $LAST_STEP  (iterations: $LAST_ITER)"
  echo "  Mode: $LAST_MODE"
  # AskUserQuestion: Resume / Restart from step / Fresh
fi

# Fresh start — init state
jq -n --arg phase "$PHASE" --arg ts "$(date -u +%FT%TZ)" '{
  phase: $phase,
  pipeline_version: "vg-v5.2",
  started_at: $ts,
  updated_at: $ts,
  current_step: "2d_validation",
  last_step_completed: "2c2_compile_check",
  steps_status: {
    "2a_plan": "completed", "2a5_cross_system": "completed",
    "2b_contracts": "completed", "2b4_design_ref_linkage": "pending",
    "2b5_test_goals": "completed", "2b7_flow_detect": "pending",
    "2c_verify_grep": "completed",
    "2c2_compile_check": "completed", "2d_validation": "in_progress",
    "3_complete": "pending"
  },
  validation_mode_chosen: null,
  thresholds: null,
  iterations: [],
  user_overrides: []
}' > "$STATE_FILE"
```

### 2d-2: Runtime prompt — strictness mode

**Skip if --auto (use config.plan_validation.default_mode):**

```
AskUserQuestion:
  "Plan validation strictness — AI will auto-fix up to 3 iterations with gap feedback."
  [Recommended: Strict]
  Options:
    - Strict (10% D / 15% G / 5% endpoints miss → BLOCK)
    - Default (20% / 30% / 10%)
    - Loose (40% / 50% / 20%)
    - Custom (enter values)
```

Save mode + thresholds to blueprint-state.json.

### 2d-3: Validation checks (deterministic, no AI)

For current iteration N (starts at 1):

```
# Parse CONTEXT decisions
DECISIONS=$(grep -oE '^D-[0-9]+' "${PHASE_DIR}/CONTEXT.md" | sort -u)
# Parse PLAN tasks with goals-covered
TASKS=$(grep -oE '^## Task [0-9]+' "${PHASE_DIR}"/PLAN*.md | sort -u)
# Parse TEST-GOALS
GOALS=$(grep -oE '^## Goal G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | sort -u)
# Parse API-CONTRACTS endpoints
ENDPOINTS=$(grep -oE '^### (POST|GET|PUT|DELETE|PATCH) /' "${PHASE_DIR}/API-CONTRACTS.md" | sort -u)

# Cross-check (bidirectional — fixes I4):
# 1. Decisions ↔ Tasks (SPECS covered)
for D in $DECISIONS:
  if no task references D (check in PLAN*.md goals-covered or implements-decision attr):
    decisions_missing += D
# 2. Goals → Tasks (normal direction: task covers goal)
for G in $GOALS:
  if no task lists G in <goals-covered>:
    goals_missing += G
# 2-bis. Goals ← Tasks (orphan goals from 2b5 Implemented-by linkage)
#        A goal flagged "⚠ NONE" in TEST-GOALS.md means bidirectional linkage failed
#        → count it as missing even if some task coincidentally has its ID.
orphan_goals=$(grep -B1 "Implemented by:.*⚠ NONE" "${PHASE_DIR}/TEST-GOALS.md" | grep -oE '^## Goal G-[0-9]+')
goals_missing = unique(goals_missing ∪ orphan_goals)
# 3. Endpoints ↔ Tasks
for E in $ENDPOINTS:
  if no task creates handler for E:
    endpoints_missing += E

# Compute miss percentages (guard against zero division for empty phases)
decisions_miss_pct = (len(decisions_missing) / len(DECISIONS) * 100) if len(DECISIONS) > 0 else 0
goals_miss_pct = (len(goals_missing) / len(GOALS) * 100) if len(GOALS) > 0 else 0
endpoints_miss_pct = (len(endpoints_missing) / len(ENDPOINTS) * 100) if len(ENDPOINTS) > 0 else 0
```

### 2d-4: Gate decision

```
Threshold T = state.thresholds (per chosen mode)

if decisions_miss_pct <= T.decisions_miss_pct AND
   goals_miss_pct <= T.goals_miss_pct AND
   endpoints_miss_pct <= T.endpoints_miss_pct:
  → PASS (proceed to CrossAI review 2d-6)
else if iteration < max_auto_fix_iterations (default 3):
  → AUTO-FIX (step 2d-5)
else:
  → EXHAUSTED (step 2d-7)
```

### 2d-5: Auto-fix iteration

```
# Backup current plan
ITER=$(jq '.iterations | length' "$STATE_FILE")
NEXT_ITER=$((ITER + 1))
cp "${PHASE_DIR}"/PLAN*.md "${PHASE_DIR}/PLAN.md.v${NEXT_ITER}"

# Write gap report
cat > "${PHASE_DIR}/GAPS-REPORT.md" <<EOF
# Gaps Report — Iteration $NEXT_ITER (Phase ${PHASE})

## Missing decisions (plan↔SPECS)
${decisions_missing[@]}

## Missing goals (plan↔TEST-GOALS)
${goals_missing[@]}

## Missing endpoints (plan↔API-CONTRACTS)
${endpoints_missing[@]}

## Instruction for planner
APPEND tasks covering the missing items. DO NOT rewrite existing tasks.
Match each new task to 1 missing `P{phase}.D-XX` / `F-XX`, G-XX, or endpoint.
EOF

# Spawn planner via SlashCommand with gap context
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    PATCH MODE — do NOT replace existing PLAN.md. APPEND tasks covering gaps.
    Read ${PHASE_DIR}/GAPS-REPORT.md for specific missing items.
    Read ${PHASE_DIR}/PLAN.md for existing task structure.
    Add new tasks at the end as "Gap closure wave".
    Follow vg-planner-rules for task attribute schema.

# Update state
jq --arg n "$NEXT_ITER" --argjson gaps "$(cat ...)" \
   '.iterations += [{n: ($n|tonumber), gaps_found: $gaps, plan_backup: ("PLAN.md.v" + $n), status: "failed", timestamp: now|strftime("%FT%TZ")}] |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

# Re-run granularity check (2a post-check), bidirectional linkage (2b5 post-check),
# grep verify (2c), compile check (2c2)
# Then loop back to 2d-3 validation
```

### 2d-6: CrossAI review (when gate PASSED)

**Skip conditions (any match → go to 2d-8):**
- `config.crossai_clis` is empty (no CLIs configured)
- `$ARGUMENTS` contains `--skip-crossai` (per-run opt-out)

Prepare context file at `${VG_TMP}/vg-crossai-{phase}-blueprint-review.md`:

```markdown
# CrossAI Blueprint Review — Phase {PHASE}

Gate passed deterministic validation. CrossAI reviews qualitative:

## Checklist
1. Plan covers all CONTEXT decisions (quick re-verify)
2. API contracts consistent with plan tasks
3. ORG 6 dimensions addressed (Infra/Env/Deploy/Smoke/Integration/Rollback)
4. Contract fields reasonable between request/response pairs
5. No duplicate endpoints or conflicting field definitions
6. Acceptance criteria are testable (not vague)
7. Design-refs linked appropriately (if config.design_assets non-empty)

## Verdict Rules
- pass: all checks pass, score >=7
- flag: minor quality concerns, score >=5
- block: missing/wrong content (deterministic gate should have caught — CrossAI as safety net)

## Artifacts
---
[CONTEXT.md content]
---
[PLAN*.md content — concatenated]
---
[API-CONTRACTS.md content]
---
[TEST-GOALS.md content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="blueprint-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

**Handle findings:**
- Minor → auto-fix (update contracts or plan)
- Major/Critical → present to user via AskUserQuestion, re-verify if fixed

**MANDATORY when escalating CrossAI concerns to user (AskUserQuestion):**

For EACH user-judgment concern (e.g., schema-vs-storage choice, architectural fork, test-strategy
trade-off), the orchestrator MUST present options with an explicit recommended option. Pattern:

1. **Pick the recommended option** before showing the question — base on:
   - CrossAI consensus (if 2+ CLIs converge on same fix → that's the recommendation)
   - Project context (CONTEXT.md decision wins over post-hoc PLAN drift)
   - Codebase reality (if existing pattern in repo, prefer aligning to it)
   - Security / correctness > convenience
2. **Order options with recommended FIRST**, label with " (Recommended)" suffix.
3. **Explain WHY recommended** in the option's `description` field — not just what it is.
4. **Do NOT ask without recommendation** — silent multi-option choices put rationalization burden on user.
   Per global guidance: "If you recommend a specific option, make that the first option in the
   list and add '(Recommended)' at the end of the label."

Bad example (no recommendation):
```
AskUserQuestion: "Refresh storage backend?"
  - Redis-only
  - Mongo collection
  - Both
```

Good example (with recommendation):
```
AskUserQuestion: "Refresh token storage backend? Recommend Both — Mongo source-of-truth survives
restart + Redis JTI cache provides fast revocation. CrossAI Codex flagged single-layer as conflict-prone."
  - Both (Mongo persist + Redis cache) (Recommended)  — production-grade, audit-friendly, fast revocation
  - Mongo only — simpler, slower revocation (each refresh checks DB)
  - Redis only — fast but loses sessions on restart
```

Apply this pattern to ALL CrossAI-escalation questions. The user can still pick a non-recommended
option (or "Other") — the recommendation just provides a default path so they don't have to
re-derive the analysis CrossAI just did.

### 2d-7: Exhausted — user intervention

```
echo "Plan validation exhausted after ${max_auto_fix_iterations} iterations."
echo "Remaining gaps:"
echo "  Decisions missing: ${decisions_missing[@]}"
echo "  Goals missing: ${goals_missing[@]}"
echo "  Endpoints missing: ${endpoints_missing[@]}"
echo ""
echo "Options:"
echo "  (a) /vg:blueprint ${PHASE} --override        → accept gaps, proceed with warning"
echo "  (b) Edit PLAN.md manually → /vg:blueprint ${PHASE} --from=2d"
echo "  (c) /vg:scope ${PHASE}                       → refine SPECS/CONTEXT (root cause may be spec gap)"

# Mark state exhausted, preserve for resume
jq '.steps_status["2d_validation"] = "exhausted"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
exit 1
```

### 2d-8: PASSED — finalize state

```
jq '.steps_status["2d_validation"] = "completed" |
    .current_step = "3_complete" |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
```

Display:
```
Plan validation: PASSED (iteration $N/${max})
  Decisions covered: $C/$total ($pct%)
  Goals covered: $C/$total ($pct%)
  Endpoints covered: $C/$total ($pct%)
  Mode: $MODE
CrossAI review: $verdict ($score/10)
Proceeding to commit.
```
</step>

<step name="3_complete">
Count plans, endpoints, decisions. Display:
```
Blueprint complete for Phase {N}.
  Plans: {N} created
  API contracts: {N} endpoints defined
  Verify 1 (grep): {verdict}
  CrossAI: {verdict} ({score}/10)
  Next: /vg:build {phase}
```

Commit all artifacts:
```bash
git add ${PHASE_DIR}/PLAN*.md ${PHASE_DIR}/API-CONTRACTS.md ${PHASE_DIR}/crossai/
git commit -m "blueprint({phase}): plans + API contracts — CrossAI {verdict}"
```
</step>

</process>

<success_criteria>
- CONTEXT.md verified as prerequisite
- PLAN*.md created via GSD planner with ORG check
- API-CONTRACTS.md generated from code + CONTEXT
- Verify 1 (grep) passed — contracts match code
- CrossAI reviewed (or skipped if no CLIs)
- All artifacts committed
- Next step guidance shows /vg:build
</success_criteria>
