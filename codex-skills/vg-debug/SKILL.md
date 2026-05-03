---
name: "vg-debug"
description: "Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)"
metadata:
  short-description: "Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-debug`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



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

<step name="3_verify_and_loop">
## Step 3: AskUserQuestion — fixed / retry / more-info / checkpoint

### Checkpoint protocol (gsd:debug feature ported)

Before asking the user, decide if this iteration needs a **CHECKPOINT** (operator
must validate manually in browser/runtime before AI continues). Auto-checkpoint
when:

- `BUG_TYPE = runtime_ui` AND auto-verify result is "skip" (MCP unavailable)
- `BUG_TYPE = network` AND auto-verify status is 5xx (server-side, can't auto-prove fix)
- AI confidence in fix < 70%

Write checkpoint marker to DEBUG-LOG and present detailed instructions:

```bash
if [ "$NEED_CHECKPOINT" = "true" ]; then
  cat >> "${DEBUG_DIR}/DEBUG-LOG.md" <<EOF

## CHECKPOINT: human-verify (iter ${ITER})
**Type:** ${BUG_TYPE}
**Fix commit:** ${SHA}
**Operator instructions:**
1. ${CHECKPOINT_REPRO_STEPS}
2. Observe: ${CHECKPOINT_EXPECTED_BEHAVIOR}
3. Resume after test: \`/vg:debug --resume=${DEBUG_ID}\`
EOF

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event debug.checkpoint \
    --payload "{\"debug_id\":\"${DEBUG_ID}\",\"iteration\":${ITER},\"checkpoint_type\":\"human-verify\"}" \
    --step debug.3_verify_and_loop --actor orchestrator --outcome INFO
fi
```

### Loop AskUserQuestion

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
    - "Pause — sẽ resume sau"
      description: "Lưu state, exit clean. Resume bằng: /vg:debug --resume=${DEBUG_ID}"
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

**(d) Pause — resume sau:**
- Append `**Status:** PAUSED at iteration ${ITER}` to DEBUG-LOG
- Emit `debug.paused` event with iter + checkpoint info
- Print: `Resume command: /vg:debug --resume=${DEBUG_ID}`
- Exit clean (run-complete with status=PAUSED, NOT RESOLVED)
- Active-session resume (Step 0a) will surface this on next no-arg invocation

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
- **Status:** RESOLVED | ESCALATED_TO_AMEND | ABANDONED | PAUSED
- **Iterations:** N
- **Commits:** SHA1, SHA2, ...
- **Files changed:** path1, path2, ...
- **Time:** Xm Ys
- **Lessons:** (if any patterns worth saving — flag for /vg:learn)
- **Resume command:** (if PAUSED) `/vg:debug --resume=${DEBUG_ID}`
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
