# blueprint contracts group — STEP 4 overview

HEAVY step. You MUST delegate to `vg-blueprint-contracts` subagent.

<HARD-GATE>
You MUST spawn `vg-blueprint-contracts` for steps 2b_contracts +
2b5_test_goals + 2b5a_codex_test_goal_lane.
You MUST NOT generate API-CONTRACTS.md inline.
</HARD-GATE>

## How to spawn

1. `vg-orchestrator step-active 2b_contracts`
2. Read `contracts-delegation.md` for input/output contract.
3. Call `Agent(subagent_type="vg-blueprint-contracts", prompt=<as defined>)`.
4. Validate returned API-CONTRACTS.md + INTERFACE-STANDARDS.{md,json}
   + TEST-GOALS.md + (optional) TEST-GOALS.codex-proposal.md.
5. Touch markers for each step + `vg-orchestrator mark-step blueprint <step>`.
6. Emit telemetry: `vg-orchestrator emit-event blueprint.contracts_generated`.
