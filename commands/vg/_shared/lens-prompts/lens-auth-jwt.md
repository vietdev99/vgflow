---
name: lens-auth-jwt
description: JWT / token authentication weaknesses — alg confusion, alg=none, kid injection, jku/x5u tampering, claim forgery
bug_class: auth
applies_to_element_classes:
  - mutation_button
  - sub_view_link
  - row_action
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/authentication_jwt.md
severity_default: warn
estimated_action_budget: 40
output_schema_version: 3
---

# Lens: JWT / Token Authentication

## Threat model

JWTs are self-contained credentials whose trust hinges entirely on a single
signature verification at the gateway. Every degree of freedom in that
verification — the algorithm field (`alg`), the key identifier (`kid`),
the JWS header URLs (`jku`, `x5u`, `x5c`, `jwk`) — is attacker-controllable
and has historically been mis-validated. Classic failure modes: `alg: none`
accepted (no signature required); RS256→HS256 algorithm confusion (verify
HMAC using the public key as the secret); `kid` header injection (path
traversal to load `/dev/null` or a known-content file as the key); `jku` /
`x5u` referring to attacker-controlled URLs; trusting `iss` / `aud` /
`sub` claims without re-validating against the registered tenant; expired
token still accepted (clock-skew window too generous, or `exp` not
checked). Beyond signature: weak HMAC secrets brute-forceable from a
single token, fixation (same JTI/session ID after privilege change),
session not invalidated on logout. White-box VG workers hold a valid
`${TOKEN_REF}` they can decode and tamper with, and a captured request
they can replay with the forged token.

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
{"lens": "lens-auth-jwt", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find JWT / token authentication weaknesses affecting `${ELEMENT_DESCRIPTION}`
and any sub-elements you discover during exploration. Decode the token
attached to the captured baseline request, identify the `alg`, `kid`,
`iss`, `sub`, `exp` claims, then probe the gateway for whether each value
is strictly verified or trusted-as-given. You are a security researcher,
not a test runner. Click anything that looks promising, follow the
workflow, dig into anomalies. Adapt to what you observe — do not follow a
fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and decode the JWT. Not a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`, click + capture the
   authenticated request. Decode the JWT (base64url the header + payload),
   note `alg`, `kid`, `iss`, `sub`, `aud`, `exp` claims and any custom
   ones (`tenant_id`, `role`, `permissions`).

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- `alg: none` confusion: re-encode the token with header `{"alg":"none",
  "typ":"JWT"}`, drop the signature segment (still keep the trailing
  `.`). Replay; expect 401 — a 200 means the gateway accepts unsigned
  tokens.
- RS256 → HS256 confusion: if `alg` is `RS256` and you can fetch the
  server's public key (typically at `/.well-known/jwks.json` or
  `/oauth/keys`), re-sign the token using HS256 with the public-key PEM
  bytes as the HMAC secret. A successful replay confirms the gateway
  trusts the header-declared algorithm.
- `kid` injection: tamper the `kid` header to `../../../dev/null`,
  `../../../../etc/passwd`, or a path inside the app (`/etc/hostname`).
  If the gateway loads a key file by `kid`, traversal can pin to a known-
  content file (e.g. empty file → empty key → trivial signature).
- `jku` / `x5u` / `jwk` smuggle: add `jku: "https://attacker.local/
  jwks.json"` (or inline `jwk` header). Some libraries fetch the
  attacker-controlled JWKS and verify against it.
- Claim forgery: change `sub` to a peer/admin user UUID, change
  `tenant_id` to a peer tenant, change `role` to `admin`, escalate
  `permissions: ["*"]` — re-sign (or leave invalid signature). If gateway
  trusts claim before verifying signature, escalation works.
- Expired token: alter `exp` to a past timestamp; replay. Expect 401; a
  200 indicates the `exp` check is missing or skewed.
- Algorithm downgrade chain: send the same JWT to multiple endpoints
  (REST, GraphQL, internal admin) — different services in the same
  cluster sometimes use different verifiers; the most permissive one is
  exploitable.
- Session non-invalidation: trigger logout via the UI, then replay the
  pre-logout token. If still 200, sessions are not server-side
  invalidated and the JWT is effectively immortal until `exp`.

## How to explore recursively (anti-script discipline)

- Tamper the token, replay the captured request, capture status + body.
  Every variant is a separate step.
- After each replay, browser_snapshot. New mutation buttons / sub-views /
  modals → click those too (recursive within this element's reach), and
  apply the token-tamper probes to each new endpoint surfaced.
- If a probe yields an anomaly (forged claim accepted, alg=none honored,
  kid traversal works) → DIG: extend the forgery to escalate (peer
  tenant_id, admin role), check whether the audit log records the forged
  identity or the original.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" GET endpoints without at least 1 token-
  tamper probe — read endpoints often have weaker validation than writes.

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
  "run_id": "<element-slug>-lens-auth-jwt-<role>-<depth>",
  "lens": "lens-auth-jwt",
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
    "worker_prompt_version": "lens-auth-jwt-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-auth-jwt",
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
