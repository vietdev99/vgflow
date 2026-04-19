---
name: vg:test
description: Clean goal verification + independent smoke + codegen regression + security audit
argument-hint: "<phase> [--skip-deploy] [--regression-only] [--smoke-only] [--fix-only] [--skip-flow]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
  - BashOutput
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate in this command.**

Why: those tools persist items in Claude Code's status tail across sessions. If a long step interrupts before items get marked completed, they hang in UI for runs after.

**Use these instead:**
1. **Markdown headers in YOUR text output** between tool calls — e.g., `## ━━━ Phase 5b: Goal verification ━━━`. Appears in message stream, does NOT persist after session ends.
2. **`run_in_background: true` for any Bash > 30s**, then poll with `BashOutput` so user sees stdout live.
3. **For Task subagents > 2 min**: write 1-line status BEFORE spawning + 1-line summary AFTER. User sees both in the message stream.
4. Bash echo narration is audit log only — not user-visible during long runs.
5. **Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `PASSED (đạt)`, `FAILED (thất bại)`, `regression (hồi quy)`, `coverage (độ phủ)`. Không áp dụng: file path, code identifier (`G-XX`, `git`), config tag values, lần lặp lại trong cùng message.
</NARRATION_POLICY>

<rules>
1. **RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md required** — review must have completed. Missing = BLOCK.
2. **TEST-GOALS.md required** — goals must exist (from blueprint or review).
3. **No discovery in test** — review already explored. Test VERIFIES known paths.
4. **MINOR-only fix (auto-gated v1.14.4+)** — AI MUST emit `fix-plans.json` before attempting fix. Pre-flight script `severity-classify.py` auto-classifies dựa trên: file count ≥3 → MODERATE, touches `apps/api/**/routes|schemas|contracts` → MODERATE, touches `packages/**|apps/web/**/lib|apps/web/**/hooks` → MODERATE, `change_type=new_feature|contract` → MAJOR. Auto-escalate MODERATE/MAJOR → REVIEW-FEEDBACK.md, kick back to review. AI không được tự classify MINOR bypass gate.
5. **Independent smoke first** — spot-check RUNTIME-MAP accuracy before trusting it.
6. **Navigate via UI clicks** — browser_navigate BANNED except for initial login/domain switch.
7. **Console monitoring** — check browser_console_messages after EVERY action.
8. **Goal-based codegen** — assertions from TEST-GOALS success criteria, paths from RUNTIME-MAP observation.
9. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
10. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    Browser steps (5c-smoke, 5c-flow, 5d codegen) carry `profile="web-fullstack,web-frontend-only"`.
    Contract-curl (5b) carries `profile="web-fullstack,web-backend-only"`.
    `create_task_tracker` preflight filters to applicable steps only; missing markers at step complete → BLOCK.
</rules>

<objective>
Step 5 of V5.1 pipeline. Clean goal verification — review already discovered + fixed. Test only verifies goals and generates regression tests.

Pipeline: specs → scope → blueprint → build → review → **test** → accept

Sub-steps:
- 5a: DEPLOY — push + build + restart on target
- 5b: RUNTIME CONTRACT VERIFY — curl + jq per endpoint
- 5c-smoke: INDEPENDENT SPOT CHECK — cross-check RUNTIME-MAP accuracy
- 5c-goal: GOAL VERIFICATION — verify each goal via known paths (topological sort)
- 5c-fix: MINOR FIX ONLY — minor fix in test, moderate/major escalate to review
- 5d: CODEGEN — generate .spec.ts from verified goals + RUNTIME-MAP paths
- 5e: REGRESSION RUN — npx playwright test
- 5f: SECURITY AUDIT — grep + optional deep scan
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `.claude/commands/vg/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

**MCP Server Selection:** Auto-claim a free Playwright server using the lock manager (see config-loader "How to Acquire Playwright MCP Server").
Run the claim command ONCE at start of 5c (browser steps), store `$MCP_PREFIX`. Release after 5c completes or on error.
Every browser tool call = `{MCP_PREFIX}browser_navigate`, `{MCP_PREFIX}browser_snapshot`, `{MCP_PREFIX}browser_click`, etc.
**NEVER call bare `browser_navigate`** — always use the full prefixed tool name.

<step name="00_gate_integrity_precheck">
**T8 gate (cổng) integrity precheck — blocks test if /vg:update left unresolved gate conflicts (xung đột).**

If `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` exists, a prior `/vg:update` detected that the 3-way merge (gộp) altered one or more HARD gate blocks. BLOCK (chặn) until resolved via `/vg:reapply-patches --verify-gates`.

```bash
if [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved — run /vg:reapply-patches --verify-gates first."
  exit 1
fi
```
</step>

<step name="00_session_lifecycle">
**Session lifecycle (tightened 2026-04-17) — clean tail UI across runs.**

Follow `.claude/commands/vg/_shared/session-lifecycle.md`.

```bash
PHASE_NUMBER=$(echo "$ARGUMENTS" | awk '{print $1}')
# v1.9.2.2 — handle zero-padding via shared resolver
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-resolver.sh" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR_CANDIDATE=$(resolve_phase_dir "$PHASE_NUMBER" 2>/dev/null || echo "")
else
  PHASE_DIR_CANDIDATE=$(ls -d ${PLANNING_DIR}/phases/${PHASE_NUMBER}* 2>/dev/null | head -1)
fi

session_start "test" "${PHASE_NUMBER:-unknown}"
[ -n "$PHASE_DIR_CANDIDATE" ] && stale_state_sweep "test" "$PHASE_DIR_CANDIDATE"
[ "${CONFIG_SESSION_PORT_SWEEP_ON_START:-true}" = "true" ] && session_port_sweep "pre-flight"
session_mark_step "0-parse-args"
```
</step>

<step name="0_parse_and_validate">
Parse `$ARGUMENTS`: phase_number, flags (--skip-deploy, --regression-only, --smoke-only, --fix-only).

Validate:
- `${PHASE_DIR}/RUNTIME-MAP.json` exists
- `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md` exists
- `${PHASE_DIR}/TEST-GOALS.md` exists
- `${PHASE_DIR}/API-CONTRACTS.md` exists

Missing → BLOCK with guidance: "Run `/vg:review {phase}` first."

**⛔ NOT_SCANNED rejection gate (tightened 2026-04-17 — GLOBAL rule):**

Test replay `goal_sequences[]` mà review ghi trong RUNTIME-MAP. Goals có status `NOT_SCANNED`/`FAILED` (intermediate) KHÔNG có sequence → test không có input replay → KHÔNG được defer sang test.

```bash
# Parse GOAL-COVERAGE-MATRIX.md → check for intermediate statuses
INTERMEDIATE=$(${PYTHON_BIN} - <<PY 2>/dev/null
import re, sys
from pathlib import Path
gcm = Path("${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md").read_text(encoding='utf-8')
# Match goal status rows: | G-XX | priority | STATUS | ... |
pat = re.compile(r'\|\s*(G-\d+)\s*\|[^|]+\|\s*(NOT_SCANNED|FAILED)\s*\|', re.I)
hits = pat.findall(gcm)
for gid, status in hits:
    print(f"{gid}|{status}")
PY
)

if [ -n "$INTERMEDIATE" ]; then
  COUNT=$(echo "$INTERMEDIATE" | wc -l | tr -d ' ')
  echo "⛔ ${COUNT} goals có status intermediate (NOT_SCANNED/FAILED) trong GOAL-COVERAGE-MATRIX:"
  echo "$INTERMEDIATE" | sed 's/^/   /'
  echo ""
  echo "GLOBAL RULE: test chỉ replay goals có status=READY + goal_sequence.steps[] ≥ 1."
  echo "Intermediate status = review chưa resolve. KHÔNG được dùng /vg:test để 'cover' NOT_SCANNED."
  echo ""
  echo "Fix tại review:"
  echo "  /vg:review ${PHASE_NUMBER} --retry-failed    (deeper probe)"
  echo "  HOẶC update TEST-GOALS với 'Infra deps: [<no-ui tag>]' → re-classify INFRA_PENDING (tag value per project config.infra_deps — workflow không hardcode)"
  echo "  HOẶC manually mark UNREACHABLE nếu feature genuinely không tồn tại"
  echo ""
  echo "Re-run: /vg:review ${PHASE_NUMBER} sau khi fix → mọi goals phải ở 1 trong 4 status kết luận"
  echo "  (READY | BLOCKED | UNREACHABLE | INFRA_PENDING)"
  exit 1
fi
```

**Per-goal runtime rule (enforced trong step 5c_goal_verification):**
Khi loop qua goals để replay:
- `status == READY` + `goal_sequence.steps[]` ≥ 1 → replay (normal path)
- `status == UNREACHABLE|INFRA_PENDING` → skip với log "expected skip" (không fail, không count)
- `status == BLOCKED` → attempt replay (fix có thể resolve) nhưng không block verdict nếu vẫn fail
- Any other status → **ERROR**: test.md không được chạm tới goal có intermediate status (đã block ở gate trên, nếu tới đây = bug)

If `--regression-only`: skip to 5e (requires generated tests to exist).
If `--smoke-only`: run only 5c-smoke, report, exit.
If `--fix-only`: skip to 5c-fix section.
</step>

<step name="create_task_tracker">
Create tasks for progress tracking:
```
TaskCreate: "5a. Deploy to target"              (activeForm: "Deploying...")
TaskCreate: "5b. Runtime contract verify"       (activeForm: "Verifying contracts...")
TaskCreate: "5c. Independent smoke check"       (activeForm: "Spot-checking runtime map...")
TaskCreate: "5c. Goal verification"             (activeForm: "Verifying goals...")
TaskCreate: "5c. Minor fix loop"                (activeForm: "Fixing minor issues...")
TaskCreate: "5c. Multi-page flows"              (activeForm: "Running flow tests...")
TaskCreate: "5d. Codegen"                       (activeForm: "Generating .spec.ts...")
TaskCreate: "5e. Regression run"                (activeForm: "Running Playwright tests...")
TaskCreate: "5f. Security audit"                (activeForm: "Running security scan...")
```
</step>

<step name="0_state_update">
**Update PIPELINE-STATE.json pipeline position:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'testing'; s['pipeline_step'] = 'test'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```
</step>

<step name="5a_deploy" profile="web-fullstack,web-frontend-only,web-backend-only,cli-tool,library">
## 5a: DEPLOY (web/cli/library)

**If --skip-deploy, skip this step.**

Read `.claude/commands/vg/_shared/env-commands.md` — deploy(env) + preflight(env).

```
1. Record SHAs (local + target)
2. Pre-deploy command (if configured in config)
3. Build + restart on target
4. Wait for startup
5. Health check → if fail → rollback
6. Preflight all services → required service FAIL → BLOCK
7. Typecheck (if configured): run typecheck(env) from env-commands.md
8. Re-seed DB (if configured): run seed_smoke(env) from env-commands.md
   Purpose: test runs generated E2E flows + mutation probes against fresh data.
   Review may have left dirty DB state (created/deleted records). Re-seed ensures
   deterministic test data. Skip silently if seed_command empty.
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
</step>

<step name="5a_mobile_deploy" profile="mobile-*">
## 5a (mobile): DEPLOY — binary build + signed upload

**If --skip-deploy, skip this step.**

Mobile deploy is fundamentally different from web deploy: there is no
`rsync + pm2 reload`; we produce a signed binary (IPA / APK / AAB) and
upload it to a distribution channel (Firebase App Distribution, TestFlight,
Play Internal Track). Helper functions live in
`.claude/commands/vg/_shared/mobile-deploy.md`.

```bash
# Source helper reference (re-exports mobile_deploy_* functions)
HELPER="${REPO_ROOT}/.claude/commands/vg/_shared/mobile-deploy.md"
[ -f "$HELPER" ] || { echo "⛔ missing mobile-deploy helper at $HELPER"; exit 1; }

# The helper is markdown — its bash blocks are meant to be copied into the
# caller's invocation context. The orchestrator reads the helper then exec's
# the fenced ```bash``` regions. In practice /vg:test extracts the seven
# primitives (mobile_deploy_provider_detect, _effective_provider,
# _check_provider, _stage, _invoke, _health, _pipeline, _rollback) and runs
# mobile_deploy_pipeline.

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

Final action: `touch "${PHASE_DIR}/.step-markers/5a_mobile_deploy.done"`
</step>

<step name="5b_runtime_contract_verify" profile="web-fullstack,web-backend-only">
## 5b: RUNTIME CONTRACT VERIFY (curl + jq, no AI)

Read `.claude/commands/vg/_shared/env-commands.md` — contract_verify_curl(phase_dir).
Read `.claude/skills/api-contract/SKILL.md` — Mode: Verify-Curl.

For each endpoint in API-CONTRACTS.md:
```
curl endpoint on target → extract response keys via jq
Compare actual keys vs expected keys from contract
Record: endpoint, match status, mismatched fields (if any)
```

Result:
- All match → PASS
- Any mismatch → BLOCK (with specific mismatches listed)

### 5b-2: Idempotency check (auto-ON for critical_domains)

**Skip conditions:**
- `config.critical_domains` not defined or empty → skip
- No endpoints in API-CONTRACTS.md match critical_domains → skip
- Server not running (`$BASE_URL` empty) → skip

**Purpose:** Billing, auth, and payout endpoints MUST be idempotent for mutations (POST/PUT/DELETE).
Double-submit the same request should NOT create duplicate records, charge twice, or
produce inconsistent state. This catches the class of bugs where retry/network-glitch
causes real financial damage.

```bash
CRITICAL_DOMAINS="${config.critical_domains:-billing,auth,payout,payment,transaction}"
IDEMPOTENCY_FAILS=0

# Parse endpoints from contract that match critical domains
${PYTHON_BIN} -c "
import re, sys
from pathlib import Path

text = Path('${PHASE_DIR}/API-CONTRACTS.md').read_text(encoding='utf-8')
domains = '${CRITICAL_DOMAINS}'.split(',')

# Find mutation endpoints (POST/PUT/DELETE) that touch critical domains
for m in re.finditer(r'###\s+(POST|PUT|DELETE)\s+(/\S+)', text):
    method, path = m.groups()
    path_lower = path.lower()
    if any(d.strip() in path_lower for d in domains):
        # Extract mutation evidence to detect expected count change
        rest = text[m.end():m.end()+500]
        evidence = re.search(r'Mutation evidence.*?:(.*?)(?:\n##|\n\*\*|$)', rest, re.DOTALL)
        ev_text = evidence.group(1).strip() if evidence else ''
        print(f'{method}\t{path}\t{ev_text}')
" > "${VG_TMP}/critical-endpoints.txt"

CRITICAL_COUNT=$(wc -l < "${VG_TMP}/critical-endpoints.txt" | tr -d ' ')

if [ "$CRITICAL_COUNT" -gt 0 ] && [ -n "$BASE_URL" ]; then
  echo "Idempotency check: ${CRITICAL_COUNT} critical-domain mutation endpoints"

  # Extract valid sample payloads from contract Block 4 (valid test samples)
  # Block 4 is authored by blueprint step 2b — values pass Zod/Pydantic validation
  ${PYTHON_BIN} -c "
import re, json
from pathlib import Path
text = Path('${PHASE_DIR}/API-CONTRACTS.md').read_text(encoding='utf-8')
domains = '${CRITICAL_DOMAINS}'.split(',')

for m in re.finditer(r'###\s+(POST|PUT|DELETE)\s+(/\S+)', text):
    method, path = m.groups()
    path_lower = path.lower()
    if any(d.strip() in path_lower for d in domains):
        rest = text[m.end():m.end()+4000]
        # Find Block 4 sample JSON (e.g. PostSitesSample = { ... })
        sample_match = re.search(r'Sample\s*=\s*(\{[^}]+\})', rest)
        if sample_match:
            print(f'{method}\t{path}\t{sample_match.group(1)}')
        else:
            print(f'{method}\t{path}\t{{}}')
" 2>/dev/null > "${VG_TMP}/critical-payloads.txt"

  while IFS=$'\t' read -r METHOD ENDPOINT PAYLOAD; do
    [ -z "$ENDPOINT" ] && continue
    [ -z "$PAYLOAD" ] && PAYLOAD='{}'

    # Step 1: Send mutation with valid contract-derived payload
    RESP1=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      -w "\n%{http_code}" 2>/dev/null)
    STATUS1=$(echo "$RESP1" | tail -1)

    # Step 2: Immediately re-send IDENTICAL request
    RESP2=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      -w "\n%{http_code}" 2>/dev/null)
    STATUS2=$(echo "$RESP2" | tail -1)

    # Step 3: Check for duplicate creation
    # Good: 2nd returns 409 Conflict, or same ID (idempotent)
    # Bad: two 201 with different IDs (duplicate created)
    if [ "$STATUS1" = "201" ] && [ "$STATUS2" = "201" ]; then
      ID1=$(echo "$RESP1" | sed '$d' | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      ID2=$(echo "$RESP2" | head -1 | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      if [ -n "$ID1" ] && [ -n "$ID2" ] && [ "$ID1" != "$ID2" ]; then
        echo "  CRITICAL: ${METHOD} ${ENDPOINT} — double-submit created 2 records (${ID1} vs ${ID2})"
        IDEMPOTENCY_FAILS=$((IDEMPOTENCY_FAILS + 1))
      fi
    elif [ "$STATUS1" = "400" ]; then
      echo "  SKIP: ${METHOD} ${ENDPOINT} — schema validation rejected test payload (400)"
    fi
  done < "${VG_TMP}/critical-payloads.txt"

  if [ "$IDEMPOTENCY_FAILS" -gt 0 ]; then
    echo "  ⛔ ${IDEMPOTENCY_FAILS} idempotency failures on critical endpoints"
  else
    echo "  ✓ All critical-domain endpoints pass idempotency check"
  fi
fi
```

Result routing:
- `IDEMPOTENCY_FAILS > 0` → FAIL (same severity as contract mismatch)
- `IDEMPOTENCY_FAILS == 0` → PASS

Display:
```
5b Runtime Contract Verify:
  Endpoints: {checked}/{total}
  Fields: {matched}/{total}
  Idempotency (critical domains): {CRITICAL_COUNT} checked, {IDEMPOTENCY_FAILS} failures
  Result: {PASS|BLOCK}
```
</step>

<step name="5c_smoke" profile="web-fullstack,web-frontend-only">
## 5c-smoke: INDEPENDENT SPOT CHECK (~2 min, ~5 MCP calls)

**PURPOSE:** Cross-check that RUNTIME-MAP matches current app state. Review may have run hours ago — app could have drifted.

**Browser mode: HEADED (visible, not headless).**

**Login** using credentials from config.credentials[ENV].

**METHOD — stratified sampling (not random):**
```
1. Select 5 views from RUNTIME-MAP.json using stratified sampling:
   - At least 1 view from each role (if multi-role)
   - Prefer views with most elements[]
   - Remaining slots: pick views referenced by goal_sequences

2. For each selected view:
   a. Navigate there via UI clicks (not URL)
   b. browser_snapshot → read current state
   c. Compare snapshot_summary vs what AI sees now
   d. Check fingerprint: element count similar? Key elements[] still exist?
   e. If goal_sequences reference this view: replay 1-2 steps from a sequence
   f. Compare observation vs RUNTIME-MAP entry:
      - Same? → MATCH
      - Different? → MISMATCH (record what changed)
   g. browser_console_messages → new errors?

3. Results:
   - 0 mismatches → PROCEED to goal verification
   - 1 mismatch → WARNING, proceed but note drift
   - ≥2 mismatches → FLAG: "Runtime may have drifted since review."
     Suggest: "Re-run /vg:review --resume to update RUNTIME-MAP"
     Ask user: proceed anyway or re-review?
```

Display:
```
5c Smoke Check:
  Views checked: 5
  Matches: {N}/5
  Result: {PROCEED|WARNING|FLAG}
```
</step>

<step name="5c_goal_verification">
## 5c-goal: GOAL VERIFICATION (surface-aware — Playwright for ui, runners for others)

**v1.14.0+ B.1 — TRUST REVIEW, KHÔNG re-verify goals READY:**

Theo spec v1.14.0+, review 100% gate đã verify mọi goal. Test KHÔNG re-verify functional — chỉ:
- **Codegen** (step 13 — B.2): sinh Playwright spec cho goal READY (regression harness).
- **Deep-probe** (step 14 — B.3): sinh 3 edge-case variants per goal.
- **MANUAL goals**: codegen sinh skeleton `.skip()` — UAT điền human check.
- **DEFERRED goals**: skip codegen (phase target chưa deploy).
- **BLOCKED/UNREACHABLE**: review 100% gate đã chặn → không đến đây.

```bash
# Gate trust-review check (v1.14.0+ B.1 — bỏ qua re-verify loop nếu config enabled)
SKIP_REVERIFY=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'skip_ready_reverify\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'true')  # default true cho v1.14.0+
except Exception:
    print('true')
")

if [ "$SKIP_REVERIFY" = "true" ]; then
  echo ""
  echo "━━━ v1.14.0+ B.1: TRUST REVIEW ━━━"
  echo "Review 100% gate đã verify goals — /vg:test bỏ qua re-verify loop."
  echo "Chỉ chạy codegen (B.2) + deep-probe (B.3) cho goals READY."
  echo ""
  # Jump thẳng sang codegen/deep-probe (step sẽ wire ở step 13+14)
  # Legacy replay loop dưới là fallback khi --legacy-mode hoặc skip_ready_reverify=false.
  export TRUST_REVIEW=true
else
  echo "ℹ skip_ready_reverify=false — chạy legacy re-verify loop (pre-v1.14 behavior)."
  export TRUST_REVIEW=false
fi
```

**Legacy path (pre-v1.14.0, chỉ chạy nếu TRUST_REVIEW=false):**

**INPUT:**
- TEST-GOALS.md (goals with success criteria + mutation evidence + dependencies + **Surface:**)
- RUNTIME-MAP.json (discovered paths from review — canonical JSON)
- GOAL-COVERAGE-MATRIX.md (which goals are ready/blocked/unreachable)

**Browser mode: HEADED (visible)** — only for `surface=ui` goals.

**Surface classification (v1.9.1 R1 — lazy migration, runs FIRST):**

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
set -e
# Same Haiku tie-break + AskUserQuestion contract as blueprint 2b5 / review 4a.
```

**Per-goal dispatch (non-UI surfaces):**

```bash
# shellcheck source=_shared/lib/test-runners/dispatch.sh
. .claude/commands/vg/_shared/lib/test-runners/dispatch.sh
for gid in $(grep -oE '^## Goal G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | grep -oE 'G-[0-9]+'); do
  surface=$(awk "/^## Goal ${gid}\b/{f=1} f && /^\*\*Surface:\*\*/{sub(/.*Surface:\*\* /,\"\"); sub(/ .*/,\"\"); print; exit}" "${PHASE_DIR}/TEST-GOALS.md")
  surface="${surface:-ui}"
  case "$surface" in
    ui|ui-mobile) continue ;;   # Fall through to existing replay loop below
    *)
      RESULT=$(dispatch_test_runner "$surface" "$gid" "${PHASE_DIR}" "${PHASE_DIR}/test-runners/fixtures")
      STATUS=$(echo "$RESULT" | sed -n 's/.*STATUS=\([A-Z]*\).*/\1/p')
      EVID=$(echo "$RESULT" | sed -n 's/.*EVIDENCE=\([^\t]*\).*/\1/p')
      # Persist result JSON so final summary tree + TEST-RESULTS.md can merge with ui results
      mkdir -p "${VG_TMP:-${PHASE_DIR}/.vg-tmp}"
      echo "{\"goal_id\":\"${gid}\",\"status\":\"${STATUS}\",\"surface\":\"${surface}\",\"evidence\":\"${EVID}\"}" \
        > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/goal-${gid}-result.json"
      ;;
  esac
done
```

UI / mobile goals flow through the existing replay loop below. Non-UI goal results are merged into the final summary tree with identical schema (goal_id, status, evidence).

**Execute goals in dependency order (topological sort):**

Parse dependencies from TEST-GOALS.md and sort:
```
For each goal: extract depends_on field
Topological sort → execution order (no-deps first, then dependents)
```

**For each goal:**

**🎬 Live narration protocol (tightened 2026-04-17 — user-readable progress):**

Trước mỗi goal và trước mỗi step, print MỘT dòng tiếng người để user theo dõi đang test cái gì. Narration MỤC TIÊU là "người đọc hiểu được flow", không phải log kỹ thuật.

Format chuẩn (copy vào narrator helper):
```bash
narrate_goal_start() {
  local gid="$1" title="$2" prio="$3" idx="$4" total="$5"
  echo ""
  echo "━━━ [${idx}/${total}] ${gid} • ${prio} ━━━"
  echo "🎯 ${title}"
}

narrate_step() {
  local n="$1" total="$2" verb="$3" target="$4" value="$5"
  # verb ∈ {click, fill, select, wait, observe, assert, navigate}
  # Map to friendly verb:
  case "$verb" in
    navigate) icon="📍"; action="Mở trang" ;;
    click)    icon="👆"; action="Bấm" ;;
    fill)     icon="⌨️ "; action="Điền" ;;
    select)   icon="🔽"; action="Chọn" ;;
    wait)     icon="⏳"; action="Đợi" ;;
    observe)  icon="👁 "; action="Kiểm tra hiện" ;;
    assert)   icon="✓"; action="Xác nhận" ;;
    *)        icon="•"; action="$verb" ;;
  esac
  if [ -n "$value" ]; then
    echo "  [${n}/${total}] ${icon} ${action} ${target} = \"${value}\""
  else
    echo "  [${n}/${total}] ${icon} ${action} ${target}"
  fi
}

narrate_step_result() {
  local status="$1" detail="$2"
  case "$status" in
    PASS) echo "       ✓ ${detail}" ;;
    FAIL) echo "       ❌ ${detail}" ;;
    SKIP) echo "       ⊘ ${detail}" ;;
  esac
}

narrate_goal_end() {
  local gid="$1" status="$2" duration="$3" reason="$4"
  case "$status" in
    PASSED)      echo "✅ ${gid} PASSED (${duration}s)" ;;
    FAILED)      echo "❌ ${gid} FAILED (${duration}s) — ${reason}" ;;
    UNREACHABLE) echo "⚠️  ${gid} UNREACHABLE — ${reason}" ;;
  esac
  echo ""
}
```

Example narration người dùng thấy khi chạy:
```
━━━ [3/12] G-03 • critical ━━━
🎯 Tạo chiến dịch mới với budget và targeting

  [1/6] 📍 Mở trang Campaigns (sidebar > Campaigns)
  [2/6] 👆 Bấm "New Campaign"
       ✓ Modal mở
  [3/6] ⌨️  Điền name = "Test Campaign"
  [4/6] ⌨️  Điền budget = "500"
  [5/6] 👆 Bấm "Create"
       ✓ Toast "Campaign created"
       ✓ API POST /api/campaigns → 201
  [6/6] ✓ Xác nhận row mới xuất hiện trong bảng
✅ G-03 PASSED (4.2s)
```

**Mandatory:** narrator MUST run at each step marker — không được silent. Caller có thể pipe tới log file nhưng NEVER skip narration in stdout.

```
1. Read goal from TEST-GOALS.md:
   - Success criteria (what must be true)
   - Mutation evidence (observable proof for mutations)
   - Priority (critical / important / nice-to-have)

   → narrate_goal_start ${goal_id} "${title}" ${priority} ${current_idx} ${total_goals}

2. Read goal_sequence from RUNTIME-MAP.json:
   - goal_sequences[goal_id].start_view → where to begin
   - goal_sequences[goal_id].steps[] → exact action chain recorded during review
   - goal_sequences[goal_id].result → what review found (passed/failed)

3. REPLAY the goal_sequence step by step:
   a. Navigate to start_view (via UI clicks, using views[start_view].arrive_via)
   b. **Snapshot baseline BEFORE replay** (HARD RULE — tightened 2026-04-17):
      - BASELINE_CONSOLE_COUNT = len(browser_console_messages() where type == "error")
      - BASELINE_NETWORK_4XX = count of network responses with status 4xx|5xx before replay
      - Persist baseline to ${VG_TMP}/goal-${goal_id}-baseline.json
   c. For each step in goal_sequences[goal_id].steps:

      → narrate_step ${step_idx} ${total_steps} "${step.do:-step.observe:-step.assert}" "${step.label:-step.selector}" "${step.value:-}"

      IF step.do exists (action step):
        Execute: browser_{step.do}(step.selector, step.value?)
        browser_wait_for → state stabilized
        **MANDATORY per-step console/network check (tightened 2026-04-17):**
          STEP_CONSOLE = browser_console_messages() filter type == "error"
          NEW_ERRORS = STEP_CONSOLE minus BASELINE_CONSOLE_COUNT
          IF NEW_ERRORS > 0:
            STEP_NETWORK = browser_network_requests() filter status >= 400
            → narrate_step_result FAIL "console error: ${NEW_ERRORS[0]}"
            Record step as FAILED with {console_errors: [...], failed_requests: [...]}
            BREAK replay — goal cannot pass when step triggers errors

      IF step.observe exists (observation step):
        browser_snapshot → compare current state vs step.observe description
        Record: MATCH or MISMATCH
        → narrate_step_result ${MATCH|MISMATCH} "${step.observe_description}"
        IF step has network[] expectations:
          ACTUAL_NET = browser_network_requests() for step.endpoint
          EXPECTED_STATUS = step.network[0].status
          → narrate_step_result ${matched?PASS:FAIL} "API ${step.endpoint} → ${ACTUAL_NET[0].status}"
          IF ACTUAL_NET[0].status != EXPECTED_STATUS:
            Record step as FAILED with {expected_status, actual_status, url}

      IF step.assert exists (verification step):
        Check criterion from TEST-GOALS against current state
        Record: PASS or FAIL with evidence
        → narrate_step_result ${PASS|FAIL} "${step.assert_description}"

   d. browser_take_screenshot → evidence
      Save to: ${SCREENSHOTS_DIR}/{phase}-goal-{goal_id}-{pass|fail}.png

4. Record goal result (HARD RULES — tightened 2026-04-17, no AI discretion):
   - ALL assert steps PASS AND NEW_ERRORS == 0 AND all network expectations met → Goal PASSED
   - ANY assert step FAIL → Goal FAILED (with specific failure + which step)
   - NEW_ERRORS > 0 (any step) → Goal FAILED (evidence: console error dump)
   - Network status mismatch at any step → Goal FAILED (evidence: {expected, actual, url})
   - Could not complete replay (element missing, navigation broken) → Goal UNREACHABLE
   **Persist goal result as JSON** to ${VG_TMP}/goal-${goal_id}-result.json with schema:
   `{goal_id, status, evidence: {console, network, assert_failures, screenshot_path}}`

   → narrate_goal_end ${goal_id} ${status} ${duration_s} "${failure_reason:-}"

5. If goal FAILED and was READY in GOAL-COVERAGE-MATRIX:
   → Possible regression since review
   → Note: "Was READY in review, FAILED in test — regression"
```

**For BLOCKED goals (from GOAL-COVERAGE-MATRIX):**
- Attempt anyway — review fix may have resolved the blocker
- If passes → upgrade to PASSED
- If fails → record expected failure

**For UNREACHABLE goals:**
- Try alternative navigation paths
- If truly unreachable → record as build gap

**🎬 Goal tree summary (tightened 2026-04-17 — cuối cùng user thấy overview):**

Sau khi replay tất cả goals, print tree tổng kết. FAILED goals expand chi tiết, PASSED chỉ 1 dòng.

```bash
echo ""
echo "═══════════════════════════════════════════════"
echo "  GOAL VERIFICATION SUMMARY"
echo "═══════════════════════════════════════════════"
PASSED_COUNT=0; FAILED_COUNT=0; UNREACHABLE_COUNT=0
for rf in "${VG_TMP}"/goal-*-result.json; do
  [ -f "$rf" ] || continue
  GID=$(${PYTHON_BIN} -c "import json;print(json.load(open('$rf'))['goal_id'])")
  STATUS=$(${PYTHON_BIN} -c "import json;print(json.load(open('$rf'))['status'])")
  TITLE=$(${PYTHON_BIN} -c "import json;print(json.load(open('$rf')).get('title',''))")
  case "$STATUS" in
    PASSED)      echo "  ✅ ${GID}: ${TITLE}"; PASSED_COUNT=$((PASSED_COUNT+1)) ;;
    FAILED)
      FAIL_STEP=$(${PYTHON_BIN} -c "import json;d=json.load(open('$rf'));print(d.get('evidence',{}).get('assert_failures',[{}])[0].get('step','?'))")
      FAIL_REASON=$(${PYTHON_BIN} -c "import json;d=json.load(open('$rf'));print(d.get('evidence',{}).get('assert_failures',[{}])[0].get('reason','unknown'))")
      echo "  ❌ ${GID}: ${TITLE}"
      echo "      └─ failed at step ${FAIL_STEP}: ${FAIL_REASON}"
      FAILED_COUNT=$((FAILED_COUNT+1))
      ;;
    UNREACHABLE) echo "  ⚠️  ${GID}: ${TITLE} (unreachable)"; UNREACHABLE_COUNT=$((UNREACHABLE_COUNT+1)) ;;
  esac
done
echo ""
echo "  Tổng: ${PASSED_COUNT} PASS · ${FAILED_COUNT} FAIL · ${UNREACHABLE_COUNT} UNREACHABLE"
echo "═══════════════════════════════════════════════"
```

**After all goals verified, update GOAL-COVERAGE-MATRIX.md:**
```
For each goal:
  Update status from review-time (READY/BLOCKED/UNREACHABLE)
    to test-verified (✅ TEST-PASSED / ❌ TEST-FAILED / ⚠️ TEST-UNREACHABLE)
  Add test timestamp and evidence reference
Write updated GOAL-COVERAGE-MATRIX.md
```

Display per goal:
```
Goal {id} ({priority}): {description}
  Criteria: {passed}/{total} passed
  Mutations: {verified}/{total} verified
  Result: {PASSED|FAILED|UNREACHABLE}
```
</step>

<step name="5c_fix">
## 5c-fix: MINOR FIX ONLY (max 2 iterations — auto-gated severity v1.14.4+)

**If all goals PASSED → skip to 5d.**

### Pre-flight: AI MUST emit fix-plans.json BEFORE editing code

Trước khi attempt fix, AI viết `${PHASE_DIR}/.test-fix-plans.json`:

```json
[
  {
    "goal_id": "G-04",
    "failure_symptom": "Toast text tiếng Việt thay vì English",
    "files_to_edit": ["apps/web/src/i18n/vi.ts"],
    "change_type": "ui_cosmetic",
    "claimed_severity": "MINOR"
  }
]
```

`change_type` phải là một trong: `ui_cosmetic | logic | contract | shared | new_feature`.

### Auto-severity gate (deterministic — R4 enforcement)

```bash
FIX_PLAN="${PHASE_DIR}/.test-fix-plans.json"
if [ ! -f "$FIX_PLAN" ]; then
  echo "⛔ R4 gate: AI chưa emit .test-fix-plans.json trước khi fix."
  echo "   Format required: [{goal_id, files_to_edit[], change_type, claimed_severity}]"
  exit 1
fi

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$FIX_PLAN" "${PHASE_DIR}" <<'PY'
import json, sys
from pathlib import Path

plans = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
phase_dir = Path(sys.argv[2])

if isinstance(plans, dict):
    plans = [plans]

# Deterministic rules
CONTRACT_PATHS = ('apps/api/src/modules/', 'apps/api/src/routes/', 'apps/api/src/schemas/', 'apps/api/src/contracts/')
SHARED_PATHS = ('packages/', 'apps/web/src/lib/', 'apps/web/src/hooks/', 'apps/web/src/stores/')

auto_escalations = []
minor_plans = []
for plan in plans:
    gid = plan.get('goal_id', '?')
    files = plan.get('files_to_edit', []) or []
    ctype = plan.get('change_type', 'logic')
    claimed = plan.get('claimed_severity', 'MINOR')

    severity = 'MINOR'
    reasons = []

    if len(files) >= 3:
        severity = 'MODERATE'
        reasons.append(f"{len(files)} files ≥ 3 (scope lớn)")

    if any(any(f.startswith(p) for p in CONTRACT_PATHS) for f in files):
        severity = 'MODERATE'
        reasons.append("touches API contract path (ảnh hưởng BE↔FE alignment)")

    if any(any(f.startswith(p) for p in SHARED_PATHS) for f in files):
        if severity != 'MAJOR':
            severity = 'MODERATE'
        reasons.append("touches shared path (ripple effect — lan tỏa sang module khác)")

    if ctype == 'new_feature':
        severity = 'MAJOR'
        reasons.append("new_feature (không phải test concern)")

    if ctype == 'contract':
        severity = 'MAJOR'
        reasons.append("contract change (đụng schema BE↔FE)")

    # AI claim vs computed
    plan['computed_severity'] = severity
    plan['gate_reasons'] = reasons

    if severity in ('MODERATE', 'MAJOR'):
        auto_escalations.append(plan)
    else:
        minor_plans.append(plan)

# Write back annotated plan
Path(sys.argv[1]).write_text(json.dumps(plans, indent=2, ensure_ascii=False), encoding='utf-8')

if auto_escalations:
    # Write REVIEW-FEEDBACK.md
    feedback = phase_dir / "REVIEW-FEEDBACK.md"
    md = ["# Review Feedback — Auto-escalated from /vg:test R4 gate", ""]
    md.append(f"**{len(auto_escalations)} goal(s) auto-classified MODERATE/MAJOR — test KHÔNG được fix, kick back sang review.**")
    md.append("")
    md.append("| Goal | AI claimed | Computed | Reasons | Files |")
    md.append("|---|---|---|---|---|")
    for e in auto_escalations:
        files_str = ', '.join(e['files_to_edit'][:3])
        if len(e['files_to_edit']) > 3:
            files_str += f" (+{len(e['files_to_edit'])-3} more)"
        md.append(f"| {e['goal_id']} | {e.get('claimed_severity','?')} | **{e['computed_severity']}** | {'; '.join(e['gate_reasons'])} | {files_str} |")
    md.append("")
    md.append("## Next step")
    md.append("```bash")
    md.append(f"/vg:review {phase_dir.name.split('-')[0]} --retry-failed")
    md.append("```")
    md.append("Review sẽ re-scan failing goals với full fix context + bật lại scanner để phát hiện root cause đúng layer.")
    feedback.write_text("\n".join(md), encoding='utf-8')

    print(f"⛔ R4 gate: {len(auto_escalations)} goal(s) auto-escalated → REVIEW-FEEDBACK.md")
    print(f"   MINOR remaining: {len(minor_plans)} (test fix được)")
    print("")
    print("Test WILL NOT fix escalated goals. Proceed với MINOR only + re-run /vg:review --retry-failed cho MODERATE/MAJOR.")
    sys.exit(2)
else:
    print(f"✓ R4 pre-flight: {len(minor_plans)} plan(s) in MINOR scope — test fix tiếp được.")
PY

SEV_RC=$?
if [ "$SEV_RC" = "2" ]; then
  # At least 1 goal escalated. Remove escalated plans từ fix-plans.json, continue với MINOR only
  # (Python already annotated fix-plans.json with computed_severity)
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$FIX_PLAN" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
plans = json.loads(path.read_text(encoding='utf-8'))
if isinstance(plans, dict):
    plans = [plans]
minor = [p for p in plans if p.get('computed_severity') == 'MINOR']
path.write_text(json.dumps(minor, indent=2, ensure_ascii=False), encoding='utf-8')
PY
fi
```

### Severity reference (cho AI tự check trước khi emit plan)

```
For each FAILED goal:
  CLASSIFY failure severity (pre-flight sẽ re-verify deterministic):
  
  MINOR (test fixes directly):
    - Wrong text/label (typo, translation key)
    - CSS/layout issue (z-index, overflow, display)
    - Off-by-one (pagination, count)
    - Missing null check (undefined in edge case)
    → FIX immediately, commit: "fix({phase}): {description}"
    → Re-verify THIS goal only
  
  MODERATE (auto-escalate to review):
    - API returns wrong status code (touches contract path)
    - Form validation missing (touches shared hooks/lib)
    - Data not refreshing after mutation (touches multiple files)
    - Touches ≥3 files — ripple ngoài scope test
  
  MAJOR (auto-escalate to review):
    - Feature completely missing (change_type=new_feature)
    - Contract schema change (change_type=contract)
    - Navigation path broken
    - Auth/permissions wrong
```

**Fix iteration (max 2 — MINOR only):**
```
Iteration 1:
  1. Fix all MINOR issues → commit each
  2. Re-verify affected goals only (not full suite)
  3. Update RUNTIME-MAP.json with fixes

Iteration 2 (if still MINOR failures):
  1. Remaining MINOR → fix + commit
  2. Re-verify
  3. If STILL failing → reclassify as MODERATE → escalate
```

**REVIEW-FEEDBACK.md** (written on auto-escalate STOP or when MODERATE/MAJOR issues persist):
```markdown
# Review Feedback — Phase {phase}

Generated by: /vg:test auto-escalate (budget {TOTAL_ITER}/3 exhausted)
Date: {ISO timestamp}

## Failing Goals
| Goal ID | Priority | Status | Failure Reason | Evidence |
|---------|----------|--------|----------------|----------|
| G-{id}  | critical | BLOCKED | {what failed}  | {network/console/screenshot path} |
...

## Runtime Map Corrections
(entries where RUNTIME-MAP.json diverged from actual runtime behavior)

## Root Cause Analysis (AI-inferred)
For each failing goal, classify most likely cause:
  - **Code bug** — behavior wrong but feature exists (fix code in editor)
  - **Test spec bug** — Playwright selector/timing wrong (edit .spec.ts)
  - **Spec mismatch** — goal criteria unrealistic or needs redesign (edit TEST-GOALS.md)
  - **Alt test needed** — E2E can't verify (perf/worker → k6/vitest)
  - **Upstream blocker** — phase depends on broken cross-phase feature

## What to do next

▶ **Step 1: Read this file + check goal details**
   cat ${PLANNING_DIR}/phases/{phase}/REVIEW-FEEDBACK.md
   cat ${PLANNING_DIR}/phases/{phase}/GOAL-COVERAGE-MATRIX.md

▶ **Step 2: Match each failing goal to a remediation path below**

Per-goal commands (filled in dynamically for THIS phase):

| Goal | Classification | Exact command to run |
|------|----------------|---------------------|
| G-{id} | code bug | (fix code manually) → `/vg:test {phase} --regression-only` |
| G-{id} | test spec bug | `rm apps/web/e2e/generated/{pattern}.spec.ts` → `/vg:test {phase} --skip-deploy` |
| G-{id} | spec mismatch | (edit TEST-GOALS.md to loosen criteria) → `/vg:test {phase} --regression-only` |
| G-{id} | alt test needed | (write k6/vitest) → mark SKIPPED in matrix → `/vg:accept {phase}` |
| G-{id} | upstream blocker | fix upstream phase first → `/vg:review {phase} --retry-failed` |

▶ **Step 3: After your fixes, pick ONE:**

   A) Verified all fixes, want to retry auto-loop fresh:
      `rm ${PLANNING_DIR}/phases/{phase}/test-loop-state.json`
      `/vg:test {phase}`

   B) Small targeted retry (no codegen, just rerun tests):
      `/vg:test {phase} --regression-only`

   C) Bypass failing goals (document limitation, ship anyway):
      (edit GOAL-COVERAGE-MATRIX.md → mark SKIPPED with justification)
      `/vg:accept {phase}`

   D) Rollback phase entirely (goal design fundamentally wrong):
      `git revert {phase_commits}`
      `/vg:scope {phase}` (redo scope with better criteria)

## Do NOT

- ❌ Run `/vg:build {phase} --gaps-only` — code for failing goals ALREADY EXISTS (review confirmed). Building again wastes tokens.
- ❌ Run `/vg:review {phase}` full fresh — use `--retry-failed` for targeted re-scan.
- ❌ Loop `/vg:test {phase}` without changes — budget won't reset, same failures return.
- ❌ Claim "done" without updating GOAL-COVERAGE-MATRIX.md for SKIPPED goals.
```
</step>

<step name="5c_auto_escalate">
## 5c-auto-escalate: AUTO-LOOP TO RESOLUTION (max 3 total iterations across test+review)

**Goal: avoid stopping at "gaps found" and making user manually stitch test → review → build. Auto-chain until PASSED or budget hit.**

Loop counter: `TOTAL_ITER` (persisted in `${PHASE_DIR}/test-loop-state.json`, survives re-invocations).

After 5c-fix completes:
```
remaining_failures = goals still NOT READY after MINOR fixes

IF remaining_failures == 0:
  → skip to 5d (codegen)

IF TOTAL_ITER >= 3:
  → STOP auto-loop. Write SANDBOX-TEST.md with verdict=GAPS_FOUND.
  → Write REVIEW-FEEDBACK.md with "What to do next" section (see template below)
  → Print FINAL GUIDANCE block (see below)
  → Do NOT escalate further (prevent infinite loop)

ELSE classify remaining_failures and auto-invoke the right next step:

  (A) MODERATE/MAJOR code bugs (API wrong, validation missing, data mismatch):
      → TOTAL_ITER += 1
      → Auto-invoke: /vg:review {phase} --retry-failed
        (review browser scan has more power to diagnose + fix than test)
      → After review completes → re-evaluate goals → loop back to top of 5c-auto-escalate

  (B) UNREACHABLE goals resurface (view wasn't found even with codegen):
      → Cross-reference code (grep pattern/route files):
        IF code missing → auto-invoke: /vg:build {phase} --gaps-only
        IF code exists  → route as MODERATE (type A above)
      → After build/review completes → re-evaluate goals → loop back

  (C) NOT_SCANNED persisting after test (wizard not walked even by Playwright):
      → Inspect test file for selector issues / wait timing
      → TOTAL_ITER += 1
      → Regenerate specific test: /vg:test {phase} --skip-deploy  (re-codegen only)
      → After regen → rerun test → loop back

  (D) Goal marked SKIPPED (not E2E-verifiable — perf/worker/cross-system):
      → Do NOT loop. Mark in SANDBOX-TEST.md with reason.
      → These goals delegated to: k6 (perf), vitest integration (worker), manual UAT
      → Update GOAL-COVERAGE-MATRIX: status=SKIPPED with justification
```

**Termination conditions (hard stops):**
```
1. All goals READY → PASSED → proceed to 5d
2. TOTAL_ITER == 3 → STOP with GAPS_FOUND + REVIEW-FEEDBACK.md
3. Pre-flight fail (service crashed mid-loop) → STOP, user fixes infra
4. User interrupts (Ctrl+C / cancel) → STOP, save state for resume
```

**FINAL GUIDANCE when budget exhausted (print to user):**

```
⛔ Auto-resolve budget exhausted (3/3 iterations).

Remaining failures: {N} goals still NOT READY
  - [BLOCKED]     {goal_id}: {reason}
  - [NOT_SCANNED] {goal_id}: {reason}
  - [UNREACHABLE] {goal_id}: {reason}

Why auto-loop stopped:
The pipeline tried 3 rounds of (fix → review → rebuild → retest) but some goals still fail.
This usually means the root cause is DEEPER than code bugs — likely:
  (a) Goal criteria too strict / not achievable with current design
  (b) Test strategy mismatch (needs k6/vitest, not E2E)
  (c) Spec bug (blueprint missed a requirement)
  (d) Cross-phase dependency (other phase's code broken)

Next actions — pick one based on diagnosis:

┌─────────────────────────────────────────────────────────────────────┐
│ Step 1 — INVESTIGATE (required before any next action):             │
│   cat ${PLANNING_DIR}/phases/{phase}/REVIEW-FEEDBACK.md                   │
│   cat ${PLANNING_DIR}/phases/{phase}/GOAL-COVERAGE-MATRIX.md              │
│   Identify: which goals failed, WHY (assertion / selector / infra)  │
└─────────────────────────────────────────────────────────────────────┘

Then choose based on what you found:

A) Code bugs you can fix manually (most common):
   # Fix code → commit → rerun test only, skip re-codegen
   /vg:test {phase} --regression-only

B) Test spec itself wrong (selector, wait, data setup):
   # Edit apps/web/e2e/generated/{spec}.ts manually
   # Or regenerate: rm apps/web/e2e/generated/{phase}-*.spec.ts
   /vg:test {phase} --skip-deploy    # re-codegen + run

C) Goal spec unrealistic / needs redesign:
   # Edit TEST-GOALS.md → loosen criteria or reclassify priority
   # Or move goal to future phase:
   #   Add entry to ${PLANNING_DIR}/KNOWN-ISSUES.json with target_phase
   /vg:test {phase} --regression-only

D) Goal needs non-E2E verification (perf, worker, cross-system):
   # Write dedicated test:
   #   Performance: apps/web/e2e/perf/{goal}.k6.js
   #   Worker:      apps/workers/src/__tests__/{goal}.test.ts
   #   Integration: apps/api/src/__tests__/{goal}.integration.test.ts
   # Mark goal SKIPPED in GOAL-COVERAGE-MATRIX.md with link to alt test
   /vg:accept {phase}    # proceed with documented limitation

E) Reset budget + retry (only if you fixed root cause):
   rm ${PHASE_DIR}/test-loop-state.json
   /vg:test {phase}      # fresh 3-iteration budget

F) Root cause is upstream (infra / prior phase broken):
   # Fix infra first, then:
   /vg:review {phase} --retry-failed     # verify root cause gone
   /vg:test {phase} --regression-only    # confirm goals unlocked

Don't do:
  ❌ /vg:build {phase} --gaps-only       (if code exists — check REVIEW-FEEDBACK)
  ❌ /vg:review {phase}                  (full re-review wastes tokens — use --retry-failed)
  ❌ Loop /vg:test again without changes (budget won't reset, same failures)
```

**Display during auto-loop (progress line per iteration):**
```
[Auto-escalate 1/3] MODERATE bug found → invoking /vg:review --retry-failed ...
[Auto-escalate 2/3] UNREACHABLE + code missing → /vg:build --gaps-only ...
[Auto-escalate 3/3] Still 2 goals failing → STOP. See FINAL GUIDANCE ↑
```

**Why budget = 3:**
- iteration 1: test fix
- iteration 2: review --retry-failed or build --gaps-only
- iteration 3: one final verification

More = user frustration (long wait), loop hides real problem.

Display:
```
5c Fix Loop:
  Minor fixes: {N} (resolved: {N})
  Moderate escalated: {N} → REVIEW-FEEDBACK.md
  Major escalated: {N} → REVIEW-FEEDBACK.md
  Iterations: {N}/2
  Goals improved: {before_pass}/{total} → {after_pass}/{total}
```
</step>

<step name="5c_flow" profile="web-fullstack,web-frontend-only">
## 5c-flow: MULTI-PAGE FLOW VERIFICATION (optional, fixes G8)

**Skip conditions:**
- `--skip-flow` flag set → skip
- `${PHASE_DIR}/FLOW-SPEC.md` does NOT exist:
  - **Check goal chains first** before skipping. Parse TEST-GOALS.md dependencies:
    ```bash
    # Count dependency chains >= 3 (same logic as blueprint 2b7)
    CHAIN_COUNT=$(${PYTHON_BIN} -c "
    import re, json, sys
    from pathlib import Path
    text = Path('${PHASE_DIR}/TEST-GOALS.md').read_text(encoding='utf-8')
    goals, cur = {}, None
    for line in text.splitlines():
        m = re.match(r'^## Goal (G-\d+)', line)
        if m: cur = m.group(1); goals[cur] = []
        elif cur:
            dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
            if dm and dm.group(1).strip().lower() not in ('none',''):
                goals[cur] = re.findall(r'G-\d+', dm.group(1))
    # BFS chain detection
    from collections import deque
    roots = [g for g,d in goals.items() if not d]
    chains = 0
    for r in roots:
        q = deque([(r, 1)])
        while q:
            node, depth = q.popleft()
            children = [g for g,d in goals.items() if node in d]
            for c in children:
                if depth + 1 >= 3: chains += 1
                q.append((c, depth + 1))
    print(chains)
    ")
    ```
  - If `CHAIN_COUNT > 0` → **block-resolver handoff** (v1.9.2 P4 — no bare A/B prompt):
    ```bash
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="test.5c-flow"
      BR_GATE_CONTEXT="FLOW-SPEC.md absent but ${CHAIN_COUNT} goal dependency chains (>=3) detected. Multi-page flows need continuity testing — without FLOW-SPEC, codegen cannot produce flow tests."
      BR_EVIDENCE=$(printf '{"chain_count":%d,"phase":"%s"}' "$CHAIN_COUNT" "$PHASE_NUMBER")
      BR_CANDIDATES='[{"id":"regen-flow-spec","cmd":"echo \"would re-run /vg:blueprint '"$PHASE_NUMBER"' --from=2b7 to auto-generate FLOW-SPEC.md — requires orchestrator\" && exit 1","confidence":0.4,"rationale":"Re-run blueprint sub-step 2b7 generates FLOW-SPEC from goal chains"}]'
      BR_RESULT=$(block_resolve "flow-spec-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      case "$BR_LEVEL" in
        L1) echo "✓ L1 resolved — FLOW-SPEC generated inline" >&2 ;;
        L2) echo "▸ L2 architect proposal — orchestrator invokes AskUserQuestion (L3) with proposal JSON" >&2
            echo "  Users option: /vg:blueprint ${PHASE_NUMBER} --from=2b7  (auto-gen flow spec)" >&2
            echo "                /vg:test ${PHASE_NUMBER} --skip-flow     (proceed without flow tests; debt logged)" >&2
            exit 2 ;;
        *)  echo "  Falling back to legacy warn — recommend /vg:blueprint ${PHASE_NUMBER} --from=2b7" >&2 ;;
      esac
    fi
    ```
  - If `CHAIN_COUNT == 0` → skip silently (no flows needed, phase is simple)

**Purpose:** Per-goal verify (5c-goal) tests each goal independently. Multi-page flows (A → B → C: login → create → edit → delete) need continuity verification that standalone goals miss — e.g., does data created in step 1 persist correctly through step 5?

**Invocation:** Use the `flow-runner` skill (already installed).

```
Read skill: flow-runner
Args:
  FLOW_SPEC      = "${PHASE_DIR}/FLOW-SPEC.md"
  PHASE          = "${PHASE}"
  CHECKPOINT_DIR = "${PHASE_DIR}/checkpoints"
  MODE           = "verify"   # not codegen — we want live execution

Flow-runner contract:
  - reads FLOW-SPEC.md flow definitions
  - claims Playwright MCP server (lock manager)
  - executes each flow end-to-end (condition-based waits, not sleep)
  - saves checkpoint after each step (resume-safe)
  - applies 4-rule deviation classification + 3-strike escalation
  - writes flow-results.json → one entry per flow with PASS/FAIL + evidence
```

**Result merging:**
```bash
FLOW_RESULTS="${PHASE_DIR}/flow-results.json"
if [ -f "$FLOW_RESULTS" ]; then
  FLOWS_PASSED=$(jq '.flows | map(select(.status == "passed")) | length' "$FLOW_RESULTS")
  FLOWS_FAILED=$(jq '.flows | map(select(.status == "failed")) | length' "$FLOW_RESULTS")
  FLOWS_TOTAL=$(jq '.flows | length' "$FLOW_RESULTS")

  # Flow failures default to MAJOR severity (fixes I3):
  #   - A multi-page state-machine break (login → create → edit → delete)
  #     is NEVER a minor bug. If step N depends on state from step N-1 and
  #     that chain breaks, the entire feature is effectively inoperable.
  #   - Single-page goal failure (5c-goal) may be minor (typo, CSS) — keep
  #     MODERATE/MINOR classification there.
  #   - flow-runner itself may downgrade to MINOR only if evidence shows
  #     the failure is cosmetic (e.g., wrong success-toast copy) AND no
  #     downstream step was affected. Default is MAJOR.
  # Escalate to REVIEW-FEEDBACK.md via 5c-fix same as goal failures.
fi
```

Display:
```
5c Multi-page Flow Verify:
  FLOW-SPEC.md: {present|absent}
  Flows executed: {FLOWS_TOTAL}
  Passed: {FLOWS_PASSED} | Failed: {FLOWS_FAILED}
  Checkpoints saved: ${PHASE_DIR}/checkpoints/
```

**Cross-flow failures feed back:** merge failed flows into the same classification pipeline as 5c-goal (MINOR/MODERATE/MAJOR) so 5c-fix and 5c-auto-escalate treat them uniformly.

</step>

<step name="5d_codegen" profile="web-fullstack,web-frontend-only">
## 5d: CODEGEN — Goal-based Test Generation

Generate Playwright test files from VERIFIED goals. Assertions come from TEST-GOALS success criteria, navigation paths come from RUNTIME-MAP.json observations.

**For each goal group, generate 1 .spec.ts file:**

Write to `${GENERATED_TESTS_DIR}/{phase}-goal-{group}.spec.ts`

**Pre-codegen Gate — Dynamic ID scan (HARD BLOCK — tightened 2026-04-17):**

Before generating tests, scan RUNTIME-MAP.json goal_sequences for dynamic ID selectors. Dynamic IDs cause flaky tests that rot on next data reset.

```bash
# Patterns that indicate dynamic IDs (must be replaced with role/text locators in RUNTIME-MAP before codegen)
DYN_ID_PATTERNS='#[a-zA-Z_-]+_[0-9]{3,}|#row-[a-z0-9]{6,}|data-id="[0-9]+|\[id\^=|\[data-id\^='

DYN_FOUND=$(${PYTHON_BIN} -c "
import json, re
rt = json.load(open('${PHASE_DIR}/RUNTIME-MAP.json', encoding='utf-8'))
patterns = re.compile(r'${DYN_ID_PATTERNS}')
hits = []
for goal_id, seq in rt.get('goal_sequences', {}).items():
    for i, step in enumerate(seq.get('steps', [])):
        sel = step.get('selector', '')
        if sel and patterns.search(sel):
            hits.append((goal_id, i, sel))
for h in hits:
    print(f'{h[0]}|step={h[1]}|{h[2]}')
" 2>/dev/null)

if [ -n "$DYN_FOUND" ]; then
  echo "⛔ Dynamic ID selectors found in RUNTIME-MAP.json goal_sequences:"
  echo "$DYN_FOUND" | sed 's/^/  /'
  echo ""
  echo "  Dynamic IDs break when data changes. Replace with role/text locators."
  echo "  Fix: /vg:review ${PHASE_NUMBER} --retry-failed  (re-record with stable selectors)"
  echo "  Override (NOT RECOMMENDED): /vg:test ${PHASE_NUMBER} --allow-dynamic-ids"
  if [[ ! "$ARGUMENTS" =~ --allow-dynamic-ids ]]; then
    # v1.9.2 P4 — block-resolver: try inline reclassification first (L1), architect L2 if stuck
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="test.codegen.dynamic-ids"
      BR_GATE_CONTEXT="Dynamic ID selectors in RUNTIME-MAP.json goal_sequences will produce flaky tests. Review must re-record using stable selectors (role/text). Alternatives: --retry-failed (re-record), --allow-dynamic-ids + ratguard (override with debt)."
      BR_EVIDENCE=$(printf '{"dyn_found":"%s"}' "$(echo "$DYN_FOUND" | head -c 800 | tr '\n' ';')")
      BR_CANDIDATES='[{"id":"retry-failed-rescan","cmd":"echo \"would re-trigger review --retry-failed to re-record selectors; requires orchestrator\" && exit 1","confidence":0.4,"rationale":"Re-scan often yields stable role-based locators if DOM updated"}]'
      BR_RESULT=$(block_resolve "dynamic-ids" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      case "$BR_LEVEL" in
        L1) echo "✓ L1 resolved — selectors re-recorded with stable locators" >&2 ;;
        L2) echo "▸ L2 architect proposal — orchestrator invokes AskUserQuestion (L3)" >&2; exit 2 ;;
        *)  exit 1 ;;
      esac
    else
      exit 1
    fi
  else
    # v1.9.0 T1: rationalization guard — dynamic IDs = flaky tests. Should rarely pass.
    RATGUARD_RESULT=$(rationalization_guard_check "dynamic-ids" \
      "Dynamic ID selectors (e.g. #user-42) break when data changes. Codegen with flaky selectors produces tests that fail intermittently and hide real bugs." \
      "found_selectors=${DYN_FOUND} user_arg=--allow-dynamic-ids")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "dynamic-ids" "--allow-dynamic-ids" "$PHASE_NUMBER" "test.codegen" "$DYN_FOUND"; then
      exit 1
    fi
    echo "⚠ --allow-dynamic-ids set — codegen will proceed with flaky selectors."
  fi
fi
```

**v1.14.0+ B.2 — Goal-status-aware codegen (tightened 2026-04-18):**

Trước khi sinh code, đọc `GOAL-COVERAGE-MATRIX.md` để phân nhánh theo trạng thái:

```bash
# Build status map: gid -> status (READY|DEFERRED|MANUAL|INFRA_PENDING|BLOCKED)
STATUS_JSON="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/goal-status.json"
mkdir -p "$(dirname "$STATUS_JSON")"
PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$STATUS_JSON" <<'PY'
import json, re, sys
matrix = open(sys.argv[1], encoding='utf-8').read() if sys.argv[1] else ""
status_map = {}
# Parse Goal Details table rows
m = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', matrix, re.M|re.S)
if m:
    body = m.group(1)
    for line in body.splitlines():
        gm = re.match(r'^\|\s*(G-[\w.-]+)\s*\|[^|]*\|[^|]*\|\s*(\w+)\s*\|', line)
        if gm:
            status_map[gm.group(1)] = gm.group(2)
json.dump(status_map, open(sys.argv[2], 'w', encoding='utf-8'), indent=2)
print(f"▸ Goal status map: {len(status_map)} goals → {sys.argv[2]}")
PY
```

**Branching (per goal, before generate):**

| Status | Action |
|---|---|
| `READY` | Sinh full spec happy path (logic existing bên dưới). |
| `MANUAL` | Sinh **skeleton** với `test.skip(...)` + comment "manual verify in UAT + verification_strategy: {strategy}". Có placeholder để user fill sau. |
| `DEFERRED` | **Skip entirely** — không tạo file .spec.ts (phase target chưa deploy). Log `[skip-deferred] {gid} depends_on_phase: {X}`. |
| `INFRA_PENDING` | Sinh skeleton `.skip()` với comment "requires infra {deps} — re-run --sandbox". |
| `BLOCKED` / `UNREACHABLE` | KHÔNG tới đây — review 100% gate đã chặn. Nếu gặp → log error, skip goal. |

**Skeleton template cho MANUAL / INFRA_PENDING:**

```typescript
// === AUTO-GENERATED SKELETON (MANUAL goal) — v1.14.0+ B.2 ===
// Goal: G-XX — {title}
// Status: MANUAL (verification_strategy: {strategy})
// Scope đã declare: tag yêu cầu user verify tay ở UAT.
// Không tự chạy trong regression — mở ở /vg:accept để user tick checklist.

import { test, expect } from '@playwright/test';

test.skip('MANUAL: {goal title}', async ({ page }) => {
  // USER FILL: Steps user cần thực hiện tay trong UAT.
  // Nếu sau này tìm được cách auto → update scope tag verification_strategy: automated + re-run codegen.
  //
  // Reference:
  //   - SPECS: {phase}/SPECS.md#{goal-id}
  //   - Context: {phase}/CONTEXT.md (decision tạo goal này)
  //   - RUNTIME-MAP.json goal_sequences[{goal-id}] (nếu có sequence đã record)
});
```

**Skeleton template cho INFRA_PENDING:**

```typescript
// === AUTO-GENERATED SKELETON (INFRA_PENDING) — v1.14.0+ B.2 ===
// Goal: G-XX — {title}
// Infra deps: {list}
// Không chạy local được (thiếu infra). Re-run /vg:test --sandbox để verify trên VPS.

import { test, expect } from '@playwright/test';

test.skip('INFRA_PENDING: {goal title} — requires {deps}', async ({ page }) => {
  // Generated skeleton. Un-skip + complete khi infra deploy xong.
});
```

**Skipping DEFERRED (narration only):**

```bash
if [ -f "$STATUS_JSON" ]; then
  DEFERRED_COUNT=$(${PYTHON_BIN} -c "
import json
d = json.load(open('$STATUS_JSON', encoding='utf-8'))
print(sum(1 for v in d.values() if v == 'DEFERRED'))
")
  [ "$DEFERRED_COUNT" -gt 0 ] && echo "▸ Codegen bỏ qua $DEFERRED_COUNT goal DEFERRED (chờ phase phụ thuộc ship)."
fi
```

**Codegen rules (READY goal path):**
1. **Credentials from env vars** — read from `process.env` (keys derived from config role names). Never hardcode emails/passwords/domains.
2. **Selectors from goal_sequences** — use exact selectors recorded during review discovery. Prefer role-based locators (getByRole > getByText > locator). Never guess selectors.
   **NEVER use dynamic IDs as selectors** (e.g., `data-id="site_9872"`, `#row-abc123`).
   These break when data changes. Prefer: `getByRole('row').first()`, `getByText('site name')`,
   or `nth(0)` index. If goal_sequence recorded a dynamic ID, the pre-codegen gate above BLOCKS execution — re-run /vg:review to re-record.
3. **Assertions from TEST-GOALS** — each `test()` block maps to a success criterion. Never invent assertions beyond what TEST-GOALS specifies.
4. **Steps from goal_sequences** — each `do` step becomes a Playwright action, each `assert` step becomes an `expect()`. Nearly 1:1 mapping.
5. **Web-first assertions** — use `expect(locator).toHaveText()`, `expect(locator).toBeVisible()` with auto-retry. Never use single-shot checks.
6. **Mutation 3-layer verify (tightened 2026-04-17)** — for every mutation step (POST/PUT/PATCH/DELETE), generated test MUST assert THREE layers:
   ```
   // Layer 1: Toast text
   await expect(page.getByRole('status')).toContainText(step.expected_toast);
   // Layer 2: API 2xx (not just called)
   const res = await page.waitForResponse(r => r.url().includes(step.endpoint));
   expect(res.status()).toBeLessThan(400);
   // Layer 3: No console errors since mutation
   const errs = await page.evaluate(() => window.__consoleErrors || []);
   expect(errs.length).toBe(0);
   ```
   Codegen that skips any layer = rejected at 5d-binding gate.

**Generated test structure (from goal_sequences — nearly 1:1):**
```
For each goal group:
  describe("{goal_id}: {goal_description}"):
    
    beforeEach:
      Login using env var credentials for required role
      Navigate to start_view via UI clicks (from views[start_view].arrive_via)
    
    test("{goal_description} — primary"):
      For each step in goal_sequences[goal_id].steps:
        IF step.do == "click":  → page.getByRole/getByText(step.label).click()
        IF step.do == "fill":   → page.locator(step.selector).fill(step.value)
        IF step.do == "select": → page.locator(step.selector).selectOption(step.value)
        IF step.do == "wait":   → page.waitForSelector/waitForLoadState(step.for)
        IF step.observe with network: → page.waitForResponse(r => r.url().includes(...) && r.status() === step.network[0].status)
        IF step.assert:         → expect(page.locator(...)).toHaveText/toBeVisible(...)
      
      // Console error check at end (expect 0 new errors)
      // Network response verification (status codes match step.network[])
      // Screenshot capture
    
    // PROBE TESTS — generated from goal_sequences[goal_id].probes[]
    For each probe in goal_sequences[goal_id].probes (if any):
      test("{goal_description} — probe:{probe.type}"):
        // Replay primary steps up to the form, then vary:
        IF probe.type == "edit":
          → Replay steps to open form in edit mode
          → Change probe.changed_fields to different valid values
          → Submit → expect same success behavior (or proper validation)
          → Verify: no console errors, API returns 2xx
        IF probe.type == "boundary":
          → Replay steps to open form
          → Fill boundary values (from probe.values_description)
          → Submit → expect either success or proper validation error (not crash)
          → Verify: no unhandled console errors
        IF probe.type == "repeat":
          → Replay exact same steps as primary
          → Submit → expect either success or proper duplicate error
          → Verify: no crash, no unhandled 500
    
    For FAILED goals: test captures the failure for regression tracking
    For PASSED goals: test locks in the working behavior + probe variations
```

**Env var naming convention:**
```
For each role in config.credentials[ENV]:
  {ROLE_UPPER}_EMAIL, {ROLE_UPPER}_PASSWORD, {ROLE_UPPER}_DOMAIN
  (role name uppercased becomes the env var prefix)
```

Display:
```
5d Codegen:
  Goal groups: {N}
  Files generated: {N}
  Tests generated: {N} (from {passed} passed + {failed} failed goals)
  Output: ${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts
```

### 5d-binding: Phase-end Goal-Test Binding Gate (STRICT by default)

After codegen, verify EVERY goal in TEST-GOALS.md is covered by at least one
test file under `${GENERATED_TESTS_DIR}/` OR committed task test files across
the phase. This is the final strict gate — goals unbound here = /vg:test FAILS.

Mode from `config.build_gates.goal_test_binding_phase_end` (default: strict).

```bash
GTB_MODE="${config.build_gates.goal_test_binding_phase_end:-strict}"
if [ "$GTB_MODE" != "off" ]; then
  # Use full phase commit range as the wave-tag proxy — scan all phase commits
  PHASE_FIRST_COMMIT=$(git log --format="%H" --reverse --grep="${PHASE_NUMBER}-" | head -1)
  if [ -n "$PHASE_FIRST_COMMIT" ]; then
    SCAN_TAG="${PHASE_FIRST_COMMIT}^"
  else
    SCAN_TAG="HEAD~200"  # fallback
  fi

  GTB_ARGS="--phase-dir ${PHASE_DIR} --wave-tag ${SCAN_TAG} --wave-number phase-end"
  [ "$GTB_MODE" = "warn" ] && GTB_ARGS="${GTB_ARGS} --lenient"

  if ! ${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS}; then
    echo "⛔ Phase-end goal-test binding FAILED."
    echo "   One or more goals claimed by plan tasks have no corresponding test."
    echo "   Codegen should have generated tests for every goal — check ${GENERATED_TESTS_DIR}/"

    # v1.9.1 R2+R4: block-resolver — try L1 re-codegen before falling through.
    # If L1 fails, L2 architect proposal (likely "create test harness sub-phase") surfaces to user.
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="test.5b-goal-test-binding"
      BR_GATE_CTX="Goal-test binding gate: plan tasks claim goals but no corresponding test file found. Codegen either skipped, deleted, or never ran for these goals."
      BR_EVIDENCE=$(printf '{"gate":"goal_test_binding_phase_end","generated_tests_dir":"%s","mode":"%s"}' "$GENERATED_TESTS_DIR" "$GTB_MODE")
      # L1 candidate: re-run codegen in isolation (skip deploy)
      BR_CANDIDATES='[{"id":"recodegen","cmd":"echo L1-SAFE: would invoke codegen-only rerun (${PYTHON_BIN} .claude/scripts/codegen.py --phase ${PHASE_NUMBER} --tests-only); skipping in resolver safe mode","confidence":0.6,"rationale":"codegen drift is the most common cause; cheap to retry"}]'
      BR_RESULT=$(block_resolve "goal-test-binding" "$BR_GATE_CTX" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LEVEL" = "L1" ]; then
        echo "✓ Block resolver L1 self-resolved — re-run verification"
        ${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS} || { VERDICT="FAILED"; FAIL_REASON="goal_test_binding_phase_end"; }
      elif [ "$BR_LEVEL" = "L2" ]; then
        block_resolve_l2_handoff "goal-test-binding" "$BR_RESULT" "$PHASE_DIR"
        VERDICT="FAILED"
        FAIL_REASON="goal_test_binding_phase_end_L2_proposal_pending"
      else
        block_resolve_l4_stuck "goal-test-binding" "L1 re-codegen failed, L2 architect unavailable"
        VERDICT="FAILED"
        FAIL_REASON="goal_test_binding_phase_end"
      fi
    else
      echo "   Options (fallback — resolver unavailable):"
      echo "     (a) Re-run: /vg:test ${PHASE_NUMBER} --skip-deploy  (re-codegen only)"
      echo "     (b) Manually add test file(s) citing missing goals, re-run /vg:test"
      echo "     (c) Set build_gates.goal_test_binding_phase_end=warn in vg.config.md (not recommended)"
      VERDICT="FAILED"
      FAIL_REASON="goal_test_binding_phase_end"
    fi
    # Fall through to 5e so regression still runs (diagnostic value)
  fi
fi
```
</step>

<step name="5c_mobile_flow" profile="mobile-*">
## 5c (mobile): GOAL FLOW via Maestro run-flow

Mobile equivalent of web smoke + goal + flow steps combined. Mobile doesn't
need the multi-step web smoke (no SPA route graph); each goal maps to a
single Maestro YAML flow that launches the app, performs the minimum
interactions, and captures assertions via `assertVisible` / `assertTrue`.

Pre-requisites:
- 5a_mobile_deploy succeeded (app installed on device / dist link live)
- `${GENERATED_TESTS_DIR}/mobile/<phase>/*.maestro.yaml` exist (from
  prior 5d_mobile_codegen run OR manually-authored flows in
  `config.mobile.e2e.flows_dir`)

```bash
WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
FLOWS_DIR=$(awk '/^mobile:/{m=1;next} m && /^  e2e:/{e=1;next}
                  e && /^  [a-z]/{e=0} e && /flows_dir:/{print $2;exit}' \
             .claude/vg.config.md | tr -d '"' | head -1)
FLOWS_DIR="${FLOWS_DIR:-${GENERATED_TESTS_DIR}/mobile}"

# Collect flows to run: either generated (codegen output) or pre-authored
FLOW_FILES=$(find "${REPO_ROOT}/${FLOWS_DIR}" -type f \( -name "*.maestro.yaml" -o -name "*.maestro.yml" \) 2>/dev/null | sort)
if [ -z "$FLOW_FILES" ]; then
  echo "⚠ No Maestro flows found under ${FLOWS_DIR}. Run 5d_mobile_codegen first."
  touch "${PHASE_DIR}/.step-markers/5c_mobile_flow.done"
  # Don't fail — codegen might be a no-op if goals are all UNREACHABLE
  exit 0
fi

# Run each flow per discoverable device (config.mobile.devices.{platform}.{name})
FAILED=0
TOTAL=0
for FLOW in $FLOW_FILES; do
  TOTAL=$((TOTAL+1))
  FLOW_NAME=$(basename "$FLOW" .maestro.yaml)
  echo "▶ Running Maestro flow: $FLOW_NAME"

  # Try each platform listed in target_platforms
  for PLATFORM in ios android; do
    # Skip platforms not in target_platforms
    grep -qE "target_platforms:.*${PLATFORM}" .claude/vg.config.md || continue

    DEVICE=$(awk -v plat="$PLATFORM" '
      /^mobile:/{m=1} m && /^    ios:/ && plat=="ios"{p=1;next}
      m && /^    android:/ && plat=="android"{p=1;next}
      p && /^    [a-z]/{p=0}
      p && /simulator_name:|emulator_name:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print; exit}
    ' .claude/vg.config.md | head -1)

    [ -z "$DEVICE" ] && { echo "  skip $PLATFORM — no device configured"; continue; }

    RESULT=$(${PYTHON_BIN} "$WRAPPER" --json run-flow --yaml "$FLOW" --device "$DEVICE")
    STATUS=$(echo "$RESULT" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin).get('status',''))")
    case "$STATUS" in
      ok)           echo "  ✓ $FLOW_NAME @ $PLATFORM ($DEVICE)" ;;
      tool_missing) echo "  · $FLOW_NAME @ $PLATFORM — maestro/adb missing, skipped" ;;
      *)
        FAILED=$((FAILED+1))
        echo "  ✗ $FLOW_NAME @ $PLATFORM ($STATUS)"
        ;;
    esac
    # Store result JSON for 5f security audit and 5e regression
    echo "$RESULT" > "${PHASE_DIR}/flow-${FLOW_NAME}-${PLATFORM}.json"
  done
done

echo ""
echo "5c Mobile Flow: ${TOTAL} flow(s), ${FAILED} failed"

if [ $FAILED -gt 0 ]; then
  # Non-fatal at this step — regression (5e) will re-run and block if still failing.
  # Reason: flow fail may be transient (emulator boot race, network).
  echo "⚠ Some flows failed — auto-fix loop handles via 5c_fix then 5e regression."
fi

touch "${PHASE_DIR}/.step-markers/5c_mobile_flow.done"
```
</step>

<step name="5d_deep_probe" profile="web-fullstack,web-frontend-only,web-backend-only,cli-tool,library">
## 5d-deep-probe: EDGE-CASE VARIANTS (v1.14.0+ B.3)

**Mục tiêu:** sinh 3 biến thể edge-case per goal READY, spawn Sonnet primary + Codex/Gemini/Haiku adversarial cross-check, escalate Opus khi disagree >30%.

**Config driver:** `test.deep_probe_enabled`, `test.deep_probe_model_primary`, `test.deep_probe_adversarial_chain`, `test.deep_probe_max_opus_escalations_per_phase`.

**Skip condition:** `test.deep_probe_enabled: false` hoặc không có goal READY → skip step.

### 5d-deep.1: Preflight — detect adversarial CLI

```bash
DEEP_PROBE_ENABLED=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_enabled\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'true')
except Exception:
    print('true')
")

if [ "$DEEP_PROBE_ENABLED" != "true" ]; then
  echo "ℹ Deep-probe disabled (config.test.deep_probe_enabled=false) — skip step 5d-deep."
else
  # Walk adversarial chain; pick first CLI available
  ADVERSARIAL_CLI=""
  for cli in codex gemini claude; do
    if command -v "$cli" >/dev/null 2>&1; then
      ADVERSARIAL_CLI="$cli"
      break
    fi
  done

  SKIP_IF_UNAVAIL=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_adversarial_skip_if_unavailable\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'false')
except Exception:
    print('false')
")

  if [ -z "$ADVERSARIAL_CLI" ]; then
    if [ "$SKIP_IF_UNAVAIL" = "true" ]; then
      echo "⚠ Không CLI nào trong adversarial chain (codex/gemini/claude) available — chỉ chạy primary."
      ADVERSARIAL_CLI="(none)"
    else
      echo "⛔ Adversarial chain hết CLI — config.skip_if_unavailable=false → BLOCK."
      echo "   Fix: cài codex/gemini/claude CLI, hoặc set deep_probe_adversarial_skip_if_unavailable: true."
      exit 1
    fi
  fi
  echo "▸ Deep-probe adversarial CLI chọn: ${ADVERSARIAL_CLI}"
fi
```

### 5d-deep.2: Spawn primary agent (Sonnet)

For mỗi goal READY (đọc từ `$STATUS_JSON` step 5d codegen):

```
Agent(subagent_type="general-purpose", model="sonnet",  # zero parent context, isolated
      name="deep-probe-{goal-id}"):
  prompt: |
    Generate 3 edge-case variants BEYOND happy path cho goal {goal-id}.

    Input:
    - SPECS.md, CONTEXT.md, API-CONTRACTS.md, GOAL-COVERAGE-MATRIX.md
    - Happy-path spec: apps/web/e2e/generated/{phase}/goal-{goal-id}.spec.ts

    Categories (auto-select theo surface):
    - `ui`:          boundary values, auth-negative (sai role), rapid-fire clicks
    - `api`:         malformed payload, rate-limit, injection (SQL/XSS)
    - `data`:        concurrent write, schema-drift, partition boundary
    - `time-driven`: just-before / just-after / exact-boundary timestamp

    Output: apps/web/e2e/generated/{phase}/goal-{goal-id}.deep.spec.ts
    Mỗi variant annotate:
    - `.variant('hard')` — MUST pass (real bug nếu fail)
    - `.variant('advisory')` — MAY fail (edge case uncertain, CI report not block)

    Reuse imports + helpers từ happy-path file khi có.
```

### 5d-deep.3: Adversarial cross-check

Sau primary generate → spawn adversarial agent (CLI chọn ở 5d-deep.1):

```bash
# Invoke adversarial CLI với cùng input + primary output + hỏi:
# 1. Có variant nào test scenario invalid-by-design không? → mark reject
# 2. Có variant `hard` nào thực ra là edge case không chắc? → demote `advisory`
# 3. Có category edge case nào primary miss? → suggest add
```

**Consensus rule:**
- Primary + adversarial đồng ý 100% → keep as-is.
- Disagree về 1-2 variants → adversarial's demote/reject applied.
- Disagree >30% variants → **escalate Opus** (nếu `deep_probe_escalate_to_opus_on_conflict: true` và budget `deep_probe_max_opus_escalations_per_phase` chưa hết).

### 5d-deep.4: Opus escalation (budget-guarded)

```bash
OPUS_BUDGET=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_max_opus_escalations_per_phase\s*:\s*(\d+)', c)
    print(m.group(1) if m else '2')
except Exception:
    print('2')
")

# Track escalation count trong .vg/phases/{phase}/.deep-probe-opus-count
OPUS_COUNT_FILE="${PHASE_DIR}/.deep-probe-opus-count"
OPUS_USED=$(cat "$OPUS_COUNT_FILE" 2>/dev/null || echo 0)

if [ "$OPUS_USED" -lt "$OPUS_BUDGET" ]; then
  # Spawn Opus với toàn bộ context (primary + adversarial + conflict detail)
  # Opus decides final verdict — write goal-{id}.deep.spec.ts với variants chuẩn
  echo "$((OPUS_USED + 1))" > "$OPUS_COUNT_FILE"
else
  echo "⚠ Budget Opus escalation hết ($OPUS_BUDGET/phase) — fallback: keep primary output, annotate uncertain variants `advisory`."
fi
```

### 5d-deep.5: Variant annotation semantics

Generated file có block format:

```typescript
// === Deep-probe variants for goal {goal-id} ===
// Primary: sonnet, Adversarial: ${ADVERSARIAL_CLI}, Escalated: ${opus_escalation_status}

import { test, expect } from '@playwright/test';

test.describe('goal-{goal-id}.deep', () => {
  test('variant hard: boundary max length', async ({ page }) => {
    // MUST pass; fail = real bug
    // ...
  });

  test('variant advisory: rapid-fire double submit', async ({ page }) => {
    // MAY fail (UX race); CI warns but does not block
    test.info().annotations.push({ type: 'variant', description: 'advisory' });
    // ...
  });
});
```

CI reader (step 18+) xử lý:
- variant `hard` fail → test exit 1 + gate block.
- variant `advisory` fail → warn only, vẫn pass phase.

### 5d-deep.6: Fallthrough

Nếu `DEEP_PROBE_ENABLED=false` hoặc goal READY = 0 → step 5d-deep.* bỏ qua, phase tiếp tục sang 5e_regression.

`touch "${PHASE_DIR}/.step-markers/5d_deep_probe.done"` dù skip hay chạy.
</step>

<step name="5d_mobile_codegen" profile="mobile-*">
## 5d (mobile): CODEGEN — Maestro YAML Generation

Mobile equivalent of `5d_codegen` (which generates Playwright .spec.ts).
Reads TEST-GOALS.md + RUNTIME-MAP.json and emits one Maestro YAML per
goal group. The flow templates minimize scope: launchApp → tap/input →
assertVisible → takeScreenshot.

Output path: `${GENERATED_TESTS_DIR}/mobile/<phase>/<G-XX>.maestro.yaml`

```bash
OUT_DIR="${GENERATED_TESTS_DIR}/mobile/${PHASE_NUMBER}"
mkdir -p "$OUT_DIR"

# Read goals + their runtime paths
GOALS=$(grep -oE 'G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | sort -u)
RUNTIME_MAP="${PHASE_DIR}/RUNTIME-MAP.json"

if [ ! -f "$RUNTIME_MAP" ]; then
  echo "⚠ RUNTIME-MAP.json missing — codegen needs discovery artifacts from /vg:review"
  touch "${PHASE_DIR}/.step-markers/5d_mobile_codegen.done"
  exit 0
fi

# Bundle id — from app.json or user-provided via MAESTRO_APP_ID
BUNDLE_ID=$(${PYTHON_BIN} -c "
import json,sys,pathlib
try:
    d = json.loads(pathlib.Path('app.json').read_text(encoding='utf-8'))
    e = d.get('expo') or d
    bid = (e.get('ios') or {}).get('bundleIdentifier') or (e.get('android') or {}).get('package')
    print(bid or '')
except Exception:
    print('')
")
BUNDLE_ID="${BUNDLE_ID:-${MAESTRO_APP_ID:-com.example.app}}"

GENERATED=0
for GID in $GOALS; do
  # Extract goal title + success_criteria text from TEST-GOALS.md
  GOAL_TEXT=$(awk -v g="$GID" '
    $0 ~ "## Goal "g":" || $0 ~ "^#* *"g":" { found=1; next }
    found && /^## Goal G-[0-9]+|^#+ G-[0-9]+:/ { exit }
    found { print }
  ' "${PHASE_DIR}/TEST-GOALS.md")

  [ -z "$GOAL_TEXT" ] && { echo "· skip $GID (no block in TEST-GOALS.md)"; continue; }

  # Pull goal-sequence steps from RUNTIME-MAP.json — these are tap/input events
  # captured during review. Mobile equivalent of web "goal_sequences[].steps[]".
  STEPS_YAML=$(${PYTHON_BIN} - <<PY
import json,pathlib,sys
try:
    rm = json.loads(pathlib.Path("${RUNTIME_MAP}").read_text(encoding='utf-8'))
except Exception:
    print("# RUNTIME-MAP missing or malformed"); sys.exit(0)

seq = rm.get("goal_sequences", {}).get("${GID}", {})
start_view = seq.get("start_view", "")
steps = seq.get("steps", [])
if not steps:
    print("# no steps recorded for ${GID} — manual flow author required")
else:
    for s in steps[:20]:  # cap at 20 steps per flow
        kind = s.get("action", "tap")
        target = s.get("target") or s.get("selector") or ""
        value = s.get("value", "")
        if kind in ("tap", "click"):
            print(f"- tapOn:")
            print(f"    text: \"{target}\"")
        elif kind in ("input", "type", "fill"):
            print(f"- tapOn:")
            print(f"    text: \"{target}\"")
            print(f"- inputText: \"{value}\"")
        elif kind == "assertVisible":
            print(f"- assertVisible: \"{target}\"")
        else:
            print(f"# unhandled action '{kind}' target='{target}'")
PY
)

  # Build the flow file
  cat > "${OUT_DIR}/${GID}.maestro.yaml" <<EOF
# Auto-generated by /vg:test 5d_mobile_codegen
# Goal: ${GID}
# Source: TEST-GOALS.md + RUNTIME-MAP.json goal_sequences.${GID}
# Regenerate: /vg:test ${PHASE_NUMBER} --skip-deploy

appId: ${BUNDLE_ID}
---
- launchApp

${STEPS_YAML}

- takeScreenshot: "${GID}-final"
EOF
  GENERATED=$((GENERATED+1))
  echo "✓ Generated ${OUT_DIR}/${GID}.maestro.yaml"
done

echo ""
echo "5d Mobile Codegen: ${GENERATED} flow(s) generated → ${OUT_DIR}/"

touch "${PHASE_DIR}/.step-markers/5d_mobile_codegen.done"
```

**Note on template quality:**
V1 emits a minimal happy-path template. Mutation probes (edit/boundary/
repeat) from `goal_sequences[].probes[]` are deferred to V2 — web already
handles these via Playwright test.each(); mobile equivalent requires more
care with state reset between probes (app restart costs ~5s on
simulator). For V1 ship, one flow per goal is enough regression coverage.
</step>

<step name="5e_regression">
## 5e: REGRESSION RUN

Run generated tests via CLI (not MCP):
```bash
run_on_target "cd ${PROJECT_PATH} && npx playwright test ${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts"
```

If playwright config for generated tests doesn't exist, create a minimal one at `${GENERATED_TESTS_DIR}/playwright.config.generated.ts` with env vars from config.

Result:
- All pass → PASS
- Failures → record in SANDBOX-TEST.md with failure details

On subsequent runs (`--regression-only`): just run generated tests. Fast, cheap, repeatable.

Display:
```
5e Regression:
  Tests: {passed}/{total}
  Duration: {time}
  Result: {PASS|FAIL}
```
</step>

<step name="5f_security_audit">
## 5f: SECURITY AUDIT

Two-tier check on phase-changed files.

### Tier 1: Built-in Security Grep (always, <10 sec)

Get changed files for this phase:
```bash
CHANGED_FILES=$(git diff --name-only HEAD~${COMMIT_COUNT} HEAD -- "${config.code_patterns.api_routes}" "${config.code_patterns.web_pages}" 2>/dev/null)
```

Security patterns (generic, not stack-specific):
```
1. Secrets scan — hardcoded credentials, API keys, tokens in source
2. Injection scan — unsanitized user input in queries/templates
3. XSS scan — raw HTML insertion patterns
4. Auth check — route handlers without auth middleware
```

### Tier 2: Deep Scan (optional, tool-dependent)

Fallback chain (use first available):
```
1. semgrep (if installed) → run on changed files
2. npm audit (if package.json exists) → dependency vulnerabilities
3. grep fallback → expanded pattern set
```

Result routing:
- CRITICAL (secrets, injection) → FAIL
- HIGH (auth bypass on sensitive routes) → FAIL
- MEDIUM → GAPS_FOUND
- LOW → logged only

### Tier 3: Contract-code verbatim verification (3 blocks)

The contract has 3 code blocks per endpoint (auth, schema, error). The executor was
instructed to copy them verbatim. Tier 3 verifies the copy actually happened.

```bash
COPY_MISMATCHES=0

# Extract auth middleware lines from contract Block 1
${PYTHON_BIN} -c "
import re
from pathlib import Path
text = Path('${PHASE_DIR}/API-CONTRACTS.md').read_text(encoding='utf-8')
# Find Block 1 auth lines (e.g., 'export const postSitesAuth = [requireAuth(), requireRole(\"publisher\")]')
for m in re.finditer(r'###\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)', text):
    method, path = m.groups()
    # Find next code block containing 'Auth' or 'auth' or 'requireRole'
    rest = text[m.end():m.end()+2000]
    auth_match = re.search(r'\`\`\`\w+\n(.*?requireRole.*?)\n', rest, re.DOTALL)
    if auth_match:
        # Extract the key line
        for line in auth_match.group(1).splitlines():
            if 'requireRole' in line or 'requireAuth' in line:
                print(f'{path}\t{line.strip()}')
                break
" 2>/dev/null > "${VG_TMP}/contract-auth-lines.txt"

# For each contract auth line, verify it exists in the actual route file
while IFS=$'\t' read -r ENDPOINT AUTH_LINE; do
  [ -z "$ENDPOINT" ] && continue
  ROUTE_FILE=$(grep -rl "${ENDPOINT}" ${config.code_patterns.api_routes} 2>/dev/null | head -1)
  [ -z "$ROUTE_FILE" ] && continue

  # Check if the exact auth line (or its key part) exists in route file
  KEY_PART=$(echo "$AUTH_LINE" | grep -oE "requireRole\(['\"][^'\"]+['\"]\)" || true)
  if [ -n "$KEY_PART" ]; then
    if ! grep -q "$KEY_PART" "$ROUTE_FILE" 2>/dev/null; then
      echo "  CRITICAL: ${ENDPOINT} — contract says '${KEY_PART}' but route file doesn't contain it"
      COPY_MISMATCHES=$((COPY_MISMATCHES + 1))
    fi
  fi
done < "${VG_TMP}/contract-auth-lines.txt"

# Same for error response shape — verify FE reads error.message not statusText
ERROR_SHAPE="${config.contract_format.error_response_shape:-{ error: { code: string, message: string } }}"
CHANGED_FE=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- "${config.code_patterns.web_pages}" 2>/dev/null)
if [ -n "$CHANGED_FE" ]; then
  # FE anti-pattern: toast.error(error.message) where error = AxiosError
  BAD_TOAST=$(echo "$CHANGED_FE" | xargs grep -l "toast.*error\.message\b\|toast.*err\.message\b" 2>/dev/null | \
    xargs grep -L "error\.response.*data.*error.*message\|\.data\.error\.message" 2>/dev/null | head -5)
  if [ -n "$BAD_TOAST" ]; then
    echo "  HIGH: FE files read error.message (AxiosError) instead of error.response.data.error.message:"
    echo "$BAD_TOAST" | sed 's/^/    /'
    COPY_MISMATCHES=$((COPY_MISMATCHES + 1))
  fi

  # FE nested path check: verify FE reads correct depth from API response
  # Extract top-level response field names from contracts
  ${PYTHON_BIN} -c "
import re
from pathlib import Path
text = Path('${PHASE_DIR}/API-CONTRACTS.md').read_text(encoding='utf-8')
# Find response schema field names
for m in re.finditer(r'Response = z\.object\(\{([^}]+)\}', text):
    fields = re.findall(r'(\w+):', m.group(1))
    for f in fields:
        print(f)
" 2>/dev/null | sort -u > "${VG_TMP}/contract-response-fields.txt"

  # Check FE files access response.data correctly (not response.data.data)
  if [ -s "${VG_TMP}/contract-response-fields.txt" ] && [ -n "$CHANGED_FE" ]; then
    DOUBLE_DATA=$(echo "$CHANGED_FE" | xargs grep -n "response\.data\.data\." 2>/dev/null | head -5)
    if [ -n "$DOUBLE_DATA" ]; then
      echo "  WARN: FE files access response.data.data (double nesting) — check if API wraps in data envelope:"
      echo "$DOUBLE_DATA" | sed 's/^/    /'
    fi
  fi
fi

if [ "$COPY_MISMATCHES" -gt 0 ]; then
  echo "  ⛔ ${COPY_MISMATCHES} contract-code mismatches — code doesn't match contract blocks"
fi
```

### Tier 4: Runtime auth smoke (if server running)

```bash
if [ -n "$BASE_URL" ]; then
  # Extract all endpoints from contract, test without token → expect 401/403
  NEG_FAILURES=0
  while IFS=$'\t' read -r ENDPOINT AUTH_LINE; do
    [ -z "$ENDPOINT" ] && continue
    STATUS=$(curl -sf -o /dev/null -w '%{http_code}' "${BASE_URL}${ENDPOINT}" 2>/dev/null)
    if [ "$STATUS" != "401" ] && [ "$STATUS" != "403" ] && [ "$STATUS" != "404" ]; then
      echo "  CRITICAL: ${ENDPOINT} no-token → ${STATUS} (expected 401/403)"
      NEG_FAILURES=$((NEG_FAILURES + 1))
    fi
  done < "${VG_TMP}/contract-auth-lines.txt"
fi
```

Display:
```
5f Security:
  Tier 1 grep: {findings} ({critical}/{high}/{medium}/{low})
  Tier 2 deep: {tool used|skipped}
  Tier 3 contract-code verify: {COPY_MISMATCHES} mismatches (auth role + error shape)
  Tier 4 runtime no-token: {NEG_FAILURES} open endpoints
  Result: {PASS|GAPS_FOUND|FAIL}
```
</step>

<step name="5f_mobile_security_audit" profile="mobile-*">
## 5f (mobile): SECURITY AUDIT

Mobile-specific grep-based scans. Complements the build-time Gate 8
(privacy manifest consistency) by looking at the ACTUAL compiled app
source — secrets, cleartext traffic config, weak crypto, insecure
storage. Cheap: runs in ≤10 seconds on typical RN project.

Each finding is classified CRITICAL / HIGH / MEDIUM / LOW. CRITICAL / HIGH
→ verdict FAIL. MEDIUM → verdict GAPS_FOUND. LOW → logged.

```bash
SEC_FINDINGS=()
SEC_DIR="${PHASE_DIR}/mobile-security"
mkdir -p "$SEC_DIR"

# --- Scan 1: Hardcoded API keys / secrets in bundle source ---
# Grep for common secret patterns in source (NOT .env files — those are gitignored
# but committed secrets indicate real leak).
echo "🔍 Scan 1: Hardcoded secrets in source..."
SECRET_HITS=$(grep -rEn \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'sk_live_[0-9a-zA-Z]{24,}' \
  -e 'sk_test_[0-9a-zA-Z]{24,}' \
  -e 'AIza[0-9A-Za-z_-]{35}' \
  -e 'xox[baprs]-[0-9a-zA-Z-]{10,}' \
  -e '-----BEGIN (RSA |DSA |EC )?PRIVATE KEY-----' \
  --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
  --include='*.swift' --include='*.kt' --include='*.java' --include='*.dart' \
  --include='*.m' --include='*.mm' \
  "${REPO_ROOT}" 2>/dev/null | grep -v node_modules | grep -v "Pods/" | head -20 || true)
if [ -n "$SECRET_HITS" ]; then
  echo "$SECRET_HITS" > "$SEC_DIR/hardcoded-secrets.txt"
  COUNT=$(echo "$SECRET_HITS" | wc -l)
  SEC_FINDINGS+=("CRITICAL|hardcoded_secrets|${COUNT} match(es) — see mobile-security/hardcoded-secrets.txt")
fi

# --- Scan 2: Cleartext traffic (iOS) ---
echo "🔍 Scan 2: iOS cleartext traffic (NSAllowsArbitraryLoads)..."
IOS_PLIST=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                  g && /^    permission_audit:/{p=1;next}
                  p && /ios_plist_path:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print;exit}' \
             .claude/vg.config.md | head -1)
if [ -n "$IOS_PLIST" ] && [ -f "$IOS_PLIST" ]; then
  # NSAppTransportSecurity.NSAllowsArbitraryLoads = true → insecure
  if grep -A1 "NSAllowsArbitraryLoads" "$IOS_PLIST" 2>/dev/null | grep -q "<true/>"; then
    SEC_FINDINGS+=("HIGH|ios_cleartext_traffic|NSAllowsArbitraryLoads=true in ${IOS_PLIST} — allows HTTP to any domain")
  fi
fi

# --- Scan 3: Cleartext traffic (Android) ---
echo "🔍 Scan 3: Android cleartext traffic (usesCleartextTraffic)..."
AND_MANIFEST=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    permission_audit:/{p=1;next}
                    p && /android_manifest_path:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print;exit}' \
              .claude/vg.config.md | head -1)
if [ -n "$AND_MANIFEST" ] && [ -f "$AND_MANIFEST" ]; then
  if grep -q 'android:usesCleartextTraffic="true"' "$AND_MANIFEST" 2>/dev/null; then
    SEC_FINDINGS+=("HIGH|android_cleartext_traffic|usesCleartextTraffic=\"true\" in ${AND_MANIFEST}")
  fi
  # Exported activities without permission
  EXPORTED=$(grep -nE 'android:exported="true"' "$AND_MANIFEST" 2>/dev/null | grep -v 'android:permission=' | head -5 || true)
  if [ -n "$EXPORTED" ]; then
    COUNT=$(echo "$EXPORTED" | wc -l)
    SEC_FINDINGS+=("MEDIUM|android_exported_unprotected|${COUNT} exported component(s) without permission guard")
  fi
fi

# --- Scan 4: Weak crypto (MD5 / SHA-1 used for security, not checksums) ---
echo "🔍 Scan 4: Weak crypto usage..."
WEAK=$(grep -rEn \
  -e 'CryptoJS\.(MD5|SHA1)' \
  -e 'CC_MD5\(|CC_SHA1\(' \
  -e 'MessageDigest\.getInstance\("MD5"\)' \
  -e 'MessageDigest\.getInstance\("SHA-?1"\)' \
  --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
  --include='*.swift' --include='*.kt' --include='*.java' \
  "${REPO_ROOT}" 2>/dev/null | grep -v node_modules | grep -v "Pods/" | head -10 || true)
if [ -n "$WEAK" ]; then
  echo "$WEAK" > "$SEC_DIR/weak-crypto.txt"
  COUNT=$(echo "$WEAK" | wc -l)
  SEC_FINDINGS+=("MEDIUM|weak_crypto|${COUNT} MD5/SHA-1 usage(s) — see mobile-security/weak-crypto.txt")
fi

# --- Scan 5: Insecure storage (plain AsyncStorage / UserDefaults / SharedPreferences for secrets) ---
echo "🔍 Scan 5: Insecure storage of tokens/credentials..."
INSECURE=$(grep -rEn \
  -e 'AsyncStorage\.setItem\([^,]*(token|password|secret|key|auth)' \
  -e 'UserDefaults.*set.*(token|password|secret|apiKey)' \
  -e 'SharedPreferences.*putString.*(token|password|secret|auth)' \
  --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
  --include='*.swift' --include='*.kt' \
  -i "${REPO_ROOT}" 2>/dev/null | grep -v node_modules | grep -v "Pods/" | head -10 || true)
if [ -n "$INSECURE" ]; then
  echo "$INSECURE" > "$SEC_DIR/insecure-storage.txt"
  COUNT=$(echo "$INSECURE" | wc -l)
  SEC_FINDINGS+=("MEDIUM|insecure_storage|${COUNT} credential-in-plain-storage hint(s) — consider EncryptedSharedPreferences / Keychain")
fi

# --- Scan 6: Debug-only code in release (TODO/FIXME/console.log in release-path files) ---
echo "🔍 Scan 6: Debug/console.log in production paths..."
CONSOLE=$(grep -rEn 'console\.(log|debug)' \
  --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
  "${REPO_ROOT}/apps" "${REPO_ROOT}/src" 2>/dev/null \
  | grep -v node_modules | grep -v __tests__ | grep -v '\.test\.\|\.spec\.' | head -5 || true)
if [ -n "$CONSOLE" ]; then
  COUNT=$(echo "$CONSOLE" | wc -l | tr -d ' ')
  SEC_FINDINGS+=("LOW|debug_logs|${COUNT}+ console.log call(s) in production paths")
fi

# --- Report ---
CRITICAL=$(printf '%s\n' "${SEC_FINDINGS[@]}" | grep -c '^CRITICAL' || echo 0)
HIGH=$(printf '%s\n' "${SEC_FINDINGS[@]}" | grep -c '^HIGH' || echo 0)
MEDIUM=$(printf '%s\n' "${SEC_FINDINGS[@]}" | grep -c '^MEDIUM' || echo 0)
LOW=$(printf '%s\n' "${SEC_FINDINGS[@]}" | grep -c '^LOW' || echo 0)

cat > "$SEC_DIR/report.md" <<EOF
# Mobile Security Audit — Phase ${PHASE_NUMBER}

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Summary
- Critical: $CRITICAL
- High:     $HIGH
- Medium:   $MEDIUM
- Low:      $LOW

## Findings
$(printf '%s\n' "${SEC_FINDINGS[@]}" | awk -F'|' '{printf "- **%s** [%s]: %s\n", $1, $2, $3}')

## Scan coverage
1. Hardcoded secrets (AWS keys, Stripe keys, Google API keys, private keys)
2. iOS cleartext traffic (NSAllowsArbitraryLoads)
3. Android cleartext traffic + exported components without permission
4. Weak crypto (MD5, SHA-1 used for security)
5. Insecure storage (AsyncStorage / UserDefaults / SharedPreferences for tokens)
6. Debug logs in production paths
EOF

echo ""
echo "5f Mobile Security Audit: C=$CRITICAL H=$HIGH M=$MEDIUM L=$LOW"
cat "$SEC_DIR/report.md" | tail -20

# Verdict:
# CRITICAL or HIGH → FAIL (set via test.md orchestrator variable)
# MEDIUM → GAPS_FOUND
# LOW → log only
if [ "$CRITICAL" -gt 0 ] || [ "$HIGH" -gt 0 ]; then
  echo "⛔ Mobile security: CRITICAL/HIGH findings — verdict = FAILED"
  # Signal to orchestrator via shared variable
  SECURITY_VERDICT="FAILED"
elif [ "$MEDIUM" -gt 0 ]; then
  SECURITY_VERDICT="GAPS_FOUND"
else
  SECURITY_VERDICT="PASSED"
fi

touch "${PHASE_DIR}/.step-markers/5f_mobile_security_audit.done"
```

**Scope limits (V2 deferred):**
- No deep semgrep / MobSF scan in V1 — grep-based is fast enough for
  common leaks. User can run `mobsf` separately on signed binary.
- No runtime network sniff (HTTP interception via mitmproxy). That
  requires device proxy setup — out of scope for automated gate.
- No Frida / root-detection analysis. Advanced anti-tamper is V2+.

Final action: `touch "${PHASE_DIR}/.step-markers/5f_mobile_security_audit.done"`
</step>

<step name="5g_performance_check" profile="web-fullstack,web-backend-only">
## 5g: PERFORMANCE CHECK (config.perf_budgets)

Read performance budgets from config. Skip entirely if `perf_budgets` section absent.

```bash
# Parse perf_budgets from config (all optional — skip if missing)
API_P95=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*api_response_p95_ms:\s*(\d+)', line)
    if m: print(m.group(1)); break
else: print('')
" 2>/dev/null)

PAGE_LOAD=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*page_load_s:\s*(\d+)', line)
    if m: print(m.group(1)); break
else: print('')
" 2>/dev/null)
```

### Check 1: API response time (if api_response_p95_ms set + ENV has running API)

```bash
if [ -n "$API_P95" ]; then
  PERF_FAILURES=0
  # Curl critical endpoints from GOAL-COVERAGE-MATRIX (top 5 by priority)
  ENDPOINTS=$(${PYTHON_BIN} -c "
import re
from pathlib import Path
contracts = Path('${PHASE_DIR}/API-CONTRACTS.md')
if contracts.exists():
    for m in re.finditer(r'(GET|POST|PUT|DELETE|PATCH)\s+(/api/\S+)', contracts.read_text(encoding='utf-8')):
        print(f'{m.group(1)} {m.group(2)}')
" 2>/dev/null | head -10)

  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    METHOD=$(echo "$ep" | cut -d' ' -f1)
    PATH_URL=$(echo "$ep" | cut -d' ' -f2)
    # Time the request (use first credential domain from config)
    DOMAIN=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*domain:\s*[\"'\'']*([^\"'\''#\s]+)', line)
    if m: print(m.group(1)); break
" 2>/dev/null)
    BASE_URL="${DOMAIN:-http://localhost:3000}"
    RESPONSE_MS=$(curl -sf -o /dev/null -w '%{time_total}' \
      -X "$METHOD" "${BASE_URL}${PATH_URL}" 2>/dev/null \
      | awk '{printf "%.0f", $1 * 1000}')

    if [ -n "$RESPONSE_MS" ] && [ "$RESPONSE_MS" -gt "$API_P95" ]; then
      echo "  ⚠ ${METHOD} ${PATH_URL}: ${RESPONSE_MS}ms > ${API_P95}ms budget"
      PERF_FAILURES=$((PERF_FAILURES + 1))
    fi
  done <<< "$ENDPOINTS"

  if [ "$PERF_FAILURES" -gt 0 ]; then
    echo "  Performance: ${PERF_FAILURES} endpoint(s) over p95 budget (${API_P95}ms)"
    PERF_RESULT="GAPS_FOUND"
  else
    echo "  Performance: all endpoints within ${API_P95}ms budget"
    PERF_RESULT="PASS"
  fi
else
  PERF_RESULT="SKIP"
fi
```

### Check 2: Page load time (if page_load_s set + web profile + browser available)

For web profiles with browser: measure initial page load for 3 critical routes.
Uses `time curl` as lightweight proxy (no real browser needed — saves tokens).

```bash
if [ -n "$PAGE_LOAD" ] && [[ "$PROFILE" =~ web ]]; then
  PAGE_LOAD_MS=$((PAGE_LOAD * 1000))
  # Check 3 pages: login, dashboard, first RUNTIME-MAP view
  PAGES=$(${PYTHON_BIN} -c "
import json
from pathlib import Path
rm = Path('${PHASE_DIR}/RUNTIME-MAP.json')
if rm.exists():
    d = json.load(rm.open(encoding='utf-8'))
    for v in list(d.get('views', {}).keys())[:3]:
        print(v)
" 2>/dev/null)

  while IFS= read -r page; do
    [ -z "$page" ] && continue
    LOAD_MS=$(curl -sf -o /dev/null -w '%{time_total}' \
      "${BASE_URL}${page}" 2>/dev/null \
      | awk '{printf "%.0f", $1 * 1000}')
    if [ -n "$LOAD_MS" ] && [ "$LOAD_MS" -gt "$PAGE_LOAD_MS" ]; then
      echo "  ⚠ ${page}: ${LOAD_MS}ms > ${PAGE_LOAD_MS}ms budget"
    fi
  done <<< "$PAGES"
fi
```

Display:
```
5g Performance:
  API p95 budget: ${API_P95}ms — ${PERF_RESULT}
  Page load budget: ${PAGE_LOAD}s — ${PAGE_PERF_RESULT:-SKIP}
```

### Check 3: Pre-prod static analysis (always, no running server needed)

```bash
STATIC_ISSUES=0

# 3a. Bundle size (if build output exists)
MAX_BUNDLE=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*max_bundle_kb:\s*(\d+)', line)
    if m: print(m.group(1)); break
else: print('')
" 2>/dev/null)

if [ -n "$MAX_BUNDLE" ]; then
  # Find build output (common patterns)
  for BUILD_DIR in dist .next/static apps/web/dist apps/web/.next/static; do
    if [ -d "$BUILD_DIR" ]; then
      BUNDLE_KB=$(du -sk "$BUILD_DIR" 2>/dev/null | cut -f1)
      if [ -n "$BUNDLE_KB" ] && [ "$BUNDLE_KB" -gt "$MAX_BUNDLE" ]; then
        echo "  ⚠ Bundle size: ${BUNDLE_KB}KB > ${MAX_BUNDLE}KB budget ($BUILD_DIR)"
        STATIC_ISSUES=$((STATIC_ISSUES + 1))
      else
        echo "  ✓ Bundle size: ${BUNDLE_KB}KB within ${MAX_BUNDLE}KB budget"
      fi
      break
    fi
  done
fi

# 3b. N+1 query patterns (grep for common anti-patterns in changed files)
CHANGED_SRC=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- '*.ts' '*.js' 2>/dev/null)
if [ -n "$CHANGED_SRC" ]; then
  # Pattern: await inside for/forEach loop (potential N+1)
  N1_HITS=$(echo "$CHANGED_SRC" | xargs grep -l "for.*await\|forEach.*await\|\.map.*await" 2>/dev/null | head -5)
  if [ -n "$N1_HITS" ]; then
    echo "  ⚠ Potential N+1 query patterns (await inside loop):"
    echo "$N1_HITS" | sed 's/^/    /'
    STATIC_ISSUES=$((STATIC_ISSUES + 1))
  fi

  # Pattern: missing .lean() on Mongoose/MongoDB queries (if applicable)
  LEAN_MISS=$(echo "$CHANGED_SRC" | xargs grep -l "\.find(\|\.findOne(" 2>/dev/null | \
    xargs grep -L "\.lean()\|\.toArray()" 2>/dev/null | head -5)
  if [ -n "$LEAN_MISS" ]; then
    echo "  ⚠ MongoDB queries without .lean()/.toArray() — may allocate excess memory:"
    echo "$LEAN_MISS" | sed 's/^/    /'
  fi
fi

# 3c. Large file imports (>50KB source files — suspicious)
LARGE_FILES=$(echo "$CHANGED_SRC" | while read f; do
  [ -f "$f" ] && SIZE=$(wc -c < "$f") && [ "$SIZE" -gt 51200 ] && echo "  $f ($(($SIZE/1024))KB)"
done)
if [ -n "$LARGE_FILES" ]; then
  echo "  ⚠ Large source files (>50KB) — consider splitting:"
  echo "$LARGE_FILES"
fi
```

Display:
```
5g Performance (pre-prod):
  API response: ${PERF_RESULT} (single-request baseline)
  Bundle size: ${BUNDLE_KB}KB / ${MAX_BUNDLE}KB budget
  Static analysis: ${STATIC_ISSUES} potential issues
  Note: Real p95 under load = production only
```

Performance failures → GAPS_FOUND (not FAIL — pre-prod is advisory). Production load test via `/vg:regression` or external tool.
</step>

<step name="write_report">
## Write SANDBOX-TEST.md

Write `${PHASE_DIR}/{num}-SANDBOX-TEST.md`:

```markdown
---
phase: "{phase}"
tested: "{ISO timestamp}"
status: "{PASSED | GAPS_FOUND | FAILED}"
deploy_sha: "{sha}"
environment: "{env}"
---

# Sandbox Test Report — Phase {phase}

## 5a Deploy
- SHA: {sha}
- Health: {OK|FAIL}

## 5b Runtime Contract Verify
- Endpoints: {N}/{total}
- Result: {PASS|BLOCK}

## 5c Smoke Check
- Views checked: 5
- Matches: {N}/5

## 5c Goal Verification
| Goal | Priority | Criteria | Passed | Failed | Status |
|------|----------|----------|--------|--------|--------|
(populated from goal verification — values from runtime)

### Goal Details
(per-goal breakdown with specific failures and screenshots)

### Fix Loop
- Minor fixes: {N}
- Escalated to review: {N}

### Feedback to Review
(if REVIEW-FEEDBACK.md was written — reference it here)

## 5d Codegen
- Files generated: {N}
- Tests generated: {N}

## 5e Regression
- Tests: {passed}/{total}

## 5f Security
- Tier 1: {findings}
- Tier 2: {tool|skipped}

## Verdict: {PASSED | GAPS_FOUND | FAILED}

Gate (weighted):
- Critical goals: {passed}/{total} (threshold: 100%)
- Important goals: {passed}/{total} (threshold: 80%)
- Nice-to-have goals: {passed}/{total} (threshold: 50%)
- Overall: {passed}/{total} ({percentage}%)
```

**Verdict COMPUTATION (HARD RULE — tightened 2026-04-17, no AI-written verdicts):**

Before writing SANDBOX-TEST.md, verdict MUST be computed from actual goal JSON results, NOT inferred by AI from context. Run this script and read `$VERDICT` from its output — do not write your own.

```bash
VERDICT_JSON=$(${PYTHON_BIN} - <<'PYEOF'
import json, re, sys, glob
from pathlib import Path
import os

phase_dir = os.environ.get('PHASE_DIR')
vg_tmp = os.environ.get('VG_TMP')

# 1. Read TEST-GOALS.md to get priority per goal
tg_path = next(Path(phase_dir).glob('*TEST-GOALS*.md'), None)
if not tg_path:
    print(json.dumps({"error": "TEST-GOALS.md missing", "verdict": "FAILED"}))
    sys.exit(1)

tg = tg_path.read_text(encoding='utf-8')
goal_priority = {}
# Parse: "## Goal G-XX: ..." followed by "**Priority:** critical|important|nice-to-have"
current = None
for line in tg.splitlines():
    m = re.match(r'^##\s*Goal\s+(G-\d+)', line)
    if m:
        current = m.group(1)
    mp = re.match(r'^\s*\*\*Priority:\*\*\s*(\w+)', line, re.I)
    if mp and current:
        goal_priority[current] = mp.group(1).lower()

# 2. Read per-goal result JSONs
results = {}
for rf in glob.glob(f"{vg_tmp}/goal-*-result.json"):
    try:
        r = json.load(open(rf, encoding='utf-8'))
        results[r['goal_id']] = r['status']  # PASSED|FAILED|UNREACHABLE
    except Exception:
        pass

# 3. Bucket by priority and compute
buckets = {'critical': {'pass': 0, 'total': 0},
           'important': {'pass': 0, 'total': 0},
           'nice-to-have': {'pass': 0, 'total': 0}}
for gid, prio in goal_priority.items():
    p = prio if prio in buckets else 'important'
    buckets[p]['total'] += 1
    if results.get(gid) == 'PASSED':
        buckets[p]['pass'] += 1

def pct(b):
    return 100.0 * b['pass'] / b['total'] if b['total'] > 0 else 100.0

crit_pct = pct(buckets['critical'])
imp_pct = pct(buckets['important'])
nice_pct = pct(buckets['nice-to-have'])

# 4. Apply thresholds
verdict = 'PASSED'
reasons = []
if crit_pct < 100.0:
    verdict = 'FAILED'
    reasons.append(f"critical {crit_pct:.0f}% < 100%")
elif imp_pct < 80.0:
    verdict = 'GAPS_FOUND'
    reasons.append(f"important {imp_pct:.0f}% < 80%")
elif nice_pct < 50.0:
    verdict = 'GAPS_FOUND'
    reasons.append(f"nice {nice_pct:.0f}% < 50%")

print(json.dumps({
    "verdict": verdict,
    "reasons": reasons,
    "buckets": buckets,
    "counts": {"critical_pct": crit_pct, "important_pct": imp_pct, "nice_pct": nice_pct}
}))
PYEOF
)

VERDICT=$(echo "$VERDICT_JSON" | ${PYTHON_BIN} -c "import json,sys; print(json.load(sys.stdin)['verdict'])")

# Persist computed verdict — AI writer MUST embed this value verbatim
echo "$VERDICT_JSON" > "${PHASE_DIR}/.verdict-computed.json"
echo "Computed verdict: $VERDICT"
```

**AI writer MUST copy $VERDICT into SANDBOX-TEST.md header and body. Do NOT re-evaluate; do NOT override. The JSON is the source of truth.**

Commit:
```bash
git add ${PHASE_DIR}/*-SANDBOX-TEST.md ${SCREENSHOTS_DIR}/ ${GENERATED_TESTS_DIR}/
git commit -m "test({phase}): goal verification — {verdict}, {passed}/{total} goals passed"
```
</step>

<step name="complete">
**⛔ Test artifact cleanup (tightened 2026-04-17 — dọn rác test run):**

Test runs sinh ra nhiều screenshot/html/json tạm không cần giữ lại sau khi SANDBOX-TEST.md đã ghi verdict + đã commit evidence chính thức. Dọn triệt để.

Phân loại **GIỮ** vs **XOÁ**:

| Loại | Path | Action |
|------|------|--------|
| Goal PASS/FAIL evidence | `${SCREENSHOTS_DIR}/{phase}-goal-*.png` | **GIỮ** (đã commit với SANDBOX-TEST.md) |
| Generated .spec.ts | `${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts` | **GIỮ** (commit vào phase) |
| Playwright test-results | `apps/*/test-results/`, `**/test-results/` | **XOÁ** (temp output) |
| Playwright report HTML | `playwright-report/`, `**/playwright-report/` | **XOÁ** |
| Root-leaked screenshots | `./*.png`, `./screenshot-*.png` | **XOÁ** (vi phạm BANNED location rule) |
| Probe temp screenshots | `${SCREENSHOTS_DIR}/*-probe-*-retry*.png` (số >1) | **XOÁ** (giữ retry=1 nếu có) |
| Goal result JSONs | `${VG_TMP}/goal-*-result.json` | **XOÁ** (đã compute verdict) |
| Baseline JSONs | `${VG_TMP}/goal-*-baseline.json` | **XOÁ** |
| MCP snapshot dumps | `**/.playwright-mcp/`, `./snapshot-*.yaml` | **XOÁ** |
| Debug videos | `**/videos/*.webm`, `**/traces/*.zip` | **XOÁ nếu test PASSED** (giữ khi FAILED để debug) |

```bash
echo "=== Test cleanup — removing transient artifacts ==="

# 1. Playwright default junk dirs
find . -type d \( -name "test-results" -o -name "playwright-report" -o -name ".playwright-mcp" \) \
  -not -path "./node_modules/*" -not -path "./.git/*" \
  -exec rm -rf {} + 2>/dev/null

# 2. Root-leaked screenshots (BANNED per project convention)
rm -f ./*.png ./screenshot-*.png ./snapshot-*.yaml 2>/dev/null

# 3. Probe retry dupes (keep retry=1, drop retry=2+)
if [ -d "${SCREENSHOTS_DIR}" ]; then
  find "${SCREENSHOTS_DIR}" -name "*-probe-*-retry[2-9]*.png" -delete 2>/dev/null
  find "${SCREENSHOTS_DIR}" -name "*-probe-*-retry[1-9][0-9]*.png" -delete 2>/dev/null
fi

# 4. VG_TMP artifacts (goal results already folded into .verdict-computed.json)
rm -f "${VG_TMP}"/goal-*-result.json 2>/dev/null
rm -f "${VG_TMP}"/goal-*-baseline.json 2>/dev/null
rm -f "${VG_TMP}"/vg-crossai-${PHASE_NUMBER}-*.md 2>/dev/null

# 5. Videos / traces — keep ONLY if test FAILED (for debug), else drop
if [ "$VERDICT" = "PASSED" ] || [ "$VERDICT" = "GAPS_FOUND" ]; then
  find . -type f \( -name "*.webm" -o -name "trace.zip" \) \
    -not -path "./node_modules/*" -not -path "./.git/*" \
    -delete 2>/dev/null
else
  echo "Test verdict = $VERDICT — keeping videos/traces for debug"
fi

# 6. Compute cleanup size
FREED=$(du -sh "${PHASE_DIR}/.test-cleanup-prev-size" 2>/dev/null | awk '{print $1}')
echo "Test cleanup complete. Evidence preserved: SANDBOX-TEST.md, goal-*.png, generated *.spec.ts"
```

**Update PIPELINE-STATE.json + ROADMAP.md:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'tested'; s['pipeline_step'] = 'test-complete'
s['test_verdict'] = '${VERDICT}'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# VG-native ROADMAP update (grep + sed)
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* tested/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```

Display:
```
Test complete for Phase {N}.
  Deploy: {OK}
  Contract (runtime): {PASS}
  Smoke check: {N}/5 match
  Goals: {passed}/{total} (critical: {N}/{N}, important: {N}/{N})
  Fix loop: {minor_fixed} minor fixed, {escalated} escalated to review
  Regression: {passed}/{total} generated tests
  Security: {verdict}
  Verdict: {PASSED | GAPS_FOUND | FAILED}
  Next: /vg:accept {phase}
```
</step>

</process>

<success_criteria>
- Deploy successful, services healthy
- Runtime contract verify passed (curl + jq)
- Smoke check confirms RUNTIME-MAP accuracy
- Goals verified against known paths from RUNTIME-MAP.json
- MINOR fixes applied (if any), MODERATE/MAJOR escalated to REVIEW-FEEDBACK.md
- Codegen produced .spec.ts per goal group (assertions from TEST-GOALS, paths from RUNTIME-MAP)
- Regression tests pass
- Security audit completed (tier 1 always, tier 2 if available)
- SANDBOX-TEST.md with weighted goal-based verdict
</success_criteria>
