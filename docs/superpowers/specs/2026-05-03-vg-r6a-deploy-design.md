# VG R6a — Deploy Workflow Dedicated Spec

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R6a (cross-cutting workflow #1, paired with R6b amend+debug)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md` (UX baseline)
**Depends on:** R5.5 hooks-source-isolation (subagent allow-list must allow `vg-deploy-executor`)
**Covers:** `commands/vg/deploy.md` and the new `vg-deploy-executor` subagent

---

## 1. Background

### 1.1 Problem

`commands/vg/deploy.md` is currently 588 lines — above the 500-line slim entry ceiling established by R1a blueprint pilot. The file mixes three concerns:

1. **Orchestration** — env selection, user confirmation, telemetry emission, DEPLOY-STATE.json read/write coordination.
2. **Per-env execution logic** — sandbox/staging/prod sequences with SSH commands, build artifact upload, service restart, smoke checks.
3. **Reference material** — env policy diff (sandbox vs staging vs prod), DEPLOY-STATE schema, log format.

The R5 batch spec (`vg-remaining-commands-batch-design.md`) flagged `deploy` as one of 4 files >500 lines requiring "slim + refs" treatment, but treated it as mechanical cleanup. In practice, deploy carries **judgement-heavy per-env logic** (smoke threshold per env, redeploy policy, log retention) that benefits from extraction into a dedicated subagent rather than reference docs.

### 1.2 Why dedicated subagent (not just refs)

Per discussion 2026-05-03 with operator:

- Future env additions (canary, prod-eu, prod-asia) will compound complexity.
- Per-env retry/rollback policies will diverge from a shared template.
- Without subagent boundary, every env-specific bug requires editing the entry skill (which loads into orchestrator AI context every invocation).
- Dedicated subagent isolates per-env logic: orchestrator only loads env contract + result, not full SSH sequences.

**Decision**: extract `vg-deploy-executor` subagent now (futureproof), even though current logic could fit in refs.

### 1.3 Scope

**In scope**:
- Refactor `commands/vg/deploy.md` from 588 to ≤500 lines (slim entry).
- Create `vg-deploy-executor` subagent in `.claude/agents/vg-deploy-executor.md`.
- Split per-env logic + reference material into `commands/vg/_shared/deploy/`.
- Update telemetry events: add `deploy.executor_spawned`, `deploy.executor_returned`, `deploy.executor_failed`.
- Add subagent to `vg-pre-tool-use-agent.sh` allow-list (already covered by `vg-*` glob).
- Pytest suite for slim size + subagent delegation.

**Out of scope**:
- Adding new envs (canary, prod-eu) — separate roadmap.
- Mobile deploy refactor — covered by `vg-_shared:mobile-deploy` shared ref.
- Codex mirror (`.codex/skills/vg-deploy/`) — defer.
- DEPLOY-STATE schema breaking changes — keep backward compatible.

### 1.4 Goals

- `commands/vg/deploy.md` ≤ 500 lines.
- `vg-deploy-executor` subagent with explicit input/output contract.
- Per-env logic isolated — orchestrator AI does not see SSH command bodies.
- DEPLOY-STATE.json schema preserved (downstream consumers unchanged).
- Subagent spawn narrated via `scripts/vg-narrate-spawn.sh` (UX baseline R2).
- Dogfood: 1 phase deploy to sandbox env on a test project succeeds end-to-end.

### 1.5 Non-goals

- Re-architecting DEPLOY-STATE.json schema.
- Replacing SSH transport (Ansible, Pulumi, etc.).
- Per-env hook integration changes.
- Removing `commands/vg/deploy.md` entirely (entry skill stays as orchestrator).

---

## 2. Inheritance from blueprint pilot

This round inherits from `_shared-ux-baseline.md`:

- **Per-task artifact split** — DEPLOY-STATE.json already has per-env block structure (`deployed.{env}`). Each env block is the natural per-unit. The flat JSON file IS the index. Deploy log per env is `.vg/phases/<P>/.deploy-log.{env}.txt`. Three layers satisfied implicitly.
- **Subagent spawn narration** — MANDATORY. Every spawn of `vg-deploy-executor` wraps with `bash scripts/vg-narrate-spawn.sh vg-deploy-executor {spawning|returned|failed}`.
- **Compact hook stderr** — if R6a adds new hooks (e.g. pre-deploy validate build artifact), hooks follow the 3-line stderr pattern from R1a.

---

## 3. Architecture

### 3.1 Orchestrator vs executor split

```
/vg:deploy <phase> [--env=sandbox|staging|prod] [--force]
   │
   ├── ENTRY SKILL (commands/vg/deploy.md, ≤500 lines)
   │     │
   │     ├── STEP 1: Preflight
   │     │     - Phase exists at .vg/phases/<P>/
   │     │     - Build artifact ready (read PHASE-STATE.md or BUILD-STATE.json)
   │     │     - vg.config.md has env block
   │     │
   │     ├── STEP 2: Env selection
   │     │     - Read DEPLOY-STATE.json existing blocks
   │     │     - Read vg.config.md env policy (which envs are configured)
   │     │     - Suggest env (default: lowest unsatisfied env in config)
   │     │
   │     ├── STEP 3: User confirm
   │     │     - AskUserQuestion: "Deploy phase <P> to <env>?"
   │     │     - Block if no confirm
   │     │
   │     ├── STEP 4: Spawn vg-deploy-executor
   │     │     - Pre-spawn narrate (green pill)
   │     │     - Agent(subagent_type="vg-deploy-executor", prompt={phase, env, force, vg_config})
   │     │     - Post-spawn narrate (cyan pill on success, red on fail)
   │     │
   │     ├── STEP 5: Verify executor result
   │     │     - DEPLOY-STATE.json updated with deployed.{env} block
   │     │     - Smoke check status recorded
   │     │     - Deploy log file exists
   │     │
   │     └── STEP 6: Emit telemetry + close
   │           - deploy.completed event
   │           - State marker .vg/phases/<P>/.step-markers/deploy-{env}.done
   │
   └── SUBAGENT (.claude/agents/vg-deploy-executor.md)
         - Receives: {phase, env, force, vg_config_excerpt}
         - Executes: per-env sequence (SSH, upload, restart, smoke)
         - Logs to: .vg/phases/<P>/.deploy-log.{env}.txt
         - Returns: {commit_sha, deployed_at, smoke_status, exit_code, log_path}
         - Writes: deployed.{env} block in DEPLOY-STATE.json
```

### 3.2 Per-env policy (loaded into subagent, not orchestrator)

| Env | Smoke threshold | Auto-rollback | Log retention | Confirm gate |
|---|---|---|---|---|
| sandbox | 1 endpoint up | no | 7 days | optional (skip with --yes) |
| staging | 3 endpoints + auth probe | no | 30 days | required |
| prod | full smoke suite + DB write probe | yes (on smoke fail) | 90 days | required (2nd factor: explicit out-of-scope, future enhancement) |

Subagent loads this table from `commands/vg/_shared/deploy/env-handling.md`. Orchestrator does NOT load it.

### 3.3 DEPLOY-STATE.json schema (UNCHANGED)

```json
{
  "phase": "P1",
  "schema_version": "1.0",
  "deployed": {
    "sandbox": {
      "commit_sha": "abc123",
      "deployed_at": "2026-05-03T14:22:18Z",
      "smoke_status": "pass",
      "exit_code": 0,
      "deploy_log_path": ".vg/phases/P1/.deploy-log.sandbox.txt"
    },
    "staging": null,
    "prod": null
  }
}
```

Backward compatibility: existing DEPLOY-STATE.json files read by R6a deploy skill must produce identical behavior to pre-R6a. Schema migration is NOT in scope.

### 3.4 Slim entry layout (≤500 lines)

```markdown
# /vg:deploy

[frontmatter — must_emit_telemetry includes deploy.executor_*]

<HARD-GATE>...</HARD-GATE>

## Red Flags
| ... |

## STEP 1 — Preflight (≤50 lines)
[checks + bash + emit-tasklist]

## STEP 2 — Env Selection (≤80 lines)
[read DEPLOY-STATE + vg.config, compute suggestion]

## STEP 3 — User Confirm (≤40 lines)
[AskUserQuestion + block on cancel]

## STEP 4 — Spawn Executor (≤60 lines)
[narrate-spawn + Agent(vg-deploy-executor) + handle return]

## STEP 5 — Verify Result (≤60 lines)
[assert DEPLOY-STATE updated, smoke status recorded]

## STEP 6 — Close (≤40 lines)
[emit telemetry, write step marker]

## References
- _shared/deploy/overview.md
- _shared/deploy/env-handling.md
- _shared/deploy/deploy-state.md
- _shared/deploy/executor-delegation.md
```

Total target: ~330 lines body + 100 lines frontmatter/HARD-GATE/Red Flags = ~430 lines.

---

## 4. Subagent contract — `vg-deploy-executor`

### 4.1 Frontmatter

```markdown
---
name: vg-deploy-executor
description: Execute per-env deploy sequence (SSH upload, service restart, smoke check). Spawned by /vg:deploy entry skill. Reports DEPLOY-STATE.json deployed.{env} block.
tools: Bash, Read, Write, Edit, Grep
model: claude-sonnet-4-6
---
```

### 4.2 Input contract

The orchestrator's spawn prompt MUST include:

- `phase` — phase ID (e.g. "P1")
- `env` — one of `sandbox|staging|prod`
- `force` — boolean (skip "already deployed at this commit" check)
- `vg_config_excerpt` — the `env.{env}` block from `vg.config.md` (SSH host, build cmd, deploy path, smoke endpoints)
- `commit_sha` — current HEAD sha (orchestrator passes; subagent does NOT re-resolve)
- `policy_ref` — pointer to `commands/vg/_shared/deploy/env-handling.md` for per-env policy table

### 4.3 Output contract

Subagent returns a single JSON object via stdout (last line):

```json
{
  "status": "success" | "smoke_fail" | "deploy_fail",
  "commit_sha": "abc123",
  "deployed_at": "2026-05-03T14:22:18Z",
  "smoke_status": "pass" | "fail" | "partial",
  "smoke_details": [{"endpoint": "/health", "status": 200}, ...],
  "exit_code": 0,
  "deploy_log_path": ".vg/phases/P1/.deploy-log.sandbox.txt"
}
```

Subagent ALSO writes `deployed.{env}` block to `.vg/phases/<P>/DEPLOY-STATE.json` directly. Orchestrator verifies the JSON file matches the returned object (cross-check).

### 4.4 Error modes

| Mode | Subagent action | Orchestrator action |
|---|---|---|
| SSH unreachable | Return `{status: "deploy_fail", smoke_status: "skipped"}` + write log | Narrate red pill, do NOT update DEPLOY-STATE, prompt user |
| Build artifact missing | Return early without SSH attempt, `{status: "deploy_fail"}` | Block — direct user to run `/vg:build` first |
| Smoke fail (non-prod) | Update DEPLOY-STATE with `smoke_status: "fail"` + log | Notify user, do NOT auto-rollback (sandbox/staging policy) |
| Smoke fail (prod) | Auto-rollback per env-handling.md | Narrate rollback in user-facing log |

### 4.5 Tool restrictions

Subagent MUST NOT:
- Spawn other subagents (no Agent tool).
- Read source code outside the build artifact (no exploration).
- Modify code.

Subagent MAY:
- SSH to env hosts (Bash).
- Read `vg.config.md`, `commands/vg/_shared/deploy/env-handling.md`, build artifact manifest.
- Write to `.vg/phases/<P>/DEPLOY-STATE.json` (atomic), `.vg/phases/<P>/.deploy-log.{env}.txt` (append).

---

## 5. File and directory layout

```
commands/vg/
  deploy.md                              REFACTOR: 588 → ≤500 lines (slim entry)
  _shared/deploy/                        NEW DIR
    overview.md                          NEW — flow diagram + step contract
    env-handling.md                      NEW — per-env policy table + smoke specs
    deploy-state.md                      NEW — DEPLOY-STATE.json schema + read/write rules
    executor-delegation.md               NEW — subagent input/output contract (mirrors §4)

.claude/agents/
  vg-deploy-executor.md                  NEW — subagent definition (frontmatter + workflow body)

scripts/
  vg-narrate-spawn.sh                    EXISTS — used in STEP 4

scripts/hooks/
  vg-meta-skill.md                       EXTEND — append "deploy"-specific Red Flags section

tests/skills/                            NEW DIR (or add to existing)
  test_deploy_slim_size.py               NEW — assert deploy.md ≤500 lines
  test_deploy_subagent_delegation.py     NEW — assert STEP 4 spawns vg-deploy-executor
  test_deploy_telemetry_events.py        NEW — assert must_emit includes deploy.executor_*
  test_deploy_state_schema_compat.py     NEW — assert pre-R6a DEPLOY-STATE.json files parse correctly
```

---

## 6. Error handling, migration, testing

### 6.1 Error handling

All blocks follow the compact 3-line stderr pattern from R1a. Subagent failure is a narration event (red pill), not a hard hook block — orchestrator decides whether to retry, prompt user, or abort.

### 6.2 Migration

- Existing `commands/vg/deploy.md` runs: stand as-is until R6a executes.
- Post-R6a: existing DEPLOY-STATE.json files (pre-R6a) MUST parse identically. `test_deploy_state_schema_compat.py` enforces this with fixtures from real prior runs.
- No data migration. No env config schema change.
- `.codex/skills/vg-deploy/SKILL.md` mirror: defer to dedicated round (Codex mirror is out of scope).

### 6.3 Testing

**Pytest static**:
- `test_deploy_slim_size.py` — `wc -l commands/vg/deploy.md ≤ 500`.
- `test_deploy_subagent_delegation.py` — grep entry skill for `Agent(subagent_type="vg-deploy-executor"`; assert ≥1 match in STEP 4 section.
- `test_deploy_telemetry_events.py` — parse frontmatter, assert `must_emit_telemetry` contains `deploy.executor_spawned`, `deploy.executor_returned` (or `deploy.executor_failed`), `deploy.completed`.
- `test_deploy_state_schema_compat.py` — load 3 fixture DEPLOY-STATE.json files (representative of pre-R6a runs), assert they parse + roundtrip without data loss.

**Pytest dynamic** (optional, requires fixture deploy target):
- `test_deploy_executor_smoke.py` — invoke executor against a localhost mock SSH target, assert DEPLOY-STATE updated correctly. Skipped in CI by default; manual.

**Manual dogfood**:
1. Pick 1 phase from a project with sandbox env configured.
2. Run `/vg:deploy <phase> --env=sandbox`.
3. Verify:
   - STEP 4 narrates green pill on spawn, cyan on return.
   - DEPLOY-STATE.json has `deployed.sandbox` block with `smoke_status: pass`.
   - Deploy log file exists at expected path.
   - Telemetry event log shows all `deploy.*` events emitted.

### 6.4 Exit criteria

R6a PASSES when ALL of:

1. `commands/vg/deploy.md` ≤ 500 lines.
2. `.claude/agents/vg-deploy-executor.md` exists with valid frontmatter (parseable).
3. `commands/vg/_shared/deploy/{overview,env-handling,deploy-state,executor-delegation}.md` exist.
4. All pytest static tests pass.
5. Manual dogfood: 1 phase deploy to sandbox PASS end-to-end.
6. R5.5 hook patches merged (prerequisite).

---

## 7. Round sequencing

R6a depends on R5.5 (hooks-source-isolation). Reason: dogfood will spawn `vg-deploy-executor` from possibly partial sessions; without R5.5 the allow-list false-block could fire.

R6a is independent of R6b (amend+debug) and may execute in parallel.

---

## 8. References

- Inherits UX baseline: `docs/superpowers/specs/_shared-ux-baseline.md`
- Inherits frontmatter pattern: `docs/superpowers/specs/2026-05-03-vg-blueprint-pilot-design.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r5.5-hooks-source-isolation-design.md`
- Sibling: `docs/superpowers/specs/2026-05-03-vg-r6b-amend-debug-design.md`
- Existing skill body: `commands/vg/deploy.md` (588 lines, source for refactor)
- Codex spec mirror reference: `.codex/skills/vg-deploy/SKILL.md` (defer)
- Mobile-deploy shared ref: `vg:_shared:mobile-deploy`
- Deploy-logging shared ref: `vg:_shared:deploy-logging`

---

## 9. UX baseline (mandatory cross-flow)

Per `_shared-ux-baseline.md`, R6a honors:

- **Per-task artifact split** — DEPLOY-STATE.json's `deployed.{env}` block IS the per-unit Layer 1; the flat file IS Layer 2/3 (consumers grep `deployed.<env>`). No additional split needed. Consumer pattern: `vg-load --phase N --artifact deploy-state --env <e>` (already supported).
- **Subagent spawn narration** — every `Agent(vg-deploy-executor)` call wraps with `vg-narrate-spawn.sh`. STEP 4 of slim entry shows the canonical pre/post pattern.
- **Compact hook stderr** — no new hooks added by R6a; existing hooks (R1a) already follow the pattern. Subagent failures are narration events, not hook blocks.
