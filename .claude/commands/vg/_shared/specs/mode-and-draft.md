<!-- v2.75.0 T1-T3 extraction — verbatim step blocks from commands/vg/specs.md -->
<!-- Group: mode-and-draft | Steps: choose_mode, guided_questions, generate_draft -->

<process>

<step name="choose_mode">
## Step 3: Choose Mode

```bash
AUTO_MODE=false
if [[ "${ARGUMENTS:-}" =~ --auto ]]; then
  AUTO_MODE=true
fi
```

If `$AUTO_MODE=true`, skip to step 5 (generate_draft).

Otherwise, invoke `AskUserQuestion`:
- header: "SPECS mode"
- question: "Phase ${PHASE_NUMBER}: ${phase_goal}. Bạn muốn tạo SPECS theo cách nào?"
- options:
  - "AI Draft — tôi tự draft dựa trên ROADMAP + PROJECT"
  - "Guided — tôi hỏi 4-5 câu để bạn mô tả"

- If "AI Draft" → go to step 5 (generate_draft)
- If "Guided" → go to step 4 (guided_questions)

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "choose_mode" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/choose_mode.done"
```
</step>

<step name="guided_questions">
## Step 4: Guided Questions (User-Guided Mode only — skipped in --auto)

Ask questions ONE AT A TIME via `AskUserQuestion`. After each answer, save it immediately to avoid context loss.

**Q1: Goal** — "Mục tiêu chính của phase này là gì? (1-2 câu). ROADMAP nói: ${phase_goal}"

**Q2: Scope IN** — "Những gì NẰM TRONG scope? (liệt kê features/tasks)"

**Q3: Scope OUT** — "Những gì KHÔNG làm trong phase này? (exclusions rõ ràng)"

**Q4: Constraints** — "Ràng buộc kỹ thuật hoặc business nào cần lưu ý? (VD: latency, compatibility, dependencies)"

**Q5: Success Criteria** — "Làm sao biết phase này DONE? (tiêu chí đo lường được)"

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "guided_questions" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/guided_questions.done"
```
</step>

<step name="generate_draft">
## Step 5: Generate Draft + Approval Gate

**If AI Draft mode (`$AUTO_MODE=true` or user chose option 1):**
- Generate SPECS.md content from ROADMAP phase goal + PROJECT.md constraints
- Infer scope, constraints, success criteria from available context
- Match style of prior SPECS.md files if present

**If Guided mode:**
- Use user's answers from step 4 as primary content
- Supplement with ROADMAP + PROJECT where answers sparse
- Do NOT override explicit user answers with AI inference

**⛔ BLOCKING APPROVAL GATE — user MUST approve before write (OHOK Batch 1 B3).**

Render preview to user, then invoke `AskUserQuestion`:
- header: "Approve SPECS.md draft?"
- question: "Preview bên trên. Chọn Approve để ghi file, Edit để yêu cầu sửa, Discard để huỷ."
- options:
  - "Approve — write SPECS.md và tiếp tục"
  - "Edit — nói cần sửa gì, tôi regenerate rồi hỏi lại"
  - "Discard — dừng command, không tạo SPECS.md"

```bash
# OHOK Batch 1 B3: enforce explicit approval via $USER_APPROVAL env.
# AI MUST set USER_APPROVAL based on AskUserQuestion response:
#   "approve" → proceed to step 6
#   "edit" → loop back (regenerate + re-gate)
#   "discard" → exit 2 (clean halt, telemetry records decision)
# Silence / ambiguous / empty = treat as unapproved.

case "${USER_APPROVAL:-}" in
  approve)
    MODE_STR=$([ "${AUTO_MODE:-false}" = "true" ] && echo "auto" || echo "guided")
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.approved" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mode\":\"${MODE_STR}\"}" >/dev/null 2>&1 || true
    ;;
  edit)
    echo "User requested edit — regenerate draft + re-gate" >&2
    # AI loops back to regenerate; marker NOT touched until approve/discard terminal
    exit 2
    ;;
  discard)
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.rejected" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"user_discarded\"}" >/dev/null 2>&1 || true
    echo "⛔ User discarded SPECS draft — halting /vg:specs (no file written)" >&2
    # Log to override-debt so audit trail captures the reject
    source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "specs-user-discard" "${PHASE_NUMBER}" "user discarded draft at approval gate" "${PHASE_DIR}"
    fi
    exit 2
    ;;
  *)
    echo "⛔ Approval gate not passed — USER_APPROVAL='${USER_APPROVAL:-<unset>}'" >&2
    echo "   AI must invoke AskUserQuestion and set USER_APPROVAL ∈ {approve, edit, discard}." >&2
    echo "   Silence / ambiguous answer = unapproved. No SPECS.md written." >&2
    exit 2
    ;;
esac

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "generate_draft" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/generate_draft.done"
```

**Rationale:** previous wording "AI MUST stop, render preview, wait" was prose-only — AI could silent-skip and proceed to write. Now gate is bash-enforced: no write without `USER_APPROVAL=approve` env set by AI based on AskUserQuestion result.
</step>

</process>
