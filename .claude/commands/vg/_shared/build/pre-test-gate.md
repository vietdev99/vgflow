# build pre-test-gate (STEP 6.5 — between CrossAI and close)

Codifies what a coder typically does post-code, pre-PR-merge. Runs after
STEP 6 (CrossAI loop) and before STEP 7 (close). Tiers (Codex round 2
revision):

  T1 static checks (typecheck, lint, debug-leftover grep, **secret scan**) — always; BLOCK
  T2 local unit + integration tests                                          — always; BLOCK
  T3 local smoke (conditional reuse of STEP 5 truthcheck evidence)           — informational
  T4/T6 deploy decision + invocation                                         — config-driven
  T7 post-deploy health + smoke specs                                        — if deployed

<HARD-GATE>
T1 + T2 are MANDATORY. Failures BLOCK build. The frontmatter on
`commands/vg/build.md` declares `12_5_pre_test_gate` with
`required_unless_flag: "--skip-pre-test"` — when the flag is set, an
`override.used` event must be emitted (see `scripts/vg-orchestrator
override-use`) for the contract validator to accept the absence.

T4/T6 deploy is policy-driven from these sources, in order:
  1. `vg.config.md` `pre_test.default_env` (project-wide default)
  2. ENV-BASELINE.md profile policy (via `deploy_decision.propose_target`)
  3. `/vg:scope` STEP 3 env-preference output (per-phase)

The orchestrator picks the highest-priority non-empty value. Build is
non-interactive by default — AskUserQuestion is invoked ONLY when
`--interactive` flag is present (matches the no-AskUserQuestion-mid-build
constraint from STEP 5.5).

Deploy/smoke failures route to the same classifier+disposition pipeline
as STEP 5.5 (in-scope-fix-loop): IN_SCOPE → STEP 5.5 retry; FORWARD_DEP
→ append to .vg/FORWARD-DEPS.md; NEEDS_TRIAGE → BLOCK with repair packet.
NO dead-end BLOCK with prose-only evidence.
</HARD-GATE>

## STEP 6.5 — orchestration

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 12_5_pre_test_gate || true

# ─── Skip-flag escape ──────────────────────────────────────────────────
if [[ "$ARGUMENTS" =~ --skip-pre-test ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-pre-test requires --override-reason=<text ≥50 chars + ticket ref>"
    exit 1
  fi
  # Emit override.used so the contract validator's forbidden_without_override
  # check is satisfied (Codex round 2 fix #8: do NOT exit 0 here — that would
  # bypass STEP 7 close).
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override-use \
    --flag "--skip-pre-test" \
    --reason "${OVERRIDE_REASON}" 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.pre_test_skipped" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_5_pre_test_gate || true
  echo "▸ STEP 6.5 skipped (override logged); continuing to STEP 7 close"
  return 0   # falls through to STEP 7, NOT exit 0 (which would terminate /vg:build)
fi

mkdir -p "${PHASE_DIR}/.pre-test"

# ─── T1 + T2 — always run ──────────────────────────────────────────────
SOURCE_ROOT=$(vg_config_get paths.source_root ".")
ENV_BASELINE_FILE="${PLANNING_DIR:-.vg}/ENV-BASELINE.md"
T12_REPORT="${PHASE_DIR}/.pre-test/tier-1-2.json"
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-pre-test-tier-1-2.py \
  --source-root "$SOURCE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --env-baseline "$ENV_BASELINE_FILE" \
  --report-out "$T12_REPORT" \
  --repo-root "${REPO_ROOT:-.}" || {
  echo "⛔ STEP 6.5 T1+T2 failed — see ${T12_REPORT}"

  # Codex round 2: route failure through classifier + disposition (no dead-end BLOCK)
  "${PYTHON_BIN:-python3}" .claude/scripts/classify-build-warning.py \
    --phase-dir "${PHASE_DIR}" --warning "$T12_REPORT" \
    > "${PHASE_DIR}/.pre-test/t12-classification.json" 2>/dev/null || true

  echo "   See classification: ${PHASE_DIR}/.pre-test/t12-classification.json"
  exit 1
}

# ─── T3 — conditional local smoke (reuse STEP 5 truthcheck evidence) ──
T3_NOTE="(reused STEP 5 truthcheck evidence)"
if [ -f "${PHASE_DIR}/SUMMARY.md" ] && grep -q "Truthcheck" "${PHASE_DIR}/SUMMARY.md" 2>/dev/null; then
  T3_NOTE="STEP 5 truthcheck PASS — local smoke reuse"
fi

# ─── Deploy decision — config-driven, no AskUserQuestion by default ──
DEPLOY_PROPOSAL=$("${PYTHON_BIN:-python3}" -c "
import sys, json
sys.path.insert(0, '.claude/scripts/lib')
from deploy_decision import propose_target, detect_phase_changes
from pathlib import Path
phase_dir = Path('${PHASE_DIR}')
changes = detect_phase_changes(phase_dir, Path('${REPO_ROOT:-.}'))
proposal = propose_target(Path('${ENV_BASELINE_FILE}'), phase_changes=changes)
proposal['phase_changes'] = changes
print(json.dumps(proposal))
")

# Source priority: vg.config.md → ENV-BASELINE proposal → /vg:scope env-preference
DEFAULT_ENV=$(vg_config_get pre_test.default_env "")
RECOMMENDED_ENV=$(echo "$DEPLOY_PROPOSAL" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(json.load(sys.stdin)['recommended_env'])")
SCOPE_ENV=""
if [ -f "${PHASE_DIR}/SCOPE.md" ]; then
  SCOPE_ENV=$(grep -E "^pre_test_env:" "${PHASE_DIR}/SCOPE.md" 2>/dev/null | awk '{print $2}' | tr -d '"' || true)
fi

DEPLOY_DECISION="${DEFAULT_ENV:-${SCOPE_ENV:-${RECOMMENDED_ENV}}}"

# Interactive override
if [[ "$ARGUMENTS" =~ --interactive ]]; then
  echo "▸ STEP 6.5 interactive deploy decision (proposal=${RECOMMENDED_ENV})"
  # AskUserQuestion: confirm/edit DEPLOY_DECISION
  # (One-time per build — NOT mid-loop; satisfies non-interactive build constraint.)
fi

echo "▸ STEP 6.5 deploy: ${DEPLOY_DECISION} (source: $([ -n "$DEFAULT_ENV" ] && echo config || ([ -n "$SCOPE_ENV" ] && echo scope || echo proposal)))"

DEPLOY_REPORT="${PHASE_DIR}/.pre-test/deploy.json"

if [ "$DEPLOY_DECISION" = "skip" ] || [ "$DEPLOY_DECISION" = "local" ]; then
  cat > "$DEPLOY_REPORT" <<JSON
{"decision":"$DEPLOY_DECISION","deployed":false,"deploy_url":null,"reason":"policy-driven skip"}
JSON
else
  # ─── Codex round 2 fix #1, #2, #3, #4: invoke /vg:deploy via Skill tool, ──
  # NOT subagent. CLI shape: <phase> --envs=<env> --non-interactive --pre-test.
  # The --pre-test mode is added by Task 20 (NEW) to allow build-incomplete
  # invocation. DEPLOY-STATE.json lives at ${PHASE_DIR}/, not ${PLANNING_DIR}/.

  echo "▸ STEP 6.5 deploy: invoking /vg:deploy ${PHASE_NUMBER} --envs=${DEPLOY_DECISION} --pre-test"

  # The orchestrator (controller) invokes the Skill tool here. The
  # markdown comment block below documents the exact invocation; the
  # AI controller MUST replace it with a Skill tool call:
  #
  #   Skill(skill="vg:deploy",
  #         args="${PHASE_NUMBER} --envs=${DEPLOY_DECISION} --non-interactive --pre-test --override-reason=\"pre-test gate from /vg:build STEP 6.5\"")
  #
  # NOT Agent(subagent_type="general-purpose", prompt="Run /vg:deploy ...") — that pattern
  # was wrong (skills are controller-side, see superpowers:using-superpowers reference).

  # After /vg:deploy returns, read the per-phase DEPLOY-STATE.json
  DEPLOY_URL=$("${PYTHON_BIN:-python3}" -c "
import json
from pathlib import Path
p = Path('${PHASE_DIR}/DEPLOY-STATE.json')   # PHASE_DIR not PLANNING_DIR (Codex fix #3)
if p.exists():
    d = json.loads(p.read_text())
    deployed = d.get('deployed', {}).get('${DEPLOY_DECISION}', {})
    print(deployed.get('url', ''))
" 2>/dev/null)

  if [ -z "$DEPLOY_URL" ]; then
    echo "⛔ STEP 6.5 deploy: no URL in ${PHASE_DIR}/DEPLOY-STATE.json — /vg:deploy may have failed"
    cat > "$DEPLOY_REPORT" <<JSON
{"decision":"$DEPLOY_DECISION","deployed":false,"deploy_url":null,"reason":"deploy returned no URL"}
JSON
    # Route through classifier
    "${PYTHON_BIN:-python3}" .claude/scripts/classify-build-warning.py \
      --phase-dir "${PHASE_DIR}" --warning "$DEPLOY_REPORT" \
      > "${PHASE_DIR}/.pre-test/deploy-classification.json" 2>/dev/null || true
    exit 1
  fi

  # ─── Post-deploy: health check + smoke (with auth + storageState support) ─
  AUTH_HEADER=$(vg_config_get pre_test.health_auth_header "")
  STORAGE_STATE=$(vg_config_get pre_test.playwright_storage_state "")
  ROLE=$(vg_config_get pre_test.smoke_role "")

  "${PYTHON_BIN:-python3}" -c "
import json, sys
sys.path.insert(0, '.claude/scripts/lib')
from post_deploy_smoke import health_check, run_smoke_specs

url = '${DEPLOY_URL}'
headers = {'Authorization': '${AUTH_HEADER}'} if '${AUTH_HEADER}' else None

hc = health_check(url, headers=headers, total_deadline_s=30)
sr = (run_smoke_specs(url,
                      storage_state_path='${STORAGE_STATE}' or None,
                      role='${ROLE}' or None)
      if hc['status'] == 'PASS' else
      {'status': 'SKIPPED', 'reason': 'health check failed'})

out = {
    'decision': '${DEPLOY_DECISION}',
    'deployed': True,
    'deploy_url': url,
    'smoke_health_check': hc,
    'smoke_test_run': sr,
}
with open('${DEPLOY_REPORT}', 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2)
sys.exit(0 if hc['status'] == 'PASS' and sr['status'] in ('PASS', 'SKIPPED') else 1)
" || {
    echo "⛔ STEP 6.5 post-deploy smoke failed — see ${DEPLOY_REPORT}"
    # Route failure through classifier + disposition
    "${PYTHON_BIN:-python3}" .claude/scripts/classify-build-warning.py \
      --phase-dir "${PHASE_DIR}" --warning "$DEPLOY_REPORT" \
      > "${PHASE_DIR}/.pre-test/smoke-classification.json" 2>/dev/null || true
    exit 1
  }
fi

# ─── Render PRE-TEST-REPORT.md ─────────────────────────────────────────
"${PYTHON_BIN:-python3}" .claude/scripts/validators/write-pre-test-report.py \
  --phase "${PHASE_NUMBER}" \
  --t12-report "$T12_REPORT" \
  --deploy-report "$DEPLOY_REPORT" \
  --t3-note "$T3_NOTE" \
  --output "${PHASE_DIR}/PRE-TEST-REPORT.md"

# ─── Telemetry ─────────────────────────────────────────────────────────
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "build.pre_test_complete" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"deploy\":\"${DEPLOY_DECISION}\"}" \
  2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_5_pre_test_gate || true
```
