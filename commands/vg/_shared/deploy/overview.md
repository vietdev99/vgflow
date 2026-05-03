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
       │     - check build-complete via PIPELINE-STATE (skipped if --pre-test)
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

## --pre-test mode (Task 20 — invoked from /vg:build STEP 6.5)

`/vg:deploy --pre-test` is a sanctioned pre-close invocation path. The
build pipeline calls it from STEP 6.5 (pre-test gate) BEFORE STEP 7
(close). Distinguishing pre-test from post-close deploys lets downstream
`/vg:test` and `/vg:review` make different smoke decisions per env.

Behavior when `--pre-test` is set:

| Aspect | Default deploy | `--pre-test` mode |
|---|---|---|
| build-complete check | required (or `--allow-build-incomplete` + override) | bypassed (sanctioned) |
| `--non-interactive` | optional | required (build is non-interactive) |
| `deployed.<env>.mode` field | `"post-close"` | `"pre-test"` |
| override-debt logged | yes (if `--allow-build-incomplete`) | no — not a manual override |
| Telemetry event | `phase.deploy_started`/`completed` | + `deploy.pre_test_invoked` |

Step 0 bypass block:

```bash
PRE_TEST_MODE=false
if [[ "$ARGUMENTS" =~ --pre-test ]]; then
  PRE_TEST_MODE=true
  echo "▸ /vg:deploy --pre-test: bypass build-complete check (pre-close invocation from build STEP 6.5)"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "deploy.pre_test_invoked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
fi

# Existing build_complete gate, now skipped when PRE_TEST_MODE=true:
if [ "$PRE_TEST_MODE" = "false" ] && [ ! -f "${PHASE_DIR}/.step-markers/12_run_complete.done" ]; then
  if [[ ! "$ARGUMENTS" =~ --allow-build-incomplete ]]; then
    echo "⛔ /vg:deploy: build not complete. Run /vg:build first or pass --allow-build-incomplete + --override-reason"
    exit 1
  fi
fi
```

Step 2 (DEPLOY-STATE merge) writes `mode` per env:

```python
deployed_entry = {
    "url": deployed_url,
    "deployed_at": iso_timestamp,
    "phase": phase_number,
    "mode": "pre-test" if pre_test_mode else "post-close",
}
```

