---
name: vg-haiku-scanner
description: Exhaustive view scanner — workflow followed by Haiku agents spawned from /vg:review. Fixed protocol, zero discretion to skip.
user-invocable: false
---

# Haiku Scanner Workflow

You are a scanner agent spawned by `/vg:review`. Your ONLY job: exhaustively scan ONE view and write results to disk.

## ⛔ Conformance contract: scanner-report-contract

This skill produces output consumed by the COMMANDER (Opus running /vg:review Phase 4). You are a SCANNER — you OBSERVE and REPORT. Severity, verdicts, prescriptions are commander's job, NOT yours.

Read: `vg:_shared:scanner-report-contract` (skill). Key rules inlined below.

### Banned vocabulary (case-insensitive — output rejected if present)

| BANNED | Use instead |
|---|---|
| `bug`, `broken`, `wrong`, `incorrect` | `expected X, observed Y` |
| `critical`, `major`, `minor`, `severe` | OMIT — commander assigns severity |
| `should`, `must`, `need to`, `needs` | drop prescription, log fact only |
| `fix`, `repair`, `patch` | OMIT — commander prescribes action |
| `obviously`, `clearly`, `apparently` | drop qualifier; state observation directly |

### Allowed match enum

Use ONLY: `yes` | `no` | `partial` | `unknown`. NOT `failed`, `passed`, `error`.

### Schema discipline

- `match: no` is fine (factual: observation differed from expected_per_lens).
- DO NOT add `severity:` field to error/issue entries. Commander assigns severity post-adjudication.
- `errors[]` array in legacy schema below has been deprecated for severity field — emit `match: no` + put diagnostic facts in `evidence.console_errors` / `evidence.network_requests` instead.

**Migration note:** older versions of this skill had `errors[].severity` ("high"/"critical") in output. v2.42.7+ removes severity from scanner output. Commander reads `match: no` + evidence + cross-references TEST-GOALS to assign severity.

## Evidence Tier System (v2.42.8+)

Per scanner-report-contract Section 2.5, evidence fields organized into tiers. This skill captures **Tier A + B + E by default**, with C / F opt-in based on goal context.

| Tier | Default | Capture instructions |
|---|---|---|
| **A** Always | ✓ | Already captured by browser MCP automatic context: `screenshot`, `network_requests`, `console_errors`, `dom_changed`, `url_*`, `elapsed_ms`. PLUS new fields: `page_title` (`document.title`), `toast` (query toast selectors per `.claude/scripts/scanner-evidence-capture.js > captureToast`), `http_status_summary` (run `summarizeHttpStatus(network_requests)` after each step). |
| **B** Form/CRUD | ✓ when step has form/list mutation | Run `captureFormValidationErrors`, `captureSubmitButtonState`, `captureLoadingIndicator`, `captureRowCount`, `captureFieldValue` from helper before+after submit. For mutations: do `db_read_after_write` follow-up GET to verify persistence (replaces old persistence_probe). |
| **C** Security | When goal touches auth/role/RBAC | `captureCookiesFiltered` (names only, NO values), `captureAuthStateHeuristic`, run `inspectRequestSecurityHeaders` + `inspectResponseSecurityHeaders` on captured network_requests. |
| **D** Realtime | Skip (instrumentation required app-side) | If `window.__vg_ws_log` exists, `captureWebSocketFrames`. Otherwise return `null`. |
| **E** Visual/A11y | ✓ on major UI state change | `captureFocusState`, `captureAriaState` (per relevant element), `captureTabOrder`. `viewport_size` from page snapshot. `a11y_tree_excerpt` from MCP `browser_snapshot` output (trimmed). |
| **F** Storage | When goal involves state persistence | `captureStorageKeys` (keys only, NEVER values — PII/token risk), `captureIndexedDBs`, `captureStoreSnapshot('__VG_STORE__')` if exposed. |
| **G** Mobile | Only when MODE=mobile | Replaces A-E. Use Maestro hierarchy diff + screenshot diff per scanner-report-contract Section 2.5. |

**Capture flow per step** (within STEP 4 element interaction):
```
1. Pre-action snapshot (Tier A always; Tier B if form; Tier E if focus-relevant)
2. Perform action (click/fill/etc)
3. Wait for stable (network idle OR 5s timeout)
4. Post-action capture (same tiers as pre)
5. Compute deltas (row_count_delta, field_value_delta) before merging into observation
6. Set match: yes|no|partial|unknown based on expected_per_lens vs observed
```

**Helper file:** `.claude/scripts/scanner-evidence-capture.js` exports JS snippets for each `captureXxx`. Pass to MCP `browser_evaluate({function: <snippet>})`. Some functions are pure JS (run on captured network array, no eval): `summarizeHttpStatus`, `inspectRequestSecurityHeaders`, `inspectResponseSecurityHeaders`.

**Empty fields = facts:** if a tier's capture returns nothing (e.g., no toast visible), emit the field with empty/null value. Empty IS a fact. Omitting confuses commander into thinking scanner didn't try.

## Arguments (injected by orchestrator)

### Common (both modes)
```
MODE           = "web" | "mobile"      (dispatch gate — defaults to "web" when absent)
PHASE          = "{phase_number}"
VIEW_SLUG      = "{filesystem-safe slug: goal id or URL}"
PHASE_DIR      = "{absolute path to phase planning dir}"
SCREENSHOTS_DIR= "{absolute path for screenshots}"
GOAL_ID        = "{G-XX id this scan is verifying}"
GOAL_TITLE     = "{goal title from TEST-GOALS.md}"
GOAL_CRITERIA  = "{success criteria text — multi-line allowed}"
```

### Web mode (MODE=web — existing behavior)
```
VIEW_URL       = "{absolute or relative URL}"
ROLE           = "{role name from config.credentials}"
BOUNDARY       = "{URL glob pattern — do NOT navigate outside}"
DOMAIN         = "{e.g. http://localhost:5173}"
EMAIL          = "{login email}"
PASSWORD       = "{login password}"
FULL_SCAN      = {true|false — if true, skip sidebar suppression}
```

### Mobile mode (MODE=mobile — NEW)
```
PLATFORM       = "ios" | "android"
DEVICE_NAME    = "{simulator or emulator name}"
SCREENSHOT_PATH= "{path to PNG captured by maestro-mcp discover}"
HIERARCHY_PATH = "{path to Maestro hierarchy JSON}"
BUNDLE_ID      = "{app bundle identifier}"
ROLE           = "{role name from config.credentials — for narration only;
                   mobile auth state is pre-seeded before discover}"
```

## CONNECTION (mandatory first step)

**Dispatch on MODE:**

### Web mode
```bash
PLAYWRIGHT_SERVER=$(bash "~/.claude/playwright-locks/playwright-lock.sh" claim "haiku-scan-{VIEW_SLUG}-$$")
```
Use `mcp__${PLAYWRIGHT_SERVER}__` as prefix for ALL browser tools. Release lock in CLEANUP.

### Mobile mode
No Playwright lock. The orchestrator already launched the app on the target
device via `maestro-mcp launch-app` and captured the snapshot via
`maestro-mcp discover` before spawning this scanner. This agent is
**artifact-only** — it reads the captured screenshot + hierarchy and does
NOT drive the device directly. If additional interaction is needed (e.g.
follow-up taps), the Haiku agent reports that in output.blocking_reasons
and the orchestrator decides whether to re-run `maestro-mcp discover`
with a different flow.

Skip STEP 1 (Login + Navigate), STEP 1.5 (Suppress Sidebar), STEP 2
(Scroll). Begin at STEP 3 (Initial Snapshot) using the pre-captured
artifacts.

## WORKFLOW — FOLLOW EXACTLY

### STEP 1: Login + Navigate

1. `browser_navigate` to `{DOMAIN}/login`
2. Fill email/password, click submit, wait for redirect
3. `browser_navigate` to `{VIEW_URL}`
4. `browser_wait_for` network idle (3s max)

### STEP 1.5: Suppress Sidebar (skip if FULL_SCAN=true)

Run ONCE before first snapshot. Uses **geometry + layout heuristics** (NOT broad tag match) to avoid hiding legitimate content like breadcrumbs, tab bars, pagination nav inside main content.

```js
browser_evaluate: `
  const main = document.querySelector('main, [role="main"], #main-content, .main-content, #content');
  if (!main) return { hidden: [], reason: 'no_main_found' };

  const hidden = [];
  function isSidebar(el) {
    if (el === main || main.contains(el) || el.contains(main)) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    // Left sidebar: tall column, narrow, at left edge
    if (r.x < 50 && r.height > innerHeight * 0.6 && r.width < 400 && r.width > 50) return 'left';
    // Top app bar/header: thin band at top, wide
    if (r.y < 10 && r.height < 120 && r.width > innerWidth * 0.5 && el.querySelector('nav, [role="navigation"]')) return 'top';
    // Right drawer (less common): tall column at right edge
    if ((innerWidth - r.right) < 50 && r.height > innerHeight * 0.6 && r.width < 400) return 'right';
    return false;
  }

  document.querySelectorAll('body > *, body > * > *').forEach(el => {
    const why = isSidebar(el);
    if (why) {
      el.setAttribute('data-vg-hidden', '1');
      hidden.push({ tag: el.tagName, id: el.id || null, cls: (el.className || '').substring(0, 40), why });
    }
  });

  if (hidden.length) {
    const s = document.createElement('style');
    s.id = '__vg_sidebar_hide';
    s.textContent = '[data-vg-hidden]{display:none !important;}';
    document.head.appendChild(s);
  }
  return { hidden, count: hidden.length };
`
```

Record `hidden[]` in scan output under `sidebar_suppressed`.

**Restore sidebar** only when needed (to click a sidebar link to navigate):
```js
browser_evaluate: "document.getElementById('__vg_sidebar_hide')?.remove(); document.querySelectorAll('[data-vg-hidden]').forEach(el => el.removeAttribute('data-vg-hidden'));"
```
After navigate → re-run Step 1.5 to suppress again.

Modals/toasts render outside sidebar → still visible in snapshots normally.

### STEP 2: Scroll Full Page

Scroll down 500px, wait 300ms, repeat until scroll position stops changing. Captures lazy-loaded content.

### STEP 3: Initial Snapshot

### STEP 3 — MODE=web (existing path)

`browser_snapshot` → build working list of interactive elements.

For each: `{ref, role, name, states (disabled/checked/expanded), visible}`.

### STEP 3 — MODE=mobile (NEW)

No browser snapshot. Read the artifacts the orchestrator already captured:

```bash
test -f "${SCREENSHOT_PATH}" || { echo "screenshot missing"; exit 1; }
test -f "${HIERARCHY_PATH}"  || { echo "hierarchy missing"; exit 1; }
```

Parse `${HIERARCHY_PATH}` (Maestro view hierarchy JSON) into the SAME
working-list schema used by web:

| Web field     | Mobile source                                          |
|---------------|--------------------------------------------------------|
| `ref`         | synthesize: `{platform}-{node_id}` from hierarchy      |
| `role`        | `accessibilityRole` (iOS) / `className` (Android) → map: Button/TextField/Text/Image/Switch/... |
| `name`        | `text` / `accessibilityLabel` / `contentDescription`   |
| `states`      | `enabled`, `checked`, `focused`, `selected` flags      |
| `visible`     | `frame.width > 0 && frame.height > 0` && `visible:true`|

Role mapping (authoritative — DO NOT invent other mappings):

```
iOS accessibilityTrait → web role
  button, link           → button / link
  searchField            → textbox
  staticText, header     → text / heading
  image                  → img
  toggle, switch         → switch
  selected               → (add to states)

Android className → web role
  android.widget.Button  → button
  android.widget.EditText→ textbox
  android.widget.TextView→ text
  android.widget.Switch  → switch
  android.widget.ImageView→ img
  <ComposeView>          → inspect `semantics.role` field for Jetpack Compose
```

Load screenshot dimensions for coordinate reference only (do NOT run
vision inference in this skill — that's the orchestrator's call if it
wants image-based verification). The hierarchy is the authoritative
element list.

Emit the same `{ref, role, name, states, visible}` record per visible
element so downstream STEP 5 writes identical schema.

### STEP 4: Visit EVERY Element (no skipping)

**MODE=web:** existing interaction loop (click/fill/toggle/etc.).

**MODE=mobile:** THIS SKILL DOES NOT DRIVE THE DEVICE. The scan is
read-only against the pre-captured snapshot. Output per-element:

- `action`: `observed` (no interaction performed)
- `outcome`: `captured` (present in hierarchy) | `not_reachable` (frame off-screen or disabled)

If follow-up interaction is needed to verify the goal (e.g. tap "Login"
then observe the next screen), set:
- `blocking_reason: "needs_interaction"`
- `suggested_next: "maestro-mcp discover --flow {next_flow}"`

The orchestrator reads `blocking_reason` and decides whether to spawn
a follow-up discover+scan round. This keeps the Haiku scanner cheap
and stateless; complex multi-step verification lives in `/vg:test`
where Maestro can run declarative YAML flows with assertions.

**Universal rule after EVERY click:**
- Re-snapshot
- Diff vs working list → any NEW elements? Append them. Continue iteration.
- Catches: accordion content, inline expansions, lazy-loaded sections, conditional buttons.

**Capture stable selectors (v2.43.5 — i18n-resilient codegen):**
For every interactive element observed (button/link/input/select/form/tab/modal/table-row), record these attributes from the DOM snapshot in addition to `name` and `role`:

- `testid` — value of `data-testid` attribute (or whatever `vg.config.md > test_ids.prop_name` specifies). Empty string if absent. **Critical** — downstream `/vg:test` codegen uses this for stable selectors over `getByText`.
- `aria_label` — `aria-label` attribute value when present (fallback selector).
- `htmlFor` — when element is a `<label>`, record `htmlFor` so codegen can pair label↔input via `getByLabel`.

When extracting from `browser_snapshot` YAML output, look for these props in the element's attribute list. Example snapshot fragment:
```yaml
- button "Đăng nhập" [ref=e19]:
    /data-testid: "login-submit-btn"
    /aria-label: "Đăng nhập vào hệ thống"
```

Map to scan output:
```json
{
  "ref": "e19",
  "role": "button",
  "name": "Đăng nhập",
  "testid": "login-submit-btn",
  "aria_label": "Đăng nhập vào hệ thống"
}
```

If `testid` is empty for an interactive element, the scan still proceeds — but downstream codegen will emit `getByText("Đăng nhập")` with a fragility warning. The `verify-i18n-vs-testid.py` validator surfaces these gaps to user post-review.

Per element type:

| Type | Action |
|------|--------|
| button / link / menuitem / accordion | Click → wait 500ms → snapshot → console + network check → screenshot. If modal opened → recurse STEP 3+4 inside modal → close. If navigated within boundary → record as `sub_view_discovered` → navigate back. If outside boundary → record skipped + reason → navigate back. |
| tab / segmented-control / pill-nav | Click EACH tab sequentially. For each tab panel: STEP 3+4 recurse. |
| dropdown / menu / popover (action menus) | Open → list items → click EACH → record outcome → close between items. |
| textbox / input / textarea | Record type/name/placeholder/required/pattern. Fill appropriate test data (email→`scan-test@example.com`, number→`9.99`, url→`scan-test.example.com`, phone→`+1234567890`, date→`2026-01-15`, name field→`Scan Test Item`, other→`scan-test-data`). |
| select / combobox | Open → record option count + first 5 labels → select first non-placeholder. |
| checkbox / radio / switch / toggle | Toggle → record state → toggle back. |
| table / list with rows | Scroll container to count rows. Click actions on FIRST row only (representative sample). If row opens detail/modal → recurse. |
| disabled / hidden | Record state. Try enable by selecting checkbox/row nearby → re-snapshot. If enables → interact. Else → mark stuck with `enable_condition: unknown`. |
| form (inputs + submit button) | Fill ALL fields (rules above) → click submit → record `{fields_filled, submit_result, api_response, console_errors, toast}`. If confirm dialog → Cancel FIRST, then re-trigger + OK. **After submit, MANDATORY Persistence Probe (Layer 4) — see sub-table below.** |

**Persistence Probe sub-workflow (MANDATORY after every form submit):**

Layer 1 (toast) + Layer 2 (API 2xx) + Layer 3 (no console error) ARE NOT ENOUGH. Bug pattern "ghost save / phantom persist" passes all three:
- Toast fires before API confirm (client optimistic dispatch)
- API returns 200 with empty/default body (silent backend skip)
- Console clean because no exception thrown

Only `refresh + re-read + diff` detects ghost save.

| Sub-step | Action | Record |
|---|---|---|
| A. Pre-snapshot | BEFORE clicking submit: read current field values + DOM text of related cells/rows. Store as `persistence_probe.pre[]`. Example: if editing a user, read `role` dropdown value + row[N].role cell text. If creating a new entity, record current row count. | `pre: [{field: "role", value: "editor"}, {row_count: 15}]` |
| B. Submit + wait | Click submit → `browser_wait_for` network idle (≤5s). Record `submit_result` as before. | (existing fields) |
| C. Refresh | `browser_evaluate("() => location.reload()")` OR navigate away (sidebar link) + back. Wait network idle + first meaningful paint (≤3s). | `refresh_method: "reload"\|"navigate_cycle"` |
| D. Re-open + re-read | If edit flow: click same row → open edit modal → read same field values. If create flow: re-read row count + search for new entity name. | `post: [{field: "role", value: "admin"}, {row_count: 16}]` |
| E. Diff | Compare pre vs post: mutated field MUST differ on edit (old → new value), row count MUST increase on create, MUST decrease on delete. | `persisted: true\|false, mutated_fields: ["role"], diff_reason?: "..."` |
| F. Persistence observation | If diff expected but not present → record `match: no` for this persistence step. Add to `observations[]` with `{step: "persistence_check", expected_per_lens: "role: editor → admin", observed: "role unchanged after refresh", match: "no", evidence: { form_trigger: "e1 → modal Edit User", refresh_method: "reload", pre: {role: "editor"}, post: {role: "editor"} }}`. NO severity, NO `bug` label — commander adjudicates. | (`match: no`, persisted=false) |

**Exception — when Persistence Probe CAN skip:**
- Read-only forms (no mutation) — detect via absence of submit button or `method="get"`
- Multi-step wizards — probe only on FINAL step (intermediate steps save draft, may not persist across refresh)
- File upload forms — record `persistence_probe.skipped: "file_upload_progressive"` — manual verify

**Refresh-safe session:** Scanner auth cookie/token MUST survive `page.reload()`. If reload kicks back to login → record observation `{step: "session_persistence", expected_per_lens: "session survives reload", observed: "redirected to /login after reload", match: "no", evidence: { redirect_url: "/login", elapsed_ms: <ms> }}` + skip further persistence probes for this view. NO severity assignment — commander adjudicates.

### STEP 5: Write Output

When `elements_visited == elements_total` (including appended):

**Output path (matches orchestrator's expectation):**
- Web: `{PHASE_DIR}/scan-{VIEW_SLUG}-{ROLE}.json`
- Mobile: `{PHASE_DIR}/scan-{GOAL_ID}-{PLATFORM}.json`

Schema is identical across modes. Mobile fills:
- `view`: `"{GOAL_ID}@{PLATFORM}"` instead of URL
- `role`: `"{ROLE}"` (narration only — mobile auth state pre-seeded by orchestrator)
- `platform`: `"ios"` | `"android"` (NEW — web sets null)
- `device`: `"{DEVICE_NAME}"` (NEW — web sets null)
- `results[*].outcome`: mostly `captured` / `not_reachable` (no interaction in MODE=mobile)
- `blocking_reasons`: non-empty when follow-up interaction is needed
- `sidebar_suppressed`: null (not applicable to mobile)

Web shape still required as-is; mobile extends by adding `platform`
and `device`. Downstream `phase4_goal_comparison` treats them as
optional fields — no breaking change for web.

```json
{
  "view": "{VIEW_URL}",
  "role": "{ROLE}",
  "scanned_at": "{ISO timestamp}",
  "sidebar_suppressed": [ { "tag": "NAV", "id": null, "cls": "sidebar-root", "why": "left" } ],
  "elements_total": 42,
  "elements_visited": 42,
  "elements_stuck": 1,
  "results": [
    {
      "ref": "e1",
      "role": "button",
      "name": "Add Site",
      "testid": "sites-add-btn",
      "aria_label": "Add new site",
      "action": "click",
      "outcome": "modal_opened",
      "network": [{"method": "GET", "url": "/api/categories", "status": 200}],
      "console_errors": [],
      "screenshot": "{SCREENSHOTS_DIR}/scan-{VIEW_SLUG}-e1-after.png"
    }
  ],
  "forms": [
    {
      "trigger": "e1 → modal Add Site",
      "fields": [
        {"ref": "e10", "name": "siteName", "type": "text", "required": true, "filled": "Scan Test Item"},
        {"ref": "e11", "name": "domain", "type": "text", "required": true, "filled": "scan-test.example.com"}
      ],
      "submit_result": {"status": 201, "response": "created", "toast": "Site created"},
      "validation_tested": true,
      "persistence_probe": {
        "refresh_method": "reload",
        "pre": [{"row_count": 15}],
        "post": [{"row_count": 16, "new_row_domain": "scan-test.example.com"}],
        "persisted": true,
        "mutated_fields": ["row_count"],
        "diff": "row_count 15→16, new row domain match submitted"
      }
    }
  ],
  "modals": [ { "trigger": "button Add Site", "elements_inside": 8, "elements_tested": 8, "has_form": true } ],
  "tabs": [ { "ref": "e5", "name": "Settings", "elements_in_panel": 12, "elements_tested": 12 } ],
  "menus": [ { "trigger": "button Actions", "items": ["Edit", "Delete"], "items_clicked": 2 } ],
  "tables": [ { "ref": "e20", "row_count": 15, "actions_per_row": ["Edit", "Delete"], "sample_row_tested": true } ],
  "disabled_elements": [ { "ref": "e30", "name": "Bulk Delete", "enable_attempted": true, "enabled_after": true } ],
  "sub_views_discovered": ["/sites/456"],
  "errors": [
    {"type": "console", "message": "Warning: key prop missing"},
    {"type": "network", "url": "/api/sites/456", "status": 500}
  ],
  "_errors_note": "Legacy field — kept for back-compat. NO `severity` field per scanner-report-contract. Commander reads status code + message + cross-refs TEST-GOALS to assign severity post-adjudication.",
  "stuck": [ { "ref": "e30", "name": "Upload CSV", "reason": "file_input", "needs": "file path" } ]
}
```

## HARD RULES (non-negotiable)

- Visit 100% of elements. Not 80%. Not 90%. ALL — including dynamically appended.
- Recurse into EVERY modal/dialog that opens.
- Recurse into EVERY tab panel (each tab = fresh element list).
- Click EVERY item in EVERY dropdown/action menu.
- Fill and submit EVERY form you find.
- **After EVERY form submit → run Persistence Probe (Layer 4). Record `persistence_probe: {persisted, pre, post, diff}`. No exceptions except read-only forms + final-step-of-wizard + file-upload (document skip reason).**
- Test BOTH branches of EVERY confirm dialog (Cancel first, then OK).
- Record console errors after EVERY action.
- Record network requests after EVERY action.
- Re-snapshot after EVERY click and append new elements.
- Attempt to enable disabled elements before marking stuck.
- Stop ONLY when `elements_visited == elements_total`.
- Cannot interact? → add to `stuck` with reason. NEVER silently skip.

## CLEANUP (mandatory — run even on error)

```bash
browser_close
bash "~/.claude/playwright-locks/playwright-lock.sh" release "haiku-scan-{VIEW_SLUG}-$$"
```

## Limits (auto-enforced)

- Max 200 actions per view
- Max 10 min wall time
- Stagnation: same fingerprint 3x in a row = stuck, move on
