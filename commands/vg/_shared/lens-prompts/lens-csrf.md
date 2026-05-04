---
name: lens-csrf
description: Cross-Site Request Forgery — missing/weak CSRF token, SameSite cookie misconfiguration, CORS-credentialed exposure, method-override smuggling
bug_class: auth
applies_to_element_classes:
  - mutation_button
  - form_trigger
  - bulk_action
  - auth_endpoint
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/csrf.md
severity_default: warn
estimated_action_budget: 30
output_schema_version: 3

# Task 26 / Task 36a additions:
recommended_worker_tier: haiku
worker_complexity_score: 2
fallback_on_inconclusive: sonnet
min_actions_floor: 4
min_evidence_steps: 3
required_probe_kinds: [token_missing, samesite_probe, cors_credentialed]
---

# Lens: CSRF (Cross-Site Request Forgery)

## Threat model

CSRF exploits the browser's automatic credential attachment: when a logged-
in user visits an attacker page, the browser will helpfully attach session
cookies to any request the attacker page issues — form submissions, image
loads, fetch with `credentials: 'include'`. If the server authorizes purely
on cookie-based session AND has no anti-CSRF defense (token, double-submit
cookie, SameSite=Lax/Strict, Origin/Referer check), the attacker can
trigger any state-changing action on behalf of the victim. Modern defenses
have layered failure modes: SameSite=None or no SameSite attribute makes
the cookie cross-site usable; CORS misconfigured to allow credentials with
a wildcard or reflected Origin reopens the same hole for fetch; method-
override headers (`X-HTTP-Method-Override: POST`, `?_method=DELETE`)
smuggle a state-changing verb through a route the framework only protects
on `POST`; missing CSRF token, predictable token, or token not bound to
session. White-box VG workers can replay the captured authenticated
mutation while stripping or tampering with the CSRF defenses to see which
layers actually enforce.

## Activation context (auto-injected by VG)

The dispatcher (`scripts/spawn-recursive-probe.py`) substitutes these
placeholders before handing the prompt to the worker subprocess. Reference them
via `${VAR}` exactly as written; never hard-code values.

- View: `${VIEW_PATH}`
- Element: `${ELEMENT_DESCRIPTION}` (selector: `${SELECTOR}`)
- Element class: `${ELEMENT_CLASS}`
- Resource: `${RESOURCE}` (scope: `${SCOPE}`)
- Role: `${ROLE}` with auth token `${TOKEN_REF}`
- Base URL: `${BASE_URL}`
- Peer credentials (cross-tenant probe, nullable): `${PEER_TOKEN_REF}`
- Run artifact output path: `${OUTPUT_PATH}`
- Action budget: `${ACTION_BUDGET}` browser actions max
- Recursion depth: `${DEPTH}`
- Wall-clock budget: 5 minutes

## Probe-only contract (HARD CONSTRAINT — read this first)

You are a probe + report worker. You are NOT a judge, NOT a fixer.

Worker MUST NOT:

- Propose code fixes or remediation ("To fix this, change X to Y" — NO).
- Assign severity ("This is critical / high / medium" — NO).
- Reason about exploit chains ("If combined with bug Z, attacker could…" — NO).
- Recommend further probing beyond this lens's declared scope.

Worker MUST:

- Explore freely within the action budget.
- Report factual `steps[].status = pass|fail|inconclusive`.
- Capture raw `observed` evidence (status code, body excerpt, DOM diff).
- Append a `finding_fact` to `runs/.broker-context.json` when a step fails —
  facts only:

```json
{"lens": "lens-csrf", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find CSRF vulnerabilities affecting `${ELEMENT_DESCRIPTION}` and any
sub-mutations you discover during exploration. The interest is whether the
state-changing endpoint requires more than just an authenticated cookie/
session — i.e. is there a token, a SameSite restriction, an Origin/Referer
check, a custom header that the browser would not let an attacker page
forge? You are a security researcher, not a test runner. Click anything
that looks promising, follow the workflow, dig into anomalies. Adapt to
what you observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture the mutation request. Not
a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, click + capture the mutation
   request. Note: cookies attached, CSRF token (header or body), Origin
   header, Referer header, custom headers (`X-Requested-With`), Content-
   Type. Inspect Set-Cookie SameSite attribute for the session cookie.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Strip CSRF token: remove the `X-CSRF-Token` header (and/or the
  `csrf_token` body field) and replay; expect 403. A 200 indicates the
  token is decorative — server doesn't actually verify.
- Tamper / replay token: send a token that belonged to a different
  session, an empty token (`X-CSRF-Token:` blank), or a static well-
  known value (`X-CSRF-Token: 0`). If accepted, the token is not bound
  to session.
- SameSite probe: inspect the session cookie's `SameSite` attribute. If
  `None` or absent (older browsers default to `None`), cross-site form
  POST will attach the cookie. Also check whether the `Secure` attribute
  is set (required for `SameSite=None`).
- Origin / Referer strip: remove or spoof the `Origin` header
  (`Origin: https://attacker.local`); remove `Referer`. If server still
  authorizes, it doesn't validate request provenance.
- CORS-credentialed misconfiguration: send a preflight `OPTIONS` from
  `Origin: https://attacker.local` to the mutation endpoint; if the
  response includes `Access-Control-Allow-Origin: https://attacker.local`
  (reflected) AND `Access-Control-Allow-Credentials: true`, fetch-based
  CSRF is open.
- Method-override smuggling: if the server requires `POST` for mutation,
  try `GET /resource?_method=POST&...`, `POST /resource` with
  `X-HTTP-Method-Override: DELETE`, or `application/x-www-form-urlencoded`
  body when the protected endpoint expected `application/json` (Rails
  CSRF historically scoped only to JSON content type).
- GET-mutation: search for any state-changing endpoint that accepts
  parameters via `GET` query string — those are auto-CSRF (`<img
  src="/api/delete?id=42">` works in any browser).
- Login CSRF: try CSRFing the login endpoint to fixate a known session;
  if successful, the attacker can pre-auth the victim into the attacker's
  account and harvest later input.

## How to explore recursively (anti-script discipline)

- Strip / tamper a CSRF defense and replay the captured request. Note
  status code, response body, and whether the state actually changed
  (re-read the resource).
- After each probe, browser_snapshot. New mutation buttons / forms / sub-
  views → click those too (recursive within this element's reach), and
  apply CSRF probes to each new mutation surfaced.
- If a probe yields an anomaly (token missing accepted, SameSite=None,
  CORS+credentials reflected) → DIG: try the same probe on neighbor
  mutations, check whether the bypass works on the bulk-action variant
  (often less protected than per-row), test login-CSRF.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" mutations like "change preference" or
  "mark read" without at least 1 CSRF probe — those are commonly
  unprotected because "low impact".

## Stopping criteria

Stop and write the artifact when ANY of:

- Action budget `${ACTION_BUDGET}` exhausted
- Wall-clock 5 minutes reached
- High-confidence finding captured + ≥3 supporting probes done
- 2 consecutive actions yield no new anomaly AND no new clickables —
  diminishing returns

## Run artifact write

After exploration ends (stopping criteria triggered), write JSON to `${OUTPUT_PATH}`:

```json
{
  "schema_version": 3,
  "worker_tool": "gemini" | "codex" | "claude",
  "run_id": "<element-slug>-lens-csrf-<role>-<depth>",
  "lens": "lens-csrf",
  "resource": "${RESOURCE}",
  "role": "${ROLE}",
  "element_class": "${ELEMENT_CLASS}",
  "selector_hash": "<sha256[:8]>",
  "view": "${VIEW_PATH}",
  "depth": ${DEPTH},
  "actions_taken": <int>,
  "stopping_reason": "budget" | "timeout" | "confidence" | "diminishing_returns",
  "steps": [
    {
      "name": "<short description of what you did/observed>",
      "status": "pass" | "fail" | "inconclusive",
      "observed": { "status_code": <int>, "body_excerpt": "<1-2 line raw>", "dom_diff": "<optional>" },
      "evidence_ref": ["<network_log_entry_id>", ...]
    }
  ],
  "coverage": {"passed": N, "failed": M, "inconclusive": K},
  "replay_manifest": {
    "commit_sha": "<auto>",
    "worker_prompt_version": "lens-csrf-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-csrf",
    "view": "${VIEW_PATH}",
    "element_class": "${ELEMENT_CLASS}",
    "resource": "${RESOURCE}",
    "parent_goal_id": "<from CRUD-SURFACES if matchable, else null>"
  }
}
```

`priority` is NOT included in worker output — aggregator assigns post-run from
`lens.severity_default` × `step.status` mapping.

## Termination

- After exploration ends → write the run artifact → call browser_close →
  output `DONE`.
- DO NOT navigate to other views (the VG manager handles cross-view recursion).
- DO NOT spawn child agents (deterministic dispatcher only).
- If action budget is exhausted before exploration feels complete, write a
  partial artifact with `stopping_reason: "budget"` — that is normal and the
  aggregator handles it.
