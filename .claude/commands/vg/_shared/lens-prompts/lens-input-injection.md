---
name: lens-input-injection
description: Input injection — XSS, SQL injection, template injection, command injection via form fields, query params, file metadata
bug_class: injection
applies_to_element_classes:
  - form_trigger
  - file_upload
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/xss.md
severity_default: warn
estimated_action_budget: 50
output_schema_version: 3

# Task 26 / Task 36a additions:
recommended_worker_tier: haiku
worker_complexity_score: 2
fallback_on_inconclusive: sonnet
min_actions_floor: 6
min_evidence_steps: 4
required_probe_kinds: [xss_form_field, sql_injection, template_injection]
---

# Lens: Input Injection

## Threat model

Whenever a user-controlled string crosses a parser boundary — HTML/JS in the
DOM, SQL in the database driver, a Jinja/Handlebars template, a shell
invocation, or LDAP / NoSQL query DSL — and the application interpolates the
raw value instead of binding/escaping it, the attacker controls the parser's
control plane. The bug class spans reflected and stored XSS (script execution
in another user's browser), SQL injection (data exfiltration, auth bypass,
RCE pivot), server-side template injection (RCE in the templating sandbox
escape), and command injection (shell metacharacters reaching `system()`).
White-box VG workers, holding `${TOKEN_REF}` and live network capture, can
submit a known marker payload through every input on the form, observe both
the reflected response and any second-order render in another view, and
detect parser breakouts deterministically — control characters in echoes,
SQL error fragments in 500 responses, template arithmetic results, or DNS
exfil callbacks.

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
{"lens": "lens-input-injection", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find input-injection vulnerabilities affecting `${ELEMENT_DESCRIPTION}` and
any sub-elements you discover during exploration. Every text field, hidden
form value, query param, file metadata field (filename, EXIF, ZIP entry
name), JSON body key, and header is an injection candidate. Refer to
`docs/security/ADVERSARIAL-PAYLOAD-LIBRARY.md` (curated marker payloads).
You are a security researcher, not a test runner. Click anything that looks
promising, follow the workflow, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture the form schema. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, enumerate every input on the form
   (name, type, hidden fields, accepted MIME types). Submit a benign baseline
   to capture the success-path request shape and response render location.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- XSS markers: submit `<script>alert(1)</script>`, `"><svg onload=alert(1)>`,
  `javascript:alert(1)` (URL-context fields), and `\` + event-handler attrs
  (`" onmouseover=alert(1) x="`). After submit, navigate to any view that
  re-renders the value (list, detail, audit log, email preview) and check
  for unescaped reflection in DOM.
- SQL injection: classic boolean (`' OR 1=1--`, `" OR ""="`), error-based
  (`'`, `"` solo to provoke 500 + driver fragment), time-based blind
  (`'; WAITFOR DELAY '0:0:5'--`, `' OR SLEEP(5)--`), UNION sniffing
  (`' UNION SELECT NULL,NULL--` then widen). Watch for response timing,
  error-message DB fingerprint, structural body diff.
- Template injection: `{{7*7}}`, `${7*7}`, `<%= 7*7 %>`, `#{7*7}`,
  `{{constructor.constructor("alert(1)")()}}`. A response containing `49`
  where `{{7*7}}` was sent confirms server-side template eval.
- Command injection: append shell metacharacters in any field that may
  reach a subprocess (filename for image processing, hostname for ping,
  URL for fetcher) — `; sleep 5`, `| whoami`, `` `id` ``, `$(id)`,
  newline-prefixed payloads. Watch for delay or command output echoed.
- Encoding bypass: try URL-encoded (`%3Cscript%3E`), double-encoded
  (`%253C`), HTML-entity (`&lt;script&gt;`), Unicode-equivalent
  (`<script>`), null-byte truncation (`payload%00.jpg`). WAFs and naive
  blacklist filters often miss one variant.
- File upload metadata: if `file_upload` is in scope, embed payloads in
  filename (`<svg onload=alert(1)>.jpg`), EXIF comment, ZIP entry name,
  CSV cell prefix (`=cmd|'/c calc'!A1` for Formula injection). Then check
  the gallery / preview / download endpoint for unescaped echo.
- Second-order injection: submit payload, then trigger admin/staff workflow
  that re-renders it (admin moderation queue, audit log, exported PDF).
  Stored XSS often only fires in the elevated viewer's context.

## How to explore recursively (anti-script discipline)

- Submit each payload, capture the network response and DOM diff. Note where
  the value is echoed (response body, list view, detail view, email).
- After each submission, browser_snapshot. New error messages, debug pages,
  500 responses, second-order renders → click those too (recursive within
  this element's reach).
- If a probe yields an anomaly (script executed, SQL error fragment, template
  evaluated, delay observed) → DIG: try the same payload class on neighbor
  fields, escalate marker (`alert(1)` → `document.cookie` exfil), test
  whether the payload persists across sessions / users.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" hidden fields without at least 1 payload —
  hidden fields are the classic blind-spot for injection filters.

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
  "run_id": "<element-slug>-lens-input-injection-<role>-<depth>",
  "lens": "lens-input-injection",
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
    "worker_prompt_version": "lens-input-injection-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-input-injection",
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
