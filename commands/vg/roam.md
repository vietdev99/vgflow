---
name: vg:roam
description: Exploratory CRUD-lifecycle pass with state-coherence assertion (post-review/test janitor). Lens-driven, post-confirmation. Catches silent state-mismatches that /vg:review and /vg:test miss. Generates new .spec.ts proposals from findings.
argument-hint: "<phase> [--lens=<csv>] [--council] [--auto-fix] [--max-cost-usd=N] [--max-surfaces=N] [--include-security] [--merge-specs] [--non-interactive] [--force] [--resume] [--aggregate-only] [--skip-pre-check] [--skip-evidence-completeness] [--override-reason=<≥50ch>] [--target-env=<v>] [--local|--sandbox|--staging|--prod] [--model=<v>] [--mode=<v>]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
  - TodoWrite
  - BashOutput
  - mcp__playwright1__browser_click
  - mcp__playwright1__browser_navigate
  - mcp__playwright1__browser_snapshot
  - mcp__playwright1__browser_console_messages
  - mcp__playwright1__browser_network_requests
  - mcp__playwright1__browser_evaluate
  - mcp__playwright1__browser_run_code
  - mcp__playwright1__browser_take_screenshot
  - mcp__playwright1__browser_fill_form
  - mcp__playwright1__browser_type
runtime_contract:
  must_write:
    - "${PHASE_DIR}/roam/SURFACES.md"
    - "${PHASE_DIR}/roam/RAW-LOG.jsonl"
    - "${PHASE_DIR}/roam/ROAM-BUGS.md"
    - "${PHASE_DIR}/roam/RUN-SUMMARY.json"
  must_touch_markers:
    - "0_parse_and_validate"
    # Decomposed mega-gate (5 sub-steps replace single 0a-mega-gate marker)
    - "0a_backfill_env_pref"
    - "0a_detect_platform_tools"
    - "0a_enrich_env_options"
    - "0a_confirm_env_model_mode"
    - "0a_persist_config"
    - "0aa_resume_check"
    - "1_discover_surfaces"
    - "2_compose_briefs"
    - "3_spawn_executors"
    - "4_aggregate_logs"
    - "5_analyze_findings"
    - "6_emit_artifacts"
    - "complete"
    - name: "7_optional_fix_loop"
      severity: "warn"
      required_unless_flag: "--auto-fix"
  must_emit_telemetry:
    - event_type: "roam.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "roam.native_tasklist_projected"  # PARTIAL audit fix (R1a-inherited)
      phase: "${PHASE_NUMBER}"
    - event_type: "roam.session.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "roam.session.completed"
      phase: "${PHASE_NUMBER}"
    - event_type: "roam.analysis.completed"
      phase: "${PHASE_NUMBER}"
    # Hard-gate prompts — prove interactive batches actually fired
    - event_type: "roam.resume_mode_chosen"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--non-interactive"
    - event_type: "roam.config_confirmed"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--non-interactive"
  forbidden_without_override:
    - "--non-interactive"
    - "--skip-pre-check"
    - "--skip-evidence-completeness"
    - "--override-reason"
---

<HARD-GATE>
Roam is post-confirmation (runs AFTER /vg:review + /vg:test PASS).
You MUST verify both passes BEFORE any roam step.

Lens auto-pick by phase profile + entity types — DO NOT manually override
unless --lens flag explicit. Spec.ts proposals stage to proposed-specs/ —
DO NOT auto-merge (requires --merge-specs).

TodoWrite IMPERATIVE after `emit-tasklist.py` projects the 8-group checklist
for vg:roam. Skipping TodoWrite emission causes Stop hook to fail because
`roam.native_tasklist_projected` event will not fire.
</HARD-GATE>

## Red Flags (you have used these before — they will not work)

| Thought | Reality |
|---|---|
| "I can skip 0a sub-steps and write the marker directly" | Each of the 5 decomposed sub-steps emits its own `mark_step` — Stop hook checks all 5 markers (audit FAIL #10 fix). Single-marker skip is a HARD GATE BREACH. |
| "Resume mode means I don't need to ask env/model/mode" | v2.42.10 footgun fix: step 0a fires its 3-question batch ALWAYS. Prior values become Recommended pre-fills, but the user must confirm. |
| "Lens prompts are all the same — I can run one lens for everything" | Per-surface composition is Cartesian (surface × lens × per-model dir). Wrong lens for a surface produces low-signal observations and pollutes RAW-LOG.jsonl. |
| "I'll just cat PLAN.md to find surfaces" | PLAN.md is 8K+ lines on large phases. Use `vg-load --phase N --artifact plan --index` instead — discovery ref enforces this and the static test rejects flat reads. |
| "Auto-merge proposed specs to save a step" | Manual gate is intentional (Q10). Auto-merging untriaged specs floods the test suite with flaky tests. Always require explicit `--merge-specs`. |

## Special invocation — `--merge-specs`

Short-circuit before the main pipeline. Validates `proposed-specs/*.spec.ts`
via `vg-codegen-interactive` validator, merges into project test suite path
(per `paths.tests` in vg.config.md). Manual gate.

```bash
if [[ "$ARGUMENTS" =~ --merge-specs ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-merge-specs.py \
    --phase-dir "${PHASE_DIR}" \
    --proposed-dir "${PHASE_DIR}/roam/proposed-specs" \
    --target-dir "$(grep -oP 'tests:\s*\K\S+' .claude/vg.config.md)"
  exit 0
fi
```

If `--merge-specs` is set, exit before reading any pipeline ref below.

## Tasklist projection

Before any pipeline step runs, project the native task checklist via
`emit-tasklist.py`. The 8-group checklist (see Task 12 of plan +
`scripts/emit-tasklist.py` `CHECKLIST_DEFS["vg:roam"]`) drives the TodoWrite
imperative. AI MUST issue `TodoWrite` with the projected items as soon as
`emit-tasklist.py` returns — this fires `roam.native_tasklist_projected`
which the runtime contract requires.

```bash
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command vg:roam \
  --phase "${PHASE_NUMBER}"
# AI: now invoke TodoWrite with the items printed above.
```

## Steps

Read each ref in order. Each ref contains its own `<step>` block with
`mark_step` calls and (where applicable) a `vg-orchestrator emit-event`
invocation. Do NOT inline content from refs into this entry — the slim
entry only sequences and gates.

### STEP 1 — preflight (parse + resume check)

Read `_shared/roam/preflight.md`.

Two markers: `0_parse_and_validate`, `0aa_resume_check`. Emits
`roam.session.started` (always) and `roam.resume_mode_chosen`
(unless `--non-interactive`).

### STEP 2 — config gate (decomposed: overview + 5 sub-steps)

Read `_shared/roam/config-gate/overview.md` first. Then sequence through
the 5 sub-step refs in order:

1. `_shared/roam/config-gate/backfill-env.md` (`0a_backfill_env_pref`)
2. `_shared/roam/config-gate/detect-platform.md` (`0a_detect_platform_tools`)
3. `_shared/roam/config-gate/enrich-env.md` (`0a_enrich_env_options`)
4. `_shared/roam/config-gate/confirm-env-model-mode.md` (`0a_confirm_env_model_mode`)
5. `_shared/roam/config-gate/persist-config.md` (`0a_persist_config`)

Each sub-step writes its own `mark_step`. Sub-step 5 emits
`roam.config_confirmed` and writes `.tmp/0a-confirmed.marker` (HARD GATE
token consumed by step 1 entry in `discovery.md`).

**Why decomposed:** original `0a_env_model_mode_gate` was 355 lines with
9 inline AskUserQuestion sub-prompts. Single marker for 9 prompts meant
silent-skip of any sub-prompt was undetectable. Decomposed: one marker
per sub-prompt, each ref ≤150 lines.

### STEP 3 — discovery + briefs

Read `_shared/roam/discovery.md`.

Two markers: `1_discover_surfaces`, `2_compose_briefs`. Discovery uses
`vg-load --index` for PLAN.md (closes Phase F Task 30 for vg:roam — single
L600 flat read replaced by index call).

CONTEXT.md and RUNTIME-MAP.md remain KEEP-FLAT (small docs / already
filtered JSON).

### STEP 4 — spawn executors (3 dispatch branches)

Read `_shared/roam/spawn-executors.md`.

Marker: `3_spawn_executors`. Branches by `$ROAM_MODE`:

- `self` → current Claude session executes via MCP Playwright
- `spawn` → subprocess CLI (codex / gemini), parallel cap 5
- `manual` → generate `PASTE-PROMPT.md`, user pastes elsewhere, drops JSONL back

Cost estimator + soft cap warning before spawn (default $10/session via
`VG_MAX_COST_USD`, override with `--max-cost-usd=N`).

### STEP 5 — aggregate + analyze

Read `_shared/roam/aggregate-analyze.md`.

Two markers: `4_aggregate_logs`, `5_analyze_findings`. Step 4 runs
evidence completeness validator (`verify-scanner-evidence-completeness.py`)
+ vocabulary validator (`grep` for banned tokens — tags
`vocabulary_violation: true`). Step 5 runs deterministic R1-R8 Python
rules in `roam-analyze.py` and emits `roam.analysis.completed`.

### STEP 6 — artifacts (PIPELINE-STATE update + spec.ts staging)

Read `_shared/roam/artifacts.md`.

Marker: `6_emit_artifacts`. Updates PIPELINE-STATE.json with verdict
(PASS or BLOCK_ACCEPT). Spec.ts proposals staged to `proposed-specs/` —
NOT auto-merged.

### STEP 7 — optional fix loop (gated by `--auto-fix`)

Read `_shared/roam/fix-loop.md`.

Marker: `7_optional_fix_loop` (severity `warn`,
`required_unless_flag: "--auto-fix"` in runtime_contract). Default path:
report only. With `--auto-fix`: spawn existing auto-fix subagent on top-N
bugs (max 5 per session). NO new subagent introduced in R3.5 — auto-fix
loop is preserved as-is.

### STEP 8 — close

Read `_shared/roam/close.md`.

Marker: `complete`. Emits `roam.session.completed` + final summary banner.

## Conformance contract for executors

Per `<rules>` 2: every brief MUST inject `vg:_shared:scanner-report-contract`
(banned vocab + report schema). Briefs without the contract block are
REJECTED at compose time by `roam-compose-brief.py`. Executors emit
**observations only, never verdicts** — the commander (Opus) is the sole
judge during step 5 analysis.

## Cost guards

- Hard cap: 50 surfaces × 1 CLI default (`--max-surfaces=N` to override)
- Soft cap: $10/session (`VG_MAX_COST_USD` env or `--max-cost-usd=N`)
- Pre-spawn estimator (in `spawn-executors.md`) warns + asks confirm if
  soft cap exceeded.
- Council mode default OFF (Q8); enable via `--council` for ship-critical
  phases (2× cost, 2 perspectives).
- Security lens skipped by default (Q13); enable via `--include-security`
  for double-coverage.

## Resume modes (recap)

| Mode | Trigger | Behavior |
|---|---|---|
| `fresh` | first run, no prior state | normal flow, all steps |
| `force` | `--force` or interactive choice | wipe `ROAM_DIR/*` then proceed fresh |
| `resume` | `--resume` or interactive choice | reuse config; per-step skip if artifact exists |
| `aggregate-only` | `--aggregate-only` or interactive choice | skip steps 1-3, run 4-6 only |

Detection logic in `preflight.md` (step 0aa). Step 0a (config gate)
ALWAYS fires regardless of mode (v2.42.10 footgun fix — prior values
become Recommended pre-fills, user must confirm).
