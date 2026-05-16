---
name: "vg-haiku-scanner"
description: "Exhaustive view scanner — workflow followed by Haiku agents spawned from /vg:review. Fixed protocol, zero discretion to skip."
metadata:
  short-description: "Exhaustive view scanner — workflow followed by Haiku agents spawned from /vg:review. Fixed protocol, zero discretion to skip."
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
`VG_RUNTIME=codex`, use Codex `update_plan` for the compact visible task
window, and bind it with `vg-orchestrator tasklist-projected --adapter codex`.

VGFlow source paths are resolved through global `VG_HOME` (default:
`~/.vgflow`). Project-local Claude workflow files may be absent in
global-only installs; Codex must use
`${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}` and
`${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}` for workflow
helpers. References below to "Claude CLI", `TodoWrite`, or Haiku describe
the Claude adapter only. Codex must map them through this adapter contract
instead of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use `tasklist-contract.json` as source of truth. Do not paste the full hierarchy into Codex `update_plan`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and `+N pending`. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`. |
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
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh --tier planner` |
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

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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
bash "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh" \
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

Invoke this skill as `$vg-haiku-scanner`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



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
| table / list with rows | Scroll container to count rows. **Batch 42:** Click actions on first/middle/last row (3 samples vs 1) — index 0, floor(row_count/2), row_count-1. Record each in `tables[].sampled_rows[]` with row_index + row_id + action_outcomes per action. If row opens detail/modal → recurse on first row only (cost cap). **Batch 40:** Also detect filter widgets / sort headers / pagination near this table (see classification rules below) and emit to `filters[]` / `sort_headers[]` / `pagination` arrays. |
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

### Batch 43 — Accessibility scan via axe-core

Read-only spec accessibility stage previously generic prose (no real
selectors). Scanner now runs axe-core programmatically and emits
findings → spec body asserts specific violations.

After STEP 4 element pass + Batch 40 widget classification + Batch 41
state probing, run axe-core via `browser_evaluate`:

```javascript
// Injected via browser_evaluate
() => {
  return new Promise((resolve) => {
    // Try local axe.min.js first (vendored), fallback to CDN
    const loadAxe = () => {
      if (window.axe) return Promise.resolve();
      return new Promise((r) => {
        const s = document.createElement('script');
        s.src = 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js';
        s.onload = r;
        s.onerror = () => r();  // graceful fallback if CDN blocked
        document.head.appendChild(s);
      });
    };
    loadAxe().then(() => {
      if (!window.axe) {
        resolve({skipped: 'axe-core unavailable', findings: []});
        return;
      }
      window.axe.run(document, {
        runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}
      }).then((results) => {
        const findings = results.violations.map(v => ({
          rule: v.id,
          wcag: (v.tags.find(t => t.startsWith('wcag')) || '').replace('wcag', ''),
          severity: v.impact,
          description: v.description,
          help_url: v.helpUrl,
          nodes: v.nodes.slice(0, 3).map(n => ({
            selector: n.target.join(' '),
            html_snippet: n.html.slice(0, 200)
          }))
        }));
        resolve({findings, run_at: new Date().toISOString()});
      });
    });
  });
}
```

Flatten `findings[].nodes[]` into top-level `accessibility_findings[]`
(one entry per (rule × node)). Each entry: `{rule, wcag, severity,
selector, html_snippet, description, help_url}`.

`accessibility_summary` tallies counts by severity. Critical/serious
violations are most actionable for spec body assertions.

If axe load fails (CSP/CDN blocked): emit
`accessibility_findings: [], accessibility_summary: {skipped: "axe_unavailable"}`.

Downstream `enrich-test-goals.py` reads top-N findings per view →
emits G-AUTO-{view}-a11y-{rule} stubs with selector + WCAG ref.

### Batch 42 — Modal-form input variation (4-tier)

Previous scanner submitted modal forms with 1 input set (valid data).
Boundary/empty/unicode bugs that surface only on specific input shapes
miss → spec body asserts only happy path.

Variants tested per modal: `valid + empty + max-length + unicode`.

For each modal-with-form discovered in STEP 4, after the existing
Persistence Probe pass on `valid` variant, run 3 additional variants:

| Variant | Input pattern | Expected outcome |
|---|---|---|
| `valid` | Original data per element-type rules (test data) | 201/200 + persisted |
| `empty_required` | Submit with all required fields blank | 422 + inline validation errors |
| `max_length` | Required string fields at max-length boundary | 201 OR 413/422 per contract |
| `unicode_special` | 包含中文 🎉 ' " < > & in text fields | 201 + stored unchanged + no XSS reflection |

Cost cap: skip variants if any of these hold:
- Modal trigger is `Cancel`/`Close` (no submit)
- Form has no required fields (empty_required is N/A)
- File upload form (per existing skip rule)

Each visit records `modals[].input_variants[]` array per the schema above.
Downstream spec generator uses these to template `test.each([variants])`
with real submit_status expectations.

### Batch 63 — Cross-view propagation probe (post-mutation)

AFTER persistence_probe success on CREATE/UPDATE/DELETE actions on the
SOURCE view, scanner navigates to top-N related sibling views and
captures whether the mutated entity propagated. Without this, test
specs only verify "entity persists on same view" — they miss the
deploy-time pain "create site → dashboard count doesn't update" or
"delete order → still appears in admin list".

**Configuration:**
- `VG_CROSS_VIEW_MODE` env: `sample|enabled|disabled` (default `sample`)
  - `sample` = scan top-3 highest-priority CREATE mutations per phase
  - `enabled` = scan EVERY CREATE/UPDATE/DELETE (expensive)
  - `disabled` = skip entirely (legacy back-compat)
- `VG_CROSS_VIEW_N` env: number of target views per probe (default 3)
- `VG_CROSS_VIEW_TOTAL_BUDGET_S` env: phase-wide budget (default 60s)
- Default OFF for readonly goals

**Target view selection (heuristic priority):**
1. Views sharing entity slug in path (e.g. `/sites` mutation → look for
   `/sites/{id}`, `/sites/archive`, `/admin/sites`)
2. Dashboard / summary views (`/dashboard`, `/home`, `/`)
3. Sibling list views derived from RUNTIME-MAP route_inventory[] that
   share the entity's resource family

**Per-target probe steps:**
1. Capture pre-snapshot of target view (entity_id absent? count baseline?)
2. Trigger source-view mutation (already happened in persistence_probe)
3. Navigate to target view via SPA route OR full reload
4. Wait network idle (≤ 3s)
5. Search DOM for entity_id (text match, NOT XHR — scanner observes
   rendered state)
6. Compute observed_count_delta if target view shows a count badge
7. Record `cross_view_propagation_observations[]` entry with:
   - `target_view_class` (B62 enum, view-rename-stable identity)
   - `entity_canonical_id` (NOT raw path — drives enrich goal-id stability)
   - `observed_in_target: yes|no|partial` (partial = entity found but
     count delta off, or in archive list when expected in primary)
   - `limitations: ["single_role_scan"]` always; add `no_delayed_propagation`
     when scan happened within 2s of mutation (insufficient for async)
8. If `observed_in_target == no` for a CREATE on dashboard_summary →
   record `match: no` step (commander adjudicates severity)

**Budget enforcement:**
- Per-probe cap: 10s (5s navigate + 5s scan). Exceeded → WARN + skip.
- Phase-wide cap: 60s. Exceeded → WARN + skip remaining probes.
  Already-collected observations preserved.

**Dedup:**
- Key: `(entity_slug_family, target_view_class)`. If sites→dashboard
  already scanned, skip sites→dashboard for other sites mutations
  unless `VG_CROSS_VIEW_MODE=enabled`.

**Skip conditions:**
- Action is readonly (GET on source view)
- RUNTIME-MAP route_inventory[] empty OR missing
- VG_CROSS_VIEW_MODE=disabled
- Total budget exhausted

**Output:** Each scan-{view}.json gets `cross_view_propagation_observations[]`
array. enrich-test-goals.py consumes to emit
`G-AUTO-{entity_canonical_id}-{action_class}-{target_view_class}` goals
with `goal_class: feature_chain` + 4-step chain_steps stub.

### Batch 41 — Active State Probing (empty / error_4xx / loading)

Read-only spec stages (Batch 36 R2 — empty_state, error_state_4xx,
loading_state) need real selectors + screenshots. Without scanner
probing them, spec body uses generic `.empty-state` guesses → flaky.

After STEP 4 element pass + Batch 40 widget classification, perform 3
explicit probes (skip if profile is cli-tool/library — no UI):

**Probe 1 — empty_state:**
1. If `search[]` non-empty: pick first search input, type random
   `'aaaa-zz-no-match-9999'` query, wait debounce + 500ms.
2. Else if `filters[]` non-empty: apply filter to least-common option
   (or 2 incompatible filters combined).
3. Else: skip with `observed: false, reason: "no narrowing controls"`.
4. Snapshot DOM. Find element matching empty-state heuristic:
   `[data-testid*='empty'], [aria-label*='empty'], [aria-label*='no result'],
    .empty-state, p:has-text(/no .*found|empty|zero result/i)`.
5. Record `selector` + `message_text` + `cta_present` (any button inside).
6. Screenshot → `state-observations.empty_state`.
7. Clear filter/query to restore default.

**Probe 2 — error_state_4xx:**
1. If route has `:id` pattern (from view-assignments source): navigate to
   `{view-base}/{99999999-fake-id-probe}` directly.
2. Else: append fake query `?_probe=invalid_99999`.
3. Wait network idle. Record `actual_status` from last network response.
4. If status >= 400: snapshot DOM, find error-state element via heuristic:
   `[data-testid*='error'], [role='alert'], .error-page, h1:has-text(/404|not found|error/i)`.
5. Confirm `no_white_screen`: DOM has more than just `<body></body>` empty.
6. Screenshot → `state-observations.error_state_4xx`.
7. Navigate back to original view.

**Probe 3 — loading_state:**
1. Use Playwright `page.route` or CDP `Network.emulateNetworkConditions`
   to throttle to slow-3g (400ms latency, 400Kb/s).
2. `page.reload()` → IMMEDIATELY snapshot DOM (within 100-200ms).
3. Find skeleton/spinner via heuristic:
   `[data-testid*='skeleton'], [role='progressbar'], .skeleton, .spinner,
    [aria-busy='true']`.
4. Record `selector` + measure `skeleton_visible_ms` (time from reload
   start to skeleton-disappeared).
5. After full load, check `no_layout_shift_after`: row count + first
   element position match prior baseline.
6. Restore network speed to normal.
7. Screenshot of mid-load state → `state-observations.loading_state`.

**Output**: 3 entries in `state_observations` object (all observed,
or `{observed: false, reason: "..."}` if skipped). Downstream
`enrich-test-goals.py` reads each → emits per-state G-AUTO stubs with
real selectors → spec generator binds expect() to those selectors.

### Batch 40 — Filter / Sort / Pagination / Search classification

Read-only views (list/dashboard/index) typically have filter+sort+paginate UI
that previously got lumped into `results[]` as generic combobox/button clicks.
Test-spec generator can't distinguish them → read-only specs sparse.

Per view, after main STEP 4 element pass, perform these classification scans:

**filters[]** — interactive control above/beside a table that filters its rows:
- Detector: `<select>`, `<input role=combobox>`, `<input type=date|search>`,
  `<input role=switch>` located within 250px (top|left|right) of a table/list root.
- Record: `{ref, name, kind, options?, near_table_ref, tested_values}`.
- Test 1 non-default value → snapshot row count diff → record in `tested_values`.

**sort_headers[]** — clickable column headers (`<th>` with `role=button`,
`aria-sort` attribute, or click handler):
- Detector: table `<th>` with `aria-sort` attribute OR `cursor:pointer` style
  OR click handler in event listeners.
- Click → snapshot ARIA sort attr → click again for desc order.
- Record: `{ref, column, current_order, clicked, resulting_order}`.

**pagination** (singular object, not array):
- Detector: any of {next/prev button, page number buttons, page-size select,
  "Showing X–Y of Z" text}.
- Record: `{present, current_page, total_pages, controls[], tested_controls[], url_sync}`.
- Test: click next → URL change detected → set `url_sync: true`. Click prev to restore.

**search[]** — global or scoped search input:
- Detector: `<input type=search>` OR `<input placeholder~="Search|Tìm">` outside
  any `<form>` (filters are usually scoped to form; global search isn't).
- Record: `{ref, placeholder, tested_query, result_count_after, debounce_ms_observed}`.
- Type 3-letter query → wait 500ms → measure first network request timing (debounce).

These 4 arrays MUST be present in output (empty `[]` or `{present:false}` if not found).
Downstream `enrich-test-goals.py` reads `scan.filters[]` to emit per-filter test stubs
with D-16 14-case rigor pack tagging.

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
  "modals": [
    {
      "trigger": "button Add Site",
      "elements_inside": 8,
      "elements_tested": 8,
      "has_form": true,
      "input_variants": [
        {"variant": "valid", "submit_status": 201, "outcome": "created"},
        {"variant": "empty_required", "submit_status": 422, "outcome": "validation_error_shown"},
        {"variant": "max_length", "submit_status": 201, "outcome": "accepted_or_truncated"},
        {"variant": "unicode_special", "submit_status": 201, "outcome": "stored_unchanged"}
      ]
    }
  ],
  "tabs": [ { "ref": "e5", "name": "Settings", "elements_in_panel": 12, "elements_tested": 12 } ],
  "menus": [ { "trigger": "button Actions", "items": ["Edit", "Delete"], "items_clicked": 2 } ],
  "tables": [
    {
      "ref": "e20",
      "row_count": 15,
      "actions_per_row": ["Edit", "Delete"],
      "sample_row_tested": true,
      "sampled_rows": [
        {"row_index": 0, "row_id": "site-001", "action_outcomes": {"Edit": "modal_opened", "Delete": "confirm_dialog"}},
        {"row_index": 7, "row_id": "site-008", "action_outcomes": {"Edit": "modal_opened", "Delete": "confirm_dialog"}},
        {"row_index": 14, "row_id": "site-015", "action_outcomes": {"Edit": "modal_opened", "Delete": "confirm_dialog"}}
      ],
      "row_indexes_tested": [0, 7, 14]
    }
  ],
  "filters": [
    { "ref": "e15", "name": "Status", "kind": "select", "options": ["all", "active", "archived"], "near_table_ref": "e20", "tested_values": ["active"] },
    { "ref": "e16", "name": "Owner", "kind": "combobox", "options": null, "near_table_ref": "e20", "tested_values": ["self"] },
    { "ref": "e17", "name": "Created since", "kind": "date", "options": null, "near_table_ref": "e20", "tested_values": ["2026-01-01"] }
  ],
  "sort_headers": [
    { "ref": "e21", "column": "Name", "current_order": "asc", "clicked": true, "resulting_order": "desc" },
    { "ref": "e22", "column": "Created", "current_order": null, "clicked": true, "resulting_order": "asc" }
  ],
  "pagination": {
    "present": true,
    "current_page": 1,
    "total_pages": 5,
    "controls": ["first", "prev", "next", "last", "jump-to-page", "page-size-select"],
    "tested_controls": ["next", "prev"],
    "url_sync": true
  },
  "search": [
    { "ref": "e10", "placeholder": "Search sites...", "tested_query": "test", "result_count_after": 3, "debounce_ms_observed": 250 }
  ],
  "accessibility_findings": [
    {
      "rule": "color-contrast",
      "wcag": "1.4.3",
      "severity": "serious",
      "selector": "button.primary-cta",
      "html_snippet": "<button class='primary-cta'>Save</button>",
      "description": "Background 4.1:1 below WCAG AA 4.5:1 threshold",
      "help_url": "https://dequeuniversity.com/rules/axe/4.x/color-contrast"
    },
    {
      "rule": "label",
      "wcag": "4.1.2",
      "severity": "critical",
      "selector": "input#search",
      "description": "Form input lacks accessible name (no label/aria-label/aria-labelledby)",
      "help_url": "https://dequeuniversity.com/rules/axe/4.x/label"
    }
  ],
  "accessibility_summary": {
    "total_violations": 2,
    "by_severity": {"critical": 1, "serious": 1, "moderate": 0, "minor": 0},
    "axe_run_at": "{ISO timestamp}",
    "viewport": "1280x800"
  },
  "state_observations": {
    "empty_state": {
      "observed": true,
      "trigger": "search 'zzzzzzzz' produced 0 rows",
      "selector": "[data-testid='empty-state'], .empty-state, [aria-label='No results']",
      "message_text": "No sites found",
      "cta_present": true,
      "screenshot": "{SCREENSHOTS_DIR}/scan-{VIEW_SLUG}-empty.png"
    },
    "error_state_4xx": {
      "observed": true,
      "trigger": "navigate to {view}/99999999-fake-id-probe",
      "expected_status": 404,
      "actual_status": 404,
      "selector": "[data-testid='error-404'], .error-page, [role='alert']",
      "message_text": "Not found",
      "no_white_screen": true,
      "screenshot": "{SCREENSHOTS_DIR}/scan-{VIEW_SLUG}-error-404.png"
    },
    "loading_state": {
      "observed": true,
      "trigger": "throttle network slow-3g, reload",
      "selector": "[data-testid='skeleton'], .skeleton, [role='progressbar'], .spinner",
      "skeleton_visible_ms": 850,
      "no_layout_shift_after": true,
      "screenshot": "{SCREENSHOTS_DIR}/scan-{VIEW_SLUG}-loading.png"
    }
  },
  "data_observations": {
    "cardinality": {"tables_total_rows": 168, "tables_visible_rows": 25, "filters_observed": 2, "sort_columns_observed": 1, "search_inputs_observed": 1},
    "status_diversity": {"http_status_codes_seen": [200, 304], "non_2xx_count": 0, "console_error_count": 0},
    "distinct_values_per_filter": [
      {"filter_name": "Status", "distinct_count": 3, "sampled_values": ["all", "active", "archived"]},
      {"filter_name": "Owner", "distinct_count": null, "sampled_values": null}
    ],
    "sampled_status_distribution": {"Active": 134, "Archived": 28, "Unknown": 6},
    "row_id_pattern": "site-NNN (zero-padded 3 digits)",
    "captured_at": "{ISO timestamp}"
  },
  "_data_observations_note": "Batch 59: emit when table/list has ≥3 rows. Recipe generator reads to size pagination_edge seeds, validate filter_combination distinctness, and detect single-value columns that cause empty filter results.",
  "cross_view_propagation_observations": [
    {
      "source_view": "/sites",
      "target_view": "/dashboard",
      "target_view_class": "dashboard_summary",
      "action": "create",
      "entity_id": "site-001",
      "entity_canonical_id": "sites:create",
      "observed_in_target": "yes",
      "evidence_screenshot": "{SCREENSHOTS_DIR}/scan-{VIEW_SLUG}-xview-dashboard.png",
      "observed_count_delta": 1,
      "navigation_duration_ms": 1850,
      "limitations": ["single_role_scan"]
    },
    {
      "source_view": "/sites",
      "target_view": "/sites/site-001",
      "target_view_class": "sibling_list",
      "action": "create",
      "entity_id": "site-001",
      "entity_canonical_id": "sites:create",
      "observed_in_target": "yes",
      "evidence_screenshot": null,
      "observed_count_delta": null,
      "navigation_duration_ms": 920,
      "limitations": ["single_role_scan"]
    },
    {
      "source_view": "/sites",
      "target_view": "/audit",
      "target_view_class": "audit_log",
      "action": "delete",
      "entity_id": "site-001",
      "entity_canonical_id": "sites:delete",
      "observed_in_target": "partial",
      "evidence_screenshot": null,
      "observed_count_delta": 1,
      "navigation_duration_ms": 2100,
      "limitations": ["single_role_scan", "no_delayed_propagation"]
    }
  ],
  "_cross_view_propagation_note": "Batch 63: AFTER persistence_probe success on CREATE/UPDATE/DELETE, scanner navigates top-N (default N=3, env VG_CROSS_VIEW_N) related sibling views from RUNTIME-MAP. Heuristic priority: (1) shared entity slug, (2) dashboard/summary, (3) sibling list. Total budget cap 60s/phase via VG_CROSS_VIEW_TOTAL_BUDGET_S. Default mode=sample (env VG_CROSS_VIEW_MODE=sample|enabled|disabled) — only top-3 highest-priority CREATE mutations scanned. Dedup by (entity_slug_family, target_view_class). entity_canonical_id is view-rename-stable identity (NOT raw path) used by enrich-test-goals to generate feature_chain goal ids. limitations[] documents known scan-time gaps for downstream awareness: single_role_scan (multi-tenant not covered), no_delayed_propagation (async webhook/notification chains not observed).",
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
- **⛔ ANTI-CANCEL ENFORCEMENT (v2.46+ — closes Phase 3.2 dogfood meta-bug):**
  - For ANY goal with `mutation_evidence` declared in TEST-GOALS — scanner MUST execute the OK/Submit path AT LEAST ONCE per goal. Cancelling without ever submitting = AUTOMATIC `match: no` for the goal step, NOT `match: yes`.
  - Sandbox is a mutation environment by design (`disposable_seed_data: true` in ENV-CONTRACT). Refusing to submit because "destructive" or "modify real data" is a CONTRACT VIOLATION — sandbox seed regenerates per /vg:test run.
  - If orchestrator (commander) prompt explicitly tells you "Cancel modals only" or "do not submit", you MUST still record `observations[].observed: "scanner_skipped_submit_per_orchestrator_directive"` with `match: unknown`. NEVER `match: yes` when submit was skipped — that fabricates passing evidence.
  - On submit, capture FULL network chain (preflight CSRF/auth GET + mutation POST + post-mutation GET for persistence). Server errors (403 CSRF, 401 AUTH, 5xx) are FACTUAL OBSERVATIONS — record them with `match: no` + verbatim error code. NEVER classify them as "expected security check" or "as designed" (banned vocabulary per scanner-report-contract Section 1).
  - Exception (only valid skip): goal explicitly declares `mutation_required: false` in TEST-GOALS frontmatter. Default for goals with `mutation_evidence` is `mutation_required: true`.
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
