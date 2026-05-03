---
name: vg:migrate-state
description: Detect + backfill phase state drift (missing step markers) after VG harness upgrades
argument-hint: "[phase] [--scan] [--apply-all] [--dry-run] [--json]"
allowed-tools:
  - Bash
  - Read
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "migrate_state.scanned"
    - event_type: "migrate_state.applied"
---

<objective>
Repair phase state drift introduced by VG harness upgrades. When a skill
adds new `<step>` blocks (or wires `mark-step` where it wasn't wired
before), phases that already ran the OLD skill miss the new markers.
`/vg:accept` then BLOCKs even though the pipeline actually ran end-to-end.

This command detects + backfills missing markers based on artifact
evidence (PLAN.md, REVIEW-FEEDBACK.md, SANDBOX-TEST.md, etc.). Idempotent.
Companion to Tier B (`.contract-pins.json` written at `/vg:scope`) which
prevents future drift; this command repairs legacy phases that pre-date
the pin mechanism.

Drift is detected per (phase, command) pair:
- Read step list from `.claude/commands/vg/{cmd}.md`
- Check artifact evidence (e.g. PLAN.md proves `/vg:blueprint` ran)
- If evidence present + markers missing → drift candidate
- If no evidence → skip (don't fabricate markers for commands that never ran)

**Auto-invocation by Stop hook (v2.8.3 hybrid recovery):**
This script is also invoked automatically by `vg-verify-claim.py` (Stop
hook) when run-complete BLOCKs purely on `must_touch_markers` AND the
same run_id has hit drift ≥ 2 times in the session. The hook calls
`migrate-state.py {phase} --apply` and retries run-complete; on retry
PASS, the session approves with telemetry event `hook.marker_drift_recovered`.
Manual invocation remains the canonical path — auto-invoke is a safety
net for skill-cache restart cycles, not a substitute for AI discipline.
</objective>

<process>

<step name="0_session_lifecycle">
Standard session banner + EXIT trap. No state mutation.

```bash
PHASE_NUMBER="${PHASE_NUMBER:-migrate-state}"
mkdir -p ".vg/.tmp"
```
</step>

<step name="1_parse_args">
Parse positional + flag arguments.

```bash
PHASE_ARG=""
SCAN=0
APPLY_ALL=0
DRY_RUN=0
JSON=0
for arg in $ARGUMENTS; do
  case "$arg" in
    --scan)        SCAN=1 ;;
    --apply-all)   APPLY_ALL=1 ;;
    --dry-run)     DRY_RUN=1 ;;
    --json)        JSON=1 ;;
    --*)           echo "⛔ Unknown flag: $arg" >&2; exit 2 ;;
    *)             PHASE_ARG="$arg" ;;
  esac
done

# Default: --scan if no positional + no apply-all
if [ -z "$PHASE_ARG" ] && [ $APPLY_ALL -eq 0 ] && [ $SCAN -eq 0 ]; then
  SCAN=1
fi
```
</step>

<step name="2_run_migrate">
Delegate to `migrate-state.py`. Script handles scan/apply/dry-run logic.

```bash
ARGS=()
[ -n "$PHASE_ARG" ] && ARGS+=("$PHASE_ARG")
[ $SCAN -eq 1 ]      && ARGS+=("--scan")
[ $APPLY_ALL -eq 1 ] && ARGS+=("--apply-all")
[ $DRY_RUN -eq 1 ]   && ARGS+=("--dry-run")
[ $JSON -eq 1 ]      && ARGS+=("--json")

"${PYTHON_BIN:-python3}" .claude/scripts/migrate-state.py "${ARGS[@]}"
RC=$?

# Emit telemetry
EVENT_TYPE="migrate_state.scanned"
[ $APPLY_ALL -eq 1 ] || ([ -n "$PHASE_ARG" ] && [ $DRY_RUN -eq 0 ]) && \
  EVENT_TYPE="migrate_state.applied"

PAYLOAD=$(printf '{"phase":"%s","mode":"%s","exit":%d}' \
  "${PHASE_ARG:-all}" \
  "$([ $DRY_RUN -eq 1 ] && echo dry-run || echo apply)" \
  "$RC")
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "$EVENT_TYPE" --payload "$PAYLOAD" >/dev/null 2>&1 || true
```

Exit codes:
- 0 → no drift OR migration applied successfully
- 1 → drift detected (--scan/--dry-run only)
- 2 → invalid args / phase not found / IO error
</step>

<step name="3_complete">
Self-mark final step.

```bash
mkdir -p ".vg/.step-markers/migrate-state" 2>/dev/null
touch ".vg/.step-markers/migrate-state/3_complete.done"
```
</step>

</process>

<success_criteria>
- `--scan` produces a project-wide drift table without writing anything
- `--apply` (or `{phase}` shorthand) backfills missing markers based on artifact evidence
- Single OD entry per applied phase (not per marker — prevents register bloat)
- Idempotent: re-running on a sync'd phase prints "no drift" + zero new OD entries
- `--dry-run` reports what would be backfilled without writing
- Phases without artifact evidence for a command are skipped (no fabricated markers)
</success_criteria>

<usage_examples>

**See project-wide drift before deciding what to fix:**
```
/vg:migrate-state --scan
```
Output: phase × (ran-commands, skipped, missing-markers) table.

**Preview what one phase would change:**
```
/vg:migrate-state 7.14.3 --dry-run
```

**Fix one phase + log audit trail:**
```
/vg:migrate-state 7.14.3
```

**Batch fix every phase with drift:**
```
/vg:migrate-state --apply-all
```

**Pipe machine-readable scan into other tooling:**
```
/vg:migrate-state --scan --json | jq '.scan[] | select(.totals.missing_markers > 0).phase'
```

</usage_examples>

<related>
- `marker-migrate.py` — one-time legacy fix for empty marker files (different drift class)
- `verify-step-markers.py` — gate that detects drift at `/vg:accept` time
- `.vg/OVERRIDE-DEBT.md` — schema-versioned audit trail
- Tier B (`/vg:scope` writes `.contract-pins.json`) — prevents future drift
</related>
