---
name: lens-mass-assignment
description: Mass assignment / over-posting — append privileged fields (is_admin, tenant_id, role) to mutation requests and observe whether the server filters them
bug_class: injection
applies_to_element_classes:
  - form_trigger
  - mutation_button
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/mass_assignment.md
severity_default: warn
estimated_action_budget: 30
output_schema_version: 3
---

# Lens: Mass Assignment (Over-Posting)

## Threat model

When a server hydrates a domain object directly from request JSON (Rails
`update_attributes`, Django `**request.data`, Express `Object.assign(user,
req.body)`, ORMs that bind by reflection), every property the model
exposes — including ones the UI never renders — becomes attacker-writable.
A naive `PATCH /users/me` accepting `{name, email}` from the form will
silently honor `{name, email, is_admin: true, tenant_id: <other>,
created_at: <past>, role: "ADMIN", email_verified: true}` if no allowlist
exists. The bug class also covers nested over-post (`{profile:
{verified_by_admin: true}}`), array-element promotion (`{permissions:
["*"]}`), and timestamp/audit-field tampering (`createdAt`, `lastLoginIp`,
`updatedBy`). White-box VG workers know the form's intended field set from
the DOM and can append speculative privileged keys to the captured request,
then read back the resource to verify whether the server respected the
allowlist or accepted the over-post.

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
{"lens": "lens-mass-assignment", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find mass-assignment / over-posting vulnerabilities affecting
`${ELEMENT_DESCRIPTION}` and any sub-elements you discover during
exploration. The interest is whether the server filters request bodies to
an allowlist or trusts the client to only send the intended fields. You are
a security researcher, not a test runner. Click anything that looks
promising, follow the workflow, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture the canonical mutation
payload. Not a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, submit a benign change and
   capture the request body (the "intended" field set). Also capture the
   matching GET response shape so you know the full property surface of
   the resource (the "actual" field set the model exposes).

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Privilege escalation keys: append `is_admin: true`, `role: "ADMIN"`,
  `is_superuser: true`, `permissions: ["*"]`, `scopes: ["admin:*"]` to
  the captured body. Re-read the resource via GET; check whether the
  server kept the elevated value.
- Tenant / ownership tampering: append `tenant_id: "<peer-tenant-uuid>"`,
  `org_id: "<other>"`, `owner_id: "<peer-user>"`, `created_by:
  "<other-user>"`. Re-read; if the resource moved tenant/owner, the
  allowlist is broken.
- Audit-field tampering: append `created_at: "2020-01-01T00:00:00Z"`,
  `updated_at: <past>`, `email_verified: true`, `kyc_status: "approved"`,
  `last_login_ip: "1.1.1.1"`. Audit fields silently accepted breaks
  forensics and KYC trust.
- Nested / relational over-post: `{profile: {verified_by_admin: true}}`,
  `{billing: {plan: "enterprise"}}`, `{settings: {feature_flags:
  {beta_admin_tools: true}}}`. ORM hydrators often recurse into nested
  objects without re-checking the allowlist.
- Field-name casing / alias smuggle: if the API documents `isAdmin`, also
  try `is_admin`, `IsAdmin`, `ISADMIN`, `admin`, and `__proto__.is_admin`
  (prototype pollution in JS backends). Different parsers normalize
  differently.
- Read-only field overwrite: append `id: "<other-uuid>"`, `uuid:
  "<other>"`, `slug: "premium-customer"`. Some PATCH handlers re-bind the
  primary key, allowing record swap.
- Inverse direction — strip required fields: send `{is_admin: true}` only
  (omit name/email). If server still updates `is_admin` while ignoring
  the missing required fields, allowlist is whitelist-permissive instead
  of strict.

## How to explore recursively (anti-script discipline)

- Submit the over-posted body, capture the response, then immediately
  re-read the resource with GET to confirm whether the field stuck.
- After each submission, browser_snapshot. New mutation buttons / forms /
  sub-views / modals → click those too (recursive within this element's
  reach), and apply the same over-post probe to each new mutation
  endpoint surfaced.
- If a probe yields an anomaly (privileged field stuck, tenant moved,
  audit field changed) → DIG: try the same over-post on neighbor
  resources, check whether peer tokens can also exploit the same key,
  observe whether the audit log records the silent change.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" sub-forms without at least 1 over-post —
  side-panel and modal forms often share the bare hydrator.

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
  "run_id": "<element-slug>-lens-mass-assignment-<role>-<depth>",
  "lens": "lens-mass-assignment",
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
    "worker_prompt_version": "lens-mass-assignment-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-mass-assignment",
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
