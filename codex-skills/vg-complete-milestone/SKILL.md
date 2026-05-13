---
name: vg:complete-milestone
description: Close out a milestone — verify all phases accepted, run security audit + summary, archive phase dirs, advance STATE.md to next milestone
argument-hint: "<milestone-id> [--check] [--allow-open-critical=<reason>] [--allow-open-override-debt=<reason>] [--no-archive]"
allowed-tools:
  - Bash
  - Read
  - Write
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "complete_milestone.started"
    - event_type: "complete_milestone.completed"
  must_touch_markers:
    - 0_args
    - 1_telemetry_started
    - 2_gate_check
    - 3_security_audit
    - 4_milestone_summary
    - 5_archive_phases
    - 6_finalize_state
    - 7_atomic_commit
---

<objective>
Atomic milestone closeout. Orchestrates the existing milestone-level pieces into a single command:

1. **Gate check** — every phase resolved for the milestone has UAT.md (= accepted), no critical OPEN threats, no critical OVERRIDE-DEBT entries unresolved.
2. **Security audit** — invokes `generate-strix-advisory.py --milestone-gate` (via `/vg:security-audit-milestone`) so decay + composite + Strix-advisory steps run with the milestone gate active.
3. **Aggregate summary** — invokes `/vg:milestone-summary` to refresh the cross-phase report.
4. **Archive phase dirs** — moves `.vg/phases/{N}/` (for phases in this milestone) into `.vg/milestones/{M}/phases/{N}/` via `git mv` to preserve history. Skip with `--no-archive` if you want phases hot-readable for amendments.
5. **Advance STATE.md** — flips `current_milestone` to `M{N+1}` and appends `milestones_completed[]` entry.
6. **Atomic commit** — single commit with all milestone artifacts + state transition. Subject: `milestone(close): {M} — {phase-count} phases archived`.

Pass `--check` to dry-run the gate without mutations. Override blockers with `--allow-open-critical=<reason>` or `--allow-open-override-debt=<reason>` (logs to OVERRIDE-DEBT for next-milestone triage).
</objective>

<process>

<step name="0_args">
```bash
MILESTONE="${1:-}"
if [ -z "$MILESTONE" ]; then
  echo "⛔ Usage: /vg:complete-milestone <milestone-id> [--check] [--allow-open-critical=<reason>] [--no-archive]"
  exit 1
fi
shift

CHECK_ONLY=false
NO_ARCHIVE=false
ALLOW_CRITICAL=""
ALLOW_DEBT=""

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=true ;;
    --no-archive) NO_ARCHIVE=true ;;
    --allow-open-critical=*) ALLOW_CRITICAL="${arg#*=}" ;;
    --allow-open-override-debt=*) ALLOW_DEBT="${arg#*=}" ;;
    *) echo "⚠ Unknown arg: $arg (ignored)" ;;
  esac
done
```
</step>

<step name="1_telemetry_started">
```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/telemetry.sh" 2>/dev/null || true
emit_telemetry_v2 "complete_milestone.started" "" "complete-milestone" \
  "milestone_orchestrator" "INFO" "{\"milestone\":\"${MILESTONE}\",\"check_only\":${CHECK_ONLY}}" 2>/dev/null || true

# F2 Batch 14: vg-orchestrator run-start — register active run so Stop hook
# sees contract and can enforce must_touch_markers (prevents silent early-exit).
_VG_ORCH="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator"
"${PYTHON_BIN:-python3}" "$_VG_ORCH" run-start "vg:complete-milestone" "milestone-level" "${MILESTONE}" >/dev/null 2>&1 || true
```
</step>

<step name="2_gate_check">
```bash
echo "━━━ Step 1 — Milestone gate check ━━━"

GATE_ARGS=( "--milestone" "$MILESTONE" )
[ -n "$ALLOW_CRITICAL" ] && GATE_ARGS+=( "--allow-open-critical=$ALLOW_CRITICAL" )
[ -n "$ALLOW_DEBT" ] && GATE_ARGS+=( "--allow-open-override-debt=$ALLOW_DEBT" )

${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py "${GATE_ARGS[@]}" --check
GATE_RC=$?

if [ "$GATE_RC" -ne 0 ]; then
  echo ""
  echo "Gate failed. Resolve blockers above, or pass override flags:"
  echo "  --allow-open-critical=\"<reason>\""
  echo "  --allow-open-override-debt=\"<reason>\""
  exit 1
fi

if [ "$CHECK_ONLY" = "true" ]; then
  echo ""
  echo "✓ --check mode — no mutations performed. Re-run without --check to finalize."
  exit 0
fi
```
</step>

<step name="3_security_audit">
```bash
echo ""
echo "━━━ Step 2 — Security audit (milestone gate) ━━━"

# F1 Batch 14: actually invoke generate-strix-advisory.py instead of print-only.
# Probe candidate script locations (VG_SCRIPT_ROOT, VG_HOME, repo-local scripts/).
STRIX=""
for _candidate in \
  "${VG_SCRIPT_ROOT:-}/generate-strix-advisory.py" \
  "${VG_HOME:-$HOME/.vgflow}/scripts/generate-strix-advisory.py" \
  "${REPO_ROOT:-.}/scripts/generate-strix-advisory.py" \
  ".claude/scripts/generate-strix-advisory.py"
do
  if [ -f "$_candidate" ]; then
    STRIX="$_candidate"
    break
  fi
done

if [ -n "$STRIX" ]; then
  echo "  Invoking $STRIX --milestone-gate ..."
  "${PYTHON_BIN:-python3}" "$STRIX" --milestone "$MILESTONE" --milestone-gate ${AUDIT_EXTRA_ARGS:-} || true
else
  echo "  ⚠ generate-strix-advisory.py not found — skipping Strix advisory (review hand-off recommended)"
fi
```
</step>

<step name="4_milestone_summary">
```bash
echo ""
echo "━━━ Step 3 — Milestone summary ━━━"

${PYTHON_BIN:-python3} .claude/scripts/generate-milestone-summary.py --milestone "$MILESTONE"
SUM_RC=$?
if [ "$SUM_RC" -ne 0 ]; then
  echo "⚠ Milestone summary failed (rc=${SUM_RC}) — continuing closeout but inspect manually."
fi
```
</step>

<step name="5_archive_phases">
```bash
echo ""
echo "━━━ Step 4 — Archive phase directories ━━━"

if [ "$NO_ARCHIVE" = "true" ]; then
  echo "  (--no-archive — phases left in place at .vg/phases/{N}/)"
else
  PHASE_NUMS=$(${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py \
    --milestone "$MILESTONE" --check --json 2>/dev/null \
    | ${PYTHON_BIN:-python3} -c "import json,sys; d=json.load(sys.stdin); print(' '.join(p.split('-',1)[0] for p in d['phases_resolved']))")

  ARCHIVE_DIR=".vg/milestones/$MILESTONE/phases"
  mkdir -p "$ARCHIVE_DIR"

  ARCHIVED=0
  for phase_num in $PHASE_NUMS; do
    SRC=".vg/phases/${phase_num}"
    if [ ! -d "$SRC" ]; then
      # try suffixed name
      SRC=$(find .vg/phases -maxdepth 1 -type d -name "${phase_num}-*" | head -1)
    fi
    if [ -n "$SRC" ] && [ -d "$SRC" ]; then
      git mv "$SRC" "${ARCHIVE_DIR}/$(basename "$SRC")" 2>/dev/null || \
        mv "$SRC" "${ARCHIVE_DIR}/$(basename "$SRC")"
      echo "  ✓ Archived $SRC → ${ARCHIVE_DIR}/$(basename "$SRC")"
      ARCHIVED=$((ARCHIVED + 1))
    fi
  done
  echo "  → $ARCHIVED phase dirs archived"
fi
```
</step>

<step name="6_finalize_state">
```bash
echo ""
echo "━━━ Step 5 — Advance STATE.md + write completion marker ━━━"

FINAL_ARGS=( "--milestone" "$MILESTONE" "--finalize" )
[ -n "$ALLOW_CRITICAL" ] && FINAL_ARGS+=( "--allow-open-critical=$ALLOW_CRITICAL" )
[ -n "$ALLOW_DEBT" ] && FINAL_ARGS+=( "--allow-open-override-debt=$ALLOW_DEBT" )

${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py "${FINAL_ARGS[@]}"
FINAL_RC=$?

if [ "$FINAL_RC" -ne 0 ]; then
  echo "⛔ Finalize failed (rc=${FINAL_RC}) — STATE.md NOT advanced. Inspect logs."
  exit 1
fi
```
</step>

<step name="7_atomic_commit">
```bash
echo ""
echo "━━━ Step 6 — Atomic commit ━━━"

PHASE_COUNT=$(ls -1 .vg/milestones/${MILESTONE}/phases/ 2>/dev/null | wc -l | tr -d ' ')
COMMIT_MSG="milestone(close): ${MILESTONE} — ${PHASE_COUNT} phases archived"

git add .vg/STATE.md .vg/milestones/${MILESTONE}/ 2>/dev/null

if git diff --cached --quiet; then
  echo "  (nothing staged — skipping commit)"
else
  git commit -m "$COMMIT_MSG" 2>&1 | tail -5
fi

emit_telemetry_v2 "complete_milestone.completed" "" "complete-milestone" \
  "milestone_orchestrator" "PASS" \
  "{\"milestone\":\"${MILESTONE}\",\"phases\":${PHASE_COUNT}}" 2>/dev/null || true

echo ""
echo "✓ Milestone ${MILESTONE} closed."
echo "  Next: /vg:project --milestone   # define milestone scope for current_milestone (advanced)"
echo "  Then: /vg:roadmap               # add phases for the new milestone"
```
</step>

</process>

<success_criteria>
- All resolved phases were UAT-accepted before close (gate enforced)
- Critical OPEN security threats were either resolved or explicitly waived (override-debt logged)
- Critical OVERRIDE-DEBT entries were either resolved or explicitly deferred (logged)
- `.vg/milestones/{M}/MILESTONE-SUMMARY.md` regenerated
- `.vg/milestones/{M}/.completed` marker JSON written with vgflow version + timestamp
- `.vg/STATE.md` advanced (`current_milestone` incremented, `milestones_completed[]` appended)
- Phase dirs archived under `.vg/milestones/{M}/phases/{N}/` (unless `--no-archive`)
- Atomic commit created with `milestone(close):` subject prefix
- Telemetry events emitted (started + completed)
</success_criteria>

<dependencies>
- `scripts/complete-milestone.py` — gate + state engine
- `scripts/generate-milestone-summary.py` — summary aggregator
- `commands/vg/security-audit-milestone.md` — security gate (Step 4 already wires `--milestone-gate`)
- `git` (for archive via `git mv` to preserve history)
</dependencies>

<see_also>
- `/vg:security-audit-milestone` — runs decay + composite + Strix advisory
- `/vg:milestone-summary` — standalone summary view (re-runnable)
- `/vg:project --milestone` — append next milestone scope to PROJECT.md
- `/vg:roadmap` — derive phases for the next milestone
</see_also>
