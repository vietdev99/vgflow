<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 6: Wire L4a gates into build STEP 5 post-execution

**Files:**
- Modify: `commands/vg/_shared/build/post-execution-overview.md`
- Modify: `commands/vg/build.md` (frontmatter telemetry + must_touch_markers)

- [ ] **Step 1: Find post-execution gate insertion point**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -nE "^### |^## STEP |truthcheck|API truthcheck" commands/vg/_shared/build/post-execution-overview.md | head -20
```
Identify the line where existing gates run (truthcheck per task). The L4a gates run AFTER all per-task gates in step 3 but BEFORE the SUMMARY.md write in step 5.

- [ ] **Step 2: Insert L4a block in post-execution-overview.md**

Append to `commands/vg/_shared/build/post-execution-overview.md` (just before the SUMMARY.md write step — anchor on the section header that introduces SUMMARY.md):

```markdown
### Step 4.5 — L4a deterministic phase-level gates (BLOCK on violation)

After per-task gates complete and before SUMMARY.md is written, run 3
deterministic phase-level gates that catch issues per-task gates cannot
see (cross-file FE↔BE comparisons + cross-document spec drift):

```bash
EVIDENCE_DIR="${PHASE_DIR}/.evidence"
mkdir -p "$EVIDENCE_DIR"

# L4a-i: FE → BE call graph (exits 1 + writes evidence on gap)
FE_ROOT=$(vg_config_get paths.web_pages "apps/web/src")
BE_ROOT=$(vg_config_get code_patterns.api_routes "apps/api/src")
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-fe-be-call-graph.py \
  --fe-root "$FE_ROOT" --be-root "$BE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/fe-be-call-graph.json" || {
  echo "⛔ L4a-i: FE→BE call graph violations — see ${EVIDENCE_DIR}/fe-be-call-graph.json"
  L4A_FAILED=1
}

# L4a-ii: Contract shape (method match for now — body P3)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-contract-shape.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
  --fe-root "$FE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/contract-shape.json" || {
  echo "⛔ L4a-ii: contract shape mismatches — see ${EVIDENCE_DIR}/contract-shape.json"
  L4A_FAILED=1
}

# L4a-iii: Spec drift (status code heuristic)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-spec-drift.py \
  --phase-dir "${PHASE_DIR}" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/spec-drift.json" || {
  echo "⛔ L4a-iii: spec drift — see ${EVIDENCE_DIR}/spec-drift.json"
  L4A_FAILED=1
}

if [ "${L4A_FAILED:-0}" = "1" ]; then
  # Emit telemetry — STEP 5.5 (next task) will pick up these evidence files
  # and run the auto-fix loop. Build does NOT mark complete with L4a violations.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.l4a_violations_detected" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\"}" \
    2>/dev/null || true
fi
```
```

- [ ] **Step 3: Add must_emit_telemetry to build.md frontmatter**

Edit `commands/vg/build.md`. Find the `must_emit_telemetry:` block. Add:

```yaml
    - event_type: "build.l4a_violations_detected"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "build.l4a_gates_passed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/build/post-execution-overview.md commands/vg/build.md
git commit -m "feat(build-fix-loop): wire L4a deterministic gates into post-execution"
```

---

