---
name: vg:debug
description: Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)
argument-hint: '"<bug description>" [--phase=<N>] [--no-amend-trigger]'
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Task
mutates_repo: true
runtime_contract:
  must_write:
    - .vg/debug/{debug_id}/DEBUG-LOG.md
  must_touch_markers:
    - 0_parse_and_classify
    - 1_discovery
    - 2_hypothesize_and_fix
    - 3_verify_and_loop
    - 4_complete
  must_emit_telemetry:
    - event_type: "debug.parsed"
    - event_type: "debug.classified"
    - event_type: "debug.fix_attempted"
    - event_type: "debug.user_confirmed"
    - event_type: "debug.completed"
---

<rules>
1. **Standalone session** — debug session lives in `.vg/debug/<id>/`, not phase-scoped (Q1 user choice).
2. **AskUserQuestion-driven loop** — no max iterations. Each loop end asks user: fixed / retry / more-info (Q2).
3. **Auto-classify** — AI picks discovery path (code-only / browser / network / infra / spec gap) without asking unless confidence < 80%.
4. **Spec gap → auto /vg:amend** — if classified as spec gap, auto-trigger `/vg:amend <phase>` (Q5=a).
5. **Browser MCP fallback** — if browser MCP unavailable + UI bug, write findings as amendment to phase (Q3) instead of blocking.
6. **Atomic commits per fix** — each fix attempt = 1 commit. Easy rollback if loop fails.
7. **No destructive actions** — fix code only. Don't drop tables, force-push, or delete branches.
</rules>

<objective>
Lightweight targeted bug-fix workflow. Use case: user gặp 1 bug cụ thể (ví dụ click /campaigns crash), thay vì chạy `/vg:review` (15-30 min full Haiku scan), chạy `/vg:debug "<mô tả>"` (3-5 min targeted) để:

1. Parse + classify bug từ natural language
2. Auto-pick discovery method
3. Generate hypothesis chain
4. Apply fix + commit atomic
5. Verify (reproduce)
6. AskUserQuestion loop until user confirms fixed

Output: `.vg/debug/<id>/DEBUG-LOG.md` + atomic commits. If detected spec gap → auto `/vg:amend`.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

<step name="0_parse_and_classify">
## Step 0: Parse + classify bug description

Parse `$ARGUMENTS`:
- First quoted string: bug description (required)
- Optional flags: `--phase=<N>`, `--no-amend-trigger`, `--from-error-log=<path>`, `--from-uat-feedback="<text>"`

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

### runtime_ui → browser MCP (with fallback)
- If browser MCP available: spawn small Haiku agent to navigate + snapshot the URL mentioned
- If unavailable: write findings to discovery/ as amendment + suggest manual reproduce

```bash
# Detect MCP availability
if [ -f "${HOME}/.claude/playwright-locks/playwright-lock.sh" ]; then
  MCP_AVAILABLE=true
else
  MCP_AVAILABLE=false
fi

if [ "$MCP_AVAILABLE" = "true" ]; then
  # Spawn Haiku agent (1 view only, not full review scan)
  echo "Spawning Haiku for targeted UI discovery..."
  # Agent(...) call with prompt focused on single URL + bug description
else
  echo "Browser MCP unavailable — fallback to code-only path."
  # Treat as static + write notice to DEBUG-LOG
  echo "**Note:** Browser MCP down. UI bug analyzed from code only. Re-run after MCP up if fix doesn't reproduce." \
    >> "${DEBUG_DIR}/DEBUG-LOG.md"
fi
```

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

<step name="3_verify_and_loop">
## Step 3: AskUserQuestion — fixed / retry / more-info

```
AskUserQuestion:
  header: "Debug ${DEBUG_ID} — Iteration ${ITER}"
  question: "Bug đã fix chưa? Vui lòng test trên môi trường của bạn rồi chọn:"
  options:
    - "Đã fix — exit clean"
      description: "Bug không còn xuất hiện. Commit + DEBUG-LOG ghi PASSED."
    - "Chưa fix — lặp lại quy trình với hypothesis tiếp theo"
      description: "Auto rollback HEAD commit (nếu fix sai), thử hypothesis khác trong list."
    - "Thêm thông tin"
      description: "Bạn nhập thêm context (error log, screenshot path, hoặc clarify) → AI re-classify + tiếp tục"
```

Emit user_confirmed event after answer:
```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.user_confirmed \
  --payload "{\"debug_id\":\"${DEBUG_ID}\",\"iteration\":${ITER},\"answer\":\"${USER_CHOICE}\"}" \
  --step debug.3_verify_and_loop --actor orchestrator --outcome INFO
```

### Branch on user choice

**(a) Fixed:**
- Mark DEBUG-LOG.md "**Status:** RESOLVED at iteration ${ITER}"
- Tag commit: `git tag debug-${DEBUG_ID}-resolved`
- Skip to step 4_complete

**(b) Retry:**
- AskUserQuestion: "Rollback iteration ${ITER}'s fix?" (yes auto-revert / no keep partial)
  - yes → `git revert HEAD --no-edit`
  - no → keep changes, build on top
- Demote current hypothesis (mark "rejected" in DEBUG-LOG)
- Pick next hypothesis from list
- Loop back to step 2 (hypothesize_and_fix)

**(c) More info:**
- AskUserQuestion: "Nhập thông tin thêm:" (free-form text)
- Append to DEBUG-LOG iteration block
- Re-classify if new info changes signal (e.g., user pastes status code → reclassify network)
- Loop back to step 2 with enriched context

```bash
touch "${DEBUG_DIR}/.markers/3_verify_and_loop.done"
```

### Spec gap detected mid-loop

If during fix attempts AI realizes the bug is actually **spec gap, not code bug** (e.g., grep confirms feature genuinely doesn't exist anywhere), auto-trigger `/vg:amend`:
```bash
echo "Bug reclassified: spec gap (no code path exists for requested behavior)."
echo "Auto-triggering /vg:amend ${PHASE_NUMBER}..."
SlashCommand: /vg:amend ${PHASE_NUMBER}
# Mark debug-log: SPEC_GAP_ROUTED_TO_AMEND
```

Phase detection: if `--phase=` not given, AI picks via grep PLAN.md / SPECS.md for matching keywords.
</step>

<step name="4_complete">
## Step 4: Finalize

Append final summary to DEBUG-LOG.md:

```markdown
## Final
- **Status:** RESOLVED | ESCALATED_TO_AMEND | ABANDONED
- **Iterations:** N
- **Commits:** SHA1, SHA2, ...
- **Files changed:** path1, path2, ...
- **Time:** Xm Ys
- **Lessons:** (if any patterns worth saving — flag for /vg:learn)
```

```bash
git add "${DEBUG_DIR}/DEBUG-LOG.md"
git commit -m "debug(${DEBUG_ID}): session log — ${STATUS}

Bug: ${BUG_DESC:0:80}
Iterations: ${ITER}
Resolution: ${STATUS}
Debug-Session: ${DEBUG_ID}"

# Emit completed event
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.completed \
  --payload "{\"debug_id\":\"${DEBUG_ID}\",\"status\":\"${STATUS}\",\"iterations\":${ITER}}" \
  --step debug.4_complete --actor orchestrator --outcome PASS

touch "${DEBUG_DIR}/.markers/4_complete.done"

# Mark all step markers via orchestrator
for m in 0_parse_and_classify 1_discovery 2_hypothesize_and_fix 3_verify_and_loop 4_complete; do
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step debug "$m" 2>/dev/null
done

# Run-complete
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
```

Display:
```
Debug ${DEBUG_ID} complete.
  Status: ${STATUS}
  Iterations: ${ITER}
  Files changed: ${FILES}
  Log: ${DEBUG_DIR}/DEBUG-LOG.md

Next:
  - If RESOLVED: continue normal pipeline (/vg:next or specific command)
  - If ESCALATED: review /vg:amend output + decide on scope change
  - If ABANDONED: re-run /vg:debug "<refined description>" with more context
```
</step>

</process>

<success_criteria>
- Bug description parsed + classified
- Discovery completed (matching bug type)
- At least 1 fix iteration attempted
- User confirmed status via AskUserQuestion (fixed / retry / more)
- DEBUG-LOG.md written with full trace
- 5 telemetry events emitted (parsed, classified, fix_attempted, user_confirmed, completed)
- Atomic commits per fix (rollback-safe)
- Spec gap → auto-routed to /vg:amend (if detected)
</success_criteria>
