# Review fix-loop subagent delegation contract (Task 33 option [a])

Input envelope (rendered as Agent prompt):

```json
{
  "gate_id": "api_precheck",
  "phase_dir": ".vg/phases/4.1-billing",
  "evidence_path": ".vg/api-precheck-evidence.json",
  "fix_hint_path": ".vg/api-precheck-detail.txt",
  "ownership_allowlist_files": ["apps/api/src/billing/**", "apps/web/src/billing/**"],
  "ownership_allowlist_dirs": ["apps/api/src/billing/", "apps/web/src/billing/"],
  "max_attempts": 3,
  "deployed_app_url": "http://localhost:3010",
  "auth_fixture_path": ".vg/test-credentials/admin.json"
}
```

## Procedure

For attempt N in 1..max_attempts:

1. Read evidence + fix_hint to understand the gate failure.
2. Decide target:
   - API gates (api_precheck, asserted_drift, replay_evidence,
     mutation_submit) → run against deployed app (curl + write
     handler/migration/restart service)
   - Drift gates (matrix_staleness, foundation_drift,
     rcrurd_post_state) → edit artifacts (CONTEXT.md, drift register,
     RUNTIME-MAP.json)
3. Apply minimal fix.
4. Re-run the validator that produced the gate failure.
5. If validator returns 0 (PASS) → return `{"status": "FIXED",
   "iterations": N, "summary": "..."}`
6. If validator still fails AND attempt < max → continue.
7. If validator still fails AND attempt == max → return
   `{"status": "UNRESOLVED", "iterations": max, "summary": "...",
    "repair_packet": {"hint": "...", "blocked_by": "..."}}`

## Forbidden actions

- Editing files outside `ownership_allowlist_*` → return
  `{"status": "OUT_OF_SCOPE", ...}`.
- Calling `AskUserQuestion` (review is wrapped already; subagent is leaf).
- Spawning child agents.
- Modifying `API-CONTRACTS.md` → return UNRESOLVED with
  `blocked_by: "contract_amendment_required"` (wrapper short-circuits
  to option `[r]`).
- Adding test stubs without implementations.

## Output

Return JSON envelope to wrapper Leg 2. Wrapper handles validator
re-run + commit + telemetry.
