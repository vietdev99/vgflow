---
name: vg:deploy
description: Standalone deploy skill — multi-env (sandbox/staging/prod), writes deployed.{env} block to DEPLOY-STATE.json. Optional step between /vg:build and /vg:review/test/roam. Suggestion-only consumers downstream — this skill produces the data; runtime gates use it to recommend env via enrich-env-question.py.
argument-hint: "<phase> [--envs=sandbox,staging,prod] [--all-envs] [--dry-run] [--non-interactive] [--prod-confirm-token=DEPLOY-PROD-{phase}] [--allow-build-incomplete] [--pre-test] [--init (bootstrap .vg/DEPLOY-CONTRACT.json interactively)]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - TodoWrite
runtime_contract:
  must_write:
    - "${PHASE_DIR}/DEPLOY-STATE.json"
  must_touch_markers:
    - "0_parse_and_validate"
    - "0a_env_select_and_confirm"
    - "1_deploy_per_env"
    - "2_persist_summary"
    - "complete"
  must_emit_telemetry:
    - event_type: "phase.deploy_started"
      phase: "${PHASE_NUMBER}"
    - event_type: "phase.deploy_completed"
      phase: "${PHASE_NUMBER}"
    # Task 44b — tasklist projection enforcement (Bug L)
    - event_type: "deploy.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "deploy.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "deploy.tasklist_projection_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_evidence_run_mismatch"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_depth_invalid"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "deploy.tasklist_block_handled_unresolved"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
  forbidden_without_override:
    - "--allow-build-incomplete"
---

<HARD-GATE>
You MUST follow STEP 0 through `complete` in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.

You MUST call TodoWrite IMMEDIATELY after STEP 0 (`0_parse_and_validate`)
runs `emit-tasklist.py` — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The
PostToolUse TodoWrite hook auto-writes that signed evidence.

TodoWrite MUST include sub-items (`↳` prefix) for each group header;
flat projection (group-headers only) is rejected by the PostToolUse
depth check (Task 44b Rule V2 — `depth_valid=false` evidence triggers
the PreToolUse depth gate).
</HARD-GATE>

<rules>
1. **Build must be complete** — PIPELINE-STATE.steps.build.status ∈ {accepted, tested, reviewed, built-with-debt, built-complete}. Otherwise BLOCK (override: `--allow-build-incomplete` logs override-debt).
2. **Multi-env supported, sequential execution** — each env runs after the previous completes. Parallel would risk infrastructure contention (shared SSH connection, same DB seed, etc).
3. **Prod requires explicit confirmation** — separate AskUserQuestion 3-option danger gate (PROCEED / NON-PROD-ONLY / ABORT). For non-interactive runs, `--prod-confirm-token=DEPLOY-PROD-{phase}` must match exactly.
4. **Per-env failure handling** — DOES NOT auto-abort remaining envs. Ask user continue/skip-failed/abort-all. Failed env writes `health: "failed"` + error log.
5. **DEPLOY-STATE.json merges** — preserves `preferred_env_for` (set by /vg:scope step 1b), `preferred_env_for_skipped` flag, and any unrelated future keys. Only `deployed.{env}` block is rewritten per run.
6. **Rollback hint** — capture `previous_sha` from existing `deployed.{env}.sha` BEFORE overwriting. Future `/vg:rollback` consumer reads this.
7. **--dry-run** prints commands but doesn't execute. Useful for verifying config + flags before real deploy.
</rules>

<objective>
Standalone optional skill bridging /vg:build → /vg:review/test/roam. User
runs `/vg:deploy <phase>` after build, picks one or more envs, this skill
runs the canonical deploy sequence per env (build → restart → health) on
that target, captures SHA + timestamp + health into
`${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}` block.

Downstream env gates (review/test/roam step 0a) read this state via
`enrich-env-question.py` (B1) and surface "deployed Nmin ago, sha XXXX"
evidence in the AskUserQuestion options. The pipeline becomes:

```
specs → scope → blueprint → build → [DEPLOY] → review → test → [roam] → accept
                                       ↑                  ↑      ↑       ↑
                                   writes              all read DEPLOY-STATE
                                   DEPLOY-STATE        for env recommendation
```

This skill never auto-picks env at runtime gates — those still fire
AskUserQuestion. /vg:deploy just feeds the suggestion data layer.
</objective>

<process>

### Preflight section (extracted v2.73.0 T1)

Read `_shared/deploy/preflight.md` and follow it exactly.
Includes 2 steps: 0_parse_and_validate, 0a_env_select_and_confirm.

### Execute per-env (extracted v2.73.0 T2)

Read `_shared/deploy/execute.md` and follow it exactly.
Includes 1 step: 1_deploy_per_env.

### Persist + close (extracted v2.73.0 T3 — final)

Read `_shared/deploy/persist-and-close.md` and follow it exactly.
Includes 2 steps: 2_persist_summary, complete.

</process>

<success_criteria>
- Build prereq ok (or debt), selected envs exist, prod confirmed by AskUserQuestion or token.
- Env commands run sequentially; health retries 30s; failed env does not auto-abort siblings.
- DEPLOY-STATE.json merges `deployed.{env}`, preserves `preferred_env_for`, captures `previous_sha`.
- `phase.deploy_completed` telemetry emits; `${PHASE_DIR}/.deploy-log.{env}.txt` exists per env.
</success_criteria>
