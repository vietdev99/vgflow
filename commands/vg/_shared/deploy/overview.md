# Deploy — Overview (Shared Reference)

Loaded by `commands/vg/deploy.md` slim entry. Defines the orchestrator
flow at a glance. Detailed per-env executor contract lives in sibling
`per-env-executor-contract.md`.

## Flow diagram

    /vg:deploy <phase> [--envs=...] [--all-envs] [--dry-run] [--non-interactive] [--prod-confirm-token=...]
       │
       ▼
    Step 0   Parse args, validate prerequisites      (orchestrator)
       │     - resolve phase dir
       │     - check build-complete via PIPELINE-STATE
       │     - emit phase.deploy_started telemetry
       │
       ▼
    Step 0a  Select envs (multi-select) + prod gate  (orchestrator)
       │     - AskUserQuestion (or flags)
       │     - prod 3-option danger gate
       │     - validate envs in vg.config.md
       │
       ▼
    Step 1   Deploy loop (sequential per env)        (orchestrator + subagent)
       │     for env in selected:
       │       narrate-spawn green
       │       Agent(vg-deploy-executor)
       │       narrate-spawn cyan/red
       │       collect result
       │       on failure → AskUserQuestion (continue/skip/abort)
       │
       ▼
    Step 2   Merge results into DEPLOY-STATE.json    (orchestrator)
       │     - read existing (preserve preferred_env_for)
       │     - merge per-env results
       │     - emit phase.deploy_completed telemetry
       │
       ▼
    Final   mark + run-complete                      (orchestrator)

## Step responsibility split

| Step | Owner | Side effects | User interaction |
|---|---|---|---|
| 0    | orchestrator | telemetry start | none |
| 0a   | orchestrator | env selection persisted to vg.config | AskUserQuestion (env multi-select + prod gate) |
| 1    | orchestrator + subagent | deploy log per env | AskUserQuestion only on per-env failure |
| 2    | orchestrator | DEPLOY-STATE.json updated; telemetry end | none |
| Final | orchestrator | step marker + run-complete | none |

## Subagent boundary

`vg-deploy-executor` receives one env's exec context and returns a result
JSON. It does NOT:
- Read or write DEPLOY-STATE.json (orchestrator merges in Step 2 to
  preserve `preferred_env_for` keys per rule 5).
- Spawn other subagents (no nested Agent calls).
- Emit telemetry (orchestrator emits `phase.deploy_*` events).

It DOES:
- Run pre → build → restart → health-retry × 6 → seed.
- Append to `${PHASE_DIR}/.deploy-log.<env>.txt`.
- Return JSON `{env, sha, deployed_at, health, deploy_log, previous_sha, dry_run, error?}`.

## When orchestrator loads which ref

- `overview.md` (this file) — Step 1 + Step 2 (high-level flow).
- `per-env-executor-contract.md` — Step 1 (constructing spawn input + parsing return).
