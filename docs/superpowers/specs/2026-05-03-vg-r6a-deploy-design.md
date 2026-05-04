# VG R6a — Deploy Workflow Dedicated Spec (REVISED 2026-05-03)

**Status:** Design (revised against actual deploy.md state, ready for plan execution)
**Date:** 2026-05-03 (revised from earlier same-day idealized version)
**Replication round:** R6a (cross-cutting workflow #1, paired with R6b)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md` (UX baseline)
**Depends on:** R5.5 hooks-source-isolation (merged)
**Covers:** `commands/vg/deploy.md` and the new `vg-deploy-executor` subagent

> **Revision note:** The earlier version of this spec assumed a 6-STEP idealized
> structure (Preflight / Env Select / User Confirm / Spawn / Verify / Close) and
> a `schema_version` field on DEPLOY-STATE.json. Both were wrong against the
> real `commands/vg/deploy.md`. This spec is rewritten against verified file
> structure: 5 sections (Step 0 / Step 0a / Step 1 / Step 2 / Final), real
> DEPLOY-STATE schema (no `schema_version`), real telemetry events
> (`phase.deploy_started` / `phase.deploy_completed`).

---

## 1. Background

### 1.1 Problem

`commands/vg/deploy.md` is currently 588 lines. The bulk (lines 281–478, ≈ 200 lines) is **Step 1 — Deploy loop (sequential per env)** which inlines all per-env work:

- Config parsing from `.claude/vg.config.md` (RUN_PREFIX, BUILD_CMD, RESTART_CMD, HEALTH_CMD, SEED_CMD, PRE_CMD) — repeated as ~5 inline Python regex blocks per invocation
- Sequential exec flow (pre → build → restart → health-retry × 6 with 30s timeout → seed)
- Per-env failure handling + AskUserQuestion (continue / skip-failed / abort-all)
- JSON append to `.tmp/deploy-results.json`

Three problems with the inline form:

1. **Orchestrator AI context pollution** — every invocation loads the full per-env script (including SSH command bodies + retry policy + error handling) into the AI orchestrator's reasoning context, even though the orchestrator only needs to coordinate.
2. **Future parallel-env extension is blocked** — the inline shape forces sequential. To support `--parallel-envs` in a future round, per-env logic must be a callable unit.
3. **Config-parsing duplication** — config extraction is hand-rolled 5 times in the same step. Trivial bugs slip in (e.g. one block defaults differently than another).

### 1.2 Why dedicated subagent (per operator decision 2026-05-03 round C)

Per discussion with operator: extract `vg-deploy-executor` subagent now (futureproof), even though current logic could fit in pure shell helpers. Rationale:

- Future env additions (canary, prod-eu, prod-asia) compound complexity inside the inline loop.
- Per-env retry / rollback policies will diverge from a shared template.
- Without subagent boundary, every env-specific bug requires editing the entry skill — which loads into orchestrator AI context every invocation.
- Dedicated subagent isolates per-env logic: orchestrator only loads contract + result, not full SSH sequences.

### 1.3 Scope

**In scope:**
- Refactor `commands/vg/deploy.md` from 588 to ≤500 lines (slim entry).
- Create `vg-deploy-executor` subagent in `.claude/agents/vg-deploy-executor.md`.
- Split per-env execution + config helpers into `commands/vg/_shared/deploy/`.
- Preserve current telemetry events (`phase.deploy_started`, `phase.deploy_completed`) — orchestrator-emitted, NOT changed by this round.
- Preserve DEPLOY-STATE.json schema EXACTLY — fields `phase`, `deployed.{env}.{sha, deployed_at, health, deploy_log, previous_sha, dry_run}`, plus preserved keys `preferred_env_for`, `preferred_env_for_skipped`.
- Preserve all 7 rules in current `<rules>` block.
- Preserve all 5 step markers (`0_parse_and_validate`, `0a_env_select_and_confirm`, `1_deploy_per_env`, `2_persist_summary`, `complete`).
- Add subagent to `vg-pre-tool-use-agent.sh` allow-list (already covered by `vg-*` glob).
- Pytest suite for slim size + subagent delegation + telemetry preservation + step-marker preservation + DEPLOY-STATE schema preservation.

**Out of scope:**
- New telemetry events (`phase.deploy_started`/`completed` are sufficient).
- Schema migration (no `schema_version` field exists today; do not introduce).
- Adding new envs (canary, prod-eu) — separate roadmap.
- `--parallel-envs` flag — refactor enables this but does not implement.
- Codex mirror (`.codex/skills/vg-deploy/`) — defer.
- Mobile deploy — covered by separate `mobile-deploy` shared ref.

### 1.4 Goals

- `commands/vg/deploy.md` ≤ 500 lines after refactor.
- `vg-deploy-executor` subagent with explicit input/output contract.
- Per-env logic isolated — orchestrator AI does not see full SSH command bodies on every invocation.
- DEPLOY-STATE.json schema unchanged (backward compat with consumers like `enrich-env-question.py`).
- Existing telemetry events preserved (downstream gates depend on `phase.deploy_completed` payload).
- Subagent spawn narrated via `scripts/vg-narrate-spawn.sh` (UX baseline R2).
- Mock dogfood: localhost-mock deploy of 1 phase to a stub `sandbox` env succeeds end-to-end (no real DEPLOY-STATE fixtures exist in repo today; mock is the pragmatic verification).

### 1.5 Non-goals

- Re-architecting DEPLOY-STATE.json schema.
- Replacing SSH transport (Ansible, Pulumi, etc.).
- Per-env hook integration changes.
- Removing `commands/vg/deploy.md` entirely (entry skill stays as orchestrator).
- Changing the 7 `<rules>` (multi-env sequential, prod confirmation gate, per-env failure handling, etc.).

---

## 2. Inheritance from blueprint pilot

This round inherits from `_shared-ux-baseline.md`:

- **Per-task artifact split** — DEPLOY-STATE.json's `deployed.{env}` block IS the per-unit Layer 1; the flat file IS Layer 2/3. Consumers grep `deployed.<env>`. No additional split needed.
- **Subagent spawn narration** — MANDATORY. Every `Agent(vg-deploy-executor)` call wraps with `bash scripts/vg-narrate-spawn.sh vg-deploy-executor {spawning|returned|failed}`. Step 1's per-env loop wraps every iteration's spawn.
- **Compact hook stderr** — no new hooks added by R6a; existing hooks (R1a + R5.5) inherited.

---

## 3. Architecture

### 3.1 Orchestrator vs executor split

```
/vg:deploy <phase> [--envs=...] [--all-envs] [--dry-run] [--non-interactive] [--prod-confirm-token=...] [--allow-build-incomplete]
   │
   ├── ENTRY SKILL (commands/vg/deploy.md, ≤500 lines)
   │
   │   ## Step 0 — Parse args, validate prerequisites      [UNCHANGED scope]
   │     - resolve phase dir
   │     - check build-complete via PIPELINE-STATE
   │     - emit phase.deploy_started telemetry
   │
   │   ## Step 0a — Select envs + prod danger gate         [UNCHANGED scope]
   │     - multi-select AskUserQuestion (or flags)
   │     - prod 3-option danger gate
   │     - validate envs exist in vg.config.md
   │
   │   ## Step 1 — Deploy loop (sequential per env)        [REFACTORED]
   │     for env in selected_envs:
   │       narrate-spawn green: "vg-deploy-executor spawning env=$env"
   │       Agent(subagent_type="vg-deploy-executor", prompt={...})
   │       narrate-spawn cyan/red based on result
   │       collect result into local accumulator
   │     # All per-env work moved into subagent.
   │     # Failure handling (continue/skip/abort) stays in orchestrator
   │     # because it requires user interaction (AskUserQuestion).
   │
   │   ## Step 2 — Merge results into DEPLOY-STATE.json    [MOSTLY UNCHANGED]
   │     - read existing DEPLOY-STATE (preserve preferred_env_for keys)
   │     - merge per-env results (sha, deployed_at, health, deploy_log, previous_sha, dry_run)
   │     - emit phase.deploy_completed telemetry
   │
   │   ## Final — mark + run-complete                      [UNCHANGED]
   │
   └── SUBAGENT (.claude/agents/vg-deploy-executor.md)
         - Receives: {phase, env, run_prefix, build_cmd, restart_cmd, health_cmd, seed_cmd, pre_cmd, local_sha, previous_sha, dry_run}
         - Executes: pre → build → restart → health-retry-6× → seed
         - Logs to: ${PHASE_DIR}/.deploy-log.{env}.txt
         - Returns: {env, sha, deployed_at, health, deploy_log, previous_sha, dry_run, error?}
         - Does NOT write DEPLOY-STATE.json (orchestrator merges in Step 2)
```

### 3.2 What stays in orchestrator (NOT extracted)

- Phase + build-complete validation (Step 0).
- Env selection UI + prod danger gate (Step 0a) — requires AskUserQuestion.
- Per-env failure handling (continue / skip-failed / abort-all) — requires AskUserQuestion.
- DEPLOY-STATE.json merge logic (Step 2) — preserves `preferred_env_for` keys per rule 5.
- Telemetry emission (Step 0 start + Step 2 end).
- Step markers (must_touch_markers).

### 3.3 What moves to subagent

- Config parsing for current env (RUN_PREFIX, BUILD_CMD, RESTART_CMD, HEALTH_CMD, SEED_CMD, PRE_CMD).
- Sequential exec: pre → build → restart → health (6× retry, 30s total) → seed.
- Capture exec result (sha, deployed_at, health, deploy_log path, previous_sha, dry_run).
- Append to `${PHASE_DIR}/.deploy-log.{env}.txt`.

### 3.4 DEPLOY-STATE.json schema (UNCHANGED)

Real schema (verified against current `commands/vg/deploy.md` Step 2):

```json
{
  "phase": "P1",
  "deployed": {
    "sandbox": {
      "sha": "abc123",
      "deployed_at": "2026-05-03T14:22:18Z",
      "health": "ok",
      "deploy_log": "${PHASE_DIR}/.deploy-log.sandbox.txt",
      "previous_sha": "f00ba12",
      "dry_run": false
    },
    "staging": null,
    "prod": null
  },
  "preferred_env_for": { ... },
  "preferred_env_for_skipped": false
}
```

**Field types:**
| Field | Type | Notes |
|---|---|---|
| `phase` | string | Set once at first deploy |
| `deployed` | object | Container; keys = env names |
| `deployed.<env>` | object \| null | null = not yet deployed |
| `deployed.<env>.sha` | string | Git HEAD at deploy time |
| `deployed.<env>.deployed_at` | string | ISO-8601 UTC |
| `deployed.<env>.health` | enum | `"ok"` \| `"failed"` \| `"dry-run"` |
| `deployed.<env>.deploy_log` | string | Path to log file |
| `deployed.<env>.previous_sha` | string \| null | For rollback hint (rule 6) |
| `deployed.<env>.dry_run` | boolean | True if --dry-run |
| `preferred_env_for` | object | Set by /vg:scope step 1b — PRESERVED |
| `preferred_env_for_skipped` | boolean | PRESERVED |

**No `schema_version` field exists today; this round does NOT introduce one.**

### 3.5 Slim entry layout (≤500 lines)

```markdown
# /vg:deploy

[frontmatter — UNCHANGED]

<rules>...</rules>     [UNCHANGED — all 7 rules preserved]

<objective>...</objective>

## Step 0 — Parse args, validate prerequisites      [~50 lines]
## Step 0a — Select envs + prod danger gate         [~140 lines — UI-heavy]
## Step 1 — Deploy loop (slim — spawn per env)      [~70 lines, was ~190]
## Step 2 — Merge results into DEPLOY-STATE.json    [~80 lines]
## Final — mark + run-complete                      [~10 lines]

## References
- _shared/deploy/overview.md
- _shared/deploy/per-env-executor-contract.md
```

Total target: ~430 lines body + ~50 lines frontmatter/rules = ~480 lines.

---

## 4. Subagent contract — `vg-deploy-executor`

### 4.1 Frontmatter

```markdown
---
name: vg-deploy-executor
description: Execute per-env deploy sequence (pre → build → restart → health-retry → seed). Spawned by /vg:deploy entry skill, ONE invocation per env. Returns result JSON; does NOT write DEPLOY-STATE.json (orchestrator merges).
tools: Bash, Read, Write, Edit, Grep
model: claude-sonnet-4-6
---
```

### 4.2 Input contract

The orchestrator's spawn prompt MUST include all of:

- `phase` — phase ID (e.g. "P1")
- `phase_dir` — absolute path to phase directory
- `env` — one of the configured env names (sandbox/staging/prod)
- `run_prefix` — string from `vg.config.md env.<env>.run_prefix` (often `ssh user@host`)
- `build_cmd` — string (e.g. `cd /var/www && npm run build`)
- `restart_cmd` — string
- `health_cmd` — string returning HTTP status or exit code
- `seed_cmd` — string (or empty if no seed step)
- `pre_cmd` — string (or empty if no pre step)
- `local_sha` — current git HEAD (orchestrator passes; subagent does NOT re-resolve)
- `previous_sha` — value of existing `deployed.<env>.sha` from DEPLOY-STATE.json (or null if first deploy)
- `dry_run` — boolean
- `policy_ref` — pointer to `commands/vg/_shared/deploy/per-env-executor-contract.md`

### 4.3 Output contract

Subagent returns a single JSON object as the LAST line of stdout:

```json
{
  "env": "sandbox",
  "sha": "abc123",
  "deployed_at": "2026-05-03T14:22:18Z",
  "health": "ok",
  "deploy_log": "${PHASE_DIR}/.deploy-log.sandbox.txt",
  "previous_sha": "f00ba12",
  "dry_run": false,
  "error": null
}
```

On failure: `health: "failed"`, `error: "<one-line cause>"`. The `deploy_log` path always points to a real file (subagent writes the log even on failure).

Subagent does NOT touch DEPLOY-STATE.json. Orchestrator Step 2 merges results.

### 4.4 Workflow (subagent body)

1. **Pre** (if `pre_cmd` non-empty): run via Bash, append to deploy log, abort with `health: "failed"` if non-zero.
2. **Build**: run `<run_prefix> <build_cmd>`, append output to deploy log, abort on non-zero.
3. **Restart**: run `<run_prefix> <restart_cmd>`, append, abort on non-zero.
4. **Health retry**: 6× attempts with 5s sleep between (30s total). Each attempt: run `<run_prefix> <health_cmd>`, capture exit code. Pass on first 0; fail after 6 attempts.
5. **Seed** (if `seed_cmd` non-empty AND health passed): run `<run_prefix> <seed_cmd>`, append, abort on non-zero.
6. **Capture timestamp**: `date -u +%FT%TZ`.
7. **Emit JSON** on last stdout line.

`--dry-run` short-circuits: print commands to log, do NOT execute, return `health: "dry-run"`.

### 4.5 Tool restrictions

ALLOWED: Bash (SSH/curl/local exec), Read (vg.config + per-env-executor-contract), Write/Edit (deploy log file).
FORBIDDEN: Agent (no nested spawns), WebSearch, WebFetch.

Subagent MAY write to:
- `${PHASE_DIR}/.deploy-log.<env>.txt` (append).

Subagent MUST NOT write to:
- `${PHASE_DIR}/DEPLOY-STATE.json` (orchestrator-only).
- Any other phase artifact.

### 4.6 Error modes

| Stage failure | Returned `health` | Returned `error` |
|---|---|---|
| pre_cmd non-zero | `"failed"` | `"pre_cmd exit ${code}"` |
| build_cmd non-zero | `"failed"` | `"build_cmd exit ${code}"` |
| restart_cmd non-zero | `"failed"` | `"restart_cmd exit ${code}"` |
| health 6× non-zero | `"failed"` | `"health_cmd failed after 6 attempts (last exit ${code})"` |
| seed_cmd non-zero | `"failed"` | `"seed_cmd exit ${code}"` |

Orchestrator Step 1 reads `health` from each result and chains the next env iff health=ok OR user picked "skip-failed" via AskUserQuestion in failure-handling subloop.

---

## 5. File and directory layout

```
commands/vg/
  deploy.md                              REFACTOR: 588 → ≤500 lines (slim entry)
  _shared/deploy/                        NEW DIR
    overview.md                          NEW — flow diagram + step responsibility table
    per-env-executor-contract.md         NEW — subagent input/output contract (mirrors §4)

.claude/agents/
  vg-deploy-executor.md                  NEW — subagent definition (frontmatter + workflow body)

scripts/
  vg-narrate-spawn.sh                    EXISTS — used in Step 1 spawn loop

scripts/hooks/
  vg-meta-skill.md                       EXTEND — append "deploy"-specific Red Flags section

tests/skills/                            (created in R5.5 or this round if absent)
  test_deploy_slim_size.py               NEW — assert deploy.md ≤500 lines
  test_deploy_subagent_delegation.py     NEW — assert Step 1 spawns vg-deploy-executor
  test_deploy_telemetry_preserved.py     NEW — assert frontmatter must_emit retains phase.deploy_started + phase.deploy_completed
  test_deploy_step_markers_preserved.py  NEW — assert all 5 markers still listed in must_touch_markers
  test_deploy_state_schema_real.py       NEW — exercise the merge logic against a synthetic in-memory DEPLOY-STATE; assert all real fields preserved
```

NOTE: no `tests/fixtures/deploy-state/*.json` — no real fixtures exist in the repo to lock against. The schema test instead uses an in-memory dict matching the real schema.

---

## 6. Telemetry events (UNCHANGED from current)

The current frontmatter declares 2 events:

```yaml
must_emit_telemetry:
  - event_type: "phase.deploy_started"
    phase: "${PHASE_NUMBER}"
  - event_type: "phase.deploy_completed"
    phase: "${PHASE_NUMBER}"
```

R6a does NOT change these. Downstream gates (review/test/roam env-recommendation via `enrich-env-question.py`) depend on `phase.deploy_completed` payload structure.

R6a's pytest `test_deploy_telemetry_preserved.py` asserts both events remain in `must_emit_telemetry` after refactor.

---

## 7. Error handling, migration, testing

### 7.1 Error handling

Subagent failure → orchestrator Step 1 reads result.health, narrates red pill, surfaces deploy log path to user via AskUserQuestion (continue / skip-failed / abort-all). This MATCHES current rule 4 ("per-env failure handling — does not auto-abort"). No new error paths.

All blocks follow the compact 3-line stderr pattern from R1a (no new hooks added).

### 7.2 Migration

- Existing `commands/vg/deploy.md` continues to work until R6a refactor lands.
- Post-R6a: existing DEPLOY-STATE.json files continue to parse identically — schema unchanged.
- No data migration. No env config schema change.
- Codex mirror: defer.

### 7.3 Testing

**Pytest static** (5 tests):

- `test_deploy_slim_size.py` — `wc -l commands/vg/deploy.md ≤ 500`.
- `test_deploy_subagent_delegation.py` — grep entry skill body for `Agent(subagent_type="vg-deploy-executor"` AND for `vg-narrate-spawn.sh vg-deploy-executor`. Both ≥ 1 in the Step 1 section.
- `test_deploy_telemetry_preserved.py` — parse YAML frontmatter, assert `must_emit_telemetry` contains entries for both `phase.deploy_started` and `phase.deploy_completed`.
- `test_deploy_step_markers_preserved.py` — parse frontmatter, assert `must_touch_markers` includes all 5 of `0_parse_and_validate`, `0a_env_select_and_confirm`, `1_deploy_per_env`, `2_persist_summary`, `complete`.
- `test_deploy_state_schema_real.py` — synthesize an in-memory pre-deploy DEPLOY-STATE dict with `preferred_env_for` keys + 1 existing env; pass it through the Step 2 merge logic via a test harness; assert all real fields present + preserved keys preserved.

**Mock dogfood** (manual, in plan Task 9):

- Stub `vg.config.md` env.sandbox with `run_prefix = ""`, `build_cmd = "true"`, `restart_cmd = "true"`, `health_cmd = "echo ok"`, `seed_cmd = ""`. Run `/vg:deploy <phase> --envs=sandbox --non-interactive`. Verify chip narration + DEPLOY-STATE.json populated + telemetry events emitted.

NO real-deploy dogfood — repo has no live infra; pretending otherwise is theatre.

### 7.4 Exit criteria

R6a PASSES when ALL of:

1. `commands/vg/deploy.md` ≤ 500 lines.
2. `.claude/agents/vg-deploy-executor.md` exists with valid frontmatter (parseable).
3. `commands/vg/_shared/deploy/{overview,per-env-executor-contract}.md` exist.
4. All 5 pytest tests pass.
5. Mock dogfood: 1 phase + stubbed sandbox env succeeds end-to-end (chip narration + DEPLOY-STATE merged + telemetry emitted).
6. R5.5 hook patches merged (already merged: `d932710`).

---

## 8. Round sequencing

R6a depends on R5.5 (already merged). R6a is independent of R6b (amend+debug) and may execute in parallel.

```
R5.5 ✅ merged
       │
       ├──► R6a (deploy)  ──► merge
       │
       └──► R6b (amend+debug) ──► merge
```

---

## 9. References

- Inherits UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r5.5-hooks-source-isolation-design.md` (merged)
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md` (revised companion)
- Existing skill body: `commands/vg/deploy.md` (588 lines, source for refactor)
- Investigation report (verified 2026-05-03): structure of all 3 commands + lack of fixtures.
- Codex spec mirror: `.codex/skills/vg-deploy/SKILL.md` (defer).

---

## 10. UX baseline (mandatory cross-flow)

Per `_shared-ux-baseline.md`, R6a honors:

- **Per-task artifact split** — DEPLOY-STATE.json's `deployed.{env}` block IS the per-unit Layer 1; the flat file IS Layer 2/3 (consumers grep `deployed.<env>`). No additional split needed. Consumer pattern: `vg-load --phase N --artifact deploy-state --env <e>` (already supported via grep).
- **Subagent spawn narration** — every `Agent(vg-deploy-executor)` in Step 1's per-env loop wraps with `vg-narrate-spawn.sh`. Each env iteration → 1 spawn → green pill at start, cyan/red at end.
- **Compact hook stderr** — no new hooks added by R6a. Existing hooks (R1a + R5.5 patches) inherited.
