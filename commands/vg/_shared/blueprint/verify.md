# blueprint verify (STEP 5)

7 verify steps. Pure grep/path checks — fast, no AI required for the verify
itself. AI orchestrates the bash calls.

<HARD-GATE>
ALL 7 verify steps MUST execute. Each must touch its marker.
</HARD-GATE>

## STEP 5.1 — grep verify (2c_verify)

```bash
python3 .claude/scripts/vg-grep-verify.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_verify.done"
vg-orchestrator mark-step blueprint 2c_verify
```

## STEP 5.2 — path verify (2c_verify_plan_paths)

```bash
python3 .claude/scripts/vg-verify-plan-paths.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_verify_plan_paths.done"
vg-orchestrator mark-step blueprint 2c_verify_plan_paths
```

## STEP 5.3 — utility reuse (2c_utility_reuse)

```bash
python3 .claude/scripts/vg-utility-reuse-check.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_utility_reuse.done"
vg-orchestrator mark-step blueprint 2c_utility_reuse
```

## STEP 5.4 — compile check (2c_compile_check)

```bash
python3 .claude/scripts/vg-compile-check.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2c_compile_check.done"
vg-orchestrator mark-step blueprint 2c_compile_check
```

## STEP 5.5 — validation gate (2d_validation_gate)

```bash
python3 .claude/scripts/vg-validation-gate.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_validation_gate.done"
vg-orchestrator mark-step blueprint 2d_validation_gate
```

## STEP 5.6 — test type coverage (2d_test_type_coverage)

```bash
python3 .claude/scripts/vg-test-type-coverage.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_test_type_coverage.done"
vg-orchestrator mark-step blueprint 2d_test_type_coverage
```

## STEP 5.7 — goal grounding (2d_goal_grounding)

```bash
python3 .claude/scripts/vg-goal-grounding.py --phase ${PHASE_NUMBER}
touch "${PHASE_DIR}/.step-markers/2d_goal_grounding.done"
vg-orchestrator mark-step blueprint 2d_goal_grounding
```

After all 7 markers, return to entry SKILL.md → STEP 6.
