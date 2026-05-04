---
name: lens-open-redirect
description: Open redirect — bypass redirect-target validation via scheme tricks, encoding, fragment confusion, referer-based redirects
bug_class: redirect
applies_to_element_classes:
  - redirect_url_param
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/open_redirect.md
severity_default: warn
estimated_action_budget: 25
output_schema_version: 3

# Task 26 / Task 36a additions:
recommended_worker_tier: haiku
worker_complexity_score: 2
fallback_on_inconclusive: sonnet
min_actions_floor: 5
min_evidence_steps: 4
required_probe_kinds: [scheme_trick, encoding_bypass, fragment_confusion]
---

# Lens: Open Redirect

## Threat model

Open redirect arises whenever the application accepts a user-supplied URL
or path and issues an HTTP 30x or client-side `window.location` to that
target without strictly validating that the destination stays on the
intended origin. Common surfaces: `/login?next=<url>` post-login redirect,
OAuth `redirect_uri`, "you are leaving our site" interstitial, `/logout?
return=<url>`, email-link post-action redirect, SSO session-bridge
redirect, multistep wizard `?continue=<url>`. Phishing weaponizes this
because the link starts on the trusted origin (`https://victim.com/
login?next=https://evil.com`) and the browser address bar shows the
trusted origin until the redirect fires. Defenses fail in characteristic
ways: scheme bypass via `//evil.com` (protocol-relative — browser uses
current scheme), `javascript:alert(1)` (XSS-via-redirect),
`data:text/html,<script>...</script>`; URL-parser disagreement
(`https://evil.com\@victim.com` — server's parser thinks host is
`victim.com`, browser thinks `evil.com`); fragment / userinfo confusion
(`https://victim.com#@evil.com`, `https://victim.com@evil.com`); encoded
variants (`%2F%2Fevil.com`, `\/\/evil.com`, `\\evil.com`); subdomain
takeover (allowlist `*.victim.com` then `evil.victim.com` if takeable).
White-box VG workers can submit each variant to the redirect param and
inspect both the `Location` header and the resulting browser navigation.

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
{"lens": "lens-open-redirect", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find open-redirect vulnerabilities affecting `${ELEMENT_DESCRIPTION}` and
any sub-redirects you discover during exploration. Identify the param
that controls the redirect target (`?next=`, `?return=`, `?redirect_uri=`,
`?continue=`, `?url=`, `?goto=`, `?dest=`, `?back=`, fragment `#redirect=`,
or POST body field). You are a security researcher, not a test runner.
Click anything that looks promising, follow the workflow, dig into
anomalies. Adapt to what you observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture the redirect baseline.
Not a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Trigger the redirect with a
   benign same-origin target. Capture both the response 30x `Location`
   header (or the JS `window.location.href` setter) and the final landed
   URL.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Direct external host: submit `?next=https://evil.com`. Expect either a
  block or a same-origin rewrite. A 30x or JS-set redirect to `evil.com`
  is open redirect.
- Protocol-relative: submit `?next=//evil.com`. The browser appends the
  current scheme; some validators see `//evil.com` and don't recognise
  it as absolute.
- Backslash-prefix (Windows / browser quirk): `?next=\\\\evil.com`,
  `?next=\/\/evil.com`. Some URL parsers treat backslash differently
  from forward slash; browsers may normalise to `//evil.com`.
- Scheme injection: `?next=javascript:alert(1)`,
  `?next=data:text/html,<script>alert(1)</script>`,
  `?next=vbscript:msgbox(1)`. A redirect to `javascript:` becomes XSS.
- Userinfo / fragment confusion: `?next=https://victim.com@evil.com/`,
  `?next=https://evil.com#@victim.com`, `?next=https://victim.com.evil.
  com/`. URL-parser disagreement between validator and browser is the
  exploit.
- Encoded variants: `?next=%2F%2Fevil.com`, `?next=%2f%2fevil.com`,
  double-encoded `?next=%252F%252Fevil.com`, Unicode `?next=//ｅｖｉｌ.
  com` (fullwidth chars normalising to ASCII).
- Allowlist bypass: if the validator only checks the suffix (`.victim.
  com`), submit `?next=https://evil.com.victim.com` (subdomain
  attacker-controllable) or `?next=https://victim.com.evil.com`. Also
  try `?next=https://victim.evil.com.victim.com` (multi-occurrence).
- Whitelist of known-good paths: if `?next=/dashboard` is allowed and
  `https://...` is blocked, try `?next=/\\evil.com`, `?next=/%5Cevil.
  com`, or `?next=//evil.com/dashboard`.
- Referer-based redirect: if no explicit param, the redirect may follow
  the `Referer` header. Set Referer to `https://evil.com` and trigger
  the action.
- Fragment-target XSS: `?next=#<svg onload=alert(1)>` — when the JS sets
  `location.hash`, some apps render hash content into the DOM via
  `location.hash.slice(1)` interpolation.

## How to explore recursively (anti-script discipline)

- Submit each redirect-target variant, capture the response. Note the
  `Location` header verbatim, the final landed URL after browser
  follows the chain, and any `Set-Cookie` issued en route (token leak
  during cross-origin redirect).
- After each probe, browser_snapshot. New buttons triggering further
  redirects (logout, switch-account, sso-link) → click those too
  (recursive within this element's reach), and apply the same probe set
  to each new redirect param.
- If a probe yields an anomaly (external redirect honored, javascript:
  scheme accepted, parser-disagreement bypass works) → DIG: chain to a
  cookie-leaking page on attacker-host, test whether OAuth callbacks
  honor the same bypass, observe whether the post-redirect referer
  carries auth tokens.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" same-origin redirects without at least 1
  external-host probe — login `next` params are the highest-value
  surface.

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
  "run_id": "<element-slug>-lens-open-redirect-<role>-<depth>",
  "lens": "lens-open-redirect",
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
    "worker_prompt_version": "lens-open-redirect-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-open-redirect",
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
