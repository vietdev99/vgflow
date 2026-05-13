# test runtime (STEP 3)

4 steps: 5b_runtime_contract_verify, 5c_smoke, 5c_flow, 5c_mobile_flow.

<!-- H7 Batch 8: skip-event emitter helper — sourced at runtime before each step -->
```bash
# H7 Batch 8: HARD-GATE skip emit helper
emit_step_skipped_by_profile() {
  local step="$1"
  local profile="${2:-${PHASE_PROFILE:-${PROFILE:-unknown}}}"
  local substitute="${3:-}"
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "test.step_skipped_by_profile" \
    --payload "{\"phase\":\"${PHASE_NUMBER:-unknown}\",\"step\":\"${step}\",\"profile\":\"${profile}\",\"substitute\":\"${substitute}\"}" \
    >/dev/null 2>&1 || true
}
```

<HARD-GATE>
Profile gating (each step runs only for its listed profiles):
- `web-fullstack`     → 5b_runtime_contract_verify + 5c_smoke + 5c_flow
- `web-backend-only`  → 5b_runtime_contract_verify only (BE-only: no FE steps)
- `web-frontend-only` → 5c_smoke + 5c_flow only (no contract verify)
- `mobile-*`          → 5c_mobile_flow only

Each active step finishes with a marker touch + `vg-orchestrator mark-step test <step>`.
Skipping ANY active step = Stop hook block.

vg-load (Phase F Task 30): 5b uses `vg-load --phase ${PHASE_NUMBER} --artifact
contracts --index` for endpoint enumeration — do NOT cat flat API-CONTRACTS.md.
5c_smoke reads RUNTIME-MAP.json directly (already JSON from /vg:review — KEEP-FLAT).
</HARD-GATE>

---

## STEP 3.1 — runtime contract verify (5b_runtime_contract_verify) [profile: web-fullstack,web-backend-only]

HARD-GATE: web-frontend-only + mobile-* MUST skip this step.

```bash
# H7 Batch 8: emit skip event for accept-time audit
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-frontend-only|mobile-*)
    emit_step_skipped_by_profile "5b_runtime_contract_verify" "${PHASE_PROFILE:-${PROFILE:-}}" ""
    # no substitute — step is genuinely N/A for this profile
    ;;
esac
```

Verify each deployed endpoint against the blueprint contract (curl + jq, no AI).
Read `.claude/commands/vg/_shared/env-commands.md` — `contract_verify_curl(phase_dir)`.
Read `.claude/skills/api-contract/SKILL.md` — Mode: Verify-Curl.

```bash
vg-orchestrator step-active 5b_runtime_contract_verify

# Phase F Task 30 — endpoint enumeration via vg-load index, not flat read
CONTRACTS_INDEX=$(vg-load --phase "${PHASE_NUMBER}" --artifact contracts --index 2>/dev/null)
if [ -z "$CONTRACTS_INDEX" ]; then
  echo "⛔ vg-load contracts --index returned empty — run /vg:blueprint ${PHASE_NUMBER} first."
  exit 1
fi
ENDPOINTS=$(echo "$CONTRACTS_INDEX" | ${PYTHON_BIN:-python3} -c "
import json, sys
idx = json.load(sys.stdin)
for ep in idx.get('endpoints', []):
    m, p = ep.get('method',''), ep.get('path','')
    if m and p: print(f'{m}\t{p}')
" 2>/dev/null)
TOTAL=$(echo "$ENDPOINTS" | grep -c . || echo 0)
echo "Contract verify: ${TOTAL} endpoints from vg-load index"
```

For each endpoint: `curl` → `jq` response keys → compare vs contract.
Error samples: check envelope per INTERFACE-STANDARDS.md (`ok:false → error.code + error.message`).
Result: All match → PASS. Any mismatch → BLOCK (list specifics).

### 5b-2: Idempotency check (DEFAULT OFF — opt-in safety gate)

> **H4 SAFETY (Batch 7):** This check double-submits POST/PUT/DELETE to live `$BASE_URL` with real `Bearer ${AUTH_TOKEN}`. **Default: OFF.** Opt-in via `config.test.idempotency.enabled: true`. Hard-gates against production-like environments. Failed cleanup emits `test.idempotency_polluted` event.

**Skip if (any one skips):**
- `config.test.idempotency.enabled` not `true` (default)
- `ENVIRONMENT` in `config.test.idempotency.blocked_envs` (default: `production,prod,live`)
- `$BASE_URL` unset
- `config.critical_domains` empty
- No matching endpoints in vg-load index

```bash
# H4 Batch 7: production-pollution safety gates
IDEM_ENABLED=$(vg_config_get test.idempotency.enabled "false" 2>/dev/null || echo "false")
if [ "${IDEM_ENABLED}" != "true" ]; then
  echo "5b-2 idempotency: SKIPPED (config.test.idempotency.enabled=false)"
  echo "  Set 'test.idempotency.enabled: true' in vg.config.md to opt in (NON-PROD only)."
  IDEMPOTENCY_SKIPPED=1
fi

if [ "${IDEMPOTENCY_SKIPPED:-0}" != "1" ]; then
  BLOCKED_ENVS=$(vg_config_get test.idempotency.blocked_envs "production,prod,live" 2>/dev/null || echo "production,prod,live")
  CUR_ENV="${ENVIRONMENT:-${VG_ENV:-unknown}}"
  for blocked in $(echo "$BLOCKED_ENVS" | tr ',' ' '); do
    if [ "${CUR_ENV,,}" = "${blocked,,}" ]; then
      echo "⛔ 5b-2 idempotency BLOCKED: ENVIRONMENT='${CUR_ENV}' in blocked list."
      echo "  Idempotency probe creates real records via double-POST — refuse production."
      echo "  Override via test.idempotency.blocked_envs config (NOT recommended)."
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "test.idempotency_blocked_production" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"env\":\"${CUR_ENV}\"}" >/dev/null 2>&1 || true
      IDEMPOTENCY_SKIPPED=1
      break
    fi
  done
fi

if [ "${IDEMPOTENCY_SKIPPED:-0}" != "1" ]; then
CRITICAL_DOMAINS=$(vg_config_get critical_domains "billing,auth,payout,payment,transaction" 2>/dev/null || echo "billing,auth,payout,payment,transaction")
IDEMPOTENCY_FAILS=0
IDEM_CLEANUP_LEDGER="${VG_TMP}/idempotency-cleanup.json"
echo "[]" > "$IDEM_CLEANUP_LEDGER"

# Phase F Task 30 — endpoint enumeration via vg-load index
echo "$CONTRACTS_INDEX" | ${PYTHON_BIN:-python3} -c "
import json, sys
idx = json.load(sys.stdin)
domains = '${CRITICAL_DOMAINS}'.split(',')
for ep in idx.get('endpoints', []):
    m, p = ep.get('method',''), ep.get('path','')
    if m not in ('POST','PUT','DELETE'): continue
    if any(d.strip() in p.lower() for d in domains):
        print(f'{m}\t{p}\t{ep.get(\"sample_payload\",\"{}\")}')
" 2>/dev/null > "${VG_TMP}/critical-payloads.txt"

CRITICAL_COUNT=$(wc -l < "${VG_TMP}/critical-payloads.txt" | tr -d ' ')

if [ "$CRITICAL_COUNT" -gt 0 ] && [ -n "$BASE_URL" ]; then
  echo "Idempotency check: ${CRITICAL_COUNT} critical-domain mutation endpoints (env=${CUR_ENV})"
  while IFS=$'\t' read -r METHOD ENDPOINT PAYLOAD; do
    [ -z "$ENDPOINT" ] && continue
    [ -z "$PAYLOAD" ] && PAYLOAD='{}'
    RESP1=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" -H "Content-Type: application/json" \
      -d "$PAYLOAD" -w "\n%{http_code}" 2>/dev/null)
    STATUS1=$(echo "$RESP1" | tail -1)
    RESP2=$(curl -sf -X "$METHOD" "${BASE_URL}${ENDPOINT}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" -H "Content-Type: application/json" \
      -d "$PAYLOAD" -w "\n%{http_code}" 2>/dev/null)
    STATUS2=$(echo "$RESP2" | tail -1)
    if [ "$STATUS1" = "201" ] && [ "$STATUS2" = "201" ]; then
      ID1=$(echo "$RESP1" | sed '$d' | ${PYTHON_BIN:-python3} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      ID2=$(echo "$RESP2" | head -1 | ${PYTHON_BIN:-python3} -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      # H4 Batch 7: Track BOTH created IDs for cleanup — even when idempotency passes (server returned same ID twice = no dup, ID2 may still be a real new record on PUT)
      for created_id in "$ID1" "$ID2"; do
        [ -n "$created_id" ] || continue
        ${PYTHON_BIN:-python3} -c "
import json
with open('${IDEM_CLEANUP_LEDGER}', encoding='utf-8') as f: data = json.load(f)
data.append({'method': '${METHOD}', 'path': '${ENDPOINT}', 'id': '${created_id}'})
with open('${IDEM_CLEANUP_LEDGER}', 'w', encoding='utf-8') as f: json.dump(data, f)
" 2>/dev/null
      done
      if [ -n "$ID1" ] && [ -n "$ID2" ] && [ "$ID1" != "$ID2" ]; then
        echo "  CRITICAL: ${METHOD} ${ENDPOINT} — double-submit created 2 records (${ID1} vs ${ID2})"
        IDEMPOTENCY_FAILS=$((IDEMPOTENCY_FAILS + 1))
      fi
    elif [ "$STATUS1" = "400" ]; then
      echo "  SKIP: ${METHOD} ${ENDPOINT} — schema validation rejected payload (400)"
    fi
  done < "${VG_TMP}/critical-payloads.txt"
  [ "$IDEMPOTENCY_FAILS" -gt 0 ] \
    && echo "  ⛔ ${IDEMPOTENCY_FAILS} idempotency failures" \
    || echo "  ✓ All critical-domain endpoints pass idempotency check"

  # H4 Batch 7: Cleanup pass — DELETE every created record
  CLEANUP_FAILS=0
  CLEANUP_COUNT=0
  while IFS= read -r entry; do
    METHOD=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('method',''))" 2>/dev/null)
    PATH_TPL=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('path',''))" 2>/dev/null)
    REC_ID=$(echo "$entry" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('id',''))" 2>/dev/null)
    [ -z "$REC_ID" ] && continue
    # Best-effort DELETE — only attempt if base path resembles a resource collection (POST /xs → DELETE /xs/$id)
    if [ "$METHOD" = "POST" ]; then
      DEL_URL="${BASE_URL}${PATH_TPL%/}/${REC_ID}"
      DEL_CODE=$(curl -sf -X DELETE "$DEL_URL" \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        -w "%{http_code}" -o /dev/null 2>/dev/null || echo "000")
      CLEANUP_COUNT=$((CLEANUP_COUNT + 1))
      if [ "$DEL_CODE" != "204" ] && [ "$DEL_CODE" != "200" ] && [ "$DEL_CODE" != "404" ]; then
        echo "  ⚠ idempotency cleanup DELETE ${DEL_URL} → ${DEL_CODE}"
        CLEANUP_FAILS=$((CLEANUP_FAILS + 1))
      fi
    fi
  done < <(${PYTHON_BIN:-python3} -c "
import json
data = json.load(open('${IDEM_CLEANUP_LEDGER}', encoding='utf-8'))
for e in data: print(json.dumps(e))
" 2>/dev/null)

  if [ "$CLEANUP_FAILS" -gt 0 ]; then
    echo "  ⚠ ${CLEANUP_FAILS}/${CLEANUP_COUNT} idempotency cleanup DELETE attempts failed — review ${IDEM_CLEANUP_LEDGER}"
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "test.idempotency_polluted" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"cleanup_fails\":${CLEANUP_FAILS},\"cleanup_total\":${CLEANUP_COUNT},\"ledger\":\"${IDEM_CLEANUP_LEDGER}\"}" >/dev/null 2>&1 || true
  else
    [ "$CLEANUP_COUNT" -gt 0 ] && echo "  ✓ idempotency cleanup: ${CLEANUP_COUNT} records DELETE'd"
  fi
fi
fi
```

Result: `IDEMPOTENCY_FAILS > 0` → FAIL (same severity as contract mismatch). Cleanup failure emits `test.idempotency_polluted` event (advisory, does NOT fail step on its own — user must inspect ledger).

Display:
```
5b Runtime Contract Verify:
  Endpoints: {checked}/{total}
  Fields: {matched}/{total}
  Idempotency (critical domains): {CRITICAL_COUNT} checked, {IDEMPOTENCY_FAILS} failures
  Result: {PASS|BLOCK}
```

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/step-status-ledger.py" \
  --phase-dir "${PHASE_DIR}" --step "5b_runtime_contract_verify" --status "${CONTRACT_VERIFY_STATUS:-PASS}" \
  --reason "${CONTRACT_VERIFY_REASON:-}" || true
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5b_runtime_contract_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5b_runtime_contract_verify.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5b_runtime_contract_verify 2>/dev/null || true
```

---

## STEP 3.2 — smoke check (5c_smoke) [profile: web-fullstack,web-frontend-only]

HARD-GATE: web-backend-only + mobile-* MUST skip this step.

```bash
# H7 Batch 8: emit skip event for accept-time audit
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-backend-only|mobile-*)
    emit_step_skipped_by_profile "5c_smoke" "${PHASE_PROFILE:-${PROFILE:-}}" "5b_runtime_contract_verify"
    ;;
esac
```

Cross-check RUNTIME-MAP vs current app state. Browser: HEADED. Login via
`config.credentials[ENV]`. RUNTIME-MAP.json is already JSON from /vg:review
— read directly (KEEP-FLAT; no vg-load needed).

**METHOD — stratified sampling:** Select 5 views from RUNTIME-MAP.json
(≥1 per role; prefer views with most elements[]; remaining from goal_sequences).
For each: navigate via UI clicks → `browser_snapshot` → compare fingerprint
(element count, key elements[]) → replay 1-2 goal_sequence steps if referenced
→ `browser_console_messages` for new errors.

Results:
- 0 mismatches → PROCEED
- 1 mismatch → WARNING + note drift
- ≥2 mismatches → FLAG drift; suggest `/vg:review --resume`; ask user to proceed or re-review

Display:
```
5c Smoke Check:
  Views checked: 5
  Matches: {N}/5
  Result: {PROCEED|WARNING|FLAG}
```

```bash
vg-orchestrator step-active 5c_smoke
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/step-status-ledger.py" \
  --phase-dir "${PHASE_DIR}" --step "5c_smoke" --status "${SMOKE_STATUS:-PASS}" \
  --reason "${SMOKE_REASON:-}" || true
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_smoke" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_smoke.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_smoke 2>/dev/null || true
```

---

## STEP 3.3 — multi-page flow verify (5c_flow) [profile: web-fullstack,web-frontend-only]

HARD-GATE: web-backend-only + mobile-* MUST skip this step.

```bash
# H7 Batch 8: emit skip event for accept-time audit
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-backend-only|mobile-*)
    emit_step_skipped_by_profile "5c_flow" "${PHASE_PROFILE:-${PROFILE:-}}" "5b_runtime_contract_verify"
    ;;
esac
```

```bash
vg-orchestrator step-active 5c_flow
```

**Skip conditions:**
- `--skip-flow` flag → skip
- `${PHASE_DIR}/FLOW-SPEC.md` absent → check goal chains first.
  KEEP-FLAT: deterministic dependency-graph BFS, NOT AI context. The
  embedded Python parses `**Dependencies:**` lines and counts depth-≥3
  chains — pure structural analysis, no agent consumption. Per review-v2
  D1 nit:
  ```bash
  CHAIN_COUNT=$(${PYTHON_BIN} -c "
  import re; from pathlib import Path; from collections import deque
  text = Path('${PHASE_DIR}/TEST-GOALS.md').read_text(encoding='utf-8')
  goals, cur = {}, None
  for line in text.splitlines():
      m = re.match(r'^## Goal (G-\d+)', line)
      if m: cur = m.group(1); goals[cur] = []
      elif cur:
          dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
          if dm and dm.group(1).strip().lower() not in ('none',''):
              goals[cur] = re.findall(r'G-\d+', dm.group(1))
  roots = [g for g,d in goals.items() if not d]; chains = 0
  for r in roots:
      q = deque([(r,1)])
      while q:
          node, depth = q.popleft()
          for c in [g for g,d in goals.items() if node in d]:
              if depth+1 >= 3: chains += 1
              q.append((c, depth+1))
  print(chains)")
  ```
  - `CHAIN_COUNT > 0` → block-resolver handoff (v1.9.2 P4):
    ```bash
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="test.5c-flow"
      BR_GATE_CONTEXT="FLOW-SPEC.md absent but ${CHAIN_COUNT} goal chains (>=3). Multi-page flows need continuity testing."
      BR_EVIDENCE=$(printf '{"chain_count":%d,"phase":"%s"}' "$CHAIN_COUNT" "$PHASE_NUMBER")
      BR_CANDIDATES='[{"id":"regen-flow-spec","cmd":"exit 1","confidence":0.4,"rationale":"Re-run blueprint 2b7 to auto-generate FLOW-SPEC.md"}]'
      BR_RESULT=$(block_resolve "flow-spec-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      case "$BR_LEVEL" in
        L1) echo "✓ L1 resolved — FLOW-SPEC generated inline" >&2 ;;
        L2) echo "▸ L2 proposal — options:" >&2
            echo "  /vg:blueprint ${PHASE_NUMBER} --from=2b7  (auto-gen flow spec)" >&2
            echo "  /vg:test ${PHASE_NUMBER} --skip-flow     (skip; debt logged)" >&2
            exit 2 ;;
        *)  echo "  Recommend /vg:blueprint ${PHASE_NUMBER} --from=2b7" >&2 ;;
      esac
    fi
    ```
  - `CHAIN_COUNT == 0` → skip silently (phase is simple, no chained flows needed)

**Purpose:** 5c-goal tests goals independently; multi-page flows need continuity
(data from step 1 must persist to step 5). Invocation: `flow-runner` skill.

```
Read skill: flow-runner
Args:
  FLOW_SPEC      = "${PHASE_DIR}/FLOW-SPEC.md"
  PHASE          = "${PHASE}"
  CHECKPOINT_DIR = "${PHASE_DIR}/checkpoints"
  MODE           = "verify"
```

Flow-runner: reads FLOW-SPEC, claims Playwright MCP, executes end-to-end
(condition waits, resume-safe checkpoints), 4-rule deviation + 3-strike
escalation → `flow-results.json` (PASS/FAIL + evidence per flow).

**Result merging:**
```bash
FLOW_RESULTS="${PHASE_DIR}/flow-results.json"
if [ -f "$FLOW_RESULTS" ]; then
  FLOWS_PASSED=$(jq '.flows | map(select(.status=="passed")) | length' "$FLOW_RESULTS")
  FLOWS_FAILED=$(jq '.flows | map(select(.status=="failed")) | length' "$FLOW_RESULTS")
  FLOWS_TOTAL=$(jq '.flows | length' "$FLOW_RESULTS")
  # Flow failures default MAJOR: multi-page state-machine break = feature inoperable.
  # flow-runner may downgrade to MINOR only if cosmetic + no downstream step affected.
fi
```

Merge failed flows into 5c-goal classification (MINOR/MODERATE/MAJOR) — 5c-fix
and 5c-auto-escalate treat them uniformly.

Display: `5c Multi-page Flow Verify: FLOW-SPEC {present|absent} | Flows {FLOWS_TOTAL} | Passed {FLOWS_PASSED} | Failed {FLOWS_FAILED} | Checkpoints ${PHASE_DIR}/checkpoints/`

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_flow" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_flow.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_flow 2>/dev/null || true
```

---

## STEP 3.4 — mobile flow (5c_mobile_flow) [profile: mobile-*]

HARD-GATE: web-fullstack, web-frontend-only, web-backend-only MUST skip this step.

```bash
# H7 Batch 8: emit skip event for accept-time audit
case "${PHASE_PROFILE:-${PROFILE:-}}" in
  web-fullstack|web-frontend-only|web-backend-only)
    emit_step_skipped_by_profile "5c_mobile_flow" "${PHASE_PROFILE:-${PROFILE:-}}" ""
    # no substitute — mobile flow is genuinely N/A for web profiles
    ;;
esac
```

Mobile equivalent of web smoke + goal + flow combined. Each goal → Maestro YAML
(`assertVisible`/`assertTrue`). Pre-req: 5a_mobile_deploy done; `*.maestro.yaml`
under `${GENERATED_TESTS_DIR}/mobile/<phase>/` or `config.mobile.e2e.flows_dir`.

```bash
vg-orchestrator step-active 5c_mobile_flow

WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
FLOWS_DIR=$(awk '/^mobile:/{m=1;next} m && /^  e2e:/{e=1;next}
                  e && /^  [a-z]/{e=0} e && /flows_dir:/{print $2;exit}' \
             .claude/vg.config.md | tr -d '"' | head -1)
FLOWS_DIR="${FLOWS_DIR:-${GENERATED_TESTS_DIR}/mobile}"

FLOW_FILES=$(find "${REPO_ROOT}/${FLOWS_DIR}" -type f \( -name "*.maestro.yaml" -o -name "*.maestro.yml" \) 2>/dev/null | sort)
if [ -z "$FLOW_FILES" ]; then
  echo "⚠ No Maestro flows found under ${FLOWS_DIR}. Run 5d_mobile_codegen first."
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_mobile_flow" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_mobile_flow.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_mobile_flow 2>/dev/null || true
  exit 0  # Don't fail — goals may all be UNREACHABLE
fi

FAILED=0; TOTAL=0
for FLOW in $FLOW_FILES; do
  TOTAL=$((TOTAL+1))
  FLOW_NAME=$(basename "$FLOW" .maestro.yaml)
  echo "▶ Running Maestro flow: $FLOW_NAME"
  for PLATFORM in ios android; do
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
      *)            FAILED=$((FAILED+1)); echo "  ✗ $FLOW_NAME @ $PLATFORM ($STATUS)" ;;
    esac
    echo "$RESULT" > "${PHASE_DIR}/flow-${FLOW_NAME}-${PLATFORM}.json"
  done
done

echo "5c Mobile Flow: ${TOTAL} flow(s), ${FAILED} failed"
[ $FAILED -gt 0 ] && echo "⚠ Non-fatal — 5c_fix + 5e regression will re-run failures."

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_mobile_flow" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_mobile_flow.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_mobile_flow 2>/dev/null || true
```

Display:
```
5c Mobile Flow:
  Flows: {TOTAL} total, {FAILED} failed
  Per-platform: ios {N}/{TOTAL} | android {N}/{TOTAL}
```

---

After ALL active step markers touched (per-profile set), return to entry
SKILL.md → STEP 4 (goal verification + codegen).
