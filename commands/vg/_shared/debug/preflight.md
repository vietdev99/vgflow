<!-- v2.75.0 T6-T8 extraction — verbatim step blocks from commands/vg/debug.md -->
<!-- Group: preflight | Steps: 0_parse_and_classify -->

<process>

<step name="0_parse_and_classify">
## Step 0: Parse + classify bug description

Parse `$ARGUMENTS`:
- First quoted string: bug description (required UNLESS `--resume` or empty-args resume picker triggers)
- Optional flags: `--phase=<N>`, `--no-amend-trigger`, `--from-error-log=<path>`, `--from-uat-feedback="<text>"`, `--resume=<debug-id>`, `--isolate`

### 0a — Active-session resume check (gsd:debug feature ported)

Before fresh classification, check for unresolved sessions:

```bash
# List active (= not RESOLVED/ABANDONED/SPEC_GAP_ROUTED) sessions, < 7 days old
ACTIVE_SESSIONS=$(find .vg/debug -maxdepth 2 -name "DEBUG-LOG.md" -mtime -7 2>/dev/null | while read f; do
  status=$(grep -E "^\*\*Status:\*\*" "$f" | head -1)
  if ! echo "$status" | grep -qE "RESOLVED|ABANDONED|SPEC_GAP_ROUTED"; then
    debug_id=$(basename "$(dirname "$f")")
    desc=$(grep -E "^\*\*Description:\*\*" "$f" | head -1 | sed 's/^\*\*Description:\*\* *//' | head -c 60)
    last_iter=$(grep -cE "^### Iteration " "$f" || echo 0)
    echo "${debug_id}|${desc}|${last_iter}"
  fi
done)

# Branch on flags
if [ -n "$RESUME_ID" ]; then
  # --resume=<id> explicit: load session, skip classification
  DEBUG_ID="$RESUME_ID"
  DEBUG_DIR=".vg/debug/${DEBUG_ID}"
  [ -d "$DEBUG_DIR" ] || { echo "Resume target $DEBUG_ID not found" >&2; exit 1; }
  BUG_DESC=$(grep -E "^\*\*Description:\*\*" "${DEBUG_DIR}/DEBUG-LOG.md" | head -1 | sed 's/^\*\*Description:\*\* *//')
  BUG_TYPE=$(grep -E "^\*\*Classification:\*\*" "${DEBUG_DIR}/DEBUG-LOG.md" | head -1 | sed 's/^\*\*Classification:\*\* *//' | awk '{print $1}')
  echo "▸ Resuming session ${DEBUG_ID} — ${BUG_DESC}"
  ITER=$(grep -cE "^### Iteration " "${DEBUG_DIR}/DEBUG-LOG.md" || echo 0)
  # Skip to step 2 (already classified, just continue iterating)
  RESUMED=true
elif [ -z "$BUG_DESC" ] && [ -n "$ACTIVE_SESSIONS" ]; then
  # No description + active sessions exist: offer pick
  echo "▸ Active debug sessions:"
  echo "$ACTIVE_SESSIONS" | awk -F'|' '{ printf "  %d) %s — %s (iter %s)\n", NR, $1, $2, $3 }'
  # AskUserQuestion: "Resume which session, or [N]ew?" — N starts fresh
  # If user picks number → set RESUME_ID, re-enter resume branch
  # If user picks "new" → require new description (loop AskUserQuestion for it)
fi
```

If neither resume path triggered:

Validate description non-empty. Empty → BLOCK with usage example.

```bash
# Generate debug session ID
DEBUG_ID="dbg-$(date -u +%Y%m%d-%H%M%S)-$(echo $$ | tail -c 5)"
DEBUG_DIR=".vg/debug/${DEBUG_ID}"
mkdir -p "$DEBUG_DIR"

# Register run with orchestrator
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:debug "${PHASE_NUMBER:-standalone}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed" >&2; exit 1
}

# Emit parsed event
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.parsed \
  --payload "{\"debug_id\":\"${DEBUG_ID}\",\"description\":$(printf '%s' "$BUG_DESC" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))'),\"phase\":\"${PHASE_NUMBER:-standalone}\"}" \
  --step debug.0_parse_and_classify --actor orchestrator --outcome INFO
```

**Classify bug type** (deterministic keyword + structure heuristic, no AI subagent for speed):

| Type | Detection signal | Discovery method |
|---|---|---|
| `static` | Stack trace mentions specific file/line; keywords: typo, null check, undefined, off-by-one | grep + read affected file |
| `runtime_ui` | Mentions: click, render, modal, page, layout, tab, button. Has URL path | Browser MCP (or fallback) |
| `network` | Mentions: 4xx, 5xx, status code, timeout, CORS, ERR_CONNECTION | curl + log inspect |
| `infra` | Mentions: env var, config, deploy, restart, port, daemon | vg.config.md + .env inspect |
| `spec_gap` | Mentions: "không có", "missing feature", "tính năng", "chưa có UI for X" | Read SPECS/CONTEXT/PLAN to confirm; if confirmed → auto-amend |
| `ambiguous` | Confidence < 80% | AskUserQuestion to clarify |

```bash
# Heuristic classification
BUG_DESC="${ARGUMENTS}"  # cleaned
BUG_TYPE="ambiguous"
CONFIDENCE=0

# UI signals
if echo "$BUG_DESC" | grep -qiE '(click|render|modal|tab|layout|button|form|page|/[a-z-]+|crash khi|không hiển thị)'; then
  BUG_TYPE="runtime_ui"; CONFIDENCE=85
fi
# Network signals (override UI if status code mentioned)
if echo "$BUG_DESC" | grep -qiE '\b(4[0-9]{2}|5[0-9]{2}|timeout|ERR_CONNECTION|CORS|fetch failed)\b'; then
  BUG_TYPE="network"; CONFIDENCE=90
fi
# Infra signals
if echo "$BUG_DESC" | grep -qiE '\b(env var|\.env|config|deploy|restart|port [0-9]+|pm2|daemon)\b'; then
  BUG_TYPE="infra"; CONFIDENCE=85
fi
# Static code signals (stack trace markers)
if echo "$BUG_DESC" | grep -qiE '(at .*:\d+|TypeError|ReferenceError|undefined is not|null is not)'; then
  BUG_TYPE="static"; CONFIDENCE=90
fi
# Spec gap signals
if echo "$BUG_DESC" | grep -qiE '(không có|missing feature|tính năng .* chưa|cần thêm|should support|wishful|nowhere)'; then
  BUG_TYPE="spec_gap"; CONFIDENCE=70
fi

echo "Bug classified: ${BUG_TYPE} (confidence ${CONFIDENCE}%)"
```

**If confidence < 80% → AskUserQuestion** with options matching detected types + "other".

```bash
# Emit classified event
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.classified \
  --payload "{\"debug_id\":\"${DEBUG_ID}\",\"bug_type\":\"${BUG_TYPE}\",\"confidence\":${CONFIDENCE}}" \
  --step debug.0_parse_and_classify --actor orchestrator --outcome INFO

# Write initial DEBUG-LOG
cat > "${DEBUG_DIR}/DEBUG-LOG.md" <<EOF
# Debug session ${DEBUG_ID}

**Started:** $(date -u +%FT%TZ)
**Description:** ${BUG_DESC}
**Phase:** ${PHASE_NUMBER:-standalone}
**Classification:** ${BUG_TYPE} (${CONFIDENCE}%)

## Iterations
EOF

touch "${DEBUG_DIR}/.markers/0_parse_and_classify.done" 2>/dev/null || mkdir -p "${DEBUG_DIR}/.markers" && touch "${DEBUG_DIR}/.markers/0_parse_and_classify.done"
```

**Spec gap branch:** if `BUG_TYPE=spec_gap` AND not `--no-amend-trigger`:
- Determine target phase (from `--phase=` flag, or grep PLAN.md for keywords matching bug, or AskUserQuestion)
- Write DEBUG-LOG note: "Classified as spec gap → auto-triggering /vg:amend"
- `SlashCommand: /vg:amend ${PHASE_NUMBER}` then exit cleanly
- Emit `debug.completed` with verdict=SPEC_GAP_ROUTED_TO_AMEND

</step>

</process>
