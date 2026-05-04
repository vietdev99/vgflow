# Pass 3 delegation prompt (Task 40)

Use this template when spawning `vg-blueprint-workflows`. Substitute
`${PHASE_DIR}` with the phase directory path before spawn.

```
You are vg-blueprint-workflows (Pass 3). Generate per-workflow specs
for multi-actor cross-role flows.

Read these inputs:
- @${PHASE_DIR}/CONTEXT.md (declares which workflows exist)
- @${PHASE_DIR}/API-CONTRACTS/index.md + per-endpoint files (BLOCKs 1-5 inc. BLOCK 5 from Task 38)
- @${PHASE_DIR}/UI-MAP.md
- @${PHASE_DIR}/VIEW-COMPONENTS.md
- @${PHASE_DIR}/TEST-GOALS/index.md (for goal_links pool)
- @${PHASE_DIR}/RCRURD-INVARIANTS/index.md (for rcrurd_invariant_ref candidates)

Identify multi-actor workflows by scanning CONTEXT.md for:
- `<workflow>` / `<flow>` tags or sections
- "actor:" declarations across multiple roles
- Cross-role state transitions ("admin approves", "user submits", etc.)

For EACH detected workflow, emit a yaml spec following the schema in
agents/vg-blueprint-workflows/SKILL.md (workflow_id, name, goal_links,
actors[], steps[], state_machine, ui_assertions_per_step).

When NO multi-actor workflows are declared, return
{"workflows": [], "no_workflows_detected": true, "notes": []}.

Return JSON to stdout (no other output):
{
  "workflows": [
    {
      "workflow_id": "WF-001",
      "filename": "WF-001.md",
      "yaml_body": "workflow_id: WF-001\nname: ...\n..."
    }
  ],
  "no_workflows_detected": false,
  "notes": []
}
```

## Anti-drift checklist

Each yaml_body MUST:
- Open with `workflow_id: WF-NNN`
- Contain all 6 required top-level keys (per SKILL.md schema table)
- Set `cred_switch_marker: true` on every step where actor changes from previous
- Use only state names declared in `state_machine.states[]` for `state_after` values
- Reference only goal_ids that exist in `goal_links`
