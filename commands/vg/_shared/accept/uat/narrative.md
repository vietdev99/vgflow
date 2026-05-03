# UAT narrative autofire — STEP 4

Maps to step `4b_uat_narrative_autofire`. Auto-generates
`UAT-NARRATIVE.md` deterministically (Sonnet-free) from TEST-GOALS
frontmatter so the human tester opens it side-by-side with the browser.

<HARD-GATE>
You MUST run this BEFORE STEP 5 (interactive UAT). The narrative document
is the anti-theatre measure for free-form interactive prompts — without
it, AI may paraphrase goals during AskUserQuestion and drift from the
TEST-GOALS frontmatter.
</HARD-GATE>

---

<step name="4b_uat_narrative_autofire">
**Phase 15 D-10 — Auto-generate UAT-NARRATIVE.md before interactive UAT (NEW, 2026-04-27).**

Before stepping into the interactive checklist, render the per-prompt UAT
narrative document so the human tester opens it side-by-side with their
browser. The narrative is built from 4 frontmatter fields per goal
(`entry_url`, `navigation_steps`, `precondition`, `expected_behavior`)
plus design-ref blocks where present (D-10 spec). Strings come ONLY from
narration-strings.yaml — no hardcoded labels (D-18 strict enforcement).

The generator (`scripts/build-uat-narrative.py`) is deterministic, takes
no Sonnet round-trip, and idempotently overwrites `UAT-NARRATIVE.md`
each run so re-acceptance always reflects the latest TEST-GOALS state.
A sibling `UAT-NARRATIVE-OVERRIDES.md` (if present) is appended verbatim
at the end so manual prose can survive regeneration.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 4b_uat_narrative_autofire 2>/dev/null || true

NARRATIVE_OUT="${PHASE_DIR}/UAT-NARRATIVE.md"
NARRATIVE_GEN="${REPO_ROOT}/.claude/scripts/build-uat-narrative.py"

if [ ! -f "$NARRATIVE_GEN" ]; then
  echo "⚠ build-uat-narrative.py missing — skipping narrative auto-fire (Phase 15 T5.1 not installed)" >&2
else
  ${PYTHON_BIN} "$NARRATIVE_GEN" \
      --phase-dir "${PHASE_DIR}" \
      --vg-config "${REPO_ROOT}/vg.config.md" \
      --output    "$NARRATIVE_OUT" \
      || {
        echo "⛔ UAT narrative generation failed — see stderr above." >&2
        echo "   Inspect TEST-GOALS frontmatter for missing entry_url / navigation_steps / precondition / expected_behavior." >&2
        exit 1
      }
  echo "✓ UAT-NARRATIVE.md written → ${NARRATIVE_OUT}"
fi

# D-05/06/07 — verify the 4 mandatory fields per prompt
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uat-narrative-fields.py" \
    --phase "${PHASE_NUMBER}" \
    > "${VG_TMP}/uat-narrative-fields.json" 2>&1
NARR_VERDICT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/uat-narrative-fields.json')).get('verdict','BLOCK'))" 2>/dev/null)
case "$NARR_VERDICT" in
  PASS|WARN) echo "✓ UAT narrative fields validator: $NARR_VERDICT" ;;
  *) echo "⛔ UAT narrative fields validator: $NARR_VERDICT — see ${VG_TMP}/uat-narrative-fields.json" >&2; exit 1 ;;
esac

# D-18 — verify no hardcoded UAT strings leaked into the rendered narrative
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uat-strings-no-hardcode.py" \
    --phase "${PHASE_NUMBER}" \
    --narrative "$NARRATIVE_OUT" \
    > "${VG_TMP}/uat-strings.json" 2>&1
STR_VERDICT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/uat-strings.json')).get('verdict','BLOCK'))" 2>/dev/null)
case "$STR_VERDICT" in
  PASS|WARN) echo "✓ UAT strings hardcode scan: $STR_VERDICT" ;;
  *) echo "⛔ UAT strings hardcode scan: $STR_VERDICT — narrative contains literal labels not from narration-strings.yaml. See ${VG_TMP}/uat-strings.json" >&2; exit 1 ;;
esac

echo ""
echo "▸ UAT-NARRATIVE.md ready. Open it side-by-side with your browser:"
echo "    ${NARRATIVE_OUT}"
echo ""
```

The interactive UAT in step 5 references this document — testers walk each
prompt with the narrative open in another window. The narrative does NOT
replace the interactive checklist; it provides the WHY/HOW context that
used to live only in tester memory.

Final action:
```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4b_uat_narrative_autofire" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4b_uat_narrative_autofire.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 4b_uat_narrative_autofire 2>/dev/null || true
```
</step>
