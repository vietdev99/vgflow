<step name="phase2_7_url_state_sync" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.7: URL state sync declaration check (Phase J)

→ `narrate_phase "Phase 2.7 — URL state sync" "Kiểm tra interactive_controls trong TEST-GOALS"`

**Purpose:** validate every list/table/grid view goal in TEST-GOALS.md
declares `interactive_controls` block (filter/sort/pagination/search +
URL sync assertion). This is the static-side complement to runtime
browser probing — declaration must exist before runtime can verify.

**CRUD surface precheck (v2.12):** before URL-state checks, validate
`${PHASE_DIR}/CRUD-SURFACES.md`. Review compares runtime observations against
the resource/platform contract first, then uses `interactive_controls` as the
web-list extension pack. Missing CRUD contract means the reviewer has no
authoritative list of expected headings, filters, columns, states, row actions,
delete confirmations, or security/abuse expectations.

```bash
CRUD_FLAGS=""
[[ "${ARGUMENTS:-}" =~ --allow-no-crud-surface ]] && CRUD_FLAGS="--allow-missing"
CRUD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" ${CRUD_FLAGS} \
    > "${PHASE_DIR}/.tmp/crud-surface-review.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD surface contract missing/incomplete — see ${PHASE_DIR}/.tmp/crud-surface-review.json"
    echo "   Fix blueprint artifact CRUD-SURFACES.md or rerun /vg:blueprint."
    exit 2
  fi
fi
```

**Why:** modern dashboard UX baseline (executor R7) requires list view
state synced to URL search params. Without declaration, AI executors
build local-state-only filters and ship apps that lose state on refresh.
This validator catches the gap at /vg:review time, before user sees it.

**Severity:** config-driven via `vg.config.md → ui_state_conventions.severity_phase_cutover`
(default 14). Phase number < cutover → WARN (grandfather). Phase ≥ cutover
→ BLOCK (mandatory). Override with `--allow-no-url-sync` to log soft OD
debt entry.

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-sync.py \
  --phase "${PHASE_NUMBER}" \
  --enforce-required-lenses \
  > "${PHASE_DIR}/.tmp/url-state-sync.json" 2>&1
URL_SYNC_RC=$?

if [ "${URL_SYNC_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-no-url-sync"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-sync \
      --reason "URL state sync waived for ${PHASE_NUMBER} via --allow-no-url-sync (soft debt logged)"
    echo "⚠ URL state sync gate waived via --allow-no-url-sync"
  else
    echo "⛔ URL state sync declarations missing — see ${PHASE_DIR}/.tmp/url-state-sync.json"
    cat "${PHASE_DIR}/.tmp/url-state-sync.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_sync" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-sync.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Add interactive_controls blocks to TEST-GOALS.md per goal."
    echo "     Schema: .claude/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md (Phase J section)."
    echo "  2. If state is genuinely local-only, declare url_sync: false + url_sync_waive_reason."
    echo "  3. Override (last resort): re-run with --allow-no-url-sync (logs soft OD debt)."
    exit 2
  fi
fi
```

**Future runtime probe (deferred to v2.9):** once RUNTIME-MAP.json is
populated by phase 2 browser discovery, a follow-up validator can click
each declared control via MCP Playwright + snapshot URL pre/post +
assert reload-survives. Static declaration check is the foundation that
makes runtime probe meaningful.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_7_url_state_sync" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_7_url_state_sync.done"`
</step>

<step name="phase2_8_url_state_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.8: URL state runtime probe (v2.7 Phase A)

→ `narrate_phase "Phase 2.8 — URL state runtime probe" "Click từng control + snapshot URL để verify declaration vs implementation"`

**Purpose:** verify that the static `interactive_controls` declarations
(checked at phase 2.7) match actual application behaviour. AI drives MCP
Playwright through every declared control, captures URL params before/after
each interaction, writes the result to
`${PHASE_DIR}/url-runtime-probe.json`. Validator reads that artifact and
flags coverage gaps (WARN) or declaration drift (BLOCK).

**Why:** static declarations close ~50% of URL-state bugs; runtime probe
catches the remaining drift class — declaration says `?status=...` but
the route handler ships `?state=...`, or the filter pretends to sync but
no `pushState` actually fires.

**Skip conditions:**
- No goal in TEST-GOALS.md has `interactive_controls.url_sync: true` → skip silently.
- `${RUN_ARGS}` contains `--skip-runtime` → run validator with the same flag (logs OD debt).
- Browser environment unavailable (no MCP Playwright) → invoke validator with `--skip-runtime`.

### 2.8a Drive the probe (AI agent task)

For every goal in `${PHASE_DIR}/TEST-GOALS.md` that declares
`interactive_controls.url_sync: true`:

1. Determine the goal's route from `${PHASE_DIR}/RUNTIME-MAP.json` (key
   matching the goal id) or, when the goal frontmatter carries an explicit
   `route:` field, prefer that.
2. Authenticate as `goal.actor` (default `admin`) using the standard
   review-phase auth helper.
3. Navigate to the route. Wait for the list/table/grid to be visible.
4. For every entry in the goal's `interactive_controls`:
   - **filter** — pick the first declared `values[0]`, click the filter
     control, snapshot URL, then prove visible rows and/or network response
     match the selected value. Example: `status=pending` must not show flagged,
     approved, rejected, or failed rows unless the contract explicitly says
     flagged is an orthogonal boolean.
   - **sort** — apply the first declared column, snapshot URL, then prove row
     order matches the declared direction.
   - **pagination** — click page 2 (or scroll once for `infinite-scroll`),
     snapshot URL, then prove the result window changed without duplicated
     first-page rows.
   - **search** — type a representative query, wait `debounce_ms + 100ms`,
     snapshot URL, then prove returned rows contain/match the query.
5. Also compare the observed route against `${PHASE_DIR}/CRUD-SURFACES.md`
   `platforms.web.list`: heading/description presence, declared table columns,
   row actions, empty/loading/error/unauthorized states where reachable, and
   delete confirmation if a delete action is declared.
6. Append one entry per goal to `url-runtime-probe.json`.

**Artifact schema** (`${PHASE_DIR}/url-runtime-probe.json`):

```json
{
  "generated_at": "2026-04-26T10:30:00Z",
  "goals": [
    {
      "goal_id": "G-01",
      "url": "/admin/campaigns",
      "controls": [
        {
          "kind": "filter",
          "name": "status",
          "value": "active",
          "url_before": "https://app.local:5173/admin/campaigns",
          "url_after": "https://app.local:5173/admin/campaigns?status=active",
          "url_params_after": {"status": "active"},
          "result_semantics": {
            "passed": true,
            "rows_checked": 20,
            "violations": []
          }
        }
      ]
    }
  ]
}
```

`kind` is one of `filter | sort | pagination | search`. `name` matches the
declared control name (or normalised — `page` for pagination, `search` for
search, `sort` for sort). `url_params_after` is the parsed search-param
dict. For filters, `result_semantics` is mandatory; URL-only success is not
enough because it misses the class where a Pending tab still renders Flagged
records.

### 2.8b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"

EXTRA_FLAGS=""
if [[ "${RUN_ARGS:-}" == *"--skip-runtime"* ]] || [[ -z "${VG_BROWSER_AVAILABLE:-1}" ]]; then
  EXTRA_FLAGS="--skip-runtime"
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-runtime.py \
  --phase "${PHASE_NUMBER}" ${EXTRA_FLAGS} \
  > "${PHASE_DIR}/.tmp/url-state-runtime.json" 2>&1
URL_RUNTIME_RC=$?

if [ "${URL_RUNTIME_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-runtime-drift"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-runtime \
      --reason "URL state runtime drift waived for ${PHASE_NUMBER} via --allow-runtime-drift (soft debt logged)"
    echo "⚠ URL state runtime drift waived via --allow-runtime-drift"
  else
    echo "⛔ URL state runtime drift detected — see ${PHASE_DIR}/.tmp/url-state-runtime.json"
    cat "${PHASE_DIR}/.tmp/url-state-runtime.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_runtime" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-runtime.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Implementation drift — fix the route handler / UI so declared url_param actually appears in URL after interaction."
    echo "  2. Declaration drift — declared url_param is wrong; update TEST-GOALS.md interactive_controls block."
    echo "  3. Override (last resort): re-run with --allow-runtime-drift (logs soft OD debt)."
    exit 2
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_8_url_state_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_8_url_state_runtime.done"`
</step>

<step name="phase2_9_error_message_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.9: API error-message runtime lens

→ `narrate_phase "Phase 2.9 — API error-message runtime lens" "Trigger API error paths and prove toast/form errors show API body messages, not HTTP transport text"`

**Purpose:** catch the P3.2 class of bug where the backend returns a useful
domain/validation message but the frontend toast shows `Request failed with
status 403`, `statusText`, or another generic transport message.

This is a plugin/lens inside review, not a second full browser discovery pass.
Reuse the authenticated browser session and routes already discovered by
Phase 2. For each API+UI mutation or protected action that can safely fail,
drive one negative path and record API body + visible UI message.

### 2.9a Drive the probe

For API+UI phases:

1. Read `${PHASE_DIR}/INTERFACE-STANDARDS.md`, `${PHASE_DIR}/API-DOCS.md`,
   `${PHASE_DIR}/API-CONTRACTS.md`, and `${PHASE_DIR}/RUNTIME-MAP.json`.
2. Pick safe negative paths in this order:
   - validation error on create/update form
   - unauthorized/forbidden path for a role-gated action
   - domain rule error that does not mutate durable data
3. Capture the network response JSON for the failed request.
4. Capture visible toast/banner/form error text from the UI.
5. Compare using the standard message priority:
   `error.user_message -> error.message -> message -> network_fallback`.
6. Write `${PHASE_DIR}/error-message-probe.json`.

**Artifact schema**:

```json
{
  "generated_at": "2026-05-02T10:30:00Z",
  "checks": [
    {
      "goal_id": "G-01",
      "route": "/admin/billing/topup-queue",
      "action": "submit invalid filter or mutation",
      "request": {"method": "POST", "path": "/api/example"},
      "status": 400,
      "api_error": {
        "code": "VALIDATION_ERROR",
        "message": "Amount is required",
        "user_message": "Amount is required"
      },
      "api_user_message": "Amount is required",
      "visible_message": "Amount is required",
      "passed": true
    }
  ]
}
```

If a phase has API contracts and UI goals but no reachable negative path, write
the artifact with `checks: []` plus `blocked_reason`, then run the diagnostic.
Do not silently skip.

### 2.9b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null

"${PYTHON_BIN}" .claude/scripts/validators/verify-error-message-runtime.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/error-message-runtime.json" 2>&1
ERROR_MESSAGE_RC=$?

if [ "${ERROR_MESSAGE_RC}" != "0" ]; then
  echo "⛔ API error-message runtime lens failed — see ${PHASE_DIR}/.tmp/error-message-runtime.json"
  cat "${PHASE_DIR}/.tmp/error-message-runtime.json"
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.error_message_runtime" \
      --phase-dir "$PHASE_DIR" \
      --input "${PHASE_DIR}/.tmp/error-message-runtime.json" \
      --out-md "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" 2>/dev/null || true
  fi
  echo ""
  echo "Fix options:"
  echo "  1. Backend drift — return the standard API error envelope from INTERFACE-STANDARDS.md."
  echo "  2. Frontend drift — use shared error adapter: error.user_message || error.message, never statusText/AxiosError.message."
  echo "  3. Probe gap — rerun full review with a safe negative path and write error-message-probe.json."
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_9_error_message_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_9_error_message_runtime.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_9_error_message_runtime 2>/dev/null || true
```
</step>