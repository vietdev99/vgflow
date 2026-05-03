# roam close (STEP 8)

<HARD-GATE>
`complete` MUST be the FINAL marker emitted in the pipeline. The
`roam.session.completed` event is the Stop-hook witness that the run
finished cleanly. Skipping this ref leaves the run in `step-active`
without a terminal mark — Stop hook fails.
</HARD-GATE>

**Marker:** `complete`

Final emit + summary. Also documents the `--merge-specs` special invocation
mode that lives outside the main pipeline.

---

## Emit completion event + banner

```bash
vg-orchestrator step-active complete

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.session.completed" \
  --actor "orchestrator" --outcome "INFO" \
  --payload "{\"surfaces\":${SURFACE_COUNT:-0},\"events\":${EVENT_COUNT:-0},\"bugs\":${BUGS_COUNT:-0}}" 2>/dev/null || true

echo ""
echo "━━━ Roam complete — Phase ${PHASE_NUMBER} ━━━"
echo "  Surfaces:    ${SURFACE_COUNT:-0}"
echo "  Events:      ${EVENT_COUNT:-0}"
echo "  Bugs total:  ${BUGS_COUNT:-0}"
echo "  Critical:    ${CRIT_COUNT:-0}"
echo "  Output:      ${ROAM_DIR}/ROAM-BUGS.md"
echo "  New specs:   ${ROAM_DIR}/proposed-specs/ (use /vg:roam --merge-specs to merge into test suite)"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam complete 2>/dev/null || true
```

---

## Special invocation mode — `--merge-specs`

Skip phases 0-7 entirely. Read existing
`${PHASE_DIR}/roam/proposed-specs/*.spec.ts`, validate each via
`vg-codegen-interactive` validator, merge into project test suite path
(per `paths.tests` in `vg.config.md`). Manual gate (Q10 — no auto-merge).

**This branch lives in the slim entry's preflight** (not in this close
ref) — when `--merge-specs` is set, the slim entry routes to the merge
branch and exits before reading any of the regular pipeline refs. The
merge invocation:

```bash
if [[ "$ARGUMENTS" =~ --merge-specs ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-merge-specs.py \
    --phase-dir "${PHASE_DIR}" \
    --proposed-dir "${PHASE_DIR}/roam/proposed-specs" \
    --target-dir "$(grep -oP 'tests:\s*\K\S+' .claude/vg.config.md)"
  exit 0
fi
```

Place this branch BEFORE step 0 (preflight) in the slim entry — it's a
short-circuit that runs alone without invoking the main pipeline.
