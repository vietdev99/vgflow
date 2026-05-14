# Pass 2 — FE consumer contracts (Task 38, Bug F)

## Position in pipeline

```
2b_contracts (Pass 1, BE 4 blocks) → ... → 2b5e_a_lens_walk → 2b5e_edge_cases →
2b6c_view_decomposition → 2b6_ui_spec → 2b6b_ui_map → 2b6d_fe_contracts (Pass 2 — THIS) →
2b7_flow_detect → 2b8_rcrurdr_invariants → 2b9_workflows → 2c_verify
```

Pass 2 runs AFTER UI artifacts exist (UI-MAP, VIEW-COMPONENTS, lens-walk seeds) so
the subagent can derive `consumers` / `ui_states` / `error_to_action_map` from real
FE structure rather than guessing.

## Steps

1. Read `_shared/blueprint/fe-contracts-delegation.md` for the prompt template.
2. Spawn `Agent(subagent_type="vg-blueprint-fe-contracts", prompt=<delegation>)` —
   narrate spawn + return per UX baseline R2 (`scripts/vg-narrate-spawn.sh`).
3. Parse return JSON `endpoints[]`. For each entry: append `block5_body` to
   `${PHASE_DIR}/API-CONTRACTS/<slug>.md` under heading `## BLOCK 5: FE consumer contract`.
   If file already has a BLOCK 5 (re-run via `--only=fe-contracts`), REPLACE the
   existing block (regex match on `## BLOCK 5:`).
4. Run `python3 scripts/validators/verify-fe-contract-block5.py --contracts-dir ${PHASE_DIR}/API-CONTRACTS`.
5. On validator pass: emit `blueprint.fe_contracts_pass_completed` event.
6. On validator fail: emit `blueprint.fe_contract_block5_blocked` event with finding count;
   route through Task 33 wrapper if interactive (auto-fix subagent option).

## Backward compat

- Phases predating this step (e.g., PV3 4.1) lack BLOCK 5. Validator BLOCKs unless
  `--allow-block5-missing --override-reason="<text>"` is passed.
- Backfill via `/vg:blueprint <phase> --only=fe-contracts`.

## Bash gate (Batch 32 — was SCAFFOLD)

Audit found this step was prose only. Required: step-active, real validator
invoke, mark-step with exit-on-fail gate.

```bash
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" step-active 2b6d_fe_contracts >/dev/null 2>&1 || true

# Profile gate: web-backend-only skips this step
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-backend-only)
    echo "ℹ 2b6d_fe_contracts SKIPPED (profile=${PHASE_PROFILE} — backend-only)"
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" mark-step blueprint 2b6d_fe_contracts 2>/dev/null || true
    return 0 2>/dev/null || exit 0
    ;;
esac

# Validator: per-endpoint BLOCK 5 FE consumer contract present in API-CONTRACTS/<slug>.md
FE_CONTRACTS_RC=0
if [ -d "${PHASE_DIR}/API-CONTRACTS" ]; then
  set +e
  "${PYTHON_BIN:-python3}" scripts/validators/verify-fe-contract-block5.py \
    --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
    > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/fe-contracts-validator.out" \
    2> "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/fe-contracts-validator.err"
  FE_CONTRACTS_RC=$?
  set -e
fi

if [ "$FE_CONTRACTS_RC" -ne 0 ]; then
  if [[ "${ARGUMENTS:-}" =~ --allow-block5-missing ]]; then
    echo "⚠ Batch 32 2b6d: --allow-block5-missing — BLOCK 5 absent (debt logged)"
  else
    echo "⛔ Batch 32 2b6d: verify-fe-contract-block5.py rc=${FE_CONTRACTS_RC}" >&2
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
      emit-event "blueprint.fe_contract_block5_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"rc\":${FE_CONTRACTS_RC}}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  emit-event "blueprint.fe_contracts_pass_completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  mark-step blueprint 2b6d_fe_contracts 2>/dev/null || true
echo "✓ Batch 32: 2b6d_fe_contracts marked"
```
