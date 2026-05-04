# specs close (STEP 3 — commit + next-step suggestions)

1 sub-step in this ref:
1. `commit_and_next` — git add SPECS.md + INTERFACE-STANDARDS.{md,json},
   commit, soft-suggest design discovery if FE work detected, run-complete

<HARD-GATE>
run-complete validates runtime_contract — must_emit_telemetry events
specs.tasklist_shown, specs.native_tasklist_projected (Bug D),
specs.started, specs.approved must all have fired before run-complete
returns 0.
</HARD-GATE>

---

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
