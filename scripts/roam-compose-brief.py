#!/usr/bin/env python3
"""roam-compose-brief.py (v1.1)

Compose per-surface × per-lens INSTRUCTION-*.md files with full env+creds+cwd
context inlined so the executor (subprocess OR another CLI via paste-prompt)
has everything it needs without external lookups.

v1.1 (2026-05-01): added --env / --target-url / --creds-json / --model /
--cwd-convention args. Filename now `INSTRUCTION-<surface>-<lens>.md` (was
`<surface>-<lens>.md`) so manual-mode paste prompts can reference them by a
distinct prefix. Login pre-flight section now inlined verbatim with real
URL + email + password from creds-json (was a TODO comment).

Spec: ROAM-RFC-v1.md section 3, Phase 1 + 2026-05-01 dogfood feedback.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


HARD_RULES = """## ⛔ HARD RULES (enforced — break = output rejected)

**Conformance contract:** `vg:_shared:scanner-report-contract` (skill).
You are a SCANNER. You DISCOVER and REPORT. The COMMANDER (Opus) ADJUDICATES.
Severity, verdicts, prescriptions = commander's job.

1. You DO NOT judge whether anything is a bug. Just log facts.
2. You DO NOT skip any RCRURD step, even if previous step seemed to fail.
3. You DO NOT stop early on errors. Log the error, continue to next step.
4. You DO NOT classify severity. The commander reads your log later.
5. You DO NOT add commentary. Output is JSONL only, one event per line.
6. If you observe a sub-view (modal, drilldown, child route) you didn't expect,
   emit `spawn-child` event with URL/handle, then continue parent RCRURD.
7. If a Playwright MCP call fails (timeout, server error), log the failure as
   an event and continue. Do NOT retry.
8. Capture full network payloads (request body + response body) verbatim.
   Do NOT redact, summarize, or truncate. PII redaction happens commander-side.
9. If a step's preconditions are not met, log a `precondition-missing` event
   and SKIP only that step's mutation; continue with the rest of RCRURD.

## ⛔ BANNED VOCABULARY (case-insensitive scan rejects output)

These words are JUDGMENTS, not OBSERVATIONS. Replace with factual descriptions:

| BANNED | Use instead |
|---|---|
| `bug`, `broken`, `wrong`, `incorrect` | `expected X per lens, observed Y` |
| `fail`, `failed`, `failure` (in description text) | `match: no` (structured field only) |
| `critical`, `major`, `minor`, `severe` | OMIT — commander assigns severity |
| `should`, `must`, `need to`, `needs` | report observation, omit prescription |
| `fix`, `repair`, `patch` | OMIT — commander prescribes action |
| `correct`, `correctly`, `properly` | `expected_per_lens: X` vs `observed: Y` |
| `obviously`, `clearly`, `apparently` | drop the qualifier; state observation |

## ✓ ALLOWED schema fields

- `step`, `expected_per_lens`, `observed`, `match` (yes|no|partial|unknown)
- `evidence`: organized into Tiers A-G per scanner-report-contract Section 2.5
- `anomalies[]` — patterns noticed, factual description, no severity
- `blockers[]` — { step, reason, evidence } when scanner cannot continue
- `queries[]` — { step, question, scanner_proposal } when scanner needs commander input

## Evidence Tier capture rules (v2.42.8+)

Capture per tier per step. Empty arrays/null = facts ("we tried, found nothing"). Helper JS: `.claude/scripts/scanner-evidence-capture.js`.

### Tier A — Always-on (every step)

Required on every observation:
- `network_requests[]` from MCP `browser_network_requests`
- `console_errors[]`, `console_warnings[]` from MCP `browser_console_messages`
- `dom_changed`, `url_before`, `url_after`, `elapsed_ms`
- `screenshot` from MCP `browser_take_screenshot` after step
- **`page_title`** = `document.title` via `browser_evaluate("() => document.title")`
- **`toast`** via `captureToast` snippet — toast/notification visible after action
- **`http_status_summary`** = `summarizeHttpStatus(network_requests)` (pure JS, no eval)

### Tier B — Form/CRUD (lens-form-lifecycle, lens-business-coherence, lens-table-interaction, lens-duplicate-submit)

Capture before+after each form interaction:
- `form_validation_errors` via `captureFormValidationErrors` snippet
- `submit_button_state` via `captureSubmitButtonState`
- `loading_indicator` via `captureLoadingIndicator`
- `row_count_before/after` via `captureRowCount` (target list selector)
- `field_value_before/after` via `captureFieldValue` (per relevant field)
- `db_read_after_write`: post-mutation, fetch the resource via `captureBackgroundJobStatus(get_url)` or direct GET; record status + body match
- `idempotency_replay`: re-submit with same Idempotency-Key, record second_call_status + response_id_matches

### Tier C — Auth/Session/Security (lens-csrf, lens-idor, lens-bfla, lens-auth-jwt, lens-tenant-boundary, lens-info-disclosure)

Capture on auth-sensitive steps:
- `cookies_filtered` via `captureCookiesFiltered` (names only)
- `auth_state` via `captureAuthStateHeuristic`
- `request_security_headers` = `inspectRequestSecurityHeaders(request)` per relevant request
- `response_security_headers` = `inspectResponseSecurityHeaders(response)` per relevant response

### Tier D — Realtime (lens-business-coherence with WS, opt-in)

Only if `window.__vg_ws_log` instrumented:
- `websocket_frames` via `captureWebSocketFrames`
- `polling_calls` from network_requests (filter URL pattern matching polling endpoint, group by interval)
- `background_job_status` via fetch /admin/jobs/dlq or equivalent

### Tier E — Visual/A11y (lens-modal-state, visual lens, opt-in for table)

Capture per major UI state change:
- `viewport_size` (capture once at session start, re-capture on resize)
- `focus_state` via `captureFocusState`
- `aria_state` via `captureAriaState(selector)` for interactive elements
- `tab_order` via `captureTabOrder` (first 30 focusable)
- `a11y_tree_excerpt` from MCP `browser_snapshot` (trimmed)

### Tier F — Storage/State (lens-business-coherence deep, lens-info-disclosure, lens-auth-jwt)

Keys ONLY, never values:
- `storage_keys` via `captureStorageKeys`
- `indexedDB_dbs` via `captureIndexedDBs`
- `store_snapshot` via `captureStoreSnapshot('__VG_STORE__')` if exposed

### Tier G — Mobile (only when MODE=mobile, replaces A-E)

Per Maestro:
- `hierarchy_diff` from before/after hierarchy.json
- `screenshot_diff_pct` from image diff
- `deep_link_resolved`, `tap_target_size_px`, `keyboard_avoidance`, `network_offline_recovery`

## Per-lens default tiers

The brief composer (Python script roam-compose-brief.py) injects tier list per lens:

| Lens | Default tiers | Rationale |
|---|---|---|
| `lens-form-lifecycle` | A + B | Form CRUD coverage |
| `lens-business-coherence` | A + B + F | UI/network/storage 3-way coherence |
| `lens-table-interaction` | A + B (row+field deltas) | List view URL state + pagination |
| `lens-duplicate-submit` | A + B (idempotency_replay) | Race + dup |
| `lens-csrf` | A + C | Token presence + cookie flags |
| `lens-idor` / `lens-bfla` / `lens-tenant-boundary` | A + C + (B if mutation) | Auth boundary + write paths |
| `lens-auth-jwt` | A + C + F | Token storage + headers + expiry |
| `lens-modal-state` | A + E | Focus trap + dismissal |
| `lens-info-disclosure` | A + C + F | Headers + storage keys |
| `lens-input-injection` | A + (C if auth-bypass) | Reflection patterns |
| `lens-file-upload` | A + B + (C if auth) | Mutation + size limits |
| `lens-business-logic` | A + B (state machine) | State-machine bypass |
| `lens-mass-assignment` | A + B + C | Privileged-field append |
| `lens-open-redirect` / `lens-path-traversal` / `lens-ssrf` | A + C | Network header inspection |

## Example — ACCEPTABLE event

```json
{"surface":"S03","step":"click submit","expected_per_lens":"POST /api/sites + 201 + redirect","observed":"5s elapsed, button enabled, URL unchanged","match":"no","evidence":{"network_requests":[],"console_errors":["TypeError at validate.ts:42"],"dom_changed":false,"elapsed_ms":5042},"timestamp":"<ISO>"}
```

## Example — UNACCEPTABLE event (will be rejected)

```json
{"surface":"S03","step":"click submit","observed":"submit BROKEN — critical bug, needs FIX","match":"failed","severity":"critical","recommendation":"fix validate.ts"}
```

Reasons: `BROKEN`/`critical`/`needs FIX` banned; `failed` not in match enum;
`severity` field is commander's job; `recommendation` is prescription.
"""


def select_lenses_for_surface(crud: str, entity: str, manual_csv: str | None) -> list[str]:
    """Auto-select lenses based on CRUD ops + entity type. Manual CSV override."""
    if manual_csv and manual_csv != "auto":
        return [s.strip() for s in manual_csv.split(",") if s.strip()]

    lenses = []
    if any(op in crud for op in "CUD"):
        lenses.append("lens-form-lifecycle")
        lenses.append("lens-business-coherence")
    if "R" in crud:
        lenses.append("lens-table-interaction")
    return lenses or ["lens-business-coherence"]


# Per-lens evidence tier defaults (scanner-report-contract Section 2.7).
# Each lens declares which tiers (A/B/C/D/E/F) capture-snippets must run on
# every observation. Tier G is mobile-only and dispatched via MODE=mobile,
# not lens config.
LENS_TIER_DEFAULTS = {
    "lens-form-lifecycle":      ["A", "B"],
    "lens-business-coherence":  ["A", "B", "F"],
    "lens-table-interaction":   ["A", "B"],
    "lens-duplicate-submit":    ["A", "B"],
    "lens-csrf":                ["A", "C"],
    "lens-idor":                ["A", "C", "B"],
    "lens-bfla":                ["A", "C", "B"],
    "lens-tenant-boundary":     ["A", "C", "B"],
    "lens-auth-jwt":            ["A", "C", "F"],
    "lens-modal-state":         ["A", "E"],
    "lens-info-disclosure":     ["A", "C", "F"],
    "lens-input-injection":     ["A", "C"],
    "lens-file-upload":         ["A", "B", "C"],
    "lens-business-logic":      ["A", "B"],
    "lens-mass-assignment":     ["A", "B", "C"],
    "lens-open-redirect":       ["A", "C"],
    "lens-path-traversal":      ["A", "C"],
    "lens-ssrf":                ["A", "C"],
    "lens-authz-negative":      ["A", "C"],
}


# Required field list per tier — validator post-write rejects observations
# missing any of these. Empty/null is OK (= fact). MISSING field = rejection.
TIER_REQUIRED_FIELDS = {
    "A": ["network_requests", "console_errors", "console_warnings", "dom_changed",
          "url_before", "url_after", "elapsed_ms", "screenshot", "page_title",
          "toast", "http_status_summary"],
    "B": ["form_validation_errors", "submit_button_state", "loading_indicator",
          "row_count_before", "row_count_after", "field_value_before",
          "field_value_after"],
    "C": ["cookies_filtered", "auth_state", "request_security_headers",
          "response_security_headers"],
    "D": ["websocket_frames", "polling_calls", "background_job_status"],
    "E": ["viewport_size", "focus_state", "aria_state", "tab_order",
          "a11y_tree_excerpt"],
    "F": ["storage_keys", "indexedDB_dbs", "store_snapshot"],
}


# Per-tier capture instruction text (injected into brief verbatim).
# v2.42.9+ — wording is HARD-ENFORCED. Validator rejects obs missing fields.
TIER_CAPTURE_INSTRUCTIONS = {
    "A": """### Tier A — Always-on (REQUIRED on EVERY observation)

⛔ MISSING any field below = observation REJECTED by post-write validator
   (verify-scanner-evidence-completeness.py). Empty array `[]` and `null` are
   FACTS — emit explicitly. Just OMITTING a field = NOT acceptable.

REQUIRED FIELDS (you MUST emit ALL of these in `evidence: { ... }`):
1. `network_requests` (array, can be []) — MCP `browser_network_requests`
2. `console_errors` (array, can be []) — MCP `browser_console_messages` filtered to errors
3. `console_warnings` (array, can be []) — MCP `browser_console_messages` filtered to warnings
4. `dom_changed` (boolean) — DOM hash diff before/after action
5. `url_before` (string) — URL before action
6. `url_after` (string) — URL after action (may equal url_before — that's a fact)
7. `elapsed_ms` (number) — Date.now() diff before/after action
8. `screenshot` (string|null) — relative path from `browser_take_screenshot`
9. `page_title` (string) — `browser_evaluate("() => document.title")`
10. `toast` (object) — `browser_evaluate(captureToast)` → `{ visible, count, items: [{text, type}] }`. Toast not visible? Emit `{ visible: false, count: 0, items: [] }`.
11. `http_status_summary` (object) — pure JS: `summarizeHttpStatus(network_requests)` → `{ "2xx": N, "3xx": N, "4xx": N, "5xx": N, cors_blocked: N, aborted: N }`. Zero requests? All counts = 0.

Helper file: `.claude/scripts/scanner-evidence-capture.js` (read once, reuse snippets).
""",
    "B": """### Tier B — Form/CRUD (REQUIRED when step touches form/list/mutation)

⛔ MISSING any field below = observation REJECTED by validator.
   Use snippets from `.claude/scripts/scanner-evidence-capture.js`.

REQUIRED FIELDS for any form/list step:
1. `form_validation_errors` — `browser_evaluate(captureFormValidationErrors)` → `{ count, items: [{field, message, source}] }`. No errors? `{ count: 0, items: [] }`.
2. `submit_button_state` — `browser_evaluate(captureSubmitButtonState)` → `{ found, text, disabled, busy }`. Element absent? `{ found: false }`.
3. `loading_indicator` — `browser_evaluate(captureLoadingIndicator)` → `{ present, selector?, bbox? }`. None? `{ present: false }`.
4. `row_count_before` (number) — `captureRowCount` BEFORE action.
5. `row_count_after` (number) — `captureRowCount` AFTER action.
6. `field_value_before` (object|null) — `captureFieldValue(name)` BEFORE for each relevant field. Multiple fields? Emit array.
7. `field_value_after` (object|null) — `captureFieldValue(name)` AFTER.

CONDITIONAL FIELDS (emit when applicable):
- `db_read_after_write` — for mutations, follow-up GET to verify persistence. Emit `{ method, url, status, body_match: yes|no|partial }`.
- `idempotency_replay` — for endpoints with Idempotency-Key, re-submit, emit `{ second_call_status, response_id_matches: yes|no|unknown }`.

Compute `row_count_delta` (after - before) and `field_value_delta` BEFORE merging.
""",
    "C": """### Tier C — Auth/Session/Security (REQUIRED on auth-sensitive steps)

⛔ MISSING any field = observation REJECTED.

REQUIRED FIELDS on login, role-switch, mutation requiring privilege, cross-tenant probe:
1. `cookies_filtered` — `browser_evaluate(captureCookiesFiltered)` → `{ document_cookie_count, names: [...] }`. NAMES ONLY, NEVER values.
2. `auth_state` — `browser_evaluate(captureAuthStateHeuristic)` → `{ authenticated, signal }`.
3. `request_security_headers` — pure JS `inspectRequestSecurityHeaders(req)` per relevant request → `{ has_authorization, has_csrf_token, has_idempotency_key, has_if_match, has_origin, has_referer, custom_headers }`. No security request? Emit `null` (= "no auth-sensitive request in this step").
4. `response_security_headers` — pure JS `inspectResponseSecurityHeaders(resp)` → `{ has_set_cookie, set_cookie_flags, has_csp, has_x_frame_options, has_strict_transport_security }`.
""",
    "D": """### Tier D — Realtime (REQUIRED when lens declares D, even if instrumentation absent)

⛔ MISSING any field = observation REJECTED.

REQUIRED FIELDS:
1. `websocket_frames` — `browser_evaluate(captureWebSocketFrames)` → `{ instrumented: bool, count, frames }`. App not instrumented? `{ instrumented: false, count: 0, frames: [] }` — explicit fact.
2. `polling_calls` — filter `network_requests` by URL pattern from config `scanner_evidence.realtime.polling_url_patterns`, group by interval. No polling? `[]`.
3. `background_job_status` — fetch /admin/jobs/dlq or equivalent → `{ status, queue_summary }`. Endpoint absent? `null`.
""",
    "E": """### Tier E — Visual/A11y (REQUIRED on major UI state change)

⛔ MISSING any field = observation REJECTED.

REQUIRED FIELDS on page load / modal open / route change:
1. `viewport_size` — `{ width, height }` from `browser_resize` or initial snapshot.
2. `focus_state` — `browser_evaluate(captureFocusState)` → `{ focused, tag, id?, name?, role?, label }`.
3. `aria_state` — `browser_evaluate(captureAriaState(selector))` for interactive elements relevant to lens. Single relevant element? Emit one object. Multiple? Array. None? `null`.
4. `tab_order` — `browser_evaluate(captureTabOrder)` → array of first 30 focusable elements.
5. `a11y_tree_excerpt` — string from MCP `browser_snapshot` output (trim per `config.scanner_evidence.a11y.snapshot_max_lines`).
""",
    "F": """### Tier F — Storage/Client State (REQUIRED when lens declares F)

⛔ MISSING any field = observation REJECTED.

REQUIRED FIELDS — KEYS ONLY, NEVER VALUES (PII/token risk, validator rejects values):
1. `storage_keys` — `browser_evaluate(captureStorageKeys)` → `{ localStorage_keys: [...], sessionStorage_keys: [...], count: { local, session } }`. Empty? `[]` arrays + `0` counts.
2. `indexedDB_dbs` — `browser_evaluate(captureIndexedDBs)` → `{ supported, dbs: [{name, version}] }`. Browser doesn't support? `{ supported: false, dbs: [] }`.
3. `store_snapshot` — `browser_evaluate(captureStoreSnapshot('__VG_STORE__'))` → `{ exposed, key, top_level_keys: [...] }`. Not exposed by app? `{ exposed: false, key: '__VG_STORE__' }`.
""",
}


def render_tier_instructions(lens: str) -> str:
    """Render evidence-tier capture block for a specific lens.

    v2.42.9+ — wording is HARD-ENFORCED. Validator
    verify-scanner-evidence-completeness.py rejects observations missing
    any required field per declared tiers.
    """
    tiers = LENS_TIER_DEFAULTS.get(lens, ["A"])
    required_fields = []
    for t in tiers:
        required_fields.extend(TIER_REQUIRED_FIELDS.get(t, []))

    parts = [
        f"## ⛔ EVIDENCE CAPTURE CONTRACT — HARD ENFORCED (this lens: {' + '.join(tiers)})\n",
        "Per scanner-report-contract Section 2.5 + 2.7. **Validator rejects observations missing any required field.** Empty/null is a FACT — emit explicitly. Just OMITTING a field = REJECTED.\n",
        "**Helper file:** `.claude/scripts/scanner-evidence-capture.js` (21 snippets — read once, reuse).\n",
        f"**Total required fields per observation: {len(required_fields)}**\n",
    ]
    for t in tiers:
        if t in TIER_CAPTURE_INSTRUCTIONS:
            parts.append(TIER_CAPTURE_INSTRUCTIONS[t])
    skipped = sorted(set("ABCDEF") - set(tiers))
    parts.append(f"**Tiers NOT captured by this lens:** {skipped} — fields from these tiers MUST NOT appear in observation. If you accidentally capture them, omit silently.\n")
    parts.append("---\n")
    parts.append("### Pre-merge self-check (run before emitting each observation)\n")
    parts.append(f"Confirm `evidence` object has ALL {len(required_fields)} keys:\n")
    parts.append("```\n" + "\n".join(f"- {f}" for f in required_fields) + "\n```\n")
    parts.append("Missing key? Add `<key>: null` (= 'we tried, value unavailable'). Then emit.\n")
    return "\n".join(parts)


def parse_surfaces_md(path: Path) -> list[dict]:
    """Parse the SURFACES.md table generated by roam-discover-surfaces.py.

    Tolerates entity="?" (the discover script's fallback for unknown entity).
    """
    surfaces = []
    if not path.exists():
        return surfaces
    text = path.read_text(encoding="utf-8")
    row_re = re.compile(r"^\|\s*(S\d+)\s*\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|\s*(\S+)\s*\|\s*(\w*)\s*\|\s*(.*?)\s*\|")
    for line in text.split("\n"):
        m = row_re.match(line)
        if m:
            surfaces.append({
                "id": m.group(1),
                "url": m.group(2),
                "role": m.group(3),
                "entity": m.group(4),
                "crud": m.group(5),
                "sub_views": m.group(6),
            })
    return surfaces


def find_role_creds(creds: dict, surface_role: str) -> dict | None:
    """Pick credential entry matching surface role; fallback to first role.

    surface.role values seen: admin, merchant, vendor, user (from
    roam-discover heuristic). Match against creds.roles[*].role exact, then
    by prefix (e.g. surface=admin → admin OR superadmin), then fallback.
    """
    roles = (creds or {}).get("roles", [])
    if not roles:
        return None
    # Exact
    for r in roles:
        if r.get("role") == surface_role:
            return r
    # Prefix match
    for r in roles:
        rname = r.get("role", "")
        if rname.startswith(surface_role) or surface_role.startswith(rname.split("-")[0]):
            return r
    return roles[0]


def render_login_preflight(env: str, target_url: str, role_creds: dict, surface_role: str) -> str:
    if not role_creds:
        return f"""## Pre-flight — login (env: {env})

⚠ No credentials available for role `{surface_role}` on env `{env}`.
   Executor must read `.claude/vg.config.md` `credentials.{env}` and pick a
   matching role. If env=prod, login is read-only — do NOT submit forms.
"""
    role = role_creds.get("role", surface_role)
    domain = role_creds.get("domain", "")
    email = role_creds.get("email", "")
    password = role_creds.get("password", "")
    proto = "http" if any(s in domain for s in ("localhost", "127.")) else "https"
    login_url = f"{proto}://{domain}/login"
    return f"""## Pre-flight — login FIRST (env: {env})

You MUST login BEFORE running the protocol below. Do NOT navigate to the
target surface URL until login completes — unauthenticated requests will
return 404/401 and every protocol step will report `precondition_missing`,
yielding a useless run.

### Login steps (verbatim, role = `{role}`):

1. `browser_navigate` → `{login_url}`
2. `browser_snapshot` to confirm login form is visible
3. `browser_fill_form` (or `browser_type` per field) with:
   - email/username: `{email}`
   - password: `{password}`
4. Submit (click login button or press Enter)
5. `browser_wait_for` (e.g. waitForURL away from /login, or for dashboard nav)
6. `browser_snapshot` to confirm authenticated state (sidebar visible, user
   menu shows `{email}`, etc.)

### Login confirmation event (emit BEFORE protocol step 1):

```
{{"surface": "<surface_id>", "step": "login", "ui_after": {{"url": "<post-login-url>", "authenticated": true}}, "network": [...], "timestamp": "<ISO>"}}
```

If login fails (wrong creds, server error, MFA required), emit:
```
{{"surface": "<surface_id>", "step": "login", "ui_after": {{"authenticated": false}}, "error": "<reason>", "timestamp": "<ISO>"}}
```
Then STOP — do not proceed with protocol; no point exercising surface as
unauthenticated.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--surfaces", required=True, help="Path to SURFACES.md")
    ap.add_argument("--lenses", default="auto", help="csv list or 'auto'")
    ap.add_argument("--output-dir", required=True, help="Per-model dir, e.g. <phase>/roam/codex/")
    ap.add_argument("--env", default="local", help="env name (local|sandbox|staging|prod)")
    ap.add_argument("--target-url", default="", help="Resolved target URL prefix from env, e.g. http://localhost:3001")
    ap.add_argument("--creds-json", default="", help="Path to .env-creds.json with roles+credentials for this env")
    ap.add_argument("--model", default="codex", help="Model name for cwd convention + filename suffix")
    ap.add_argument("--cwd-convention", default="", help="Executor cwd, e.g. ${PHASE_DIR}/roam/codex (used in JSONL output path)")
    ap.add_argument("--include-security", default="false")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    surfaces = parse_surfaces_md(Path(args.surfaces))
    if not surfaces:
        print("[roam-compose] no surfaces found — run /vg:roam step 1 first", file=sys.stderr)
        return 2

    creds = {}
    if args.creds_json:
        cp = Path(args.creds_json)
        if cp.exists():
            try:
                creds = json.loads(cp.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[roam-compose] WARN: bad creds-json: {e}", file=sys.stderr)

    lens_dir = Path(".claude/commands/vg/_shared/lens-prompts")

    cwd_label = args.cwd_convention or f"${{PHASE_DIR}}/roam/{args.model}"

    brief_count = 0
    for surface in surfaces:
        lenses = select_lenses_for_surface(surface["crud"], surface["entity"], args.lenses)

        if args.include_security != "true":
            lenses = [l for l in lenses if not any(s in l for s in ("csrf", "idor", "bfla", "ssrf", "auth-jwt", "input-injection", "open-redirect", "path-traversal", "tenant-boundary", "info-disclosure", "file-upload"))]

        role_creds = find_role_creds(creds, surface["role"])
        login_section = render_login_preflight(args.env, args.target_url, role_creds, surface["role"])

        # Build absolute target URL for the surface
        if args.target_url:
            base = args.target_url.rstrip("/")
            url_path = surface["url"] if surface["url"].startswith("/") else "/" + surface["url"]
            absolute_url = base + url_path
        else:
            absolute_url = surface["url"]

        for lens in lenses:
            lens_md = lens_dir / f"{lens}.md"
            if not lens_md.exists():
                print(f"[roam-compose] WARN: lens {lens} not found, skipping", file=sys.stderr)
                continue

            lens_text = lens_md.read_text(encoding="utf-8")
            if lens_text.startswith("---\n"):
                lens_text = lens_text.split("\n---\n", 1)[1] if "\n---\n" in lens_text else lens_text

            brief_id = f"{surface['id']}-{lens}"
            brief_path = out_dir / f"INSTRUCTION-{brief_id}.md"
            jsonl_filename = f"observe-{brief_id}.jsonl"

            content = f"""# ROAM EXECUTOR INSTRUCTION — {brief_id}

## Target

- **Surface ID:** {surface['id']}
- **Surface URL (absolute):** `{absolute_url}`
- **Auth role:** `{surface['role']}`
- **Entity:** {surface['entity']}
- **CRUD ops observed:** {surface['crud'] or 'R'}
- **Lens:** {lens}
- **Env:** `{args.env}`
- **Model (cwd):** `{args.model}`

## Working directory + output target

- **CWD:** `{cwd_label}` (executor MUST run from this directory)
- **Output JSONL:** `{jsonl_filename}` (relative to cwd, NOT phase dir)
- One JSON object per line, no markdown, no commentary outside JSON.
- Schema per ROAM-RFC-v1.md appendix B. Required keys per event:
  `surface`, `step`, `ui_before` / `ui_after`, `network`, `console_errors`, `timestamp`.

{login_section}

{render_tier_instructions(lens)}

---

## Lens-specific protocol

{lens_text.strip()}

---

## Prod-env safety (when env=prod)

If env is `prod`, this is a **READ-ONLY** run. SKIP every protocol step that
mutates state (form submit, delete confirm, bulk-action confirm, sort/filter
that triggers writes). Continue read-only steps (snapshot, network capture).
Emit `{{"surface":"...","step":"<name>","skipped":true,"reason":"prod-read-only"}}`
for skipped mutation steps.

For env={args.env}, mutations are allowed per the lens protocol unless the
lens itself flags otherwise.

---

{HARD_RULES}

---

## Done signal

After completing ALL protocol steps, emit ONE final event:

```
{{"surface": "{surface['id']}", "step": "complete", "total_events": <int>, "lens": "{lens}", "timestamp": "<ISO>"}}
```

Then exit. Commander aggregates and analyzes.
"""
            brief_path.write_text(content, encoding="utf-8")
            brief_count += 1

    print(f"[roam-compose] wrote {brief_count} INSTRUCTION-*.md to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
