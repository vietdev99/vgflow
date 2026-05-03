<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Codex Round 2 Correction D inlined below the original task body. -->

## Task 18: Wire STEP 6.5 into build.md + frontmatter contracts

**Files:**
- Create: `commands/vg/_shared/build/pre-test-gate.md` (orchestrator-side ref)
- Modify: `commands/vg/build.md` (frontmatter contract + STEP 6.5 wiring)

- [ ] **Step 1: Create the step ref**

Create `commands/vg/_shared/build/pre-test-gate.md`:

```markdown
# build pre-test-gate (STEP 6.5 — between CrossAI and close)

Codifies what a coder typically does post-code, pre-PR-merge. Runs after
STEP 6 (CrossAI loop) and before STEP 7 (close). 5 sub-tiers:

  T1 static checks (typecheck, lint, debug-leftover grep)   — always; BLOCK
  T2 local unit + integration tests                          — always; BLOCK
  T3 (deferred — local smoke; covered by /vg:test STEP 3)
  T4/T6 deploy decision + invocation                        — conditional
  T7 post-deploy health + smoke specs                       — if deployed

<HARD-GATE>
T1 + T2 are MANDATORY. Failures BLOCK build (no override without
--skip-pre-test which logs override-debt). T4/T6 deploy is policy-driven
from ENV-BASELINE.md but user can override via AskUserQuestion.

NO inline implementation: this step delegates each tier to the validators
created in Tasks 15-17. The orchestrator only sequences.
</HARD-GATE>

## STEP 6.5 — orchestration

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 12_5_pre_test_gate || true

# Skip-flag escape (paired with --override-reason)
if [[ "$ARGUMENTS" =~ --skip-pre-test ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-pre-test requires --override-reason=<text>"
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.pre_test_skipped" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_5_pre_test_gate || true
  exit 0
fi

mkdir -p "${PHASE_DIR}/.pre-test"

# T1 + T2 — always run
SOURCE_ROOT=$(vg_config_get paths.source_root ".")
T12_REPORT="${PHASE_DIR}/.pre-test/tier-1-2.json"
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-pre-test-tier-1-2.py \
  --source-root "$SOURCE_ROOT" \
  --phase "${PHASE_NUMBER}" \
  --report-out "$T12_REPORT" \
  --repo-root "${REPO_ROOT:-.}" || {
  echo "⛔ STEP 6.5 T1+T2 failed — see ${T12_REPORT}"
  echo "   Build BLOCKED before deploy decision."
  exit 1
}

# Deploy decision — read ENV-BASELINE policy + ask user
ENV_BASELINE_FILE="${PLANNING_DIR:-.vg}/ENV-BASELINE.md"
DEPLOY_PROPOSAL=$("${PYTHON_BIN:-python3}" -c "
import sys, json
sys.path.insert(0, '.claude/scripts/lib')
from deploy_decision import propose_target
from pathlib import Path
proposal = propose_target(Path('${ENV_BASELINE_FILE}'), phase_changes={})
print(json.dumps(proposal))
")
RECOMMENDED_ENV=$(echo "$DEPLOY_PROPOSAL" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(json.load(sys.stdin)['recommended_env'])")

echo "▸ STEP 6.5 deploy proposal: ${RECOMMENDED_ENV}"
echo "  Reason: $(echo "$DEPLOY_PROPOSAL" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(json.load(sys.stdin)['reason'])")"

# AskUserQuestion: confirm deploy target
# Question: "Deploy phase ${PHASE_NUMBER} for pre-test?"
# Options:
#   [recommended] Use recommended (${RECOMMENDED_ENV})
#   [s] Skip deploy (T1+T2 only)
#   [l] Local only (skip deploy)
#   [sandbox] Force sandbox
#   [staging] Force staging
# Persist choice to ${PHASE_DIR}/.pre-test/deploy-decision.json

DEPLOY_REPORT="${PHASE_DIR}/.pre-test/deploy.json"
DEPLOY_DECISION=""  # filled from AskUserQuestion answer

if [ "$DEPLOY_DECISION" = "skip" ] || [ "$DEPLOY_DECISION" = "local" ]; then
  echo "▸ STEP 6.5 deploy: skipped (user choice)"
  cat > "$DEPLOY_REPORT" <<JSON
{"decision":"$DEPLOY_DECISION","deployed":false,"deploy_url":null,"reason":"user opted out"}
JSON
else
  # Invoke /vg:deploy with target env
  echo "▸ STEP 6.5 deploy: invoking /vg:deploy --env ${DEPLOY_DECISION}"
  bash scripts/vg-narrate-spawn.sh general-purpose spawning "deploy ${PHASE_NUMBER} → ${DEPLOY_DECISION}"
  # Agent(subagent_type="general-purpose", prompt="Run /vg:deploy --env=${DEPLOY_DECISION} --phase=${PHASE_NUMBER}")
  # Read DEPLOY-STATE.json after; extract URL.
  DEPLOY_URL=$("${PYTHON_BIN:-python3}" -c "
import json
from pathlib import Path
p = Path('${PLANNING_DIR:-.vg}/DEPLOY-STATE.json')
if p.exists():
    d = json.loads(p.read_text())
    deployed = d.get('deployed', {}).get('${DEPLOY_DECISION}', {})
    print(deployed.get('url', ''))
" 2>/dev/null)

  # Post-deploy: health check + smoke
  "${PYTHON_BIN:-python3}" -c "
import json, sys
sys.path.insert(0, '.claude/scripts/lib')
from post_deploy_smoke import health_check, run_smoke_specs
url = '${DEPLOY_URL}'
hc = health_check(url) if url else {'status': 'BLOCK', 'reason': 'no deploy url'}
sr = run_smoke_specs(url) if url and hc['status'] == 'PASS' else {'status': 'SKIPPED', 'reason': 'health check failed'}
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
    exit 1
  }
fi

# Render PRE-TEST-REPORT.md
"${PYTHON_BIN:-python3}" .claude/scripts/validators/write-pre-test-report.py \
  --phase "${PHASE_NUMBER}" \
  --t12-report "$T12_REPORT" \
  --deploy-report "$DEPLOY_REPORT" \
  --output "${PHASE_DIR}/PRE-TEST-REPORT.md"

# Telemetry
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "build.pre_test_complete" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"deploy\":\"${DEPLOY_DECISION}\"}" \
  2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 12_5_pre_test_gate || true
```
```

- [ ] **Step 2: Wire into build.md slim entry**

Edit `commands/vg/build.md`. Find the line `### STEP 7 — close` and INSERT before it:

```markdown
### STEP 6.5 — Pre-Test Gate (HEAVY, conditional)

Read `_shared/build/pre-test-gate.md`. Runs T1 (static) + T2 (local tests) +
optional T4/T6 (deploy decision + post-deploy smoke). BLOCKs build on T1/T2
failure. Deploy is policy-driven from ENV-BASELINE.md, user can override.

Output: `${PHASE_DIR}/PRE-TEST-REPORT.md`. Skippable via `--skip-pre-test`
+ `--override-reason=<text>` (logs override-debt).
```

Add to `must_touch_markers:` in build.md frontmatter:

```yaml
    - name: "12_5_pre_test_gate"
      severity: "warn"
      required_unless_flag: "--skip-pre-test"
```

Add to `must_emit_telemetry:`:

```yaml
    - event_type: "build.pre_test_complete"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
      required_unless_flag: "--skip-pre-test"
    - event_type: "build.pre_test_skipped"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

Add to `forbidden_without_override:`:

```yaml
    - "--skip-pre-test"
```

Update `argument-hint:` to include `[--skip-pre-test]`.

- [ ] **Step 3: Sync to .claude mirror**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
DEV_ROOT=. bash sync.sh --no-global
python3 scripts/vg_sync_codex.py --apply 2>&1 | tail -3
```
Expected: sync applies; codex sync 53 applied.

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/build/pre-test-gate.md commands/vg/build.md .claude/ codex-skills/
git commit -m "feat(pre-test): wire STEP 6.5 pre-test gate into build pipeline"
```



---

## Codex Round 2 Correction D (mandatory — apply on top of the original task body above)

### Correction D — Task 18: COMPREHENSIVE REWRITE

**Problems (Codex #1, #2, #3, #4, #6, #8, #9):** Task 18 had multiple
bugs in deploy invocation, paths, severity, and UX. Replace
`commands/vg/_shared/build/pre-test-gate.md` body with the corrected
version below.

**Patch — Full rewrite of `commands/vg/_shared/build/pre-test-gate.md`:**

````markdown
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
# Per Codex feedback: "if STEP 5 truthcheck evidence exists, reference it".
# Otherwise skip with clear note in PRE-TEST-REPORT.md.
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
````

**Patch — `commands/vg/build.md` frontmatter (replaces Task 18 Step 2):**

```yaml
must_write:
  # ... existing entries unchanged ...
  - path: "${PHASE_DIR}/PRE-TEST-REPORT.md"
    required_unless_flag: "--skip-pre-test"
    content_min_bytes: 80

must_touch_markers:
  # ... existing entries unchanged ...
  - name: "12_5_pre_test_gate"
    required_unless_flag: "--skip-pre-test"   # (Codex fix #9: was severity:warn)

must_emit_telemetry:
  # ... existing entries unchanged ...
  - event_type: "build.pre_test_complete"
    phase: "${PHASE_NUMBER}"
    required_unless_flag: "--skip-pre-test"
  - event_type: "build.pre_test_skipped"
    phase: "${PHASE_NUMBER}"
    severity: "warn"

forbidden_without_override:
  # ... existing entries unchanged ...
  - "--skip-pre-test"
```

argument-hint: append `[--skip-pre-test] [--interactive]`.

