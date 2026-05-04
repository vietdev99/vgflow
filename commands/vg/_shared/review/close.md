# review close (STEP 9 — write artifacts + reflection + run-complete)

3 steps for run-completion:
- `write_artifacts` — verify + commit RUNTIME-MAP.json/.md, GOAL-COVERAGE-MATRIX.md, element-counts.json
- `bootstrap_reflection` — spawn vg-reflector subagent for retrospective (heavy, narrate)
- `complete` — PIPELINE-STATE update + auto-resolve hotfix debt + verdict-aware closing message + 8+ post-verdict gates + tasklist clear + run-complete

<HARD-GATE>
You MUST complete all 3 steps in order. The `complete` marker +
`review.completed` event MUST fire — Stop hook verifies both. Tasklist
clear via R1a sentinel (TodoWrite all items completed) — implementation
in `_shared/lib/tasklist-projection-instruction.md`.

Required artifacts (BLOCK commit if any missing — verify with Glob):
- `${PHASE_DIR}/RUNTIME-MAP.json` (canonical JSON, write FIRST)
- `${PHASE_DIR}/RUNTIME-MAP.md` (derived from JSON)
- `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md` (from Phase 4)

Reflection spawn MUST use `Agent` (not `Task` — Codex correction per
plan §C) + narrate-spawn wrapper (UX baseline req 2). Reflector reads
artifacts + telemetry + git log only — NEVER the parent transcript
(echo chamber forbidden). DO NOT skip reflection on "clean" runs —
empirical 96.5% inline-skip rate without subagent.

Post-verdict gates in `complete` step (run AFTER mark-step + emit-event,
BEFORE run-complete):
- verify-flow-compliance (advisory by default, override --skip-compliance)
- verify-matrix-evidence-link (block on fabricated READY status)
- rcrurd-preflight --mode post (post_state lifecycle gate, BLOCK on assertion fail)
- verify-matrix-staleness (block on goals READY without submit/2xx)
- verify-evidence-provenance (block on missing structured provenance)
- verify-mutation-actually-submitted (block on Cancel-only "passed" goals)
- verify-rcrurd-depth (scanner-stopped-too-early gate)
- verify-asserted-rule-match (BR-NN drift gate)
- verify-replay-evidence (--enable-replay opt-in)
- verify-cross-phase-decision-validity (D-XX revoked/missing gate)
- verify-scanner-business-alignment (two-phase adversarial verifier)
- DEFECT-LOG.md generation via tester-pro-cli.py (D21)
</HARD-GATE>

---

## STEP 9.1 — write artifacts (write_artifacts)

<step name="write_artifacts" mode="full">
## Write Final Artifacts

**Write order: JSON first, then derive MD from it.**

**1. `${PHASE_DIR}/RUNTIME-MAP.json`** — canonical JSON (source of truth). MUST be written FIRST.
**2. `${PHASE_DIR}/RUNTIME-MAP.md`** — derived from JSON (human-readable). Written AFTER JSON.
**3. `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`** — from Phase 4
**4. `${PHASE_DIR}/element-counts.json`** — from Phase 1b

### MANDATORY ARTIFACT VALIDATION (do NOT skip)

After writing all files, verify they exist before committing:
```
Required files — BLOCK commit if ANY missing:
  ✓ ${PHASE_DIR}/RUNTIME-MAP.json     ← downstream /vg:test reads this, NOT .md
  ✓ ${PHASE_DIR}/RUNTIME-MAP.md
  ✓ ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md

Use Glob to confirm each file exists. If RUNTIME-MAP.json is missing,
you MUST create it before proceeding. The .md alone is NOT sufficient.
```

Commit:
```bash
git add ${PHASE_DIR}/RUNTIME-MAP.json ${PHASE_DIR}/RUNTIME-MAP.md \
       ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md ${PHASE_DIR}/element-counts.json \
       ${SCREENSHOTS_DIR}/
# UNREACHABLE-TRIAGE artifacts (only exist if triage ran — i.e., any UNREACHABLE goal)
[ -f "${PHASE_DIR}/UNREACHABLE-TRIAGE.md" ]   && git add "${PHASE_DIR}/UNREACHABLE-TRIAGE.md"
[ -f "${PHASE_DIR}/.unreachable-triage.json" ] && git add "${PHASE_DIR}/.unreachable-triage.json"
git commit -m "review({phase}): RUNTIME-MAP — {views} views, {actions} actions, gate {PASS|BLOCK}"
```
</step>

---

## STEP 9.2 — end-of-step reflection (bootstrap_reflection)

<step name="bootstrap_reflection" mode="full">
## End-of-Step Reflection (v1.15.0 Bootstrap Overlay)

Before closing review, spawn the **reflector** subagent to analyze this step's
artifacts + user messages + telemetry and draft learning candidates for user
review. Primary path for project self-adaptation.

**Skip conditions** (reflection does nothing, exit 0):
- `.vg/bootstrap/` directory absent (project hasn't opted in)
- `config.bootstrap.reflection_enabled == false` (user disabled)
- Review verdict = `FAIL` with fatal errors (reflect when next review succeeds)

### Pre-spawn narration (UX req 2)

```bash
bash scripts/vg-narrate-spawn.sh vg-reflector spawning \
  "end-of-step reflection for review phase ${PHASE_NUMBER}"
```

### Run

```bash
BOOTSTRAP_DIR=".vg/bootstrap"
if [ ! -d "$BOOTSTRAP_DIR" ]; then
  :  # Bootstrap not opted in — skip silently
else
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-review-${REFLECT_TS}.yaml"
  USER_MSG_FILE="${VG_TMP}/reflect-user-msgs-${REFLECT_TS}.txt"

  : > "$USER_MSG_FILE"

  TELEMETRY_SLICE="${VG_TMP}/reflect-telemetry-${REFLECT_TS}.jsonl"
  grep -E "\"phase\":\"${PHASE}\".*\"command\":\"vg:review\"" "${PLANNING_DIR}/telemetry.jsonl" 2>/dev/null \
    | tail -200 > "$TELEMETRY_SLICE" || true

  OVERRIDE_SLICE="${VG_TMP}/reflect-overrides-${REFLECT_TS}.md"
  grep -E "\"step\":\"review\"" "${PLANNING_DIR}/OVERRIDE-DEBT.md" 2>/dev/null > "$OVERRIDE_SLICE" || true

  echo "📝 Running end-of-step reflection (Haiku, isolated context)..."
fi
```

### Spawn reflector agent (isolated Haiku) — Tool name = Agent

Use `Agent` tool (NOT `Task` — per plan §C Codex correction) with skill
`vg-reflector`, model `haiku`, fresh context:

```
Agent(
  description="End-of-step reflection for review phase {PHASE}",
  subagent_type="general-purpose",
  prompt="""
Use skill: vg-reflector

Arguments:
  STEP           = "review"
  PHASE          = "{PHASE}"
  PHASE_DIR      = "{PHASE_DIR absolute path}"
  USER_MSG_FILE  = "{USER_MSG_FILE}"
  TELEMETRY_FILE = "{TELEMETRY_SLICE}"
  OVERRIDE_FILE  = "{OVERRIDE_SLICE}"
  ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
  REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
  OUT_FILE       = "{REFLECT_OUT}"

Read .claude/skills/vg-reflector/SKILL.md and follow workflow exactly.
Do NOT read parent conversation transcript — echo chamber forbidden.
Output max 3 candidates with evidence to OUT_FILE.
"""
)
```

### Post-spawn narration

```bash
bash scripts/vg-narrate-spawn.sh vg-reflector returned \
  "${CANDIDATE_COUNT:-0} learning candidate(s) drafted to ${REFLECT_OUT}"
```

### Interactive promote flow (user gates)

After reflector exits, parse OUT_FILE. If candidates found, show to user with the [y]/[n]/[e]/[s] menu (see review.md.r3-backup lines 7146-7184 for verbatim format). For `y` → delegate to `/vg:learn --promote L-{id}` internally; for `n` → REJECTED.md; for `e` → field-by-field edit; for `s` → leave in `.vg/bootstrap/CANDIDATES.md` for `/vg:learn --review`.

### Emit telemetry

```bash
emit_telemetry "bootstrap.reflection_ran" PASS \
  "{\"step\":\"review\",\"phase\":\"${PHASE}\",\"candidates\":${CANDIDATE_COUNT:-0}}"
```

### Failure mode

Reflector crash or timeout → log warning, continue to `complete` step. Never block review completion.

```
⚠ Reflection failed — review completes normally. Check .vg/bootstrap/logs/
```
</step>

---

## STEP 9.3 — complete (run-end + post-verdict gates + tasklist clear)

<step name="complete">
**Update PIPELINE-STATE.json:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'reviewed'; s['pipeline_step'] = 'review-complete'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```

**v2.6.1 (2026-04-26): Auto-resolve hotfix debt entries from prior phases.**

If THIS phase's review ran clean (no `--allow-orthogonal-hotfix` /
`--allow-no-bugref` / `--allow-empty-bugfix` overrides hit), prior phases'
OPEN debt entries with matching gate_id auto-resolve. Closes AUDIT.md D2 H4
(hotfix overrides had no natural resolution path → debt piled up forever).

Each gate_id maps to a specific re-run condition that the current clean
review proves: if review passed without orthogonal-hotfix override, the
"goal-coverage" condition is satisfied for prior phases too.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
if type -t override_auto_resolve_clean_run >/dev/null 2>&1; then
  # Only resolve if THIS phase didn't fall back to the override itself
  if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
    override_auto_resolve_clean_run "review-goal-coverage" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
    override_auto_resolve_clean_run "bugfix-bugref-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
    override_auto_resolve_clean_run "bugfix-code-delta-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
fi
```

**Display — VERDICT-AWARE next steps (MANDATORY format).**

The closing message MUST follow this structure regardless of orchestrator (Claude / Codex / Gemini).
Every finding section MUST end with a concrete actionable command, not just a description.

### When verdict = PASS
```
Review complete for Phase {N} — PASS.
  Goals: {ready}/{total} READY ({pct}%)
  Gate: PASS (critical {C}/{C} 100%, important {I}/{I_total} ≥80%)
  Artifacts: RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md{REVIEW_FEEDBACK_SUFFIX}

Next:
  /vg:test {phase}            # codegen + run regression suite
```

### When verdict = FLAG (passed but with improvements)
```
Review complete for Phase {N} — FLAG ({N} non-blocking findings).
  Goals: {ready}/{total} READY
  Gate: PASS-WITH-FLAGS

Findings (improvements — non-blocking):
  - [Med] {one-line summary} → fix at {file:line}, then commit
  - [Low] {one-line summary} → defer or fix at {file:line}
  ... (full detail in REVIEW-FEEDBACK.md)

Next (pick one):
  /vg:test {phase}                          # proceed — flags are advisory
  edit {file:line}; git commit; /vg:next    # fix flags first, then continue
```

### When verdict = BLOCK (cannot proceed)
```
Review complete for Phase {N} — BLOCK.
  Goals: {ready}/{total} READY ({blocked} BLOCKED, {failed} FAILED, {unreach} UNREACHABLE)
  Gate: BLOCK ({reason — e.g., "critical goal G-03 FAILED" or "infra success_criteria 1/8 READY"})

Findings (severity-grouped — full detail in REVIEW-FEEDBACK.md):
  ⛔ Critical/Nghiêm trọng ({N}):
     1. {one-line summary}
        ↳ Fix: {concrete action — file:line, command, or workflow}
        ↳ Verify: {how to confirm — curl, test, diff}
     2. ...
  ⚠ High/Cao ({N}):
     ... (same format)
  ⓘ Medium/Trung bình ({N}):
     ... (same format)

Next steps (pick the matching path — DO NOT just re-run /vg:review blindly):

  A. Fix code bugs found → re-review:
     # Edit affected files (paths above), then stage + commit as SEPARATE
     # steps (v2.5.2.7: don't chain staging with commit — if commit-msg
     # hook BLOCKs on missing citation, prior `git add` success gets
     # masked by the red "Exit 1" UI label):
     git add path/to/fixed-file.ts              # stage intentional files
     git commit -m "fix({phase}-XX): {summary}

Per CONTEXT.md D-XX OR Per API-CONTRACTS.md"  # body must cite
     /vg:review {phase} --retry-failed      # only re-scan failed goals (faster)
     # OR /vg:review {phase}                # full re-scan if many fixes

  B. If findings need scope discussion (architectural, decision change):
     /vg:amend {phase}                       # mid-phase change request workflow
     # then re-blueprint + re-build before re-review

  C. If findings are infra/env (services down, config missing):
     /vg:doctor                              # diagnose env + service health
     # fix infra → /vg:review {phase}

  D. If finding is BUG in /vg:review tooling itself (not phase code):
     /vg:bug-report                          # surface to vietdev99/vgflow

  E. If you DISAGREE with verdict (false positive):
     # Open REVIEW-FEEDBACK.md, dispute specific finding with evidence
     /vg:review {phase} --override-reason "..." --allow-failed=G-XX
     # Will register in OVERRIDE-DEBT — re-evaluated at /vg:accept
```

### Hard rules for AI orchestrator (Claude/Codex/Gemini)
1. **Never end a BLOCK review without listing per-finding fixes + verify steps.** Bare list of issues = user has to re-derive next action — anti-pattern.
2. **Use RELATIVE paths** in narration (`apps/api/src/plugins/health.ts:23`), NOT absolute (`/D/Workspace/...`). Absolute paths waste 60% of terminal width on repeated prefixes.
3. **Per-finding format MUST be:**
   ```
   {N}. [Severity] {ONE LINE root-cause}
        ↳ Fix:    {file:line edit OR shell command OR workflow}
        ↳ Verify: {1-line check command OR test ID}
        ↳ Refs:   {file:line, file:line}  (only if 2+ refs needed)
   ```
4. **Closing MUST contain "Next:" block** with at least 2 labeled options (A/B/C...) when verdict ≠ PASS.
5. **If executor cannot run something** (bash broken, no internet, missing creds), say so EXPLICITLY and tell user the manual command to run instead. Don't bury it in middle of output.


```bash
# v2.2 — complete step marker + terminal emit + run-complete
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0_parse_and_validate 2>/dev/null || true
READY_COUNT=$(grep -c "READY" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo 0)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_ready\":${READY_COUNT}}" >/dev/null

# v2.38.0 — Flow compliance audit
if [[ "$ARGUMENTS" =~ --skip-compliance=\"([^\"]*)\" ]]; then
  COMP_REASON="${BASH_REMATCH[1]}"
else
  COMP_REASON=""
fi
COMP_SEV=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
COMP_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "review" "--severity" "$COMP_SEV" )
[ -n "$COMP_REASON" ] && COMP_ARGS+=( "--skip-compliance=$COMP_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMP_ARGS[@]}"
COMP_RC=$?
if [ "$COMP_RC" -ne 0 ] && [ "$COMP_SEV" = "block" ]; then
  echo "⛔ Review flow compliance failed. See .flow-compliance-review.yaml or pass --skip-compliance=\"<reason>\"."
  exit 1
fi

# v2.45 fail-closed-validators PR: matrix↔runtime evidence cross-check.
# Phase 3.2 dogfood found GOAL-COVERAGE-MATRIX.md fabricating READY status
# even when goal_sequences[].result == "blocked" or sequence missing entirely.
# This validator catches the fabrication BEFORE review exits, so /vg:test
# never sees a lying matrix.
MATRIX_LINK_VAL=".claude/scripts/validators/verify-matrix-evidence-link.py"
if [ -f "$MATRIX_LINK_VAL" ]; then
  ${PYTHON_BIN:-python3} "$MATRIX_LINK_VAL" --phase-dir "$PHASE_DIR" --severity block
  MATRIX_LINK_RC=$?
  if [ "$MATRIX_LINK_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_evidence_link_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-evidence-link-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_evidence_link",
  "summary": "Review matrix-evidence-link gate failed — GOAL-COVERAGE-MATRIX.md asserts goal status that runtime evidence does not support",
  "fix_hint": "1. Re-run /vg:review ${PHASE_NUMBER} --retry-failed (record real sequences); 2. OR reclassify goals to UNREACHABLE/INFRA_PENDING/DEFERRED with justification"
}
JSON
    blocking_gate_prompt_emit "matrix_evidence_link" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# RFC v9 PR-D2 Codex-HIGH-1 fix: post_state lifecycle gate AFTER scanner ran.
# Pre_state checked at Phase 0.5 (pre-scanner); post_state must verify the
# action actually mutated state correctly. Without this leg, RCRURD is half-
# wired (Codex review found pre-only).
# Re-resolve base URL from config (PRE_BASE local to Phase 0.5; not in scope).
# Codex-R4-HIGH-2 fix: read base_url from ENV-CONTRACT.md (canonical),
# not from vg.config.md step_env (env NAME, not URL).
POST_BASE_RC=$("${PYTHON_BIN:-python3}" -c "
import re
try:
    text = open('${PHASE_DIR}/ENV-CONTRACT.md', encoding='utf-8').read()
    m = re.search(r'^target:\s*\n((?:[ \t].*\n)+)', text, re.MULTILINE)
    if m:
        bm = re.search(r'^\s*base_url:\s*[\"\\']?([^\"\\'\s#]+)', m.group(1), re.MULTILINE)
        if bm: print(bm.group(1))
except FileNotFoundError: pass
" 2>/dev/null)
[ -z "$POST_BASE_RC" ] && POST_BASE_RC="${VG_BASE_URL:-}"
HAS_POST_LIFECYCLE=$(grep -lE '^\s*post_state:' "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
# Codex-HIGH-5-bis fix: post_state setup error blocks even without runner exec
if [ "$HAS_POST_LIFECYCLE" -gt 0 ] && [ -z "$POST_BASE_RC" ] && \
   [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
  echo "⛔ RCRURD post_state setup error — FIXTURES declare post_state"
  echo "   blocks but no sandbox base_url available at run-complete."
  exit 1
fi
VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
[ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
if [ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] && \
   [ -d "${PHASE_DIR}/FIXTURES" ] && [ -n "$POST_BASE_RC" ]; then
  # Codex-HIGH-1-ter fix: snapshot must exist when delta assertions present
  POST_NEEDS_SNAP=$(grep -lE 'increased_by_at_least|decreased_by_at_least' \
    "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
  if [ "$POST_NEEDS_SNAP" -gt 0 ] && [ ! -f "${PHASE_DIR}/.rcrurd-pre-snapshot.json" ] && \
     [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    echo "⛔ RCRURD post_state — pre-snapshot missing but ${POST_NEEDS_SNAP}"
    echo "   fixture(s) declare delta assertions. Pre-mode at Phase 0.5"
    echo "   should have captured it. Re-run /vg:review from scratch."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_snapshot_missing" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  POST_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" \
    --phase "$PHASE_NUMBER" --base-url "$POST_BASE_RC" \
    --mode post --severity "${VG_RCRURD_POST_SEVERITY:-block}" \
    --pre-snapshot "${PHASE_DIR}/.rcrurd-pre-snapshot.json" 2>&1)
  POST_RC=$?
  echo "▸ RCRURD post_state: $(echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} post-state assertions failed)")
    elif v == "WARN":
        print(f"WARN ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed)")
    elif v == "PASS":
        print(f"PASS ({d.get(\"checked\",0)} fixtures)")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
  if [ "$POST_RC" -eq 2 ]; then
    echo "⛔ RCRURD post_state setup error — cannot proceed:"
    echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown\")[:300]}")
except: print("   (could not parse error)")
'
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if [ "$POST_RC" -eq 1 ] && [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_state_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-post-state-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_post_state",
  "summary": "RCRURD post_state gate BLOCK — fixture lifecycle assertions failed after the scanner action. State did not transition as expected.",
  "fix_hint": "Re-run scanner if action genuinely succeeded; or fix the action's expected_network/post_state assertion drift."
}
JSON
    blocking_gate_prompt_emit "rcrurd_post_state" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2 matrix-staleness final gate: after matrix is BUILT (Phase 4),
# re-run staleness validator at review-complete time. Step 0 entry pass catches
# stale entries from PRIOR runs; this catches stale entries created by THIS run
# (e.g. scanner recorded sequence but skipped submit, then matrix wrote READY).
# Phase 3.2 dogfood found 36/39 mutation goals stale despite verdict=PASS.
MATRIX_STALE_VAL=".claude/scripts/validators/verify-matrix-staleness.py"
if [ -f "$MATRIX_STALE_VAL" ]; then
  STALE_SEV="block"
  [[ "${ARGUMENTS}" =~ --allow-stale-matrix ]] && STALE_SEV="warn"
  ${PYTHON_BIN:-python3} "$MATRIX_STALE_VAL" --phase "${PHASE_NUMBER}" --severity "$STALE_SEV"
  STALE_RC=$?
  if [ "$STALE_RC" -ne 0 ] && [ "$STALE_SEV" = "block" ]; then
    SUSPECTED_N=$(${PYTHON_BIN:-python3} -c "
import json
try: print(json.load(open('${PHASE_DIR}/.matrix-staleness.json'))['suspected_count'])
except: print('?')
")
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_staleness_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"suspected\":${SUSPECTED_N}}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-staleness-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_staleness",
  "summary": "Matrix-staleness gate failed — ${SUSPECTED_N} mutation goal(s) marked READY without submit/2xx evidence",
  "fix_hint": "1. /vg:review ${PHASE_NUMBER} --retry-failed; 2. /vg:review ${PHASE_NUMBER} --re-scan-goals=G-XX,G-YY; 3. /vg:review ${PHASE_NUMBER} --dogfood; 4. /vg:review ${PHASE_NUMBER} --allow-stale-matrix --override-reason=... (debt)"
}
JSON
    blocking_gate_prompt_emit "matrix_staleness" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2.3 (RFC v9 D10) — evidence provenance gate. Mutation steps
# claiming success (action + 2xx network) MUST carry structured evidence:
# {source, artifact_hash, captured_at, schema_version, scanner_run_id |
# layer2_proposal_id}. Closes the trust hole where executor agents could
# fabricate evidence to flip matrix-staleness bidirectional sync.
#
# Codex-HIGH-4 fix: default to BLOCK (was warn). Migration grace via
# explicit `review.provenance.enforcement: warn` in vg.config.md OR
# --allow-legacy-provenance flag for phases pre-dating RFC v9.
PROV_VAL=".claude/scripts/validators/verify-evidence-provenance.py"
if [ -f "$PROV_VAL" ]; then
  # Resolve enforcement from config — env var wins, then grep config, default block
  PROV_MODE="${VG_PROVENANCE_ENFORCEMENT:-}"
  if [ -z "$PROV_MODE" ] && [ -n "${CONFIG_RAW:-}" ]; then
    PROV_MODE=$(echo "$CONFIG_RAW" | grep -A2 '^review:' | grep -E '^\s*provenance:' -A2 | \
                grep -E '^\s*enforcement:' | head -1 | sed 's/.*enforcement:\s*//;s/[\"'\'']//g' | tr -d ' ')
  fi
  [ -z "$PROV_MODE" ] && PROV_MODE="block"
  PROV_FLAGS="--severity ${PROV_MODE}"
  # During migration window, allow legacy phases without provenance
  [[ "${ARGUMENTS}" =~ --allow-legacy-provenance ]] && PROV_FLAGS="$PROV_FLAGS --allow-legacy"
  ${PYTHON_BIN:-python3} "$PROV_VAL" --phase "${PHASE_NUMBER}" $PROV_FLAGS
  PROV_RC=$?
  if [ "$PROV_RC" -ne 0 ] && [ "$PROV_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.evidence_provenance_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/evidence-provenance-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "evidence_provenance",
  "summary": "Evidence provenance gate failed — mutation steps claim success without structured provenance object (RFC v9 D10). Possible fabricated evidence.",
  "fix_hint": "1. Re-run scanner: /vg:review ${PHASE_NUMBER} --retry-failed; 2. For legacy phases: --allow-legacy-provenance; 3. Set review.provenance.enforcement: warn in vg.config.md to defer enforcement"
}
JSON
    blocking_gate_prompt_emit "evidence_provenance" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 anti-performative-review: ép scanner phải submit mutation goals,
# không được Cancel modal rồi mark passed. Phase 3.2 dogfood (2026-05-01) tìm
# 5 false-pass goals (G-31/G-34/G-35/G-44/G-52) modal opened nhưng chưa bao giờ
# submit. Validator này check goal_sequences.steps[] có submit click + 2xx
# network entry trước khi cho phép run-complete.
MUT_SUBMIT_VAL=".claude/scripts/validators/verify-mutation-actually-submitted.py"
if [ -f "$MUT_SUBMIT_VAL" ]; then
  MUT_FLAGS="--severity block"
  if [[ "${ARGUMENTS}" =~ --allow-cancel-only-mutations ]]; then
    MUT_FLAGS="--severity block --allow-cancel-only-mutations"
  fi
  ${PYTHON_BIN:-python3} "$MUT_SUBMIT_VAL" --phase "${PHASE_NUMBER}" $MUT_FLAGS
  MUT_RC=$?
  if [ "$MUT_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.mutation_submit_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/mutation-submit-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "mutation_submit",
  "summary": "Review mutation-actually-submitted gate failed — mutation goals marked passed without actual submit click + 2xx network",
  "fix_hint": "Re-run /vg:review ${PHASE_NUMBER} with scanner prompt requiring SUBMIT, or use --allow-cancel-only-mutations override (logs OVERRIDE-DEBT)"
}
JSON
    blocking_gate_prompt_emit "mutation_submit" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 Phase 6 enrichment: traceability + RCRURD enforcement.
# Closes "AI bịa goal/decision/business-rule" + "scanner stops too early".
# Migration: VG_TRACEABILITY_MODE=warn for pre-2026-05-01 phases (set in
# vg.config.md). New phases default to block.
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"

# v2.46 L4 — RCRURD step depth (per goal_class threshold)
RCRURD_VAL=".claude/scripts/validators/verify-rcrurd-depth.py"
if [ -f "$RCRURD_VAL" ]; then
  RCRURD_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-shallow-scans ]] && RCRURD_FLAGS="$RCRURD_FLAGS --allow-shallow-scans"
  ${PYTHON_BIN:-python3} "$RCRURD_VAL" --phase "${PHASE_NUMBER}" $RCRURD_FLAGS
  RCRURD_RC=$?
  if [ "$RCRURD_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_depth_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-depth-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_depth",
  "summary": "RCRURD depth gate failed — scanner stopped too early on mutation goals",
  "fix_hint": "See scanner-report-contract.md 'RCRURD Lifecycle Protocol'. Goal class drives min steps."
}
JSON
    blocking_gate_prompt_emit "rcrurd_depth" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — asserted_quote vs business rule similarity
ASSERTED_VAL=".claude/scripts/validators/verify-asserted-rule-match.py"
if [ -f "$ASSERTED_VAL" ]; then
  ASSERTED_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-asserted-drift ]] && ASSERTED_FLAGS="$ASSERTED_FLAGS --allow-asserted-drift"
  ${PYTHON_BIN:-python3} "$ASSERTED_VAL" --phase "${PHASE_NUMBER}" $ASSERTED_FLAGS
  ASSERTED_RC=$?
  if [ "$ASSERTED_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.asserted_drift_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/asserted-drift-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "asserted_drift",
  "summary": "Asserted-rule-match gate failed — scanner asserted_quote drifts from BR-NN text",
  "fix_hint": "Align scanner asserted_quote fields with the business rule text in BUSINESS-RULES.md or use --allow-asserted-drift override"
}
JSON
    blocking_gate_prompt_emit "asserted_drift" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — replay-evidence (structural + optional curl replay)
REPLAY_VAL=".claude/scripts/validators/verify-replay-evidence.py"
if [ -f "$REPLAY_VAL" ]; then
  REPLAY_FLAGS="--severity warn"  # default warn — auth fixture not always available
  [[ "${ARGUMENTS}" =~ --enable-replay ]] && REPLAY_FLAGS="--severity ${TRACE_MODE} --enable-replay"
  ${PYTHON_BIN:-python3} "$REPLAY_VAL" --phase "${PHASE_NUMBER}" $REPLAY_FLAGS
  REPLAY_RC=$?
  if [ "$REPLAY_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ] && [[ "${ARGUMENTS}" =~ --enable-replay ]]; then
    echo "⛔ Replay-evidence gate failed — scanner network claims can't be verified."
    exit 1
  fi
fi

# v2.46 L4 — cross-phase decision validity (D-XX from earlier phase still active)
CROSS_VAL=".claude/scripts/validators/verify-cross-phase-decision-validity.py"
if [ -f "$CROSS_VAL" ]; then
  CROSS_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-stale-decisions ]] && CROSS_FLAGS="$CROSS_FLAGS --allow-stale-decisions"
  ${PYTHON_BIN:-python3} "$CROSS_VAL" --phase "${PHASE_NUMBER}" $CROSS_FLAGS
  CROSS_RC=$?
  if [ "$CROSS_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Cross-phase decision validity failed — goal cites revoked/missing D-XX."
    exit 1
  fi
fi

# v2.46 L6 — adversarial scanner-business-alignment verifier
# Two-phase: emit prompts → orchestrator spawns Haiku verifier per prompt →
# re-run validator with --verifier-results to gate.
ALIGN_VAL=".claude/scripts/validators/verify-scanner-business-alignment.py"
if [ -f "$ALIGN_VAL" ]; then
  PROMPTS_FILE="${PHASE_DIR}/.tmp/business-alignment-prompts.jsonl"
  RESULTS_FILE="${PHASE_DIR}/.tmp/business-alignment-results.jsonl"
  mkdir -p "$(dirname "$PROMPTS_FILE")" 2>/dev/null
  ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" --prompts-out "$PROMPTS_FILE" 2>&1 | head -3
  PROMPT_COUNT=$(wc -l < "$PROMPTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

  if [ "$PROMPT_COUNT" -gt 0 ]; then
    echo ""
    echo "📋 Business alignment verifier needs ${PROMPT_COUNT} adversarial check(s)."
    echo "   Orchestrator should spawn isolated Haiku per prompt + write JSONL results to:"
    echo "     ${RESULTS_FILE}"
    echo "   Then re-run review with --verifier-results=${RESULTS_FILE}"
    echo ""
    # If results file exists from prior orchestrator pass, gate now
    if [ -f "$RESULTS_FILE" ]; then
      ALIGN_FLAGS="--severity ${TRACE_MODE} --verifier-results ${RESULTS_FILE}"
      [[ "${ARGUMENTS}" =~ --allow-business-drift ]] && ALIGN_FLAGS="$ALIGN_FLAGS --allow-business-drift"
      ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" $ALIGN_FLAGS
      ALIGN_RC=$?
      if [ "$ALIGN_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
        echo "⛔ Business alignment gate failed — adversarial verifier flagged drift."
        exit 1
      fi
    fi
  fi
fi

# RFC v9 D21 — DEFECT-LOG.md generation (tester pro).
# After GOAL-COVERAGE-MATRIX is final, parse the matrix and create one
# Defect entry per goal with status ∈ {BLOCKED, UNREACHABLE, FAILED, SUSPECTED}
# that does NOT already have an open defect in .tester-pro/defects.json.
# Severity inferred from priority + block_family heuristics.
TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ] && [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
  echo "━━━ D21 — Defect log generation ━━━"
  TESTER_PRO_CLI="$TESTER_PRO_CLI" ${PYTHON_BIN:-python3} - <<'PYDEFECT' 2>&1 | sed 's/^/  D21: /' || true
import json, os, re, subprocess, sys
phase_dir = os.environ['PHASE_DIR']
phase_no = os.environ['PHASE_NUMBER']
matrix = open(os.path.join(phase_dir, 'GOAL-COVERAGE-MATRIX.md'),
              encoding='utf-8').read()
cli = os.environ.get(
    'TESTER_PRO_CLI',
    os.path.join(os.environ['REPO_ROOT'], 'scripts', 'tester-pro-cli.py'),
)
# Parse rows `| G-XX | priority | surface | STATUS | evidence |`
row_re = re.compile(
    r"^\|\s*(G-[\w.-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
    r"\s*([A-Z_]+)\s*\|\s*(.+?)\s*\|", re.MULTILINE,
)
fail_states = {"BLOCKED", "UNREACHABLE", "FAILED", "SUSPECTED"}
# Load existing open defects to skip duplicates by (goal, title-prefix)
defects_path = os.path.join(phase_dir, '.tester-pro', 'defects.json')
existing = []
if os.path.exists(defects_path):
    try: existing = json.load(open(defects_path, encoding='utf-8'))
    except: pass
def is_open_for(gid, title_prefix):
    return any(
        d.get('related_goals') and gid in d['related_goals']
        and d.get('title','').startswith(title_prefix)
        and not d.get('closed_at')
        for d in existing
    )
opened = 0
for m in row_re.finditer(matrix):
    gid, prio, surf, status, ev = m.groups()
    if status not in fail_states:
        continue
    title_prefix = f"[{status}]"
    if is_open_for(gid, title_prefix):
        continue
    # Severity heuristic: critical priority → critical; backend mutation → major;
    # else minor.
    prio_l = prio.strip().lower()
    surf_l = surf.strip().lower()
    if prio_l == 'critical':
        sev = 'critical'
    elif any(s in surf_l for s in ('api', 'data', 'integration')):
        sev = 'major'
    else:
        sev = 'minor'
    title = f"[{status}] {gid} — {ev[:80]}"
    cmd = [
        sys.executable, cli, 'defect', 'new',
        '--phase', phase_no, '--title', title,
        '--severity', sev, '--found-in', 'review',
        '--goals', gid,
        '--notes', f"surface={surf} priority={prio} status={status}. Auto-opened from GOAL-COVERAGE-MATRIX.",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        opened += 1
print(f"opened {opened} new defect(s) from matrix")
PYDEFECT
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ review run-complete BLOCK — review orchestrator output + fix before /vg:test" >&2
  exit $RUN_RC
fi
```
</step>
