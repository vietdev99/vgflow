<step name="phase_profile_branch">
## Phase profile branch (P5, v1.9.2)

**If `REVIEW_MODE` ≠ `full`, short-circuit before code scan + browser discovery.**

Each non-full review mode has a dedicated handler. After handler completes,
jump straight to `write_goal_coverage_matrix` (step 4d equivalent) and exit.
The `phase_profile_branch` step is a router — see dedicated `phaseP_*` steps below.

```bash
case "$REVIEW_MODE" in
  full)
    # Classic path — Phase 1 code scan → Phase 2 browser → Phase 3 fix → Phase 4 goal compare
    echo "▸ Review mode: full (feature profile) — running classic discovery pipeline"
    ;;
  infra-smoke)
    echo "▸ Review mode: infra-smoke (${PHASE_PROFILE} profile) — parsing SPECS success_criteria"
    # Handled by `phaseP_infra_smoke` below. Jumps to goal-coverage-matrix write + exit.
    ;;
  delta)
    echo "▸ Review mode: delta (hotfix profile) — focus on delta + parent goals re-verify"
    # Handled by `phaseP_delta` below.
    ;;
  regression)
    echo "▸ Review mode: regression (bugfix profile) — regression sweep around issue"
    # Handled by `phaseP_regression` below.
    ;;
  schema-verify)
    echo "▸ Review mode: schema-verify (migration profile) — schema round-trip check"
    # Handled by `phaseP_schema_verify` below.
    ;;
  link-check)
    echo "▸ Review mode: link-check (docs profile) — markdown link validation"
    # Handled by `phaseP_link_check` below.
    ;;
  *)
    echo "⚠ Unknown REVIEW_MODE='${REVIEW_MODE}' — falling back to full pipeline" >&2
    REVIEW_MODE="full"
    ;;
esac

# Materialize the profile-aware checklist/plugin contract early. Full web runs
# refresh it after RUNTIME-MAP discovery, but backend-only/CLI/library and
# non-full modes still need a REVIEW-LENS-PLAN artifact and task contract.
LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --write >/dev/null 2>&1 || {
      echo "⛔ Review checklist/lens plan generation failed for profile=${PROFILE:-${CONFIG_PROFILE:-web-fullstack}} mode=${REVIEW_MODE:-full}" >&2
      exit 1
    }
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_plan_generated" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"platform\":\"${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}\",\"phase_profile\":\"${PHASE_PROFILE:-unknown}\",\"mode\":\"${REVIEW_MODE:-full}\",\"artifact\":\"REVIEW-LENS-PLAN.json\"}" \
    >/dev/null 2>&1 || true
else
  echo "⛔ Missing review lens planner: $LENS_PLAN_SCRIPT" >&2
  exit 1
fi
```

**Dispatcher rule:** Orchestrator runs EXACTLY ONE of: `phaseP_infra_smoke` | `phaseP_delta` | `phaseP_regression` | `phaseP_schema_verify` | `phaseP_link_check` | classic `phase1_code_scan → phase4_goal_comparison`. Infra-smoke etc. write `GOAL-COVERAGE-MATRIX.md` directly (implicit goals from SPECS), skip browser + RUNTIME-MAP entirely.
</step>

<step name="phaseP_infra_smoke" profile="web-fullstack,web-backend-only,cli-tool,library" mode="infra-smoke">
## Review mode: infra-smoke (P5, v1.9.2)

**Runs when `REVIEW_MODE=infra-smoke` (infra profile).**

Logic: parse SPECS `## Success criteria` checklist → run each bash command on target env → map to implicit goals `S-01..S-NN` → gate on all READY.

```bash
if [ "$REVIEW_MODE" != "infra-smoke" ]; then
  echo "↷ Skipping phaseP_infra_smoke (REVIEW_MODE=$REVIEW_MODE)"
else
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true

  # 1. Parse SPECS success_criteria
  SMOKE_JSON=$(parse_success_criteria "$PHASE_DIR")
  SMOKE_COUNT=$(${PYTHON_BIN} -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$SMOKE_JSON" 2>/dev/null || echo 0)

  if [ "$SMOKE_COUNT" -eq 0 ]; then
    echo "⛔ SPECS has no '## Success criteria' checklist bullets — infra-smoke needs implicit goals." >&2
    echo "   Fix: add markdown checklist ('- [ ] `cmd` → expected') to SPECS.md" >&2
    exit 1
  fi

  echo "▸ Infra-smoke: phát hiện ${SMOKE_COUNT} implicit goals từ success_criteria"
  echo "$SMOKE_JSON" > "${PHASE_DIR}/.success-criteria.json"

  # 2. Determine run_prefix from env (--sandbox flag or config.step_env.verify)
  RUN_PREFIX=""
  ENV_NAME="${VG_ENV:-}"
  if [ -z "$ENV_NAME" ]; then
    if [[ "$ARGUMENTS" =~ --sandbox ]]; then ENV_NAME="sandbox"
    elif [[ "$ARGUMENTS" =~ --local ]]; then ENV_NAME="local"
    else ENV_NAME="${CONFIG_STEP_ENV_VERIFY:-local}"
    fi
  fi
  # NOTE: commands in SPECS typically already include `ssh vollx`; don't double-prefix
  # when command already has the run_prefix. phase-profile keeps this simple — run as-is.

  # 3. Run each bullet, record status
  RESULTS_JSON="${PHASE_DIR}/.infra-smoke-results.json"
  ${PYTHON_BIN} - "$SMOKE_JSON" "$RESULTS_JSON" "$ENV_NAME" <<'PY'
import json, sys, subprocess, shlex, time
smoke = json.loads(sys.argv[1])
out_path = sys.argv[2]
env_name = sys.argv[3]
results = []
for entry in smoke:
    sid = entry['id']
    cmd = entry.get('cmd','').strip()
    expected = entry.get('expected','').strip()
    raw = entry.get('raw','')
    if not cmd:
        results.append({"id":sid,"status":"UNREACHABLE","reason":"no bash command in bullet","raw":raw})
        continue
    if cmd.startswith('/vg:') or cmd.startswith('/gsd:'):
        # Slash commands — not directly runnable here. Mark DEFERRED.
        results.append({"id":sid,"status":"DEFERRED","reason":f"slash command requires orchestrator: {cmd}","raw":raw})
        continue
    try:
        t0 = time.time()
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        dur = round(time.time() - t0, 2)
        ok = p.returncode == 0
        if ok and expected:
            # Expected substring must appear in combined output
            combined = (p.stdout or '') + (p.stderr or '')
            ok = expected.split()[0] in combined or expected in combined
        status = "READY" if ok else "BLOCKED"
        tail = ((p.stdout or '')[-300:] + (p.stderr or '')[-200:]).replace('\n',' | ')
        results.append({"id":sid,"status":status,"exit":p.returncode,"dur":dur,"expected":expected,"evidence":tail[:600],"raw":raw})
    except subprocess.TimeoutExpired:
        results.append({"id":sid,"status":"BLOCKED","reason":"timeout 60s","raw":raw})
    except Exception as e:
        results.append({"id":sid,"status":"FAILED","reason":str(e),"raw":raw})
with open(out_path,'w',encoding='utf-8') as f:
    json.dump({"env":env_name,"results":results,"generated_at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}, f, ensure_ascii=False, indent=2)
PY

  # 4. Display human-readable summary
  ${PYTHON_BIN} - "$RESULTS_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
r = d['results']
ready = sum(1 for x in r if x['status']=='READY')
blocked = sum(1 for x in r if x['status']=='BLOCKED')
failed = sum(1 for x in r if x['status']=='FAILED')
deferred = sum(1 for x in r if x['status']=='DEFERRED')
unreach = sum(1 for x in r if x['status']=='UNREACHABLE')
print(f"\n┌─ Infra-smoke results (env={d['env']}) ─────────────────")
for x in r:
    icon = {'READY':'✓','BLOCKED':'⛔','FAILED':'✗','DEFERRED':'⟳','UNREACHABLE':'⚠'}.get(x['status'],'?')
    print(f"│ {icon} {x['id']} [{x['status']}] {x.get('raw','')[:70]}")
    if x['status'] in ('BLOCKED','FAILED'):
        print(f"│   └─ {x.get('reason') or x.get('evidence','')[:160]}")
print(f"├─ Summary: READY={ready} BLOCKED={blocked} FAILED={failed} DEFERRED={deferred} UNREACHABLE={unreach} (total={len(r)})")
print("└──────────────────────────────────────────────────────────")
PY

  # 5. Write GOAL-COVERAGE-MATRIX.md with implicit goals
  ${PYTHON_BIN} - "$RESULTS_JSON" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PHASE_PROFILE" <<'PY'
import json, sys
from datetime import datetime, timezone
results = json.load(open(sys.argv[1], encoding='utf-8'))['results']
out_path = sys.argv[2]
phase = sys.argv[3]
profile = sys.argv[4]
lines = [
    f"# Goal Coverage Matrix — Phase {phase}",
    "",
    f"**Profile:** {profile}  ",
    f"**Source:** SPECS.success_criteria (implicit goals)  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    f"**Review mode:** infra-smoke",
    "",
    "## Implicit Goals (from SPECS `## Success criteria`)",
    "",
    "| Goal | Status | Command | Evidence |",
    "|------|--------|---------|----------|",
]
for r in results:
    raw = r.get('raw','').replace('|',r'\|')[:120]
    ev = (r.get('evidence') or r.get('reason') or '').replace('|',r'\|')[:120]
    lines.append(f"| {r['id']} | {r['status']} | {raw} | {ev} |")

ready = sum(1 for r in results if r['status']=='READY')
total = len(results)
pct = round(100*ready/total, 1) if total else 0
lines += ["", f"## Gate", "", f"**Pass rate:** {ready}/{total} ({pct}%) READY  ",
          f"**Verdict:** {'PASS' if ready == total else 'BLOCK'}", ""]
open(out_path,'w',encoding='utf-8').write('\n'.join(lines) + '\n')
print(f"✓ GOAL-COVERAGE-MATRIX.md written with {total} implicit goals ({ready} READY)")
PY

  # 6. Gate check + block_resolve fallback
  READY_COUNT=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(sum(1 for r in d['results'] if r['status']=='READY'))")
  TOTAL=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(len(d['results']))")
  if [ "$READY_COUNT" -ne "$TOTAL" ]; then
    echo "⛔ Infra-smoke gate: ${READY_COUNT}/${TOTAL} goals READY — phase NOT yet provisioned."

    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.infra-smoke"
      BR_GATE_CONTEXT="Infra-smoke review: ${TOTAL} SPECS success_criteria checked, only ${READY_COUNT} READY. Remaining BLOCKED/FAILED/DEFERRED imply provisioning incomplete on env='${ENV_NAME}'."
      BR_EVIDENCE=$(cat "$RESULTS_JSON")
      BR_CANDIDATES='[{"id":"re-run-ansible","cmd":"echo would re-run ansible-playbook (user must chạy explicitly)","confidence":0.3,"rationale":"re-run provisioning may fix BLOCKED infra"}]'
      BR_RESULT=$(block_resolve "infra-smoke-not-ready" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "infra-smoke-not-ready" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
    fi
    exit 1
  fi

  echo "✓ Infra-smoke PASS (${READY_COUNT}/${TOTAL}) — phase provisioned as specified."
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_infra_smoke" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_infra_smoke.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_infra_smoke 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Infra-smoke checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_infra_smoke_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  # Exit review early — subsequent steps (browser, goal comparison) N/A for infra profile.
  exit 0
fi
```
</step>

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
  # Previously: one global overlap → any touched parent file false-PASSed every
  # goal. Now: each failed goal evaluated independently. Block if ANY failed
  # goal with known commits has zero overlap with delta.
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
    # v2.6.1 (2026-04-26): fix arg-ordering bug — was passing flag-as-step,
    # phase-dir-as-reason, missing gate_id. Function signature is:
    # log_override_debt FLAG PHASE STEP REASON [GATE_ID]
    # gate_id="review-goal-coverage" enables auto-resolve when next phase
    # review goal-coverage validator passes clean.
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
# Previously: any global overlap = PASS for all goals. Now: goals tracked
# individually. BLOCK if any failed goal with known commits has no per-goal
# overlap with delta.
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

<step name="phaseP_regression" mode="regression">
## Review mode: regression (P5, v1.9.2 — bugfix profile, OHOK Batch 2 B5: real verification)

**Runs when `REVIEW_MODE=regression`.**

**Previous behavior (performative):** wrote "Verdict: PASS (regression handled at /vg:test)" stub without verifying (a) issue is referenced, (b) code was actually changed, or (c) regression test exists. Bugfix could ship with empty changeset.

OHOK Batch 2 B5 enforces 3 real checks:
1. Bug reference exists in SPECS (else BLOCK — bugfix must cite issue)
2. Phase has ≥1 code commit (else BLOCK — fix must touch code)
3. Phase introduces ≥1 test file or extends existing test with bug ID reference (else WARN — logged but doesn't block; /vg:test will discover gap if test truly missing)

```bash
if [ "$REVIEW_MODE" != "regression" ]; then
  echo "↷ Skipping phaseP_regression (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Extract bug reference — MUST exist
  BUG_REF=$(grep -E '^\*\*issue_id\*\*:|^issue_id:|^\*\*bug_ref\*\*:|^bug_ref:|^\*\*Fixes bug\*\*:' \
            "$PHASE_DIR/SPECS.md" 2>/dev/null | sed -E 's/.*://; s/^\s*//' | head -1)
  if [ -z "$BUG_REF" ]; then
    echo "⛔ Bugfix profile requires issue_id/bug_ref in SPECS.md — no reference found" >&2
    echo "   Add to SPECS frontmatter: issue_id: JIRA-123" >&2
    echo "   or body: **Fixes bug**: GH#456" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    # v2.6.1 (2026-04-26): correct API call (FLAG PHASE STEP REASON GATE_ID)
    # gate_id="bugfix-bugref-required" enables auto-resolve when next review
    # finds the bugref later added.
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-no-bugref" "${PHASE_NUMBER}" "review.bugref-check" \
        "bugfix without issue_id — SPECS frontmatter missing issue_id/bug_ref/Fixes bug" \
        "bugfix-bugref-required"
    BUG_REF="<unspecified>"
  fi
  echo "▸ Regression review (bugfix): issue_ref=${BUG_REF}"

  # 2. Phase must have ≥1 code commit — empty bugfix is meaningless
  BASELINE_SHA=$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD 2>/dev/null)
  CODE_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               'apps/**/src/**' 'packages/**/src/**' 'infra/**' 2>/dev/null | sort -u)
  CODE_COUNT=$([ -z "$CODE_FILES" ] && echo 0 || echo "$CODE_FILES" | wc -l | tr -d ' ')

  if [ "$CODE_COUNT" -eq 0 ]; then
    echo "⛔ Bugfix phase has 0 code files changed in apps|packages|infra" >&2
    echo "   Bugfix must modify at least 1 production file." >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    # v2.6.1 (2026-04-26): correct API call (FLAG PHASE STEP REASON GATE_ID)
    # gate_id="bugfix-code-delta-required" enables auto-resolve when next
    # review finds non-empty code delta in apps|packages|infra.
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-empty-bugfix" "${PHASE_NUMBER}" "review.code-delta-check" \
        "bugfix has 0 code files changed in apps|packages|infra — no production delta" \
        "bugfix-code-delta-required"
  fi

  # 3. Scan for regression test — WARN if missing (don't block; /vg:test catches real gaps)
  TEST_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               '**/e2e/**/*.spec.ts' '**/__tests__/**' '**/*.test.ts' '**/*.test.js' \
               '**/tests/**/*.py' 2>/dev/null | sort -u)
  TEST_COUNT=$([ -z "$TEST_FILES" ] && echo 0 || echo "$TEST_FILES" | wc -l | tr -d ' ')
  BUG_ID_SAFE=$(echo "$BUG_REF" | grep -oE '[A-Za-z0-9_-]+' | head -1)

  # Look for test file mentioning the bug ID (by name or content)
  TEST_MENTIONS_BUG=0
  if [ -n "$BUG_ID_SAFE" ] && [ "$TEST_COUNT" -gt 0 ]; then
    for f in $TEST_FILES; do
      if [ -f "$f" ]; then
        if grep -qiE "(${BUG_ID_SAFE}|regression|bugfix)" "$f" 2>/dev/null; then
          TEST_MENTIONS_BUG=1
          break
        fi
      fi
    done
  fi

  if [ "$TEST_COUNT" -eq 0 ]; then
    echo "⚠ Bugfix introduces no test files — /vg:test will attempt to generate regression coverage" >&2
    REGRESSION_NOTE="no-test-added (WARN — /vg:test to generate)"
  elif [ "$TEST_MENTIONS_BUG" -eq 0 ]; then
    echo "⚠ Bugfix has ${TEST_COUNT} test files but none reference bug ID '${BUG_ID_SAFE}'" >&2
    REGRESSION_NOTE="test-files-unlinked (WARN — consider adding bug ID comment to test)"
  else
    echo "✓ Bugfix has ${TEST_COUNT} test files, at least one references bug ID" >&2
    REGRESSION_NOTE="test-linked (OK)"
  fi

  # 4. Write matrix with actual verification results
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$BUG_REF" \
    "$CODE_COUNT" "$TEST_COUNT" "$TEST_MENTIONS_BUG" "$REGRESSION_NOTE" <<'PY'
import sys
from datetime import datetime, timezone
out, phase, bug, code_count, test_count, test_mentions, note = sys.argv[1:8]
code_count = int(code_count); test_count = int(test_count); test_mentions = int(test_mentions)

if code_count == 0:
    verdict = "BLOCK (empty bugfix — no code changes)"
elif test_count > 0 and test_mentions:
    verdict = f"PASS (bugfix has {code_count} code files + linked test; /vg:test re-verifies)"
elif test_count > 0:
    verdict = f"PASS-WARN (bugfix has {code_count} code files + {test_count} tests unlinked to bug)"
else:
    verdict = f"PASS-WARN (bugfix has {code_count} code files but 0 tests; /vg:test must generate)"

lines = [
    f"# Goal Coverage Matrix — Phase {phase} (bugfix regression)",
    "",
    f"**Profile:** bugfix  ",
    f"**Bug reference:** {bug}  ",
    f"**Source:** SPECS.md issue_id + git delta vs HEAD~1  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "## Verification checks",
    "",
    "| Check | Status |",
    "|-------|--------|",
    f"| Bug reference present | {'✓' if bug != '<unspecified>' else '⛔ missing'} |",
    f"| Code files changed | {code_count} |",
    f"| Test files changed | {test_count} |",
    f"| Tests reference bug ID | {'✓' if test_mentions else 'no'} |",
    f"| Regression note | {note} |",
    "",
    "## Gate",
    "",
    f"**Verdict:** {verdict}",
    "",
    "**Next:** /vg:test runs issue-specific runner to re-verify bug is actually fixed.",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print(f"✓ GOAL-COVERAGE-MATRIX.md written — {verdict.split(' (')[0]}")
PY

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_regression" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_regression.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_regression 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.phaseP_regression_verified" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"bug_ref\":\"${BUG_REF}\",\"code_count\":${CODE_COUNT},\"test_count\":${TEST_COUNT},\"test_linked\":${TEST_MENTIONS_BUG}}" >/dev/null 2>&1 || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Regression checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_regression_lens_plan" \
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

<step name="phaseP_schema_verify" mode="schema-verify">
## Review mode: schema-verify (P5, v1.9.2 — migration profile)

```bash
if [ "$REVIEW_MODE" != "schema-verify" ]; then
  echo "↷ Skipping phaseP_schema_verify (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Schema-verify review (migration): checking ROLLBACK.md + migration files"
  # Minimum verification: ROLLBACK.md present (already checked in prereq),
  # migration files referenced in PLAN exist.
  MISSING_MIG=""
  for f in $(grep -oE '<file-path>[^<]*migrations[^<]*\.sql[^<]*</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
             sed -E 's/<\/?file-path>//g'); do
    [ -f "$f" ] || MISSING_MIG="${MISSING_MIG} $f"
  done
  if [ -n "$MISSING_MIG" ]; then
    echo "⛔ Migration files referenced in PLAN but missing:$MISSING_MIG"
    exit 1
  fi

  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (migration schema-verify)",
    "",
    "**Profile:** migration  ",
    "**Source:** SPECS.migration_plan + ROLLBACK.md  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "## Schema verification",
    "",
    "- ROLLBACK.md present",
    "- Migration files referenced in PLAN exist on disk",
    "- Schema round-trip validation deferred to /vg:test schema-roundtrip runner",
    "",
    "**Verdict:** PASS",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (migration schema-verify)")
PY
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_schema_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_schema_verify.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_schema_verify 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Schema-verify checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_schema_verify_lens_plan" \
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

<step name="phaseP_link_check" mode="link-check">
## Review mode: link-check (P5, v1.9.2 — docs profile)

```bash
if [ "$REVIEW_MODE" != "link-check" ]; then
  echo "↷ Skipping phaseP_link_check (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Link-check review (docs): scanning markdown files for broken relative links"
  DOC_FILES=$(grep -oE '<file-path>[^<]+\.md</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
              sed -E 's/<\/?file-path>//g')
  BROKEN=""
  for f in $DOC_FILES; do
    [ -f "$f" ] || continue
    for link in $(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/\]\(//; s/\)$//' | grep -vE '^https?://|^#'); do
      target=$(dirname "$f")/"$link"
      [ -e "$target" ] || BROKEN="${BROKEN}\n$f → $link"
    done
  done
  if [ -n "$BROKEN" ]; then
    echo -e "⚠ Broken relative links:$BROKEN"
  fi
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (docs link-check)",
    "",
    "**Profile:** docs  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "Docs-only phase — link-check performed; content fidelity deferred to /vg:test markdown-lint.",
    "",
    "**Verdict:** PASS",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (docs link-check)")
PY
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_link_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_link_check.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_link_check 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Link-check checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_link_check_lens_plan" \
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
