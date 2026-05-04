# Transition Kit — Static SAST (Code-Only)

**Pattern:** static analysis without running the app. For backend-only / CLI / library / data-pipeline phases that have no UI runtime, but still need bug-finding rigor.

This kit applies when:
- Phase profile is `web-backend-only`, `cli-tool`, `library`, or `data-pipeline`
- No live URL available (CI, sandboxed env)
- Resource declares `kit: static-sast` in CRUD-SURFACES.md (rare; usually backend-only blanket)

Inspired by Strix's static triage layer (semgrep + tree-sitter + ast-grep). VG ships a thin wrapper that prefers `semgrep` if available, falls back to grep patterns if not.

---

## Worker invocation contract

You receive:
- **Code root** — phase directory or scope (e.g. `apps/api/src`)
- **Run ID** + output path
- **Bug class focus** — one of: `injection`, `broken-auth`, `idor`, `secrets`, `unsafe-deserialize`, `mass-assignment`, `path-traversal`, `crypto-weak`. Manager passes ONE focus per spawn for token efficiency.
- **SAST output** — pre-computed by `scripts/static-sast-runner.py` (semgrep or fallback) — list of candidate findings with file:line + match snippet

You DO NOT have browser access (no Playwright). Tools available: `Read`, `Grep`, `Glob`. Worker is purely analytical.

---

## Workflow per bug class

### Step 1 — Triage SAST candidates

Read the SAST candidate list. For each candidate:
- Read the file context (±20 lines around match)
- Decide: `confirmed_bug` | `false_positive` | `needs_human_review`

Confirmation requires:
- The match is reachable (not dead code, not test fixture)
- The pattern produces actual security/correctness issue (not just "looks like SQL string concatenation in a tool that escapes properly")

### Step 2 — Trace usage

For each `confirmed_bug` or `needs_human_review`:
- Grep for callers of the function/route/symbol containing the bug
- Trace at least 1 call chain back to a public entry point (request handler, CLI command, library export)
- Document the chain in finding `data_flow` field

### Step 3 — Severity assessment

Bug class → default severity:
| Class | Default severity |
|---|---|
| injection (SQLi/NoSQLi/cmd) | critical |
| secrets (hardcoded keys/tokens) | critical |
| broken-auth (missing role check on mutation) | high |
| idor (missing object-level authz) | high |
| unsafe-deserialize | high |
| mass-assignment | medium |
| path-traversal | high |
| crypto-weak (MD5, SHA1 for auth) | medium |

Adjust based on reachability:
- Reachable from public entry → keep severity
- Internal-only → downgrade 1 tier
- Test code only → discard (false_positive)

### Step 4 — Emit findings

For each `confirmed_bug`:
- Generate dedupe_key: `{bug_class}-{file}-{line}-{symbol}`
- Fill schema fields (no PoC payload — static analysis)
- `confidence` is medium by default (static can have false positives), high only if pattern is unambiguous (e.g. literal string concat into raw SQL with user input)
- `poc_script_code` may be empty; provide `data_flow` instead

---

## Findings — additional fields for static SAST

```json
{
  ...
  "data_flow": [
    "user input enters at apps/api/src/routes/login.ts:42 (req.body.username)",
    "passed to db.query() at apps/api/src/services/auth.ts:18",
    "concatenated into SQL string at apps/api/src/services/auth.ts:24 — INJECTION POINT"
  ],
  "code_locations": [
    {"path": "apps/api/src/services/auth.ts", "line": 24, "snippet": "..."}
  ],
  "confidence_reason": "Literal string concat with req.body — no parameterization"
}
```

---

## Severity matrix (kit-level summary)

Same as crud-roundtrip table, plus:
| Finding | Severity | Why |
|---|---|---|
| Hardcoded API keys / secrets in code | critical | exposure |
| SQL/NoSQL/Cmd injection point | critical | exploitation chain |
| Auth check missing on mutation route | high | privilege/authz |
| IDOR — missing object-level scope check | high | tenancy/authz |
| Unsafe deserialization (`pickle.loads`, `unserialize`, `yaml.load`) | high | RCE |
| Path traversal (uncleaned filenames in fs ops) | high | data exposure |
| Weak crypto (MD5, SHA1, ECB) for auth/integrity | medium | crypto |

---

## Output

Write to `${OUTPUT_PATH}` per `run-artifact-template.json` with `kit: "static-sast"`. `coverage` reflects: (attempted = SAST candidates triaged, passed = false_positives + confirmed_no_issue, failed = confirmed_bugs, blocked = needs_human_review, skipped = dead-code).
