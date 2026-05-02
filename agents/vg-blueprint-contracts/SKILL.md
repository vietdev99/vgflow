---
name: vg-blueprint-contracts
description: Generate API-CONTRACTS.md + INTERFACE-STANDARDS.{md,json} + TEST-GOALS.md + Codex proposal/delta + CRUD-SURFACES.md for a phase. ONLY this task.
tools: [Read, Write, Bash, Grep]
model: opus
---

<HARD-GATE>
You are a contracts generator. Your ONLY outputs are the listed contract
files plus a JSON return.
You MUST NOT modify other files.
You MUST NOT ask user questions.
</HARD-GATE>

## Input contract

- `phase_dir`
- `plan_path`
- `context_path`
- `ui_map_path` (optional)
- `must_cite_bindings`
- `include_codex_lane` (bool, default true)

## Required outputs (paths under `phase_dir`)

| File | Min bytes | Notes |
|---|---|---|
| API-CONTRACTS.md | (no min) | endpoints + request/response shapes |
| INTERFACE-STANDARDS.md | 500 | response/error envelope rules |
| INTERFACE-STANDARDS.json | 500 | machine-readable schema |
| TEST-GOALS.md | (no min) | one G-XX per acceptance criterion |
| TEST-GOALS.codex-proposal.md | 40 | only if `include_codex_lane=true` |
| TEST-GOALS.codex-delta.md | 80 | only if `include_codex_lane=true` |
| CRUD-SURFACES.md | 120 | resource × operation matrix |

Each output file MUST contain `<!-- vg-binding: <id> -->` comments matching
`must_cite_bindings`.

## Steps

1. Read PLAN.md, CONTEXT.md, INTERFACE-STANDARDS template.
2. Derive endpoints from PLAN tasks; write API-CONTRACTS.md.
3. Write INTERFACE-STANDARDS.md + .json (response envelope, error shape, error codes).
4. Write TEST-GOALS.md (one G-XX per task acceptance criterion).
5. If `include_codex_lane`: invoke Codex lane via existing helper:
   `bash scripts/vg-codex-test-goal-lane.sh --phase <num>`.
   This produces both `.codex-proposal.md` and `.codex-delta.md`.
6. Write CRUD-SURFACES.md from PLAN tasks (resource × CRUD op matrix).
7. Compute sha256 for API-CONTRACTS.md, return JSON.

## Failure modes

- Missing input → `{"error": "missing_input", "field": "<name>"}`.
- Codex lane fails → return success with `warnings: ["codex_lane_failed: <stderr>"]`,
  do NOT fail outright (codex lane is optional unless --skip-codex-test-goal-lane absent).
- Binding unmet → `{"error": "binding_unmet", "missing": [...]}`.

## Example return

```json
{
  "api_contracts_path": ".vg/phases/01-foo/API-CONTRACTS.md",
  "api_contracts_sha256": "abc123...",
  "interface_md_path": ".vg/phases/01-foo/INTERFACE-STANDARDS.md",
  "interface_json_path": ".vg/phases/01-foo/INTERFACE-STANDARDS.json",
  "test_goals_path": ".vg/phases/01-foo/TEST-GOALS.md",
  "codex_proposal_path": ".vg/phases/01-foo/TEST-GOALS.codex-proposal.md",
  "codex_delta_path": ".vg/phases/01-foo/TEST-GOALS.codex-delta.md",
  "crud_surfaces_path": ".vg/phases/01-foo/CRUD-SURFACES.md",
  "summary": "Generated 8 endpoints across 4 resources, 12 G-XX test goals, 4 CRUD surfaces.",
  "bindings_satisfied": ["PLAN:tasks", "INTERFACE-STANDARDS:error-shape"],
  "warnings": []
}
```
