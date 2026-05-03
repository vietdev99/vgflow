---
description: Bootstrap overlay inspection — view merged config, diff vs vanilla, health report, test fixtures, export/import
argument-hint: "[--view|--diff|--health|--trace <id>|--test|--export|--import <file>]"
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "bootstrap.started"
    - event_type: "bootstrap.completed"
---

# /vg:bootstrap

Inspect and manage the project's bootstrap zone (`.vg/bootstrap/`).

**DOES NOT modify rules.** Use `/vg:learn` for modification.

## Load config

Read `.claude/commands/vg/_shared/config-loader.md` first.

## Subcommands

### `/vg:bootstrap --view`

Show the effective config (vanilla + overlay) currently applied.

```bash
PYTHONIOENCODING=utf-8 ${PYTHON_BIN} .claude/scripts/bootstrap-loader.py \
  --command bootstrap --emit overlay \
  | python -c "import json,sys; d=json.load(sys.stdin); print('\n--- Overlay ---'); import pprint; pprint.pprint(d.get('overlay',{})); print('\n--- Rejected ---'); [print(r) for r in d.get('overlay_rejected',[])]"
```

Also list active rules:
```bash
${PYTHON_BIN} .claude/scripts/bootstrap-loader.py --command bootstrap --emit rules
```

### `/vg:bootstrap --diff`

Show delta between vanilla vg.config.md and effective config.

Implementation:
1. Load vanilla `.claude/vg.config.md` (ignore overlay)
2. Load with overlay merged
3. Diff — show keys changed/added/removed

### `/vg:bootstrap --health`

Full report:
- Active rules count by status (active/dormant/retracted/experimental)
- Rules with `hits==0` and older than 5 phases → dormant candidates
- Rules with `fail_count > success_count` → regression candidates
- Conflicting rules (same target key, opposite values)
- Patches approaching limit (5 max)
- Recent candidates pending review count

```bash
${PYTHON_BIN} .claude/scripts/bootstrap-hygiene.py health
```

### `/vg:bootstrap --trace <rule-id>`

Show firing history of one rule. Reads telemetry.jsonl + events.db for events with `event_type=bootstrap.rule_fired` and `rule_id=<id>`.

```bash
${PYTHON_BIN} .claude/scripts/bootstrap-hygiene.py trace --rule "$RULE_ID"
```

### `/vg:bootstrap --efficacy`

Recompute `hits` + `hit_outcomes.{success_count,fail_count}` in ACCEPTED.md
from telemetry events. Run periodically (or auto-triggered by `/vg:accept`
at phase completion — see Gap 3 wiring).

```bash
${PYTHON_BIN} .claude/scripts/bootstrap-hygiene.py efficacy
```

Outputs summary of rules updated + new efficacy scores.

### `/vg:bootstrap --test`

Run bootstrap fixture regression tests in `.vg/bootstrap/tests/*.yml`.

```bash
${PYTHON_BIN} .claude/scripts/bootstrap-test-runner.py
```

Exit codes:
- 0 — all runnable fixtures pass
- 1 — at least one FAIL
- 2 — runner error

Phase A fixture status:
- `scenario-3-portability-empty-zone` — PASS (empty `.vg/bootstrap/` merges onto vanilla config without crash)
- `scenario-1-playwright-lazy-propagation` — SKIP (needs Phase C override re-validation)
- `scenario-2-toast-fake-success-mutation-verify` — SKIP (needs Phase B reflector)

Each fixture YAML declares:
```yaml
name: "scenario-3-portability-empty-zone"
given:
  bootstrap_zone_state: "empty"
  phase_metadata: {phase: "01", surfaces: ["web"]}
when:
  config_loader_runs: true
then:
  overlay_count: 0
  rules_matched: 0
  crashed: false
```

### `/vg:bootstrap --export`

Package bootstrap zone into `bootstrap-{project}-{date}.tar.gz` for opt-in sharing to other projects.

```bash
tar -czf "bootstrap-${PROJECT_NAME}-$(date +%Y%m%d).tar.gz" .vg/bootstrap/
```

### `/vg:bootstrap --import <file>`

Import a bootstrap tar.gz into current project. **Destructive** — merges onto existing zone, prompts for conflicts.

## Output

Plain stdout. Not meant to be piped into other commands.
