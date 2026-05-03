---
name: lens-idor
description: IDOR/BOLA — find horizontal & vertical object-level authorization failures via ID swap probes
bug_class: authz
applies_to_element_classes:
  - mutation_button
  - row_action
  - sub_view_link
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/idor.md
severity_default: warn
estimated_action_budget: 40
output_schema_version: 3
---

# Lens: IDOR (Object-Level Authorization)

## Threat model

Endpoints expose object IDs in paths, query strings, JSON bodies, JWT claims,
or GraphQL args, and use those IDs to fetch or mutate state. If the server
fails to verify the caller owns (or is authorized to act on) the referenced
object, an attacker can swap the ID — to a peer tenant's record, a sequential
neighbor, a deleted item, or an admin-only resource — and read or modify data
they should not reach. White-box VG workers, holding both `${TOKEN_REF}` and
`${PEER_TOKEN_REF}` plus live network capture, are well placed to detect IDOR:
capture an authentic ID from the baseline call, replay with a swap, observe
whether the server returns 403/404 (correct) or 200 with peer-owned content
(broken authorization).

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
{"lens": "lens-idor", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find IDOR/BOLA vulnerabilities affecting `${ELEMENT_DESCRIPTION}` and any
sub-elements you discover during exploration. Object IDs hide everywhere —
URL paths, query strings, JSON bodies, batch arrays, expansion params,
pagination cursors, export endpoints, background-job result URLs. You are a
security researcher, not a test runner. Click anything that looks promising,
follow the workflow, dig into anomalies. Adapt to what you observe — do not
follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture a baseline ID. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, click + capture baseline response;
   note all object IDs in URL/body (call your own ID `OBJ_ID_SELF`).

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Replay the captured request with `${PEER_TOKEN_REF}` (peer tenant); check
  whether status 200 returns `OBJ_ID_SELF` content — peer should get 403/404.
- Sequential ID guess: try `OBJ_ID_SELF ± 1`, `± 100`, `± 1000`; cross-check
  `ownerId` / `tenantId` fields in the response for cross-tenant leaks.
- Bulk endpoints: inject a peer-tenant ID mid-array; check whether the server
  partially processes mixed-tenant payloads instead of rejecting the batch.
- Admin-tagged objects (URL or payload contains `admin`, `staff`,
  `_internal`): attempt access as a non-admin role with `${TOKEN_REF}`.
- Expansion / projection params (`?include=`, `?expand=`, `?fields=`): IDOR
  often hides where ACL applies to the root entity but not to expanded edges.
- CSV / PDF / export endpoints (`/export`, `/download`, `/report`): swap the
  ID parameter; exports frequently bypass per-row authorization checks.
- Background jobs (`/jobs/<id>/result`, `/tasks/<id>`): IDs tend to be
  sequential — swap to peek at other tenants' job output or status.
- Pagination cursor: replay with a peer's cursor token; some implementations
  decode the cursor server-side and skip the tenant filter.

## How to explore recursively (anti-script discipline)

- Click the element, capture network response baseline. Note every ID in URL
  and body.
- After each action, browser_snapshot. New buttons / forms / sub-views /
  modals → click those too (recursive within this element's reach).
- If a probe yields an anomaly (peer data leaked, cross-owner mutation
  succeeded, admin object accessible) → DIG: try the same swap with a
  different role to map blast radius; try a write verb (PUT/PATCH/DELETE) on
  the leaked ID; check whether the audit log endpoint records your action.
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
  "run_id": "<element-slug>-lens-idor-<role>-<depth>",
  "lens": "lens-idor",
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
    "worker_prompt_version": "lens-idor-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-idor",
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
