# test regression + security (STEP 7)

5 steps: 5e_regression, 5f_security_audit, 5f_mobile_security_audit, 5g_performance_check, 5h_security_dynamic.

<HARD-GATE>
Profile gating (each step runs only for its listed profiles):
- `web-fullstack`     → 5e_regression + 5f_security_audit + 5g_performance_check + 5h_security_dynamic
- `web-backend-only`  → 5e_regression + 5f_security_audit + 5g_performance_check + 5h_security_dynamic
- `web-frontend-only` → 5e_regression + 5f_security_audit only (no perf/DAST)
- `mobile-*`          → 5e_regression + 5f_mobile_security_audit only

Each active step finishes with a marker touch + `vg-orchestrator mark-step test <step>`.
Skipping ANY active step = Stop hook block.

vg-load: no vg-load injection needed; orchestration-only.
5f_security_audit reads API-CONTRACTS.md directly (contract-code verbatim verification).
5g reads perf budgets from vg.config.md directly (no PLAN/TEST-GOALS AI context path).
5h reads no AI context files — pure DAST tooling.
</HARD-GATE>

---

## STEP 7.1 — regression run (5e_regression) [profile: all]

Run generated tests via CLI (not MCP):

```bash
run_on_target "cd ${PROJECT_PATH} && npx playwright test ${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts"
```

If playwright config for generated tests doesn't exist, create a minimal one at
`${GENERATED_TESTS_DIR}/playwright.config.generated.ts` with env vars from config.

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

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5e_regression" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5e_regression.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5e_regression 2>/dev/null || true
```

---

## STEP 7.2 — security audit (5f_security_audit) [profile: web-fullstack,web-backend-only,web-frontend-only]

HARD-GATE: mobile-* MUST skip this step (use 5f_mobile_security_audit instead).

Multi-tier security check. Tier 0 runs B8 structured validators (mandatory, 2026-04-23);
Tier 1-4 run grep heuristics.

### Tier 0: B8 structured validators (MANDATORY)

```bash
echo "━━━ 5f Tier 0: B8 security validators ━━━"
SEC_TIER0_EXIT=0

for V in secrets-scan verify-input-validation verify-authz-declared verify-goal-security verify-goal-perf verify-crud-surface-contract verify-security-baseline; do
  OUT=$(${PYTHON_BIN:-python3} ".claude/scripts/validators/${V}.py" \
        --phase "${PHASE_NUMBER}" 2>&1)
  RC=$?
  VERDICT=$(echo "$OUT" | ${PYTHON_BIN:-python3} -c \
    "import json,sys; d=json.loads(sys.stdin.read().splitlines()[-1]); print(d.get('verdict','UNKNOWN'))" \
    2>/dev/null || echo "UNKNOWN")
  echo "  [${V}] verdict=${VERDICT} rc=${RC}"
  echo "$OUT" | ${PYTHON_BIN:-python3} -c \
    "import json,sys; d=json.loads(sys.stdin.read().splitlines()[-1]); [print('    ─', e.get('type'), e.get('message','')) for e in d.get('evidence', [])]" \
    2>/dev/null || true
  if [ "$RC" -ne 0 ]; then
    SEC_TIER0_EXIT=1
  fi
done

if [ "$SEC_TIER0_EXIT" -ne 0 ]; then
  echo "  ⛔ Tier 0 BLOCK — fix B8 findings before rerun /vg:test"
  # Fall through to show Tier 1-4 for complete picture; exit rolled into final verdict
fi
```

Config gate: `config.security.skip_tier0` (default false). Set true only for legacy phases.

### Tier 1: Built-in Security Grep (always, <10 sec)

```bash
API_ROUTES_PATTERN=$(vg_config_get code_patterns.api_routes "apps/api/**/*.ts")
WEB_PAGES_PATTERN=$(vg_config_get code_patterns.web_pages "apps/web/**/*.tsx")
CHANGED_FILES=$(git diff --name-only HEAD~${COMMIT_COUNT} HEAD -- "$API_ROUTES_PATTERN" "$WEB_PAGES_PATTERN" 2>/dev/null)
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

Result routing: CRITICAL (secrets, injection) → FAIL | HIGH (auth bypass) → FAIL |
MEDIUM → GAPS_FOUND | LOW → logged only.

### Tier 3: Contract-code verbatim verification

```bash
COPY_MISMATCHES=0

# Extract auth middleware lines from contract Block 1
${PYTHON_BIN} -c "
import re
from pathlib import Path
text = Path('${PHASE_DIR}/API-CONTRACTS.md').read_text(encoding='utf-8')
for m in re.finditer(r'###\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)', text):
    method, path = m.groups()
    rest = text[m.end():m.end()+2000]
    auth_match = re.search(r'\`\`\`\w+\n(.*?requireRole.*?)\n', rest, re.DOTALL)
    if auth_match:
        for line in auth_match.group(1).splitlines():
            if 'requireRole' in line or 'requireAuth' in line:
                print(f'{path}\t{line.strip()}')
                break
" 2>/dev/null > "${VG_TMP}/contract-auth-lines.txt"

while IFS=$'\t' read -r ENDPOINT AUTH_LINE; do
  [ -z "$ENDPOINT" ] && continue
  ROUTE_FILE=$(grep -rl "${ENDPOINT}" ${config.code_patterns.api_routes} 2>/dev/null | head -1)
  [ -z "$ROUTE_FILE" ] && continue
  KEY_PART=$(echo "$AUTH_LINE" | grep -oE "requireRole\(['\"][^'\"]+['\"]\)" || true)
  if [ -n "$KEY_PART" ]; then
    if ! grep -q "$KEY_PART" "$ROUTE_FILE" 2>/dev/null; then
      echo "  CRITICAL: ${ENDPOINT} — contract says '${KEY_PART}' but route file doesn't contain it"
      COPY_MISMATCHES=$((COPY_MISMATCHES + 1))
    fi
  fi
done < "${VG_TMP}/contract-auth-lines.txt"

# FE error shape — verify reads standard API envelope, not AxiosError.message
WEB_PAGES_PATTERN=$(vg_config_get code_patterns.web_pages "apps/web/**/*.tsx")
CHANGED_FE=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- "$WEB_PAGES_PATTERN" 2>/dev/null)
if [ -n "$CHANGED_FE" ]; then
  BAD_TOAST=$(echo "$CHANGED_FE" | xargs grep -l "toast.*error\.message\b\|toast.*err\.message\b" 2>/dev/null | \
    xargs grep -L "error\.response.*data.*error.*user_message\|error\.response.*data.*error.*message\|\.data\.error\.user_message\|\.data\.error\.message" 2>/dev/null | head -5)
  if [ -n "$BAD_TOAST" ]; then
    echo "  HIGH: FE files read error.message (AxiosError) instead of error.response.data.error.user_message || error.response.data.error.message:"
    echo "$BAD_TOAST" | sed 's/^/    /'
    COPY_MISMATCHES=$((COPY_MISMATCHES + 1))
  fi

  # Check FE files access response.data correctly (not response.data.data)
  DOUBLE_DATA=$(echo "$CHANGED_FE" | xargs grep -n "response\.data\.data\." 2>/dev/null | head -5)
  if [ -n "$DOUBLE_DATA" ]; then
    echo "  WARN: FE files access response.data.data (double nesting) — check if API wraps in data envelope:"
    echo "$DOUBLE_DATA" | sed 's/^/    /'
  fi
fi

if [ "$COPY_MISMATCHES" -gt 0 ]; then
  echo "  ⛔ ${COPY_MISMATCHES} contract-code mismatches — code doesn't match contract blocks"
fi
```

### Tier 4: Runtime auth smoke (if server running)

```bash
if [ -n "$BASE_URL" ]; then
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
  Tier 0 B8 validators: {secrets,input-validation,authz,crud-surface} {PASS|BLOCK|WARN}
  Tier 1 grep: {findings} ({critical}/{high}/{medium}/{low})
  Tier 2 deep: {tool used|skipped}
  Tier 3 contract-code verify: {COPY_MISMATCHES} mismatches (auth role + error shape)
  Tier 4 runtime no-token: {NEG_FAILURES} open endpoints
  Result: {PASS|GAPS_FOUND|FAIL}
```

Final verdict rule: `SEC_TIER0_EXIT != 0` → FAIL regardless of Tier 1-4 outcome.
B8 validators are structured truth gates; grep tiers are advisory complements.

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5f_security_audit" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5f_security_audit.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5f_security_audit 2>/dev/null || true
```

---

## STEP 7.3 — mobile security audit (5f_mobile_security_audit) [profile: mobile-*]

HARD-GATE: web-* MUST skip this step (use 5f_security_audit instead).

Mobile-specific grep-based scans. Complements build-time Gate 8 (privacy manifest
consistency) by checking ACTUAL source — secrets, cleartext traffic, weak crypto,
insecure storage. Runs ≤10 seconds. CRITICAL/HIGH → FAIL. MEDIUM → GAPS_FOUND. LOW → logged.

```bash
SEC_FINDINGS=()
SEC_DIR="${PHASE_DIR}/mobile-security"
mkdir -p "$SEC_DIR"

# --- Scan 1: Hardcoded API keys / secrets ---
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

# --- Scan 2: iOS cleartext traffic (NSAllowsArbitraryLoads) ---
IOS_PLIST=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                  g && /^    permission_audit:/{p=1;next}
                  p && /ios_plist_path:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print;exit}' \
             .claude/vg.config.md | head -1)
if [ -n "$IOS_PLIST" ] && [ -f "$IOS_PLIST" ]; then
  if grep -A1 "NSAllowsArbitraryLoads" "$IOS_PLIST" 2>/dev/null | grep -q "<true/>"; then
    SEC_FINDINGS+=("HIGH|ios_cleartext_traffic|NSAllowsArbitraryLoads=true in ${IOS_PLIST} — allows HTTP to any domain")
  fi
fi

# --- Scan 3: Android cleartext traffic + exported components ---
AND_MANIFEST=$(awk '/^mobile:/{m=1;next} m && /^  gates:/{g=1;next}
                    g && /^    permission_audit:/{p=1;next}
                    p && /android_manifest_path:/{gsub(/^[^:]+:[[:space:]]*/,""); gsub(/[\"'"'"']/,""); print;exit}' \
              .claude/vg.config.md | head -1)
if [ -n "$AND_MANIFEST" ] && [ -f "$AND_MANIFEST" ]; then
  if grep -q 'android:usesCleartextTraffic="true"' "$AND_MANIFEST" 2>/dev/null; then
    SEC_FINDINGS+=("HIGH|android_cleartext_traffic|usesCleartextTraffic=\"true\" in ${AND_MANIFEST}")
  fi
  EXPORTED=$(grep -nE 'android:exported="true"' "$AND_MANIFEST" 2>/dev/null | grep -v 'android:permission=' | head -5 || true)
  if [ -n "$EXPORTED" ]; then
    COUNT=$(echo "$EXPORTED" | wc -l)
    SEC_FINDINGS+=("MEDIUM|android_exported_unprotected|${COUNT} exported component(s) without permission guard")
  fi
fi

# --- Scan 4: Weak crypto (MD5 / SHA-1) ---
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

# --- Scan 5: Insecure storage (plain AsyncStorage / UserDefaults / SharedPreferences) ---
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

# --- Scan 6: Debug/console.log in production paths ---
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

echo "5f Mobile Security Audit: C=$CRITICAL H=$HIGH M=$MEDIUM L=$LOW"
cat "$SEC_DIR/report.md" | tail -20

if [ "$CRITICAL" -gt 0 ] || [ "$HIGH" -gt 0 ]; then
  echo "⛔ Mobile security: CRITICAL/HIGH findings — verdict = FAILED"
  SECURITY_VERDICT="FAILED"
elif [ "$MEDIUM" -gt 0 ]; then
  SECURITY_VERDICT="GAPS_FOUND"
else
  SECURITY_VERDICT="PASSED"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5f_mobile_security_audit" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5f_mobile_security_audit.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5f_mobile_security_audit 2>/dev/null || true
```

V2 deferred: no deep semgrep/MobSF, no runtime network sniff (mitmproxy), no Frida/root-detection.

---

## STEP 7.4 — performance check (5g_performance_check) [profile: web-fullstack,web-backend-only]

HARD-GATE: web-frontend-only + mobile-* MUST skip this step.

Read performance budgets from config. Skip entirely if `perf_budgets` section absent.

```bash
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

### Check 1: API response time (if api_response_p95_ms set + running API)

```bash
if [ -n "$API_P95" ]; then
  PERF_FAILURES=0
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
    PERF_RESULT="GAPS_FOUND"
  else
    echo "  Performance: all endpoints within ${API_P95}ms budget"
    PERF_RESULT="PASS"
  fi
else
  PERF_RESULT="SKIP"
fi
```

### Check 2: Page load time (if page_load_s set + web profile)

```bash
if [ -n "$PAGE_LOAD" ] && [[ "$PROFILE" =~ web ]]; then
  PAGE_LOAD_MS=$((PAGE_LOAD * 1000))
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

### Check 3: Pre-prod static analysis (always, no running server needed)

```bash
STATIC_ISSUES=0

# 3a. Bundle size
MAX_BUNDLE=$(${PYTHON_BIN} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*max_bundle_kb:\s*(\d+)', line)
    if m: print(m.group(1)); break
else: print('')
" 2>/dev/null)

if [ -n "$MAX_BUNDLE" ]; then
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

# 3b. N+1 query patterns
CHANGED_SRC=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- '*.ts' '*.js' 2>/dev/null)
if [ -n "$CHANGED_SRC" ]; then
  N1_HITS=$(echo "$CHANGED_SRC" | xargs grep -l "for.*await\|forEach.*await\|\.map.*await" 2>/dev/null | head -5)
  if [ -n "$N1_HITS" ]; then
    echo "  ⚠ Potential N+1 query patterns (await inside loop):"
    echo "$N1_HITS" | sed 's/^/    /'
    STATIC_ISSUES=$((STATIC_ISSUES + 1))
  fi

  LEAN_MISS=$(echo "$CHANGED_SRC" | xargs grep -l "\.find(\|\.findOne(" 2>/dev/null | \
    xargs grep -L "\.lean()\|\.toArray()" 2>/dev/null | head -5)
  if [ -n "$LEAN_MISS" ]; then
    echo "  ⚠ MongoDB queries without .lean()/.toArray() — may allocate excess memory:"
    echo "$LEAN_MISS" | sed 's/^/    /'
  fi
fi

# 3c. Large file imports (>50KB source files)
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
5g Performance:
  API p95 budget: ${API_P95}ms — ${PERF_RESULT}
  Page load budget: ${PAGE_LOAD}s — ${PAGE_PERF_RESULT:-SKIP}
  Bundle size: ${BUNDLE_KB}KB / ${MAX_BUNDLE}KB budget
  Static analysis: ${STATIC_ISSUES} potential issues
  Note: Real p95 under load = production only
```

Performance failures → GAPS_FOUND (not FAIL — pre-prod is advisory).

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5g_performance_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5g_performance_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5g_performance_check 2>/dev/null || true
```

---

## STEP 7.5 — DAST dynamic security scan (5h_security_dynamic) [profile: web-fullstack,web-backend-only]

HARD-GATE: web-frontend-only + mobile-* + docs + cli-tool MUST skip this step.

Dynamic Application Security Testing (v2.5 Phase B.5). Runs after 5a_deploy +
5b_runtime_contract_verify. Spawns DAST tool (ZAP baseline active scan / Nuclei / fallback)
to send malicious payloads (SQLi, XSS, CSRF, SSRF, path traversal) to live endpoints.

Findings severity routing via `config.project_risk_profile`:
- `critical` → High/Critical finding = HARD BLOCK
- `moderate` → High = WARN, Medium = advisory
- `low` → all advisory

```bash
echo ""
echo "━━━ Step 5h — DAST (Dynamic Application Security Testing) ━━━"

SCAN_URL="${SANDBOX_URL:-}"
if [ -z "$SCAN_URL" ]; then
  SCAN_URL="${LOCAL_API_URL:-http://localhost:3001}"
fi

SCAN_MODE="full"
[[ "$ARGUMENTS" =~ --dast-baseline ]] && SCAN_MODE="baseline"
[[ "$ARGUMENTS" =~ --skip-dast ]] && {
  echo "⚠ DAST skipped via --skip-dast (logged to override-debt)"
  type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
    "--skip-dast" "$PHASE_NUMBER" "test.5h" "user skipped DAST scan" \
    "test-dast-skip-${PHASE_NUMBER}"
  touch "${PHASE_DIR}/.step-markers/5h_security_dynamic.done"
  :
}

if [[ ! "$ARGUMENTS" =~ --skip-dast ]]; then
  DAST_REPORT="${PHASE_DIR}/dast-report.json"

  bash .claude/commands/vg/_shared/lib/dast-runner.sh \
    "${PHASE_NUMBER}" "${SCAN_URL}" "${SCAN_MODE}" "${DAST_REPORT}"
  RUNNER_RC=$?

  if [ "$RUNNER_RC" -eq 2 ]; then
    echo "⚠ DAST runner: no tool available (Docker/Nuclei missing), skipped."
    echo "   Install ZAP (docker pull zaproxy/zaproxy) or nuclei to enable."
  fi

  RISK_PROFILE="${CONFIG_PROJECT_RISK_PROFILE:-moderate}"
  REPORT_OUT=$(${PYTHON_BIN:-python3} \
    .claude/scripts/validators/dast-scan-report.py \
    --phase "${PHASE_NUMBER}" \
    --report "${DAST_REPORT}" \
    --risk-profile "${RISK_PROFILE}" 2>&1)
  REPORT_RC=$?

  echo "$REPORT_OUT" | tail -1 | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    verdict = d.get('verdict', '?')
    ev = d.get('evidence', [])
    print(f'  DAST verdict: {verdict} ({len(ev)} finding-group(s))')
    for e in ev[:5]:
        print(f'    - {e.get(\"type\")}: {e.get(\"message\",\"\")[:200]}')
except Exception:
    pass
" 2>/dev/null || true

  if [ "$REPORT_RC" -ne 0 ]; then
    if [[ "$ARGUMENTS" =~ --allow-dast-findings ]]; then
      echo "⚠ DAST findings — OVERRIDE accepted via --allow-dast-findings"
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--allow-dast-findings" "$PHASE_NUMBER" "test.5h.dast" \
        "Critical/High DAST findings accepted by user" \
        "test-dast-${PHASE_NUMBER}"
    else
      echo ""
      echo "⛔ DAST found Critical/High vulnerabilities at ${SCAN_URL}"
      echo "   Fix each finding (check dast-report.json detail), re-run /vg:test."
      echo "   Override: /vg:test ${PHASE_NUMBER} --allow-dast-findings"
      exit 1
    fi
  fi
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5h_security_dynamic" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5h_security_dynamic.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5h_security_dynamic 2>/dev/null || true
```

---

After ALL active step markers touched (per-profile set), return to entry
SKILL.md → STEP 8 (fix loop / escalation).
