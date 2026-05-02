# blueprint plan delegation contract (vg-blueprint-planner subagent)

## Input

Pass to `Agent(subagent_type="vg-blueprint-planner", prompt={...})`:

```json
{
  "phase_dir": "${PHASE_DIR}",
  "context_path": "${PHASE_DIR}/CONTEXT.md",
  "interface_standards_path": "${PHASE_DIR}/INTERFACE-STANDARDS.md",
  "design_refs": [
    "${PHASE_DIR}/UI-SPEC.md",
    "${PHASE_DIR}/UI-MAP.md"
  ],
  "must_cite_bindings": [
    "CONTEXT:decisions",
    "INTERFACE-STANDARDS:error-shape"
  ]
}
```

## Output (subagent returns)

```json
{
  "path": "${PHASE_DIR}/PLAN.md",
  "sha256": "<hex sha256 of PLAN.md contents>",
  "summary": "<one paragraph summary of plan structure>",
  "bindings_satisfied": ["CONTEXT:decisions", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```

## Main agent post-spawn validation

1. Open returned `path`, recompute sha256, assert match.
2. Confirm PLAN.md ≥ 500 bytes (content_min_bytes).
3. Confirm `bindings_satisfied` covers required `must_cite_bindings`.
4. If validation fails, retry up to 2 times, then escalate AskUserQuestion.

## Failure mode

If subagent returns error JSON (missing input, ORG 6-dim violation, etc.),
do NOT mark step done. Re-spawn after fixing input.
