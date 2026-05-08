# Reflection Trigger (Shared Reference)

Referenced by end-of-step substeps in `/vg:scope`, `/vg:blueprint`,
`/vg:build` (end-of-wave), `/vg:review`. DRY the reflector spawn so each
host command only writes a short snippet.

## How to invoke

Each host command emits a `<step name="bootstrap_reflection">` block at the
end of its step (or after each wave, for build). That step MUST:

1. **Skip silently** if bootstrap zone absent OR config disables reflection:
   ```bash
   [ ! -d ".vg/bootstrap" ] && return 0
   ```

2. **Prepare inputs** (step-specific):
   ```bash
   REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
   REFLECT_STEP="{scope|blueprint|build|review|wave}"
   REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
   USER_MSG_FILE="${VG_TMP}/reflect-user-msgs-${REFLECT_TS}.txt"
   TELEMETRY_SLICE="${VG_TMP}/reflect-telemetry-${REFLECT_TS}.jsonl"
   OVERRIDE_SLICE="${VG_TMP}/reflect-overrides-${REFLECT_TS}.md"

   # Empty file if no extraction available (orchestrator may populate)
   : > "$USER_MSG_FILE"

   # Filter telemetry to this phase + step
   grep -E "\"phase\":\"${PHASE}\".*\"step\":\"${REFLECT_STEP}\"" \
     "${PLANNING_DIR:-.vg}/telemetry.jsonl" 2>/dev/null | tail -200 \
     > "$TELEMETRY_SLICE" || true

   # Collect override-debt entries created in this step
   grep -E "\"step\":\"${REFLECT_STEP}\"" \
     "${PLANNING_DIR:-.vg}/OVERRIDE-DEBT.md" 2>/dev/null > "$OVERRIDE_SLICE" \
     || true
   ```

3. **Spawn reflector agent** (Haiku, isolated context):
   ```
   Use Agent tool with:
     subagent_type: "general-purpose"
     model: "haiku"
     description: "Reflection end-of-{step} phase {PHASE}"
     prompt: """
       Use skill: vg-reflector

       STEP           = "{REFLECT_STEP}"
       PHASE          = "{PHASE}"
       PHASE_DIR      = "{PHASE_DIR}"
       USER_MSG_FILE  = "{USER_MSG_FILE}"
       TELEMETRY_FILE = "{TELEMETRY_SLICE}"
       OVERRIDE_FILE  = "{OVERRIDE_SLICE}"
       ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
       REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
       OUT_FILE       = "{REFLECT_OUT}"

       Read .claude/skills/vg-reflector/SKILL.md and follow protocol.
       HARD RULE: never read parent conversation transcript.
       Output max 3 candidates with evidence to OUT_FILE.
     """
   ```

4. **Post-reflect interactive prompt** — if `$REFLECT_OUT` has candidates:
   ```
   📝 Reflection — {step} phase {PHASE} found {N} learning(s):

   [1] {title}
       Type: {type}
       Scope: {scope}
       Evidence: {N} items — {first_sample}
       Confidence: {conf}

       → Proposed: {target summary}

       [y] ghi sổ tay  [n] reject  [e] edit inline  [s] skip lần này
   ```

   User chooses per item:
   - `y` → delegate to `/vg:learn --promote L-{id}` internally (conflict check,
     schema validate, dry-run preview, git commit atomic)
   - `n` → prompt "lý do ngắn?" → append REJECTED.md with reason
   - `e` → inline field-edit loop (not external editor):
     ```
     Editing L-{id}:
       (1) title
       (2) scope
       (3) prose / target
       (4) action
       [1-4/done]:
     ```
   - `s` → append candidate to CANDIDATES.md for later review

5. **Telemetry**:
   ```bash
   emit_telemetry "bootstrap.reflection_ran" PASS \
     "{\"step\":\"${REFLECT_STEP}\",\"phase\":\"${PHASE}\",\"candidates\":${CANDIDATE_COUNT:-0}}"
   ```

6. **Never block host step completion** — reflector crash → log warning, continue.

## Rate limiting

- Max 1 reflection per step per run
- `/vg:build` runs reflection at end of EACH wave (build is long-running,
  multiple learnings may emerge mid-step)
- Other commands (`scope`, `blueprint`, `review`) run once at end

## Autonomous-mode accumulation (v1.15.1 — hard rule)

Long multi-wave runs (e.g. `/vg:build` with 5+ waves) cannot stop at every
wave for interactive y/n/e/s prompts — that breaks unattended execution.
BUT the reflector itself MUST still fire. Protocol:

1. **Every wave** — reflector runs + writes candidates to
   `${PHASE_DIR}/reflection-wave-${N}-${TS}.yaml`. **No user prompt yet.**
   Append each candidate YAML block to `.vg/bootstrap/CANDIDATES.md` as
   pending. This is the "accumulate silently" mode.

2. **Once per phase, at phase-end** — orchestrator MUST collect every
   reflection YAML under `${PHASE_DIR}/reflection-*.yaml` produced by the
   phase's waves, present ALL pending candidates in ONE y/n/e/s review
   session (not per-wave). This is the single mandatory prompt point.

3. **No escape hatch** — orchestrator MAY NOT skip the phase-end prompt for
   any reason short of the declared skip conditions below. "Interactive
   prompt interrupts autonomous run" is NOT a valid skip reason — the
   prompt fires exactly once, at a natural checkpoint.

4. **Single-step commands** (scope, blueprint, review) — reflector runs at
   end-of-step, candidates go straight to the single y/n/e/s prompt (no
   accumulation needed — only one reflection per run).

## Skip conditions (exhaustive — any other reason is a bug)

- `.vg/bootstrap/` directory absent (user hasn't opted in at project init)
- Config `bootstrap.reflection_enabled: false` (user explicitly disabled)
- Step exited with fatal error (reflect when next run succeeds — reflector
  on broken state produces garbage candidates)

Explicitly NOT valid skip reasons:
- "Autonomous run, don't want to pause for interactive prompt" → use
  phase-end accumulation above
- "Context budget concern" → reflector runs in isolated Haiku context, does
  not consume orchestrator budget
- "No signals this step" → reflector handles silently (0-candidate output
  is fine); orchestrator MUST still fire it

## Static verification

`.claude/scripts/verify-reflection-coverage.py` walks host command files
(build.md, blueprint.md, scope.md, review.md) and verifies each has a
`<step name="bootstrap_reflection">` OR `<step name="*_reflection_*">`
block that invokes this skill. Missing reflection step in any host = CI
fail. Run: `python .claude/scripts/verify-reflection-coverage.py`

## post-deploy (NEW v1.1, Stage 2 task 1/5)

**Trigger event:** `phase.deploy_completed` (any outcome).

**Inputs to reflector:**
- `events.db` query: `deploy.{started,completed,failed}` for current phase
- `${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}` block
- `${PHASE_DIR}/.deploy-log.{env}.txt` per env stdout
- `vg.config.md` env list, deploy commands, package manager

**Candidate target:** target_step=deploy, type=procedural.

**Fingerprint:** hash(repo_id + deploy_target + health_cmd + env + commands + dockerfile_hash + package_manager).

**Gating:** vg.config.md → meta_memory_mode != "disabled". Default disabled — no spawn until explicitly enabled per Stage 6 rollout flag (Section 13.6 design).

**Wiring site:** commands/vg/deploy.md — block inserted after existing phase.deploy_completed emit. See test: tests/test_post_deploy_reflector_wiring.py.

## post-test (NEW v1.1, Stage 2 task 2/5)

**Trigger event:** `phase.test_completed` (any outcome).

**Inputs to reflector:**
- events.db query: test.* + codegen.* for current phase
- TEST-GOALS.md per-goal verdicts
- fix-loop iteration count

**Candidate target:** target_step=test, type=declarative|procedural (auto-detect).

**Fingerprint:** hash(framework + selector_strategy + repo_id).

**Gating:** vg.config.md → meta_memory_mode != "disabled". Default disabled.

**Wiring site:** commands/vg/test.md.

## post-accept (NEW v1.1, Stage 2 task 3/5)

**Trigger event:** `phase.accept_uat_completed` (any outcome).

**Inputs to reflector:**
- UAT-CHECKLIST.md per-item verdicts
- events.db query: `gate.fired` for current phase
- structured digest of user msgs (NO raw transcript — echo-chamber guard)

**Candidate target:** target_step=accept, type=declarative.

**Fingerprint:** hash(phase_type + gate_pattern + repo_id).

**Gating:** vg.config.md → meta_memory_mode != "disabled". Default disabled.

**Wiring site:** commands/vg/accept.md.

## post-roam (NEW v1.1, Stage 2 task 4/5)

**Trigger event:** `phase.roam_completed` (any outcome).

**Inputs to reflector:**
- roam findings JSON
- state-mismatch report

**Candidate target:** target_step=roam, type=declarative (caught patterns).

**Fingerprint:** hash(lens_set + bug_pattern + repo_id).

**Gating:** vg.config.md → meta_memory_mode != "disabled". Default disabled.

**Wiring site:** commands/vg/roam.md.

Note: roam catches bugs review/test miss → high-signal reflector input (Codex #2).
