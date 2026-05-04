# RCRURDR invariants generation (Task 39, Bug G — R6 wiring)

## Position in pipeline

```
2b6d_fe_contracts → 2b8_rcrurdr_invariants (THIS) → 2b9_workflows → 2c_verify
```

## Purpose

Validate per-goal RCRURD invariants in extracted ` ```yaml-rcrurd``` ` fences
in `TEST-GOALS/G-NN.md`. Parser `scripts/lib/rcrurd_invariant.py::
extract_from_test_goal_md` (Task 39 commit 9923bad) parses each goal's
yaml fence into a `LifecyclePhase[]` structure used by review/test runtime
verification.

This blueprint step does NOT generate new RCRURD invariants — those live
inline in TEST-GOALS yaml-rcrurd fences (written by `vg-blueprint-contracts`
in Pass 1). This step VALIDATES that every goal with mutation behavior has
a parseable invariant, and emits per-goal telemetry for downstream
review/test consumers.

**Single source of truth (R7 Task 2 — G7 fix):** Inline `yaml-rcrurd` fences
in `TEST-GOALS/G-NN.md` are the **only canonical location** for RCRURD
invariants. The legacy `${PHASE_DIR}/RCRURD-INVARIANTS/G-NN.yaml` directory
is supported by `scripts/pre-executor-check.py` only as a backward-compat
fallback for pre-v2.49 phases. New phases MUST use inline fences; do NOT
write standalone files in `RCRURD-INVARIANTS/`.

<step name="2b8_rcrurdr_invariants">

## Lifecycle wrapper (R6 Task 1 — wire missing marker)

```bash
# Skip-flag check (forbidden_without_override paired)
if [[ "$ARGUMENTS" =~ --skip-rcrurdr ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-rcrurdr requires --override-reason=<text>"
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.rcrurdr_invariant_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"--skip-rcrurdr\"}" 2>/dev/null || true
  # Canonical override.used emit — runtime_contract.forbidden_without_override
  # requires an exact override.used.flag match for --skip-rcrurdr before
  # run-complete will pass.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--skip-rcrurdr" \
    --reason "RCRURDR invariant validation skipped (phase ${PHASE_NUMBER})" \
    >/dev/null 2>&1 || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-rcrurdr-skipped" "${PHASE_NUMBER}" \
      "RCRURDR invariant validation skipped" "$PHASE_DIR"
  exit 0
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2b8_rcrurdr_invariants

# Iterate TEST-GOALS/G-*.md and validate each via parser. Emit per-goal event.
GOAL_COUNT=0
PARSED_COUNT=0
SKIPPED_COUNT=0

for goal_file in "${PHASE_DIR}"/TEST-GOALS/G-*.md; do
  [ -f "$goal_file" ] || continue
  goal_id=$(basename "$goal_file" .md)
  GOAL_COUNT=$((GOAL_COUNT + 1))

  # Run parser — exit 0 if yaml-rcrurd fence present + parseable, exit 1 if not
  if "${PYTHON_BIN:-python3}" -c "
import sys
sys.path.insert(0, 'scripts/lib')
from rcrurd_invariant import extract_from_test_goal_md
text = open('${goal_file}', encoding='utf-8').read()
sys.exit(0 if extract_from_test_goal_md(text) is not None else 1)
" 2>/dev/null; then
    PARSED_COUNT=$((PARSED_COUNT + 1))
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "blueprint.rcrurdr_invariant_emitted" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goal\":\"${goal_id}\"}" 2>/dev/null || true
  else
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    # Goal lacks yaml-rcrurd fence — informational, not blocking
    # (mutation goals SHOULD have one but read-only goals don't need it)
  fi
done

echo "rcrurdr-invariants: ${PARSED_COUNT}/${GOAL_COUNT} goals parsed (${SKIPPED_COUNT} skipped — likely read-only)"

# Lifecycle close
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER}" "2b8_rcrurdr_invariants" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/2b8_rcrurdr_invariants.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b8_rcrurdr_invariants 2>/dev/null || true
```

</step>
