# roam artifacts (STEP 6)

<HARD-GATE>
`6_emit_artifacts` MUST run after step 5 analysis writes ROAM-BUGS.md +
RUN-SUMMARY.json. PIPELINE-STATE verdict `BLOCK_ACCEPT` flips when
critical bug count > 0; `/vg:accept` consumes this verdict. Do NOT
auto-merge `proposed-specs/*.spec.ts` — manual gate per `<rules>` 4.
</HARD-GATE>

**Marker:** `6_emit_artifacts`

`ROAM-BUGS.md` and `RUN-SUMMARY.json` are already written by step 5
(`aggregate-analyze.md`). This step:

1. Updates `PIPELINE-STATE.json` with the roam verdict
   (`PASS` / `BLOCK_ACCEPT` based on critical bug count).
2. Notes that proposed `.spec.ts` files are **staged** under
   `${PHASE_DIR}/roam/proposed-specs/` — NOT auto-merged into the test
   suite. Merge requires `--merge-specs` confirmation (per `<rules>` 4).

---

## Update PIPELINE-STATE + verdict

```bash
vg-orchestrator step-active 6_emit_artifacts

${PYTHON_BIN:-python3} -c "
import json, datetime
from pathlib import Path
p = Path('${PHASE_DIR}/PIPELINE-STATE.json')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
steps = s.setdefault('steps', {})
roam = steps.setdefault('roam', {})
roam['status'] = 'done'
roam['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
roam['bugs_total'] = ${BUGS_COUNT:-0}
roam['bugs_critical'] = ${CRIT_COUNT:-0}
roam['verdict'] = 'BLOCK_ACCEPT' if ${CRIT_COUNT:-0} > 0 else 'PASS'
p.write_text(json.dumps(s, indent=2))
"

if [ "${CRIT_COUNT:-0}" -gt 0 ]; then
  echo "⛔ ${CRIT_COUNT} critical bug(s) — blocks /vg:accept until resolved or override-debt logged"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "6_emit_artifacts" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_emit_artifacts.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 6_emit_artifacts 2>/dev/null || true
```

## Spec.ts proposal staging contract

`roam-analyze.py` writes proposed `.spec.ts` files to
`${PHASE_DIR}/roam/proposed-specs/`. These are **proposals only** — the
auto-merge gate is intentional (per Q10 from ROAM-RFC):

- Roam observations may include false positives, especially on the first
  pass over a new lens-surface combination.
- Auto-merging untriaged specs would pollute the test suite with flaky
  tests that subsequently get disabled, creating coverage debt.
- Manual gate ensures user reviews each proposed spec, validates against
  product behavior expectations, then merges via `--merge-specs`.

The merge invocation is documented in `close.md` (alongside the
`--merge-specs` invocation note for Special Modes).

## Artifact summary

After this step the following exist in `${PHASE_DIR}/roam/`:

| File | Origin | Purpose |
|---|---|---|
| `SURFACES.md` | step 1 | CRUD-bearing surface table |
| `INSTRUCTION-{S}-{lens}.md` | step 2 (per-model dir) | Brief per surface×lens |
| `observe-{S}-{lens}.jsonl` | step 3 (per-model dir) | Executor output JSONL |
| `RAW-LOG.jsonl` | step 4 | Merged observations |
| `evidence-compliance.json` | step 4 | Evidence completeness report |
| `ROAM-BUGS.md` | step 5 | Bug findings, ranked by severity |
| `RUN-SUMMARY.json` | step 5 | Counts + by_severity dict |
| `proposed-specs/*.spec.ts` | step 5 | Staged spec proposals |
| `ROAM-CONFIG.json` | step 0a | env/model/mode/target_url snapshot |
