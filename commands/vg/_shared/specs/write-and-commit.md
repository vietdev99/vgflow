<!-- v2.75.0 T1-T3 extraction — verbatim step blocks from commands/vg/specs.md -->
<!-- Group: write-and-commit | Steps: write_specs, write_interface_standards, commit_and_next -->

<process>

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
status: approved
created: {YYYY-MM-DD}
source: ai-draft|user-guided
---

## Goal

{1-2 sentence phase objective}

## Scope

### In Scope
- {feature/task 1}
- {feature/task 2}

### Out of Scope
- {exclusion 1}
- {exclusion 2}

## Constraints
- {constraint 1}

## Success Criteria
- [ ] {measurable criterion 1}
- [ ] {measurable criterion 2}

## Dependencies
- {dependency on prior phase or external system}
```

- **source**: `ai-draft` if --auto or user chose option 1, else `user-guided`
- **created**: today's date YYYY-MM-DD

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

<step name="commit_and_next">
## Step 8: Commit and Next Step

```bash
git add "${PHASE_DIR}/SPECS.md" \
        "${PHASE_DIR}/INTERFACE-STANDARDS.md" \
        "${PHASE_DIR}/INTERFACE-STANDARDS.json" || {
  echo "⛔ git add failed — check permissions" >&2
  exit 1
}
git commit -m "specs(${PHASE_NUMBER}): create SPECS and interface standards for phase ${PHASE_NUMBER}" || {
  echo "⛔ git commit failed — check pre-commit hooks" >&2
  exit 1
}

# ─── P20 D-05: greenfield design discovery suggestion ──────────────────────
# After SPECS committed, surface design state proactively. Soft suggestion
# (doesn't block). Hard gate fires later in /vg:blueprint D-12.
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/scaffold-discovery.sh" 2>/dev/null || true
if type -t scaffold_detect_fe_work >/dev/null 2>&1 && scaffold_detect_fe_work "$PHASE_DIR"; then
  DESIGN_DIR=$(vg_config_get design_assets.paths "" 2>/dev/null | head -1)
  DESIGN_DIR="${DESIGN_DIR:-designs}"
  if ! scaffold_design_md_present "$PHASE_DIR"; then
    echo ""
    echo "ℹ Phase ${PHASE_NUMBER} có FE work nhưng chưa có DESIGN.md (tokens). Khuyến nghị:"
    echo "    /vg:design-system --browse   (chọn brand từ 58 variants)"
    echo "    /vg:design-system --create   (tạo custom)"
  fi
  MOCKUP_COUNT=$(scaffold_count_existing_mockups "$DESIGN_DIR")
  if [ "$MOCKUP_COUNT" = "0" ]; then
    echo ""
    echo "ℹ Chưa có mockup nào ở ${DESIGN_DIR}/. Khuyến nghị trước /vg:blueprint:"
    echo "    /vg:design-scaffold       (interactive tool selector)"
    echo "    /vg:design-scaffold --tool=pencil-mcp   (auto-generate)"
    echo ""
    echo "  /vg:blueprint D-12 sẽ HARD-BLOCK nếu vẫn thiếu mockup."
  fi
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "commit_and_next" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/commit_and_next.done"

# Orchestrator run-complete — validates runtime_contract + emits specs.completed
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ "$RUN_RC" -ne 0 ]; then
  echo "⛔ specs run-complete BLOCK (rc=$RUN_RC) — see orchestrator output" >&2
  exit $RUN_RC
fi

echo ""
echo "✓ SPECS.md + INTERFACE-STANDARDS created for Phase ${PHASE_NUMBER}."
echo "  Next: /vg:scope ${PHASE_NUMBER}"
```
</step>

</process>
