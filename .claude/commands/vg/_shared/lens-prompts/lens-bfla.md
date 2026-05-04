---
name: lens-bfla
description: Broken Function-Level Authorization — admin/staff/internal endpoint access from non-admin roles via direct API call, verb drift, and action-field bypass
bug_class: authz
applies_to_element_classes:
  - mutation_button
  - row_action
  - bulk_action
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/broken_function_level_authorization.md
severity_default: warn
estimated_action_budget: 30
output_schema_version: 3

# Task 26 / Task 36a additions:
recommended_worker_tier: sonnet
worker_complexity_score: 3
fallback_on_inconclusive: opus
min_actions_floor: 8
min_evidence_steps: 6
required_probe_kinds: [admin_endpoint_from_user, verb_drift, action_field_bypass]
---

# Lens: BFLA (Broken Function-Level Authorization)

## Threat model

BFLA is **action-level** authorization failure: a non-admin caller invokes a
function (endpoint, mutation, admin tool) the role matrix does not entitle
them to. It typically slips in when admin-only routes are protected by a
client-side route guard (no API middleware), when a role check is missing on
a newer or alternate endpoint, when middleware covers `GET` but not
`POST/PUT/DELETE/PATCH` on the same path, or when authorization branches on
a body field (`{action: "approve"}`) that anyone can supply. This lens is
distinct from `lens-authz-negative` (which probes generic credential
degradation across all clickables) — here the focus is specifically on
**vertical privilege**: surfaces flagged or behaving as admin/staff/
internal, and whether the lower-privilege `${ROLE}` can reach them. White-
box VG workers see the role matrix, the captured admin request shape, and
have a non-admin token in `${TOKEN_REF}`, so they can replay admin actions
deterministically and watch the boundary.

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
{"lens": "lens-bfla", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find broken function-level authorization affecting `${ELEMENT_DESCRIPTION}`
and any sub-elements you discover during exploration. Identify the
admin-flavored functions reachable from this element (URL contains
`/admin/`, `/staff/`, `/_internal/`, `/manage/`, the resource is documented
admin-only, or the button label is approve/void/refund/impersonate/grant)
and check whether `${ROLE}` (assumed lower-privilege than admin) can invoke
them. You are a security researcher, not a test runner. Click anything that
looks promising, follow workflows, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and identify candidate admin endpoints.
Not a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Inspect the DOM and the network
   tab for endpoints that look admin-flavored (path tokens, response shape,
   button copy). Note the methods and bodies of those endpoints — this is
   the candidate set you will hit directly via API call below.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Identify admin-tagged endpoints (URL contains `/admin/`, `/staff/`,
  `/_internal/`, `/manage/`, OR the resource is flagged admin-only in the
  role matrix, OR the button copy is approve/void/refund/impersonate/grant).
- For each candidate endpoint, replay the request as `${ROLE}` (non-admin)
  via direct API call — bypassing the UI route guard. The correct response
  is 403; a 200 with state change is broken function-level authz.
- Verb drift: if `GET /admin/users` returns 403, try `POST`, `PUT`,
  `PATCH`, `DELETE` on the same path; also try `X-HTTP-Method-Override:
  DELETE` on a `GET` and `?_method=DELETE`. Middleware sometimes guards only
  the documented method.
- Action-field bypass: when an endpoint authorizes by a body field
  (`{action: "approve"}`, `{role: "ADMIN"}`, `{op: "promote"}`), submit it
  as `${ROLE}` and observe whether the server consults the role matrix or
  trusts the field.
- Role-hierarchy escalation: if the system has `super-admin > admin > user`
  (or similar), test each tier — a `user` token reaching `admin`-only
  endpoints, an `admin` token reaching `super-admin`-only endpoints. Each
  rung is a separate finding.
- Transport / encoding drift: same admin action via REST vs GraphQL vs
  gRPC vs WebSocket; same JSON body re-sent as `application/x-www-form-
  urlencoded` or `multipart/form-data`. The most permissive parser often
  bypasses the strictest middleware.

## How to explore recursively (anti-script discipline)

- Click the element, capture network response baseline. Note every endpoint
  the element touches and any embedded admin tokens in URL/body.
- After each action, browser_snapshot. New buttons / forms / sub-views /
  modals → click those too (recursive within this element's reach), and
  apply the role-degraded direct-API replay to each new admin-flavored
  endpoint surfaced.
- If a probe yields an anomaly (non-admin role accepted, verb drift
  succeeds, action-field bypass works) → DIG: try the same probe on
  neighboring admin endpoints in the same view, try the inverse role pair
  (admin reaching super-admin), check whether GraphQL exposes the same
  mutation under a different resolver name.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" sub-elements without at least 1 click —
  coverage beats narrow-focus within budget.

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
  "run_id": "<element-slug>-lens-bfla-<role>-<depth>",
  "lens": "lens-bfla",
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
    "worker_prompt_version": "lens-bfla-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-bfla",
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
