# Pass 3 — Multi-actor workflow specs (Task 40, Bug H)

## Position in pipeline

```
2b_contracts (Pass 1) → ... → 2b6d_fe_contracts (Pass 2 Task 38) → 2b7_flow_detect →
2b8_rcrurdr_invariants (Task 22 + Task 39) → 2b9_workflows (Pass 3 — THIS) → 2c_verify
```

Pass 3 runs AFTER all schema-emitting steps so the subagent can reference
real goal_ids, real endpoint paths, real component names from FE artifacts.

## Steps

1. Read `_shared/blueprint/workflows-delegation.md` for the prompt template.
2. Spawn `Agent(subagent_type="vg-blueprint-workflows", prompt=<delegation>)` —
   narrate spawn + return per UX baseline R2 (`scripts/vg-narrate-spawn.sh`).
3. Parse return JSON `workflows[]`:
   - For each entry: write `${PHASE_DIR}/WORKFLOW-SPECS/<filename>` containing
     ```` ```yaml\n<yaml_body>\n``` ````.
   - Write `${PHASE_DIR}/WORKFLOW-SPECS/index.md`: `# WORKFLOW-SPECS index\n\n- WF-001\n- WF-002\n` (or `flows: []` when none).
   - Concat all WF bodies into `${PHASE_DIR}/WORKFLOW-SPECS.md` (flat) for legacy reads.
4. Run `python3 scripts/validators/verify-workflow-specs.py --workflows-dir ${PHASE_DIR}/WORKFLOW-SPECS`.
5. On validator pass: emit `blueprint.workflows_pass_completed` event.
6. On validator fail: route through Task 33 wrapper (auto-fix subagent option).

## Backward compat

- Phases without multi-actor workflows: subagent returns `no_workflows_detected: true`. Orchestrator writes empty `index.md` with `flows: []`. Validator passes.
- `--skip-workflows --override-reason="..."` available for legacy phases.
