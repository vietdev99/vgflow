# blueprint close (STEP 6)

Final 2 steps: bootstrap reflection + run-complete.

## STEP 6.1 — bootstrap reflection (2e_bootstrap_reflection)

Spawn the existing vg-reflector skill via the Skill tool:

```
Skill(skill="vg-reflector", args="--phase ${PHASE_NUMBER} --command vg:blueprint")
```

Then:

```bash
touch "${PHASE_DIR}/.step-markers/2e_bootstrap_reflection.done"
vg-orchestrator mark-step blueprint 2e_bootstrap_reflection
```

## STEP 6.2 — run complete (3_complete)

Final marker + emit completion event:

```bash
vg-orchestrator emit-event blueprint.completed --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/3_complete.done"
vg-orchestrator mark-step blueprint 3_complete
vg-orchestrator run-complete
```

The Stop hook will then verify:
- All `must_write` artifacts present + content_min_bytes met
- All `must_emit_telemetry` events present
- All `must_touch_markers` touched
- vg.block.fired count == vg.block.handled count
- State machine ordering valid

If any fails → exit 2 + diagnostic. Else → run successful.

## Update tasklist (close-on-complete)

Mark all checklist items completed via TodoWrite. Then either clear the
list (preferred) or replace with one sentinel: "vg:blueprint phase ${PHASE_NUMBER} complete".
