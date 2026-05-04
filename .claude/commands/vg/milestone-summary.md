---
name: vg:milestone-summary
description: Generate aggregate report across all phases in a milestone — phase status, goal coverage, security posture, override debt, companion artifact links
argument-hint: "<milestone-id> [--phases <range>] [--out <path>] [--json]"
allowed-tools:
  - Bash
  - Read
  - Write
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "milestone_summary.generated"
---

<objective>
Read-only aggregator across every phase that belongs to milestone `{M}`. Produces `.vg/milestones/{M}/MILESTONE-SUMMARY.md` containing:

- Phase pipeline status (specs/plan/build/review/test/UAT) per phase
- Goal coverage rolled up by priority (critical/important/nice-to-have)
- Decisions inventory (D-XX namespace count per phase)
- Security register snapshot (open threats by severity)
- Override-debt entries carried forward
- Companion artifact links (security-audit-*.md, SECURITY-PENTEST-CHECKLIST.md, STRIX-ADVISORY.md)
- Timeline (first commit → last commit per milestone scope)

Phase membership resolved from ROADMAP.md `## Milestone {M}` section, with fallback to all phases if no milestone section found (single-milestone projects).

This is a **non-mutating** view — re-runnable after any artifact change. Does NOT verify phase acceptance gates; for that use `/vg:complete-milestone`.
</objective>

<process>

<step name="0_args">
Parse arguments:
- Positional `{milestone}` — required (e.g. `M1`)
- `--phases <range>` — explicit phase range (e.g. `3-7`), overrides ROADMAP resolution
- `--out <path>` — override output location
- `--json` — print summary payload to stdout instead of human prose
- `--quiet` — suppress informational stdout (still writes file)

```bash
MILESTONE="${1:-}"
if [ -z "$MILESTONE" ]; then
  echo "⛔ Usage: /vg:milestone-summary <milestone-id> [--phases <range>] [--out <path>] [--json]"
  exit 1
fi
shift
EXTRA_ARGS=( "$@" )
```
</step>

<step name="1_invoke_aggregator">
```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/telemetry.sh" 2>/dev/null || true

emit_telemetry_v2 "milestone_summary.started" "" "milestone-summary" \
  "milestone_aggregator" "INFO" "{\"milestone\":\"${MILESTONE}\"}" 2>/dev/null || true

${PYTHON_BIN:-python3} .claude/scripts/generate-milestone-summary.py \
  --milestone "$MILESTONE" "${EXTRA_ARGS[@]}"
RC=$?

if [ "$RC" -eq 0 ]; then
  emit_telemetry_v2 "milestone_summary.generated" "" "milestone-summary" \
    "milestone_aggregator" "PASS" "{\"milestone\":\"${MILESTONE}\"}" 2>/dev/null || true
else
  emit_telemetry_v2 "milestone_summary.failed" "" "milestone-summary" \
    "milestone_aggregator" "FAIL" "{\"milestone\":\"${MILESTONE}\",\"rc\":${RC}}" 2>/dev/null || true
fi

exit $RC
```
</step>

</process>

<success_criteria>
- `.vg/milestones/{M}/MILESTONE-SUMMARY.md` written (or `--out` path if specified)
- Phase pipeline status reflects current artifact presence per phase
- Goal coverage table includes critical/important/nice-to-have buckets
- Companion artifact links resolve to existing files in the milestone dir
- Re-runnable: subsequent invocations regenerate from fresh artifact state
- Telemetry events emitted (`milestone_summary.started` + `milestone_summary.generated`)
</success_criteria>

<dependencies>
- `scripts/generate-milestone-summary.py` (this command's engine)
- `.vg/phases/{N}/{SPECS,PLAN,SUMMARY,UAT,TEST-GOALS,CONTEXT}.md` (read inputs)
- `.vg/ROADMAP.md` (milestone → phase resolution)
- `.vg/SECURITY-REGISTER.md` (optional — security posture roll-up)
- `.vg/OVERRIDE-DEBT.md` (optional — debt carryover count)
</dependencies>

<see_also>
- `/vg:complete-milestone` — uses this aggregator as part of milestone closeout
- `/vg:security-audit-milestone` — produces companion artifacts referenced here
- `/vg:progress` — per-phase status (single-phase view, complementary)
</see_also>
