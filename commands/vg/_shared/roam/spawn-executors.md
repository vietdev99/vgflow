# roam spawn-executors (STEP 4)

<HARD-GATE>
`3_spawn_executors` is gated by `0a-confirmed.marker` from config-gate.
Single canonical mark-step emit lives at the BOTTOM of this ref — every
branch (self/spawn/manual/aggregate-only-skip) MUST fall through to it.
Do NOT add per-branch `mark_step`/`mark-step roam` calls; that re-introduces
the duplicate-marker drift the round-2 review caught.
</HARD-GATE>

**Marker:** `3_spawn_executors`

Run executors per `$ROAM_MODE`:

- **Branch A — `self`:** current Claude session executes via MCP Playwright (no subprocess).
- **Branch B — `spawn`:** subprocess each CLI per brief, parallel-bounded (cap 5 concurrent), capture stdout JSONL.
- **Branch C — `manual`:** generate `PASTE-PROMPT.md` per model dir + display the paste prompt to user. User runs in their preferred CLI (Claude Code, Codex, Cursor, web ChatGPT), drops JSONL in the model dir, then signals continue.

**CWD contract** for executors (all branches): `${PHASE_DIR}/roam/${MODEL}/`
so all artifacts land beside the brief.

**Narration:** for spawn / self branches that invoke sub-agents or sub-processes,
emit `bash scripts/vg-narrate-spawn.sh <name> spawning [...]` before AND
`bash scripts/vg-narrate-spawn.sh <name> returned [...]` after. UX courtesy
per harness convention — no hook enforces this but operator visibility wins
over 1 saved bash call.

---

## Resume guard + cost estimator

```bash
vg-orchestrator step-active 3_spawn_executors

# Resume guard: aggregate-only mode skips step 3 entirely;
# resume mode triggers per-brief skip in spawn loop (observe-X.jsonl
# with ≥1 event = brief already done).
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  EXISTING_OBSERVE=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
  echo "▸ aggregate-only mode — skipping step 3. Found ${EXISTING_OBSERVE} observe-*.jsonl ready for aggregate."
  if [ "$EXISTING_OBSERVE" -eq 0 ]; then
    echo "  ⚠ No observe-*.jsonl found in ${ROAM_MODEL_DIRS[*]}. Did you drop manual-mode JSONL files there?"
  fi
  # NOTE: marker emit deferred to single bottom-of-ref site (see B4 fix —
  # prior shape double-marked when aggregate-only AND fall-through to bottom).
else  # not aggregate-only — run executors

# Pre-spawn cost estimator (spawn mode only)
EST_USD=$(${PYTHON_BIN:-python3} -c "
brief_count = ${BRIEF_COUNT:-0}
print(f'{brief_count * 0.08:.2f}')
")
SOFT_CAP=${VG_MAX_COST_USD:-10}
if [[ "$ARGUMENTS" =~ --max-cost-usd=([0-9.]+) ]]; then SOFT_CAP="${BASH_REMATCH[1]}"; fi
```

## Branch A — `$ROAM_MODE=self`

Current Claude session is the executor via MCP Playwright. No subprocess,
no Chromium permission issue, login works because the current model is
authed via the MCP servers. Sequential per-brief.

```bash
if [ "$ROAM_MODE" = "self" ]; then
  echo "▸ Self mode — current Claude session executes ${BRIEF_COUNT} brief(s) via MCP Playwright"
  echo ""
  echo "AI INSTRUCTIONS (verbatim — follow exactly):"
  echo "  1. For each INSTRUCTION-*.md in ${ROAM_MODEL_DIRS[*]} (lexical order):"
  echo "     a. Skip if observe-{surface}-{lens}.jsonl already exists with ≥1 line."
  echo "     b. Read the brief's Pre-flight section. Login FIRST via mcp__playwright1__browser_navigate"
  echo "        to login URL, mcp__playwright1__browser_fill_form with creds, submit, wait."
  echo "     c. Emit login confirmation event (JSON, single line) into observe file."
  echo "     d. Run lens protocol steps verbatim using mcp__playwright[1-5]__browser_* tools."
  echo "     e. Emit one JSON line per step. Each line MUST be valid JSON (no markdown)."
  echo "     f. Final event: {\"surface\":\"S##\",\"step\":\"complete\",\"total_events\":N}"
  echo "  2. After all briefs done, fall through to step 4 aggregate."
  echo ""
  echo "  Bound: ~3-5 min per brief × 19 briefs / parallel cap 1 (Playwright lock) = ~60-90 min."
  echo "  Per-brief skip handled by AI checking observe-*.jsonl existence before login."

  # Sanity ping: verify Playwright MCP responds
  if ! grep -q 'mcp__playwright' .claude/settings.json .claude/settings.local.json 2>/dev/null; then
    echo "  ⚠ Could not detect Playwright MCP in settings.json — AI may need to fall back to manual."
  fi
fi
```

## Branch B — `$ROAM_MODE=spawn`

Subprocess each CLI per brief. Parallel cap 5 (Playwright lock). Cost
estimator + soft cap warning before spawn.

```bash
if [ "$ROAM_MODE" = "spawn" ]; then
  echo "▸ Spawn mode — estimated cost: \$${EST_USD} (soft cap: \$${SOFT_CAP})"
  if (( $(echo "$EST_USD > $SOFT_CAP" | bc -l 2>/dev/null) )); then
    [[ ! "$ARGUMENTS" =~ --non-interactive ]] && echo "⚠ Cost > soft cap — confirm via AskUserQuestion before proceeding."
  fi

  # Resolve CLI command per model
  declare -A CLI_CMD_FOR_MODEL
  CLI_CMD_FOR_MODEL[codex]='cat "{brief}" | codex exec --full-auto'
  CLI_CMD_FOR_MODEL[gemini]='cat "{brief}" | gemini -m gemini-2.5-pro -p "follow brief verbatim, output JSONL only" --yolo'

  declare -a PIDS
  for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
    MODEL_NAME=$(basename "$MODEL_DIR")
    CLI_TEMPLATE="${CLI_CMD_FOR_MODEL[$MODEL_NAME]}"

    # NARRATION: spawning sub-process executor (UX courtesy).
    bash scripts/vg-narrate-spawn.sh "${MODEL_NAME}-executor" spawning "spawning $(ls "$MODEL_DIR"/INSTRUCTION-*.md 2>/dev/null | wc -l | tr -d ' ') brief(s)" 2>/dev/null || true

    for brief in "$MODEL_DIR"/INSTRUCTION-*.md; do
      [ -f "$brief" ] || continue
      surface_lens=$(basename "$brief" .md | sed 's/^INSTRUCTION-//')
      out="${MODEL_DIR}/observe-${surface_lens}.jsonl"
      err="${MODEL_DIR}/observe-${surface_lens}.err"

      # Per-brief resume skip: if observe file exists + has any non-empty
      # line, skip this brief. Don't validate JSON here — any content means
      # the brief was attempted; commander will catch malformed JSON in
      # step 4 aggregate.
      if [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [ -s "$out" ] && [[ ! "$ARGUMENTS" =~ --refresh-spawn ]]; then
        EVENT_COUNT=$(grep -c . "$out" 2>/dev/null | head -1)
        EVENT_COUNT=${EVENT_COUNT:-0}
        if [ "$EVENT_COUNT" -gt 0 ]; then
          echo "  ↷ skip ${surface_lens} (${EVENT_COUNT} lines already)"
          continue
        fi
      fi

      RENDERED=$(echo "$CLI_TEMPLATE" | sed "s|{brief}|${brief}|g")

      (
        cd "$MODEL_DIR"
        timeout 600 bash -c "$RENDERED" > "$out" 2>"$err"
        echo "exit_code=$?" >> "$err"
      ) &
      PIDS+=($!)

      # Throttle: max 5 parallel (Playwright lock cap)
      if [ ${#PIDS[@]} -ge 5 ]; then
        wait "${PIDS[0]}"
        PIDS=("${PIDS[@]:1}")
      fi
    done

    bash scripts/vg-narrate-spawn.sh "${MODEL_NAME}-executor" returned "all briefs dispatched" 2>/dev/null || true
  done
  [ ${#PIDS[@]} -gt 0 ] && wait "${PIDS[@]}"
  echo "✓ All spawn executors completed"
fi
```

## Branch C — `$ROAM_MODE=manual`

Generate `PASTE-PROMPT.md` per model dir. User pastes into their CLI, drops
JSONL into `${MODEL_DIR}/observe-*.jsonl`, signals continue.

```bash
if [ "$ROAM_MODE" = "manual" ]; then
  echo "▸ Manual mode — generating PASTE-PROMPT.md per model dir"

  for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
    MODEL_NAME=$(basename "$MODEL_DIR")
    PASTE="${MODEL_DIR}/PASTE-PROMPT.md"
    BRIEF_LIST=$(ls "$MODEL_DIR"/INSTRUCTION-*.md 2>/dev/null | xargs -n1 basename)
    BRIEF_COUNT_MODEL=$(echo "$BRIEF_LIST" | wc -l | tr -d ' ')
    ABS_MODEL_DIR=$(cd "$MODEL_DIR" && pwd)

    cat > "$PASTE" <<EOF
# PASTE PROMPT — /vg:roam executor (model: ${MODEL_NAME}, env: ${ROAM_ENV})

Copy the block below + paste into your CLI of choice (Claude Code, Codex,
Cursor, web ChatGPT). The CLI must have Playwright MCP available.

\`\`\`
You are running roam executor for phase ${PHASE_NUMBER} on env=${ROAM_ENV}.
Working directory (cwd): ${ABS_MODEL_DIR}

There are ${BRIEF_COUNT_MODEL} INSTRUCTION-*.md files in cwd. Process them one
by one in lexical order. For each:

1. Read the file (it has full lens protocol + URL + creds inlined).
2. Follow steps verbatim using Playwright MCP (browser_navigate, browser_fill_form,
   browser_click, browser_snapshot, browser_network_requests, browser_console_messages).
3. Login FIRST per the brief's "Pre-flight" section before running protocol steps.
4. Write JSONL events ONE PER LINE to: observe-<surface>-<lens>.jsonl in cwd.
   The filename must match the INSTRUCTION-<surface>-<lens>.md basename
   (replace INSTRUCTION- prefix with observe-, .md → .jsonl).
5. Each line MUST be valid JSON. NO markdown. NO commentary outside JSON.
6. Do NOT redact PII (commander redacts).
7. After each brief, print a single line to STDERR: "DONE <surface>-<lens> events=N"
8. When all ${BRIEF_COUNT_MODEL} briefs done, print "ALL DONE" to STDERR.

Files (in lexical order):
${BRIEF_LIST}

START NOW. Read first INSTRUCTION file, login, run protocol, emit JSONL.
\`\`\`

After ALL briefs complete, the JSONL files in this dir get aggregated by
\`/vg:roam ${PHASE_NUMBER} --resume-aggregate\` (or by re-invoking roam — it'll
detect existing observe-*.jsonl and skip step 3 for that model).
EOF

    echo ""
    echo "━━━ PASTE PROMPT for model=${MODEL_NAME} ━━━"
    echo "  File: ${PASTE}"
    echo "  Briefs: ${BRIEF_COUNT_MODEL} INSTRUCTION-*.md in ${ABS_MODEL_DIR}"
    echo ""
    echo "  Copy from line below, paste into your CLI:"
    echo ""
    sed -n '/^```$/,/^```$/p' "$PASTE" | grep -v '^```$'
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  done

  # Manual mode resume awareness:
  # If $ROAM_RESUME_MODE=resume AND PASTE-PROMPT.md already exists in all model dirs,
  # AND some observe-*.jsonl files have been dropped, prefer pointing user to
  # /vg:roam --aggregate-only instead of regenerating paste prompts.
  if [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ]; then
    EXIST_PASTE=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "PASTE-PROMPT.md" 2>/dev/null | wc -l | tr -d ' ')
    EXIST_OBS=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$EXIST_PASTE" -gt 0 ] && [ "$EXIST_OBS" -gt 0 ]; then
      echo ""
      echo "▸ Manual mode resume — found ${EXIST_PASTE} PASTE-PROMPT.md + ${EXIST_OBS} observe-*.jsonl already."
      echo "  If executor runs are done, re-invoke: /vg:roam ${PHASE_NUMBER} --aggregate-only"
      echo "  If still pasting/running, leave them — re-run later."
    fi
  fi

  # Pause: ask user if all manual runs finished + JSONL ready in dirs
  if [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
    echo ""
    echo "→ When all CLI runs finished, re-invoke /vg:roam ${PHASE_NUMBER} --aggregate-only"
    echo "  (or set VG_ROAM_RESUME=1 + signal continue to this session)"
    echo ""
    # AI: invoke AskUserQuestion "Manual roam runs complete? (yes / abort)"
    # If abort → exit 1
    # If yes → fall through to step 4 aggregate
  fi
fi  # end if manual

fi  # end aggregate-only guard

# Single idempotent marker emit — fires on EVERY path (self/spawn/manual or
# aggregate-only-skip). Round-2 B4 fix: prior shape emitted inside the
# aggregate-only branch AND again at the bottom unconditionally → double-mark.
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "3_spawn_executors" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_spawn_executors.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 3_spawn_executors 2>/dev/null || true
```

**Recursion (commander loop):** scan emitted `observe-*.jsonl` for
`spawn-child` events. For each, compose new brief + spawn/manual-paste
executor. Bound: max recursion depth 3, max children per parent 5.
