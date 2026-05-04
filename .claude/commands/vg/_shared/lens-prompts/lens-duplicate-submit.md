---
name: lens-duplicate-submit
description: Race conditions / duplicate-submit — TOCTOU, parallel HTTP/2 multiplexing, idempotency-key reuse, last-byte sync attacks
bug_class: bizlogic
applies_to_element_classes:
  - mutation_button
  - form_trigger
  - bulk_action
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/race_conditions.md
severity_default: warn
estimated_action_budget: 30
output_schema_version: 3

# Task 26 / Task 36a additions:
recommended_worker_tier: sonnet
worker_complexity_score: 4
fallback_on_inconclusive: opus
min_actions_floor: 8
min_evidence_steps: 6
required_probe_kinds: [parallel_http2, idempotency_reuse, last_byte_sync]
---

# Lens: Duplicate-Submit / Race Conditions

## Threat model

Most application code reads a value, branches on it, then writes back —
without holding a lock or using a compare-and-swap. Between the read and
the write, the same code path running in another request can re-read the
old value and ALSO write, causing both branches to "succeed" against a
single entitlement. The bug class spans: double-spend (a $100 balance
spent twice in parallel because both transactions saw $100 and both
debited), single-use coupon redeemed N times, idempotency-key reuse where
the server uses the key as a cache lookup but doesn't lock on it, single-
ticket purchase reserving multiple seats, signup-bonus / referral abuse,
and rate-limit bypass via parallel submit before the counter increments.
HTTP/2 multiplexing makes this trivially weaponizable: send 5+ requests in
a single TCP roundtrip, last-byte sync ensures they hit the server within
microseconds. White-box VG workers can replay the captured mutation
multiple times in parallel and observe whether the state respected
serialization (one win, others rejected) or showed the race (multiple
wins).

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
{"lens": "lens-duplicate-submit", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find race-condition / duplicate-submit vulnerabilities affecting
`${ELEMENT_DESCRIPTION}` and any sub-mutations you discover during
exploration. Identify mutations that branch on a count, a balance, a
boolean flag, or a coupon redemption — those are the candidate TOCTOU
sites. You are a security researcher, not a test runner. Click anything
that looks promising, follow the workflow, dig into anomalies. Adapt to
what you observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and capture the mutation. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, click + capture the mutation
   request and the success-state read-back (the value the server checked,
   e.g. balance, coupon redeem flag, vote count). Note any idempotency
   token / nonce / one-time key in the request.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Rapid sequential double-submit: replay the captured mutation twice
  with <100ms gap. If the server records both as success (e.g. two coupon
  redeems, balance debited twice), no per-resource lock exists.
- HTTP/2 parallel multiplexing: open one TCP connection, queue 5-10
  identical mutation requests, flush them in a single packet (last-byte
  sync — buffer all but the final byte, then flush together). Count
  successful state changes vs expected one.
- Idempotency-key reuse: if the request has `Idempotency-Key: <uuid>`,
  send 3 parallel requests with the same key. Verify whether the server
  serves a cached response for #2 and #3 (correct) or processes all
  three (broken, the key is a tag not a lock).
- Idempotency-key swap: send 3 parallel requests with DIFFERENT keys
  but identical payload. If the server treats each as a fresh
  transaction, the key is required-but-not-deduped.
- Limit-bypass parallelism: if the resource has a quota ("free trial:
  1", "vote: 1", "comment per minute: 5"), parallel-submit N requests
  before the counter increments. Count successes vs limit.
- Workflow-state race: capture two mutations that operate on the same
  resource with conflicting effects (e.g. "approve" + "reject" on a
  pending request). Submit both in parallel; observe whether the final
  state is deterministic or whichever wrote last wins (last-write-
  wins implies no state-machine guard).
- Slice-and-sum: split a privileged operation into N small requests
  whose individual amount is below threshold but whose sum exceeds it
  (transfer $100 limit → 11 × $9.99). Submit all in parallel.
- Cancel-then-confirm race: if the resource has a "confirm within X
  seconds" window, attempt confirm + cancel in parallel.

## How to explore recursively (anti-script discipline)

- Submit the parallel/duplicate burst, capture all response bodies and
  status codes. Re-read the resource (or balance, or counter) and compare
  against the expected single-mutation outcome.
- After each burst, browser_snapshot. New mutation buttons / sub-views /
  modals → click those too (recursive within this element's reach), and
  apply the parallel-submit probe to each new mutation surfaced.
- If a probe yields an anomaly (double-spend, idempotency key not
  honored, quota exceeded) → DIG: try the same race against a peer-
  tenant resource, vary the burst size to find the breaking point, check
  whether the audit log records all duplicates or just one.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" mutations like "claim reward" or "add to
  cart" without at least 1 parallel-submit probe — those are classic
  unprotected counters.

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
  "run_id": "<element-slug>-lens-duplicate-submit-<role>-<depth>",
  "lens": "lens-duplicate-submit",
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
    "worker_prompt_version": "lens-duplicate-submit-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-duplicate-submit",
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
