# Matrix INTENT (review discovery-only)

Compute 3-verdict intent per goal in `GOAL-COVERAGE-MATRIX.json`:

- `READY_STRUCTURAL` — goal has L1/L2 selector bindings + endpoint observed in RUNTIME-MAP, but NO per-goal assertion evidence persisted by review. Test lane MUST replay (NOT auto-pass).
- `READY_BEHAVIORAL` — goal has structural readiness PLUS persisted assertion evidence (e.g. observed mutation + persistence_check passed during review discovery). TRUST_REVIEW may auto-pass.
- `BLOCKED` — goal endpoint missing OR selectors unresolved
- `NOT_SCANNED` — goal not exercised during browser discovery

> **Backward compatibility:** Bare `READY` is treated as `READY_STRUCTURAL` (safe default — forces replay). New `READY_BEHAVIORAL` is opt-in when review captures `evidence_ref` per goal.

**No TEST_PENDING here.** That verdict is computed by `/vg:test` Step 5 (after actual playwright execute).

## Algorithm

```python
for goal in goals:
    if goal.endpoint_observed and goal.selectors_resolved:
        if goal.assertion_evidence_persisted:  # NEW
            verdict = "READY_BEHAVIORAL"
        else:
            verdict = "READY_STRUCTURAL"
    elif not goal.endpoint_observed:
        verdict = "BLOCKED"
    else:
        verdict = "NOT_SCANNED"
```

## Output

Write `MATRIX-INTENT.json` to phase dir:

```json
{
  "phase": "${PHASE_NUMBER}",
  "computed_at": "<ISO timestamp>",
  "goals": [
    {"goal_id": "G-01", "verdict": "READY", "reason": "endpoint + selectors OK"},
    {"goal_id": "G-02", "verdict": "BLOCKED", "reason": "endpoint /api/refund missing in RUNTIME-MAP"}
  ]
}
```

## Mark step

```bash
"${PYTHON_BIN:-python3}" "$ORCH" mark-step review phase2.5_matrix_intent 2>/dev/null || true
```
