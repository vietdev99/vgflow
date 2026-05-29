<!-- v2.75.0 T6-T8 extraction — verbatim step blocks from commands/vg/debug.md -->
<!-- Group: preflight | Steps: 0_parse_and_classify -->

<process>

<step name="0_parse_and_classify">
## Step 0: Parse + classify bug description

Parse `$ARGUMENTS`:
- First quoted string: bug description (required UNLESS `--resume` or empty-args resume picker triggers)
- Optional flags: `--phase=<N>`, `--no-amend-trigger`, `--from-error-log=<path>`, `--from-uat-feedback="<text>"`, `--resume=<debug-id>`, `--isolate`, `--race` (B115 — enable multi-hypothesis race)

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
  # B116 ranked picker: score sessions by recency × iter × symptom similarity
  echo "▸ Active debug sessions (B116 ranked):"
  "${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_session.py rank \
    --sessions-dir .vg/debug --symptom "" --top-n 5 \
    | "${PYTHON_BIN:-python3}" -c "
import json, sys
data = json.load(sys.stdin)
for i, c in enumerate(data, 1):
    dup_tag = ' [DUP]' if c['is_duplicate_of_current'] else ''
    print(f\"  {i}) {c['debug_id']} — {c['description']} (iter {c['iter_count']}, score {c['score']}){dup_tag}\")
"
  # AskUserQuestion: "Resume which session, or [N]ew?" — N starts fresh
fi

# B116 duplicate detection: if user gives description but symptom matches
# active session, recommend resume instead of new
if [ -n "$BUG_DESC" ] && [ -z "$RESUME_ID" ]; then
  DUP_ID=$("${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_session.py dup \
    --sessions-dir .vg/debug --description "$BUG_DESC" 2>/dev/null || true)
  if [ -n "$DUP_ID" ]; then
    echo "▸ B116 duplicate detected: symptom matches existing session ${DUP_ID}"
    # AskUserQuestion: "Resume ${DUP_ID} or start fresh?"
    # If user picks resume → RESUME_ID=$DUP_ID
  fi
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

**Classify bug type** (B114 v4.73.0 — token+confidence scoring via `scripts/lib/debug_classifier.py`):

| Type | Detection signal | Discovery method |
|---|---|---|
| `static` | Stack trace mentions specific file/line; keywords: typo, null check, undefined, off-by-one | grep + read affected file |
| `runtime_ui` | Mentions: click, render, modal, page, layout, tab, button. Has URL path | Browser MCP (or fallback) + sibling-route probe |
| `network` | Mentions: 4xx, 5xx, status code, timeout, CORS, ERR_CONNECTION | curl + log inspect + related-error scan |
| `infra` | Mentions: env var, config, deploy, restart, port, daemon | vg.config.md + .env inspect |
| `spec_gap` | Mentions: "không có", "missing feature", "tính năng", "chưa có UI for X" | Read SPECS/CONTEXT/PLAN to confirm; if confirmed → auto-amend |
| `ambiguous` | Confidence < 80% | AskUserQuestion to clarify |

```bash
# B114: classifier with confidence scoring + evidence trail
BUG_DESC="${ARGUMENTS}"  # cleaned
CLASSIFIER_OUT="${DEBUG_DIR}/classifier.json"

"${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_classifier.py "$BUG_DESC" \
  > "$CLASSIFIER_OUT" 2>/dev/null
CLASSIFIER_EXIT=$?

BUG_TYPE=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open('${CLASSIFIER_OUT}')); print(d['bug_type'])")
CONFIDENCE=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open('${CLASSIFIER_OUT}')); print(d['confidence'])")
NEEDS_CLARIF=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open('${CLASSIFIER_OUT}')); print(str(d.get('needs_clarification',False)).lower())")
PROBE_SIBLINGS=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open('${CLASSIFIER_OUT}')); print(str(d.get('probe_siblings_enabled',False)).lower())")

echo "Bug classified: ${BUG_TYPE} (confidence ${CONFIDENCE}%)"

# B114: surface alternates if close call
ALTS=$("${PYTHON_BIN:-python3}" -c "
import json
d=json.load(open('${CLASSIFIER_OUT}'))
alts=d.get('alternates',[])
if alts:
    print(', '.join(f\"{a['type']}({a['confidence']}%)\" for a in alts[:2]))
")
[ -n "$ALTS" ] && echo "  alternates: ${ALTS}"
```

**If `NEEDS_CLARIF == "true"` → AskUserQuestion** with options matching `bug_type` + each alternate from `classifier.json` + "other".

**B114 — Cross-symptom probe (runtime_ui + network only):**

If `PROBE_SIBLINGS == "true"`, expand discovery to sibling routes BEFORE Step 1:

```bash
SUSPECTED_ROUTE=$(echo "$BUG_DESC" | grep -oE '/[a-zA-Z0-9_/-]+' | head -1)
if [ -n "$SUSPECTED_ROUTE" ] && [ "$PROBE_SIBLINGS" = "true" ]; then
  SIBLINGS=$("${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_probe.py expand "$SUSPECTED_ROUTE" 2>/dev/null)
  echo "Sibling routes to probe: $SIBLINGS" >> "${DEBUG_DIR}/DEBUG-LOG.md"
  echo "$SIBLINGS" > "${DEBUG_DIR}/sibling_routes.json"
fi

# Graphify integration (graceful — empty if graph absent)
GRAPHIFY_NEIGHBORS=$("${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_probe.py graphify "$BUG_DESC" 2>/dev/null)
if [ -n "$GRAPHIFY_NEIGHBORS" ] && [ "$GRAPHIFY_NEIGHBORS" != "[]" ]; then
  echo "$GRAPHIFY_NEIGHBORS" > "${DEBUG_DIR}/graphify_neighbors.json"
fi
```

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
