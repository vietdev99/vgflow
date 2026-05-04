---
name: vg-blueprint-workflows
description: Generate WORKFLOW-SPECS for multi-actor cross-role workflows (Task 40 Pass 3). Reads BLOCK 5 + UI-MAP + VIEW-COMPONENTS + scope CONTEXT, emits per-workflow WF-NN.md files.
tools: Read, Bash, Grep
---

# vg-blueprint-workflows (Pass 3)

You generate per-workflow specs for multi-actor cross-role flows. Each
workflow involves ≥2 actors (e.g., user + admin) with a defined state
machine + per-step UI/API expectations.

## When this subagent runs

After Pass 2 (FE contracts) completes. UI-MAP, VIEW-COMPONENTS, BLOCK 5
all exist. Before close.

## Input artifacts

The delegation prompt cites:
- `${PHASE_DIR}/CONTEXT.md` (or scope output) — declares which workflows exist
- `${PHASE_DIR}/API-CONTRACTS/index.md` + per-endpoint files (BLOCKs 1-5)
- `${PHASE_DIR}/UI-MAP.md`
- `${PHASE_DIR}/VIEW-COMPONENTS.md`
- `${PHASE_DIR}/TEST-GOALS/index.md` + per-goal files (for goal_links)
- `${PHASE_DIR}/RCRURD-INVARIANTS/index.md` (for rcrurd_invariant_ref candidates)

## Output (return as JSON to orchestrator)

```json
{
  "workflows": [
    { "workflow_id": "WF-001", "filename": "WF-001.md", "yaml_body": "...full yaml..." }
  ],
  "no_workflows_detected": false,
  "notes": []
}
```

When CONTEXT.md declares no multi-actor workflows: return `no_workflows_detected: true` + empty `workflows[]`. Orchestrator writes only `index.md` with `flows: []`.

## Schema (per WF-NN.md)

Each workflow MUST declare these top-level keys:

| Key | Type | Required | Notes |
|---|---|---|---|
| `workflow_id` | string | yes | `WF-NN` (zero-padded 3-digit) |
| `name` | string | yes | Human-readable |
| `goal_links` | string[] | yes | List of `G-NN` cross-actor goals this workflow covers |
| `actors` | array | yes | Each: `{ role: user\|admin\|system\|..., cred_fixture: <FIXTURE_ENV_NAME> }` |
| `steps` | array | yes | Ordered list; see step schema below |
| `state_machine` | object | yes | `{ states: [...], transitions: [...] }` |
| `ui_assertions_per_step` | array | yes | Optional per-step UI expectations |

Step schema:
```yaml
- step_id: <int>
  actor: <role-name>            # must match an actors[].role
  cred_switch_marker: true      # REQUIRED when actor differs from previous step
  view: /path                   # FE route
  action: open_modal | submit | click | see_pending | ...
  target: ComponentName         # optional
  api: METHOD /path             # optional, but required when action implies API call
  state_after: { resource: state_value }  # state_value MUST be in state_machine.states[]
  goals: [G-NN, ...]            # optional goal_links subset
```

`cred_switch_marker: true` is injected at FE codegen level (Playwright `testRoleSwitch()` calls).
`rcrurd_invariant_ref: G-NN` links each ui_assertions_per_step entry to a per-goal RCRURD invariant.

## Anti-laziness rules

- DO NOT invent state names — every `state_after` value must appear in `state_machine.states[]`
- DO NOT skip `cred_switch_marker` when actor changes (FE codegen injects testRoleSwitch())
- DO NOT reference unknown goal_ids in `rcrurd_invariant_ref`
- DO NOT collapse step_id values (must be unique sequential integers)
- When CONTEXT.md does NOT declare workflows, return `no_workflows_detected: true` — DO NOT fabricate empty WF files
