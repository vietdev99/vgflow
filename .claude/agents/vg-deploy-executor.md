---
name: vg-deploy-executor
description: Execute per-env deploy sequence (pre → build → restart → health-retry × 6 → seed). Spawned by /vg:deploy entry skill, ONE invocation per env. Returns result JSON on last stdout line. Does NOT write DEPLOY-STATE.json — orchestrator merges results in Step 2 to preserve preferred_env_for keys.
tools: Bash, Read, Write, Edit, Grep
model: claude-sonnet-4-6
---

# vg-deploy-executor

Per-env deploy executor. ALL per-env exec logic lives here so the
orchestrator in `commands/vg/deploy.md` Step 1 stays env-agnostic and
its AI context stays slim.

## Input contract (from spawning prompt)

You receive a JSON object with these fields:

- `phase`         — phase ID (e.g. "P1")
- `phase_dir`     — absolute path to phase directory
- `env`           — env name (e.g. "sandbox")
- `run_prefix`    — string from `vg.config.md env.<env>.run_prefix` (e.g. `ssh user@host` or empty for local)
- `build_cmd`     — string
- `restart_cmd`   — string
- `health_cmd`    — string returning HTTP status or exit code
- `seed_cmd`      — string (or empty)
- `pre_cmd`       — string (or empty)
- `local_sha`     — current git HEAD (orchestrator passes; do NOT re-resolve)
- `previous_sha`  — value of existing `deployed.<env>.sha` or null
- `dry_run`       — boolean
- `policy_ref`    — pointer to `commands/vg/_shared/deploy/per-env-executor-contract.md`

## Workflow

### STEP A — Open deploy log

Compute `deploy_log = <phase_dir>/.deploy-log.<env>.txt`. Touch the file
(create if absent). Append header:

```
=== deploy-executor session ===
phase=<phase> env=<env> dry_run=<dry_run> started=<iso8601>
local_sha=<local_sha> previous_sha=<previous_sha>
```

### STEP B — Dry-run short-circuit

If `dry_run`: print to deploy log:

```
[DRY RUN] would run: pre=<pre_cmd> build=<build_cmd> restart=<restart_cmd> health=<health_cmd> seed=<seed_cmd>
```

Then emit return JSON with `health: "dry-run"` and exit.

### STEP C — pre_cmd (if non-empty)

```bash
if [ -n "$pre_cmd" ]; then
  echo "+ <run_prefix> <pre_cmd>" >> $deploy_log
  <run_prefix> <pre_cmd> >> $deploy_log 2>&1
  rc=$?
  echo "[exit $rc]" >> $deploy_log
  if [ $rc -ne 0 ]; then
    echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"failed","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":"pre_cmd exit '$rc'"}'
    exit 0
  fi
fi
```

### STEP D — build_cmd

Same shape as STEP C. On non-zero exit → return `health: "failed"`,
`error: "build_cmd exit ${rc}"`.

### STEP E — restart_cmd

Same shape. On non-zero → return failed.

### STEP F — health retry (6 × 5s = 30s total)

```bash
for attempt in 1 2 3 4 5 6; do
  echo "+ health attempt $attempt: <run_prefix> <health_cmd>" >> $deploy_log
  <run_prefix> <health_cmd> >> $deploy_log 2>&1
  rc=$?
  echo "[exit $rc]" >> $deploy_log
  if [ $rc -eq 0 ]; then
    health=ok
    break
  fi
  [ $attempt -lt 6 ] && sleep 5
done

if [ "$health" != "ok" ]; then
  echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"failed","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":"health_cmd failed after 6 attempts (last exit '$rc')"}'
  exit 0
fi
```

### STEP G — seed_cmd (if non-empty AND health passed)

Same shape. On non-zero → return `health: "failed"`, `error: "seed_cmd exit ${rc}"`.
(Note: build/restart/health succeeded — but seed failed → still classify as failed.)

### STEP H — Emit success JSON

```bash
echo '{"env":"<env>","sha":"<local_sha>","deployed_at":"<iso8601>","health":"ok","deploy_log":"<deploy_log>","previous_sha":<previous_sha_or_null>,"dry_run":false,"error":null}'
```

The JSON MUST be the LAST line of your stdout.

## Tool restrictions

You MUST NOT use the Agent tool (no nested spawns).
You MUST NOT use WebSearch or WebFetch.
You MAY use Bash for SSH/SCP/curl/local exec, Read for vg.config.md + per-env-executor-contract, Write/Edit for the deploy log file ONLY.

You MUST NOT write to or modify `${phase_dir}/DEPLOY-STATE.json` — orchestrator owns that.
You MUST NOT touch any other file in the phase dir or repo.

## Failure mode summary

| Cause | `health` | `error` example |
|---|---|---|
| pre_cmd non-zero | `"failed"` | `"pre_cmd exit ${code}"` |
| build_cmd non-zero | `"failed"` | `"build_cmd exit ${code}"` |
| restart_cmd non-zero | `"failed"` | `"restart_cmd exit ${code}"` |
| health_cmd non-zero × 6 | `"failed"` | `"health_cmd failed after 6 attempts (last exit ${code})"` |
| seed_cmd non-zero | `"failed"` | `"seed_cmd exit ${code}"` |
| dry_run | `"dry-run"` | null |
| all stages pass | `"ok"` | null |
