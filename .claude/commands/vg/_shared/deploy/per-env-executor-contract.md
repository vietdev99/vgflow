# Deploy — Per-Env Executor Contract (Shared Reference)

The contract between `commands/vg/deploy.md` orchestrator (Step 1) and
`vg-deploy-executor` subagent. Mirrors spec §4 (canonical source).

## Spawn site (orchestrator Step 1, per env)

```bash
bash scripts/vg-narrate-spawn.sh vg-deploy-executor spawning "phase=$PHASE env=$ENV"
```

Then construct the prompt JSON and call:

```text
Agent(
  subagent_type="vg-deploy-executor",
  prompt={
    "phase": "<phase id>",
    "phase_dir": "${PHASE_DIR}",
    "env": "<env>",
    "run_prefix": "<from vg.config.md env.<env>.run_prefix>",
    "build_cmd": "<from vg.config.md env.<env>.build_cmd>",
    "restart_cmd": "<from vg.config.md env.<env>.restart_cmd>",
    "health_cmd": "<from vg.config.md env.<env>.health_cmd>",
    "seed_cmd": "<from vg.config.md env.<env>.seed_cmd or empty>",
    "pre_cmd": "<from vg.config.md env.<env>.pre_cmd or empty>",
    "local_sha": "<git rev-parse HEAD>",
    "previous_sha": "<existing deployed.<env>.sha or null>",
    "dry_run": <bool from --dry-run flag>,
    "policy_ref": "commands/vg/_shared/deploy/per-env-executor-contract.md"
  }
)
```

On return:

```bash
# health == "ok" or "dry-run" → cyan
bash scripts/vg-narrate-spawn.sh vg-deploy-executor returned "env=$ENV health=$HEALTH"

# health == "failed" → red
bash scripts/vg-narrate-spawn.sh vg-deploy-executor failed "env=$ENV cause=$ERROR"
```

## Subagent return JSON (last line of stdout)

```json
{
  "env": "sandbox",
  "sha": "abc123",
  "deployed_at": "2026-05-03T14:22:18Z",
  "health": "ok" | "failed" | "dry-run",
  "deploy_log": "${PHASE_DIR}/.deploy-log.sandbox.txt",
  "previous_sha": "f00ba12" | null,
  "dry_run": false,
  "error": null | "<one-line cause>"
}
```

## Subagent workflow

1. **pre_cmd** (if non-empty): Bash → append output to deploy log → if non-zero → return `{health: "failed", error: "pre_cmd exit ${code}"}`.
2. **build_cmd**: `<run_prefix> <build_cmd>` → append → fail on non-zero.
3. **restart_cmd**: `<run_prefix> <restart_cmd>` → append → fail on non-zero.
4. **health retry**: 6 attempts, 5s sleep between. First passing exit code → success. After 6 → `{health: "failed", error: "health_cmd failed after 6 attempts"}`.
5. **seed_cmd** (if non-empty AND health passed): `<run_prefix> <seed_cmd>` → append → fail on non-zero.
6. Capture `deployed_at = $(date -u +%FT%TZ)`, `sha = local_sha`, `deploy_log = ${PHASE_DIR}/.deploy-log.<env>.txt`.
7. Print result JSON on LAST stdout line.

`--dry-run` short-circuit: print commands to deploy log, do NOT execute, return `{health: "dry-run", error: null}` with `sha = local_sha` and current timestamp.

## Tool restrictions

ALLOWED: Bash (SSH/curl/local exec), Read (vg.config.md + this contract), Write/Edit (deploy log file).
FORBIDDEN: Agent (no nested spawns), WebSearch, WebFetch.

Subagent MAY write only to `${PHASE_DIR}/.deploy-log.<env>.txt` (append).
Subagent MUST NOT write to `${PHASE_DIR}/DEPLOY-STATE.json` (orchestrator-only).

## Orchestrator post-spawn handling

After spawn returns:
1. Parse last stdout line as JSON. On parse failure → emit block `Deploy-Executor-Bad-Return`.
2. Verify `<deploy_log>` file exists. On missing → emit block `Deploy-Executor-Missing-Log`.
3. Append result to local accumulator (Python list).
4. If `health == "failed"` AND not `--non-interactive` → AskUserQuestion (continue / skip-failed / abort-all). On `--non-interactive` → continue with next env.
5. Loop to next env or exit Step 1.

## Failure-mode → orchestrator action map

| `health` | `error` example | Orchestrator action |
|---|---|---|
| `ok` | null | Append result, continue next env |
| `dry-run` | null | Append result with `dry_run: true`, continue |
| `failed` | "pre_cmd exit 2" | Narrate red, AskUserQuestion (interactive) or continue (non-interactive) |
