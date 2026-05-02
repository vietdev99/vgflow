# blueprint contracts delegation contract (vg-blueprint-contracts subagent)

## Input

```json
{
  "phase_dir": "${PHASE_DIR}",
  "plan_path": "${PHASE_DIR}/PLAN.md",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "ui_map_path": "${PHASE_DIR}/UI-MAP.md",
  "must_cite_bindings": [
    "PLAN:tasks",
    "INTERFACE-STANDARDS:error-shape",
    "INTERFACE-STANDARDS:response-envelope"
  ],
  "include_codex_lane": true
}
```

## Output

```json
{
  "api_contracts_path": "${PHASE_DIR}/API-CONTRACTS.md",
  "api_contracts_sha256": "<hex>",
  "interface_md_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "interface_json_path": "${PHASE_DIR}/INTERFACE-STANDARDS.json",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "codex_proposal_path": "${PHASE_DIR}/TEST-GOALS.codex-proposal.md",
  "codex_delta_path": "${PHASE_DIR}/TEST-GOALS.codex-delta.md",
  "crud_surfaces_path": "${PHASE_DIR}/CRUD-SURFACES.md",
  "summary": "<one paragraph>",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape", ...],
  "warnings": []
}
```

## Main agent post-spawn validation

1. Each path exists with content_min_bytes per blueprint.md frontmatter
   (API-CONTRACTS.md no min, codex-proposal ≥ 40 bytes, codex-delta ≥ 80,
   CRUD-SURFACES.md ≥ 120 unless --crossai-only).
2. Recompute sha256 of API-CONTRACTS.md, assert match.
3. Confirm bindings_satisfied covers must_cite.
4. Failure → retry 2× then AskUserQuestion.
