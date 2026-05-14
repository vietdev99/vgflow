---
name: vg:test-spec
description: Post-review deep test-spec authoring — derive lifecycle specs, fixture DAG, localizer prompt, and execution plan consuming RUNTIME-MAP from review
argument-hint: "<phase> [--regen] [--max-files=N] [--ai-response=path] [--crossai-review] [--no-crossai-review]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
  - TodoWrite
runtime_contract:
  must_write:
    - path: "${PHASE_DIR}/DEEP-TEST-SPECS.md"
      content_min_bytes: 400
    - path: "${PHASE_DIR}/LIFECYCLE-SPECS.json"
      content_min_bytes: 80
    - path: "${PHASE_DIR}/TEST-FIXTURE-DAG.json"
      content_min_bytes: 80
    - path: "${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
      content_min_bytes: 80
    - path: "${PHASE_DIR}/TEST-SPEC-LOCALIZER/REQUEST.json"
      content_min_bytes: 80
    - path: "${PHASE_DIR}/TEST-SPEC-LOCALIZER/PROMPT.md"
      content_min_bytes: 200
    - path: "${PHASE_DIR}/PLAYWRIGHT-SPEC-PLAN.md"
      content_min_bytes: 180
    - path: "${PHASE_DIR}/TEST-SPEC-GAPS.md"
      content_min_bytes: 40
    - path: "tests/e2e/lifecycle/"
      min_files: 1
      pattern: "*.spec.ts"
    - path: "${PHASE_DIR}/CODEGEN-MANIFEST.json"
      min_bytes: 100
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_build_artifact_gate"
    - "2_generate_deep_specs"
    - "3_validate_deep_specs"
    - "3_crossai_sweep"
    - "4_codegen"
    - "4_self_review"
    - "5_complete"
  must_emit_telemetry:
    - event_type: "test_spec.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "test_spec.generated"
      phase: "${PHASE_NUMBER}"
    - event_type: "test_spec.crossai_skipped"
      phase: "${PHASE_NUMBER}"
    - event_type: "test_spec.crossai_completed"
      phase: "${PHASE_NUMBER}"
    - event_type: "test_spec.completed"
      phase: "${PHASE_NUMBER}"
---

<LANGUAGE_POLICY>
Follow `_shared/language-policy.md`. Default narration is Vietnamese; file
paths, command names, JSON keys, and code identifiers stay English.
</LANGUAGE_POLICY>

<objective>
Run the dedicated deep test-spec lane after `/vg:build` and before
`/vg:review`.

Why this exists:
- Blueprint is too early: implemented DOM, route files, API handlers, generated
  UI, and concrete form state may not exist yet.
- Build must not self-certify runtime coverage.
- Review should verify runtime against a pre-authored deep spec contract, not
  discover test depth late and route it ambiguously.

Pipeline:
`specs → scope → blueprint → build → review → test-spec → test → accept`
</objective>

<rules>
1. This command is post-build only. Missing `SUMMARY*.md`, `BUILD-LOG.md`, or
   `.build-progress.json` BLOCKs with guidance to run `/vg:build`.
2. It authors test-depth contracts, not executable test specs. Executable
   specs still belong to `/vg:test`.
3. Mutation and multi-actor goals must get closed-loop RCRURDR coverage:
   read_before → create → read_after_create → update → read_after_update →
   delete → read_after_delete.
4. Fixture dependencies must be explicit: actors, sessions, resource ownership,
   artifact sinks, cleanup order.
5. VG is profile-aware. Web may use Playwright, mobile may use Maestro/Appium/native,
   CLI may use command assertions, backend may use HTTP/RPC/job checks, library may
   use unit/property tests.
6. Review consumes these artifacts. If review finds runtime blockers, stay in
   review/debug. If runtime is clean but executable specs are missing, route to
   `/vg:test`.
</rules>

<process>

<step name="0_parse_and_validate">
```bash
set -euo pipefail

REPO_ROOT="$(pwd)"
PHASE_NUMBER="$(printf '%s\n' "${ARGUMENTS:-}" | awk '{print $1}')"
if [ -z "${PHASE_NUMBER:-}" ]; then
  echo "⛔ Missing phase. Usage: /vg:test-spec <phase>"
  exit 1
fi

VG_HOME="${VG_HOME:-${HOME}/.vgflow}"
ORCH="${REPO_ROOT}/.claude/scripts/vg-orchestrator"
[ -e "$ORCH" ] || ORCH="${VG_HOME}/scripts/vg-orchestrator"
if [ ! -e "$ORCH" ]; then
  echo "⛔ vg-orchestrator missing. Re-sync VGFlow global install."
  exit 1
fi

MAX_FILES="1200"
AI_RESPONSE=""
for tok in ${ARGUMENTS:-}; do
  case "$tok" in
    --max-files=*) MAX_FILES="${tok#--max-files=}" ;;
    --ai-response=*) AI_RESPONSE="${tok#--ai-response=}" ;;
    --regen) ;;
    *) ;;
  esac
done

PHASE_RESOLVER="${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-resolver.sh"
[ -f "$PHASE_RESOLVER" ] || PHASE_RESOLVER="${VG_HOME}/commands/vg/_shared/lib/phase-resolver.sh"
source "$PHASE_RESOLVER" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR="$(resolve_phase_dir "$PHASE_NUMBER")"
else
  PHASE_DIR="$(ls -d "${REPO_ROOT}/.vg/phases/${PHASE_NUMBER}"* "${REPO_ROOT}/.vg/phases/$(printf '%02d' "$PHASE_NUMBER" 2>/dev/null)"* 2>/dev/null | head -1)"
fi
if [ -z "${PHASE_DIR:-}" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "⛔ Phase dir not found for ${PHASE_NUMBER}"
  exit 1
fi

"${PYTHON_BIN:-python3}" "$ORCH" run-start vg:test-spec "${PHASE_NUMBER}" "${ARGUMENTS:-}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}
mkdir -p "${PHASE_DIR}/.step-markers/test-spec"
touch "${PHASE_DIR}/.step-markers/test-spec/0_parse_and_validate.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 0_parse_and_validate 2>/dev/null || true
"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.started" --step "0_parse_and_validate" --actor "llm-claimed" \
  --outcome "INFO" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
```
</step>

<step name="1_build_artifact_gate">
```bash
if ! ls "${PHASE_DIR}"/SUMMARY*.md >/dev/null 2>&1 && \
   [ ! -f "${PHASE_DIR}/BUILD-LOG.md" ] && \
   [ ! -d "${PHASE_DIR}/BUILD-LOG" ] && \
   [ ! -f "${PHASE_DIR}/.build-progress.json" ]; then
  echo "⛔ /vg:test-spec requires build evidence first."
  echo "   Run: /vg:build ${PHASE_NUMBER}"
  exit 1
fi

if [ ! -f "${PHASE_DIR}/TEST-GOALS.md" ] && [ ! -d "${PHASE_DIR}/TEST-GOALS" ]; then
  echo "⛔ /vg:test-spec requires TEST-GOALS from blueprint."
  echo "   Run: /vg:blueprint ${PHASE_NUMBER}"
  exit 1
fi

# Batch 34 F1: enforce review artifact consumption. Previously test-spec
# generation built from phase docs + static scan only — review outputs
# (RUNTIME-MAP, GOAL-COVERAGE-MATRIX, scan-*) silently dropped. Audit
# severity: CRITICAL.
if [ ! -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
  echo "⛔ Batch 34 F1: /vg:test-spec requires RUNTIME-MAP.json from /vg:review."
  echo "   Run: /vg:review ${PHASE_NUMBER}"
  echo "   Escape: --allow-no-review-artifacts (legacy phases, debt logged)"
  if [[ ! "${ARGUMENTS:-}" =~ --allow-no-review-artifacts ]]; then
    exit 1
  fi
  echo "⚠ Batch 34 F1: --allow-no-review-artifacts set, RUNTIME-MAP.json absent (debt logged)"
fi

if [ ! -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ] && [ ! -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json" ]; then
  echo "⛔ Batch 34 F1: /vg:test-spec requires GOAL-COVERAGE-MATRIX (md or json) from /vg:review."
  echo "   Run: /vg:review ${PHASE_NUMBER}"
  if [[ ! "${ARGUMENTS:-}" =~ --allow-no-review-artifacts ]]; then
    exit 1
  fi
fi

# Stale-matrix check: review SHA in matrix vs current HEAD. If matrix written
# before latest build commits, re-review recommended.
if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json" ] && [ -d "${PHASE_DIR}/.review-state" ]; then
  REVIEW_SHA=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json', encoding='utf-8'))
    print(d.get('build_sha', ''))
except Exception:
    print('')
" 2>/dev/null)
  HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
  if [ -n "$REVIEW_SHA" ] && [ -n "$HEAD_SHA" ] && [ "$REVIEW_SHA" != "$HEAD_SHA" ]; then
    echo "⚠ Batch 34 F1: GOAL-COVERAGE-MATRIX.json stale (review_sha=${REVIEW_SHA:0:8}, head=${HEAD_SHA:0:8})"
    echo "   Recommend: /vg:review ${PHASE_NUMBER} --retry-failed"
  fi
fi

touch "${PHASE_DIR}/.step-markers/test-spec/1_build_artifact_gate.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 1_build_artifact_gate 2>/dev/null || true
```
</step>

<step name="2_generate_deep_specs">
```bash
SCRIPT="${REPO_ROOT}/.claude/scripts/generate-deep-test-specs.py"
[ -f "$SCRIPT" ] || SCRIPT="${REPO_ROOT}/scripts/generate-deep-test-specs.py"
[ -f "$SCRIPT" ] || SCRIPT="${VG_HOME}/scripts/generate-deep-test-specs.py"
if [ ! -f "$SCRIPT" ]; then
  echo "⛔ generate-deep-test-specs.py missing. Re-sync VGFlow."
  exit 1
fi

AI_ARGS=()
if [ -n "${AI_RESPONSE:-}" ]; then
  AI_ARGS=(--ai-response "${AI_RESPONSE}")
fi

"${PYTHON_BIN:-python3}" "$SCRIPT" \
  --phase "${PHASE_NUMBER}" \
  --phase-dir "${PHASE_DIR}" \
  --root "${REPO_ROOT}" \
  --max-files "${MAX_FILES}" \
  "${AI_ARGS[@]}" \
  --json > "${PHASE_DIR}/.deep-test-spec-summary.json"

"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.generated" --step "2_generate_deep_specs" --actor "llm-claimed" \
  --outcome "PASS" --payload "$(cat "${PHASE_DIR}/.deep-test-spec-summary.json")" >/dev/null 2>&1 || true

touch "${PHASE_DIR}/.step-markers/test-spec/2_generate_deep_specs.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 2_generate_deep_specs 2>/dev/null || true
```
</step>

<step name="3_validate_deep_specs">
```bash
VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-deep-test-specs.py"
[ -f "$VALIDATOR" ] || VALIDATOR="${REPO_ROOT}/scripts/validators/verify-deep-test-specs.py"
[ -f "$VALIDATOR" ] || VALIDATOR="${VG_HOME}/scripts/validators/verify-deep-test-specs.py"
if [ ! -f "$VALIDATOR" ]; then
  echo "⛔ verify-deep-test-specs.py missing. Re-sync VGFlow."
  exit 1
fi

"${PYTHON_BIN:-python3}" "$VALIDATOR" --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.deep-test-spec-verify.json" 2>&1

touch "${PHASE_DIR}/.step-markers/test-spec/3_validate_deep_specs.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 3_validate_deep_specs 2>/dev/null || true
```
</step>

<step name="3_crossai_sweep">

## Step 3.5: CrossAI sweep (`3_crossai_sweep`)

Test-spec is the ONLY post-build artifact phase without CrossAI semantic review.
Deterministic validators (`verify-lifecycle-spec-depth.py`, `verify-deep-test-specs.py`)
catch SYNTAX gaps. They cannot catch SEMANTIC gaps — missing actors on multi-actor
goals, preconditions that contradict API contracts, fixture DAG cycles, RCRURDR
transition skips, cleanup order errors.

This step adds an adversarial gap-hunt sweep over LIFECYCLE-SPECS.json +
TEST-FIXTURE-DAG.json + TEST-EXECUTION-PLAN.json + DEEP-TEST-SPECS.md. Reuses
the shared `crossai-invoke.md` invoker (same pattern as `blueprint/verify.md:550+`).

### Trigger rules (Option B + A)

Flag precedence (highest first):
1. `--no-crossai-review` in `$ARGUMENTS` → SKIP unconditionally. Emit
   `test_spec.crossai_skipped` with reason `operator-override`.
2. `--crossai-review` in `$ARGUMENTS` → FORCE on regardless of profile / goals.
3. Auto-trigger condition (Option B):
   - ANY goal in LIFECYCLE-SPECS.json has `goal_type` containing `mutation` OR
     `multi-actor` OR `realtime` OR `financial` (high-stakes semantic surface)
   - OR `verify-lifecycle-spec-depth.py` previously returned WARN (not BLOCK)
   - OR profile in `{mobile, realtime, fintech}` from `vg.config.md`
   → FIRE the sweep.
4. None of the above → SKIP with reason `low-stakes-profile`. Emit
   `test_spec.crossai_skipped`.

```bash
vg-orchestrator step-active 3_crossai_sweep

CROSSAI_SHOULD_RUN="false"
CROSSAI_TRIGGER_REASON=""

if [[ "${ARGUMENTS}" =~ --no-crossai-review ]]; then
  CROSSAI_TRIGGER_REASON="operator-override-no"
elif [[ "${ARGUMENTS}" =~ --crossai-review ]]; then
  CROSSAI_SHOULD_RUN="true"
  CROSSAI_TRIGGER_REASON="operator-override-force"
else
  # Option B — auto-trigger heuristics.
  AUTO_TRIGGER=$(${PYTHON_BIN:-python3} - "${PHASE_DIR}" "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" <<'PY'
import json, os, sys
phase_dir = sys.argv[1]
profile = (sys.argv[2] or '').lower()
high_stakes_profiles = {'mobile', 'realtime', 'fintech', 'financial'}
high_stakes_goal_types = {'mutation', 'multi-actor', 'realtime', 'financial'}

if profile in high_stakes_profiles:
    print(f"profile-high-stakes:{profile}")
    sys.exit(0)

lifecycle_path = os.path.join(phase_dir, 'LIFECYCLE-SPECS.json')
if os.path.exists(lifecycle_path):
    try:
        data = json.load(open(lifecycle_path, encoding='utf-8'))
        goals = data.get('goals') or {}
        for gid, spec in goals.items():
            if not isinstance(spec, dict):
                continue
            gtype = str(spec.get('goal_type') or '').lower()
            if any(s in gtype for s in high_stakes_goal_types):
                print(f"goal-high-stakes:{gid}:{gtype}")
                sys.exit(0)
            actors = spec.get('actors') or {}
            if isinstance(actors, dict) and len(actors) >= 2:
                print(f"goal-multi-actor:{gid}")
                sys.exit(0)
    except Exception as e:
        print(f"lifecycle-parse-err:{e}", file=sys.stderr)

# Check lifecycle-depth verdict file if present
depth_verdict = os.path.join(phase_dir, '.tmp', 'lifecycle-spec-depth.json')
if os.path.exists(depth_verdict):
    try:
        v = json.load(open(depth_verdict, encoding='utf-8'))
        if str(v.get('severity') or '').lower() == 'warn':
            print("depth-warn")
            sys.exit(0)
    except Exception:
        pass

print("none")
PY
)
  if [ "$AUTO_TRIGGER" != "none" ] && [ -n "$AUTO_TRIGGER" ]; then
    CROSSAI_SHOULD_RUN="true"
    CROSSAI_TRIGGER_REASON="auto:${AUTO_TRIGGER}"
  else
    CROSSAI_TRIGGER_REASON="low-stakes-skip"
  fi
fi

if [ "$CROSSAI_SHOULD_RUN" != "true" ]; then
  echo "▸ CrossAI sweep SKIPPED (reason: ${CROSSAI_TRIGGER_REASON})"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "test_spec.crossai_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"${CROSSAI_TRIGGER_REASON}\"}" \
    >/dev/null 2>&1 || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test-spec 3_crossai_sweep 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/3_crossai_sweep.done"
else
  echo "▸ CrossAI sweep starting — phase ${PHASE_NUMBER} (trigger: ${CROSSAI_TRIGGER_REASON})"

  CROSSAI_CTX="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/vg-crossai-${PHASE_NUMBER}-test-spec-review.md"
  mkdir -p "$(dirname "$CROSSAI_CTX")" 2>/dev/null
  {
    echo "# CrossAI Test-Spec Sweep — Phase ${PHASE_NUMBER}"
    echo ""
    echo "Trigger reason: ${CROSSAI_TRIGGER_REASON}"
    echo ""
    echo "## Adversarial gap-hunt task"
    echo ""
    echo "Deterministic validators passed syntax. Now find SEMANTIC gaps:"
    echo "1. Multi-actor lifecycle: actors declared match the goal type?"
    echo "2. Preconditions: contradict API contract invariants? (e.g. items:[] when contract says owner always present)"
    echo "3. Fixture DAG: cycles? missing dependencies? cleanup order reverse-correct?"
    echo "4. RCRURDR: transition skips? read_after_X missing? assertions specific (not vague)?"
    echo "5. Cleanup chain: covers all test-owned fixtures? handles failure cleanup?"
    echo "6. Runner family (TEST-EXECUTION-PLAN.json): matches profile? non-web phase not forced into Playwright?"
    echo "7. Source assertions: mutation_evidence + persistence_check actually verifiable?"
    echo "8. Goal coverage: are there obvious goals from CONTEXT decisions that LIFECYCLE-SPECS missed?"
    echo ""
    echo "Verdict: pass (score >=7, no major gaps) | flag (>=5 minor gaps) | block (missing/wrong) | inconclusive (CLIs unreachable)."
    echo ""
    echo "## Artifacts"
    echo "---"; cat "${PHASE_DIR}/LIFECYCLE-SPECS.json" 2>/dev/null || echo '(LIFECYCLE-SPECS.json missing)'
    echo "---"; cat "${PHASE_DIR}/TEST-FIXTURE-DAG.json" 2>/dev/null || echo '(TEST-FIXTURE-DAG.json missing)'
    echo "---"; cat "${PHASE_DIR}/TEST-EXECUTION-PLAN.json" 2>/dev/null || echo '(TEST-EXECUTION-PLAN.json missing)'
    echo "---"; cat "${PHASE_DIR}/DEEP-TEST-SPECS.md" 2>/dev/null || echo '(DEEP-TEST-SPECS.md missing)'
    echo "---"; cat "${PHASE_DIR}/CONTEXT.md" 2>/dev/null || echo '(CONTEXT.md missing)'
    echo "---"; cat "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || echo '(API-CONTRACTS.md missing)'
  } > "$CROSSAI_CTX"

  export CONTEXT_FILE="$CROSSAI_CTX"
  export OUTPUT_DIR="${PHASE_DIR}/crossai"
  export LABEL="test-spec-review"
  source "${REPO_ROOT}/.claude/commands/vg/_shared/crossai-invoke.md" 2>/dev/null || true
  # crossai-invoke populates CROSSAI_VERDICT, OK_COUNT, TOTAL_CLIS, CLI_STATUS[]

  # Write summary digest to TEST-SPEC-CROSSAI.md for review to consume.
  {
    echo "# TEST-SPEC-CROSSAI.md — Phase ${PHASE_NUMBER}"
    echo ""
    echo "**Verdict:** ${CROSSAI_VERDICT:-unknown}"
    echo "**Trigger reason:** ${CROSSAI_TRIGGER_REASON}"
    echo "**CLIs agreed:** ${OK_COUNT:-?}/${TOTAL_CLIS:-?}"
    echo ""
    echo "## Raw findings"
    echo ""
    for f in "${PHASE_DIR}"/crossai/result-*test-spec-review*.xml; do
      [ -f "$f" ] || continue
      echo "### $(basename "$f")"
      echo '```xml'
      cat "$f"
      echo '```'
      echo ""
    done
  } > "${PHASE_DIR}/TEST-SPEC-CROSSAI.md"

  case "${CROSSAI_VERDICT:-unknown}" in
    pass)
      echo "✓ CrossAI: PASS (${OK_COUNT:-?}/${TOTAL_CLIS:-?} CLIs agreed)"
      ;;
    flag)
      echo "⚠ CrossAI: FLAG — minor concerns logged at ${PHASE_DIR}/TEST-SPEC-CROSSAI.md"
      echo "   Review will consume the findings; proceeding to 5_complete."
      ;;
    block)
      echo "⛔ CrossAI: BLOCK — major/critical gaps in test-spec contracts."
      echo "   ${PHASE_DIR}/TEST-SPEC-CROSSAI.md contains findings."
      echo "   Re-run with --regen to apply fixes, or --no-crossai-review to skip + log debt."
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "test_spec.crossai_completed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"verdict\":\"block\"}" \
        >/dev/null 2>&1 || true
      exit 2
      ;;
    inconclusive)
      echo "⛔ CrossAI: INCONCLUSIVE (${OK_COUNT:-0}/${TOTAL_CLIS:-?} CLIs reachable)"
      if [[ "$ARGUMENTS" =~ --allow-crossai-inconclusive ]]; then
        echo "  Override accepted — logging debt and proceeding."
      else
        echo "  Use --allow-crossai-inconclusive --override-reason='<X>' to proceed."
        exit 2
      fi
      ;;
  esac

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "test_spec.crossai_completed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"verdict\":\"${CROSSAI_VERDICT:-unknown}\",\"trigger\":\"${CROSSAI_TRIGGER_REASON}\"}" \
    >/dev/null 2>&1 || true

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test-spec 3_crossai_sweep 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/3_crossai_sweep.done"
fi
```

### Output consumed by review

`${PHASE_DIR}/TEST-SPEC-CROSSAI.md` — review preflight (already reads diagnostic surface per PR #183) extended to surface CrossAI verdict + findings count in `GOAL-COVERAGE-MATRIX.md` provenance.
</step>

<step name="4_codegen">

## Step 4: codegen (`4_codegen`)

Spawn `vg-test-codegen` subagent to generate Playwright lifecycle specs per goal. Smart-routing applies lens set per `goal_type` from `GOAL-COVERAGE-MATRIX.json`.

**Smart-routing lens map:**

| `goal_type` | Lens set |
|---|---|
| `mutation` | `idor` + `mass-assignment` + `authz-negative` + `business-logic` |
| `read` | `authz` + `info-disclosure` + `tenant-boundary` |
| `auth` | `auth-jwt` + `csrf` + `duplicate-submit` |
| `default` | `business-coherence` + `input-injection` |

**Subagent invocation:**

Read `commands/vg/_shared/test/codegen/delegation.md` and `commands/vg/_shared/test/codegen/overview.md` (existing files, no change). Then:

```
Agent(
  subagent_type="vg-test-codegen",
  prompt=<from delegation.md template>,
  input={
    phase_dir: "${PHASE_DIR}",
    phase_number: "${PHASE_NUMBER}",
    phase_profile: "${PHASE_PROFILE}",
    runtime_map_path: "${PHASE_DIR}/RUNTIME-MAP.json",
    goal_coverage_matrix_path: "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json",
    generated_tests_dir: "tests/e2e/lifecycle/",
    lens_routing_map: <smart-routing map above>
  }
)
```

**Output contract:**
- `tests/e2e/lifecycle/G-XX.{lens}.spec.ts` — one file per goal × lens
- `${PHASE_DIR}/CODEGEN-MANIFEST.json` — list of generated files + their L1/L2 binding state

**Post-spawn gate (F1 Batch 19):**

```bash
# F1 Batch 19: vg-test-codegen MUST write CODEGEN-MANIFEST.json + playwright
# spec files. Marker gates on those outputs (mirrors Batch 15 F3/F4 pattern).
CODEGEN_MANIFEST="${PHASE_DIR}/CODEGEN-MANIFEST.json"
if [ ! -f "$CODEGEN_MANIFEST" ]; then
  echo "⛔ F1 BLOCK: vg-test-codegen did not write CODEGEN-MANIFEST.json" >&2
  echo "   Codegen Agent spawn produced no output. Re-run /vg:test-spec ${PHASE_NUMBER}." >&2
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test_spec.codegen_missing_manifest" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
  exit 1
fi
# Spec count check — manifest must list playwright specs
SPEC_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
m = json.loads(open('${CODEGEN_MANIFEST}', encoding='utf-8').read())
specs = m.get('playwright_specs', m.get('specs', []))
print(len(specs))
" 2>/dev/null || echo "0")
if [ "${SPEC_COUNT:-0}" -lt 1 ]; then
  echo "⛔ F1 BLOCK: CODEGEN-MANIFEST.json contains 0 playwright specs" >&2
  echo "   vg-test-codegen claims to have run but produced no spec files." >&2
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test_spec.codegen_zero_specs" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
  exit 1
fi
echo "✓ F1: codegen wrote ${SPEC_COUNT} playwright specs"
```

**Batch 23: spec body coverage gate (post-F1, pre-run-complete):**

```bash
# Batch 23: spec body coverage gate — catch shallow specs.
STAGE_COV_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-spec-stage-coverage.py"
[ -f "$STAGE_COV_VAL" ] || STAGE_COV_VAL="${REPO_ROOT:-.}/scripts/validators/verify-spec-stage-coverage.py"
if [ -f "$STAGE_COV_VAL" ]; then
  if ! "${PYTHON_BIN:-python3}" "$STAGE_COV_VAL" \
       --phase-dir "${PHASE_DIR}" \
       --repo-root "${REPO_ROOT:-.}"; then
    echo "⛔ Batch 23 BLOCK: shallow spec(s) detected — codegen produced specs missing stage coverage" >&2
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
      "test_spec.spec_body_shallow" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

**Mark step:**
```bash
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 4_codegen 2>/dev/null || true
```

</step>

<step name="4_self_review">

## Step 4.5: codegen self-review (`4_self_review`)

After codegen, verify generated `.spec.ts` files compile via `npx playwright --list`. Catch syntax errors before `/vg:test` Step 2 execute time.

**Run check:**

```bash
SELF_REVIEW_LOG="${PHASE_DIR}/.step-markers/test-spec/4_self_review.log"
mkdir -p "$(dirname "$SELF_REVIEW_LOG")"

RETRY=0
MAX_RETRY=2
while [ $RETRY -le $MAX_RETRY ]; do
  if npx playwright --list tests/e2e/lifecycle/ > "$SELF_REVIEW_LOG" 2>&1; then
    echo "✓ Codegen self-review PASS (retry=$RETRY)"
    break
  fi
  RETRY=$((RETRY + 1))
  if [ $RETRY -gt $MAX_RETRY ]; then
    echo "⛔ Codegen self-review FAIL after $MAX_RETRY retries — see $SELF_REVIEW_LOG"
    echo "Escalate to user. Manual fix or rollback codegen."
    exit 1
  fi
  echo "⚠ Self-review FAIL (retry=$RETRY) — re-running codegen subagent"
  # Re-spawn vg-test-codegen with prior output context
done

"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 4_self_review 2>/dev/null || true
```

</step>

<step name="5_complete">
```bash
"${PYTHON_BIN:-python3}" - <<PY
import json
from datetime import datetime
from pathlib import Path
p = Path("${PHASE_DIR}") / "PIPELINE-STATE.json"
state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
state.setdefault("steps", {}).setdefault("test-spec", {})
state["steps"]["test-spec"].update({
    "status": "done",
    "verdict": "PASS",
    "updated_at": datetime.now().isoformat(),
})
state["pipeline_step"] = "test-spec-complete"
state["next_command"] = "/vg:review ${PHASE_NUMBER}"
state["next_command_emitted_at"] = datetime.now().isoformat() + "Z"
state["updated_at"] = datetime.now().isoformat()
p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
PY

touch "${PHASE_DIR}/.step-markers/test-spec/5_complete.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 5_complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.completed" --step "5_complete" --actor "llm-claimed" \
  --outcome "PASS" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
# F2 Batch 19: run-complete failure must NOT be swallowed. PASS verdict
# was written above (lines 521-525), but if run-complete fails the
# orchestrator contract validator caught a problem — surface it loudly.
if ! "${PYTHON_BIN:-python3}" "$ORCH" run-complete --outcome PASS 2>&1 | tee /tmp/run-complete-err.$$; then
  RC=${PIPESTATUS[0]:-1}
  echo "⛔ F2 BLOCK: test-spec run-complete failed (rc=$RC) — contract validator caught issue" >&2
  echo "   PASS verdict was written prematurely. Re-verify artifacts before retry." >&2
  rm -f /tmp/run-complete-err.$$
  exit 1
fi
rm -f /tmp/run-complete-err.$$

echo "✓ /vg:test-spec complete"
echo "  Wrote: ${PHASE_DIR}/DEEP-TEST-SPECS.md"
echo "  Wrote: ${PHASE_DIR}/LIFECYCLE-SPECS.json"
echo "  Wrote: ${PHASE_DIR}/TEST-FIXTURE-DAG.json"
echo "  Wrote: ${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
echo "  Wrote: ${PHASE_DIR}/TEST-SPEC-LOCALIZER/PROMPT.md"
echo "  Wrote: ${PHASE_DIR}/PLAYWRIGHT-SPEC-PLAN.md"
echo "  Next:  /vg:review ${PHASE_NUMBER}"
```
</step>

</process>

<success_criteria>
- Build evidence existed before generation.
- Deep test-spec artifacts exist and pass `verify-deep-test-specs.py`.
- `TEST-EXECUTION-PLAN.json` selects runner family from phase profile.
- `TEST-SPEC-LOCALIZER/PROMPT.md` exists for optional project-local AI expansion.
- `PIPELINE-STATE.json` marks `steps.test-spec.status=done`.
- Next command is `/vg:review <phase>`.
</success_criteria>
