---
name: vg:review-batch
description: Multi-phase /vg:review orchestrator — sandbox/staging batch sweep with per-env policy enforcement (v2.40 Phase 1.D-bis)
argument-hint: "(--phases <list> | --milestone <M> | --since <git-sha>) [--recursion=light|deep|exhaustive] [--probe-mode=auto|manual|hybrid] [--target-env=local|sandbox|staging|prod] [--non-interactive]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
runtime_contract:
  must_write:
    - path: "BATCH-FINDINGS-*.json"
      severity: "warn"
      content_min_bytes: 32
---

# /vg:review-batch

Run the v2.40 recursive-lens-probe review across multiple phases sequentially. Wraps `scripts/review_batch.py` with bash arg parsing + user-facing docs.

> **Operator recommendation (Tier 2 C — runaway-cost safety net):** invoke this skill from a Claude Code session launched with `--max-budget-usd 10` (or higher for large milestones). Multi-phase sweeps with retry loops can occasionally hit pathological pattern → unbounded fix loop → $10+ in a single run. The `--max-budget-usd` flag is operator-side only (the harness cannot self-cap); see `CLAUDE.md > Performance — --max-budget-usd runaway-cost safety net`. Example:
> ```bash
> claude --print --max-budget-usd 10 --exclude-dynamic-system-prompt-sections -p '/vg:review-batch --milestone M2'
> ```

## When to use

- **Sandbox sweep**: every Phase 2b-2.5 lens probe end-to-end against a freshly seeded sandbox VPS, before promoting to staging.
- **Staging gate**: re-run the same sweep with `--target-env=staging` to confirm prod-bound code does not trip the staging-stripped lens set (input-injection drops out).
- **Cross-phase regression**: when a refactor touches multiple phases, point `--since=<sha>` at the merge base and review-batch picks up every phase whose `.vg/phases/<N>/` was touched.

## Phase selection (one of)

| Flag | Description |
|---|---|
| `--phases 1,2,3` | Explicit comma-separated list. |
| `--milestone M2` | Read `ROADMAP.md`, pick all `Phase N` lines under `## Milestone M2`. |
| `--since <git-sha>` | `git diff --name-only <sha>...HEAD` filtered to `.vg/phases/<N>/`. |

## Forwarded flags

These are passed through to each per-phase `/vg:review` invocation:

- `--recursion={light,deep,exhaustive}` — worker cap envelope (15 / 40 / 100).
- `--probe-mode={auto,manual,hybrid}` — spawn strategy (Phase 2b-2.5).
- `--target-env={local,sandbox,staging,prod}` — env_policy enforcement.
- `--non-interactive` — suppress stdin prompts (CI mode).

## Bash entry point

```bash
PHASES_ARG=""
MILESTONE_ARG=""
SINCE_ARG=""
RECURSION="${RECURSION:-light}"
PROBE_MODE="${PROBE_MODE:-auto}"
TARGET_ENV="${TARGET_ENV:-sandbox}"
NON_INTERACTIVE="${VG_NON_INTERACTIVE:-0}"

# Argparse passthrough — script-side parser is the source of truth, this
# wrapper just narrates and forwards.
ARGS=()
[[ -n "$PHASES_ARG" ]]    && ARGS+=( --phases "$PHASES_ARG" )
[[ -n "$MILESTONE_ARG" ]] && ARGS+=( --milestone "$MILESTONE_ARG" )
[[ -n "$SINCE_ARG" ]]     && ARGS+=( --since "$SINCE_ARG" )
ARGS+=( --recursion "$RECURSION" --probe-mode "$PROBE_MODE" --target-env "$TARGET_ENV" )
[[ "$NON_INTERACTIVE" == "1" ]] && ARGS+=( --non-interactive )

python scripts/review_batch.py "${ARGS[@]}"
```

## Failure semantics

Per-phase failure is logged + the batch continues. Aggregate exit code:

- `0` — every phase passed.
- `1` — at least one phase failed (see `BATCH-FINDINGS-*.json` summary).
- `2` — argparse error (no phases resolved, mutually-exclusive selectors).

`BATCH-FINDINGS-{ISO-date}.json` includes:

- `started_at` / `finished_at`
- `selector` (which flag resolved the phase list)
- `forwarded` (recursion, probe_mode, target_env, non_interactive)
- `phases[]` — per-phase `{phase, exit_code, stdout_tail, stderr_tail, cmd}`
- `summary` — total / passed / failed counts

## Examples

```bash
# Sequential sandbox sweep across phases 7-9
/vg:review-batch --phases 7,8,9 --target-env sandbox --recursion light

# Milestone gate (CI)
/vg:review-batch --milestone M2 --target-env staging --non-interactive

# Diff-driven sweep after a wide refactor
/vg:review-batch --since origin/main --recursion deep --probe-mode hybrid
```

## See also

- `scripts/review_batch.py` — implementation
- `scripts/spawn_recursive_probe.py` — per-phase Phase 2b-2.5 dispatcher
- `scripts/env_policy.py` — per-env constraint table
- `vg.config.template.md` → `review.batch` block — parallelism + retry config (Task 26f)
