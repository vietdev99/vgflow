# vg-accept-cleanup — input/output contract (delegation appendix, NOT a step)

<HARD-GATE>
This file is a **non-step appendix** — it carries the input/output
contract consumed by `overview.md` and the `vg-accept-cleanup`
SKILL.md. It owns NO step marker, emits NO step-active event, and runs
NO bash on its own. Step lifecycle (step-active → spawn → 3 hard-exit
gates → mark-step + accept.completed + run-complete) is performed
entirely by `overview.md` against the `7_post_accept_actions` marker.

Read order: `overview.md` first (lifecycle + post-spawn gates), then
this delegation contract (capsule + branch-on-verdict + JSON shape).
Do NOT execute any step bash from this file.
</HARD-GATE>

Run post-accept lifecycle cleanup for an ACCEPTED phase. Short-circuit to
minimal updates for DEFER/REJECTED/FAILED/ABORTED verdicts.

## Input capsule (build prompt from these)

Required env from main agent:
- `PHASE_NUMBER` — e.g. `7.6`
- `PHASE_DIR` — e.g. `.vg/phases/07.6-…/`
- `PLANNING_DIR` — e.g. `.vg/`
- `REPO_ROOT` — repo root
- `PYTHON_BIN` — `python3`
- `UAT_VERDICT` — `ACCEPTED` | `DEFER` | `REJECTED` | `FAILED` | `ABORTED`
  (parsed from `${PHASE_NUMBER}-UAT.md` Verdict line — the main agent reads
  this BEFORE spawning the subagent so the subagent can short-circuit).

## Subagent workflow

### Branch on verdict

If `UAT_VERDICT != ACCEPTED`: emit one log line, return early with
empty `cleanup_actions_taken[]`. UAT.md is already written (step 6),
PIPELINE-STATE keeps its non-accepted status. No artifact deletion.

If `UAT_VERDICT == ACCEPTED`: run all 8 subroutines below.

### Subroutines (ACCEPTED only)

1. **Scan-intermediate cleanup** — remove transient JSON artifacts
   that already aggregated into UAT.md / RUNTIME-MAP / SUMMARY:
   `scan-*.json`, `probe-*.json`, `nav-discovery.json`,
   `discovery-state.json`, `view-assignments.json`,
   `element-counts.json`, `.ripple-input.txt`, `.ripple.json`,
   `.callers.json`, `.god-nodes.json`, `.wave-context/`, `.wave-tasks/`.
   KEEP: SPECS, CONTEXT, PLAN*, API-CONTRACTS, TEST-GOALS, CRUD-SURFACES,
   SUMMARY*, RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md,
   RIPPLE-ANALYSIS.md, UAT.md, .step-markers/.

2. **Root-leaked screenshot cleanup** — `rm -f ./${PHASE_NUMBER}-*.png`
   (project convention bans root screenshots).

3. **Worktree + playwright prune** — `git worktree prune`,
   `playwright-lock.sh cleanup 0 all`.

4. **Bootstrap rule outcome attribution (Gap 3 fix)** — for each rule that
   fired during this phase, emit `bootstrap.outcome_recorded` event with
   `outcome=success` (ACCEPTED) and run
   `bootstrap-hygiene.py efficacy --apply` to update ACCEPTED.md hits +
   hit_outcomes counters.

5. **VG-native PIPELINE-STATE update** — set `status=complete`,
   `pipeline_step=accepted`, `updated_at=<now>`.

6. **ROADMAP flip** — `sed` Status line in `${PLANNING_DIR}/ROADMAP.md`
   to `complete`.

7. **CROSS-PHASE-DEPS flip (v1.14.0+ A.4)** — invoke
   `.claude/scripts/vg_cross_phase_deps.py flip "$PHASE_NUMBER"` to flip
   rows depending on this phase + suggest `/vg:review {source}
   --reverify-deferred` for affected phases.

8. **DEPLOY-RUNBOOK lifecycle (v1.14.0+ C.3)** — auto-draft from
   `.deploy-log.txt`, prompt user-fill section 5 (skip if offline),
   promote `.staged` → canonical.

### Return JSON contract

```json
{
  "verdict": "${UAT_VERDICT}",
  "cleanup_actions_taken": ["…"],
  "files_archived": ["…"],
  "files_removed": ["…"],
  "summary": "ACCEPTED phase ${PHASE_NUMBER} — N cleanup actions"
}
```

## Allowed tools (subagent FRONTMATTER)

`tools: [Read, Write, Edit, Bash, Glob, Grep]`

(NO `Task` / `Agent` — subagent must NOT spawn other subagents.)

## Forbidden inside subagent

- DO NOT modify UAT.md (already finalized in step 6).
- DO NOT touch `${PHASE_DIR}/.step-markers/*.done` — main agent does that.
- DO NOT delete files in the KEEP list (SPECS, CONTEXT, PLAN*, API-CONTRACTS,
  TEST-GOALS, CRUD-SURFACES, SUMMARY*, RUNTIME-MAP.json, etc.).
- DO NOT spawn subagents.
- DO NOT call AskUserQuestion (interactive happened in main agent at STEP 5).
- DO NOT exit non-zero on RUNBOOK draft warnings — log and continue.

## Failure modes

```json
{ "error": "verdict_mismatch", "uat_md_verdict": "…", "input_verdict": "…" }
{ "error": "pipeline_state_write_failed", "path": "…", "stderr": "…" }
{ "error": "subroutine_failed", "subroutine": "bootstrap_outcome_attribution", "stderr": "…" }
```

Main agent surfaces these via 3-line block + retry option. Subroutine
failures are non-fatal individually — the subagent collects failures and
returns a partial-success JSON only if a critical subroutine
(PIPELINE-STATE, ROADMAP) fails.

## Example main-agent prompt to subagent

```
Run post-accept cleanup for phase {PHASE_NUMBER}.

Inputs:
- PHASE_NUMBER={PHASE_NUMBER}
- PHASE_DIR={PHASE_DIR}
- PLANNING_DIR={PLANNING_DIR}
- REPO_ROOT={REPO_ROOT}
- UAT_VERDICT={UAT_VERDICT}

Read your SKILL.md for the full per-subroutine bash. Branch on UAT_VERDICT
— short-circuit for non-ACCEPTED verdicts. Return the JSON contract from
your SKILL §Output.
```
