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

<step name="2b9_workflows">

## Lifecycle wrapper (R6 Task 1 — wire missing marker)

```bash
# Skip-flag check (forbidden_without_override paired)
if [[ "$ARGUMENTS" =~ --skip-workflows ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-workflows requires --override-reason=<text>"
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.workflows_pass_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"--skip-workflows\"}" 2>/dev/null || true
  # Canonical override.used emit — runtime_contract.forbidden_without_override
  # requires an exact override.used.flag match for --skip-workflows before
  # run-complete will pass.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--skip-workflows" \
    --reason "Pass 3 multi-actor workflow specs skipped (phase ${PHASE_NUMBER})" \
    >/dev/null 2>&1 || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-workflows-skipped" "${PHASE_NUMBER}" \
      "Pass 3 multi-actor workflow specs skipped" "$PHASE_DIR"
  exit 0
fi

# Profile-gate (web-fullstack, web-frontend-only, backend-multi-actor)
case "${PHASE_PROFILE:-feature}" in
  web-fullstack|web-frontend-only|backend-multi-actor) ;;
  *)
    echo "ℹ Profile ${PHASE_PROFILE} — skipping 2b9_workflows (multi-actor profiles only)"
    exit 0
    ;;
esac

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2b9_workflows

# Spawn vg-blueprint-workflows subagent (narrate per UX baseline R2)
bash .claude/scripts/vg-narrate-spawn.sh vg-blueprint-workflows spawning \
  "phase ${PHASE_NUMBER} multi-actor workflow specs"
# AI: now spawn:
#   Agent(subagent_type="vg-blueprint-workflows",
#         prompt=<from workflows-delegation.md>)
# AI: parse return JSON `workflows[]`. For each entry write
#     ${PHASE_DIR}/WORKFLOW-SPECS/<filename> with ```yaml<body>``` body.
# AI: write ${PHASE_DIR}/WORKFLOW-SPECS/index.md (or `flows: []` when none).
# AI: concat bodies into ${PHASE_DIR}/WORKFLOW-SPECS.md (Layer 3 legacy).
# AI: post-spawn narration:
#   bash .claude/scripts/vg-narrate-spawn.sh vg-blueprint-workflows returned \
#     "<count> workflows"

# Run validator
"${PYTHON_BIN:-python3}" scripts/validators/verify-workflow-specs.py \
  --workflows-dir "${PHASE_DIR}/WORKFLOW-SPECS"
VAL_RC=$?
if [ "$VAL_RC" -eq 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.workflows_pass_completed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
else
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.workflows_pass_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"validator_rc\":${VAL_RC}}" 2>/dev/null || true
  echo "⛔ workflow-specs validator failed (rc=${VAL_RC})" >&2
  exit 1
fi

# Lifecycle close
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER}" "2b9_workflows" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/2b9_workflows.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b9_workflows 2>/dev/null || true
```

</step>
