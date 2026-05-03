---
name: lens-info-disclosure
description: Information disclosure — stack-trace leak via 500, exposed dotfiles/.env/.git/debug routes, source maps, verbose response headers
bug_class: server-side
applies_to_element_classes:
  - error_response
  - sub_view_link
  - mutation_button
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/information_disclosure.md
severity_default: warn
estimated_action_budget: 35
output_schema_version: 3
---

# Lens: Information Disclosure

## Threat model

Information disclosure is the cumulative leakage of internals — stack
traces, framework version, file paths, source code, debug pages, secret
fragments — that on its own may be "low severity" but in aggregate fuels
every other attack class. Common surfaces: a 500 error revealing a Python/
Java/Ruby stack trace with absolute file paths, function names, and SQL
query fragments; an unprotected `.env` / `.git/config` / `web.config` /
`appsettings.json` served as static; debug routes left enabled in
production (`/debug`, `/__debug__/`, `/_admin/`, `/actuator/env`,
`/metrics`); JS source maps shipped to production (`*.js.map` reveals
TypeScript pre-minified source); response headers betraying tech stack
(`X-Powered-By`, `Server`, `X-AspNet-Version`); error verbosity
differential (404 vs 403 vs 200 used to enumerate users / resources);
verbose login response distinguishing "user not found" from "wrong
password"; response timing differential. White-box VG workers can probe
known-bad endpoints, induce error states, inspect headers, and aggregate
the leakage signal.

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
{"lens": "lens-info-disclosure", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find information-disclosure leaks affecting `${ELEMENT_DESCRIPTION}` and
the surrounding view / origin. The leak surfaces are: error responses
this element can produce, static-file paths reachable from the same
origin, debug routes co-located with the application, response headers
on every request, and verbosity differentials in error messages. You are
a security researcher, not a test runner. Click anything that looks
promising, follow the workflow, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture a baseline. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Capture the baseline
   request/response pair. Inspect response headers (`Server`,
   `X-Powered-By`, `X-AspNet-Version`, `Via`, framework cookies). Note
   the response shape on success — you will compare it to error variants.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Induce 500 errors: send malformed JSON (`{`), oversized payloads
  (10MB), unexpected types (string where int expected), null bytes,
  invalid UTF-8 sequences. Inspect the 500 body for stack-trace
  fragments, file paths (`/var/www/app/...`, `C:\\inetpub\\wwwroot\\
  ...`), framework versions, SQL query fragments.
- Static / dotfile probe: from `${BASE_URL}` directly fetch `.env`,
  `.git/config`, `.git/HEAD`, `.svn/entries`, `.DS_Store`,
  `web.config`, `appsettings.json`, `composer.json`, `package.json`,
  `WEB-INF/web.xml`, `wp-config.php.bak`. Record each 200.
- Debug routes: `/debug`, `/__debug__/`, `/_debug/`, `/admin`,
  `/actuator/env`, `/actuator/heapdump`, `/actuator/mappings`,
  `/metrics`, `/health/detail`, `/_status/`, `/server-status`,
  `/trace.axd`, `/Trace.axd`, `/elmah.axd`, `/swagger`, `/api-docs`,
  `/graphql/playground`, `/graphiql`. Try with and without
  `${TOKEN_REF}`.
- Source maps: fetch `${BASE_URL}/static/js/<bundle>.js.map`. If served,
  the original TypeScript source (often with comments and unminified
  variable names) is exposed.
- Response header sweep: on the captured baseline + each error response,
  enumerate every response header. `X-Powered-By`, `Server`,
  `X-AspNet-Version`, `X-AspNetMvc-Version`, `X-Runtime`, `X-Backend-
  Server`, `X-Drupal-Cache`, `Via`, custom build IDs all narrow the
  attack-tool selection.
- Error-message verbosity / oracle: on a login or password-reset form,
  compare responses for "valid user wrong password" vs "invalid user".
  If different (text, status, timing, response length), the endpoint is
  a username oracle.
- Robots / sitemap / well-known: `${BASE_URL}/robots.txt`, `/sitemap.xml`,
  `/.well-known/` enumeration. Disallow rules often list admin paths.
- Verbose API metadata: GraphQL `__schema { types { name fields { name }
  } }` introspection; OpenAPI / Swagger JSON at `/openapi.json`,
  `/v2/api-docs`. Reveals every endpoint and their auth requirements.

## How to explore recursively (anti-script discipline)

- Issue each probe, capture the full response including all headers.
  Note any leaked file path, version string, secret fragment, or
  internal route name.
- After each probe, browser_snapshot. New routes / sub-pages / debug
  toolbar links → click those too (recursive within this element's
  reach), and probe the same disclosure surfaces on each.
- If a probe yields an anomaly (stack trace with absolute path, source
  map served, debug route 200, version disclosed) → DIG: chain probes
  (use the disclosed framework version to fetch its known debug routes,
  use the disclosed file path to attempt path-traversal in another
  element).
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" 404 / 500 pages without inspecting their
  body and headers — error pages are a primary leak surface.

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
  "run_id": "<element-slug>-lens-info-disclosure-<role>-<depth>",
  "lens": "lens-info-disclosure",
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
    "worker_prompt_version": "lens-info-disclosure-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-info-disclosure",
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
