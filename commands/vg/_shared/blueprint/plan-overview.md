# blueprint plan group — STEP 3 overview

This is a HEAVY step (current spec ~673 lines). You MUST delegate to the
`vg-blueprint-planner` subagent (tool name `Agent`, NOT `Task`).

<HARD-GATE>
You MUST spawn `vg-blueprint-planner` for step 2a_plan.
You MUST NOT generate PLAN.md inline.
</HARD-GATE>

## How to spawn

1. `vg-orchestrator step-active 2a_plan`
2. Read `plan-delegation.md` for exact input/output contract.
3. Call `Agent(subagent_type="vg-blueprint-planner", prompt=<as defined in delegation.md>)`
4. On return, validate `path` + `sha256` of returned PLAN.md.
5. Touch marker + `vg-orchestrator mark-step blueprint 2a_plan`.
6. Emit telemetry: `vg-orchestrator emit-event blueprint.plan_written`.

The PreToolUse Bash hook will block step 5/6 if step 1 was not preceded by
TodoWrite (signed evidence required).
