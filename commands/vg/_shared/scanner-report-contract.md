---
name: vg:_shared:scanner-report-contract
description: Canonical contract — scanner agents (CLI/Haiku) report observations only, NEVER verdicts. Commander (Opus) is sole judge. Used by /vg:roam workers + /vg:review Phase 2b-2 Haiku scanners.
---

# Scanner Report Contract

**Principle:** Scanner agents **discover and report**. Commander (Opus) **adjudicates and decides**. Verdicts, severity, prescriptions — all commander's job.

**Why:** Lower-tier CLI models (Codex / Gemini Flash / Haiku) are good observers but biased judges. Letting them mark "BUG" / "CRITICAL" / "FIX NEEDED" pollutes downstream synthesis with low-quality severity signal. Separate concerns: scanner = factual capture; commander = trained model with full context evaluates.

This contract is read by:
- `/vg:roam` workers (CLI executors)
- `/vg:review` Phase 2b-2 Haiku scanners (`vg-haiku-scanner` skill)
- Future: `/vg:debug` discovery agents

---

## Section 1 — Banned vocabulary

Scanner output **MUST NOT** contain any of these tokens (case-insensitive). They are verdicts, not observations.

| Banned | Why | Use instead |
|---|---|---|
| `bug`, `broken`, `wrong`, `incorrect` | Judgmental | `expected X, observed Y` |
| `fail`, `failed`, `failure` (in description text) | Verdict | `match: no` (in structured field only) |
| `critical`, `major`, `minor`, `severe` | Severity = commander's matrix | `unknown` (commander assigns post-adjudication) |
| `should`, `must`, `need to`, `needs` | Prescriptive | `evidence: <fact>` |
| `fix`, `repair`, `patch` | Action recommendation | report observation, let commander prescribe |
| `correct`, `correctly`, `properly` | Implies right/wrong judgment | `expected_per_lens: <spec>` vs `observed: <fact>` |
| `obviously`, `clearly`, `apparently` | Speculation, not observation | drop the qualifier; state observation directly |

**Allowed words:**
- `expected_per_lens`, `observed`, `match`, `mismatch`, `partial`, `unknown`
- `evidence`, `screenshot`, `network_requests`, `console_errors`, `dom_changed`, `url_after`
- `elapsed`, `timeout`, `retry`, `step`, `anomaly`, `query`, `blocker`

**Validator:** post-write grep on scanner output files. Hits in banned list → reject report + log to scanner's quarantine list. Commander still reads, but tags the report `vocabulary_violation: true` for trust calibration.

---

## Section 2 — Report schema (canonical)

All scanner reports MUST conform to this JSON schema. Per-tool wrappers (web/mobile/CLI) extend, never violate.

```json
{
  "$schema_version": "scanner-report.v1",
  "scanner_id": "string — unique per invocation (e.g., haiku-csrf-3, codex-form-7)",
  "lens": "string — lens or task name (e.g., form-lifecycle, csrf, idor, view-scan)",
  "target": {
    "page": "string | null — URL/route or N/A",
    "role": "string | null — auth role used",
    "platform": "web | ios | android | cli | api | null",
    "device": "string | null — device name if mobile/desktop"
  },
  "session": "string — orchestrator-provided session UUID",
  "started_at": "ISO 8601",
  "ended_at": "ISO 8601",
  "duration_s": "number",

  "observations": [
    {
      "step": "string — what scanner did, factual (e.g., 'click submit', 'navigate /sites/new')",
      "expected_per_lens": "string | null — what the lens spec said to expect",
      "observed": "string — factual observation, no judgment words",
      "match": "yes | no | partial | unknown",
      "evidence": {
        // Tier A — Always-on (every UI step)
        "screenshot": "string | null — relative path",
        "network_requests": "array<{method, url, status, timing_ms, headers?, request_body?, response_body?}>",
        "console_errors": "array<string — raw error text>",
        "console_warnings": "array<string>",
        "dom_changed": "boolean | null",
        "url_before": "string | null",
        "url_after": "string | null",
        "elapsed_ms": "number | null",
        "page_title": "string | null — document.title after step",
        "toast": "{ visible, count, items: [{text, type}] } | null — UX feedback message",
        "http_status_summary": "{ '2xx': N, '3xx': N, '4xx': N, '5xx': N, cors_blocked: N, aborted: N } | null",

        // Tier B — Form / CRUD (set by form-lifecycle, business-coherence lenses)
        "form_validation_errors": "{ count, items: [{field, message, source}] } | null",
        "submit_button_state": "{ found, text, disabled, busy } | null",
        "loading_indicator": "{ present, selector?, bbox? } | null",
        "row_count_before": "number | null",
        "row_count_after": "number | null",
        "field_value_before": "{ field, value, type } | null",
        "field_value_after": "{ field, value, type } | null",
        "db_read_after_write": "{ method, url, status, body_match: yes|no|partial } | null — follow-up GET to verify mutation",
        "idempotency_replay": "{ second_call_status, response_id_matches: yes|no|unknown } | null",

        // Tier C — Auth / Session / Security (set by csrf, idor, bfla, auth-jwt lenses)
        "cookies_filtered": "{ document_cookie_count, names: [...] } | null — names only, no values",
        "auth_state": "{ authenticated: yes|no|unknown, signal } | null",
        "request_security_headers": "{ has_authorization, has_csrf_token, has_idempotency_key, has_if_match, has_origin, has_referer, custom_headers } | null",
        "response_security_headers": "{ has_set_cookie, set_cookie_flags: [{has_httponly, has_secure, same_site}], has_csp, has_x_frame_options, has_strict_transport_security } | null",

        // Tier D — Realtime / Async (set by realtime-coherence, websocket-scope lenses)
        "websocket_frames": "{ instrumented: bool, count, frames: [{dir, data, t}] } | null",
        "polling_calls": "array<{url, interval_ms, count}> | null",
        "background_job_status": "{ status, queue_summary } | null",

        // Tier E — Visual / A11y (set by visual, a11y, modal-state lenses)
        "viewport_size": "{ width, height } | null",
        "focus_state": "{ focused, tag, id?, name?, role?, label } | null",
        "aria_state": "{ found, attributes: { 'aria-*': value, role: value } } | null — captured per relevant element",
        "a11y_tree_excerpt": "string | null — MCP browser_snapshot output, trimmed",
        "tab_order": "array<{tag, label, tabindex}> | null — first 30 focusable elements",

        // Tier F — Storage / Client State (set by business-coherence deep, info-disclosure lenses)
        "storage_keys": "{ localStorage_keys: [...], sessionStorage_keys: [...], count } | null — keys only, never values",
        "indexedDB_dbs": "{ supported, dbs: [{name, version}] } | null",
        "store_snapshot": "{ exposed, key, top_level_keys: [...] } | null — Zustand/Redux dev-exposed store, top-level keys only",

        // Tier G — Mobile (set by Maestro-driven scanners, MODE=mobile)
        "hierarchy_diff": "{ added: [...], removed: [...], changed: [...] } | null — Maestro hierarchy.json diff",
        "screenshot_diff_pct": "number | null — pixel diff percentage between before/after",
        "deep_link_resolved": "{ requested_url, final_screen_id, success: bool } | null",
        "tap_target_size_px": "{ element_id, width, height, hig_compliant: bool } | null — iOS HIG 44pt / Material 48dp",
        "keyboard_avoidance": "{ form_visible_when_keyboard: bool, bottom_inset_px } | null",
        "network_offline_recovery": "{ tested, recovered: yes|no|partial } | null",

        // Free-form — lens-specific fields not in tiers above
        "extra": "object — lens-specific fields, free-form"
      }
    }
  ],

  "anomalies": [
    "string — pattern noticed but unclear if related (e.g., 'console emitted same TypeError 3x with identical stack')"
  ],

  "blockers": [
    {
      "step": "string — which step blocked",
      "reason": "string — factual (e.g., 'page returned 502', 'auth cookie missing after redirect', 'browser MCP timeout 30s')",
      "evidence": "object | string"
    }
  ],

  "queries": [
    {
      "step": "string — current step",
      "question": "string — needs commander input to continue",
      "scanner_proposal": "string | null — what scanner would do if allowed (NOT prescription, just option)"
    }
  ],

  "completion": {
    "status": "complete | partial | aborted",
    "steps_total": "number",
    "steps_completed": "number",
    "steps_skipped": "number"
  }
}
```

**Field discipline:**

- `match` is the ONLY judgment field. `yes` = observed matches expected. `no` = mismatch. `partial` = some criteria match, others don't. `unknown` = lens didn't specify expected, or evidence inconclusive.
- `observations[].observed` = pure description. NO interpretation. "Button stayed enabled, no network call in 5s" ✓ — "submit handler appears broken" ✗.
- `evidence` arrays may be empty `[]` — empty IS a fact (e.g., `network_requests: []` = "we observed zero requests").
- `anomalies` is a low-confidence noticeboard for commander. Format: factual description, no severity.
- `blockers` halts scanner — commander must triage. Use sparingly; don't blocker on minor mismatches.
- `queries` is the explicit "I don't know how to proceed, please decide" channel. Commander answers in next iteration.

---

## Section 2.5 — Evidence Tier System (v2.42.8+)

Evidence fields organized into 7 tiers by capture cost + bug class coverage. Scanners capture per-tier based on lens config + platform capability. Helper JS snippets for each tier live in `.claude/scripts/scanner-evidence-capture.js`.

### Tier A — Always-on (every UI step, ~0ms cost)

Captured automatically by browser MCP without extra eval. Required on EVERY observation in UI mode.

| Field | What it catches |
|---|---|
| `screenshot`, `dom_changed`, `url_before`, `url_after`, `elapsed_ms` | Page transitions, hangs, optimistic UI failures |
| `network_requests[]` | API not firing, 4xx/5xx, race conditions |
| `console_errors[]`, `console_warnings[]` | Runtime exceptions, deprecation warnings |
| `page_title` | Wrong navigation, stale title |
| `toast` | UX silent — user doesn't know action result |
| `http_status_summary` | Mass-failure pattern (e.g., 5 auth requests all 401) |

### Tier B — Form / CRUD (form-lifecycle, business-coherence; ~50-200ms extra)

Capture when step involves a form submit, edit, delete, or list mutation.

| Field | What it catches |
|---|---|
| `form_validation_errors` | Field-level validation broken, mass-assignment exposure |
| `submit_button_state` | Button stuck enabled (handler dead), missing aria-busy |
| `loading_indicator` | UX no feedback during 2s+ wait |
| `db_read_after_write` | **Ghost save** — toast OK but DB didn't update |
| `row_count_before` / `row_count_after` | Optimistic-only update, server didn't persist |
| `field_value_before` / `field_value_after` | Edit didn't stick, race overwrite |
| `idempotency_replay` | Duplicate-create on retry |

### Tier C — Auth / Session / Security (csrf, idor, bfla, auth-jwt; ~20-50ms)

Capture on auth-sensitive steps: login, role-switch, sensitive mutation, cross-tenant probe.

| Field | What it catches |
|---|---|
| `cookies_filtered` | Missing HttpOnly/Secure/SameSite, CSRF token leak |
| `auth_state` | Silent logout, session expire mid-flow |
| `request_security_headers` | Header drift, missing CSRF/Idempotency-Key |
| `response_security_headers` | Set-Cookie missing flags, missing CSP/HSTS, session fixation |

### Tier D — Realtime / Async (websocket-scope, polling-coherence; ~0ms passive but instrumented)

Requires app-side instrumentation (`window.__vg_ws_log`). Without instrumentation, fields return `instrumented: false`.

| Field | What it catches |
|---|---|
| `websocket_frames` | Frame drop, scope leak (M1 receives M2's events), reconnect replay storms |
| `polling_calls` | Wasted polling, missing backoff |
| `background_job_status` | Silent BullMQ failure, cron not firing |

### Tier E — Visual / A11y (visual, a11y, modal-state; ~200-500ms)

Capture per major UI state change (page load, modal open, route change).

| Field | What it catches |
|---|---|
| `viewport_size` | Responsive breakpoint mistakes |
| `focus_state` | Focus trap missing on modal, focus loss after close |
| `aria_state` | Wrong screen-reader signal, aria-expanded not updating |
| `a11y_tree_excerpt` | A11y tree corruption, missing landmarks |
| `tab_order` | Skip-link failure, hidden tabbable, wrong tab sequence |

### Tier F — Storage / Client State (business-coherence deep, info-disclosure; ~30-100ms)

Capture for state-coherence checks. Keys ONLY — never values (PII / token risk).

| Field | What it catches |
|---|---|
| `storage_keys` | State leak, PII in storage, leftover cache |
| `indexedDB_dbs` | Schema migration drift, leaked DB |
| `store_snapshot` | State desync vs UI claim (Zustand/Redux), if dev exposed `window.__VG_STORE__` |

### Tier G — Mobile (Maestro, MODE=mobile; ~500ms-2s per step)

Replaces Tier A-E for mobile profile. Browser MCP fields N/A.

| Field | What it catches |
|---|---|
| `hierarchy_diff` | Element appearance/disappearance |
| `screenshot_diff_pct` | Visual regression |
| `deep_link_resolved` | Universal link broken |
| `tap_target_size_px` | <44pt iOS HIG / <48dp Material |
| `keyboard_avoidance` | Form covered by keyboard |
| `network_offline_recovery` | Offline UX missing |

---

## Section 2.6 — Capability Matrix per Platform

| Tool / Platform | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| Browser MCP (web) | ✓ all | ✓ all | ✓ cookies/auth | ✓ if instrumented | ✓ screenshot+a11y | ✓ all | ✗ |
| Maestro (mobile) | ✓ network limited | ✓ form (no validation API) | ✓ basic auth | ✗ no WS hook | ✓ screenshot only | ✗ no eval | ✓ all |
| curl / API-only | ✓ status+headers | ✗ no UI | ✓ headers+cookies | ✗ no WS | ✗ | ✗ | ✗ |
| CLI subprocess | exit code + stdout/stderr | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Scanners that can't capture a tier emit `<field>: null` (NOT omit — `null` is a fact: "we tried, capability missing"). Commander reads `null` as "tier unavailable on this platform" and weights accordingly.

---

## Section 2.7 — Per-lens Tier Defaults (v2.42.8+)

Each lens declares which tiers fire. Scanner reads lens spec, captures only relevant tiers (cost optimization). Defaults below; lens authors can override per-step.

| Scanner / Lens | Always | Conditional | Opt-in via flag |
|---|---|---|---|
| `vg-haiku-scanner` (review Phase 2b-2 exhaustive) | A + B + E | C if mutation, F if state-coherence | D (instrumentation), G (mobile) |
| roam `lens-form-lifecycle` | A + B | C if auth flow, F if SPA | D, E |
| roam `lens-business-coherence` | A + B + F | C if auth | D, E |
| roam `lens-csrf` | A + C | B if mutation | — |
| roam `lens-idor` / `lens-bfla` / `lens-tenant-boundary` | A + C | B if mutation | F (storage cross-tenant) |
| roam `lens-auth-jwt` | A + C + F | — | D (token refresh frames) |
| roam `lens-modal-state` | A + E | — | F (modal-internal store) |
| roam `lens-table-interaction` | A + B (row count, field) | E (focus during keyboard nav) | — |
| roam `lens-info-disclosure` | A + F | C (response headers) | — |
| roam `lens-input-injection` | A | C if auth-bypass attempted | — |
| roam `lens-file-upload` | A + B | C if file-mutation auth | E (upload progress UI) |
| roam `lens-duplicate-submit` | A + B (idempotency_replay) | — | — |
| /vg:debug discovery agent | A only (lightweight) | B/C/E based on classification | F if storage-related |
| Mobile (Maestro) | A (limited) + G | E (screenshot diff) | — |

Lens spec format reflects this: each `step:` entry has `evidence_tiers: [A, B, ...]` declaring which tiers to capture.

---

## Section 3 — Output format per tool

| Tool | File | Format |
|---|---|---|
| `vg-haiku-scanner` (review Phase 2b-2) | `${PHASE_DIR}/scan-{VIEW_SLUG}-{ROLE}.json` | Single JSON object per scanner invocation |
| `/vg:roam` workers (CLI executors) | `${ROAM_DIR}/runs/<tool>/observe-{surface}-{lens}.jsonl` | JSONL — one event per line, accumulated |
| `/vg:debug` discovery agent | `${DEBUG_DIR}/discovery/{type}-{slug}.json` | Single JSON per discovery pass |

**JSONL variant (roam):** each line is a partial observation. Aggregator at end of roam Phase 4 collates lines into the canonical schema. First line MUST be the wrapper:

```json
{"$schema_version":"scanner-report.v1","scanner_id":"...","lens":"...","target":{...},"session":"...","started_at":"...","_observations_follow":true}
```

Subsequent lines are individual `observations[]` / `anomalies[]` / `blockers[]` / `queries[]` entries with explicit `_kind` field:

```json
{"_kind":"observation","step":"click submit","expected_per_lens":"POST /api/sites","observed":"5s elapsed, no network","match":"no","evidence":{"network_requests":[],"console_errors":["TypeError"]}}
{"_kind":"anomaly","note":"3x identical TypeError in console"}
{"_kind":"blocker","step":"verify created record","reason":"no resource :id available because POST never fired"}
```

Final line:
```json
{"_kind":"completion","status":"partial","steps_total":12,"steps_completed":4,"ended_at":"..."}
```

---

## Section 4 — Acceptable vs unacceptable examples

### ✓ ACCEPTABLE — observation only

```yaml
step: "fill form: domain=example.com, click submit"
expected_per_lens: "POST /api/sites within 2s + 201 status + redirect to /sites/{id}"
observed: "5 seconds elapsed; button remained enabled; URL unchanged at /sites/new; zero network requests captured; console emitted TypeError: validate is not a function (validate.ts:42)"
match: no
evidence:
  network_requests: []
  console_errors: ["TypeError: validate is not a function at validate.ts:42"]
  dom_changed: false
  url_before: "/sites/new"
  url_after: "/sites/new"
  elapsed_ms: 5042
  screenshot: "iter-3-after-submit.png"
```

Commander reads → has enough to: classify (likely code-bug), assign severity (mutation blocked = high), route (file:line in stack trace → /vg:debug or executor fix).

### ✗ UNACCEPTABLE — verdict-poisoned

```yaml
step: "click submit"
observed: "Submit button is BROKEN. Critical bug — needs fix immediately. Handler is clearly missing."
match: failed                       # bad: 'failed' not in enum
severity: critical                  # bad: severity is commander's job
recommendation: "fix validate.ts"   # bad: prescription, not observation
```

Reasons:
1. "BROKEN", "Critical", "needs fix" — banned vocabulary
2. `severity: critical` — scanner doesn't decide severity
3. `recommendation: ...` — scanner doesn't prescribe
4. `match: failed` — not in enum (`yes`/`no`/`partial`/`unknown`)
5. No evidence: missing network/console/screenshot/elapsed

Commander gets corrupted signal — must discount or re-run.

---

## Section 5 — Commander adjudication contract

Commander reads scanner reports + applies:

```
1. Vocabulary check
   For each report, scan for banned tokens.
   Hit → tag report `vocabulary_violation: true`, deprioritize but don't discard.

2. Coherence check
   - UI claim ↔ network truth: did toast say "saved" but network show no POST?
   - Read-after-write: did GET return the value POST claimed to set?
   - Console correlation: did mismatch line up with a console error?

3. Cross-reference TEST-GOALS / SPECS contract
   - Is `expected_per_lens` from a real lens spec? Or scanner improvised?
   - Does the goal G-XX exist for this surface?
   - Is observed behavior actually in scope of this phase?

4. Categorize finding
   - false-positive: lens spec stale, observed is intentional
   - code-bug: handler dead, dispatch missing, off-by-one
   - spec-gap: feature not in PLAN — auto-trigger /vg:amend
   - scope-issue: out-of-phase, defer to later phase
   - infra-issue: env-specific (dev seed missing, etc.)
   - regression: was working, now isn't (compare with baseline scan)

5. Severity assignment (project profile matrix)
   - critical: data loss, security, financial, auth bypass, idempotency violation
   - high: mutation blocked, contract violation, IDOR/BFLA actually exploitable
   - med: UX broken with workaround, coherence gap
   - low: cosmetic, console noise, logging-only

6. Verdict + action
   - pass / weak-pass / fail / escalate
   - Route: /vg:debug (code bug), /vg:amend (spec gap), accept-with-debt (low+medium), block (critical+high)
```

**Commander → user surface:** never raw scanner reports. Always adjudicated summary with verdict + action options.

---

## Section 6 — Validator (post-write contract enforcement)

Every scanner-report writer MUST be validated by `verify-scanner-report-contract.py` (TODO — script lands when this contract is consumed by ≥1 skill that writes scan reports).

Validator checks:

1. JSON schema valid (or JSONL: every line valid JSON, wrapper + completion present)
2. No banned tokens in any string field (regex grep)
3. `match` enum compliance
4. Required fields present (scanner_id, lens, target, observations[])
5. `evidence` shape per observation (warn if missing for `match: no`)

Verdict:
- All checks pass → `contract_compliance: 100`
- Violations → emit telemetry `scanner.contract_violation` with details. Commander deprioritizes report (still consumes — partial signal > no signal).

---

## Section 7 — Migration notes

**Existing scanner outputs** (pre-contract) often violate banned vocab + lack `expected_per_lens`. Migration strategy:

| Skill | Current state | Required change |
|---|---|---|
| `vg-haiku-scanner` (review Phase 2b-2) | Has `errors[].severity` — banned field | Replace with `match: no` + move severity to commander step (review Phase 4 weighted gate already does this) |
| `/vg:roam` workers | JSONL freeform with verdict words possible | Inject this contract into INSTRUCTION-*.md briefs, add validator post-aggregate |
| `/vg:debug` discovery agent | New (already drafted) | Reference contract from skill body |

Old scan files remain readable; new writes conform.

---

## Section 8 — Lens spec format (companion contract)

Lens specs declare `expected_per_lens` for each step. Without explicit lens spec, scanner falls back to `expected_per_lens: null` and commander has less to compare against.

```yaml
# .claude/commands/vg/_shared/lens-prompts/lens-form-lifecycle.md
lens_id: form-lifecycle
applicable_to: [crud-create, crud-update, crud-delete]
steps:
  - id: navigate
    action: "navigate to {target_url}"
    expected: "form rendered with all declared fields visible"
  - id: fill_required
    action: "fill all required fields with valid sample"
    expected: "no inline validation errors, submit button enabled"
  - id: submit
    action: "click submit"
    expected: "{request_method} {request_path} within 2s; status {success_code}; redirect to {success_url}"
  - id: read_after_write
    action: "GET created resource"
    expected: "200 response with field values matching submitted payload"
  - id: refresh_persistence
    action: "page.reload(); GET again"
    expected: "same field values as previous read (no ghost-save)"
```

Scanner copies `expected` verbatim into `observations[].expected_per_lens`. No paraphrasing.

---

## Quick reference card

```
SCANNER:
  - Discover, capture facts
  - No verdicts, no severity, no prescriptions
  - match: yes|no|partial|unknown ONLY
  - Evidence-rich, vocabulary-clean

COMMANDER:
  - Read all reports
  - Coherence + spec cross-ref
  - Categorize: false-pos/code-bug/spec-gap/scope/infra/regression
  - Severity matrix + verdict
  - Route to debug/amend/accept-debt/block

USER:
  - See adjudicated summary only
  - Make final accept/reject decision on commander's recommendation
```
