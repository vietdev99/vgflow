# Gemini CLI — TLS / self-signed certificate troubleshooting

Issue #197 dogfood (PrintwayV3 `/vg:test-spec --regen` CrossAI sweep,
2026-05-20): Gemini CLI auth-fail blocked the codex+gemini vote with:

```
Error authenticating: _GaxiosError: request to
https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist failed,
reason: self-signed certificate in certificate chain
```

Effect: CrossAI sweep configured to vote `codex + gemini` falls to
INCONCLUSIVE verdict because gemini quorum vote never arrives.

## Root cause

Node.js (which the Gemini CLI bundles) does NOT trust corporate / VPN /
ZScaler-style middlebox certificates by default. When the host runs
behind a TLS intercepting proxy, the chain presented to Node includes
a root CA the bundled CA store doesn't recognize.

Gemini CLI docs do NOT mention this — `gcloud` has equivalent behavior
but uses Python `requests` which honors `REQUESTS_CA_BUNDLE`. Node uses
`NODE_EXTRA_CA_CERTS` instead.

## Fix

### Option 1 (recommended) — install corporate root CA into Node trust store

Export the corporate root CA PEM (ask IT / network admin) and point
Node at it via env var:

```bash
# macOS / Linux
export NODE_EXTRA_CA_CERTS=/path/to/corp-root-ca.pem

# Windows PowerShell
$env:NODE_EXTRA_CA_CERTS = "C:\path\to\corp-root-ca.pem"

# Windows cmd
set NODE_EXTRA_CA_CERTS=C:\path\to\corp-root-ca.pem
```

Then re-run `gemini auth login` (or whatever the CLI's auth entry is).

### Option 2 (testing only — INSECURE) — bypass TLS verification

DO NOT use in production. Last-resort for spike / one-off scripts:

```bash
export NODE_TLS_REJECT_UNAUTHORIZED=0
```

This globally disables certificate verification for the Node process.
Network MITM possible. Document the use as override-debt:

```bash
vg-orchestrator emit-event override.used --force --reason \
  "NODE_TLS_REJECT_UNAUTHORIZED=0 for Gemini CLI dev session — corp CA bundle pending IT delivery"
```

### Option 3 — pin via Gemini CLI config

If/when Gemini CLI adds a `--ca-bundle <path>` flag or config equivalent,
prefer that over the env-var approach (process-scoped). As of v4.68.0
no such flag documented.

## Persistence

For VGFlow harness sessions, export the variable in the parent shell
BEFORE launching Claude Code so child processes inherit:

```bash
# In ~/.bashrc or ~/.zshrc
export NODE_EXTRA_CA_CERTS="$HOME/.config/corp-ca.pem"
```

Or in Claude Code `~/.claude/settings.json` `env` block:

```json
{
  "env": {
    "NODE_EXTRA_CA_CERTS": "/Users/<you>/.config/corp-ca.pem"
  }
}
```

Settings.json env is read at Claude Code start and propagated to all
spawned hooks + tools.

## Verification

After applying:

```bash
# Should print "OK" if cert chain validates
node -e "require('https').get('https://cloudcode-pa.googleapis.com', (r) => console.log(r.statusCode === 200 || r.statusCode === 401 ? 'OK' : 'fail: ' + r.statusCode)).on('error', (e) => console.log('fail:', e.code))"
```

Then re-run the original CrossAI sweep — vote should succeed.

## Related

- Issue #197 dogfood log entry.
- VGFlow CrossAI sweep `/vg:_shared:crossai-invoke` skill — configures
  the codex + gemini vote and surfaces INCONCLUSIVE when either vote
  fails.
- B95 v4.68.0 ships this doc + `verify-fe-be-shape-coherence.py` static
  validator (advisory) for the build-gate proposal from the same issue.
