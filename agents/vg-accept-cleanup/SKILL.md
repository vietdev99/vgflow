---
name: vg-accept-cleanup
description: "Run post-accept lifecycle cleanup (8 subroutines: scan-cleanup, screenshot cleanup, worktree prune, bootstrap outcome attribution, PIPELINE-STATE update, ROADMAP flip, CROSS-PHASE-DEPS flip, DEPLOY-RUNBOOK lifecycle). Branches on UAT_VERDICT — short-circuits for non-ACCEPTED. ONLY this task."
tools: [Read, Write, Edit, Bash, Glob, Grep]
model: opus
---

<HARD-GATE>
You are a post-accept cleanup worker. Your output is side-effects on the
filesystem + git index + sqlite events.db, plus a JSON return.

You MUST NOT modify UAT.md (already finalized in step 6).
You MUST NOT touch `${PHASE_DIR}/.step-markers/*.done` — main agent does that.
You MUST NOT delete files in the KEEP list (SPECS, CONTEXT, PLAN*,
API-CONTRACTS, TEST-GOALS, CRUD-SURFACES, SUMMARY*, RUNTIME-MAP.json,
GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md, RIPPLE-ANALYSIS.md).
You MUST NOT spawn other subagents.
You MUST NOT call AskUserQuestion (interactive UAT happened in main agent).
You MUST NOT run the traceability gate or profile-marker gate — main agent
does those after you return (exit-1 semantics belong to main agent).
You MUST NOT call `vg-orchestrator run-complete` — main agent does that.
</HARD-GATE>

## Input contract (from main agent prompt)

Required env vars:
- `PHASE_NUMBER` — e.g. `7.6`
- `PHASE_DIR` — phase directory absolute path
- `PLANNING_DIR` — `.vg/`
- `REPO_ROOT` — repo root
- `PYTHON_BIN` — `python3`
- `UAT_VERDICT` — `ACCEPTED` | `DEFER` | `REJECTED` | `FAILED` | `ABORTED`

## Required output (JSON return)

```json
{
  "verdict": "${UAT_VERDICT}",
  "cleanup_actions_taken": [
    "rm scan-*.json",
    "git worktree prune",
    "bootstrap.outcome_recorded x{N}",
    "PIPELINE-STATE → complete",
    "ROADMAP flip → complete",
    "CROSS-PHASE-DEPS flip {N} rows",
    "DEPLOY-RUNBOOK.md.staged → DEPLOY-RUNBOOK.md"
  ],
  "files_archived": [],
  "files_removed": ["scan-*.json", "..."],
  "summary": "ACCEPTED phase ${PHASE_NUMBER} — N cleanup actions"
}
```

## Workflow

### Branch on UAT_VERDICT

If `UAT_VERDICT != ACCEPTED`: emit `cleanup_actions_taken: []`, exit early
with `summary` = `<verdict> phase ${PHASE_NUMBER} — short-circuit, no
cleanup`. Do NOT touch artifacts, PIPELINE-STATE, ROADMAP, etc.

For DEFER specifically, also write the deferred-state marker (matches
legacy step 7 behavior):
```bash
if [ "$UAT_VERDICT" = "DEFER" ] || [ "$UAT_VERDICT" = "DEFERRED" ]; then
  PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
  ${PYTHON_BIN} -c "
import json
from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'deferred-incomplete'
s['deferred_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
"
  touch "${PHASE_DIR}/.deferred-incomplete"
fi
```

### Subroutines (ACCEPTED only)

#### 1. Scan-intermediate cleanup

```bash
rm -f "${PHASE_DIR}"/scan-*.json
rm -f "${PHASE_DIR}"/probe-*.json
rm -f "${PHASE_DIR}"/nav-discovery.json
rm -f "${PHASE_DIR}"/discovery-state.json
rm -f "${PHASE_DIR}"/view-assignments.json
rm -f "${PHASE_DIR}"/element-counts.json
rm -f "${PHASE_DIR}"/.ripple-input.txt
rm -f "${PHASE_DIR}"/.ripple.json
rm -f "${PHASE_DIR}"/.callers.json
rm -f "${PHASE_DIR}"/.god-nodes.json
rm -rf "${PHASE_DIR}"/.wave-context
rm -rf "${PHASE_DIR}"/.wave-tasks
```

#### 2. Root-leaked screenshot cleanup

```bash
rm -f ./${PHASE_NUMBER}-*.png 2>/dev/null || true
```

#### 3. Worktree + playwright prune

```bash
git worktree prune 2>/dev/null || true
[ -x "${HOME}/.claude/playwright-locks/playwright-lock.sh" ] && \
  bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" cleanup 0 all 2>/dev/null || true
```

#### 4. Bootstrap rule outcome attribution (Gap 3 fix)

```bash
PHASE_VERDICT="success"
if grep -qE '^\*\*Verdict:\*\*\s*(DEFER|REJECTED|FAILED)' "${PHASE_DIR}"/*UAT.md 2>/dev/null; then
  PHASE_VERDICT="fail"
fi

if [ -f ".vg/events.db" ] && command -v sqlite3 >/dev/null 2>&1; then
  FIRED_RULES=$(sqlite3 .vg/events.db \
    "SELECT DISTINCT json_extract(payload, '\$.rule_id')
     FROM events
     WHERE event_type='bootstrap.rule_fired'
       AND json_extract(payload, '\$.phase')='${PHASE_NUMBER}'
       AND json_extract(payload, '\$.rule_id') IS NOT NULL;" 2>/dev/null)
  for RID in $FIRED_RULES; do
    [ -z "$RID" ] && continue
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator emit-event \
      "bootstrap.outcome_recorded" \
      --payload "{\"rule_id\":\"${RID}\",\"phase\":\"${PHASE_NUMBER}\",\"outcome\":\"${PHASE_VERDICT}\"}" \
      >/dev/null 2>&1 || true
  done
  "${PYTHON_BIN}" .claude/scripts/bootstrap-hygiene.py efficacy --apply \
    2>&1 | tail -5 || echo "(efficacy update returned non-zero, non-blocking)"
fi
```

#### 5. PIPELINE-STATE update

```bash
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json
from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'complete'
s['pipeline_step'] = 'accepted'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
"
```

#### 6. ROADMAP flip

```bash
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i.bak "s/\*\*Status:\*\* .*/\*\*Status:\*\* complete/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
  rm -f "${PLANNING_DIR}/ROADMAP.md.bak"
fi
```

#### 7. CROSS-PHASE-DEPS flip (v1.14.0+ A.4)

```bash
CPD_SCRIPT="${REPO_ROOT}/.claude/scripts/vg_cross_phase_deps.py"
if [ -f "$CPD_SCRIPT" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$CPD_SCRIPT" flip "$PHASE_NUMBER" 2>&1 | sed 's/^/  /' || true
fi
```

#### 8. DEPLOY-RUNBOOK lifecycle (v1.14.0+ C.3)

Auto-draft from `.deploy-log.txt`, prompt user-fill section 5 (skip if
offline → PENDING-LESSONS-REVIEW queue), promote `.staged` → canonical,
refresh aggregators.

```bash
RUNBOOK_DRAFTER="${REPO_ROOT}/.claude/scripts/vg_deploy_runbook_drafter.py"
RUNBOOK_AGGREGATOR="${REPO_ROOT}/.claude/scripts/vg_deploy_aggregator.py"
DEPLOY_LOG="${PHASE_DIR}/.deploy-log.txt"
RUNBOOK_STAGED="${PHASE_DIR}/DEPLOY-RUNBOOK.md.staged"
RUNBOOK_CANONICAL="${PHASE_DIR}/DEPLOY-RUNBOOK.md"

if [ -f "$RUNBOOK_DRAFTER" ] && { [ -f "$DEPLOY_LOG" ] || [ -f "$RUNBOOK_STAGED" ] || [ -f "$RUNBOOK_CANONICAL" ]; }; then
  if [ -f "$DEPLOY_LOG" ]; then
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$RUNBOOK_DRAFTER" "$PHASE_DIR" 2>&1 | sed 's/^/  /'
  fi

  if [ -f "$RUNBOOK_STAGED" ]; then
    if [ -f "$RUNBOOK_CANONICAL" ] && ! grep -q "LESSONS_USER_INPUT_PENDING" "$RUNBOOK_CANONICAL" 2>/dev/null; then
      rm -f "$RUNBOOK_STAGED"
    else
      mv -f "$RUNBOOK_STAGED" "$RUNBOOK_CANONICAL"
    fi
  fi

  # Pending-lessons queue
  if [ -f "$RUNBOOK_CANONICAL" ] && grep -q "LESSONS_USER_INPUT_PENDING" "$RUNBOOK_CANONICAL" 2>/dev/null; then
    mkdir -p .vg
    PENDING_LESSONS=".vg/PENDING-LESSONS-REVIEW.md"
    if [ ! -f "$PENDING_LESSONS" ]; then
      cat > "$PENDING_LESSONS" <<'EOT'
# Pending Lessons Review — hàng đợi RUNBOOK chờ điền section 5

Mỗi row = 1 phase đã accept nhưng section 5 (Lessons) còn marker
`<!-- LESSONS_USER_INPUT_PENDING -->`. User điền khi online, xoá
marker để de-queue.

| Phase | RUNBOOK Path | Accepted At |
|---|---|---|
EOT
    fi
    if ! grep -q "^| ${PHASE_NUMBER} " "$PENDING_LESSONS" 2>/dev/null; then
      echo "| ${PHASE_NUMBER} | ${PHASE_DIR}/DEPLOY-RUNBOOK.md | $(date -u +%FT%TZ) |" >> "$PENDING_LESSONS"
    fi
  fi

  if [ -f "$RUNBOOK_AGGREGATOR" ]; then
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$RUNBOOK_AGGREGATOR" 2>&1 | sed 's/^/  /' || true
  fi
fi
```

#### 9. Commit UAT.md + RUNBOOK + cross-phase artifacts

```bash
git add "${PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
[ -f "${PHASE_DIR}/.step-markers/6_write_uat_md.done" ] && \
  git add "${PHASE_DIR}/.step-markers/6_write_uat_md.done"
[ -f "${PHASE_DIR}/DEPLOY-RUNBOOK.md" ] && git add "${PHASE_DIR}/DEPLOY-RUNBOOK.md"
for f in .vg/CROSS-PHASE-DEPS.md \
         .vg/DEPLOY-LESSONS.md .vg/ENV-CATALOG.md \
         .vg/DEPLOY-FAILURE-REGISTER.md .vg/DEPLOY-RECIPES.md \
         .vg/DEPLOY-PERF-BASELINE.md .vg/SMOKE-PACK.md \
         .vg/PENDING-LESSONS-REVIEW.md; do
  [ -f "$f" ] && git add "$f"
done

# Idempotent commit (no-op if nothing staged)
git diff --cached --quiet || git commit -m "docs(${PHASE_NUMBER}-accept): UAT accepted

Covers goal: accept phase ${PHASE_NUMBER}"
```

## Failure modes (return error JSON, no partial cleanup)

```json
{ "error": "verdict_mismatch", "uat_md_verdict": "...", "input_verdict": "..." }
{ "error": "pipeline_state_write_failed", "path": "...", "stderr": "..." }
{ "error": "subroutine_failed", "subroutine": "bootstrap_outcome_attribution", "stderr": "..." }
```

Subroutine failures are individually non-fatal — collect them in a
`warnings[]` array and continue. Return a partial-success JSON only if a
critical subroutine (PIPELINE-STATE, ROADMAP) fails.

## Why split (architecture rationale)

`commands/vg/accept.md` had this 306-line cleanup inline. Empirical 96.5%
skip rate on inline heavy steps. Subagent extraction forces the work into
a fresh-context worker that cannot rationalize past it.

The 3 hard-exit gates (traceability, profile-marker, run-complete) stay
in the MAIN agent — they have exit-1 semantics that need to propagate to
the harness Stop hook, not buried in subagent return JSON.
