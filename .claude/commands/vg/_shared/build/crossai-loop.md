# build CrossAI loop (STEP 6 — REFACTOR DEFERRED)

> **Note:** Per spec §1.5, CrossAI loop refactor deferred to separate
> round (88% loop fail rate is architectural — symptom of CrossAI
> verdict-loop pattern, not the build flow). This ref preserves backup
> bash verbatim so the slim entry (Task 12) can route through it
> without behavior change. Future refactor will replace this whole
> step with a different verification mechanism.

<HARD-GATE>
You MUST run STEP 6.1. The CrossAI loop emits a verdict — pass /
needs_revision / fail. The Stop hook checks `crossai.verdict` event
exists. Skipping this step blocks run completion.

The `build-crossai-required.py` validator at run-complete (step 12)
inspects events.db for iteration evidence — there is no "promise"
path. Bypassing this step BLOCKs run-complete.
</HARD-GATE>

---

## STEP 6.1 — invoke crossai-build-verify (11_crossai_build_verify_loop)

<prose: Spawns CrossAI subagent (Codex + Gemini via shell wrapper) to
verify build output against the 4 source-of-truth artifacts
(API-CONTRACTS.md, TEST-GOALS.md, CONTEXT.md decisions, PLAN.md
tasks). Loops up to 5 iterations; each BLOCK round is fixed by a
Sonnet `Agent` (not Task) subagent before re-invocation. Refactor
deferred — see spec §1.5.>

## Step 11: OHOK-7 MANDATORY CrossAI build verification loop

After wave execution + post-mortem, we MUST verify the build actually
completed against its 4 source-of-truth artifacts (API-CONTRACTS.md,
TEST-GOALS.md, CONTEXT.md decisions, PLAN.md tasks). This is ENFORCED
by `build-crossai-required.py` validator at run-complete — no "promise"
path; events.db evidence required.

**Flow**:

```
for iteration in 1..5:
  Run: python .claude/scripts/vg-build-crossai-loop.py \
          --phase ${PHASE_NUMBER} --iteration ${iter} --max-iterations 5

  Exit code 0 (CLEAN):
    - Both Codex + Gemini report no BLOCK findings
    - Emit build.crossai_loop_complete → BREAK out of loop
    - Build done
  Exit code 1 (BLOCKS_FOUND):
    - Read ${PHASE_DIR}/crossai-build-verify/findings-iter${iter}.json
    - Narrate + spawn Sonnet Agent (NOT Task) subagent:
        bash scripts/vg-narrate-spawn.sh general-purpose spawning \
          "crossai-fix iter-${iter} BLOCKs"
        Agent(subagent_type="general-purpose", model="claude-sonnet-4-6"):
          description: "Fix CrossAI BLOCK findings iter ${iter}"
          prompt: findings JSON + artifact paths + "fix each BLOCK, commit
                  with feat(${phase}-${iter}.fixN): subject"
        bash scripts/vg-narrate-spawn.sh general-purpose returned \
          "crossai-fix iter-${iter} done"
    - After subagent returns, continue to iter+1
  Exit code 2 (CLI_INFRA_FAILURE):
    - Retry once. If still fails, prompt user (CLI down / network / quota)

After loop:
  If cleaned before max: emit build.crossai_loop_complete (already done on
                          clean exit, just a safety)
  If 5 iterations exhausted WITHOUT clean:
    - Emit build.crossai_loop_exhausted
    - Prompt user with 3 options:
      (a) continue — run another 5 iterations
      (b) defer — proceed to /vg:review with remaining findings as known
          issues (emit build.crossai_loop_user_override)
      (c) skip + HARD debt — emit build.crossai_loop_user_override +
          vg-orchestrator override --flag=skip-crossai-build-loop
          --reason='<URL + explanation, ≥50ch>'
```

**Fix subagent model**: Sonnet (`claude-sonnet-4-6`). Sonnet is:
- Fast enough to not bloat loop runtime (~1 min per fix)
- Strong enough for contract-gap level fixes
- Isolated context so main Claude doesn't accumulate fix noise

**Severity threshold for triggering fix**: ANY BLOCK finding from either
CLI. MEDIUM/LOW findings are captured but deferred to /vg:review or
/vg:test phase (not blocking the build loop).

**Prompt template for fix subagent**:

```
You are fixing CrossAI BLOCK findings from build iteration ${N} of phase ${P}.

Read findings: ${PHASE_DIR}/crossai-build-verify/findings-iter${N}.json

For each finding with severity=BLOCK:
  1. Read the file at finding.file
  2. Understand the gap (finding.message) against the artifact ref
     (finding.artifact_ref — D-XX / G-XX / endpoint / task)
  3. Apply the minimal fix per finding.fix_hint
  4. Commit with: feat(${P}-${N}.fix${K}): <finding.artifact_ref>
     body: "Per CrossAI iter ${N} — <finding.message>"

Do NOT refactor, do NOT add features beyond the fix. Stop and return.
```

**IMPORTANT — this step is Claude-orchestrated, not bash-looped.**

Bash auto-loop was wrong: re-running CrossAI on SAME unfixed code just
re-produces the same findings. Main Claude (Opus) MUST orchestrate
iteration-by-iteration with a Sonnet Agent (NOT Task) subagent fixing
between iters; see the literal Agent() block above.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 11_crossai_build_verify_loop 2>/dev/null || true

# Phase 1 — iteration 1: establish baseline
CROSSAI_PHASE="${PHASE_NUMBER:-${PHASE_ARG}}"
CROSSAI_MAX_ITER=5
echo "▸ CrossAI build-verify iteration 1/${CROSSAI_MAX_ITER}..."
"${PYTHON_BIN:-python3}" .claude/scripts/vg-build-crossai-loop.py \
  --phase "${CROSSAI_PHASE}" --iteration 1 --max-iterations ${CROSSAI_MAX_ITER}
CROSSAI_RC=$?
echo "▸ iter 1 exit code: ${CROSSAI_RC} (0=CLEAN, 1=BLOCKS_FOUND, 2=INFRA_FAILURE)"
```

**Now the orchestrator (main Claude Opus) reads CROSSAI_RC and decides**:

- **CROSSAI_RC = 0**: loop script already emitted `build.crossai_loop_complete`.
  Proceed directly to step 12 (run-complete). Build done clean at iter 1.

- **CROSSAI_RC = 1**: BLOCK findings exist at
  `${PHASE_DIR}/crossai-build-verify/findings-iter1.json`.
  **Opus MUST narrate + dispatch a Sonnet `Agent` (NOT Task) subagent**
  with the findings JSON + fix prompt (see template above). The literal
  call is:

  ```bash
  bash scripts/vg-narrate-spawn.sh general-purpose spawning \
    "crossai-fix iter-1 BLOCKs"
  ```

  ```
  Agent(subagent_type="general-purpose", model="claude-sonnet-4-6", prompt=<rendered>)
  ```

  ```bash
  bash scripts/vg-narrate-spawn.sh general-purpose returned \
    "crossai-fix iter-1 done"
  ```

  Subagent reads each finding, applies minimal fix, commits with
  `feat(${PHASE}-1.fixN):` subject. After subagent returns (all BLOCKS
  fixed + committed), Opus re-invokes:
  ```bash
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-build-crossai-loop.py \
    --phase "${CROSSAI_PHASE}" --iteration 2 --max-iterations ${CROSSAI_MAX_ITER}
  ```
  Repeat: exit 0 → done; exit 1 → fix + iter 3; ... up to iter 5.

- **CROSSAI_RC = 2**: CLI infra failure (Codex/Gemini network/timeout/parse
  fail). Opus investigates (check `${PHASE_DIR}/crossai-build-verify/
  codex-iter*.md` + `gemini-iter*.md` for error detail). Either retry
  the same iteration after fixing infra OR escalate to user for override.

**After iter 5 without clean** — Opus MUST prompt user with 3 options:

```
━━━ ACTION REQUIRED — CrossAI loop exhausted ━━━

5 iterations ran without clean. Remaining BLOCK findings listed in
${PHASE_DIR}/crossai-build-verify/findings-iter5.json.

Pick one:
  (a) continue — spawn another Sonnet fix round + run iterations 6-10
      (HARD CAP: build.crossai_global_max=10 — refuses iter 11)
  (b) defer — record exhausted + proceed to /vg:review with remaining
      findings as known issues. Runs:
      python .claude/scripts/vg-orchestrator emit-crossai-terminal exhausted \
        --payload '{"iterations":5,"reason":"user_deferred"}'
  (c) skip + HARD debt — requires override.used with crossai flag:
      python .claude/scripts/vg-orchestrator override \
        --flag=skip-crossai-build-loop --reason='<ticket URL or SHA ≥50ch>'
      python .claude/scripts/vg-orchestrator emit-crossai-terminal user_override
```

Opus presents options, user picks, Opus invokes the chosen command. Run-
complete (step 12) BLOCKs until ONE of the three terminal events lands.

### R6 Task 7 — bounded global iteration cap (build.crossai_global_max)

When user picks `(a) continue` after iter 5, the legacy flow had no upper
bound on iter 6-10. With stubborn BLOCK findings, AI could rationalize
"just one more" indefinitely. Hard cap from config: `build.crossai_global_max`
(default 10). Even with user "continue" consent, total iterations cannot
exceed this cap.

**Before invoking `vg-build-crossai-loop.py` for ANY iteration ≥ 6, check:**

```bash
CROSSAI_GLOBAL_MAX=$(vg_config_get build.crossai_global_max 10 2>/dev/null || echo 10)

# CURRENT_ITER is the iteration about to run (e.g. 11 if user wants to continue past 10)
if [ "${CURRENT_ITER:-0}" -gt "${CROSSAI_GLOBAL_MAX:-10}" ]; then
  echo "⛔ CrossAI build loop hit GLOBAL hard cap: ${CURRENT_ITER}>${CROSSAI_GLOBAL_MAX}"
  echo "   Config key: build.crossai_global_max (default 10)"
  echo "   Refusing iteration — user must defer (option b) OR skip+HARD debt (option c)."

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.crossai_global_max_iter_reached" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"requested_iter\":${CURRENT_ITER},\"max\":${CROSSAI_GLOBAL_MAX}}" \
    >/dev/null 2>&1 || true

  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "build-crossai-global-max-iter" "${PHASE_NUMBER}" \
      "build.11_crossai_build_verify_loop" \
      "Build CrossAI loop hit global cap ${CURRENT_ITER}>${CROSSAI_GLOBAL_MAX} — user must defer or skip+HARD" \
      "$PHASE_DIR" 2>/dev/null || true

  exit 1
fi
```

This cap fires only when `(a) continue` would push the cumulative iteration
count past `build.crossai_global_max`. The existing 3-option prompt at iter
5 still handles 5→10 normally; this cap only refuses iter 11 onwards.

**Why no bash while-loop**: the fix between iterations needs an Agent
spawn (Sonnet with isolated context reading findings-iterN.json), which
a bash block can't issue. Each iteration is a discrete Claude-orchestrated
step driven by the `Agent` tool, not the legacy `Task` tool.

**If Opus bypasses this step** entirely: step 12 fires
`build-crossai-required` validator which sees 0 iteration events → BLOCK.
No way to skip via "promise" — events.db evidence required (OHOK-7/8).

```bash
mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "11_crossai_build_verify_loop" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/11_crossai_build_verify_loop.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 11_crossai_build_verify_loop 2>/dev/null || true
```
