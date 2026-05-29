<!-- v2.75.0 T6-T8 extraction — verbatim step blocks from commands/vg/debug.md -->
<!-- Group: verify-and-close | Steps: 3_verify_and_loop, 4_complete -->

<process>

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

### B116 silent auto-continue check

Before triggering AskUserQuestion, check if this iteration qualifies for
silent skip (high confidence + verify passed + early iteration):

```bash
SILENT_OK=$("${PYTHON_BIN:-python3}" .claude/scripts/lib/debug_session.py silent \
  --confidence "$CONFIDENCE" \
  $([ "$VERIFY_PASSED" = "true" ] && echo "--verify-passed") \
  --iter "$ITER" 2>/dev/null)

if [ "$SILENT_OK" = "true" ]; then
  echo "▸ B116 silent-continue: confidence ${CONFIDENCE}%, verify passed, iter ${ITER} → skipping prompt"
  echo "**Status:** SILENT_PASS at iteration ${ITER}" >> "${DEBUG_DIR}/DEBUG-LOG.md"
  USER_CHOICE="fixed"
  # Skip to step 4_complete
else
  # Fall through to AskUserQuestion below
  :
fi
```

### Loop AskUserQuestion (only if silent-continue did NOT trigger)

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
