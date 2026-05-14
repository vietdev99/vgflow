# Pass 3 — Multi-actor workflow specs (Task 40, Bug H)

## Position in pipeline

```
2b_contracts (Pass 1) → ... → 2b6d_fe_contracts (Pass 2 Task 38) → 2b7_flow_detect →
2b8_rcrurdr_invariants (Task 22 + Task 39) → 2b9_workflows (Pass 3 — THIS) → 2c_verify
```

Pass 3 runs AFTER all schema-emitting steps so the subagent can reference
real goal_ids, real endpoint paths, real component names from FE artifacts.

## Steps

1. Read `_shared/blueprint/workflows-delegation.md` for the prompt template.
2. Spawn `Agent(subagent_type="vg-blueprint-workflows", prompt=<delegation>)` —
   narrate spawn + return per UX baseline R2 (`scripts/vg-narrate-spawn.sh`).
3. Parse return JSON `workflows[]`:
   - For each entry: write `${PHASE_DIR}/WORKFLOW-SPECS/<filename>` containing
     ```` ```yaml\n<yaml_body>\n``` ````.
   - Write `${PHASE_DIR}/WORKFLOW-SPECS/index.md`: `# WORKFLOW-SPECS index\n\n- WF-001\n- WF-002\n` (or `flows: []` when none).
   - Concat all WF bodies into `${PHASE_DIR}/WORKFLOW-SPECS.md` (flat) for legacy reads.
4. Run `python3 scripts/validators/verify-workflow-specs.py --workflows-dir ${PHASE_DIR}/WORKFLOW-SPECS`.
5. On validator pass: emit `blueprint.workflows_pass_completed` event.
6. On validator fail: route through Task 33 wrapper (auto-fix subagent option).

## Backward compat

- Phases without multi-actor workflows: subagent returns `no_workflows_detected: true`. Orchestrator writes empty `index.md` with `flows: []`. Validator passes.
- `--skip-workflows --override-reason="..."` available for legacy phases.

## Bash gate (Batch 32 — was SCAFFOLD)

Audit found this step was prose only. Required: step-active, real validator
invoke, mark-step with exit-on-fail gate.

```bash
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" step-active 2b9_workflows >/dev/null 2>&1 || true

# Profile gate: profiles not declared in blueprint.md must_mark skip
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-fullstack|web-frontend-only|backend-multi-actor)
    : ;;
  *)
    echo "ℹ 2b9_workflows SKIPPED (profile=${PHASE_PROFILE} not multi-actor)"
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" mark-step blueprint 2b9_workflows 2>/dev/null || true
    return 0 2>/dev/null || exit 0
    ;;
esac

# Skip flag escape
if [[ "${ARGUMENTS:-}" =~ --skip-workflows ]]; then
  echo "⚠ 2b9_workflows skipped (--skip-workflows debt logged)"
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" mark-step blueprint 2b9_workflows 2>/dev/null || true
  return 0 2>/dev/null || exit 0
fi

WF_RC=0
if [ -d "${PHASE_DIR}/WORKFLOW-SPECS" ]; then
  set +e
  "${PYTHON_BIN:-python3}" scripts/validators/verify-workflow-specs.py \
    --workflows-dir "${PHASE_DIR}/WORKFLOW-SPECS" \
    > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/workflows-validator.out" \
    2> "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/workflows-validator.err"
  WF_RC=$?
  set -e
else
  # No WORKFLOW-SPECS dir produced — subagent must explicitly mark no_workflows_detected.
  # If subagent ran and returned that, an empty index.md should exist; without it: FAIL.
  WF_RC=1
fi

if [ "$WF_RC" -ne 0 ]; then
  echo "⛔ Batch 32 2b9: verify-workflow-specs.py rc=${WF_RC}" >&2
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
    emit-event "blueprint.workflows_pass_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"rc\":${WF_RC}}" >/dev/null 2>&1 || true
  exit 1
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  emit-event "blueprint.workflows_pass_completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" \
  mark-step blueprint 2b9_workflows 2>/dev/null || true
echo "✓ Batch 32: 2b9_workflows marked"
```
