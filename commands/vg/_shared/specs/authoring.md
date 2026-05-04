# specs authoring (STEP 2 — draft + approval + write SPECS + interface standards)

3 sub-steps in this ref:
1. `generate_draft` — render preview + AskUserQuestion approval gate
   (OHOK Batch 1 B3: bash-enforced USER_APPROVAL=approve required)
2. `write_specs` — write SPECS.md with frontmatter + sections
3. `write_interface_standards` — generate INTERFACE-STANDARDS.{md,json}

<HARD-GATE>
generate_draft is BLOCKING APPROVAL GATE — silent / unset USER_APPROVAL = BLOCK.
- approve → write SPECS.md + emit specs.approved
- edit → loop back, regenerate
- discard → exit 2, emit specs.rejected, log override-debt

write_specs runs verify-artifact-schema.py post-write to catch frontmatter drift.
</HARD-GATE>

---

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

<step name="write_specs">
## Step 6: Write SPECS.md

Write to `${PHASE_DIR}/SPECS.md` with this format:

```markdown
---

<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

Ví dụ:
- ❌ "Validator failed with 225 evidence count"
- ✅ "Validator báo 225 trường thiếu — chi tiết ở `[path]`. Mình sẽ sửa rồi chạy lại."

File paths, code identifiers (G-04, Wave 9, getUserById), commit messages,
CLI commands stay English. AskUserQuestion title + options + question prose:
ngôn ngữ config.
</LANGUAGE_POLICY>
phase: {X}
profile: {feature|infra|hotfix|bugfix|migration|docs}
platform: {web-fullstack|web-frontend-only|web-backend-only|mobile-rn|mobile-flutter|mobile-native|desktop-electron|desktop-tauri|cli-tool|library|server-setup|server-management}
status: approved
created_at: {YYYY-MM-DD}
source: ai-draft|user-guided
---

## Goal

{1-2 sentence phase objective}

## Scope

### In Scope
- {feature/task 1}
- {feature/task 2}

## Out of Scope
- {exclusion 1}
- {exclusion 2}

## Constraints
- {constraint 1}

## Success criteria
- [ ] {measurable criterion 1}
- [ ] {measurable criterion 2}

## Dependencies
- {dependency on prior phase or external system}
```

- **profile**: project profile from `.claude/vg.config.md` (e.g. `feature`, `bugfix`)
- **platform**: project platform from `.claude/vg.config.md` (e.g. `web-fullstack`)
- **source**: `ai-draft` if --auto or user chose option 1, else `user-guided`
- **created_at**: today's date YYYY-MM-DD (schema-canonical key per `.claude/schemas/specs.v1.json`)

```bash
# Verify file actually written (catches silent write fail)
if [ ! -s "${PHASE_DIR}/SPECS.md" ]; then
  echo "⛔ SPECS.md write failed — file missing or empty at ${PHASE_DIR}/SPECS.md" >&2
  exit 1
fi

# v2.7 Phase E — schema validation post-write (BLOCK on frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact specs \
  > "${PHASE_DIR}/.tmp/artifact-schema-specs.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ SPECS.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-specs.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-specs.json"
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "write_specs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/write_specs.done"
```
</step>

<step name="write_interface_standards">
## Step 7: Write Interface Standards

After SPECS.md exists, generate the phase-local API/FE/CLI/mobile interface
contract. This artifact is mandatory context for blueprint, build, review,
and test. It standardizes API response envelopes, FE toast/form error
priority, CLI stdout/stderr/JSON output, and harness enforcement.

```bash
INTERFACE_GEN="${REPO_ROOT:-.}/.claude/scripts/generate-interface-standards.py"
INTERFACE_VAL="${REPO_ROOT:-.}/.claude/scripts/validators/verify-interface-standards.py"
[ -f "$INTERFACE_GEN" ] || INTERFACE_GEN="${REPO_ROOT:-.}/scripts/generate-interface-standards.py"
[ -f "$INTERFACE_VAL" ] || INTERFACE_VAL="${REPO_ROOT:-.}/scripts/validators/verify-interface-standards.py"

if [ ! -f "$INTERFACE_GEN" ] || [ ! -f "$INTERFACE_VAL" ]; then
  echo "⛔ Interface standards helpers missing — cannot continue specs." >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" "$INTERFACE_GEN" \
  --phase-dir "$PHASE_DIR" \
  --profile "${PROFILE:-web-fullstack}" \
  --force

mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
"${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
  --phase-dir "$PHASE_DIR" \
  --profile "${PROFILE:-web-fullstack}" \
  --no-scan-source \
  > "${PHASE_DIR}/.tmp/interface-standards-specs.json" 2>&1
INTERFACE_RC=$?
if [ "$INTERFACE_RC" -ne 0 ]; then
  echo "⛔ INTERFACE-STANDARDS validation failed — see ${PHASE_DIR}/.tmp/interface-standards-specs.json" >&2
  cat "${PHASE_DIR}/.tmp/interface-standards-specs.json"
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "write_interface_standards" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/write_interface_standards.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step specs write_interface_standards 2>/dev/null || true
```
</step>
