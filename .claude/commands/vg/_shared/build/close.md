# build close (STEP 7)

<!-- # Exception: oversized ref (761 lines) — combines step 10 + 12 from
     backup (90 + 395 = 485 source lines) plus PR-D OpenAPI export + PR-E
     truthcheck loop scaffolding + Item 3 contract-runtime proof-artifact
     handoff + Item 4 PR-E read-endpoint light probe (Codex deferred).
     Ceiling raised to 800 in test_build_references_exist.py.
     The truthcheck loop's inline Python keeps fixture orchestration atomic
     in one place (recipe_executor + lease + write_captured); splitting it
     would scatter 2-phase commit semantics. -->

2 sub-steps: `10_postmortem_sanity` (recovery-bypass + silent-gate-failure detector + UI drift advisory + final graphify refresh) and `12_run_complete` (terminal validators + `build.completed` telemetry + truthcheck loop + `vg-orchestrator run-complete` + PIPELINE-STATE flip + ROADMAP status). This is the closing group of `/vg:build`; control returns to the user (or to `/vg:phase` chaining `/vg:review`) after STEP 7.2 succeeds.

<HARD-GATE>
You MUST run STEP 7.1 then STEP 7.2 in exact order. STEP 7.2
(`12_run_complete`) emits the terminal `build.completed` event — the
Stop hook refuses `vg-orchestrator run-complete` without it. Tasklist
clear-on-complete fires here too; skipping leaves a stale tasklist
after the run.

STEP 7.1 (`10_postmortem_sanity`) is the bypass detector — if it does
not run, recovery-mode bypasses (manual `(recovered)` commits, missing
telemetry, missing graphify rebuild events) go undetected and `/vg:review`
inherits a silently-corrupt phase. The PreToolUse Bash hook gates
`vg-orchestrator step-active`; each sub-step's bash MUST be wrapped with
`step-active` before its real work and `mark-step` after.
</HARD-GATE>

---

## STEP 7.1 — postmortem sanity (10_postmortem_sanity)

**Final sanity gate — catches recovery-mode bypass + silent gate failures.**

Historical: Phase 10 audit (2026-04-19) found build completed with 0 telemetry events + 0 graphify rebuild events + `(recovered)` commits — gates were bypassed via manual recovery path. This step ensures future bypasses are visible.

The check is composed of:
- `vg_build_postmortem_check` — telemetry + wave tags + recovery commits + step markers (deterministic shell, reads `.vg/telemetry.jsonl` + git log, no AI-context flat reads).
- `verify-goal-coverage-phase.py --advisory` — phase-level goal coverage audit (warn-only at build end; `/vg:review` enforces).
- UI structure drift (only if `UI-MAP.md` exists) — generates actual UI tree from code, diffs against expected, reports above thresholds. Layout-advisory only at build end.
- Final graphify refresh — closes the "first build has no graph / build ended with stale graph" gap so `run-complete` validator sees the `graphify_auto_rebuild` event.

```bash
vg-orchestrator step-active 10_postmortem_sanity

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/build-postmortem.sh"

# Full post-mortem: telemetry + wave tags + recovery commits + step markers
vg_build_postmortem_check "${PHASE_NUMBER}" "${PHASE_DIR}" ".vg/telemetry.jsonl"
POSTMORTEM_RC=$?

# Phase-level goal coverage audit (complements per-task binding check)
echo ""
echo "━━━ Phase goal coverage audit ━━━"
${PYTHON_BIN} .claude/scripts/verify-goal-coverage-phase.py \
  --phase-dir "${PHASE_DIR}" \
  --repo-root "${REPO_ROOT}" \
  --advisory  # warn-only at build end; /vg:review enforces
GOAL_COVERAGE_RC=$?

# Signal to user but don't block (review is the enforcement point)
if [ "$POSTMORTEM_RC" -ne 0 ] || [ "$GOAL_COVERAGE_RC" -ne 0 ]; then
  echo ""
  echo "⚠ Post-mortem flagged issues — review will enforce. Run: /vg:review ${PHASE_NUMBER}"
fi

# UI structure drift check (chỉ chạy nếu UI-MAP.md tồn tại)
if [ -f "${PHASE_DIR}/UI-MAP.md" ]; then
  echo ""
  echo "━━━ UI structure drift (lệch cấu trúc UI) ━━━"

  UI_MAP_SRC=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /src:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
  UI_MAP_ENTRY=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /entry:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')

  if [ -n "$UI_MAP_SRC" ] && [ -n "$UI_MAP_ENTRY" ]; then
    # Sinh cây thực tế từ code vừa build
    node .claude/scripts/generate-ui-map.mjs \
      --src "$UI_MAP_SRC" \
      --entry "$UI_MAP_ENTRY" \
      --format json \
      --output "${PHASE_DIR}/.ui-map-actual.json" 2>&1 | tail -3

    # So sánh với UI-MAP.md (kế hoạch đích)
    MAX_MISSING=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /max_missing:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "0")
    MAX_UNEXPECTED=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /max_unexpected:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "3")

    ${PYTHON_BIN} .claude/scripts/verify-ui-structure.py \
      --expected "${PHASE_DIR}/UI-MAP.md" \
      --actual "${PHASE_DIR}/.ui-map-actual.json" \
      --max-missing "$MAX_MISSING" \
      --max-unexpected "$MAX_UNEXPECTED" \
      --layout-advisory
    UI_DRIFT_RC=$?

    if [ "$UI_DRIFT_RC" -eq 2 ]; then
      echo ""
      echo "⚠ UI structure drift vượt ngưỡng — /vg:review sẽ BLOCK nếu không khắc phục"
    fi
  else
    echo "⚠ ui_map.src/entry chưa cấu hình — bỏ qua UI drift check"
  fi
fi

# Final graphify refresh after all build mutations and post-execution gates.
# This closes the "first build has no graph / build ended with stale graph"
# gap: run-complete validator checks the graphify_auto_rebuild event emitted here.
if [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
  if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-final"; then
    GRAPHIFY_ACTIVE="true"
  elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
    echo "⛔ Graphify final rebuild failed and fallback_to_grep=false"
    exit 1
  else
    echo "⚠ Graphify final rebuild failed; run-complete will surface evidence"
  fi
fi

# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "10_postmortem_sanity" "${PHASE_DIR}") || touch "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers/10_postmortem_sanity.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 10_postmortem_sanity 2>/dev/null || true
```

---

## STEP 7.1.5 — B4 cumulative final review (v2.66.1, hardened v2.69.0)

**v2.69.0 T2 escape hatch:** `SKIP_FINAL_REVIEW=1` short-circuits this
step (set by preflight when `--skip-final-review` is passed; logs
override-debt). When unset, full cumulative review runs.

**Cumulative delta review across the entire phase** — runs ONCE between
postmortem (STEP 7.1) and run-complete (next step). Spawns the new
`vg-build-final-reviewer` subagent (`.claude/agents/vg-build-final-reviewer/SKILL.md`)
which reads PLAN.md goal + the entire phase commit range + L-gate
results, then emits a `PASS | PARTIAL | FAIL` verdict.

This complements B1's per-task spec compliance reviewer
(`vg-build-spec-reviewer`, STEP 5.1): B1 catches per-task spec drift,
B4 catches cross-task integration gaps that no single task review can
see (e.g. FE Task 3 consumes an API endpoint Task 2 BE never actually
shipped).

**v2.69.0 T2 — flipped warn → block.** Marker `7_1_5_final_review` was
added to `must_touch_markers` (was doc-only) with
`required_unless_flag: "--skip-final-review"`. Build BLOCKs when the
reviewer FAILs and the flag is absent. Escape hatch logs override-debt.

```bash
vg-orchestrator step-active 7_1_5_final_review

# v2.69.0 T2 — --skip-final-review escape hatch (debt-tracked in preflight).
# When set, short-circuit reviewer spawn, touch marker, proceed.
if [ "${SKIP_FINAL_REVIEW:-0}" = "1" ]; then
  echo "▸ STEP 7.1.5: --skip-final-review set (debt-tracked); skipping cumulative review" >&2
  mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_1_5_final_review" "${PHASE_DIR}") || touch "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers/7_1_5_final_review.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 7_1_5_final_review 2>/dev/null || true
else
  # Resolve commit range covering the entire phase build
  BUILD_START_SHA=$(cat "${PHASE_DIR}/.build-start-sha" 2>/dev/null || git rev-parse HEAD~10)
  COMMIT_RANGE="${BUILD_START_SHA}..HEAD"

  bash scripts/vg-narrate-spawn.sh vg-build-final-reviewer spawning "cumulative review ${COMMIT_RANGE}"
  # AI orchestrator MUST call:
  #   Agent(subagent_type="vg-build-final-reviewer",
  #         prompt=<rendered with phase_dir + commit_range>)
  # The agent MUST write verdict to ${PHASE_DIR}/.final-review/verdict.md
  # with frontmatter format:
  #   ---
  #   verdict: PASS | PARTIAL | FAIL
  #   commit_range: <range>
  #   gaps: <markdown list>
  #   ---

  # F4 Batch 15: verdict file gate
  VERDICT_FILE="${PHASE_DIR}/.final-review/verdict.md"
  if [ ! -f "$VERDICT_FILE" ]; then
    echo "⛔ STEP 7.1.5 F4: vg-build-final-reviewer did not write $VERDICT_FILE" >&2
    echo "   Final review must persist verdict to disk; marker requires evidence." >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.final_review_missing_verdict" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -qE "^verdict:\s*FAIL" "$VERDICT_FILE"; then
    echo "⛔ STEP 7.1.5 F4: cumulative final review FAIL" >&2
    head -30 "$VERDICT_FILE" >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.final_review_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -qE "^verdict:\s*PARTIAL" "$VERDICT_FILE"; then
    echo "⚠ STEP 7.1.5 F4: cumulative final review PARTIAL — gaps logged but proceeding (v4.18.0 advisory)" >&2
  fi

  mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_1_5_final_review" "${PHASE_DIR}") || touch "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers/7_1_5_final_review.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 7_1_5_final_review 2>/dev/null || true
fi
```

**Marker:** `7_1_5_final_review` — v2.69.0
`required_unless_flag: "--skip-final-review"` (was doc-only severity warn).

---

## STEP 7.2 — run complete (12_run_complete)

**Terminal step. Validators fire, BLOCK on violations, then `vg-orchestrator run-complete` flips PIPELINE-STATE.**

Verifies R7 markers, runs the terminal validator slate (business-rule-implemented, interface-standards, flow-compliance, route-schema-coverage, OpenAPI export, API truthcheck loop), emits `build.completed` telemetry, calls `vg-orchestrator run-complete`, flips `PIPELINE-STATE.json` to `executed` / `build-complete`, and updates ROADMAP status. The pre-built artifacts that this step relies on (SUMMARY.md, INTERFACE-STANDARDS.{md,json}, API-DOCS.md, `.build-progress.json`, BUILD-LOG layers) are produced upstream by waves and the post-execution group; this step commits the closing telemetry and gate verdicts, it does not regenerate artifacts.

Per **R1a UX baseline Req 1** (3-layer split for any flat artifact), the BUILD-LOG family follows the convention: `BUILD-LOG/task-*.md` (Layer 1 per-task — `vg-build-task-executor` writes one per spawn) + `BUILD-LOG/index.md` (Layer 2 TOC — `vg-build-post-executor` writes) + `BUILD-LOG.md` (Layer 3 flat concat — `vg-build-post-executor` enumerates `BUILD-LOG/task-*.md` lexicographically and writes the atomic concat). Both Layer 2 + Layer 3 are produced by the post-executor in STEP 5, NOT by waves; close.md only commits whatever the post-executor wrote.

<HARD-GATE>
You MUST emit `build.completed` via `vg-orchestrator emit-event` before
`mark-step`. The Stop hook refuses `vg-orchestrator run-complete` if the
`build.completed` event is missing.

The pre-built artifacts (SUMMARY.md, INTERFACE-STANDARDS.{md,json},
API-DOCS.md, .build-progress.json) MUST exist in PHASE_DIR before this
step runs — they are produced upstream and verified by the validator
slate here.

The 3-layer BUILD-LOG split (BUILD-LOG/task-*.md per-task layer 1
written by each `vg-build-task-executor`, BUILD-LOG/index.md TOC layer
2 + BUILD-LOG.md flat concat layer 3 written by `vg-build-post-executor`
in STEP 5) is materialized upstream per R1a UX baseline Req 1; this step
commits whatever exists on disk but does NOT generate any of the layers.

Truthcheck-enabled runs are fail-closed: `apps/api/openapi.json` MUST
exist (probe or pre-export) before the truthcheck loop, otherwise
PR-D/PR-E BLOCK fires.
</HARD-GATE>

```bash
vg-orchestrator step-active 12_run_complete

# v2.46 Phase 6 — business rule constants in code
# Closes "code drift from D-XX values" gap (e.g., D-46 says 5 but code has 3).
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"
BIZRULE_VAL=".claude/scripts/validators/verify-business-rule-implemented.py"
if [ -f "$BIZRULE_VAL" ]; then
  BIZRULE_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-rule-not-implemented ]] && BIZRULE_FLAGS="$BIZRULE_FLAGS --allow-rule-not-implemented"
  ${PYTHON_BIN:-python3} "$BIZRULE_VAL" --phase "${PHASE_NUMBER:-${PHASE_ARG}}" $BIZRULE_FLAGS
  BIZRULE_RC=$?
  if [ "$BIZRULE_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Business-rule-implemented gate failed: code constants drift from CONTEXT decisions."
    echo "   Verify expected_assertion values appear as constants in apps/packages/infra source."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.bizrule_blocked" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

INTERFACE_VAL=".claude/scripts/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_VAL" ]; then
  ${PYTHON_BIN:-python3} "$INTERFACE_VAL" \
    --phase "${PHASE_NUMBER:-${PHASE_ARG}}" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}"
  INTERFACE_RC=$?
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ Interface standards gate failed at build run-complete."
    echo "   API/FE/CLI code must follow INTERFACE-STANDARDS.md before /vg:review."
    exit 1
  fi
fi

# Emit final completion telemetry only after the CrossAI loop has reached an
# accepted terminal state. run-complete validates this event in the same call.
SUMMARY_COUNT=$(ls "${PHASE_DIR}"/SUMMARY*.md 2>/dev/null | wc -l | tr -d " ")
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.completed" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"summaries\":${SUMMARY_COUNT},\"after_crossai\":true}" >/dev/null

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "12_run_complete" "${PHASE_DIR}") || touch "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers/12_run_complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_run_complete 2>/dev/null || true

# Rule 2 Batch 13: collect per-task diff stats + complexity gate (simplicity-first)
COMPLEXITY_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-task-complexity.py"
[ -f "$COMPLEXITY_VAL" ] || COMPLEXITY_VAL="${REPO_ROOT:-.}/scripts/validators/verify-task-complexity.py"
[ -f "$COMPLEXITY_VAL" ] || COMPLEXITY_VAL=".claude/scripts/validators/verify-task-complexity.py"
TASK_STATS="${PHASE_DIR}/.task-diff-stats.json"
if [ -f "$COMPLEXITY_VAL" ] && [ -d "${PHASE_DIR}/.step-markers" ]; then
  # Collect git diff stats per task: parse PLAN.md for ## Task T-XX headers
  ${PYTHON_BIN:-python3} - <<'PYEOF' > "$TASK_STATS"
import json, subprocess, re
from pathlib import Path
import os
phase_dir = Path(os.environ.get("PHASE_DIR", "."))
stats = {}
plan_path = phase_dir / "PLAN.md"
task_ids = []
if plan_path.is_file():
    for m in re.finditer(r"##\s+Task\s+(T-\d+)\b", plan_path.read_text(encoding="utf-8")):
        task_ids.append(m.group(1))
# Also scan step-markers for any T-XX.done markers (marker schema compat)
markers_dir = phase_dir / ".step-markers"
if markers_dir.is_dir():
    for mf in markers_dir.glob("*T-*.done"):
        tid = re.search(r"(T-\d+)", mf.name)
        if tid and tid.group(1) not in task_ids:
            task_ids.append(tid.group(1))
for task_id in task_ids:
    diff = subprocess.run(
        ["git", "diff", "--shortstat", "HEAD~1", "HEAD"],
        capture_output=True, text=True, cwd=str(phase_dir.parents[2] if len(phase_dir.parts) >= 3 else "."),
    )
    out = diff.stdout.strip()
    files = int((re.search(r"(\d+) files? changed", out) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
    ins = int((re.search(r"(\d+) insertions?", out) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
    dels = int((re.search(r"(\d+) deletions?", out) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
    stats[task_id] = {"files_changed": files, "loc_delta": ins + dels}
print(json.dumps(stats, indent=2))
PYEOF
  # Run validator per task — advisory (no exit 1 unless user passes --strict-complexity)
  while IFS= read -r task_id || [ -n "$task_id" ]; do
    [[ -z "$task_id" ]] && continue
    STRICT_FLAG=""
    [[ "${ARGUMENTS}" =~ --strict-complexity ]] && STRICT_FLAG="--strict"
    "${PYTHON_BIN:-python3}" "$COMPLEXITY_VAL" \
      --phase-dir "${PHASE_DIR}" --task-id "$task_id" $STRICT_FLAG || true
  done < <(grep -oP '(?<=## Task )T-\d+' "${PHASE_DIR}/PLAN.md" 2>/dev/null || echo "")
fi

# v2.38.0 — Flow compliance audit (closes "AI bypass step via override" loophole)
# Severity warn first release for dogfood; promote to block via vg.config.md.
if [[ ! "$ARGUMENTS" =~ --skip-compliance ]]; then
  COMPLIANCE_REASON=""
  COMPLIANCE_SEVERITY=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
else
  COMPLIANCE_REASON=$(echo "$ARGUMENTS" | grep -oE -- '--skip-compliance="[^"]*"' | sed 's/--skip-compliance="//; s/"$//')
  COMPLIANCE_SEVERITY="warn"
fi

COMPLIANCE_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "build" "--severity" "$COMPLIANCE_SEVERITY" )
[ -n "$COMPLIANCE_REASON" ] && COMPLIANCE_ARGS+=( "--skip-compliance=$COMPLIANCE_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMPLIANCE_ARGS[@]}"
COMPLIANCE_RC=$?
if [ "$COMPLIANCE_RC" -ne 0 ]; then
  emit_telemetry_v2 "build_flow_compliance_failed" "${PHASE_NUMBER}" \
    "build.compliance" "flow_compliance" "$COMPLIANCE_SEVERITY" \
    "{\"command\":\"build\"}" 2>/dev/null || true
  if [ "$COMPLIANCE_SEVERITY" = "block" ]; then
    echo "⛔ Build flow compliance failed. Re-run with proper artifacts OR --skip-compliance=\"<reason>\"."
    exit 1
  fi
fi

# RFC v9 PR-D — Route schema coverage gate (P1.D-24/54).
# Every Fastify route must attach a Zod schema (validation + auto-OpenAPI).
# Profile gate: only runs for web-fullstack / web-backend-only with apps/api
# present. Pre-2026-05-01 phases get warn-mode (legacy gap tolerated);
# baseline file tracks per-phase coverage to BLOCK only on regression.
ROUTE_SCHEMA_VAL=".claude/scripts/validators/verify-route-schema-coverage.py"
if [ -f "$ROUTE_SCHEMA_VAL" ] && [ -d "apps/api/src" ]; then
  RSC_BASELINE=".vg/baselines/route-schema-coverage.json"
  RSC_FLAGS=( --severity block --threshold 0.8 --baseline-file "$RSC_BASELINE" )
  [[ "${ARGUMENTS}" =~ --allow-coverage-regression ]] && \
    RSC_FLAGS+=( --allow-coverage-regression )
  # Pre-cutoff phases: WARN mode to migrate gradually
  GOALS_FIRST_COMMIT_TS=$(git log --reverse --format=%ct -- \
    "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null | head -1)
  GRANDFATHER_CUTOFF=$(date -u -j -f "%Y-%m-%d" "2026-05-01" +%s 2>/dev/null \
    || date -u -d "2026-05-01" +%s 2>/dev/null || echo "0")
  if [ -n "$GOALS_FIRST_COMMIT_TS" ] && [ "$GOALS_FIRST_COMMIT_TS" -lt "$GRANDFATHER_CUTOFF" ]; then
    RSC_FLAGS=( --severity warn --threshold 0.8 --baseline-file "$RSC_BASELINE" )
  fi
  ${PYTHON_BIN:-python3} "$ROUTE_SCHEMA_VAL" "${RSC_FLAGS[@]}" \
    --report-md "${PHASE_DIR}/.route-schema-coverage.md"
  RSC_RC=$?
  if [ "$RSC_RC" -ne 0 ]; then
    echo "⛔ Route schema coverage gate failed."
    echo "   Existing legacy gap (e.g. PrintwayV3 1% baseline) is tolerated"
    echo "   via --baseline-file; only REGRESSIONS block. Fix path:"
    echo "     1. Wrap routes with .withTypeProvider<ZodTypeProvider>()"
    echo "     2. Attach { schema: { body, querystring, response } } to each route"
    echo "     3. Or override: --allow-coverage-regression --override-reason='...'"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.route_schema_blocked" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

# v3.7.1 (Codex wiring fix) — verify-contract-runtime.py static existence gate.
# Closes the gap where validator existed (B7.2 / OHOK gap A2) but was never
# wired into the build pipeline. Phantom endpoints (declared in API-CONTRACTS.md
# but never implemented in source) previously surfaced only at review step 5b
# curl — 1+ hours after the wave committed. This static gate runs BEFORE
# PR-E runtime truthcheck so cheap presence checks fire first.
CONTRACT_RUNTIME_VAL=".claude/scripts/validators/verify-contract-runtime.py"
if [ -f "$CONTRACT_RUNTIME_VAL" ]; then
  if [[ "${ARGUMENTS}" =~ --skip-contract-runtime ]]; then
    if [[ ! "${ARGUMENTS}" =~ --override-reason=([^[:space:]]+) ]]; then
      echo "⛔ --skip-contract-runtime requires --override-reason=<issue-id-or-url>"
      exit 1
    fi
    CONTRACT_SKIP_REASON="${BASH_REMATCH[1]}"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag=--skip-contract-runtime \
      --reason="build.contract-runtime.skipped phase=${PHASE_NUMBER:-${PHASE_ARG}} ts=$(date -u +%FT%TZ); operator-supplied: ${CONTRACT_SKIP_REASON}" \
      2>&1 || echo "⚠ vg-orchestrator override emit failed for --skip-contract-runtime; debt register still appended" >&2
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "--skip-contract-runtime" "${PHASE_NUMBER:-${PHASE_ARG}}" \
        "build.contract-runtime.skipped" "$CONTRACT_SKIP_REASON" \
        "build-contract-runtime-skipped" >/dev/null 2>&1 || true
    fi
    echo "  contract-runtime: SKIPPED via --skip-contract-runtime (override-debt logged: ${CONTRACT_SKIP_REASON})"
  else
    ${PYTHON_BIN:-python3} "$CONTRACT_RUNTIME_VAL" --phase "${PHASE_NUMBER:-${PHASE_ARG}}"
    CONTRACT_RC=$?
    if [ "$CONTRACT_RC" -ne 0 ]; then
      echo "⛔ Contract-runtime gate failed at build close — phantom endpoints detected."
      echo "   API-CONTRACTS.md declares endpoints not found in source code."
      echo "   Fix path:"
      echo "     1. Implement the missing route handler in apps/api/src/..."
      echo "     2. Or remove the obsolete declaration from API-CONTRACTS.md"
      echo "     3. Or override (logs debt): --skip-contract-runtime --override-reason='<reason>'"
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.contract_runtime_blocked" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\"}" >/dev/null 2>&1 || true
      exit 1
    fi
    # v4.0.x Item 3 (Codex deferred) — emit proof artifact for review phase2a fallback.
    # phase2a_api_contract_probe at review preflight checks this artifact: if fresh
    # (creator_run_id matches current run), review SKIPS re-probing (saves 10-30s).
    # Artifact written: .contract-runtime-report.json (phase2a reads this to skip probe)
    PROOF_PATH="${PHASE_DIR}/.contract-runtime-report.json"
    ${PYTHON_BIN:-python3} "$CONTRACT_RUNTIME_VAL" \
      --phase "${PHASE_NUMBER:-${PHASE_ARG}}" \
      --json > "$PROOF_PATH" 2>/dev/null || \
      ${PYTHON_BIN:-python3} -c "import json,sys; json.dump({'verdict':'PASS','endpoints':[],'note':'static-presence-check passed; validator --json unsupported, see stderr for details'}, sys.stdout)" > "$PROOF_PATH"
    EMIT_MANIFEST="${REPO_ROOT}/.claude/scripts/emit-evidence-manifest.py"
    [ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
    if [ -f "$EMIT_MANIFEST" ]; then
      # emit-evidence-manifest binds .contract-runtime-report.json to this run_id
      # verify-artifact-freshness.py at review phase2a uses this to confirm freshness.
      ${PYTHON_BIN:-python3} "$EMIT_MANIFEST" \
        --path "${PHASE_DIR}/.contract-runtime-report.json" \
        --producer "vg:build/12_run_complete/verify-contract-runtime" \
        --source-inputs "${PHASE_DIR}/API-CONTRACTS.md" \
        --quiet || true
    fi
  fi
fi

# RFC v9 PR-E — API truthcheck loop (1-command 3-phase build).
# After BE+FE code committed and openapi.json exported, run every backend
# mutation goal that has FIXTURES through recipe_executor with hard
# guardrails. Closes the "review hits 4xx because Haiku scanner uses bogus
# values" loop: by verifying API responds correctly to FIXTURES bodies
# BEFORE /vg:review runs, we catch backend bugs at build time and Haiku
# scanner has captured store from successful runs to populate UI form
# values from at review time.
#
# Hard guardrails (anti-fake-test):
#   - max 5 iterations per goal
#   - exit criteria gates (NOT just "test pass"):
#     * D18 test_type coverage: ≥1 happy + ≥1 edge + ≥1 negative per
#       mutation goal
#     * Response shape match openapi.json schema
#     * lifecycle.post_state assertion fires (DB state read-after-write)
#     * Idempotency replay: same key twice → identical response
#     * Auth boundary: wrong-role call → 403
#   - iter 5 fail → spawn diagnostic_l2 single-advisory (D26) + user gate
#   - council guard: Codex review test code BEFORE accepting loop pass
#     (catches AI fake-test like `expect(true).toBe(true)`)
#
# Skip flags:
#   --skip-truthcheck                  fully bypass (--override-reason required)
#   --resume=truthcheck                re-run truthcheck only (skip BE/FE)
TRUTHCHECK_OUT="${PHASE_DIR}/.api-truthcheck.json"
TRUTHCHECK_ENABLED=$(vg_config_get "build.api_truthcheck.enabled" "true" 2>/dev/null || echo "true")
TRUTHCHECK_SKIP_REASON=""
TRUTHCHECK_SUMMARY='{"verdict":"SKIP","reason":"not-run"}'

if [[ "${ARGUMENTS}" =~ --skip-truthcheck ]]; then
  if [[ ! "${ARGUMENTS}" =~ --override-reason=([^[:space:]]+) ]]; then
    echo "⛔ --skip-truthcheck requires --override-reason=<issue-id-or-url>"
    exit 1
  fi
  TRUTHCHECK_SKIP_REASON="${BASH_REMATCH[1]}"
  # R2 round-2 (A5) — emit canonical override.used so run-complete's
  # forbidden_without_override check (build.md frontmatter declares
  # --skip-truthcheck) clears. log_override_debt mirrors into the legacy
  # debt register; both paths coexist during migration.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag=--skip-truthcheck \
    --reason="build.api-truthcheck.skipped phase=${PHASE_NUMBER:-${PHASE_ARG}} ts=$(date -u +%FT%TZ); operator-supplied: ${TRUTHCHECK_SKIP_REASON}" \
    2>&1 || echo "⚠ vg-orchestrator override emit failed for --skip-truthcheck; debt register still appended" >&2
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "--skip-truthcheck" "$PHASE_NUMBER" \
      "build.api-truthcheck.skipped" "$TRUTHCHECK_SKIP_REASON" \
      "build-api-truthcheck-skipped" >/dev/null 2>&1 || true
  fi
  echo "  PR-E: SKIPPED via --skip-truthcheck (override-debt logged: ${TRUTHCHECK_SKIP_REASON})"
  TRUTHCHECK_SUMMARY=$(TRUTHCHECK_SKIP_REASON="$TRUTHCHECK_SKIP_REASON" ${PYTHON_BIN:-python3} -c "import json,os; print(json.dumps({'verdict':'SKIP','reason':'--skip-truthcheck','override_reason':os.environ.get('TRUTHCHECK_SKIP_REASON','')}))")
  printf '%s\n' "$TRUTHCHECK_SUMMARY" > "$TRUTHCHECK_OUT"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.api_truthcheck_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"reason\":$(printf '%s' "$TRUTHCHECK_SKIP_REASON" | ${PYTHON_BIN:-python3} -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    >/dev/null 2>&1 || true
  TRUTHCHECK_ENABLED="false"
fi

# RFC v9 PR-D — OpenAPI export evidence step.
# Truthcheck-enabled runs are fail-closed: must have machine-readable OpenAPI.
OPENAPI_EXPORT_OUT="apps/api/openapi.json"
OPENAPI_EXPORT_OK="false"
if [ -d "apps/api/src" ] && [ "${VG_OPENAPI_EXPORT:-true}" = "true" ]; then
  echo "━━━ PR-D — OpenAPI evidence export ━━━"
  OPENAPI_URL_PROBE="${VG_OPENAPI_PROBE_URL:-http://localhost:4000/api/v1/openapi.json}"
  if curl -fsS --max-time 3 "$OPENAPI_URL_PROBE" -o /tmp/openapi-probe.json 2>/dev/null; then
    cp /tmp/openapi-probe.json "$OPENAPI_EXPORT_OUT"
    OPENAPI_PATHS=$(${PYTHON_BIN:-python3} -c "
import json
try: print(len(json.load(open('$OPENAPI_EXPORT_OUT'))['paths']))
except Exception: print('?')
")
    echo "  PR-D: openapi.json exported (${OPENAPI_PATHS} paths) → ${OPENAPI_EXPORT_OUT}"
    OPENAPI_EXPORT_OK="true"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.openapi_exported" --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"paths\":${OPENAPI_PATHS:-0}}" >/dev/null 2>&1 || true
  else
    echo "  PR-D: probe failed at ${OPENAPI_URL_PROBE}"
  fi
fi

if [ "$OPENAPI_EXPORT_OK" != "true" ] && [ -f "$OPENAPI_EXPORT_OUT" ]; then
  OPENAPI_EXPORT_OK="true"
  echo "  PR-D: using existing ${OPENAPI_EXPORT_OUT} (probe unavailable)"
fi

if [ "$TRUTHCHECK_ENABLED" = "true" ] && [ "$OPENAPI_EXPORT_OK" != "true" ]; then
  echo "⛔ PR-D/PR-E BLOCK: truthcheck enabled but openapi evidence unavailable."
  echo "   Required: boot API so ${VG_OPENAPI_PROBE_URL:-http://localhost:4000/api/v1/openapi.json} responds,"
  echo "   or provide ${OPENAPI_EXPORT_OUT} before /vg:review."
  exit 1
fi

if [ "$TRUTHCHECK_ENABLED" = "true" ]; then
  VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
  [ -d "${VG_SCRIPT_ROOT}/runtime" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
  if [ ! -d "${PHASE_DIR}/FIXTURES" ]; then
    echo "  PR-E: no FIXTURES directory — skip truthcheck"
    TRUTHCHECK_SUMMARY='{"verdict":"SKIP","reason":"no-fixtures-dir"}'
    printf '%s\n' "$TRUTHCHECK_SUMMARY" > "$TRUTHCHECK_OUT"
  elif [ ! -f "${VG_SCRIPT_ROOT}/runtime/recipe_executor.py" ]; then
    echo "⛔ PR-E BLOCK: runtime/recipe_executor.py missing from VG workflow scripts"
    exit 1
  else
    echo "━━━ PR-E — API truthcheck loop (max 5 iter) ━━━"

    TRUTHCHECK_GOALS=$(ls "${PHASE_DIR}/FIXTURES"/G-*.yaml 2>/dev/null | \
      xargs -n1 basename 2>/dev/null | sed 's/\.yaml$//' | tr '\n' ' ')
    TRUTHCHECK_COUNT=$(echo "$TRUTHCHECK_GOALS" | wc -w | tr -d ' ')

    if [ "${TRUTHCHECK_COUNT:-0}" -eq 0 ]; then
      echo "  PR-E: no fixture goals — skip truthcheck"
      TRUTHCHECK_SUMMARY='{"verdict":"SKIP","reason":"no-fixture-goals"}'
      printf '%s\n' "$TRUTHCHECK_SUMMARY" > "$TRUTHCHECK_OUT"
    else
      echo "  PR-E: ${TRUTHCHECK_COUNT} fixture goal(s) to verify"
      TRUTHCHECK_BASE_URL="${VG_BASE_URL:-${VG_OPENAPI_PROBE_URL:-http://localhost:4000/api/v1/openapi.json}}"
      TRUTHCHECK_BASE_URL="${TRUTHCHECK_BASE_URL%/api/v1/openapi.json}"
      if [ -z "$TRUTHCHECK_BASE_URL" ]; then
        echo "⛔ PR-E BLOCK: cannot resolve TRUTHCHECK_BASE_URL (set VG_BASE_URL)."
        exit 1
      fi

      TRUTHCHECK_ITER=0
      TRUTHCHECK_MAX_ITER=5
      TRUTHCHECK_FAILED_GOALS="$TRUTHCHECK_GOALS"

      while [ "$TRUTHCHECK_ITER" -lt "$TRUTHCHECK_MAX_ITER" ] && \
            [ -n "$TRUTHCHECK_FAILED_GOALS" ]; do
        TRUTHCHECK_ITER=$((TRUTHCHECK_ITER + 1))
        echo "  PR-E iter ${TRUTHCHECK_ITER}/${TRUTHCHECK_MAX_ITER}: running ${TRUTHCHECK_FAILED_GOALS}"

        ITER_FAILED=""
        for gid in $TRUTHCHECK_FAILED_GOALS; do
          PHASE_DIR="$PHASE_DIR" PHASE_NUMBER="$PHASE_NUMBER" REPO_ROOT="$REPO_ROOT" \
          TRUTHCHECK_BASE_URL="$TRUTHCHECK_BASE_URL" GID="$gid" PYTHON_BIN="${PYTHON_BIN:-python3}" \
          VG_SCRIPT_ROOT="$VG_SCRIPT_ROOT" \
          ${PYTHON_BIN:-python3} - <<'PY' 2>&1 | sed "s/^/    [${gid}] /"
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.environ["VG_SCRIPT_ROOT"])

from runtime.fixture_cache import acquire_lease, release_lease, recipe_hash, write_captured
from runtime.recipe_executor import RecipeRunner
from runtime.recipe_loader import load_recipe

phase_dir = Path(os.environ["PHASE_DIR"])
phase = os.environ.get("PHASE_NUMBER") or "unknown"
repo_root = Path(os.environ["REPO_ROOT"])
base_url = os.environ["TRUTHCHECK_BASE_URL"]
gid = os.environ["GID"]

def load_credentials_map(config_path: Path) -> dict:
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        m = re.search(r"^credentials:\s*\n(?P<body>(?:[ \t].*\n)+)", text, re.MULTILINE)
        if m:
            try:
                import yaml  # type: ignore
                full = yaml.safe_load("credentials:\n" + m.group("body"))
                if isinstance(full, dict):
                    creds = full.get("credentials")
                    if isinstance(creds, dict):
                        return creds
            except Exception:
                pass
    env_creds = os.environ.get("VG_CREDENTIALS_JSON")
    if env_creds:
        try:
            parsed = json.loads(env_creds)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}

config_path = repo_root / ".claude" / "vg.config.md"
credentials_map = load_credentials_map(config_path)
if not credentials_map:
    raise RuntimeError(
        f"credentials_map empty — load from {config_path} OR set VG_CREDENTIALS_JSON"
    )

fixture_path = phase_dir / "FIXTURES" / f"{gid}.yaml"
recipe = load_recipe(fixture_path)
recipe_text = fixture_path.read_text(encoding="utf-8")
owner_session = f"build-{phase}-{os.getpid()}"

acquire_lease(
    phase_dir, gid,
    owner_session=owner_session,
    consume_semantics=(recipe.get("consume_semantics") or "read_only"),
    recipe_hash_value=recipe_hash(recipe_text),
)
try:
    runner = RecipeRunner(
        base_url=base_url,
        env=os.environ.get("VG_ENV", "sandbox"),
        credentials_map=credentials_map,
    )
    captured = runner.run(recipe)
    write_captured(
        phase_dir, gid, captured,
        owner_session=owner_session,
        recipe_hash_value=recipe_hash(recipe_text),
    )
    print(f"PASS — captured: {sorted(captured.keys())}")
finally:
    release_lease(phase_dir, gid, owner_session)
PY
          if [ "${PIPESTATUS[0]}" -ne 0 ]; then
            ITER_FAILED="$ITER_FAILED $gid"
          fi
        done

        TRUTHCHECK_FAILED_GOALS=$(echo "$ITER_FAILED" | xargs)
        if [ -z "$TRUTHCHECK_FAILED_GOALS" ]; then
          echo "  PR-E: all goals PASS at iter ${TRUTHCHECK_ITER}"
          TRUTHCHECK_SUMMARY=$(${PYTHON_BIN:-python3} -c "import json; print(json.dumps({'verdict':'PASS','iterations':${TRUTHCHECK_ITER},'goals':${TRUTHCHECK_COUNT}}))")
          printf '%s\n' "$TRUTHCHECK_SUMMARY" > "$TRUTHCHECK_OUT"
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "build.api_truthcheck_passed" \
            --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"iterations\":${TRUTHCHECK_ITER},\"goals\":${TRUTHCHECK_COUNT}}" \
            >/dev/null 2>&1 || true
          break
        fi
      done

      if [ -n "$TRUTHCHECK_FAILED_GOALS" ]; then
        TRUTHCHECK_SUMMARY=$(${PYTHON_BIN:-python3} -c "import json; print(json.dumps({'verdict':'BLOCK','iterations':${TRUTHCHECK_MAX_ITER},'failed':'$TRUTHCHECK_FAILED_GOALS'}))")
        printf '%s\n' "$TRUTHCHECK_SUMMARY" > "$TRUTHCHECK_OUT"
        echo "  PR-E: iter cap hit, ${TRUTHCHECK_FAILED_GOALS} still failing"
        DIAGNOSTIC_L2="${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py"
        [ -f "$DIAGNOSTIC_L2" ] || DIAGNOSTIC_L2="${REPO_ROOT}/scripts/spawn-diagnostic-l2.py"
        if [ -f "$DIAGNOSTIC_L2" ]; then
          echo "  PR-E: spawning diagnostic_l2 for residual failures"
          echo "$TRUTHCHECK_FAILED_GOALS" > "${PHASE_DIR}/.api-truthcheck-failed.txt"
          "${PYTHON_BIN:-python3}" "$DIAGNOSTIC_L2" \
            --phase "${PHASE_NUMBER:-${PHASE_ARG}}" \
            --gate-id "build.api_truthcheck" \
            --evidence-file "${PHASE_DIR}/.api-truthcheck-failed.txt" 2>&1 | sed 's/^/    /' || true
          TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
          [ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
          if [ -f "$TESTER_PRO_CLI" ]; then
            for gid in $TRUTHCHECK_FAILED_GOALS; do
              "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" \
                defect new --phase "${PHASE_NUMBER:-${PHASE_ARG}}" \
                --title "[API-TRUTHCHECK] ${gid} fails recipe execution after ${TRUTHCHECK_MAX_ITER} iter" \
                --severity major --found-in build \
                --goals "$gid" \
                --notes "L2 proposal pending; see .api-truthcheck-failed.txt" 2>/dev/null || true
            done
          fi
        fi
        echo "  PR-E: BLOCK — fix path:"
        echo "    1. User accept L2 proposal → re-run /vg:build --resume=truthcheck"
        echo "    2. /vg:build --skip-truthcheck --override-reason=\"...\" (debt)"
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
          "build.api_truthcheck_blocked" \
          --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"failed\":\"$TRUTHCHECK_FAILED_GOALS\"}" \
          >/dev/null 2>&1 || true
        exit 1
      fi
    fi
  fi
fi

# v4.0.x Item 4 (Codex deferred) — PR-E read-endpoint light probe.
# Existing PR-E truthcheck covers mutation goals with FIXTURES only.
# Read endpoints (GET) + endpoints declared in API-CONTRACTS.md but not mapped
# to any goal slip through to review step 5b runtime fail. This adds a LIGHT
# probe: single curl per declared endpoint, checking only for 404 (phantom
# endpoint signal). 4xx/5xx with auth-required body or schema mismatch are
# treated as "responding" (endpoint exists, just needs auth/payload).
# Output: ${PHASE_DIR}/.pr-e-read-probe.json with per-endpoint verdict.
# ADVISORY only — phantom endpoints already caught by static contract-runtime
# gate (commit 564a39a + Item 1 wave advisory); this is defense-in-depth.
# No D18 coverage, no idempotency replay, no auth boundary check —
# just "does endpoint exist and respond reasonably" (non-mutation, read-only).
if [ -d "apps/api/src" ] || [ -f "apps/api/package.json" ]; then
  API_BASE_URL="${VG_API_BASE_URL:-http://localhost:4000}"
  PR_E_READ_PROBE_OUT="${PHASE_DIR}/.pr-e-read-probe.json"
  if curl -fsS --max-time 2 "${API_BASE_URL}/health" >/dev/null 2>&1 || \
     curl -fsS --max-time 2 "${API_BASE_URL}" >/dev/null 2>&1; then
    # API alive — extract GET endpoints from API-CONTRACTS.md and light-probe each
    export PHASE_DIR API_BASE_URL
    ${PYTHON_BIN:-python3} - <<'PYEOF' > "$PR_E_READ_PROBE_OUT"
import os, re, json, subprocess
from pathlib import Path

phase_dir = Path(os.environ.get("PHASE_DIR", "."))
contracts = phase_dir / "API-CONTRACTS.md"
api_base = os.environ.get("API_BASE_URL", "http://localhost:4000")

endpoints = []
if contracts.is_file():
    # Pattern: `## METHOD /path` or `### METHOD /path`
    pat = re.compile(r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)", re.M)
    for m in pat.finditer(contracts.read_text(encoding="utf-8", errors="ignore")):
        endpoints.append({"method": m.group(1), "path": m.group(2)})

results = []
for ep in endpoints:
    # Replace path params with placeholder (e.g., :id, {id}, ${id} → 1)
    probe_path = re.sub(r":\w+|\{[^}]+\}|\$\{[^}]+\}", "1", ep["path"])
    url = f"{api_base}{probe_path}"
    try:
        # Light probe: curl -sS, 2s timeout. We care about status code only.
        out = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "2", "-X", ep["method"], url],
            capture_output=True, text=True, timeout=5,
        )
        code = (out.stdout or "0").strip()
    except Exception:
        code = "ERR"
    verdict = "missing" if code == "404" else (
        "ok" if code and code != "0" and code != "ERR" else "unreachable"
    )
    results.append({
        "method": ep["method"], "path": ep["path"],
        "probe_url": url, "http_code": code, "verdict": verdict,
    })

missing = [r for r in results if r["verdict"] == "missing"]
print(json.dumps({
    "verdict": "WARN" if missing else "PASS",
    "endpoint_count": len(endpoints),
    "missing_count": len(missing),
    "missing": missing,
    "all_results": results,
}, indent=2))
PYEOF

    READ_PROBE_RC=$?
    MISSING_COUNT=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('$PR_E_READ_PROBE_OUT')); print(d.get('missing_count', 0))" 2>/dev/null || echo "0")
    if [ "${MISSING_COUNT:-0}" -gt 0 ]; then
      echo "⚠ PR-E read-probe: ${MISSING_COUNT} phantom endpoint(s) detected (404 on light probe). See ${PR_E_READ_PROBE_OUT}"
      echo "   Static contract-runtime gate (build close) should have already blocked these. If you reached here, the static gate was skipped via --skip-contract-runtime."
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "build.pr_e_read_probe_completed" \
        --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"missing\":${MISSING_COUNT}}" \
        >/dev/null 2>&1 || true
    else
      echo "  PR-E read-probe: all declared endpoints respond (read_endpoint_coverage advisory: PASS)"
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "build.pr_e_read_probe_completed" \
        --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"missing\":0}" \
        >/dev/null 2>&1 || true
    fi
  else
    echo "  PR-E read-probe: API not responding at ${API_BASE_URL} — skip light probe"
  fi
fi

# F3 Batch 10: strict marker check — run_id match (propagated from test/close.md Batch 9)
MARKER_LIB="${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg/_shared}/lib/marker-schema.sh"
[ -f "$MARKER_LIB" ] || MARKER_LIB="commands/vg/_shared/lib/marker-schema.sh"
[ -f "$MARKER_LIB" ] || MARKER_LIB=".claude/commands/vg/_shared/lib/marker-schema.sh"
if [ -f "$MARKER_LIB" ]; then
  source "$MARKER_LIB"
  export VG_MARKER_STRICT=1
  if ! verify_all_markers_strict_runid "${PHASE_DIR}" "${PHASE_NUMBER}" "${VG_RUN_ID:-}"; then
    echo "⛔ Marker integrity gate failed — empty/stale/forged markers detected" >&2
    echo "   Set VG_MARKER_STRICT=0 to bypass (UNSAFE — only for migration)." >&2
    exit 1
  fi
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ build run-complete BLOCK — review orchestrator output + fix before /vg:review" >&2
  exit $RUN_RC
fi

PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN:-python3} -c "
import json; from datetime import datetime; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
now = datetime.now().isoformat()
s['status'] = 'executed'
s['pipeline_step'] = 'build-complete'
s['updated_at'] = now
prev = s.get('steps', {}).get('build', {})
prev.update({
    'status': 'built-complete',
    'finished_at': now,
    'reason': 'CrossAI loop and run-complete passed',
})
s.setdefault('steps', {})['build'] = prev
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* executed/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```
</content>
</invoke>