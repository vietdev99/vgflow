# Multi-actor session primitive (Shared Reference, R7 Task 5 / G9)

Per-actor browser/auth context primitives used by
`commands/vg/_shared/review/verdict/multi-actor-workflow.md` when replaying
WORKFLOW-SPECS/<WF-NN>.md flows during review verdict.

This is the multi-actor sibling of the single-actor session pattern in
`flow-runner` skill. flow-runner's `resume_context.logged_in_as` carries one
role at a time. WORKFLOW-SPECS routinely hop across 2-N actors (user submits
→ admin reviews → manager approves) — this file documents how to drive that
hop without false positives from leaked auth state.

## Two execution shapes

The orchestrator picks one based on `vg.config.md > review.multi_actor_mode`
(default `multi-context`).

### Shape A — Multi-context (recommended)

Each actor gets its own browser context via Playwright MCP. Cookies / storage
are isolated by construction — no leakage. Faster and safer than logout-relogin.

```
mcp__playwright1__browser_navigate { url: ${BASE_URL} }
# Actor A flow ───────────────────────────────────────────
# (auth as user, submit, capture state_after = pending)
mcp__playwright1__browser_evaluate { function: "() => fetch('/api/auth/login', { method:'POST', body: JSON.stringify({...userCreds}) })" }
# ... actor A steps ...
mcp__playwright1__browser_take_screenshot { filename: "WF-001-step-1.png" }

# Actor B flow ───────────────────────────────────────────
# Open SECOND browser context for admin (do NOT logout context 1)
mcp__playwright2__browser_navigate { url: ${BASE_URL} }
mcp__playwright2__browser_evaluate { function: "() => fetch('/api/auth/login', { method:'POST', body: JSON.stringify({...adminCreds}) })" }
# ... actor B steps ...
mcp__playwright2__browser_take_screenshot { filename: "WF-001-step-2.png" }
```

Properties:
- Auth tokens never cross contexts → no false-positive cross-role visibility
- Each actor's console / network log is isolated
- Up to 5 distinct contexts (`mcp__playwright1` … `mcp__playwright5`)

When workflow has more than 5 actors → fall back to Shape B for the 6th+.

### Shape B — Single-context, sequential logout/login

One browser; explicit auth flush between actors. Cheaper on resources but
requires careful cleanup.

```
# Actor A flow ───────────────────────────────────────────
mcp__playwright1__browser_navigate { url: ${BASE_URL} }
mcp__playwright1__browser_evaluate { function: "() => fetch('/api/auth/login', { method:'POST', body: JSON.stringify(userCreds) })" }
# ... actor A steps ...

# Cleanup before role switch ─────────────────────────────
mcp__playwright1__browser_evaluate { function: "() => { localStorage.clear(); sessionStorage.clear(); }" }
mcp__playwright1__browser_navigate { url: ${BASE_URL}/api/auth/logout }
mcp__playwright1__browser_evaluate { function: "() => document.cookie.split(';').forEach(c => document.cookie = c.replace(/^ +/,'').replace(/=.*/, '=;expires='+new Date().toUTCString()+';path=/'))" }

# Actor B flow ───────────────────────────────────────────
mcp__playwright1__browser_evaluate { function: "() => fetch('/api/auth/login', { method:'POST', body: JSON.stringify(adminCreds) })" }
# ... actor B steps ...
```

When this fails (cookies survive logout, residual JWT in IndexedDB, etc.) →
upgrade to Shape A and log override-debt with `kind=multi-actor-session-leak`.

## Credential resolution

Per-actor credentials come from the same `config.credentials.${ENV}` block
that `flow-runner` consumes. WORKFLOW-SPECS schema requires every actor to
declare `cred_fixture: <FIXTURE_ENV_NAME>`. Resolution:

```bash
ROLE="${1:-user}"
FIXTURE_KEY=$(${PYTHON_BIN} -c "
import yaml
with open('${WF_FILE}', encoding='utf-8') as f:
    text = f.read()
import re
m = re.search(r'\`\`\`ya?ml\s*\n(.+?)\n\`\`\`', text, re.S)
spec = yaml.safe_load(m.group(1))
for a in spec.get('actors', []):
    if a.get('role') == '${ROLE}':
        print(a.get('cred_fixture', ''))
        break
")
USERNAME=$(vg_config_get "credentials.${ENV}.${FIXTURE_KEY}.username" "")
PASSWORD=$(vg_config_get "credentials.${ENV}.${FIXTURE_KEY}.password" "")
```

When `cred_fixture` is missing OR resolves to empty → emit
`review.multi_actor_cred_missing` event and SKIP that step (PARTIAL replay
verdict). Do NOT silently assume a default role.

## Cleanup contract

Between every `cred_switch_marker: true` step boundary:

1. Capture screenshot of post-state for the outgoing actor (evidence chain)
2. Drain pending network requests (`browser_wait_for { networkIdle: true }`)
3. Either
   a. Open new MCP context (Shape A), OR
   b. Clear all of: cookies, localStorage, sessionStorage, IndexedDB
      (Shape B). Verify by fetching a protected endpoint and confirming
      401/302 — if it still returns 200, the session leaked.

## Output contract

Every multi-actor session emits to
`${PHASE_DIR}/.runs/<WF-NN>.replay.json` per
`schemas/workflow-replay.v1.schema.json`. The orchestrator builds this via
`scripts/lib/workflow_replay.py:execute_replay()` — see
`commands/vg/_shared/review/verdict/multi-actor-workflow.md` for the
end-to-end wiring.

## Failure classification (mirrors flow-runner 4-rule classifier)

| Rule | Symptom | Action |
|---|---|---|
| 1 AUTO-FIX | wrong selector, label changed | re-grep MCP snapshot, retry step |
| 2 AUTO-ENHANCE | missing wait, race | add `browser_wait_for` + retry |
| 3 AUTO-RETRY | 5xx, network blip | retry once after 10s |
| 4 ESCALATE | wrong-role transition succeeded, cross-role state invisible | record FAILED step + blocking_failures entry, do NOT auto-fix |

Rule 4 is the load-bearing classification — that's the multi-actor bug class
this whole gate exists to catch. Never reclassify a Rule-4 finding as Rule 1
during fix loop (rationalization-guard rejects).
