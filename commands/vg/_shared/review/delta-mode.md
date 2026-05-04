# review delta-mode (STEP — phaseP_delta, hotfix profile only)

Single step `phaseP_delta` covers `REVIEW_MODE=delta` (hotfix profile).
Short-circuits the classic Phase 1-4 pipeline; instead verifies that the
hotfix delta touches the parent phase's failed goals (per-goal overlap).

vg-load convention: parent phase artifacts (PARENT_DIR/GOAL-COVERAGE-MATRIX.md,
SPECS.md) are read via grep/regex extraction — those reads do NOT enter
AI context. If a downstream blueprint re-plan is needed (orthogonal
hotfix override path), the orchestrator should reach those artifacts via
`vg-load --phase ${PARENT_REF} --artifact <plan|contracts|goals>`.

---

## STEP — phaseP_delta

<step name="phaseP_delta" mode="delta">
## Review mode: delta (P5, v1.9.2 — OHOK Batch 2 B5: real verification)

**Runs when `REVIEW_MODE=delta` (hotfix profile).**

**Previous behavior (performative):** wrote "Verdict: PASS" stub without actually verifying hotfix touches parent failures. Hotfix could ship completely untested. OHOK Batch 2 B5 replaces stub with per-goal verification loop.

Logic: hotfix patches a parent phase. Review MUST:
- (a) Find parent's failed/blocked goals in GOAL-COVERAGE-MATRIX
- (b) For each failed goal, check if hotfix commits touch files that were implicated in the failure (via commit paths ∩ parent phase commits for that goal)
- (c) Fail build if any critical failed goal is NOT covered by hotfix delta — ship would regress

```bash
if [ "$REVIEW_MODE" != "delta" ]; then
  echo "↷ Skipping phaseP_delta (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Resolve parent phase
  PARENT_REF=$(grep -E '^\*\*Parent phase:\*\*|^parent_phase:' "$PHASE_DIR/SPECS.md" 2>/dev/null | \
               sed -E 's/.*(Parent phase:\*\*|parent_phase:)\s*//' | awk '{print $1}' | head -1)
  if [ -z "$PARENT_REF" ]; then
    echo "⛔ Hotfix profile but no parent_phase in SPECS.md — cannot derive delta context" >&2
    exit 1
  fi
  PARENT_DIR=$(ls -d "${PHASES_DIR}/${PARENT_REF}"* 2>/dev/null | head -1)
  if [ -z "$PARENT_DIR" ]; then
    echo "⛔ Parent phase dir not found for ref '${PARENT_REF}'" >&2
    exit 1
  fi
  PARENT_MATRIX="${PARENT_DIR}/GOAL-COVERAGE-MATRIX.md"
  echo "▸ Delta review: parent=${PARENT_REF} → ${PARENT_DIR}"

  # 2. Extract parent failed/blocked goals (actionable subset — UNREACHABLE/INFRA_PENDING
  #    are parent-domain issues hotfix can't resolve, exclude from coverage gate)
  FAILED_GOALS=""
  if [ -f "$PARENT_MATRIX" ]; then
    FAILED_GOALS=$(grep -E '\|[[:space:]]*(BLOCKED|FAILED)[[:space:]]*\|' "$PARENT_MATRIX" | \
                   grep -oE 'G-[0-9]+' | sort -u)
    FAILED_COUNT=$([ -z "$FAILED_GOALS" ] && echo 0 || echo "$FAILED_GOALS" | wc -l | tr -d ' ')
    echo "▸ Parent BLOCKED/FAILED goals (${FAILED_COUNT}): $(echo $FAILED_GOALS | tr '\n' ' ')"
  else
    echo "⚠ Parent has no GOAL-COVERAGE-MATRIX — cannot verify delta coverage"
    FAILED_COUNT=0
  fi

  # 3. Extract delta files (changes made in THIS phase — current commits only)
  PHASE_COMMITS=$(git log --format=%H -- "${PHASE_DIR}" 2>/dev/null | head -1)
  BASELINE_SHA=$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD 2>/dev/null)
  DELTA_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
                'apps/**/src/**' 'packages/**/src/**' 'infra/**' 2>/dev/null | sort -u)
  DELTA_COUNT=$([ -z "$DELTA_FILES" ] && echo 0 || echo "$DELTA_FILES" | wc -l | tr -d ' ')

  if [ "$DELTA_COUNT" -eq 0 ]; then
    echo "⛔ Hotfix phase has 0 code files changed (apps/**/src|packages/**/src|infra/**)" >&2
    echo "   Hotfix must modify at least 1 code file to be meaningful." >&2
    echo "   Override: --allow-empty-hotfix (log to override-debt)" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-empty-hotfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "phaseP-delta-empty-hotfix" "${PHASE_NUMBER}" "hotfix has no code delta" "${PHASE_DIR}"
  fi

  # 4. For each failed goal, check if delta files overlap with files parent modified
  #    when the goal was recorded as failing. Proxy: grep parent commits mentioning G-XX
  #    for file paths, check intersection with DELTA_FILES.
  COVERAGE_JSON="${PHASE_DIR}/.delta-coverage.json"
  ${PYTHON_BIN} - "$PARENT_DIR" "$PHASE_DIR" "$COVERAGE_JSON" "$PARENT_REF" <<'PY' || true
import json, re, subprocess, sys
from pathlib import Path

parent_dir, phase_dir, out_path, parent_ref = sys.argv[1:5]
matrix = Path(parent_dir) / "GOAL-COVERAGE-MATRIX.md"

failed = []
if matrix.exists():
    for line in matrix.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r'\|\s*(G-\d+)\s*\|.*\|\s*(BLOCKED|FAILED)\s*\|', line)
        if m:
            failed.append(m.group(1))

# Delta files (current hotfix phase)
try:
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD",
         "--", "apps/**/src/**", "packages/**/src/**", "infra/**"],
        capture_output=True, text=True, timeout=10,
    )
    delta_files = set(f.strip() for f in r.stdout.splitlines() if f.strip())
except Exception:
    delta_files = set()

# Per-goal overlap (CrossAI R6 fix).
# Previously: one global parent file set → any touched parent file false-PASSes
# every failed goal. Now: for each failed goal, find files in parent commits
# that cite that goal_id, compute overlap per-goal.
def _files_for_goal(goal_id: str) -> set[str]:
    """Files changed in parent commits whose message cites `goal_id`.

    Proxy for "files involved in this goal's implementation/failure". Limits
    by default to code paths. Falls back to empty set if grep yields nothing
    (goal may have no associated commit — e.g., goal added but never worked on).
    """
    try:
        r = subprocess.run(
            ["git", "log", f"--grep={goal_id}", "--name-only", "--format=",
             "--", str(parent_dir), "apps", "packages", "infra"],
            capture_output=True, text=True, timeout=10,
        )
        return {
            ln.strip() for ln in r.stdout.splitlines()
            if ln.strip() and any(
                ln.startswith(p) for p in ("apps/", "packages/", "infra/")
            )
        }
    except Exception:
        return set()

per_goal: dict[str, dict] = {}
parent_files: set[str] = set()
goals_covered = 0
goals_orthogonal = 0

for g in failed:
    gf = _files_for_goal(g)
    parent_files |= gf
    ovl = sorted(gf & delta_files)
    covered = bool(ovl)
    if covered:
        goals_covered += 1
    elif gf:
        # Goal has known files but none overlap with delta — orthogonal
        goals_orthogonal += 1
    per_goal[g] = {
        "parent_files": sorted(gf),
        "parent_files_count": len(gf),
        "overlap_files": ovl,
        "overlap_count": len(ovl),
        "covered": covered,
        "has_goal_commits": bool(gf),
    }

overlap = sorted(parent_files & delta_files)
coverage_pct = (len(overlap) / len(parent_files) * 100) if parent_files else 0

out = {
    "parent_ref": parent_ref,
    "failed_goals": failed,
    "parent_files_count": len(parent_files),
    "delta_files_count": len(delta_files),
    "overlap_files": overlap,
    "overlap_count": len(overlap),
    "coverage_pct_of_parent": round(coverage_pct, 1),
    "per_goal": per_goal,
    "goals_covered": goals_covered,
    "goals_orthogonal": goals_orthogonal,
    "goals_no_commits": sum(1 for d in per_goal.values() if not d["has_goal_commits"]),
}
Path(out_path).write_text(json.dumps(out, indent=2))
print(f"✓ delta coverage: {goals_covered}/{len(failed)} failed goals have file overlap "
      f"({goals_orthogonal} orthogonal, {out['goals_no_commits']} unmapped); "
      f"total overlap {len(overlap)}/{len(parent_files)} files")
PY

  # 5. Gate: per-goal coverage (CrossAI R6 fix).
  GOALS_COVERED=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_covered',0))" 2>/dev/null || echo 0)
  GOALS_ORTHOGONAL=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_orthogonal',0))" 2>/dev/null || echo 0)
  GOALS_UNMAPPED=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_no_commits',0))" 2>/dev/null || echo 0)

  if [ "${FAILED_COUNT:-0}" -gt 0 ] && [ "${GOALS_ORTHOGONAL:-0}" -gt 0 ]; then
    echo "⛔ ${GOALS_ORTHOGONAL} of ${FAILED_COUNT} failed parent goal(s) have known commits but delta touches NONE of their files." >&2
    echo "   Covered:   ${GOALS_COVERED}/${FAILED_COUNT}" >&2
    echo "   Orthogonal: ${GOALS_ORTHOGONAL}/${FAILED_COUNT} ← hotfix does not address these" >&2
    echo "   Unmapped:  ${GOALS_UNMAPPED}/${FAILED_COUNT} (no parent commits cite these goals)" >&2
    echo "   Delta files: ${DELTA_COUNT}" >&2
    echo "   Options:" >&2
    echo "     (a) Ensure hotfix edits files involved in each failed goal" >&2
    echo "     (b) /vg:scope ${PHASE_NUMBER} — re-scope if truly unrelated" >&2
    echo "     (c) --allow-orthogonal-hotfix override (debt logged, hotfix ships without per-goal coverage)" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-orthogonal-hotfix" "${PHASE_NUMBER}" "review.goal-coverage" \
        "${GOALS_ORTHOGONAL}/${FAILED_COUNT} failed goals uncovered per-goal — hotfix delta orthogonal to failed goals" \
        "review-goal-coverage"
  fi

  # Preserve legacy OVERLAP_COUNT var for downstream consumers
  OVERLAP_COUNT=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}'))['overlap_count'])" 2>/dev/null || echo 0)

  # 6. Write matrix with actual per-goal delta-overlap status
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PARENT_REF" "$COVERAGE_JSON" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

out_path, phase, parent_ref, cov_json = sys.argv[1:5]
cov = json.loads(Path(cov_json).read_text(encoding="utf-8")) if Path(cov_json).exists() else {}

failed = cov.get("failed_goals", [])
overlap = cov.get("overlap_files", [])
delta_count = cov.get("delta_files_count", 0)
parent_files_count = cov.get("parent_files_count", 0)
coverage_pct = cov.get("coverage_pct_of_parent", 0)
per_goal = cov.get("per_goal", {})
goals_covered = cov.get("goals_covered", 0)
goals_orthogonal = cov.get("goals_orthogonal", 0)
goals_no_commits = cov.get("goals_no_commits", 0)

# Decide verdict using PER-GOAL coverage (CrossAI R6 fix).
if failed and goals_orthogonal > 0:
    verdict = (f"BLOCK ({goals_orthogonal}/{len(failed)} failed goals orthogonal — "
               f"hotfix doesn't touch their files)")
elif failed and goals_covered == 0 and goals_no_commits == len(failed):
    verdict = (f"FLAG (all {len(failed)} failed goals have no parent commits — "
               f"cannot verify per-goal coverage; /vg:test must re-verify each)")
elif failed and goals_covered > 0:
    verdict = (f"PASS ({goals_covered}/{len(failed)} failed goals have file overlap; "
               f"{goals_no_commits} unmapped deferred to /vg:test)")
elif not failed:
    verdict = "PASS (parent had no failed goals; delta review defers full goal re-check to /vg:test)"
else:
    verdict = "PASS (no parent matrix found; /vg:test will handle regression)"

lines = [
    f"# Goal Coverage Matrix — Phase {phase} (hotfix delta)",
    "",
    f"**Profile:** hotfix  ",
    f"**Parent phase:** {parent_ref}  ",
    f"**Source:** parent GOAL-COVERAGE-MATRIX + git delta vs HEAD~1  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    "",
    "## Parent failed goals (per-goal overlap)",
    "",
]
if failed:
    lines.append("| Goal | Status | Parent files | Overlap | Verdict |")
    lines.append("|------|--------|--------------|---------|---------|")
    for g in failed:
        pg = per_goal.get(g, {})
        pf_count = pg.get("parent_files_count", 0)
        ov_count = pg.get("overlap_count", 0)
        if pg.get("covered"):
            mark = f"COVERED ({ov_count}/{pf_count})"
        elif pg.get("has_goal_commits"):
            mark = f"ORTHOGONAL (0/{pf_count})"
        else:
            mark = "UNMAPPED (no parent commits cite goal)"
        lines.append(f"| {g} | BLOCKED/FAILED (parent) | {pf_count} | {ov_count} | {mark} |")
else:
    lines.append("_no parent failed/blocked goals found_")
lines += [
    "",
    "## Delta changes",
    "",
    f"**Files changed (code paths):** {delta_count}",
    f"**Overlap with parent files:** {len(overlap)}/{parent_files_count} ({coverage_pct:.1f}%)",
    "",
]
if overlap:
    lines.append("Sample overlapping files:")
    for f in overlap[:10]:
        lines.append(f"- `{f}`")
lines += [
    "",
    "## Gate",
    "",
    f"**Verdict:** {verdict}",
    "",
]
Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f"✓ GOAL-COVERAGE-MATRIX.md written — verdict: {verdict.split(' (')[0]}")
PY

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_delta" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_delta.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_delta 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.phaseP_delta_verified" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"parent\":\"${PARENT_REF}\",\"overlap_count\":${OVERLAP_COUNT:-0},\"failed_count\":${FAILED_COUNT:-0}}" >/dev/null 2>&1 || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Delta checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_delta_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  exit 0
fi
```
</step>
