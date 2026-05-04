---
name: vg:validators
description: Query the validator registry — list catalog, check drift, manage enable/disable status.
user-invocable: true
runtime_contract:
  observation_only: true
  contract_exempt_reason: "read-only: queries registry.yaml + events.db, no mutations"
---

<objective>
Phase S surface for the validator registry. Read-only queries over
`.claude/scripts/validators/registry.yaml` + drift metrics from
`.vg/state/events.db`.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

## Subcommands

### `/vg:validators list [--domain X] [--severity Y]`

Print validator catalog.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list --domain security
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py list --severity block
```

### `/vg:validators describe <id>`

Show full registry entry for one validator.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py describe artifact-freshness
```

### `/vg:validators missing`

List validators on disk not in registry (indicates audit gap).

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py missing
```

Non-zero exit if any found.

### `/vg:validators orphans`

List registry entries whose backing file doesn't exist (stale entries).

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py orphans
```

### `/vg:validators drift [--lookback-days N] [--min-runs N]`

Detect validators with drift patterns over the lookback window:
- `never_fires` — registry-active but 0 runs → dead or mis-wired
- `always_pass` — 100% pass rate → likely too permissive
- `high_block_rate` — 80%+ block/fail → candidate false-positive pattern
- `perf_regression` — p95 runtime > 2x registry target → performance issue

```bash
${PYTHON_BIN:-python3} .claude/scripts/validators/verify-validator-drift.py \
  --lookback-days 30 --min-runs 10
```

### `/vg:validators validate`

Schema check the registry YAML itself.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py validate
```

### `/vg:validators disable <id> --reason "..." [--until YYYY-MM-DD]`

Mark a validator disabled (ops action). Rubber-stamp detection applies
via Phase O `allow_flag_gate.py` — requires human TTY or env approver
if this command writes to registry.

```bash
${PYTHON_BIN:-python3} .claude/scripts/validator-registry.py disable \
  log-hygiene --reason "false positives on proxy middleware" --until 2026-06-01
```

## Notes

- Runtime metrics come from `events.db` table `events` with
  `event_type LIKE 'validator.%'` + JSON payload containing
  `{validator, verdict, duration_ms}`.
- Validators emit these events via `_common.py` `emit_and_exit` helper
  (automatic — no per-script wiring needed).
- Drift output is advisory — ops team runs weekly to catch patterns.
- Registry is the source of truth for validator catalog; `missing` +
  `orphans` close the audit surface.

</process>

<success_criteria>
- List/describe/missing/orphans/validate return within 2s
- Drift completes within 10s for 30-day window
- Disable/enable persist to registry.yaml (preserves YAML formatting)
- All commands support `--json` for machine output
- `observation_only` contract exempts from Phase J must_emit_telemetry
</success_criteria>
