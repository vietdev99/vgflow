# test deploy (STEP 2)

2 steps: 5a_deploy (web/cli/library profiles), 5a_mobile_deploy (mobile-* profiles).
The two steps are mutually exclusive — only one runs based on `${PROFILE}`.

<!-- no vg-load needed; orchestration only — does not read PLAN/API-CONTRACTS/TEST-GOALS.
     Task 15 (vg-load consumption test) can verify this ref cleanly. -->

<HARD-GATE>
You MUST execute exactly one of the two steps based on profile. Each step finishes
with a marker touch + `vg-orchestrator mark-step test <step>`. Skipping the active
step = Stop hook block.

Profile gating (mutually exclusive):
- `mobile-*`                                             → run 5a_mobile_deploy only
- web-fullstack | web-frontend-only | web-backend-only |
  cli-tool | library                                     → run 5a_deploy only

If `--skip-deploy` flag is present, skip the active step but still touch its marker.

The PreToolUse Bash hook gates `vg-orchestrator step-active` calls. Each step's bash
must be wrapped with step-active before its real work and mark-step after.
</HARD-GATE>

---

## STEP 2.1 — deploy web/cli/library (5a_deploy) [profile: web-fullstack,web-frontend-only,web-backend-only,cli-tool,library]

Deploy to target environment: record SHAs, pre-deploy command, build + restart,
health check, preflight all services, optional typecheck, optional DB re-seed.

Read `.claude/commands/vg/_shared/env-commands.md` — deploy(env) + preflight(env).

**If `--skip-deploy`, skip the bash body below but still touch the step marker.**

```bash
vg-orchestrator step-active 5a_deploy

# Batch 20: source deploy contract — guarantees AI uses project's locked deploy method
LOAD_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/deploy-contract-load.py"
[ -f "$LOAD_SCRIPT" ] || LOAD_SCRIPT="${REPO_ROOT:-.}/scripts/deploy-contract-load.py"
if [ ! -f "$LOAD_SCRIPT" ]; then
  echo "deploy-contract-load.py missing — required by Batch 20 hard gate" >&2
  exit 1
fi
eval "$(${PYTHON_BIN:-python3} "$LOAD_SCRIPT" --vg-dir "${PROJECT_VG_DIR:-.vg}" --env "${ENV:-sandbox}" 2>&1)" || {
  echo "deploy-contract-load failed — DEPLOY-CONTRACT.json missing or malformed" >&2
  echo "   Bootstrap: /vg:deploy --init  OR  python scripts/deploy-contract-init.py --method <X> ..." >&2
  exit 1
}

# 1. Record SHAs (local + target)
LOCAL_SHA=$(git rev-parse --short HEAD)
echo "Local SHA: $LOCAL_SHA"

# 2. Pre-deploy command (if configured via DEPLOY_PRE from contract)
[ -n "$DEPLOY_PRE" ] && eval "$DEPLOY_PRE"

# 3. Build + restart on target — uses contracted commands from .vg/DEPLOY-CONTRACT.json
run_on_target "${DEPLOY_BUILD} && ${DEPLOY_RESTART}" || {
  echo "Build/restart failed via ${DEPLOY_METHOD}" >&2
  [ -n "$DEPLOY_ROLLBACK" ] && run_on_target "$DEPLOY_ROLLBACK"
  exit 1
}

# 4. Wait for startup
sleep 5

# 5. Health check via contracted command → if fail → rollback
run_on_target "$DEPLOY_HEALTH" || {
  echo "Health failed via ${DEPLOY_METHOD}" >&2
  [ -n "$DEPLOY_ROLLBACK" ] && run_on_target "$DEPLOY_ROLLBACK"
  exit 1
}
echo "Deploy (${DEPLOY_METHOD}) PASS on env=${ENV:-sandbox}"

# 6. Preflight all services → required service FAIL → BLOCK
# 7. Typecheck (if configured): run typecheck(env) from env-commands.md
# 8. Re-seed DB (if configured): run seed_smoke(env) from env-commands.md
#    Purpose: test runs generated E2E flows + mutation probes against fresh data.
#    Review may have left dirty DB state (created/deleted records). Re-seed ensures
#    deterministic test data. Skip silently if seed_command empty.

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/step-status-ledger.py" \
  --phase-dir "${PHASE_DIR}" --step "5a_deploy" --status "${DEPLOY_STATUS:-PASS}" \
  --reason "${DEPLOY_REASON:-}" || true
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5a_deploy" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5a_deploy.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5a_deploy 2>/dev/null || true
```

```bash
# Batch 26: FE route wiring probe — catch un-wired routes post-deploy
ROUTE_PROBE="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/probe-fe-routes.py"
[ -f "$ROUTE_PROBE" ] || ROUTE_PROBE="${REPO_ROOT:-.}/scripts/probe-fe-routes.py"
if [ -f "$ROUTE_PROBE" ] && [ -d "${PHASE_DIR}/API-CONTRACTS" ]; then
  FE_BASE_URL="${FE_BASE_URL:-http://localhost:5173}"
  "${PYTHON_BIN:-python3}" "$ROUTE_PROBE" \
    --phase-dir "${PHASE_DIR}" \
    --base-url "$FE_BASE_URL" \
    --json > "${PHASE_DIR}/.route-probe.json" 2>&1 || {
    echo "WARN Batch 26: FE route probe found un-wired route(s) — see ${PHASE_DIR}/.route-probe.json" >&2
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
      "test.fe_route_unwired" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
  }
fi
```

Display:
```
5a Deploy:
  Local SHA: {sha}
  Target SHA: {sha} → {new_sha}
  Build: {OK|FAIL}
  Health: {OK|FAIL}
  Services: {N}/{total} OK
  Seed: {OK|skipped (no seed_command)}
```

---

## STEP 2.2 — deploy mobile binary (5a_mobile_deploy) [profile: mobile-*]

Mobile deploy: produce a signed binary (IPA / APK / AAB) and upload to a
distribution channel (Firebase App Distribution, TestFlight, Play Internal Track).
Helper functions live in `.claude/commands/vg/_shared/mobile-deploy.md`.

**If `--skip-deploy`, skip the bash body below but still touch the step marker.**

```bash
vg-orchestrator step-active 5a_mobile_deploy

# Batch 31 gap #14: source helper bash. Previously functions like
# mobile_deploy_effective_provider were referenced but never defined in
# shell scope — helper bash blocks live inside markdown fences and weren't
# extracted/eval'd. Causes "command not found" at runtime.
HELPER="${REPO_ROOT}/.claude/commands/vg/_shared/mobile-deploy.md"
[ -f "$HELPER" ] || { echo "⛔ missing mobile-deploy helper at $HELPER"; exit 1; }

# Extract bash blocks from markdown helper and source them. awk pulls every
# ```bash ... ``` fence into a single eval-able script.
HELPER_BASH="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/mobile-deploy-helpers.sh"
mkdir -p "$(dirname "$HELPER_BASH")" 2>/dev/null
awk '/^```bash$/{f=1; next} /^```$/{f=0; next} f' "$HELPER" > "$HELPER_BASH"
if [ ! -s "$HELPER_BASH" ]; then
  echo "⛔ Batch 31 gap #14: extract_bash from $HELPER yielded empty script" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$HELPER_BASH"
MOBILE_HELPERS_SOURCED=1
echo "✓ Batch 31: sourced $(grep -c '^[a-z_]*_deploy_.*()' "$HELPER_BASH" 2>/dev/null || echo "?") mobile_deploy_* functions from helper"

# 1. SHAs (identical to web)
LOCAL_SHA=$(git rev-parse HEAD)
echo "Local SHA: $LOCAL_SHA"

# 2. Detect effective provider (with iOS cloud fallback if host ≠ darwin)
PROVIDER=$(mobile_deploy_effective_provider)
echo "Mobile deploy provider: $PROVIDER"

# 3. Verify provider CLI installed — HARD FAIL if missing (deploy cannot skip)
mobile_deploy_check_provider "$PROVIDER" || exit 1

# 4. Run full pipeline (all stages from config.mobile.deploy.stages[])
mobile_deploy_pipeline
DEPLOY_RC=$?

# 5. Report
if [ $DEPLOY_RC -ne 0 ]; then
  echo "⛔ Mobile deploy failed."
  # Rollback offered for supported providers (eas republish / fastlane lane)
  echo "Rollback option: mobile_deploy_rollback $PROVIDER <prev_sha>"
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5a_mobile_deploy" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5a_mobile_deploy.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5a_mobile_deploy 2>/dev/null || true
```

Display:
```
5a Mobile Deploy:
  Local SHA: {sha}
  Provider: {effective}  (detected={detected}, fallback_applied={yes|no})
  Stages:
    - internal_qa [{target}] → {✓|✗}  ({health_check}: {pass|fail|noop})
    - beta [{target}]        → {✓|✗|skipped}
  Artifacts:
    - ios:     {path/to/*.ipa}  ({N} MB)
    - android: {path/to/*.apk}  ({N} MB)
```

**Notes for orchestrator:**
- If `mobile.target_platforms` excludes `ios` and host ≠ darwin, there is
  nothing to skip — provider still runs for android targets only.
- `mobile.deploy.cloud_fallback_for_ios=true` automatically maps iOS-only
  stages to the cloud provider; iOS + android target on Linux → android via
  fastlane locally, iOS via EAS cloud.
- After pipeline exit 0, verify-bundle-size (Gate 10 at build time) already
  ran; test doesn't re-check size. Instead test step 5f security audit
  scans the signed binary for hardcoded secrets.

---

After STEP 2 marker touched, return to entry SKILL.md → STEP 3 (verify + codegen).
