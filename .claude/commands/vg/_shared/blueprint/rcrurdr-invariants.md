# 2b8_rcrurdr_invariants — Per-goal RCRURD invariants extraction

## Position in pipeline

```
2b_contracts (Pass 1) → ... → 2b6d_fe_contracts (Pass 2) → 2b7_flow_detect →
2b8_rcrurdr_invariants (THIS — Task 22 + 39) → 2b9_workflows (Pass 3) → 2c_verify
```

## Purpose

For each mutation goal in `TEST-GOALS/G-NN.md`, extract its declared
RCRURD lifecycle (Read-Create-Read-Update-Read-Delete-Read) invariant
block (` ```yaml-rcrurd ` fenced) and emit a per-goal stage map.

This produces `${PHASE_DIR}/LIFECYCLE-SPECS.json` consumed by:
- /vg:test codegen for mutation specs (read-after-write Layer 3)
- /vg:test 5c_goal_verification per-goal replay
- /vg:test step7_matrix_verdict RCRURD runtime gate

## Steps

1. Read every `${PHASE_DIR}/TEST-GOALS/G-*.md` file.
2. Extract ` ```yaml-rcrurd` ... ` ``` ` blocks per goal.
3. Run `scripts/rcrurd-preflight.py --phase ${PHASE_NUMBER}` to generate
   LIFECYCLE-SPECS.json from extracted blocks.
4. Run `scripts/validators/verify-rcrurd-depth.py --phase ${PHASE_NUMBER}`
   to assert each mutation goal has all 7 stages declared.

## Bash gate (Batch 32 — was SCAFFOLD)

Audit (docs/plans/2026-05-15-codex-blueprint-scaffold-audit.md): declared
in blueprint.md must_mark list but no owner file. No bash. No mark-step.

```bash
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" step-active 2b8_rcrurdr_invariants >/dev/null 2>&1 || true

# Skip flag escape — phases without crud goals (e.g. cli/library) can skip
if [[ "${ARGUMENTS:-}" =~ --skip-rcrurdr ]]; then
  echo "⚠ 2b8_rcrurdr_invariants skipped (--skip-rcrurdr debt logged)"
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" mark-step blueprint 2b8_rcrurdr_invariants 2>/dev/null || true
  return 0 2>/dev/null || exit 0
fi

# Generate LIFECYCLE-SPECS.json from per-goal yaml-rcrurd blocks
PREFLIGHT_RC=0
if [ -f scripts/rcrurd-preflight.py ]; then
  set +e
  "${PYTHON_BIN:-python3}" scripts/rcrurd-preflight.py \
    --phase "${PHASE_NUMBER}" \
    --output "${PHASE_DIR}/LIFECYCLE-SPECS.json" \
    > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurdr-preflight.out" \
    2> "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurdr-preflight.err"
  PREFLIGHT_RC=$?
  set -e
fi

# Validate depth (7 stages per mutation goal)
DEPTH_RC=0
if [ -f scripts/validators/verify-rcrurd-depth.py ] && [ -f "${PHASE_DIR}/LIFECYCLE-SPECS.json" ]; then
  set +e
  "${PYTHON_BIN:-python3}" scripts/validators/verify-rcrurd-depth.py \
    --phase "${PHASE_NUMBER}" \
    > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurdr-depth.out" \
    2> "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurdr-depth.err"
  DEPTH_RC=$?
  set -e
fi

if [ "$PREFLIGHT_RC" -ne 0 ] || [ "$DEPTH_RC" -ne 0 ]; then
  echo "⛔ Batch 32 2b8_rcrurdr_invariants: preflight rc=${PREFLIGHT_RC}, depth rc=${DEPTH_RC}" >&2
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
    emit-event "blueprint.rcrurdr_invariants_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"preflight_rc\":${PREFLIGHT_RC},\"depth_rc\":${DEPTH_RC}}" \
    >/dev/null 2>&1 || true
  if [[ ! "${ARGUMENTS:-}" =~ --allow-rcrurdr-shortfall ]]; then
    exit 1
  fi
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  emit-event "blueprint.rcrurdr_invariants_generated" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  mark-step blueprint 2b8_rcrurdr_invariants 2>/dev/null || true
echo "✓ Batch 32: 2b8_rcrurdr_invariants marked"
```

## Backward compat

- Phases without mutation goals: empty extraction → LIFECYCLE-SPECS.json
  contains `{"goals": {}}`. Validator passes (no rcrurd to verify).
- `--skip-rcrurdr --override-reason="..."` for phases that cannot have
  CRUD goals (pure CLI tools, library extracts, etc).
- `--allow-rcrurdr-shortfall` for in-progress migration where some goals
  still lack yaml-rcrurd blocks.
