# test runtime (STEP 3)

4 steps: 5b_runtime_contract_verify, 5c_smoke, 5c_flow, 5c_mobile_flow.

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

### 5b-2: Idempotency check (auto-ON for critical_domains)

Skip if `config.critical_domains` empty, no matching endpoints, or `$BASE_URL` unset.
Billing/auth/payout endpoints MUST be idempotent — double-submit must NOT duplicate.

```bash
CRITICAL_DOMAINS="${config.critical_domains:-billing,auth,payout,payment,transaction}"
IDEMPOTENCY_FAILS=0

# Phase F Task 30 — endpoint enumeration via vg-load index, not flat read
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
  echo "Idempotency check: ${CRITICAL_COUNT} critical-domain mutation endpoints"
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
fi
```

Result: `IDEMPOTENCY_FAILS > 0` → FAIL (same severity as contract mismatch).

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
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5b_runtime_contract_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5b_runtime_contract_verify.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5b_runtime_contract_verify 2>/dev/null || true
```

---

## STEP 3.2 — smoke check (5c_smoke) [profile: web-fullstack,web-frontend-only]

HARD-GATE: web-backend-only + mobile-* MUST skip this step.

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
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_smoke" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_smoke.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_smoke 2>/dev/null || true
```

---

## STEP 3.3 — multi-page flow verify (5c_flow) [profile: web-fullstack,web-frontend-only]

HARD-GATE: web-backend-only + mobile-* MUST skip this step.

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
  # R6 Task 14 (2026-05-05): fail-loud. After Task 14, 5d_mobile_codegen runs
  # BEFORE 5c_mobile_flow (must_touch_markers order swap in test.md). This
  # branch is now UNREACHABLE in normal flow — codegen produces .maestro.yaml
  # files first. If we still hit it, codegen actually failed silently or
  # flows_dir is misconfigured — both are real errors worth blocking.
  echo "⛔ 5c_mobile_flow ran with NO Maestro flows under ${FLOWS_DIR}." >&2
  echo "   Expected: 5d_mobile_codegen runs FIRST and produces .maestro.yaml files." >&2
  echo "   Actual: codegen marker present (you got here) but flows_dir empty." >&2
  echo "   Likely causes:" >&2
  echo "     1. Codegen subagent failed silently — re-run /vg:test --only=5d_mobile_codegen" >&2
  echo "     2. flows_dir misconfigured in .claude/vg.config.md (mobile.e2e.flows_dir)" >&2
  echo "     3. Dry-run / --skip-codegen flag bypassed codegen — re-run without skip" >&2
  echo "" >&2
  echo "   To proceed without flows (record UNREACHABLE goals): use --skip-mobile-flow --override-reason" >&2

  # Allow override path — paired --skip-mobile-flow + --override-reason
  if [[ "$ARGUMENTS" =~ --skip-mobile-flow ]]; then
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      echo "⛔ --skip-mobile-flow requires --override-reason=<text>" >&2
      exit 1
    fi
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag "--skip-mobile-flow" \
      --reason "Empty mobile flows after codegen (phase ${PHASE_NUMBER})" \
      >/dev/null 2>&1 || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--skip-mobile-flow" "${PHASE_NUMBER}" "test.5c_mobile_flow" \
        "Empty Maestro flows after codegen; goals marked UNREACHABLE" "test-mobile-flow-empty"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "test.mobile_flow_empty_after_codegen" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"flows_dir\":\"${FLOWS_DIR}\"}" \
      2>/dev/null || true
    (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_mobile_flow" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_mobile_flow.done"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_mobile_flow 2>/dev/null || true
    exit 0
  fi
  exit 1
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
