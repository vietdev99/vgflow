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
