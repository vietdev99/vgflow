# build close (STEP 7)

<!-- # Exception: oversized ref (539 lines) — combines step 10 + 12 from
     backup (90 + 395 = 485 source lines) plus PR-D OpenAPI export + PR-E
     truthcheck loop scaffolding; ceiling 600 in test_build_references_exist.py.
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
    'status': 'done',
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