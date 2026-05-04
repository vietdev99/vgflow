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

<step name="2b6d_fe_contracts">

## Lifecycle wrapper (R6 Task 1 — wire missing marker)

```bash
# Skip-flag check (forbidden_without_override paired)
if [[ "$ARGUMENTS" =~ --skip-fe-contracts ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-fe-contracts requires --override-reason=<text>"
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contracts_pass_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"--skip-fe-contracts\"}" 2>/dev/null || true
  # Canonical override.used emit — runtime_contract.forbidden_without_override
  # requires an exact override.used.flag match for --skip-fe-contracts before
  # run-complete will pass.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--skip-fe-contracts" \
    --reason "Pass 2 FE consumer contracts skipped (phase ${PHASE_NUMBER})" \
    >/dev/null 2>&1 || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-fe-contracts-skipped" "${PHASE_NUMBER}" \
      "Pass 2 FE consumer contracts skipped" "$PHASE_DIR"
  exit 0
fi

# Profile-gate (web-fullstack, web-frontend-only only)
case "${PHASE_PROFILE:-feature}" in
  web-fullstack|web-frontend-only) ;;
  *)
    echo "ℹ Profile ${PHASE_PROFILE} — skipping 2b6d_fe_contracts (web-only step)"
    exit 0
    ;;
esac

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2b6d_fe_contracts

# Spawn vg-blueprint-fe-contracts subagent (narrate per UX baseline R2)
bash .claude/scripts/vg-narrate-spawn.sh vg-blueprint-fe-contracts spawning \
  "phase ${PHASE_NUMBER} FE BLOCK 5 generation"
# AI: now spawn:
#   Agent(subagent_type="vg-blueprint-fe-contracts",
#         prompt=<from fe-contracts-delegation.md>)
# AI: parse return JSON; for each endpoints[] entry, append BLOCK 5 to
#     ${PHASE_DIR}/API-CONTRACTS/<slug>.md under heading
#     `## BLOCK 5: FE consumer contract` (REPLACE if exists, regex match
#     on `## BLOCK 5:`).
# AI: post-spawn narration:
#   bash .claude/scripts/vg-narrate-spawn.sh vg-blueprint-fe-contracts returned \
#     "<count> endpoints"

# Run validator
"${PYTHON_BIN:-python3}" scripts/validators/verify-fe-contract-block5.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS"
VAL_RC=$?
if [ "$VAL_RC" -eq 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contracts_pass_completed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
else
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contract_block5_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"validator_rc\":${VAL_RC}}" 2>/dev/null || true
  echo "⛔ FE BLOCK 5 validator failed (rc=${VAL_RC})" >&2
  exit 1
fi

# Lifecycle close
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER}" "2b6d_fe_contracts" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/2b6d_fe_contracts.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6d_fe_contracts 2>/dev/null || true
```

</step>
