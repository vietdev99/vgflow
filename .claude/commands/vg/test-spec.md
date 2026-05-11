---
name: vg:test-spec
description: Post-build deep test-spec authoring — derive lifecycle specs and fixture DAG before review
argument-hint: "<phase> [--regen] [--max-files=N]"
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
    - path: "${PHASE_DIR}/PLAYWRIGHT-SPEC-PLAN.md"
      content_min_bytes: 180
    - path: "${PHASE_DIR}/TEST-SPEC-GAPS.md"
      content_min_bytes: 40
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_build_artifact_gate"
    - "2_generate_deep_specs"
    - "3_validate_deep_specs"
    - "4_complete"
  must_emit_telemetry:
    - event_type: "test_spec.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "test_spec.generated"
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
`specs → scope → blueprint → build → test-spec → review → test → accept`
</objective>

<rules>
1. This command is post-build only. Missing `SUMMARY*.md`, `BUILD-LOG.md`, or
   `.build-progress.json` BLOCKs with guidance to run `/vg:build`.
2. It authors test-depth contracts, not executable Playwright specs. Executable
   specs still belong to `/vg:test`.
3. Mutation and multi-actor goals must get closed-loop RCRURDR coverage:
   read_before → create → read_after_create → update → read_after_update →
   delete → read_after_delete.
4. Fixture dependencies must be explicit: actors, sessions, resource ownership,
   artifact sinks, cleanup order.
5. Review consumes these artifacts. If review finds runtime blockers, stay in
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
for tok in ${ARGUMENTS:-}; do
  case "$tok" in
    --max-files=*) MAX_FILES="${tok#--max-files=}" ;;
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

"${PYTHON_BIN:-python3}" "$SCRIPT" \
  --phase "${PHASE_NUMBER}" \
  --phase-dir "${PHASE_DIR}" \
  --root "${REPO_ROOT}" \
  --max-files "${MAX_FILES}" \
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

<step name="4_complete">
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
state["updated_at"] = datetime.now().isoformat()
p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
PY

touch "${PHASE_DIR}/.step-markers/test-spec/4_complete.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 4_complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.completed" --step "4_complete" --actor "llm-claimed" \
  --outcome "PASS" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
"${PYTHON_BIN:-python3}" "$ORCH" run-complete --outcome PASS 2>/dev/null || true

echo "✓ /vg:test-spec complete"
echo "  Wrote: ${PHASE_DIR}/DEEP-TEST-SPECS.md"
echo "  Wrote: ${PHASE_DIR}/LIFECYCLE-SPECS.json"
echo "  Wrote: ${PHASE_DIR}/TEST-FIXTURE-DAG.json"
echo "  Wrote: ${PHASE_DIR}/PLAYWRIGHT-SPEC-PLAN.md"
echo "  Next:  /vg:review ${PHASE_NUMBER}"
```
</step>

</process>

<success_criteria>
- Build evidence existed before generation.
- Deep test-spec artifacts exist and pass `verify-deep-test-specs.py`.
- `PIPELINE-STATE.json` marks `steps.test-spec.status=done`.
- Next command is `/vg:review <phase>`.
</success_criteria>
