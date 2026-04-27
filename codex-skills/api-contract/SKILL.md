---
name: "api-contract"
description: "Generate, verify (grep), and runtime-verify (curl) API contracts — used by blueprint, audit, and test steps"
metadata:
  short-description: "Generate, verify (grep), and runtime-verify (curl) API contracts — used by blueprint, audit, and test steps"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$api-contract`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# API Contract Management

Generate and verify API contracts across the V5 pipeline. Called at 3 points:
- **blueprint 2b:** Generate API-CONTRACTS.md from code/specs
- **audit 4a:** Verify code follows contracts (grep)
- **test 5b:** Verify runtime responses match contracts (curl)

## Context Budget

Per invocation: max 300 lines. Read only the specific artifacts needed for that mode.

## Mode: Generate (blueprint 2b)

**Input:** CONTEXT.md + code_patterns paths from config
**Output:** `${PHASE_DIR}/API-CONTRACTS.md`

### Process

1. **Detect existing API code:**
   ```bash
   API_ROUTES="${config.code_patterns.api_routes}"
   if [ -n "$API_ROUTES" ] && [ -d "$API_ROUTES" ]; then
     # BE exists — extract from Zod schemas
     grep -r "z\.\(object\|string\|number\|boolean\|array\|enum\)" "$API_ROUTES" --include="*.ts" --include="*.js" -l
     # For each schema file: extract field names, types, required status
   fi
   ```

2. **Detect frontend forms/tables:**
   ```bash
   WEB_PAGES="${config.code_patterns.web_pages}"
   if [ -n "$WEB_PAGES" ] && [ -d "$WEB_PAGES" ]; then
     grep -r "name=\"\|id=\"\|data-field=" "$WEB_PAGES" --include="*.tsx" --include="*.jsx" --include="*.html" -l
     # For each form: extract field names from input elements
   fi
   ```

3. **Cross-reference with CONTEXT.md decisions:**
   - Each decision (D-XX) that mentions data/CRUD → must have at least one endpoint
   - Each form in HTML → must have a submit endpoint
   - Each table → must have a list/fetch endpoint

4. **Generate contract file:**

```markdown
# API Contracts — Phase {PHASE}

Generated by: /vg:blueprint (step 2b)
Source: {BE Zod schemas | FE HTML forms | AI draft from CONTEXT}

## Endpoint Summary

| # | Method | Endpoint | Purpose | Decision |
|---|--------|----------|---------|----------|
| 1 | GET | /api/sites | List sites | D-01 |
| 2 | POST | /api/sites | Create site | D-01 |

## Contract Details

### EP-01: GET /api/sites

**Request:**
| Field | Type | Required | Source |
|-------|------|----------|--------|
| page | number | no | query param |
| limit | number | no | query param |
| status | string | no | query param, enum: active/pending/paused |

**Response:**
| Field | Type | Description | Source |
|-------|------|-------------|--------|
| data | array | Site objects | Zod: SiteSchema |
| data[].id | string | Site ID | Zod |
| data[].name | string | Site name | Zod |
| data[].domain | string | Site domain | Zod |
| data[].status | string | active/pending/paused | Zod enum |
| total | number | Total count | Zod |
| page | number | Current page | Zod |

**Decision:** D-01 (Site Management)
```

## Mode: Verify-Grep (audit 4a)

**Input:** API-CONTRACTS.md + source code
**Output:** Mismatch report (inline, not file)

### Process

1. Read API-CONTRACTS.md, extract all endpoints + fields
2. For each endpoint:
   ```bash
   # Check BE route exists
   grep -r "(get|post|put|delete|patch).*'${ENDPOINT}'" "$API_ROUTES" --include="*.ts" --include="*.js"

   # Check Zod schema has all response fields
   # For each field in contract response:
   grep -r "${FIELD_NAME}" "$SCHEMA_FILE"

   # Check FE calls this endpoint
   grep -r "${ENDPOINT}" "$WEB_PAGES" --include="*.tsx" --include="*.jsx" --include="*.ts"

   # Check FE reads correct response fields
   # For each field in contract response:
   grep -r "\.${FIELD_NAME}\b\|data\.${FIELD_NAME}\|response\.${FIELD_NAME}" "$WEB_PAGES"
   ```
3. Report mismatches: `{endpoint} — {field} missing in {BE|FE}`
4. Any mismatch → return BLOCK status

## Mode: Verify-Curl (test 5b)

**Input:** API-CONTRACTS.md + running server
**Output:** Mismatch report (inline)

### Process

1. Read API-CONTRACTS.md, extract all GET endpoints (safe to curl)
2. For each GET endpoint:
   ```bash
   # Curl the endpoint
   RESPONSE=$(run_on_target "curl -sf '${BASE_URL}${ENDPOINT}'" 2>/dev/null)

   # Extract actual response keys
   echo "$RESPONSE" | jq -r 'if type == "object" then keys[] else .[0] | keys[] end' > ${VG_TMP}/actual_keys

   # Compare with contract
   diff <(echo "$EXPECTED_KEYS" | sort) <(sort ${VG_TMP}/actual_keys)
   ```
3. For POST/PUT/DELETE: verify endpoint responds (status code only, don't mutate)
   ```bash
   STATUS=$(run_on_target "curl -sf -o /dev/null -w '%{http_code}' -X OPTIONS '${BASE_URL}${ENDPOINT}'" 2>/dev/null)
   # 200/204/405 = endpoint exists. 404 = missing.
   ```
4. Report mismatches. Any missing endpoint or field → BLOCK.

## Anti-Patterns

- NEVER invent fields not in code or CONTEXT — only document what exists or is decided
- NEVER skip frontend field verification — FE→BE field mismatch is the #1 bug source
- NEVER verify POST/PUT by actually POSTing — use OPTIONS or HEAD for existence check
- NEVER exceed 300 lines context — read only relevant schemas, not entire codebase
