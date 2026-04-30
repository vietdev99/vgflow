---
name: lens-business-logic
description: Business-logic flaws — state-machine bypass, currency rounding, quota slicing, workflow shortcuts, negative-amount tricks
bug_class: bizlogic
applies_to_element_classes:
  - mutation_button
  - form_trigger
  - payment_or_workflow
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/business_logic.md
severity_default: warn
estimated_action_budget: 40
output_schema_version: 3
---

# Lens: Business Logic

## Threat model

Business-logic bugs are the class scanners can never find: rule violations
that look like valid requests at the HTTP layer because every header, token,
and field is correctly formed — only the *semantic* invariant is broken.
Common patterns: state-machine bypass (jump from `pending` directly to
`completed`, skipping the `approved` state and the manager-approval gate);
currency / quantity rounding (`1.005` rounds to `1.00` on debit but `1.01`
on credit, attacker pockets the difference cumulatively); negative-amount
tricks (a refund of `-$100` becomes a deposit; a transfer of `-1` items
moves stock backward into the attacker); quota slicing (per-day limit is
$1000, but no aggregate limit on N×$999 transactions submitted across days
or in parallel); workflow shortcut (user clicks "approve" on their own
submission by directly invoking the API endpoint despite UI hiding the
button); coupon stacking ("one coupon per cart" enforced client-side only);
sequence dependency violation (call step 5 of a 5-step KYC flow and skip
identity proofing). White-box VG workers know the resource's intended
state machine, the captured authorized request, and can re-issue the
mutation with mutated values to test the semantic guard.

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
{"lens": "lens-business-logic", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find business-logic flaws affecting `${ELEMENT_DESCRIPTION}` and any
sub-workflows you discover during exploration. Identify the resource's
state machine (what states exist, what transitions are legal, who is
allowed to fire each transition) and the value invariants (price = qty ×
unit_price, balance ≥ 0, refund ≤ original_charge). Probe the boundaries
of each. You are a security researcher, not a test runner. Click anything
that looks promising, follow the workflow, dig into anomalies. Adapt to
what you observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and infer the workflow. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Walk the workflow once with
   benign values. Note: states observed (`draft → pending → approved →
   completed`), value fields (amount, quantity, currency, dates),
   transitions and the role gate on each (manager-approval required at X).
   This is the spec you will probe against.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- State-machine skip: instead of `draft → pending → approved → completed`,
  fire the API call that triggers the final transition (`POST
  /workflow/<id>/complete`) directly from `draft`. If accepted, state
  guards are missing.
- Self-approval: if the workflow requires a different role to approve,
  invoke the approve endpoint while authenticated as the submitter.
- Negative / zero amount: submit `amount: -100`, `qty: -1`, `discount:
  150` (>100%), `price: 0` for a normally-paid item. Negatives often
  bypass `amount > 0` gates because comparison is `amount < limit`.
- Currency / decimal rounding: submit amounts that exploit IEEE-754 or
  rounding mode — `1.005` rounded half-even gives `1.00`, half-up gives
  `1.01`; `0.1 + 0.2 != 0.3`. Repeat trades that lose 0.005 each but
  credit 0.01 each.
- Quota slicing: if a daily limit is $1000, submit `1000 / 999.99 = 1`
  small extra; for "1 per user" promo, fire 100 in parallel before the
  flag flips.
- Currency / unit confusion: submit `amount: 100` with `currency: "JPY"`
  when the resource expects `USD` — if the server interprets numerically
  the same, $100 = ¥100 ≈ $0.65.
- Date / time manipulation: submit `valid_from: <future>`,
  `subscription_until: 2099`, `birthdate: <yesterday>` for an
  age-restricted action. Server-side time should be authoritative.
- Coupon / referral stacking: apply the same coupon twice with different
  casing (`SAVE10` + `save10`); apply two single-use coupons in the same
  order; self-refer (signup with own referral code).
- Direct-API workflow shortcut: if the UI hides "skip identity check" but
  the API exposes `/kyc/<id>/skip`, invoke it directly. Same for "manager
  override" buttons that may exist on the backend without a UI.

## How to explore recursively (anti-script discipline)

- Submit each manipulated request, capture response and re-read the
  resource state. Compare against the spec inferred during reconnaissance.
- After each probe, browser_snapshot. New transition buttons / approval
  steps / payment confirms → click those too (recursive within this
  element's reach), and probe the same value/state guards on each.
- If a probe yields an anomaly (state skip, negative honored, rounding
  exploitable) → DIG: chain probes (state-skip + self-approve), test the
  same flaw with peer credentials, observe whether the audit log records
  the bypass or normalizes it.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" workflow steps without at least 1 boundary
  probe — the most-clicked normal path is often the most-trusted code.

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
  "run_id": "<element-slug>-lens-business-logic-<role>-<depth>",
  "lens": "lens-business-logic",
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
    "worker_prompt_version": "lens-business-logic-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-business-logic",
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
