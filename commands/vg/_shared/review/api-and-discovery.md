<step name="phase2a_api_contract_probe" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2a.5: API CONTRACT PROBE (curl, no browser)

**Mandatory before browser discovery for web feature phases.**

Purpose:
- prove the current run touched the live API surface before any browser scan
- fail fast on broken/stale backend routes instead of hiding the problem behind discovery noise
- create a fresh artifact that runtime_contract can enforce even on older pinned phases
- verify API-DOCS.md fully covers API-CONTRACTS.md so discovery/test use the built API reference, not stale prose

**Scope:** low-cost readiness gate only. This is NOT the full `/vg:test` runtime contract verification and NOT a project-specific mutation batch. Mutating endpoints are probed safely (OPTIONS / existence check), not executed for side effects.

```bash
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔎 Phase 2a.5 — API contract probe"
echo "   Curl API contracts trước browser discovery"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator step-active phase2a_api_contract_probe >/dev/null 2>&1 || true

API_PROBE_OUT="${PHASE_DIR}/api-contract-precheck.txt"
API_DOCS_CHECK_OUT="${PHASE_DIR}/api-docs-check.txt"
VG_SCRIPT_ROOT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}"
[ -d "$VG_SCRIPT_ROOT" ] || VG_SCRIPT_ROOT="${REPO_ROOT:-.}/scripts"
PROBE_SCRIPT="${VG_SCRIPT_ROOT}/review-api-contract-probe.py"
INTERFACE_CHECK_OUT="${PHASE_DIR}/.tmp/interface-standards-review.json"

# v4.0.x Item 3 (Codex deferred) — proof-artifact fallback.
# Build close (run_complete) already produces .contract-runtime-report.json
# when verify-contract-runtime gate passed. If that proof is fresh for THIS
# run (creator_run_id check via evidence-manifest), skip the live runtime probe —
# same evidence, cheaper. Falls back to fresh probe when proof missing or stale.
PROOF_ARTIFACT="${PHASE_DIR}/.contract-runtime-report.json"
PROOF_FRESH="false"
if [ -f "$PROOF_ARTIFACT" ]; then
  FRESHNESS_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-artifact-freshness.py"
  [ -f "$FRESHNESS_VAL" ] || FRESHNESS_VAL="${REPO_ROOT}/scripts/validators/verify-artifact-freshness.py"
  if [ -f "$FRESHNESS_VAL" ]; then
    ${PYTHON_BIN:-python3} "$FRESHNESS_VAL" \
      --path "$PROOF_ARTIFACT" \
      --producer "vg:build/12_run_complete/verify-contract-runtime" \
      --quiet 2>/dev/null && PROOF_FRESH="true"
  fi
fi

# C8 Batch 2: proof reuse only skips live probe — interface + api-docs still run
SKIP_LIVE_PROBE=false
if [ "$PROOF_FRESH" = "true" ]; then
  echo "phase2a: reusing fresh contract-runtime proof from build close (skip live probe only)"
  cp "$PROOF_ARTIFACT" "${PHASE_DIR}/.api-contract-probe.json"
  SKIP_LIVE_PROBE=true
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "review.phase2a_proof_reused" \
    --payload "{\"phase\":\"${PHASE_NUMBER:-${PHASE_ARG}}\",\"scope\":\"live_probe_only\"}" \
    >/dev/null 2>&1 || true
fi

if [ "$SKIP_LIVE_PROBE" != "true" ]; then
  # Fall through to existing fresh-probe path (review-api-contract-probe.py)
  echo "phase2a: no fresh proof artifact, running fresh runtime probe"

  if [ ! -f "$PROBE_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event "review.api_precheck_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_helper\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — missing helper: $PROBE_SCRIPT",
  "fix_hint": "Ensure review-api-contract-probe.py exists in ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/ or scripts/"
}
JSON
    blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi

  # Resolve base URL from the same canonical source used by Phase 0.5 preflight.
  API_PROBE_BASE=$("${PYTHON_BIN:-python3}" -c "
import re, sys
path = '${PHASE_DIR}/ENV-CONTRACT.md'
try:
    text = open(path, encoding='utf-8').read()
except OSError:
    sys.exit(0)
m = re.search(r'^target:\\s*\\n((?:[ \\t].*\\n)+)', text, re.MULTILINE)
if m:
    body = m.group(1)
    bm = re.search(r'^\\s*base_url:\\s*[\"\\']?([^\"\\'\\s#]+)', body, re.MULTILINE)
    if bm:
        print(bm.group(1))
" 2>/dev/null)
  [ -z "$API_PROBE_BASE" ] && API_PROBE_BASE="${VG_BASE_URL:-}"

  if [ -z "$API_PROBE_BASE" ]; then
    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event "review.api_precheck_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_base_url\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — no base_url found in ENV-CONTRACT.md and VG_BASE_URL is empty",
  "fix_hint": "Set target.base_url in ENV-CONTRACT.md or export VG_BASE_URL"
}
JSON
    blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi

  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event "review.api_precheck_started" \
    --payload "$(printf '{"phase":"%s","base_url":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}")" >/dev/null 2>&1 || true

  PROBE_CMD=("${PYTHON_BIN:-python3}" "$PROBE_SCRIPT"
    --contracts "${PHASE_DIR}/API-CONTRACTS.md"
    --base-url "$API_PROBE_BASE"
    --out "$API_PROBE_OUT")

  # Optional auth token from deploy/auth bootstrap. If absent, 401/403 still count
  # as route-exists evidence for auth-protected endpoints.
  if [ -n "${AUTH_TOKEN:-}" ]; then
    PROBE_CMD+=(--header "Authorization: Bearer ${AUTH_TOKEN}")
  fi

  "${PROBE_CMD[@]}"
  API_PROBE_RC=$?
  cat "$API_PROBE_OUT"

  if [ "$API_PROBE_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event "review.api_precheck_blocked" \
      --payload "$(printf '{"phase":"%s","base_url":"%s","rc":%s}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "${API_PROBE_RC}")" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe failed — browser discovery is not allowed to start on stale/broken API surface",
  "fix_hint": "Fix the API surface issues found in api-contract-precheck.txt before continuing review"
}
JSON
    blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi

  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
    --path "${PHASE_DIR}/api-contract-precheck.txt" \
    --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,.claude/vg.config.md" \
    --producer "vg:review/phase2a_api_contract_probe"
  MANIFEST_RC=$?
  if [ "$MANIFEST_RC" -ne 0 ]; then
    echo "⛔ API contract probe wrote report but failed to bind evidence to current run." >&2
    exit 1
  fi

  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event "review.api_precheck_completed" \
    --payload "$(printf '{"phase":"%s","base_url":"%s","artifact":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "api-contract-precheck.txt")" >/dev/null 2>&1 || true
fi  # end SKIP_LIVE_PROBE gate — live probe only

# C8: interface-standards + api-docs coverage ALWAYS run, regardless of proof status
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
INTERFACE_VAL="${VG_SCRIPT_ROOT}/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_VAL" ]; then
  "${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    > "$INTERFACE_CHECK_OUT" 2>&1
  INTERFACE_RC=$?
  cat "$INTERFACE_CHECK_OUT"
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ Interface standards gate failed — review cannot continue with undefined API/FE error semantics." >&2
    DIAG_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.interface_standards" \
        --phase-dir "$PHASE_DIR" \
        --input "$INTERFACE_CHECK_OUT" \
        --out-md "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" 2>/dev/null || true
    fi
    exit 1
  fi
else
  echo "⛔ Interface standards validator missing: $INTERFACE_VAL" >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-api-docs-coverage.py \
  --phase "${PHASE_NUMBER}" \
  > "${API_DOCS_CHECK_OUT}" 2>&1
API_DOCS_RC=$?
cat "${API_DOCS_CHECK_OUT}"
if [ "$API_DOCS_RC" -ne 0 ]; then
  echo "⛔ API docs coverage failed — browser discovery is not allowed to continue with incomplete API-DOCS.md." >&2
  DIAG_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.api_docs_contract_coverage" \
      --phase-dir "$PHASE_DIR" \
      --input "$API_DOCS_CHECK_OUT" \
      --out-md "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" 2>/dev/null || true
  fi
  exit 1
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
  --path "${PHASE_DIR}/api-docs-check.txt" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/API-DOCS.md,.claude/vg.config.md" \
  --producer "vg:review/phase2a_api_contract_probe"
API_DOCS_MANIFEST_RC=$?
if [ "$API_DOCS_MANIFEST_RC" -ne 0 ]; then
  echo "⛔ API docs check wrote report but failed to bind evidence to current run." >&2
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2a_api_contract_probe" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2a_api_contract_probe.done"
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator mark-step review phase2a_api_contract_probe 2>/dev/null || true
```

</step>

<step name="phase2_browser_discovery" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2: BROWSER DISCOVERY (MCP Playwright — organic)

**🎬 Live narration protocol (tightened 2026-04-17 — user theo dõi flow):**

Orchestrator PHẢI in dòng tiếng người BEFORE mỗi sub-phase + BEFORE mỗi view/goal đang xử lý. Khác test.md: review chạy parallel nhiều Haiku, narration ở orchestrator level không cần per-step.

```bash
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator step-active phase2_browser_discovery >/dev/null 2>&1 || true
narrate_phase() {
  # $1=phase_name, $2=intent tiếng Việt
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "🔎 $1"
  echo "   $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

narrate_view_scan() {
  # $1=view_url, $2=idx, $3=total, $4=roles, $5=element_count
  echo "  [${2}/${3}] 📄 Đang scan: ${1}  (role: ${4}, ~${5} elements)"
}

narrate_view_done() {
  # $1=view_url, $2=status, $3=issues_count, $4=duration_s
  case "$2" in
    ok)      echo "       ✓ Scan xong — ${3} issues phát hiện (${4}s)" ;;
    partial) echo "       ⚠ Scan 1 phần — ${3} issues (${4}s)" ;;
    fail)    echo "       ❌ Scan lỗi — xem ${PHASE_DIR}/scan-*.json (per-view atomic artifacts)" ;;
  esac
}

narrate_goal_flow() {
  # $1=gid, $2=title, $3=idx, $4=total
  echo ""
  echo "  ▶ Flow [${3}/${4}] ${1}: ${2}"
}

narrate_goal_flow_step() {
  # $1=n, $2=total, $3=action_vn, $4=target
  echo "      ${1}/${2} → ${3} ${4}"
}

narrate_goal_flow_end() {
  # $1=gid, $2=status (passed|failed|blocked), $3=steps_captured, $4=reason
  case "$2" in
    passed)  echo "      ✅ Flow ${1} ghi ${3} bước, ready for /vg:test" ;;
    failed)  echo "      ❌ Flow ${1} fail — ${4}" ;;
    blocked) echo "      ⚠ Flow ${1} blocked — ${4}" ;;
  esac
}
```

Ví dụ user thấy khi `/vg:review` chạy:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2a — Deploy + preflight
   Triển khai code lên sandbox, kiểm tra health + seed data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Deploy OK (sha abc1234)
  ✓ Health: https://sandbox.example.com/health → 200
  ✓ Seed: 12 sites, 48 campaigns loaded

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-1 — Navigator (Haiku)
   Login, đọc sidebar, liệt kê tất cả views
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Phát hiện 14 views: /sites, /campaigns, /reports, /settings, ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-2 — Parallel scanners (8 Haiku agents)
   Mỗi agent scan 1 view: modals, forms, interactions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1/14] 📄 Đang scan: /sites  (role: publisher, ~32 elements)
         ✓ Scan xong — 2 issues phát hiện (12s)
  [2/14] 📄 Đang scan: /campaigns  (role: advertiser, ~48 elements)
         ✓ Scan xong — 0 issues (8s)
  [3/14] 📄 Đang scan: /reports  (role: admin, ~15 elements)
         ⚠ Scan 1 phần — 3 issues (14s)
  ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-3 — Goal sequence recording
   Ghi lại chuỗi thao tác cho từng business goal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ▶ Flow [1/8] G-01: Tạo site mới với domain + brand safety
      1/5 → 📍 Mở /sites
      2/5 → 👆 Bấm "New Site"
      3/5 → ⌨️  Điền domain
      4/5 → 🔽 Chọn category
      5/5 → ✓ Xác nhận toast "Site created"
      ✅ Flow G-01 ghi 5 bước, ready for /vg:test

  ▶ Flow [2/8] G-02: Edit site floor price
      1/4 → ...
      ❌ Flow G-02 fail — button "Edit" không tìm thấy trên row

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 3 — Fix loop (iteration 1/5)
   Sửa các bug MINOR, re-verify affected views
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Fixed: /reports missing empty-state (1 file changed)
  ✓ Re-scan /reports: 0 issues
  ⚠ 2 MAJOR issues escalated to REVIEW-FEEDBACK.md
```

**Rule:** narrator gọi ở các điểm sau trong phase 2:
- Trước 2a deploy → `narrate_phase "Phase 2a — Deploy" "Triển khai + health"`
- Trước 2b-1 navigator → `narrate_phase "Phase 2b-1 — Navigator" "Login, đọc sidebar..."`
- Sau navigator → in `Phát hiện N views: ...`
- Trước 2b-2 spawn → `narrate_phase "Phase 2b-2 — Parallel scanners"` + `Spawning N Haiku agents...`
- Khi mỗi Haiku scan xong (poll scan-*.json) → `narrate_view_scan` + `narrate_view_done`
- Trước goal sequence recording → `narrate_phase "Phase 2b-3 — Goal flows" "Ghi chuỗi thao tác..."`
- Mỗi goal → `narrate_goal_flow` + step loop + `narrate_goal_flow_end`
- Trước Phase 3 fix → `narrate_phase "Phase 3 — Fix loop" "Iteration {i}/3..."`

**If --skip-discovery, skip to Phase 4.**
**If --evaluate-only, skip to Phase 2b-3 (collect + merge scan results) → Phase 3 → Phase 4.**
  Validate: ${PHASE_DIR}/nav-discovery.json AND at least 1 scan-*.json must exist.
  Missing → BLOCK: "Run discovery first: `$vg-review {phase} --discovery-only` in Codex/Gemini."

**If --retry-failed:**
  Validate: ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md AND ${PHASE_DIR}/RUNTIME-MAP.json exist.
  Missing → BLOCK: "Run `/vg:review {phase}` first to generate initial artifacts."

  Parse GOAL-COVERAGE-MATRIX.md → collect all goals where status NOT IN (READY, INFRA_PENDING, DEFERRED, MANUAL).
  This includes: BLOCKED, UNREACHABLE, FAILED, PARTIAL, NOT_SCANNED, **and SUSPECTED** (v2.46-wave3.2 — matrix=READY but no submit/2xx evidence; flagged by `verify-matrix-staleness.py` at step 0_parse_and_validate and folded in here).
  If none found → print "All goals already READY. Nothing to retry." → skip to Phase 4.

  Parse RUNTIME-MAP.json → for each failed goal_id:
    start_view = goal_sequences[goal_id].start_view
  RETRY_VIEWS[] = unique(all start_views), with roles from RUNTIME-MAP views[start_view].role

  Print: "Retry mode: {N} failed/suspected goals → {M} views to re-scan: {RETRY_VIEWS[]}"

  Skip Phase 1 (code scan). Skip 2b-0 (seed). Skip 2b-1 (navigator — reuse existing nav-discovery.json).
  Go directly to 2b-2 using RETRY_VIEWS[] as view_assignments (NOT view-assignments.json).

**If --re-scan-goals=G-XX,G-YY,G-ZZ (v2.46-wave3.2):**
  Validate: ${PHASE_DIR}/RUNTIME-MAP.json exists (matrix not required — bypasses status filter).
  Missing → BLOCK: "Run `/vg:review {phase}` first to generate RUNTIME-MAP.json."

  Each goal ID validated already at step 0_parse_and_validate (unknown IDs → exit 1 there).

  Parse RUNTIME-MAP.json → for each goal_id in $RE_SCAN_GOALS:
    start_view = goal_sequences[goal_id].start_view
  RETRY_VIEWS[] = unique(all start_views).

  Print: "Re-scan mode: {N} explicit goals → {M} views: {RETRY_VIEWS[]}"

  Skip Phase 1 + 2b-0 + 2b-1. Go directly to 2b-2 using RETRY_VIEWS[].
  Marker: write `${PHASE_DIR}/.re-scan-goals.txt` with the list (consumed by 2b-3 to scope sequence recording to just these goals).

**If --dogfood (v2.46-wave3.2):**
  Validate: ${PHASE_DIR}/TEST-GOALS.md AND ${PHASE_DIR}/RUNTIME-MAP.json exist.

  Parse TEST-GOALS.md → all goals with non-empty `**Mutation evidence:**` field (see verify-matrix-staleness.py `parse_goals` for parser).
  RE_SCAN_GOALS := comma-join(those goal_ids), then proceed exactly as `--re-scan-goals` branch above.

  Print: "Dogfood mode: re-scanning ALL {N} mutation goals (regardless of matrix status)."

### 2a: Deploy + Environment Prep

Deploy to target environment:
```
1. Record SHAs (local + target)
2. Build + restart on target
3. Health check → if fail → PRE-FLIGHT BLOCK (see below)
4. (v1.14.0+) Infra auto-start — nếu review.try_infra_start=true AND config có infra_start declared → chạy
5. DB seed (if configured): run_on_target "${config.environments[ENV].seed_command}"
   (skip if seed_command not in config — portable)
6. Auth bootstrap (if configured):
   For each role in config.credentials[ENV]:
     Run config.environments[ENV].auth_command with role credentials
     Save response token for API checks below
   (skip if auth_command not in config — MCP login handles auth instead)
```

Read `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/env-commands.md` — deploy(env) + preflight(env).

### 2a-infra: Tự động khởi động hạ tầng (v1.14.0+)

**Triết lý:** Review hiện skip `INFRA_PENDING` goals (ClickHouse/Kafka/Pixel không chạy). Cổng 100% không cho phép skip — review phải tự khởi động hạ tầng để goals verify được.

```bash
# Gate 1: config knob enabled?
TRY_INFRA_START=$(yq '.review.try_infra_start // true' .claude/vg.config.md 2>/dev/null)
if [ "$TRY_INFRA_START" != "true" ]; then
  echo "ℹ review.try_infra_start=false — bỏ qua bước khởi động hạ tầng"
else
  # Gate 2: env có declare infra_start không?
  INFRA_START=$(yq ".environments.${ENV}.infra_start // \"\"" .claude/vg.config.md 2>/dev/null)
  INFRA_STOP=$(yq  ".environments.${ENV}.infra_stop  // \"\"" .claude/vg.config.md 2>/dev/null)
  INFRA_STATUS=$(yq ".environments.${ENV}.infra_status // \"\"" .claude/vg.config.md 2>/dev/null)

  if [ -z "$INFRA_START" ]; then
    echo "ℹ Env '${ENV}' không declare infra_start — bỏ qua (infra không do review quản lý)"
  else
    # Gate 3: hạ tầng đã chạy sẵn chưa? (idempotent check)
    ALREADY_RUNNING=false
    if [ -n "$INFRA_STATUS" ]; then
      if eval "$INFRA_STATUS" 2>/dev/null | grep -qiE "running|up|ok|online"; then
        ALREADY_RUNNING=true
        echo "✓ Hạ tầng đã chạy sẵn (infra_status detect)"
      fi
    fi

    if [ "$ALREADY_RUNNING" = "false" ]; then
      # Gate 4: khởi động hạ tầng + trap EXIT để dọn
      narrate_phase "Phase 2a-infra — Khởi động hạ tầng" "Chạy infra_start + trap cleanup"
      echo "  Command: $INFRA_START"

      # Chạy, capture exit code
      eval "$INFRA_START"
      INFRA_START_RC=$?

      if [ $INFRA_START_RC -ne 0 ]; then
        # Hard block — không skip theo cổng 100%
        echo "⛔ infra_start THẤT BẠI (exit $INFRA_START_RC) — review không tiếp tục."
        echo "   Nguyên nhân khả dĩ: port conflict, resource thiếu, config sai."
        echo "   Debug: chạy '${INFRA_START}' thủ công xem stderr."
        echo "   Override: /vg:review ${PHASE_NUMBER} --legacy-mode (DEPRECATED, expire 2 milestones)"
        exit 1
      fi

      echo "  ✓ infra_start OK — trap infra_stop đã cài"

      # Trap: auto dọn khi review thoát (normal/error/interrupt)
      if [ -n "$INFRA_STOP" ]; then
        trap "echo '  ♻ Dọn hạ tầng (infra_stop)...'; eval \"$INFRA_STOP\" 2>/dev/null || true" EXIT INT TERM
      fi

      # Chờ hạ tầng ready (retry health 30s)
      for i in {1..30}; do
        if eval "$INFRA_STATUS" 2>/dev/null | grep -qiE "running|up|ok|online"; then
          echo "  ✓ Hạ tầng ready sau ${i}s"
          break
        fi
        sleep 1
      done

      # Emit telemetry
      if type -t telemetry_emit >/dev/null 2>&1; then
        telemetry_emit "review_infra_start_success" "{\"env\":\"${ENV}\",\"duration_s\":${i}}"
      fi
    fi
  fi
fi
```

**Tại sao không có AskUserQuestion:**  
Đây là autonomous action — config đã khai `try_infra_start: true` nghĩa là user OK. Nếu user không muốn auto-start → set `false` trong config. Giữa đêm chạy review mà lại hỏi user = anti-pattern.

**Cleanup guarantee:**  
Trap `EXIT INT TERM` bắt mọi đường thoát (normal / error / Ctrl+C). Hạ tầng sẽ stop khi review kết thúc dù success hay fail. Ngoại lệ: SIGKILL (process killed) → trap không chạy → user phải thủ công `infra_stop`.

**Cổng cứng:**  
infra_start fail → BLOCK. Không có "try again later" hay "skip INFRA_PENDING". Đây là điểm khác biệt cốt lõi với v1.13 — không cho phép defer hạ tầng.

### 2a-preflight: INFRASTRUCTURE READINESS GATE

**Review fix loop can only fix CODE bugs. Infra failures (missing config, app down, domain unreachable) must be fixed BEFORE review can work.**

Before entering Phase 2 browser discovery, verify:

```
PRE-FLIGHT CHECKLIST:
[ ] Build succeeded (exit 0, no TS/Rust compile errors)
[ ] Restart succeeded (pm2/systemd/dev_command exited 0, service running)
[ ] Health endpoint(s) return 200 — all entries in config.services[ENV]
[ ] All role domains from config.credentials[ENV] resolve + return any response (not ERR_CONNECTION)
[ ] At least 1 role can login successfully (curl auth endpoint, or MCP smoke login)
```

**If ANY pre-flight fails → BLOCK review with DIAGNOSTIC + FIX GUIDANCE:**

```
⛔ PRE-FLIGHT FAILED — review cannot proceed.

The review step fixes code bugs, not infrastructure. Fix the infra issue below, then re-run.

Issues detected:
  [1] {category}: {specific error}
      Example: "Build: ecosystem.config.js missing at apps/api/"
      Example: "Health: api.{domain}/health returned 502"
      Example: "Domain: advertiser.{domain} ERR_CONNECTION_REFUSED"
      Example: "Login: admin@{domain} POST /auth/login returned 500"

┌─ What to fix (by category) ─────────────────────────────────┐
│ Build failure      → Check compile errors, missing files,   │
│                      dependency conflicts. Fix then retry.  │
│                      Common: missing ecosystem.config.js,   │
│                      .env, turbo task, tsconfig paths.      │
│                                                             │
│ Health endpoint    → Service didn't start or crashed.       │
│                      Check logs: pm2 logs / journalctl /    │
│                      dev server output. Usually missing     │
│                      env var, DB down, port conflict.       │
│                                                             │
│ Domain unreachable → Hostname not resolving or not served.  │
│                      Local: check /etc/hosts + dev proxy.   │
│                      Sandbox: check DNS + HAProxy/nginx.    │
│                                                             │
│ Login failure      → Auth broken server-side (not code bug  │
│                      review can catch later). Check DB      │
│                      seed ran, user exists, JWT secret set. │
└─────────────────────────────────────────────────────────────┘

Next actions — choose scenario that matches your error, follow the exact commands:

  First: read deploy log to identify exact error
  `cat ${PLANNING_DIR}/phases/{phase}/deploy-review.json`

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario A — Deploy command WRONG in config                             │
  │   (e.g., pm2 but no ecosystem.config.js, dev_command points to missing  │
  │    script, services[ENV] lists non-existent health endpoint)            │
  │                                                                         │
  │   Fix:  edit `.claude/vg.config.md` → environments.{ENV}.deploy.*       │
  │         or run: /vg:init        (interactive config wizard)             │
  │   Then: /vg:review {phase}                                              │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario B — Service crashed / code error                               │
  │   (logs show stack trace, 500 errors, module not found, port in use)    │
  │                                                                         │
  │   Fix:  inspect logs (pm2 logs / journalctl / dev output), fix code     │
  │   Then: /vg:review {phase} --retry-failed                               │
  │         (--retry-failed only re-scans failed views → 5-10× faster)     │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario C — Feature genuinely NOT BUILT (status UNREACHABLE)           │
  │   Verify first: grep code for expected page file / route / handler.    │
  │   If grep returns NOTHING → truly not built.                            │
  │   Symptoms: route missing, page file doesn't exist, sidebar link absent │
  │                                                                         │
  │   Fix:  /vg:build {phase} --gaps-only   (builds missing plans)          │
  │   Then: /vg:review {phase} --retry-failed                               │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario C2 — Code BUILT but review didn't replay (status NOT_SCANNED)  │
  │   Verify first: grep confirms page file/route/handler EXIST.            │
  │   Common causes:                                                        │
  │     • Multi-step wizard / mutation flow needs dedicated browser session │
  │     • Orphan route not linked from sidebar → discovery missed it        │
  │     • Haiku scan timed out / hit max_actions for that view              │
  │     • --retry-failed was run but goal wasn't in the retry scope         │
  │                                                                         │
  │   Fix: pick by cause:                                                   │
  │     (a) Complex flow → /vg:test {phase}                                 │
  │         (codegen + Playwright auto-walks wizard, fills all steps)       │
  │     (b) Orphan route → add sidebar link or update nav-discovery seed,  │
  │         then /vg:review {phase} --retry-failed                         │
  │     (c) Timeout/scope → /vg:review {phase} --retry-failed              │
  │         (fresh re-scan of only failed views, bypass cache)              │
  │                                                                         │
  │   DO NOT run /vg:build --gaps-only — it'll regenerate plans for code   │
  │   that already exists and waste tokens.                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario D — Auth/DB setup missing                                      │
  │   (login 500, seed user not found, JWT signature invalid)               │
  │                                                                         │
  │   Fix:  run project seed (e.g., pnpm db:seed), verify .env has secrets  │
  │   Then: /vg:review {phase} --retry-failed                               │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario E — Cross-CLI (reduce token cost by splitting work)            │
  │                                                                         │
  │   Discovery (cheap, any CLI with browser):                              │
  │     $vg-review {phase} --retry-failed --discovery-only    (Codex)       │
  │     /vg-review {phase} --retry-failed --discovery-only    (Gemini)      │
  │   Evaluate + fix (Claude only):                                         │
  │     /vg:review {phase} --evaluate-only                                  │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario F — External infra unavailable (ClickHouse, Kafka, pixel srv) │
  │   Some goals need services not running on current ENV.                 │
  │   Symptoms: 500 on events/stats endpoints, 502 on postback test,      │
  │   ClickHouse table not found, Kafka ECONNREFUSED.                      │
  │                                                                        │
  │   This is NOT a code bug — code is correct but infra missing.          │
  │                                                                        │
  │   ⚠ ANTI-PATTERN WARNING (v1.9.1 R2 + v1.9.2 P4):                      │
  │   Do NOT fall back to "list 3 options (A/B/C) and wait".               │
  │   Use `block_resolve` helper — L1 auto-try `--skip`, L2 architect      │
  │   proposal for cross-env retry, L3 provider-native prompt if needed.   │
  │                                                                        │
  │   Block-resolver handler:                                              │
  └─────────────────────────────────────────────────────────────────────────┘

```bash
# v1.9.2 P4 — Scenario F resolver (replaces legacy A/B/C prompt)
source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/block-resolver.sh" 2>/dev/null || true
if type -t block_resolve >/dev/null 2>&1; then
  export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.infra-unavailable"
  BR_GATE_CONTEXT="External infra (${UNAVAILABLE_SERVICES:-unknown}) not reachable on env='${ENV}'. ${INFRA_PENDING_GOALS:-?} goals blocked. User must choose: continue local with skip, switch to sandbox, or partial (local + sandbox retry)."
  BR_EVIDENCE=$(printf '{"env":"%s","unavailable":"%s","pending_goals":"%s"}' "$ENV" "${UNAVAILABLE_SERVICES:-unknown}" "${INFRA_PENDING_GOALS:-0}")
  BR_CANDIDATES='[
    {"id":"skip-infra-goals","cmd":"echo \"Setting infra_deps.unmet_behavior=skip for this run\" && export CONFIG_INFRA_DEPS_UNMET_BEHAVIOR=skip","confidence":0.75,"rationale":"Skip infra-dependent goals = valid strategy for code-only review passes"}
  ]'
  BR_RESULT=$(block_resolve "infra-unavailable" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
  BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
  case "$BR_LEVEL" in
    L1) echo "✓ L1 resolved — continuing local review with infra goals skipped" >&2 ;;
    L2) block_resolve_l2_handoff "infra-unavailable" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
    *)  block_resolve_l4_stuck "infra-unavailable" "All candidates failed + no architect proposal"; exit 1 ;;
  esac
fi
```

  **Semantic fallback (if resolver unavailable — provider-native prompt):**
  - Claude Code: AskUserQuestion.
  - Codex: ask the same options in the main Codex thread / closest input UI.
  - If A → set config.infra_deps.unmet_behavior="skip", continue
  - If B → switch ENV=sandbox, re-run deploy + preflight
  - If C → continue local with skip, save INFRA_PENDING goals list for sandbox retry

  Verify smoke test before any re-run:
    curl {config.services[ENV][0].health}                      # must return 200
    curl -I https://{config.credentials[ENV][0].domain}        # NOT ERR_CONNECTION
```

**Only when ALL pre-flight checks pass** → proceed to Phase 2b Browser Discovery.

API integration check — curl each endpoint in API-CONTRACTS.md:
```
For each endpoint parsed from API-CONTRACTS.md:
  If endpoint requires auth → include auth token header
  curl endpoint on target → record status code + response shape
```

### 2b: Discovery — 2-Tier Deep Scan (Opus + Haiku)

**Architecture: Opus discovers views (minimal browser), Haiku agents scan exhaustively (1 per view).**
- **Opus**: list views (1 sidebar snapshot + read SPECS), spawn Haiku, merge results, evaluate
- **Haiku**: fixed workflow scanner — click ALL elements, fill ALL forms, recurse into ALL modals. Context tiny → no lazy behavior.

**Why Haiku, not Sonnet**: AI laziness correlates with context length. Haiku agents receive a short prompt + 1 URL = near-zero context = maximum depth. Each Haiku scans 1 view exhaustively rather than skimming many views.

**MCP Server Selection:** Each Haiku agent auto-claims its own Playwright server via lock manager.
Up to 5 parallel browser sessions (5 Playwright slots configured).

#### 2b-0: Seed Data (if configured)

```
Read vg.config.md → check if seed_command exists for current ENV
IF seed_command exists:
  Run: {RUN_PREFIX} "{seed_command}"
  Wait for completion → log output
  Purpose: ensure diverse data (multiple statuses, types) so Haiku can sample representative rows
IF seed_command missing: skip silently (not a blocker)
```

#### 2b-1: Discover Views (Haiku navigator — Opus does NOT touch browser)

```
Opus reads files only (no browser):
1. Read SPECS.md → extract "In Scope" → grep route patterns
   Read PLAN.md → extract task descriptions → grep URL patterns
   Read SUMMARY.md → extract "files changed" → map to routes
   → expected_views = ["/sites", "/sites/:id", "/ad-units", ...]

2. **⛔ REGISTERED ROUTES scan (tightened 2026-04-17 — fix critical miss):**

   Sidebar DOM chỉ show top-level nav. Sub-routes đăng ký trong router config
   (ví dụ React Router `<Route path="...">`, Next.js app/pages dir, Vue Router,
   Flutter GoRouter) thường KHÔNG hiện trong sidebar → scanner miss → mark UNREACHABLE.

   **Trước khi spawn navigator, đọc route registrations từ code — pure config-driven, no defaults:**

   ```bash
   REGISTERED_ROUTES=""

   # Source 1 (preferred): graphify query — chỉ chạy khi có cả graph + predicate
   ROUTE_PRED="${config.graphify.route_predicate:-}"
   if [ "$GRAPHIFY_ACTIVE" = "true" ] && [ -n "$ROUTE_PRED" ]; then
     REGISTERED_ROUTES=$(ROUTE_PRED="$ROUTE_PRED" \
                        ROUTE_EXTRACT="${config.graphify.route_path_extract:-}" \
                        ${PYTHON_BIN} -c "
import json, os, re, sys
pred = os.environ.get('ROUTE_PRED', '')
extract = os.environ.get('ROUTE_EXTRACT', '')
if not pred or not extract:
    sys.exit(0)  # config incomplete → skip
graph_path = os.environ.get('GRAPHIFY_GRAPH_PATH')
if not graph_path or not os.path.exists(graph_path):
    sys.exit(0)
graph = json.load(open(graph_path, encoding='utf-8'))
hits = set()
for n in graph.get('nodes', []):
    blob = ' '.join(str(n.get(k,'')) for k in ('label','type','file'))
    if not re.search(pred, blob): continue
    m = re.search(extract, blob)
    if m:
        hits.add(m.group(1) if m.groups() else m.group(0))
for h in sorted(hits): print(h)
" 2>/dev/null)
   fi

   # Source 2 (fallback): grep files theo config — chỉ chạy khi có cả glob + regex
   ROUTE_GLOB="${config.code_patterns.frontend_routes:-}"
   ROUTE_REGEX="${config.code_patterns.route_path_regex:-}"
   if [ -z "$REGISTERED_ROUTES" ] && [ -n "$ROUTE_GLOB" ] && [ -n "$ROUTE_REGEX" ]; then
     REGISTERED_ROUTES=$(grep -rhoE "$ROUTE_REGEX" $ROUTE_GLOB 2>/dev/null | sort -u)
   fi

   # Report state
   if [ -n "$REGISTERED_ROUTES" ]; then
     COUNT=$(echo "$REGISTERED_ROUTES" | wc -l | tr -d ' ')
     echo "✓ Found ${COUNT} route registrations từ code (source: $([ "$GRAPHIFY_ACTIVE" = true ] && [ -n "$ROUTE_PRED" ] && echo graphify || echo grep))"
   elif [ -z "$ROUTE_PRED" ] && [ -z "$ROUTE_GLOB" ]; then
     echo "⚠ Route discovery KHÔNG được cấu hình (neither config.graphify.route_predicate"
     echo "  nor config.code_patterns.frontend_routes + route_path_regex set)."
     echo "  Review sẽ CHỈ dựa sidebar DOM → CÓ THỂ miss routes không trên menu."
     echo "  Add vào vg.config.md (pick 1 source, ví dụ theo stack của bạn — workflow không đoán hộ):"
     echo ""
     echo "  # Via grep (universal, cần regex ngôn ngữ):"
     echo "  code_patterns:"
     echo "    frontend_routes: '<glob tới route config files>'"
     echo "    route_path_regex: '<regex extract path với capture group>'"
     echo ""
     echo "  # HOẶC via graphify knowledge graph:"
     echo "  graphify:"
     echo "    route_predicate: '<regex match node.label/type/file>'"
     echo "    route_path_extract: '<regex extract path with capture group>'"
   else
     echo "⚠ Route config partial (need BOTH pattern+extract hoặc predicate+extract) → skip code scan."
   fi
   ```

   **Config keys (pure config-driven, workflow KHÔNG có stack defaults):**
   - `code_patterns.frontend_routes` — glob tới file chứa route declarations
   - `code_patterns.route_path_regex` — regex với capture group trả về route path
   - `graphify.route_predicate` — regex matching graphify node (label/type/file) identify route
   - `graphify.route_path_extract` — regex với capture group extract path từ matched node

   **Nguyên tắc:** Thiếu cả 2 source → warn + sidebar-only. Project quyết định stack, workflow chỉ là engine.
   (Examples per stack để tham khảo user-side; KHÔNG fallback trong code workflow.)

3. Load KNOWN-ISSUES.json (if exists):
   Filter: issues where suggested_phase == current phase OR status == "open"

4. Create GOAL-COVERAGE-MATRIX.md (all ⬜ UNTESTED)

5. Spawn 1 Haiku navigator agent (Agent tool, model="haiku"):
   prompt = """
   You are a navigator agent. Login and extract all navigation URLs.

   ## CONNECTION
   SESSION_ID="haiku-nav-{phase}-$$"
   MCP_PREFIX=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
   trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
   Use returned $MCP_PREFIX as server for all browser tool calls.

   ## TASK
   1. Login: {domain}/login | {email} | {password}  (use first role from config)
   2. browser_snapshot → read sidebar/nav menu (top-level visible links)
   3. Extract ALL visible navigation URLs
   4. **⛔ HARD RULE (tightened 2026-04-17): REGISTERED_ROUTES list được inject vào prompt.**
      Agent PHẢI visit EVERY route trong REGISTERED_ROUTES list, KHÔNG CHỈ sidebar.
      Route không có trong sidebar = "hidden_but_registered" → truy cập qua direct URL.
      Nếu visit route bị redirect (ví dụ → /login, → /403), ghi lại reason.
   5. For each URL with :id params:
      Navigate to list page → snapshot → pick first row → extract real URL
   6. Write ${PHASE_DIR}/nav-discovery.json với schema mở rộng:
      {
        "sidebar_views": ["/sites", "/campaigns"],
        "registered_routes_visited": ["/sites", "/audit-log", "/settings/roles", ...],
        "hidden_but_registered": ["/audit-log", "/settings/roles"],
        "redirected": {"/settings/billing": "/403"},
        "actual_views": ["/sites", "/campaigns", "/audit-log", "/settings/roles", ...]
      }
   7. browser_close
   8. bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" release "haiku-nav-{phase}-$$"

   ## INJECTED DATA
   REGISTERED_ROUTES = [{from step 2 above — list from code scan}]
   SIDEBAR_ONLY_HINT = false  # default: visit all registered routes
   """

6. Wait for Haiku navigator → Read nav-discovery.json
   actual_views = parsed JSON .actual_views[]  (already union of sidebar + registered)

7. Merge: union(expected_views, actual_views), deduplicated, within phase scope
   Flag `hidden_but_registered` routes explicitly trong view-assignments.json
   (Haiku scanner phase 2b-2 thấy flag này → biết access qua direct URL, không click sidebar)

8. **IMMEDIATELY write view-assignments.json** — do NOT hold in context:
   Write ${PHASE_DIR}/view-assignments.json:
   {
     "phase": "{phase}",
     "generated_at": "{ISO timestamp}",
     "views": [
       { "url": "/sites", "roles": ["admin", "publisher"], "param_example": null, "source": "sidebar" },
       { "url": "/sites/123", "roles": ["publisher"], "param_example": "123", "source": "sidebar" },
       { "url": "/audit-log", "roles": ["admin"], "param_example": null, "source": "registered_hidden", "access_via": "direct_url" },
       { "url": "/settings/roles", "roles": ["admin"], "param_example": null, "source": "registered_hidden", "access_via": "direct_url" }
     ]
   }
   Trường `source` giúp Haiku scanner biết cách navigate:
   - `sidebar` → click từ menu
   - `registered_hidden` → `browser_navigate` direct URL (không có menu entry)
   
   After writing: DISCARD view list from context. Read from file when needed.

Output: view-assignments.json written to disk. Context cleared.
```

<FLUSH_RULE>
After step 8 writes view-assignments.json, you MUST NOT keep the view list in your response text.
Do NOT summarize the views found. Do NOT repeat the list.
Simply write: "view-assignments.json written — {N} views × {M} roles = {K} scan jobs."
Then immediately proceed to 2b-2 (spawn Haiku).
</FLUSH_RULE>

#### 2b-2: Spawn Haiku Scanners (parallel OR sequential per view — v1.9.4 R3.3)

<DEEPSCAN_OPT_OUT_GATE_v2.65.0>
**v2.65.0 BREAKING change — Phase 2b-2 deepscan now default ON.**

Earlier history: v2.42.4 made deepscan OPT-IN to push exhaustive UI
exploration toward `/vg:roam`. Field audit (v2.64.x) found this caused
state-shortcut bypass — reviews silently skipped deepscan even when
review state was stale, and bugs that deepscan would have caught fell
through to test/accept. v2.65.0 flips back to OPT-OUT so /vg:review
once again surfaces those bugs by default. Adds ~30-90s wall time per
review run; this is intentional (correctness over speed).

**Run 2b-2 BY DEFAULT.** Skip ONLY if one of these explicit opt-outs holds:
- `$ARGUMENTS` contains `--skip-deepscan` (v2.65.0 opt-out flag), OR
- `CONFIG_REVIEW_DEEPSCAN_DEFAULT` is set to `off` in vg.config.md
  (per-project opt-out — useful for cli-tool / library profiles where
  there is no UI surface to deepscan)

Legacy compatibility (v2.42.4 → v2.64.x):
- `--with-deepscan` and `--full-scan` flags still parsed but are now
  no-ops (deepscan runs anyway). Emit a deprecation notice if seen.
- `CONFIG_REVIEW_DEEPSCAN_DEFAULT: on` is now the default; explicit
  `on` is harmless (idempotent).

Skip narration (only when --skip-deepscan or config off resolved):
```
echo "▸ Phase 2b-2 (Haiku per-view exhaustive scan) skipped — explicit opt-out."
echo "  Reason: $SKIP_REASON  (--skip-deepscan flag | CONFIG_REVIEW_DEEPSCAN_DEFAULT=off)"
echo "  Note: v2.65.0 made deepscan default ON. Skipping trades ~30-90s for"
echo "  weaker bug detection. Re-enable by removing the flag or setting"
echo "  CONFIG_REVIEW_DEEPSCAN_DEFAULT=on in vg.config.md."
```

Run narration (default path):
```
echo "▸ Phase 2b-2 (Haiku per-view exhaustive scan) running — v2.65.0 default ON."
echo "  Opt out per-run with --skip-deepscan, or project-wide with"
echo "  CONFIG_REVIEW_DEEPSCAN_DEFAULT=off in vg.config.md."
```

After running 2b-2 (or echoing skip narration), proceed to phase2b-3
(goal sequence recording). The MANDATORY_GATE block below applies on
the default path; it is bypassed only when an explicit opt-out resolved.
</DEEPSCAN_OPT_OUT_GATE_v2.65.0>

<MANDATORY_GATE>
**Applies on the default path (v2.65.0+ deepscan default ON). Bypassed only when an explicit opt-out resolved (--skip-deepscan flag OR CONFIG_REVIEW_DEEPSCAN_DEFAULT=off).**

**You MUST run the provider-native scanner protocol in step 2b-2** (unless spawn_mode=none for cli-tool/library profiles). This is NOT optional.
- Do NOT skip this step because "phase is small" or "I already covered everything in 2b-1"
- Claude Code path: spawn at least 1 Haiku agent per view discovered in 2b-1; the Agent tool with model="haiku" MUST be called.
- Codex path: keep MCP/browser actions in main Codex orchestrator for `codex-inline`. For non-MCP classification work over captured snapshots, you MAY spawn `codex-spawn.sh --tier scanner --sandbox read-only` workers when `parallel_workers > 1` in vg.config.md (v2.65.0 A3). Do not spawn Haiku on Codex (Haiku is Claude-only); only `codex-spawn` model is allowed for parallel codex scanner workers.
- Required evidence is provider-neutral: `scan-*.json`, RUNTIME-MAP merge, GOAL-COVERAGE-MATRIX impact, and `review.haiku_scanner_spawned` telemetry semantics.
</MANDATORY_GATE>

<SPAWN_MODE_RESOLUTION>
**v1.9.4 R3.3 — Scanner spawn mode (mobile sequential constraint):**

Mobile apps (iOS simulator, Android emulator, physical device) can typically run only ONE instance at a time. Spawning 5 parallel Haiku agents on a single emulator causes conflicts / crashes / app state corruption. CLI/library projects have no UI to scan at all.

```bash
# Resolve scanner spawn mode BEFORE entering spawn loop
resolve_scanner_spawn_mode() {
  local mode="${CONFIG_REVIEW_SCANNER_SPAWN_MODE:-auto}"
  if [ "$mode" != "auto" ]; then
    echo "$mode"
    return
  fi
  # Auto-derive from config.profile
  case "${CONFIG_PROFILE:-web-fullstack}" in
    mobile-rn|mobile-flutter|mobile-native-ios|mobile-native-android|mobile-hybrid)
      echo "sequential"  # Single emulator/simulator/device
      ;;
    cli-tool|library)
      echo "none"        # No UI to scan
      ;;
    web-fullstack|web-frontend-only|web-backend-only|*)
      echo "parallel"    # Default — multiple browser contexts supported
      ;;
  esac
}

SPAWN_MODE=$(resolve_scanner_spawn_mode)
echo ""
echo "▸ Scanner spawn mode: ${SPAWN_MODE} (profile: ${CONFIG_PROFILE:-web-fullstack})"
case "$SPAWN_MODE" in
  sequential)
    echo "📱 Sequential mode — 1 Haiku agent at a time (mobile/single-window constraint)"
    echo "   Tổng ${TOTAL} view sẽ scan tuần tự; thời gian ~${TOTAL}×5min (1 agent/view)"
    ;;
  parallel)
    echo "🌐 Parallel mode — up to 5 Haiku agents concurrent (Playwright lock caps)"
    echo "   Tổng ${TOTAL} view; thời gian ~${TOTAL}/5 × 5min"
    ;;
  none)
    echo "⏭  Spawn mode=none — skipping Phase 2b-2 entirely (profile has no UI scan)"
    echo "   Backend goals resolved via surface probes in Phase 4a instead."
    ;;
  *)
    echo "⚠ Unknown spawn_mode=${SPAWN_MODE} — falling back to parallel" >&2
    SPAWN_MODE="parallel"
    ;;
esac
```

**Behavior branch by mode:**

- **`parallel`** (web default): All Agent(model="haiku", ...) calls in ONE tool_use block → Claude Code harness runs them concurrently. Playwright lock manager caps effective concurrency at 5 slots.

- **`sequential`** (mobile default): Each Agent(model="haiku", ...) call in SEPARATE messages, awaiting completion before spawning next. Guarantees single emulator/device state. User sees 1/N → 2/N → ... progression serially.

- **`none`** (cli-tool/library): Skip 2b-2 entirely. Jump to 2b-3 collect phase (will merge 0 scans). Phase 4 goal coverage relies 100% on surface probes (api/data/integration/time-driven) from Phase 4a.

**Override via config:** Set `review.scanner_spawn_mode: "sequential"` in vg.config.md to force sequential even for web projects (e.g., if CI has constrained browser resources).
</SPAWN_MODE_RESOLUTION>

<REREAD_REQUIRED>
**Before spawning Haiku agents, you MUST re-read `view-assignments.json` via the Read tool
(fixes I5).** The `<FLUSH_RULE>` in step 2b-1 required discarding the view list from context
to save tokens. That means right now you don't have it — do NOT guess view URLs or roles
from memory. Call Read on `${PHASE_DIR}/view-assignments.json` FIRST, then iterate the
parsed `.views[]` to spawn one Haiku per (view × role) pair.

If `--retry-failed` mode, read `view-assignments-retry.json` instead. Both files share
the same schema; iteration logic is identical.
</REREAD_REQUIRED>

**Spawn 1 Haiku agent per view** using Agent tool with `model="haiku"`.
Each agent scans 1 view exhaustively with a FIXED workflow — no discretion to skip.

**Bootstrap rules injection (v1.15.0+):** Before spawning each Haiku scanner,
render + inject promoted project rules so scanners see project-specific checks
(e.g. "verify data persists after mutation" rule L-050 will fire here):
```bash
source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "review")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "review" "${PHASE_NUMBER}"
```
Then in each Haiku prompt body, include:
```
<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>
```
Position: after static `<scanner_workflow>` block, before `<view_assignment>`.
Scanner skill treats rules as additional per-element checks on top of fixed protocol.

IF --retry-failed:
  Normalize RETRY_VIEWS[] → view-assignments-retry.json (same schema as view-assignments.json):
    {
      "phase": "{phase}",
      "generated_at": "{ISO}",
      "mode": "retry-failed",
      "views": [{"url": "/sites", "roles": ["publisher"], "param_example": null}, ...]
    }
  READ view-assignments-retry.json
ELSE:
  READ ${PHASE_DIR}/view-assignments.json
  (both paths → same schema → downstream code identical)

view_assignments = parsed .views[]

**🎬 Pre-spawn briefing (tightened 2026-04-17 — user biết agent sẽ làm gì):**

Trước mỗi spawn, orchestrator phải:
1. Load goals map từ TEST-GOALS.md → tìm goals có `start_view == view.url` HOẶC flow references view
2. Print briefing block với: view, role, goals_covered, expected_interactions, expected_mutations
3. Set `description` của Agent tool theo format structured, không freeform

```bash
briefing_for_view() {
  local VIEW_URL="$1" ROLE="$2" IDX="$3" TOTAL="$4"
  # Parse TEST-GOALS.md → collect goals whose start_view or flow touches this view
  local BRIEFING=$(${PYTHON_BIN} - <<PY 2>/dev/null
import re, os, sys
view_url = "$VIEW_URL"
phase_dir = os.environ.get("PHASE_DIR", ".")
import glob
tg_files = glob.glob(f"{phase_dir}/*TEST-GOALS*.md")
if not tg_files:
    sys.exit(0)
tg = open(tg_files[0], encoding="utf-8").read()
# Parse goal blocks: "## Goal G-XX: title\n...**Start view:** /path\n**Success criteria:** ...\n**Mutation evidence:** ..."
blocks = re.split(r'^##\s*Goal\s+', tg, flags=re.M)
hits = []
for blk in blocks[1:]:
    m = re.match(r'(G-\d+)[:\s]+(.+?)\n', blk)
    if not m: continue
    gid, title = m.group(1), m.group(2).strip()
    # Match by start_view OR mention in flow
    start = re.search(r'\*\*Start view:\*\*\s*(\S+)', blk)
    touches = (start and start.group(1) == view_url) or (view_url in blk)
    if not touches: continue
    crit = re.search(r'\*\*Success criteria:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.S)
    mut  = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.S)
    prio = re.search(r'\*\*Priority:\*\*\s*(\w+)', blk)
    hits.append({
        "gid": gid, "title": title[:80],
        "priority": (prio.group(1) if prio else "important").lower(),
        "criteria": (crit.group(1).strip()[:120] if crit else ""),
        "mutation": (mut.group(1).strip()[:100] if mut else ""),
    })
for h in hits:
    print(f"{h['gid']}|{h['priority']}|{h['title']}|{h['criteria']}|{h['mutation']}")
PY
  )

  echo ""
  echo "┌─────────────────────────────────────────────────────────────"
  echo "│ [${IDX}/${TOTAL}] Haiku scanner briefing"
  echo "├─────────────────────────────────────────────────────────────"
  echo "│ 📄 View:  ${VIEW_URL}"
  echo "│ 👤 Role:  ${ROLE}"
  if [ -z "$BRIEFING" ]; then
    echo "│ 🎯 Goals: (none mapped — exploratory scan, fill gaps)"
  else
    echo "│ 🎯 Goals sẽ cover:"
    while IFS='|' read -r gid prio title crit mut; do
      [ -z "$gid" ] && continue
      echo "│   • ${gid} [${prio}] ${title}"
      [ -n "$crit" ] && echo "│       ✓ Expect: ${crit}"
      [ -n "$mut" ]  && echo "│       Δ Mutation: ${mut}"
    done <<< "$BRIEFING"
  fi
  echo "│ 🔎 Agent sẽ:"
  echo "│   - Login as ${ROLE} → navigate to ${VIEW_URL}"
  echo "│   - Snapshot + enumerate all modals/forms/interactive elements"
  echo "│   - For each goal above: replay interaction flow, capture evidence"
  echo "│   - Log console.error + network 4xx/5xx per step"
  echo "│   - Output: scan-${VIEW_URL//\//_}-${ROLE}.json"
  echo "└─────────────────────────────────────────────────────────────"
}
```

Then spawn with **structured description** (thay vì freeform).

**⚠ SPAWN_MODE enforcement (v1.9.4 R3.3) — orchestrator branching:**

| SPAWN_MODE  | Tool-use pattern                                           | Use case                               |
|-------------|------------------------------------------------------------|----------------------------------------|
| `none`      | Skip spawn loop entirely, write empty scan-manifest, jump to 2b-3 | cli-tool, library (no UI to scan)      |
| `sequential`| Each Agent() call in **SEPARATE** message, await each complete before next | mobile-* (single emulator/device)      |
| `parallel`  | All Agent() calls in **ONE** tool_use block, harness runs concurrent ≤5 | web-* (default, multi-browser contexts)|

**When SPAWN_MODE=none:** orchestrator writes empty scan-manifest.json then skips to 2b-3:
```bash
${PYTHON_BIN} -c "
import json; from pathlib import Path
Path('${PHASE_DIR}/scans').mkdir(exist_ok=True)
Path('${PHASE_DIR}/scan-manifest.json').write_text(json.dumps({
  'mode': 'skipped_no_ui',
  'profile': '${CONFIG_PROFILE}',
  'scans': []
}, indent=2))"
# → proceed to 2b-3 collect (which handles empty scans gracefully)
```

**When SPAWN_MODE=sequential (mobile):** iterate view_assignments ONE AT A TIME. Each Agent() call in a separate message — DO NOT batch them into one tool_use block. Narrate `[idx/total] spawning <view>@<role>...` before each, `[idx/total] done (<N goals, <M regressions>)` after. User sees serial progression.

**When SPAWN_MODE=parallel (web):** batch ALL Agent() calls in ONE tool_use block so Claude harness dispatches them concurrently (Playwright lock manager caps at 5 slots).

**Common spawn pattern (applies to both sequential and parallel):**

```
For each view in view_assignments:
  For each role that can access this view (from config.credentials):
    IDX=$((IDX + 1))
    briefing_for_view "{view.url}" "{role}" "$IDX" "$TOTAL"

    # ─── Phase 15 D-17 telemetry (BEFORE spawn, not after) ──────────────
    # Emit `review.haiku_scanner_spawned` IMMEDIATELY before Agent() so the
    # event survives Agent failure / run abort. Validator
    # verify-haiku-spawn-fired.py (Phase 15 T3.11) reads this in events.db
    # to confirm step 2b-2 actually fired for UI-profile phases. Without
    # this, a non-deterministic spawn failure could leave the validator
    # unable to distinguish "spawn never attempted" from "spawn attempted
    # but Agent crashed". Order matters: emit BEFORE Agent call.
    #
    # Parallel mode: emit per-spawn in a serial bash loop, THEN batch all
    # Agent() calls in one tool_use block. Sequential mode: emit
    # immediately before each Agent() call individually.
    Bash:
      ${PYTHON_BIN} ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event \
        "review.haiku_scanner_spawned" \
        --step "2b-2" --actor "orchestrator" --outcome "INFO" \
        --payload "$(printf '{"view":"%s","role":"%s","idx":%d,"total":%d,"spawn_mode":"%s"}' \
          "{view.url}" "{role}" "$IDX" "$TOTAL" "$SPAWN_MODE")" \
        2>/dev/null || true

    Agent(
      model="haiku",
      description="[{IDX}/{TOTAL}] {ROLE}@{view.url} — verify {N} goals: {G-XX,G-YY,...}"
    ):
      prompt = """
      Read skill: vg-haiku-scanner (at .claude/skills/vg-haiku-scanner/SKILL.md)
      Follow it exactly. Inject these args into the workflow:

        PHASE          = "{phase}"
        VIEW_URL       = "{view.url — substitute param_example if :id pattern}"
        VIEW_SLUG      = "{filesystem-safe slug from VIEW_URL}"
        ROLE           = "{role}"
        BOUNDARY       = "{allowed URL pattern for this view}"
        DOMAIN         = "{role.domain from config.credentials[ENV]}"
        EMAIL          = "{role.email}"
        PASSWORD       = "{role.password}"
        PHASE_DIR      = "{absolute ${PHASE_DIR}}"
        SCREENSHOTS_DIR= "{absolute ${SCREENSHOTS_DIR}}"
        FULL_SCAN      = {true if --full-scan flag set else false}
        GOALS_COVERED  = [{G-XX, G-YY, ...} — from briefing_for_view parse]
        GOAL_BRIEFS    = {gid: {title, criteria, mutation, priority} — full context for prompts}

      The skill contains the full workflow (login, sidebar suppression, STEP 1-5,
      element interaction rules, output JSON schema, hard rules, cleanup).
      Do NOT invent variations. Execute skill verbatim.

      Report progress back in description updates (Agent tool surfaces `description`
      in main terminal — update per goal processed so user sees progress).
      """
      # Inline prompt collapsed — full workflow lives in skill file to keep context small.
```

**Description format (structured, parseable):**
- `[{idx}/{total}] {role}@{view} — verify {N} goals: {G-list}` — lúc spawn
- `[{idx}/{total}] {role}@{view} — G-03/5 filling form...` — trong lúc chạy (Haiku update)
- `[{idx}/{total}] {role}@{view} — ✓ 4/5 goals, 1 regression` — khi xong

User sẽ thấy banner đầy đủ BEFORE spawn + structured description trong/sau spawn.
```

**Limits (per Haiku agent):**
- Max 200 actions per view (prevents runaway on huge pages)
- Max 10 min wall time per agent
- Stagnation: same state 3x = stuck, move on
- **Concurrency (v1.9.4 R3.3 SPAWN_MODE aware):**
  - `parallel` mode: up to 5 Haiku agents concurrent (Playwright slot cap)
  - `sequential` mode: exactly 1 Haiku agent at a time (mobile safety)
  - `none` mode: no Haiku agents spawned (cli-tool/library)

</step>
