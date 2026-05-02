# Cleanup — STEP 8 (HEAVY, subagent)

Maps to step `7_post_accept_actions` (306 lines in legacy accept.md).
Final post-accept lifecycle: scan-intermediate cleanup, bootstrap rule
attribution, VG-native state update, CROSS-PHASE-DEPS flip, DEPLOY-RUNBOOK
lifecycle, telemetry consolidation.

<HARD-GATE>
DO NOT cleanup inline. You MUST spawn `vg-accept-cleanup` via the `Agent`
tool. The 306-line step has 8+ subroutines (scan cleanup, screenshot
cleanup, worktree prune, bootstrap outcome attribution, PIPELINE-STATE
update, ROADMAP flip, CROSS-PHASE-DEPS flip, RUNBOOK draft+promote).
Inline execution will skim — empirical 96.5% skip rate without subagent.

Cleanup runs ONLY when UAT verdict is ACCEPTED. For DEFER/REJECTED/FAILED
verdicts, the cleanup short-circuits to a minimal lifecycle update (UAT.md
already written) and exits.
</HARD-GATE>

## Pre-spawn narration

```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup spawning "post-accept ${PHASE_NUMBER}"
```

## Spawn

Read `delegation.md` for the input/output contract. Then call:

```
Agent(subagent_type="vg-accept-cleanup", prompt=<built from delegation>)
```

## Post-spawn narration

On success:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup returned "<count> actions"
```

On failure:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup failed "<one-line cause>"
```

## Output validation

Subagent returns:
```json
{
  "verdict": "ACCEPTED" | "DEFER" | "REJECTED" | "FAILED" | "ABORTED",
  "cleanup_actions_taken": [
    "rm scan-*.json",
    "rm probe-*.json",
    "git worktree prune",
    "bootstrap.outcome_recorded x{N}",
    "PIPELINE-STATE → complete",
    "ROADMAP flip → complete",
    "CROSS-PHASE-DEPS flip {N} rows",
    "DEPLOY-RUNBOOK.md.staged → DEPLOY-RUNBOOK.md"
  ],
  "files_archived": ["..."],
  "files_removed": ["..."],
  "summary": "ACCEPTED phase {PHASE_NUMBER} — {N} cleanup actions"
}
```

After return, validate:
1. `verdict` matches the verdict written to `${PHASE_NUMBER}-UAT.md`
2. `cleanup_actions_taken[]` non-empty for ACCEPTED verdict (DEFER/REJECTED
   may be empty — subagent short-circuits)
3. PIPELINE-STATE.json `status=complete` and `pipeline_step=accepted` for
   ACCEPTED verdict

## Marker

After validation:
```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_post_accept_actions" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_post_accept_actions.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 7_post_accept_actions 2>/dev/null || true
```

## After cleanup

Emit `accept.completed` event (runtime_contract requirement). The Stop
hook verifies all 17 step markers are present + UAT.md content_min_bytes
satisfied + .uat-responses.json present + Verdict line matches.
