# Aggregate + analyze — STEPS 5 & 6

Two sub-steps:

1. `4_aggregate_logs` — merge per-model `observe-*.jsonl` into single
   `RAW-LOG.jsonl`, run evidence completeness validator + vocabulary
   validator (banned tokens tagged `vocabulary_violation: true`)
2. `5_analyze_findings` — commander analysis via R1-R8 deterministic
   Python rules in `roam-analyze.py`

---

<step name="4_aggregate_logs">
## Step 4 — Aggregate raw logs (commander)

```bash
# Merge observe-*.jsonl from EVERY model dir into single RAW-LOG.jsonl
> "${ROAM_DIR}/RAW-LOG.jsonl"
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  cat "$MODEL_DIR"/observe-*.jsonl >> "${ROAM_DIR}/RAW-LOG.jsonl" 2>/dev/null || true
done
EVENT_COUNT=$(wc -l < "${ROAM_DIR}/RAW-LOG.jsonl" 2>/dev/null | tr -d ' ' || echo 0)
EXEC_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
echo "▸ Aggregated ${EVENT_COUNT} events from ${EXEC_COUNT} executor output(s) across ${#ROAM_MODEL_DIRS[@]} model dir(s)"

# v2.42.9+ — Evidence completeness validator (HARD gate per scanner-report-contract)
# Rejects observations missing required tier fields. Output tagged for commander.
echo ""
echo "▸ Evidence completeness check (rule: REQUIRED fields per tier — empty/null OK, missing = reject)"
COMPLIANCE_OUT="${ROAM_DIR}/evidence-compliance.json"
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  "${PYTHON_BIN:-python3}" .claude/scripts/verify-scanner-evidence-completeness.py \
    --jsonl-glob "${MODEL_DIR}/observe-*.jsonl" \
    --lens-from-filename \
    --threshold "${ROAM_EVIDENCE_THRESHOLD:-80}" \
    --output "${COMPLIANCE_OUT}" 2>&1 | tail -10
  COMPL_RC=$?
  if [ $COMPL_RC -eq 1 ]; then
    echo "⛔ Evidence completeness BLOCK — see ${COMPLIANCE_OUT}"
    if [[ ! "${ARGUMENTS}" =~ --skip-evidence-completeness ]]; then
      echo "   Override (NOT recommended): /vg:roam ${PHASE_NUMBER} --skip-evidence-completeness"
      echo "   Recommended: re-run scanner — it produced too many incomplete observations."
      exit 1
    fi
    echo "⚠ --skip-evidence-completeness set — proceeding with partial evidence"
  elif [ $COMPL_RC -eq 2 ]; then
    echo "⚠ Evidence completeness WARN — partial coverage, commander will deprioritize"
  fi
done

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "4_aggregate_logs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_aggregate_logs.done"
```

### Vocabulary validator (preserved as-is per `<rules>` rule 8)

Post-aggregate step runs `grep` on `observe-*.jsonl` for banned tokens
(`bug`, `broken`, `critical`, `should fix`, etc — full list in
`vg:_shared:scanner-report-contract`). Hits → tag report
`vocabulary_violation: true`, commander deprioritizes during step 5
analysis but still consumes (partial signal > no signal). Implementation
inside `roam-analyze.py` — no separate script invocation here.
</step>

---

<step name="5_analyze_findings">
## Step 5 — Commander analysis (THE judgment step)

Run deterministic Python rules R1-R8 over `RAW-LOG.jsonl`. Classify
findings into severity buckets. Output `ROAM-BUGS.md` + proposed
`.spec.ts` files.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/roam-analyze.py \
  --raw-log "${ROAM_DIR}/RAW-LOG.jsonl" \
  --phase-dir "${PHASE_DIR}" \
  --output-md "${ROAM_DIR}/ROAM-BUGS.md" \
  --output-specs-dir "${ROAM_DIR}/proposed-specs" \
  --output-summary "${ROAM_DIR}/RUN-SUMMARY.json"

BUGS_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${ROAM_DIR}/RUN-SUMMARY.json')); print(d.get('total_bugs',0))" 2>/dev/null || echo 0)
CRIT_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${ROAM_DIR}/RUN-SUMMARY.json')); print(d.get('by_severity',{}).get('critical',0))" 2>/dev/null || echo 0)
echo "▸ Found ${BUGS_COUNT} bugs (${CRIT_COUNT} critical)"

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.analysis.completed" \
  --actor "orchestrator" --outcome "INFO" --payload "{\"bugs\":${BUGS_COUNT},\"critical\":${CRIT_COUNT}}" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "5_analyze_findings" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_analyze_findings.done"
```

### R1-R8 deterministic rules

State coherence assertion via R1-R8 deterministic Python rules in
`roam-analyze.py` (preserved as-is). The commander is the sole judge —
scanners only report observations (per
`vg:_shared:scanner-report-contract`). Rules cover:

- **R1-R3:** UI claim ↔ network truth ↔ DB read-after-write coherence
- **R4-R5:** Form RCRURD lifecycle integrity
- **R6:** Modal lifecycle hygiene (ESC, focus trap, parent state isolation)
- **R7:** Authorization negative paths (wrong role, peer-tenant)
- **R8:** Business-logic state machine + race conditions
</step>
