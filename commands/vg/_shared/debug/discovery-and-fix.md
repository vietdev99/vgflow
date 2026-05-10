<!-- v2.75.0 T6-T8 extraction — verbatim step blocks from commands/vg/debug.md -->
<!-- Group: discovery-and-fix | Steps: 1_discovery, 2_hypothesize_and_fix -->

<process>

<step name="1_discovery">
## Step 1: Discovery (path picked from classification)

```bash
mkdir -p "${DEBUG_DIR}/discovery"
```

Branch on `$BUG_TYPE`:

### static → code grep + read
```bash
# Extract keywords from description
KEYWORDS=$(echo "$BUG_DESC" | grep -oE '[a-zA-Z][a-zA-Z0-9_-]{3,}' | sort -u | head -10)
for kw in $KEYWORDS; do
  grep -rn "$kw" apps/ packages/ --include="*.ts" --include="*.tsx" 2>/dev/null | head -5 \
    >> "${DEBUG_DIR}/discovery/grep-results.txt"
done
```

### runtime_ui → browser MCP via vg-debug-ui-discovery subagent

Detect MCP availability + extract suspected route from bug description:

```bash
# MCP detection
if [ -f "${HOME}/.claude/playwright-locks/playwright-lock.sh" ]; then
  MCP_AVAILABLE=true
else
  MCP_AVAILABLE=false
fi

# Heuristic: extract URL path from bug description, default "unknown"
SUSPECTED_ROUTE=$(echo "$BUG_DESC" | grep -oE '/[a-zA-Z0-9_/-]+' | head -1)
[ -z "$SUSPECTED_ROUTE" ] && SUSPECTED_ROUTE="unknown"

# Read base URL from config (sandbox env preferred)
BASE_URL=$(python3 scripts/lib/vg-config-extract.py "env.sandbox.base_url" 2>/dev/null || echo "http://localhost:3000")
```

#### Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery spawning "route=$SUSPECTED_ROUTE mcp=$MCP_AVAILABLE"
```

#### Spawn

AI: invoke
`Agent(subagent_type="vg-debug-ui-discovery", prompt={bug_description, suspected_route, debug_id, mcp_available, base_url})`.
Subagent returns markdown findings block on last stdout. Capture into `FINDINGS_MD`.

#### Post-spawn narrate

```bash
if [ -n "$FINDINGS_MD" ]; then
  bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery returned "route=$SUSPECTED_ROUTE"
else
  bash scripts/vg-narrate-spawn.sh vg-debug-ui-discovery failed "no markdown findings block returned"
fi
```

#### Append findings to DEBUG-LOG.md

```bash
echo "$FINDINGS_MD" >> "${DEBUG_DIR}/DEBUG-LOG.md"
```

If subagent fell back (rule 5 — MCP unavailable), the findings block
itself contains the fallback note. Orchestrator may then auto-route to
`/vg:amend ${PHASE_NUMBER}` if `--no-amend-trigger` is NOT set (per
existing Step 0 spec_gap routing pattern).

See `.claude/agents/vg-debug-ui-discovery.md` for the full subagent
contract (workflow STEP A-D, MCP tool list, fallback paths).

### network → curl reproduce + tail logs
```bash
# Extract URL/endpoint from description
URL=$(echo "$BUG_DESC" | grep -oE 'https?://[^ ]+|/api/v[0-9]+/[^ ]+' | head -1)
if [ -n "$URL" ]; then
  curl -sv "$URL" > "${DEBUG_DIR}/discovery/curl-output.txt" 2>&1
fi
# Inspect recent server logs (project-specific path from config)
tail -100 apps/api/logs/error.log 2>/dev/null > "${DEBUG_DIR}/discovery/recent-errors.txt"
```

### infra → vg.config + env inspect
```bash
cp .claude/vg.config.md "${DEBUG_DIR}/discovery/vg.config.snapshot.md"
[ -f .env ] && grep -v '^[A-Z_]*_SECRET\|_KEY\|_PASSWORD' .env > "${DEBUG_DIR}/discovery/env-redacted.txt"
```

Write discovery summary to DEBUG-LOG.

```bash
touch "${DEBUG_DIR}/.markers/1_discovery.done"
```
</step>

<step name="2_hypothesize_and_fix">
## Step 2: Generate hypothesis + apply fix

### Subagent isolation (gsd:debug feature ported, opt-in)

If `--isolate` flag set OR discovery findings combined > 50KB (long investigation
risks burning main context), spawn `general-purpose` to do hypothesis+fix work
in isolated 200k context, return result to main. Skip if neither condition:

```bash
DISCOVERY_SIZE=$(du -sb "${DEBUG_DIR}/discovery" 2>/dev/null | awk '{print $1}')
if [ "$ISOLATE" = "true" ] || [ "${DISCOVERY_SIZE:-0}" -gt 51200 ]; then
  bash scripts/vg-narrate-spawn.sh general-purpose spawning "debug-${DEBUG_ID} hypothesize+fix"
  # Agent(subagent_type="general-purpose"):
  #   prompt: |
  #     Continue debug session ${DEBUG_ID}.
  #     Read ${DEBUG_DIR}/DEBUG-LOG.md + ${DEBUG_DIR}/discovery/* for context.
  #     Generate 3-5 ranked hypotheses, pick top, apply fix via Edit tool,
  #     commit atomic with prefix `fix(debug-${DEBUG_ID}): iter ${ITER}`,
  #     run auto-verify (typecheck/curl/snapshot per BUG_TYPE), append iteration
  #     entry to DEBUG-LOG.md. Return: { iter: N, commit: SHA, hypothesis: <text>,
  #     verify_result: pass|fail|skip }
  #     Constraints: NO destructive ops, NO --no-verify, atomic commit only.
  bash scripts/vg-narrate-spawn.sh general-purpose returned "iter ${ITER} fix applied"
  # Skip the inline path below
else
  # Inline path (default — short investigations, fast main-context loop)
fi
```

### Inline hypothesize + fix (default)

Based on discovery findings, generate **3-5 ranked hypotheses** for root cause. Pick top hypothesis, apply fix.

```
Iteration N:
  Hypothesis: <root cause>
  Evidence: <discovery findings supporting it>
  Fix: <files to edit + change description>
```

Apply fix using Edit tool. Commit atomic:
```bash
git add <changed files>
git commit -m "fix(debug-${DEBUG_ID}): iteration ${ITER} — <one-line fix description>

Hypothesis: <root cause>
Bug: ${BUG_DESC:0:80}
Debug-Session: ${DEBUG_ID}"
```

Append iteration entry to DEBUG-LOG.md:
```markdown
### Iteration ${ITER} — $(date -u +%FT%TZ)
**Hypothesis:** ...
**Files changed:** ...
**Commit:** <sha>
```

Emit fix_attempted event:
```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.fix_attempted \
  --payload "{\"debug_id\":\"${DEBUG_ID}\",\"iteration\":${ITER},\"commit\":\"${SHA}\"}" \
  --step debug.2_hypothesize_and_fix --actor orchestrator --outcome INFO

touch "${DEBUG_DIR}/.markers/2_hypothesize_and_fix.done"
```

**Auto-verify if possible:**
- static fix → run typecheck on file: `tsc --noEmit <file>`
- network fix → re-curl the endpoint
- ui fix → if MCP up, re-snapshot via Haiku
- infra fix → re-run health check

Document auto-verify result in DEBUG-LOG.
</step>

</process>
