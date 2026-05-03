# Bug Detection Guide (v1.11.2 R6) — AI Instructions

**This file is loaded by every VG workflow command. AI orchestrator (Claude/Codex/Gemini) MUST follow these rules to auto-detect workflow bugs and trigger `/vg:bug-report`.**

## Mục đích

Bug-reporter.sh có **code để đẩy issue** lên `vietdev99/vgflow` GitHub. Nhưng code không tự chạy — **AI phải biết khi nào gọi nó**. File này là instruction cho AI để recognize bug patterns + trigger reporter.

---

## Universal Rule

**Khi AI orchestrator gặp BẤT KỲ pattern nào sau đây trong khi chạy workflow, MUST:**

1. **NARRATE intent**: "🐛 Phát hiện workflow bug: {brief description}. Đang đẩy issue lên vietdev99/vgflow..."
2. **CALL** `report_bug SIGNATURE TYPE CONTEXT [SEVERITY]` qua Bash sau khi source `bug-reporter.sh`
3. **CONTINUE** workflow — bug-report là background side-effect, không block main flow

**KHÔNG được:**
- Silent skip bug detection (im lặng = data leak loss)
- Block workflow để wait bug submission (best-effort, queue locally OK)
- Spam: dedup tự động via signature, OK to "report" same thing — sẽ skip

---

## Detection patterns AI MUST recognize

### Pattern 1: Schema violation (subagent output shape mismatch)

**Trigger condition:** Khi receive JSON output from subagent (Opus/Sonnet/Haiku via Task tool), verify schema. Nếu fields missing hoặc wrong types:

```bash
source .claude/commands/vg/_shared/lib/bug-reporter.sh

# Auto-detect via helper
bug_reporter_validate_schema "dim_expander" "$opus_json_output"
# Returns 1 if schema violated; helper auto-calls report_bug
```

**Manual detection example:**
```
SUBAGENT_RESPONSE='{"critical_missing": ["test_pyramid", "fixture"]}'
# Expected: array of OBJECTS {dimension, question, rationale}
# Actual: array of STRINGS
# → AI thoughts: "schema violation, must report"
# → Narrate + call report_bug
```

### Pattern 2: Helper bash function fails unexpectedly

**Trigger:** Bash command in workflow exits ≠ 0 BUT command was supposed to succeed (not deliberate exit-on-fail like gate check).

```bash
RESULT=$(some_helper_function "$arg" 2>&1)
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ] && ! [[ "$RESULT" =~ "expected_failure_marker" ]]; then
  source .claude/commands/vg/_shared/lib/bug-reporter.sh
  report_bug "helper-fail-${FUNCNAME[0]}" "helper_error" \
    "Helper $FUNCNAME exited $EXIT_CODE unexpectedly. Output: ${RESULT:0:200}" "medium"
fi
```

### Pattern 3: User pushback (semantic signal)

**Trigger:** User answer contains keywords indicating workflow misunderstood:

```
Keywords: nhầm, sai, bug, wrong, không đúng, không phải, phân tích sai,
         hiểu nhầm, lỗi, broken, doesn't work, "có vấn đề"
```

**AI MUST detect:**
```
USER_ANSWER="bạn phân tích nhầm trang rồi"
# AI sees "nhầm" → trigger pushback detector
source .claude/commands/vg/_shared/lib/bug-reporter.sh
bug_reporter_detect_pushback "$USER_ANSWER" "scope.round_5"
# Helper auto-calls report_bug if keyword found
```

### Pattern 4: Self-discovered bug during AI reasoning

**Trigger:** AI's own analysis reveals bug in workflow code/docs/install/script. Examples:

- "Install.sh missing copy step for `_shared/lib/*.sh`" → install bug
- "scope.md says 'use Read tool on /tmp file' but subagent sandbox can't" → docs bug
- "Helper outputs path on fd 3 but caller expects content" → API mismatch
- "Config drift: section X exists in template but not in active config" → migration gap

```bash
# AI narrates and reports
echo "🐛 Workflow bug discovered: <description>"
source .claude/commands/vg/_shared/lib/bug-reporter.sh
report_bug "self-found-{short-name}" "ai_inconsistency" \
  "AI orchestrator self-detected: {description}. Affected: {file/line}. Repro: {steps}. Suggested fix direction: {idea}." "medium"
```

### Pattern 5: Gate loop fatigue (workflow keeps blocking)

**Trigger:** Same gate fails N+ times consecutively, suggesting either user can't satisfy condition OR gate is wrong.

```bash
# In gate-checking code
GATE_FAIL_COUNT="${GATE_FAIL_COUNT:-0}"
if ! check_gate; then
  GATE_FAIL_COUNT=$((GATE_FAIL_COUNT + 1))
  if [ "$GATE_FAIL_COUNT" -ge 3 ]; then
    source .claude/commands/vg/_shared/lib/bug-reporter.sh
    report_bug "gate-loop-${GATE_NAME}" "gate_loop" \
      "Gate ${GATE_NAME} failed 3+ times. Either gate is too strict or condition is unreachable." "medium"
  fi
fi
```

### Pattern 6: AI inconsistency (same input → different outputs)

**Trigger:** AI calls same subagent twice with same input but gets structurally different responses.

```bash
# Cross-check 2 same-input runs
if ! diff <(echo "$RUN1") <(echo "$RUN2") | grep -qE "schema|structure"; then
  source .claude/commands/vg/_shared/lib/bug-reporter.sh
  report_bug "ai-flaky-${SUBAGENT_TYPE}" "ai_inconsistency" \
    "Subagent ${SUBAGENT_TYPE} returned structurally different outputs for same input. Prompt may need explicit schema reminder." "high"
fi
```

---

## Severity classification

| Severity | When | Send mode |
|---|---|---|
| `critical` | Workflow blocked, no workaround | Immediate |
| `high` | Workflow degraded, partial workaround | Immediate |
| `medium` | Affects quality, has workaround | Immediate (default if `auto_send_minor=true`) |
| `minor` | Polish/nice-to-have | Queued |
| `info` | Telemetry events (install/update/command) | Batched weekly |

**AI default for self-found bugs:** `medium`. Critical chỉ khi confirm 0 workaround.

---

## Anti-patterns — AI KHÔNG được làm

❌ **Silent skip:** Phát hiện bug nhưng không narrate → user không biết, lost data point
❌ **Pre-emptive disable:** Tự ý disable bug-reporter vì "ngại spam" → vi phạm purpose
❌ **Override severity downward:** "Just minor lah" cho real high → mất signal
❌ **Reference user bug instead of self-found:** "User said something is wrong" thay vì specific finding → noise
❌ **Block workflow for bug submission:** wait gh API → degrade UX. Best-effort queue đủ.

---

## Self-demo / Verification

User feedback 2026-04-18: "AI phải biết là sẽ đẩy issue nhé" — đây là rule chính của file này.

Sau khi load guide này, AI MUST acknowledge:
> "✓ Bug-detection-guide loaded. Recognize 6 patterns: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. Will narrate + report bugs as discovered."

---

## Integration in workflow commands

Each main workflow command (scope/build/review/test/accept) MUST include this line trong process header:

```markdown
**Bug detection (v1.11.2 R6):** Read `.claude/commands/vg/_shared/bug-detection-guide.md`. Apply 6 detection patterns throughout this workflow. Auto-trigger /vg:bug-report when patterns match.
```

---

## Telemetry events (info severity)

AI MUST emit these telemetry events automatically (no narration needed for `info` severity):

```bash
# At command start
report_telemetry "command_invoked" "{\"command\":\"$CMD\",\"phase\":\"$PHASE\"}"

# At command end (success)
report_telemetry "command_completed" "{\"command\":\"$CMD\",\"duration_sec\":$DURATION}"

# At command end (failure)
report_telemetry "command_failed" "{\"command\":\"$CMD\",\"step\":\"$STEP\",\"error\":\"$ERR\"}"
```

These get queued + batched weekly — no GitHub issue per event.
