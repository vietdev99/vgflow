# build post-execution (STEP 5 — HEAVY)

<!-- # Exception: oversized ref (~948 lines) — extracted verbatim from backup
     spec lines 3030-3925; ceiling 980 in test_build_references_exist.py
     per audit doc docs/audits/2026-05-04-build-flat-vs-split.md. Verbatim
     preserves the i18n/a11y/cross-phase-ripple/L2-L6 fidelity sequence
     intact; future refactor splits the L2-L6 gate slate into its own ref.
     R2 round-2 expanded the post-spawn validator with BUILD-LOG layer
     enforcement (build_log_path/sha/index/sub_files). -->

This is the orchestrator-side body of the build pipeline's
post-execution step (`9_post_execution`). It is heavy: backup spec
~896 lines (backup lines 3030-3925), drives the i18n/a11y UX gates,
cross-phase ripple analysis, reflection-coverage verification, final
full-repo gate matrix (typecheck/build/unit/regression/spec-sync),
SUMMARY.md aggregation + commit, schema validation, API-DOCS
generation, and the L2/L3/L5/L6 design-fidelity gates.

Read `post-execution-delegation.md` for the input/output JSON
contract of the `vg-build-post-executor` subagent. This file
describes the orchestrator's responsibilities ONLY — pre-spawn
checklist, spawn site narration, post-spawn validation of returned
JSON, marker emission.

<HARD-GATE>
You MUST spawn ONE `vg-build-post-executor` subagent (NOT parallel —
this verifier walks all task results sequentially). You MUST NOT
verify inline. Single Agent() call in this step. The spawn-guard
(`scripts/vg-agent-spawn-guard.py`) enforces single-spawn for
`vg-build-post-executor` (R6 Task 3): a 2nd
`Agent(subagent_type="vg-build-post-executor")` call in the same run
is hard-denied. Counter persisted at
`.vg/runs/<run_id>/.post-executor-spawns.json`.

You MUST narrate the spawn via `bash scripts/vg-narrate-spawn.sh`
(green pill per R1a UX baseline Req 2) — `spawning` before the
Agent() call, `returned` on success, `failed` on error JSON. Skipping
narration breaks operator UX visibility but does NOT block.

The post-executor returns a JSON envelope. You MUST validate that
`gates_passed[]` includes `L2`, `L3` (when any task carried
`design_ref`), `L5`, `L6` (when any task carried `design_ref`), and
`truthcheck` BEFORE writing the step marker. You MUST also validate
that `summary_path` exists on disk and `sha256sum ${summary_path}`
matches `summary_sha256`. Marker write WITHOUT this validation is a
HARD VIOLATION — review/test/accept downstream consumes
SUMMARY.md and trusts gates_passed; drift here corrupts the entire
phase tail.
</HARD-GATE>

---

## Step ordering

1. **Pre-spawn checklist** (this file, sections below) — mark step
   active, run UX gates (i18n/a11y), cross-phase ripple, reflection
   coverage verify, step-marker check, final-gate matrix
   (typecheck/build/unit/regression), aggregate per-task results,
   verify per-task fingerprints exist (fail-fast), enumerate inputs
   for the subagent envelope.
2. **Spawn site** — narrate + spawn ONE `vg-build-post-executor` in a
   single Agent() call, then narrate return/failure.
3. **Post-spawn validation** — validate returned JSON shape, gates,
   summary path + sha256, then commit SUMMARY.md + state files,
   schema-validate SUMMARY.md, generate API-DOCS.md, write step
   marker.

---

## Pre-spawn checklist

Mark step active:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 9_post_execution
```

### Step 1 — Aggregate per-wave results

Aggregate before any gate runs so failures surface against a clean
inventory:

- Count completed plans, failed plans
- Check all `SUMMARY*.md` files exist
- Check `build-state.log` — every wave passed gate? (no wave should
  have lingering failure)

Per UX baseline Req 1, enumerate per-task plan slices via the loader
instead of cat-ing the flat PLAN file:

```bash
vg-load --phase ${PHASE_NUMBER} --artifact plan --list
```

(Loader prints one per-task path per line; use this list to drive the
fingerprint existence check below.)

### Step 2 — UX gates (i18n + a11y, lightweight AST scan, v1.14.4+)

Static AST scan của FE changed files (`.tsx`/`.jsx`). Catches:
- **i18n drift**: hardcoded text trong JSX không wrap `t()` /
  `useTranslation`
- **a11y gap**: button/img/input thiếu aria-label/alt/label

Lightweight (no browser). Heavy Playwright + axe-core thuộc về
`/vg:test`. Skip silently nếu phase không touch FE.

```bash
if [[ ! "$ARGUMENTS" =~ --skip-ux-gates ]]; then
  # Get FE files changed in this phase
  FE_CHANGED=""
  if [ -n "${first_commit:-}" ]; then
    FE_CHANGED=$(git diff --name-only "${first_commit}^..HEAD" 2>/dev/null | grep -E '\.(tsx|jsx)$' | grep -E '(apps/web|packages/ui)' || true)
  fi

  if [ -n "$FE_CHANGED" ]; then
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - <<PY
import re, sys
from pathlib import Path

changed = """$FE_CHANGED""".strip().split("\n")
i18n_violations = []
a11y_violations = []

# i18n patterns: JSX text nodes hardcoded (not wrapped in t())
JSX_TEXT_RE = re.compile(r'>\s*([A-Z][A-Za-z0-9 ,.!?\'-]{3,})\s*<')
T_CALL_RE = re.compile(r'\bt\s*\(')

# a11y patterns
BTN_NO_LABEL = re.compile(r'<button\b(?![^>]*\baria-label\b)(?![^>]*\baria-labelledby\b)[^>]*>(?:\s*<[^>]*/>)*\s*</button>')
IMG_NO_ALT = re.compile(r'<img\b(?![^>]*\balt\b)[^>]*/?>')
INPUT_NO_LABEL = re.compile(r'<input\b(?![^>]*\baria-label\b)(?![^>]*\baria-labelledby\b)(?![^>]*\bid\b)[^>]*/?>')

for fpath in changed:
    if not fpath:
        continue
    p = Path(fpath)
    if not p.exists():
        continue
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue

    # Skip files that are pure type declarations / config
    if '.d.ts' in fpath or fpath.endswith('.config.tsx'):
        continue

    # i18n: hardcoded JSX text without t() in same file
    has_t_import = bool(re.search(r'\b(useTranslation|i18n|from\s+[\'\"](react-i18next|next-i18next)[\'\"])', text))
    jsx_texts = [m.group(1).strip() for m in JSX_TEXT_RE.finditer(text)]
    # Filter: short single-word likely tags, numbers, dev placeholders
    real_texts = [t for t in jsx_texts if len(t.split()) >= 2 and not t.isdigit() and 'TODO' not in t]
    if real_texts and not has_t_import:
        i18n_violations.append({"file": fpath, "samples": real_texts[:3], "count": len(real_texts)})

    # a11y: button/img/input checks
    btn_count = len(BTN_NO_LABEL.findall(text))
    img_count = len(IMG_NO_ALT.findall(text))
    if btn_count or img_count:
        a11y_violations.append({"file": fpath, "buttons_no_label": btn_count, "imgs_no_alt": img_count})

# Report
print(f"UX gate scan: {len([f for f in changed if f])} FE files changed")

if i18n_violations:
    print(f"⚠ i18n: {len(i18n_violations)} files có hardcoded JSX text không wrap useTranslation/t():")
    for v in i18n_violations[:5]:
        print(f"   - {v['file']}: {v['count']} strings, samples: {v['samples'][:2]}")
    if len(i18n_violations) > 5:
        print(f"   ... +{len(i18n_violations)-5} more files")
else:
    print("✓ i18n: no hardcoded JSX text drift")

if a11y_violations:
    print(f"⚠ a11y: {len(a11y_violations)} files có button/img missing label/alt:")
    for v in a11y_violations[:5]:
        parts = []
        if v['buttons_no_label']: parts.append(f"{v['buttons_no_label']} button-no-label")
        if v['imgs_no_alt']: parts.append(f"{v['imgs_no_alt']} img-no-alt")
        print(f"   - {v['file']}: {', '.join(parts)}")
    if len(a11y_violations) > 5:
        print(f"   ... +{len(a11y_violations)-5} more files")
else:
    print("✓ a11y: no missing labels detected")

# Threshold for block: >5 i18n files OR >3 a11y files = significant drift
total_violation_files = len(i18n_violations) + len(a11y_violations)
if total_violation_files > 8:
    print(f"\n⛔ UX gate: {total_violation_files} violation files > threshold 8")
    sys.exit(1)
PY

    UX_RC=$?
    if [ "$UX_RC" != "0" ]; then
      echo "build-ux-gate-violation phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "ux_gate_violation" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" "{}"
      fi
      if [[ "$ARGUMENTS" =~ --allow-ux-violations ]]; then
        if type -t log_override_debt >/dev/null 2>&1; then
          log_override_debt "build-ux-violations" "${PHASE_NUMBER}" "i18n+a11y violations exceeded threshold" "$PHASE_DIR"
        fi
        echo "⚠ --allow-ux-violations set — proceeding, logged to debt"
      else
        echo "   Override (NOT recommended): /vg:build ${PHASE_NUMBER} --resume --allow-ux-violations"
        exit 1
      fi
    fi
  fi
elif [[ "$ARGUMENTS" =~ --skip-ux-gates ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-ux-gates" "${PHASE_NUMBER}" "user opted out i18n/a11y gates" "$PHASE_DIR"
  fi
fi
```

### Step 3 — Cross-phase ripple impact gate (v1.14.4+)

Verify build phase X không vô tình break code của phases trước. Sử
dụng graphify caller graph để identify upstream callers, group theo
phase commit ranges, run quick regression cho affected phases.

```bash
if [[ ! "$ARGUMENTS" =~ --skip-cross-phase-ripple ]]; then
  RIPPLE_REPORT="${PHASE_DIR}/.cross-phase-ripple.json"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}" "${PHASE_NUMBER}" <<'PY' > "$RIPPLE_REPORT"
import json, subprocess, sys, re, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
phase_num = sys.argv[2]
planning_dir = Path(".vg") if Path(".vg").exists() else Path(".planning")

# 1. Get files changed in this phase (git diff vs phase start)
try:
    first_commit = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", "--grep", f"({phase_num}-"],
        capture_output=True, text=True, check=True
    ).stdout.strip().split("\n")[0]
    if not first_commit:
        print(json.dumps({"skipped": "no_phase_commits"})); sys.exit(0)
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{first_commit}^..HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip().split("\n")
    changed = [f for f in changed if f and (f.endswith('.ts') or f.endswith('.tsx') or f.endswith('.js'))]
except Exception as e:
    print(json.dumps({"error": str(e)})); sys.exit(0)

if not changed:
    print(json.dumps({"changed_files": 0, "affected_phases": []})); sys.exit(0)

# 2. Find phases referencing these files (via SUMMARY.md mentions or commit attribution)
affected_phases = {}
for summary in glob.glob(str(planning_dir / "phases" / "*" / "SUMMARY*.md")):
    p = Path(summary)
    phase_name = p.parent.name
    # Extract phase num from dir name
    m = re.match(r'^(\d+(?:\.\d+)*)', phase_name)
    if not m:
        continue
    other_phase = m.group(1)
    # Skip self + future phases (lexical compare may not be perfect — skip exact match)
    if other_phase == phase_num:
        continue
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
        hits = sum(1 for f in changed if f in text)
        if hits > 0:
            affected_phases[other_phase] = hits
    except Exception:
        continue

result = {
    "phase": phase_num,
    "changed_files_count": len(changed),
    "affected_phases": affected_phases,
    "ripple_severity": "high" if len(affected_phases) >= 3 else ("medium" if len(affected_phases) >= 1 else "low"),
}
print(json.dumps(result, indent=2))
PY

  RIPPLE_RESULT=$(cat "$RIPPLE_REPORT" 2>/dev/null)
  AFFECTED_COUNT=$(echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "import sys,json; d=json.loads(sys.stdin.read()); print(len(d.get('affected_phases', {})))" 2>/dev/null || echo 0)

  if [ "${AFFECTED_COUNT:-0}" -gt 0 ]; then
    echo "⚠ Cross-phase ripple: ${AFFECTED_COUNT} previous phases reference changed files"
    echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "
import sys, json
d = json.loads(sys.stdin.read())
for p, hits in sorted(d.get('affected_phases', {}).items()):
    print(f'   - Phase {p}: {hits} file mentions in SUMMARY')
" 2>/dev/null

    echo ""
    echo "Recommended (manual): /vg:regression --phases=$(echo "$RIPPLE_RESULT" | ${PYTHON_BIN} -c "import sys, json; print(','.join(json.loads(sys.stdin.read()).get('affected_phases', {}).keys()))" 2>/dev/null)"
    echo ""

    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "cross_phase_ripple" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" \
        "{\"affected_count\":${AFFECTED_COUNT}}"
    fi
  else
    echo "✓ Cross-phase ripple: 0 previous phases impacted"
  fi
elif [[ "$ARGUMENTS" =~ --skip-cross-phase-ripple ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-ripple" "${PHASE_NUMBER}" "user opted out cross-phase ripple analysis" "$PHASE_DIR"
  fi
fi
```

### Step 4 — Reflection coverage verify (v1.14.4+)

If `.vg/bootstrap/` present, verify mỗi wave thành công đã produce
reflection file. Missing = WARN + telemetry (không block để không
ngăn build merge khi reflector fail nhẹ).

```bash
if [ -d ".vg/bootstrap" ] && [[ ! "$ARGUMENTS" =~ --skip-reflection ]]; then
  WAVES_TOTAL=$(ls "${PHASE_DIR}"/SUMMARY-WAVE-*.md 2>/dev/null | wc -l | tr -d ' ')
  REFLECTIONS_PRESENT=$(ls "${PHASE_DIR}"/reflection-wave-*.yaml 2>/dev/null | wc -l | tr -d ' ')
  MISSING_COUNT=$((WAVES_TOTAL - REFLECTIONS_PRESENT))

  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "⚠ Reflection coverage: ${REFLECTIONS_PRESENT}/${WAVES_TOTAL} waves có reflection file"
    echo "   Missing reflections sẽ giảm chất lượng bootstrap candidates."
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "reflection_skipped" "${PHASE_NUMBER}" "build.9" "post-execution" "WARN" \
        "{\"missing\":${MISSING_COUNT},\"total\":${WAVES_TOTAL}}"
    fi
  else
    echo "✓ Reflection coverage: ${REFLECTIONS_PRESENT}/${WAVES_TOTAL} waves complete"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "reflection_complete" "${PHASE_NUMBER}" "build.9" "post-execution" "PASS" \
        "{\"count\":${REFLECTIONS_PRESENT}}"
    fi
  fi
elif [[ "$ARGUMENTS" =~ --skip-reflection ]]; then
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "build-skip-reflection" "${PHASE_NUMBER}" "user opted out reflection step" "$PHASE_DIR"
  fi
  echo "⚠ --skip-reflection set — reflection skipped, logged to debt register"
fi
```

### Step 5 — Step filter marker check (deterministic enforcement)

```bash
# Re-compute expected steps — same as create_task_tracker
PROFILE=$(${PYTHON_BIN} -c "import re; [print(m.group(1)) or exit() for m in [re.match(r'^profile:\s*[\"\']?([^\"\'#\s]+)', l) for l in open('.claude/vg.config.md', encoding='utf-8')] if m]")
EXPECTED_STEPS=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/build.md \
  --profile "$PROFILE" \
  --output-ids | tr ',' ' ')

MISSED_STEPS=""
for step in $EXPECTED_STEPS; do
  if [ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]; then
    MISSED_STEPS="$MISSED_STEPS $step"
  fi
done

# 9_post_execution itself hasn't written its marker yet; allow self-exclusion
MISSED_STEPS=$(echo "$MISSED_STEPS" | tr ' ' '\n' | grep -v '^9_post_execution$' | tr '\n' ' ')

if [ -n "$(echo "$MISSED_STEPS" | xargs)" ]; then
  echo "⛔ Steps did not write markers:$MISSED_STEPS"
  echo "   Profile: $PROFILE expected these. AI skipped silently — BLOCK."
  echo "   Check ${PHASE_DIR}/.step-markers/ to see what ran."
  exit 1
fi
```

### Step 6 — Final gate matrix (all waves combined) — BLOCK on fail

```bash
FINAL_TYPECHECK=$(vg_config_get build_gates.typecheck_cmd "")
FINAL_BUILD=$(vg_config_get build_gates.build_cmd "")
echo "Final gate: full-repo typecheck..."
if [ -n "$FINAL_TYPECHECK" ] && ! eval "$FINAL_TYPECHECK"; then
  echo "⛔ Final typecheck failed"
  exit 1
fi

echo "Final gate: full-repo build..."
if [ -n "$FINAL_BUILD" ] && ! eval "$FINAL_BUILD"; then
  echo "⛔ Final build failed"
  exit 1
fi

# Full unit test suite (catches cross-wave regression)
# ⛔ HARD GATE (tightened 2026-04-17): --allow-no-tests replaced with --override-reason= requirement.
# Cannot silently skip final unit suite — must cite reason and log to build-state.
UNIT_CMD=$(vg_config_get build_gates.test_unit_cmd "")
UNIT_REQ=$(vg_config_get build_gates.test_unit_required "true")
if [ -n "$UNIT_CMD" ]; then
  echo "Final gate: full unit suite..."
  if ! eval "$UNIT_CMD"; then
    if [ "$UNIT_REQ" = "true" ]; then
      OVERRIDE_REASON=""
      if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
        echo "⚠ Final unit suite failed — override accepted (reason: $OVERRIDE_REASON)"
        echo "override: gate=final_unit_suite reason=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
        type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
          "--override-reason" "$PHASE_NUMBER" "build.final-unit-suite" "$OVERRIDE_REASON" "build-final-unit-suite"
      else
        echo "⛔ Final unit suite failed (test_unit_required=true)"
        echo "   To override: /vg:build ${PHASE_NUMBER} --override-reason=<issue-id-or-url>"
        exit 1
      fi
    else
      echo "⚠ Final unit suite failed — test_unit_required=false in config"
    fi
  fi
fi
```

### Step 7 — Regression gate (compare full test results vs accepted-phase baselines)

```bash
REGRESSION_ENABLED=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*regression_guard_enabled:\s*(\w+)', line)
    if m: print(m.group(1).lower()); break
else: print('true')
" 2>/dev/null)

if [ "$REGRESSION_ENABLED" = "true" ] && [ -d "${PLANNING_DIR}/phases" ]; then
  echo "Regression gate: collecting baselines from accepted phases..."
  ${PYTHON_BIN} .claude/scripts/regression-collect.py \
    --phases-dir "${PHASES_DIR}" --repo-root "${REPO_ROOT}" \
    --output "${VG_TMP}/regression-baselines.json" 2>&1

  BASELINE_COUNT=$(${PYTHON_BIN} -c "
import json
b = json.load(open('${VG_TMP}/regression-baselines.json', encoding='utf-8'))
print(b.get('total_goals', 0))
" 2>/dev/null)

  if [ "${BASELINE_COUNT:-0}" -gt 0 ]; then
    echo "Regression gate: comparing full suite results vs ${BASELINE_COUNT} goal baselines..."

    # Vitest results from final gate above (reuse if JSON output available)
    VITEST_JSON="${VG_TMP}/vitest-results.json"
    if [ ! -f "$VITEST_JSON" ] && [ -n "$UNIT_CMD" ]; then
      eval "$UNIT_CMD -- --reporter=json --outputFile=${VITEST_JSON}" 2>/dev/null || true
    fi

    ${PYTHON_BIN} .claude/scripts/regression-compare.py \
      --baselines "${VG_TMP}/regression-baselines.json" \
      --vitest-results "${VITEST_JSON}" \
      --output-dir "${VG_TMP}" \
      --json-only 2>&1
    REGRESSION_EXIT=$?

    if [ "$REGRESSION_EXIT" -eq 3 ]; then
      REG_COUNT=$(${PYTHON_BIN} -c "
import json
r = json.load(open('${VG_TMP}/regression-results.json', encoding='utf-8'))
print(r['summary']['REGRESSION'])
" 2>/dev/null)
      echo ""
      echo "⛔ Regression gate: ${REG_COUNT} goal(s) regressed (was PASS, now FAIL)."
      echo ""
      # Show top 5 regressions
      ${PYTHON_BIN} -c "
import json
r = json.load(open('${VG_TMP}/regression-results.json', encoding='utf-8'))
for c in r.get('classified', []):
    if c['current_status'] == 'REGRESSION':
        errs = c['current_errors'][0][:60] if c['current_errors'] else 'unknown'
        print(f\"  Phase {c['phase']} {c['goal_id']}: {c['title'][:40]} — {errs}\")
" 2>/dev/null | head -5
      echo ""
      echo "  Full report: /vg:regression --fix"
      echo ""

      FAIL_ACTION=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*regression_guard_fail_action:\s*(\w+)', line)
    if m: print(m.group(1).lower()); break
else: print('block')
" 2>/dev/null)

      case "$FAIL_ACTION" in
        block)
          echo "  regression_guard_fail_action=block → BLOCKING build."
          echo "  Fix: /vg:regression --fix  (auto-fix loop)"
          # ⛔ HARD BLOCK (tightened 2026-04-17): no silent skip option. Must --override-reason=.
          OVERRIDE_REASON=""
          if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
            OVERRIDE_REASON="${BASH_REMATCH[1]}"
          fi
          if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
            echo "⚠ Regression gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
            type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
              "--override-reason" "$PHASE_NUMBER" "build.regression.wave-${N}" "$OVERRIDE_REASON" "build-regression-wave-${N}"
            echo "regression-guard: wave-final OVERRIDE count=${REG_COUNT} reason=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
            # Mark phase as needing accept-gate review
            echo "${REG_COUNT}" > "${PHASE_DIR}/.regressions-overridden.count"
          else
            echo "  To override: /vg:build ${PHASE_NUMBER} --override-reason=<issue-id-or-url>"
            echo "  Or run: /vg:regression --fix"
            exit 1
          fi
          ;;
        warn)
          # ⛔ TIGHTENED: warn mode still logs to build-state for accept-gate audit.
          # Accept gate must read build-state.log and surface warn-mode regressions to user.
          echo "  regression_guard_fail_action=warn → proceeding with warning (logged for accept review)."
          echo "regression-guard: wave-final WARN count=${REG_COUNT} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
          echo "${REG_COUNT}" > "${PHASE_DIR}/.regressions-warned.count"
          ;;
      esac
    else
      echo "✓ Regression gate: 0 regressions. All baselines stable."
    fi
  else
    echo "Regression gate: no accepted phase baselines — skipping."
  fi
fi
```

### Step 8 — Spec Sync (auto-update specs from built code)

After build completes, check if code changed API routes or pages
that affect existing specs:

```bash
# Surface scan: new/changed endpoints vs API-CONTRACTS.md
CHANGED_ROUTES=$(git diff --name-only HEAD~${COMPLETED_COUNT} HEAD -- "$API_ROUTES" 2>/dev/null)
CHANGED_PAGES=$(git diff --name-only HEAD~${COMPLETED_COUNT} HEAD -- "$WEB_PAGES" 2>/dev/null)

if [ -n "$CHANGED_ROUTES" ] || [ -n "$CHANGED_PAGES" ]; then
  echo "Code changed after build — API-CONTRACTS.md may need sync."
  echo "Changed routes: $CHANGED_ROUTES"
  echo "Changed pages: $CHANGED_PAGES"
  echo "Run /vg:review to re-verify contracts + discover runtime drift."
fi
```

### Step 9 — VG-native State Update (MANDATORY)

```bash
# 1. Verify all plans have SUMMARY — HARD BLOCK (tightened 2026-04-17)
# Missing SUMMARY = agent silently skipped documentation → orphan commits → review misses scope.
MISSING_SUMMARIES=""
# Canonical: blueprint writes single `PLAN.md` → expect `SUMMARY.md`.
# Legacy (GSD-migrated): `{N}-PLAN*.md` pairs with `{N}-SUMMARY*.md`.
# Glob handles both; [ ! -e "$plan" ] skips unexpanded literal when no match.
for plan in ${PHASE_DIR}/PLAN*.md ${PHASE_DIR}/*-PLAN*.md; do
  [ ! -e "$plan" ] && continue
  plan_base=$(basename "$plan")
  if [[ "$plan_base" =~ ^([0-9]+)-PLAN ]]; then
    PLAN_NUM="${BASH_REMATCH[1]}"
    SUMMARY="${PHASE_DIR}/${PLAN_NUM}-SUMMARY*.md"
  else
    PLAN_NUM="canonical"
    SUMMARY="${PHASE_DIR}/SUMMARY*.md"
  fi
  if ! ls $SUMMARY 1>/dev/null 2>&1; then
    echo "⛔ Plan ${PLAN_NUM} has no SUMMARY"
    MISSING_SUMMARIES="${MISSING_SUMMARIES} ${PLAN_NUM}"
  fi
done
if [ -n "$MISSING_SUMMARIES" ]; then
  OVERRIDE_REASON=""
  if [[ "$ARGUMENTS" =~ --override-reason=([^[:space:]]+) ]]; then
    OVERRIDE_REASON="${BASH_REMATCH[1]}"
  fi
  if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
    echo "⚠ Missing SUMMARIES overridden (reason: $OVERRIDE_REASON) — plans:${MISSING_SUMMARIES}"
    echo "missing-summaries:${MISSING_SUMMARIES} override=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
      "--override-reason" "$PHASE_NUMBER" "build.missing-summaries" "$OVERRIDE_REASON" "build-missing-summaries"
  else
    echo "⛔ Missing SUMMARY for plans:${MISSING_SUMMARIES}"
    echo "   Each PLAN needs matching SUMMARY — executor must document what was built."
    echo "   Fix: regenerate missing SUMMARY manually or re-run wave with --resume"
    echo "   Override: --override-reason=<issue-id-or-url>"
    exit 1
  fi
fi

# 2. Update PIPELINE-STATE.json — mark phase execution complete (no GSD dependency)
#    IMPORTANT: must also append a structured ``steps.build`` entry so
#    vg-progress.py state-driven path recognises build as done. Prior
#    versions only wrote top-level fields (status/plans_*), which caused
#    /vg:progress to keep showing build=⬜ even though SUMMARY.md existed.
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from datetime import datetime; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'executing'; s['pipeline_step'] = 'build-crossai-pending'
s['plans_completed'] = '${COMPLETED_COUNT}'; s['plans_total'] = '${PLAN_COUNT}'
now = datetime.now().isoformat()
s['updated_at'] = now
s.setdefault('steps', {})['build'] = {
    'status': 'in_progress',
    'updated_at': now,
    'plans_completed': '${COMPLETED_COUNT}',
    'plans_total': '${PLAN_COUNT}',
    'summary': 'SUMMARY.md written; CrossAI build verification pending',
    'reason': 'code execution complete; build is not done until CrossAI loop and run-complete pass',
}
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# 3. Update ROADMAP.md — mark phase as "in progress" (not complete until accept)
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* build-crossai-pending/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```

Display:
```
Code execution complete for Phase {N}; build is NOT complete yet.
  Plans executed: {completed}/{total}
  Contract compliance: executors had contract context
  State: SUMMARY.md written; PIPELINE-STATE build=in_progress
  Next: mandatory CrossAI build-verify -> run-complete -> /vg:review {phase}
  Do not claim /vg:build PASS until step 12 run-complete succeeds.
```

### Step 10 — Per-task fingerprint existence (fail-fast pre-spawn)

Before spawning the post-executor, fail-fast if any task's
fingerprint marker file is missing — this is a deterministic disk
check (KEEP-FLAT per audit doc). Missing fingerprints mean the wave
executor exited without writing the L2 forcing-function artifact;
the post-executor cannot validate L2 in that case.

```bash
TASK_FINGERPRINT_MISSING=""
TASK_FINGERPRINT_LIST=()
TASK_READ_EVIDENCE_LIST=()

for task_path in $(vg-load --phase ${PHASE_NUMBER} --artifact plan --list); do
  TASK_NUM=$(basename "$task_path" .md | sed 's/^task-//')
  FP="${PHASE_DIR}/.fingerprints/task-${TASK_NUM}.fingerprint.md"
  RE="${PHASE_DIR}/.read-evidence/task-${TASK_NUM}.json"
  TASK_FINGERPRINT_LIST+=("$FP")

  if [ ! -s "$FP" ]; then
    TASK_FINGERPRINT_MISSING="${TASK_FINGERPRINT_MISSING} task-${TASK_NUM}"
  fi

  # Read-evidence is OPTIONAL per task (only present for design-ref tasks).
  # Pass null entry when absent so the subagent envelope index aligns with task list.
  if [ -s "$RE" ]; then
    TASK_READ_EVIDENCE_LIST+=("$RE")
  else
    TASK_READ_EVIDENCE_LIST+=("null")
  fi
done

if [ -n "$TASK_FINGERPRINT_MISSING" ]; then
  echo "⛔ Pre-spawn fail-fast: per-task fingerprints missing for:${TASK_FINGERPRINT_MISSING}"
  echo "   Each per-task executor must Write .fingerprints/task-N.fingerprint.md before commit."
  echo "   Fix: re-run wave with --resume; do NOT spawn post-executor on broken inputs."
  exit 1
fi
```

### Step 11 — Build subagent envelope inputs

Resolve the input envelope fields the post-executor needs (paths,
profile threshold lock, sandbox URL, per-task endpoint map). The
envelope is conceptual — the orchestrator passes the values via the
rendered prompt template defined in `post-execution-delegation.md`.

```bash
TASK_COUNT=${#TASK_FINGERPRINT_LIST[@]}
DESIGN_FIDELITY_GUARD_SCRIPT="scripts/run-design-fidelity-guard.sh"
FIDELITY_PROFILE_LOCK="${PHASE_DIR}/.fidelity-profile.lock"
SANDBOX_URL="${SANDBOX_URL:-$(vg_config_get build_gates.sandbox_url http://localhost:3000)}"

# Per-task endpoint map, derived deterministically from PLAN slices via
# vg-load (KEEP-FLAT — already split). One entry per task; empty
# endpoints[] for non-API tasks.
TASK_ENDPOINT_MAP_JSON="${PHASE_DIR}/.tmp/task-endpoint-map.json"
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}" "${PHASE_NUMBER}" <<'PY' > "$TASK_ENDPOINT_MAP_JSON"
import json, re, subprocess, sys
from pathlib import Path
phase_dir, phase_num = sys.argv[1], sys.argv[2]
out = []
listing = subprocess.run(
    ["vg-load", "--phase", phase_num, "--artifact", "plan", "--list"],
    capture_output=True, text=True
).stdout.strip().splitlines()
for path in listing:
    p = Path(path)
    if not p.is_absolute():
        p = Path(phase_dir) / path
    tid = re.sub(r"\.md$", "", p.name)
    body = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    endpoints = re.findall(r"<edits-endpoint>([^<]+)</edits-endpoint>", body)
    out.append({"task_id": tid, "endpoints": [e.strip() for e in endpoints]})
print(json.dumps(out, indent=2))
PY
```

---

## Spawn site

The orchestrator emits ONE narration line, then the SINGLE Agent()
call, then a narration line on return (or failure):

```bash
bash scripts/vg-narrate-spawn.sh vg-build-post-executor spawning "L2/L3/L5/L6 + truthcheck for ${PHASE_NUMBER}"
```

then calls (single Agent tool call, NOT parallel):

```
Agent(subagent_type="vg-build-post-executor", prompt=<rendered from post-execution-delegation.md template>)
```

After the subagent returns, the orchestrator narrates the outcome:

```bash
# On success (return JSON parses + gates_passed includes required gates)
bash scripts/vg-narrate-spawn.sh vg-build-post-executor returned "${N} gates passed, summary written"

# On failure (return JSON has error field, OR validation below fails)
bash scripts/vg-narrate-spawn.sh vg-build-post-executor failed "<gate-id>: <one-line cause>"
```

Read `post-execution-delegation.md` for the EXACT input envelope,
prompt template, and output JSON contract.

### Codex runtime spawn path

If the runtime is Codex, apply
`commands/vg/_shared/codex-spawn-contract.md` instead of calling the
Claude-only `Agent(...)` syntax:

1. Render `post-execution-delegation.md` into
   `${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/build-post-executor.prompt.md`.
2. Run `codex-spawn.sh --tier executor --sandbox workspace-write
   --spawn-role vg-build-post-executor --spawn-id build-post-executor` with
   `--out ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/build-post-executor.json`.
3. Set `SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"` and run the exact same
   post-spawn validation below.
4. Treat missing helper, missing Codex CLI, non-zero exit, empty output,
   malformed JSON, or invalid summary sha as a HARD BLOCK.

Do NOT verify post-execution inline on Codex.

---

## Post-spawn validation

The orchestrator MUST validate the returned JSON BEFORE marking the
step complete. The post-executor returns the envelope shaped per
`post-execution-delegation.md`'s "Output JSON contract" section.

### Validation checks

1. **Schema**: returned value parses as JSON and contains required
   keys: `gates_passed`, `gates_failed`, `gaps_closed`, `summary_path`,
   `summary_sha256`, plus the BUILD-LOG layer keys `build_log_path`,
   `build_log_index_path`, `build_log_sha256`, `build_log_sub_files`
   (R2 round-2 — closes A4/E2/C5 BUILD-LOG contract drift between SKILL
   and delegation).
2. **Gates coverage**: `gates_passed[]` MUST include `L2`, `L5`, and
   `truthcheck` unconditionally; MUST include `L3` AND `L6` when ANY
   task in the phase carried a `<design-ref>` (i.e., when
   `${TASK_READ_EVIDENCE_LIST[@]}` contains any non-`null` entry).
3. **Summary path exists**: `[ -f "${summary_path}" ]` must succeed.
4. **Summary hash matches**: `sha256sum "${summary_path}" | cut -d' ' -f1`
   must equal `summary_sha256`.
5. **BUILD-LOG concat exists + hashes**: `[ -s "${build_log_path}" ]`
   AND `sha256sum "${build_log_path}" | cut -d' ' -f1` MUST equal
   `build_log_sha256`. The path MUST resolve to
   `${PHASE_DIR}/BUILD-LOG.md` (entry contract `must_write` Layer 3).
6. **BUILD-LOG index exists**: `[ -s "${build_log_index_path}" ]` AND
   the path MUST resolve to `${PHASE_DIR}/BUILD-LOG/index.md`.
7. **BUILD-LOG sub-files non-empty + on disk**: `build_log_sub_files[]`
   MUST be non-empty (entry contract `glob_min_count: 1` for
   `BUILD-LOG/task-*.md`) AND every entry must exist on disk.
8. **Failed-without-closure**: if `gates_failed[]` is non-empty AND
   no entry in `gaps_closed[]` covers each failure (matched by
   `task_id` + `gate`), route to gap-recovery (separate flow, out of
   scope here) — do NOT mark step complete.

```bash
RET="$POST_EXECUTOR_RETURN_JSON"   # captured from Agent() return
${PYTHON_BIN} - "$RET" "$PHASE_DIR" "${TASK_READ_EVIDENCE_LIST[*]}" <<'PY' || exit 1
import json, sys, hashlib, os
from pathlib import Path

ret = json.loads(sys.argv[1])
phase_dir = Path(sys.argv[2]).resolve()
re_list = sys.argv[3].split()

required_keys = {
    "gates_passed", "gates_failed", "gaps_closed",
    "summary_path", "summary_sha256",
    # R2 round-2: BUILD-LOG contract keys (closes A4/E2/C5 drift).
    "build_log_path", "build_log_index_path",
    "build_log_sha256", "build_log_sub_files",
}
missing_keys = required_keys - ret.keys()
if missing_keys:
    print(f"⛔ Post-executor return missing keys: {missing_keys}"); sys.exit(1)

gates_passed = set(ret["gates_passed"])
required_gates = {"L2", "L5", "truthcheck"}
has_design_ref = any(p != "null" for p in re_list)
if has_design_ref:
    required_gates |= {"L3", "L6"}

missing_gates = required_gates - gates_passed
if missing_gates:
    print(f"⛔ Post-executor gates_passed missing required: {missing_gates}"); sys.exit(1)

summary_path = ret["summary_path"]
if not Path(summary_path).is_file():
    print(f"⛔ summary_path does not exist on disk: {summary_path}"); sys.exit(1)

actual_sha = hashlib.sha256(Path(summary_path).read_bytes()).hexdigest()
if actual_sha != ret["summary_sha256"]:
    print(f"⛔ summary_sha256 mismatch: returned={ret['summary_sha256']} actual={actual_sha}")
    sys.exit(1)

# BUILD-LOG layer 3 (flat concat) — must equal entry contract path.
expected_build_log = phase_dir / "BUILD-LOG.md"
build_log_path = Path(ret["build_log_path"])
if build_log_path.resolve() != expected_build_log.resolve():
    print(f"⛔ build_log_path drift: returned={build_log_path} expected={expected_build_log}")
    sys.exit(1)
if not build_log_path.is_file() or build_log_path.stat().st_size == 0:
    print(f"⛔ build_log_path missing or empty: {build_log_path}"); sys.exit(1)
actual_bl_sha = hashlib.sha256(build_log_path.read_bytes()).hexdigest()
if actual_bl_sha != ret["build_log_sha256"]:
    print(f"⛔ build_log_sha256 mismatch: returned={ret['build_log_sha256']} actual={actual_bl_sha}")
    sys.exit(1)

# BUILD-LOG layer 2 (index TOC).
expected_index = phase_dir / "BUILD-LOG" / "index.md"
build_log_index_path = Path(ret["build_log_index_path"])
if build_log_index_path.resolve() != expected_index.resolve():
    print(f"⛔ build_log_index_path drift: returned={build_log_index_path} expected={expected_index}")
    sys.exit(1)
if not build_log_index_path.is_file() or build_log_index_path.stat().st_size == 0:
    print(f"⛔ build_log_index_path missing or empty: {build_log_index_path}"); sys.exit(1)

# BUILD-LOG layer 1 (per-task split) — entry contract glob_min_count: 1.
sub_files = ret.get("build_log_sub_files") or []
if not sub_files:
    print("⛔ build_log_sub_files empty — Layer 1 split missing (R1a UX baseline Req 1)")
    sys.exit(1)
missing_subs = [p for p in sub_files if not Path(p).is_file()]
if missing_subs:
    print(f"⛔ build_log_sub_files paths missing on disk: {missing_subs}"); sys.exit(1)

# Failed-without-closure check
unclosed = []
for fail in ret.get("gates_failed", []):
    matched = any(
        c.get("task_id") == fail.get("task_id") and c.get("gate") == fail.get("gate")
        for c in ret.get("gaps_closed", [])
    )
    if not matched:
        unclosed.append(f"{fail.get('task_id')}:{fail.get('gate')}")

if unclosed:
    print(f"⛔ Post-executor failures without gap closure: {unclosed}")
    print("   Route to gap-recovery before marking step complete.")
    sys.exit(1)

print(f"✓ Post-executor return validated: gates={sorted(gates_passed)}, "
      f"summary+build_log sha256 match, {len(sub_files)} BUILD-LOG sub-files")
PY
```

### Step 4.5 — L4a deterministic phase-level gates (BLOCK on violation)

After per-task gates complete and before SUMMARY.md is written, run 3
deterministic phase-level gates that catch issues per-task gates cannot
see (cross-file FE↔BE comparisons + cross-document spec drift):

```bash
EVIDENCE_DIR="${PHASE_DIR}/.evidence"
mkdir -p "$EVIDENCE_DIR"

# L4a-i: FE → BE call graph (exits 1 + writes evidence on gap)
FE_ROOT=$(vg_config_get paths.web_pages "apps/web/src")
BE_ROOT=$(vg_config_get code_patterns.api_routes "apps/api/src")
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-fe-be-call-graph.py \
  --fe-root "$FE_ROOT" --be-root "$BE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/fe-be-call-graph.json" || {
  echo "⛔ L4a-i: FE→BE call graph violations — see ${EVIDENCE_DIR}/fe-be-call-graph.json"
  L4A_FAILED=1
}

# L4a-ii: Contract shape (method match for now — body P3)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-contract-shape.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
  --fe-root "$FE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/contract-shape.json" || {
  echo "⛔ L4a-ii: contract shape mismatches — see ${EVIDENCE_DIR}/contract-shape.json"
  L4A_FAILED=1
}

# L4a-iii: Spec drift (status code heuristic)
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-spec-drift.py \
  --phase-dir "${PHASE_DIR}" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${EVIDENCE_DIR}/spec-drift.json" || {
  echo "⛔ L4a-iii: spec drift — see ${EVIDENCE_DIR}/spec-drift.json"
  L4A_FAILED=1
}

if [ "${L4A_FAILED:-0}" = "1" ]; then
  # Emit telemetry — STEP 5.5 (next task) will pick up these evidence files
  # and run the auto-fix loop. Build does NOT mark complete with L4a violations.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.l4a_violations_detected" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\"}" \
    2>/dev/null || true
else
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.l4a_gates_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" \
    2>/dev/null || true
fi
```

### Commit SUMMARY.md + state files

The post-executor writes SUMMARY.md atomically. The orchestrator
commits it together with the updated state files:

```bash
git add ${PHASE_DIR}/SUMMARY*.md ${PLANNING_DIR}/STATE.md ${PLANNING_DIR}/ROADMAP.md
git commit -m "build({phase}): {completed}/{total} plans executed"
```

### Schema validation (BLOCK on SUMMARY.md frontmatter drift)

```bash
# v2.7 Phase E — schema validation post-write (BLOCK on SUMMARY.md frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact summary \
  > "${PHASE_DIR}/.tmp/artifact-schema-summary.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ SUMMARY.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-summary.json"
  exit 2
fi
```

### API-DOCS.md generation + coverage verify

```bash
# v2.48 — build-time API docs. Generated from API-CONTRACTS plus the current
# implementation so review/test consume what was actually built, not only the
# planning-time contract.
API_DOCS_PATH="${PHASE_DIR}/API-DOCS.md"
"${PYTHON_BIN}" .claude/scripts/generate-api-docs.py \
  --phase "${PHASE_NUMBER}" \
  --contracts "${PHASE_DIR}/API-CONTRACTS.md" \
  --plan "${PHASE_DIR}/PLAN.md" \
  --goals "${PHASE_DIR}/TEST-GOALS.md" \
  --interface-standards "${PHASE_DIR}/INTERFACE-STANDARDS.json" \
  --out "${API_DOCS_PATH}"
API_DOCS_RC=$?
if [ "${API_DOCS_RC}" != "0" ]; then
  echo "⛔ API docs generation failed — build cannot complete without API-DOCS.md."
  exit 2
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-api-docs-coverage.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/api-docs-coverage.json" 2>&1
API_DOCS_VERIFY_RC=$?
if [ "${API_DOCS_VERIFY_RC}" != "0" ]; then
  echo "⛔ API docs coverage failed — see ${PHASE_DIR}/.tmp/api-docs-coverage.json"
  cat "${PHASE_DIR}/.tmp/api-docs-coverage.json"
  exit 2
fi

"${PYTHON_BIN}" .claude/scripts/emit-evidence-manifest.py \
  --path "${API_DOCS_PATH}" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/PLAN.md,${PHASE_DIR}/TEST-GOALS.md" \
  --producer "vg:build/9_post_execution" >/dev/null 2>&1 || {
    echo "⛔ API-DOCS.md was written but evidence binding failed."
    exit 2
  }
echo "✓ API-DOCS.md generated and validated for review/test consumption"
```

---

## Step exit + marker

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "9_post_execution" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/9_post_execution.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 9_post_execution 2>/dev/null || true
```

After step 9 marker touched, return to entry `build.md` → STEP 6
(`10_postmortem_sanity`).
