# Environment Commands (Shared Reference)

Referenced by sandbox-test.md, execute-verify.md, verify.md. Provides reusable command patterns that read from vg.config.md.

Prerequisite: config-loader.md already loaded (variables available).

## dev_start(env)

Ensure app is running before review/test. For local: start dev server with hotreload on worktree-specific ports. For sandbox: verify already running.

**Called automatically by review.md and test.md before browser steps.**

```bash
# 1. Check if already running — replace ALL port placeholders dynamically
HEALTH_CMD="$DEPLOY_HEALTH"
for key in $PORTS; do
  HEALTH_CMD=$(echo "$HEALTH_CMD" | sed "s/{${key}_port}/${PORTS[$key]}/g")
done
if [ -n "$HEALTH_CMD" ]; then
  eval "$HEALTH_CMD" 2>/dev/null && {
    echo "App already running. Health: OK"
    return 0
  }
fi

# 2. If local env — start infra first (WSL services, shared across worktrees)
if [ -z "$RUN_PREFIX" ]; then
  INFRA_START=config.environments[env].infra_start
  if [ -n "$INFRA_START" ]; then
    echo "Starting local infrastructure..."
    eval "$INFRA_START"
    sleep 2
  fi
fi

# 3. Start dev server (local only — sandbox uses deploy())
if [ -z "$RUN_PREFIX" ]; then
  DEV_CMD=config.environments[env].dev_command
  if [ -n "$DEV_CMD" ]; then
    # ⛔ HARD GATE (tightened 2026-04-17): validate placeholders BEFORE replacing.
    # Silent mismatch ({database_port} with no matching config.ports.database key)
    # caused prod bugs — typo placeholders ran literally, service bound wrong port.
    DECLARED=$(echo "$DEV_CMD" | grep -oE '\{[a-z_]+_port\}' | sort -u)
    for ph in $DECLARED; do
      key=$(echo "$ph" | sed 's/^{//; s/_port}$//')
      if [ -z "${PORTS[$key]+_}" ]; then
        echo "⛔ dev_command references ${ph} but config.ports has no key '${key}'."
        echo "   Defined ports: ${!PORTS[@]}"
        echo "   Fix: add '${key}' to config.ports.<role>, OR remove ${ph} from dev_command."
        return 1
      fi
    done

    # Replace port placeholders with worktree-resolved values (dynamic from config keys)
    # For each key in $PORTS map: replace {key_port} with resolved port value
    for key in $PORTS; do
      DEV_CMD=$(echo "$DEV_CMD" | sed "s/{${key}_port}/${PORTS[$key]}/g")
    done
    DEV_CMD=$(echo "$DEV_CMD" | sed "s/{db_name}/$DB_NAME/g")

    # Post-replacement check: ensure no {*_port} leftover
    LEFTOVER=$(echo "$DEV_CMD" | grep -oE '\{[a-z_]+_port\}' | head -1)
    if [ -n "$LEFTOVER" ]; then
      echo "⛔ dev_command still contains unresolved placeholder: $LEFTOVER"
      return 1
    fi

    # ⛔ PRE-FLIGHT PORT SWEEP (tightened 2026-04-17 — GLOBAL, stack-agnostic):
    # Kill zombie processes holding our ports before starting dev.
    # Identity of "zombie" is project-specific → read from config.dev_process_markers
    # (list of regex patterns matching cmdline — e.g. ["node", "vite"] for JS stacks,
    # ["flutter"] for Flutter, ["uvicorn"] for Python, etc.). Fallback: ask user.
    ZOMBIE_MARKERS=$(echo "${config.dev_process_markers:-}" | tr ',' '|')
    for key in "${!PORTS[@]}"; do
      port="${PORTS[$key]}"
      [ -z "$port" ] && continue
      HOLDER=""
      if command -v lsof >/dev/null 2>&1; then
        HOLDER=$(lsof -iTCP:$port -sTCP:LISTEN -t 2>/dev/null | head -1)
      elif command -v ss >/dev/null 2>&1; then
        HOLDER=$(ss -ltnp 2>/dev/null | grep ":${port}\b" | grep -oP 'pid=\K[0-9]+' | head -1)
      elif command -v netstat >/dev/null 2>&1; then
        HOLDER=$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":${port}\b" | awk '{print $NF}' | head -1)
      fi
      [ -z "$HOLDER" ] && continue

      HOLDER_CMD=""
      if [ -f "/proc/${HOLDER}/cmdline" ]; then
        HOLDER_CMD=$(tr '\0' ' ' < "/proc/${HOLDER}/cmdline" 2>/dev/null)
      elif command -v ps >/dev/null 2>&1; then
        HOLDER_CMD=$(ps -p "$HOLDER" -o command= 2>/dev/null)
      fi

      IS_ZOMBIE="unknown"
      if [ -n "$ZOMBIE_MARKERS" ] && echo "$HOLDER_CMD" | grep -qE "$ZOMBIE_MARKERS"; then
        IS_ZOMBIE="yes"
      fi

      if [ "$IS_ZOMBIE" = "yes" ]; then
        echo "⚠ Port $port held by zombie PID $HOLDER ($HOLDER_CMD) — killing..."
        if [[ "$(uname -s)" =~ MINGW|MSYS|CYGWIN ]]; then
          taskkill //F //PID "$HOLDER" 2>/dev/null
        else
          kill -9 "$HOLDER" 2>/dev/null
        fi
        sleep 1
      else
        echo "⛔ Port $port held by PID $HOLDER — $HOLDER_CMD"
        if [ -z "$ZOMBIE_MARKERS" ]; then
          echo "   config.dev_process_markers chưa cấu hình → không đoán được 'zombie' vs 'user process'."
        else
          echo "   Không match config.dev_process_markers ($ZOMBIE_MARKERS)."
        fi
        echo "   Options: (a) kill thủ công, (b) đổi port trong vg.config.md,"
        echo "            (c) --skip-dev-start (user tự start), (d) --sandbox"
        return 1
      fi
    done

    # ⛔ DEPENDENCY PRE-FLIGHT (config-driven, stack-agnostic):
    # Verify services listed in config.infra_deps.services are reachable BEFORE dev start.
    # Action on missing: config.infra_deps.unmet_behavior (block|warn|filter|continue).
    # If `filter`: apply config.infra_deps.services.{name}.dev_filter_flag to DEV_CMD
    # (generic flag append — works for any CLI: --filter, --skip, --exclude-*, etc).
    DEP_FAIL=""
    DEP_FAIL_FLAGS=""
    for dep in $(echo "${config.infra_deps.services:-}" | tr ',' ' '); do
      CHECK=$(eval echo "\${config.infra_deps.services.${dep}.check_local:-}")
      [ -z "$CHECK" ] && continue
      if ! eval "$CHECK" >/dev/null 2>&1; then
        DEP_FAIL="${DEP_FAIL} ${dep}"
        FLAG=$(eval echo "\${config.infra_deps.services.${dep}.dev_filter_flag:-}")
        [ -n "$FLAG" ] && DEP_FAIL_FLAGS="${DEP_FAIL_FLAGS} ${FLAG}"
      fi
    done
    if [ -n "$DEP_FAIL" ]; then
      UNMET="${config.infra_deps.unmet_behavior:-warn}"
      case "$UNMET" in
        block)
          echo "⛔ Infra deps not reachable:${DEP_FAIL}  (unmet_behavior=block)"
          echo "   Fix: start deps via ${config.infra_deps.start_cmd:-see vg.config.md}"
          return 1 ;;
        filter)
          if [ -n "$DEP_FAIL_FLAGS" ]; then
            DEV_CMD="${DEV_CMD}${DEP_FAIL_FLAGS}"
            echo "⚠ Deps missing:${DEP_FAIL}. Auto-applied config flags:${DEP_FAIL_FLAGS}"
          else
            echo "⚠ Deps missing:${DEP_FAIL}. No dev_filter_flag in config → run as-is (may crash)."
          fi ;;
        warn|*)
          echo "⚠ Deps missing:${DEP_FAIL}. unmet_behavior=${UNMET} → proceed, may crash."
          ;;
      esac
    fi

    # ⛔ OS RESOURCE WARNING (config-driven):
    # Projects with many concurrent dev processes can exhaust OS resources
    # (Windows ephemeral ports, Linux FDs, macOS kqueue). Threshold + mitigations
    # come from config.dev_os_limits (keyed by host OS). If unset, skip silently.
    HOST_OS=$(uname -s 2>/dev/null || echo "Unknown")
    OS_KEY=""
    if [[ "$HOST_OS" =~ MINGW|MSYS|CYGWIN|Windows ]]; then OS_KEY="windows"
    elif [[ "$HOST_OS" = "Darwin" ]]; then OS_KEY="macos"
    elif [[ "$HOST_OS" = "Linux" ]]; then OS_KEY="linux"
    fi
    if [ -n "$OS_KEY" ]; then
      PORT_THRESHOLD=$(eval echo "\${config.dev_os_limits.${OS_KEY}.warn_ports_above:-0}")
      if [ "${PORT_THRESHOLD:-0}" -gt 0 ] && [ "${#PORTS[@]}" -ge "$PORT_THRESHOLD" ]; then
        HINTS=$(eval echo "\${config.dev_os_limits.${OS_KEY}.mitigations:-}")
        echo "⚠ ${HOST_OS}: ${#PORTS[@]} ports ≥ threshold ${PORT_THRESHOLD}. Resource risk."
        [ -n "$HINTS" ] && echo "   Mitigations: $HINTS"
        echo "   Or: --sandbox to bypass local OS limits."
      fi
    fi

    echo "Starting dev server (worktree $WORKTREE_INDEX): $DEV_CMD"
    # Capture stderr to log for post-mortem diagnosis
    DEV_LOG="${VG_TMP:-/tmp}/vg-dev-${WORKTREE_INDEX:-0}.log"
    eval "$DEV_CMD" > "$DEV_LOG" 2>&1 &
    DEV_PID=$!
    echo "Dev server PID: $DEV_PID (log: $DEV_LOG)"

    # 4. Wait for health check to pass WITH early-exit detection
    TIMEOUT=${config.environments[env].dev_health_timeout:-30}
    ELAPSED=0
    while [ $ELAPSED -lt $TIMEOUT ]; do
      # Early-exit detection: if Turbo fail-fast killed the process, don't wait full timeout
      if ! kill -0 "$DEV_PID" 2>/dev/null; then
        echo "⛔ Dev process exited early (PID $DEV_PID dead)."
        diagnose_dev_failure "$DEV_LOG" "$DEV_CMD"
        return 1
      fi
      if eval "$HEALTH_CMD" 2>/dev/null; then
        echo "App healthy after ${ELAPSED}s"
        return 0
      fi
      sleep 2
      ELAPSED=$((ELAPSED + 2))
    done

    echo "⛔ Health check not passing after ${TIMEOUT}s"
    diagnose_dev_failure "$DEV_LOG" "$DEV_CMD"
    return 1
  fi
else
  # Sandbox — just verify health, don't start
  if ! run_on_target "$DEPLOY_HEALTH" 2>/dev/null; then
    echo "App not running on sandbox. Run /vg:build first."
    STOP
  fi
fi
```

**Key behaviors:**
- **Local**: starts WSL infra → runs dev_command with port placeholders replaced → health poll
- **Sandbox**: only checks health (deploy() handles startup)
- **Multi-port**: `{api_port}`, `{web_port}` replaced with worktree-resolved values from config-loader
- **Idempotent**: if health passes on correct port, returns immediately
- **Shared infra**: WSL services (MongoDB, Redis) shared across all worktrees — only app ports differ
- **Auto-recovery (tightened 2026-04-17)**: zombie port holders auto-killed, infra deps checked, OS limits surfaced

## diagnose_dev_failure(log_file, dev_cmd)

**Called when dev_start fails. Stack-agnostic: pattern library loaded from config, NOT hardcoded.**

**Rationale:** Every stack has its own error vocabulary (Kafka `UNKNOWN_TOPIC`, Python `ImportError`, Rails `could not connect to server`, Flutter `Pub get failed`). VG is config-driven workflow, nên patterns phải cấu hình trong `vg.config.md`, workflow chỉ là engine apply pattern → classify → surface.

**Config schema** (in `vg.config.md`):
```yaml
dev_failure_patterns:
  - id: port-in-use
    match: "EADDRINUSE|address already in use"
    cause: "Port in use"
    fix:
      - "Kill holder manually, or use config.dev_process_markers auto-kill"
      - "Change port in config.ports"
  - id: kafka-topic-missing
    match: "UNKNOWN_TOPIC_OR_PARTITION|Topic.*does not exist"
    cause: "Kafka topic chưa tạo — worker crash"
    fix:
      - "Chạy scripts/create-topics.sh"
      - "config.infra_deps.services.kafka.dev_filter_flag để tự skip worker"
  - id: missing-env
    match: "process\\.env\\.[A-Z_]+ is undefined|Missing required env"
    extract: "process\\.env\\.[A-Z_]+"
    cause: "Env var thiếu: {matches}"
    fix:
      - "cp .env.example .env + điền values"
  # ... add per stack/project
```

**Generic (always-on) patterns** — KHÔNG hardcode, chỉ 3 thứ universal:
1. Log tail (always dump last N lines regardless of match)
2. Port in use — `EADDRINUSE` là POSIX errno, mọi stack TCP đều trả về
3. Generic permission/FD errors — `EACCES|EMFILE|ENOBUFS` là POSIX errno

Everything else (Kafka, DB, Turbo, TypeScript, etc.) → come from config.

```bash
diagnose_dev_failure() {
  local LOG="$1"
  local CMD="$2"
  [ ! -f "$LOG" ] && { echo "No log captured at $LOG — cannot diagnose."; return; }

  echo ""
  echo "═══════════════════════════════════════════════"
  echo "  DEV FAILURE DIAGNOSIS"
  echo "═══════════════════════════════════════════════"
  local TAIL_LINES="${config.dev_failure_log_tail:-30}"
  echo "Log tail ($TAIL_LINES lines): $LOG"
  tail -${TAIL_LINES} "$LOG" | sed 's/^/  │ /'
  echo ""

  local CAUSES=() FIXES=()

  # --- GENERIC POSIX patterns (always on, stack-agnostic) ---
  if grep -qE "EADDRINUSE|address already in use" "$LOG"; then
    local BAD_PORT=$(grep -oE "(EADDRINUSE|address already in use)[^0-9]*([0-9]{2,5})" "$LOG" | grep -oE "[0-9]{2,5}" | head -1)
    CAUSES+=("Port in use: ${BAD_PORT:-unknown}")
    FIXES+=("Kill holder, change port trong config.ports, hoặc bật config.dev_process_markers để auto-kill")
  fi
  if grep -qE "EACCES|permission denied" "$LOG"; then
    CAUSES+=("Permission denied (POSIX EACCES)")
    FIXES+=("Check file ownership + mount permissions")
  fi
  if grep -qE "ENOBUFS|EMFILE|no buffer space|too many open files" "$LOG"; then
    CAUSES+=("OS resource pool exhausted (EMFILE/ENOBUFS)")
    FIXES+=("Xem config.dev_os_limits.${OS_KEY:-host}.mitigations cho host OS của bạn")
    FIXES+=("--sandbox để bypass local OS limits")
  fi

  # --- CONFIG-DRIVEN patterns ---
  # Workflow reads config.dev_failure_patterns[] — each item: {id, match, cause, extract?, fix[]}
  # Python helper parses the YAML list (env-command is bash, delegating YAML parse to python).
  if [ -n "${config.dev_failure_patterns}" ]; then
    local MATCHES=$(${PYTHON_BIN} - <<PY 2>/dev/null
import os, re, sys
try:
    import yaml
except ImportError:
    sys.exit(0)
cfg_path = ".claude/vg.config.md"
try:
    with open(cfg_path, encoding="utf-8") as f:
        raw = f.read()
    fm = re.search(r'^---\n(.*?)\n---', raw, re.DOTALL)
    cfg = yaml.safe_load(fm.group(1)) if fm else {}
except Exception:
    sys.exit(0)
patterns = cfg.get("dev_failure_patterns") or []
log = open(os.environ["LOG"], encoding="utf-8", errors="replace").read()
for p in patterns:
    m = re.search(p.get("match",""), log)
    if not m: continue
    cause = p.get("cause","")
    if p.get("extract"):
        hits = sorted(set(re.findall(p["extract"], log)))[:5]
        cause = cause.replace("{matches}", ", ".join(hits))
    print(f"CAUSE::{cause}")
    for fx in p.get("fix", []):
        print(f"FIX::{fx}")
PY
    )
    while IFS= read -r line; do
      case "$line" in
        CAUSE::*) CAUSES+=("${line#CAUSE::}") ;;
        FIX::*)   FIXES+=("${line#FIX::}") ;;
      esac
    done <<< "$MATCHES"
  fi

  # --- Report ---
  if [ ${#CAUSES[@]} -eq 0 ]; then
    echo "⚠ Không auto-classify được. Pattern library (${#config.dev_failure_patterns[@]:-0} patterns) không match."
    echo "  Manual steps:"
    echo "    - Đọc log tail phía trên"
    echo "    - Thêm pattern vào config.dev_failure_patterns để lần sau auto-diagnose"
    echo "    - Escape: --sandbox hoặc --skip-dev-start"
  else
    echo "Detected causes (${#CAUSES[@]}):"
    for c in "${CAUSES[@]}"; do echo "  • $c"; done
    echo ""
    echo "Proposed fixes:"
    local i=1
    for f in "${FIXES[@]}"; do echo "  ${i}) $f"; i=$((i+1)); done
    echo ""
    echo "  Escape hatches:"
    echo "    --sandbox       (skip local, dùng remote env)"
    echo "    --skip-dev-start (user đã start thủ công)"
  fi

  # Persist diagnosis as YAML (downstream: review.md fix loop, accept.md surface)
  {
    echo "timestamp: $(date -u +%FT%TZ)"
    echo "log: $LOG"
    echo "causes:"
    for c in "${CAUSES[@]}"; do echo "  - \"$c\""; done
    echo "fixes:"
    for f in "${FIXES[@]}"; do echo "  - \"$f\""; done
  } > "${PHASE_DIR:-${VG_TMP:-/tmp}}/.dev-failure-diagnosis.yaml" 2>/dev/null
}
```

**Config keys referenced (all optional, workflow works without them):**
- `dev_process_markers` — regex matching cmdline of YOUR dev processes (zombie kill safety)
- `dev_failure_patterns[]` — pattern library: `{id, match, cause, extract?, fix[]}`
- `dev_failure_log_tail` — how many log lines to dump (default 30)
- `dev_os_limits.{windows|linux|macos}.{warn_ports_above, mitigations}` — OS-specific hints
- `infra_deps.services.{name}.{check_local, start_cmd, dev_filter_flag}` — dep check + auto-filter
- `infra_deps.unmet_behavior` — `block|warn|filter|continue` (default `warn`)

**Escape hatch flags** (recognized by review.md / test.md):
- `--sandbox` — skip local dev entirely
- `--skip-dev-start` — external process running
- `--allow-partial-infra` — proceed with degraded deps

**Migration note:** Existing projects không có `dev_failure_patterns` vẫn chạy được — chỉ mất classification của stack-specific errors. Thêm dần vào config theo error thực tế gặp.

## deploy(env)

Full deploy sequence. Reads config, not hardcoded.

```bash
# 1. Record SHAs for rollback
if [ -n "$RUN_PREFIX" ]; then
  PREV_SHA=$(run_on_target "git rev-parse --short HEAD")
else
  PREV_SHA=$(git rev-parse --short HEAD)
fi
LOCAL_SHA=$(git rev-parse --short HEAD)

# 2. Pre-deploy (runs locally — e.g. git push)
PRE_CMD="{from config: environments[env].deploy.pre}"
if [ -n "$PRE_CMD" ]; then
  eval "$PRE_CMD"
fi

# 3. Build + restart on target
run_on_target "$DEPLOY_BUILD && $DEPLOY_RESTART"

# 4. Wait for startup
sleep 5

# 5. Health check
run_on_target "$DEPLOY_HEALTH"
```

If health check fails → rollback:
```bash
run_on_target "$DEPLOY_ROLLBACK"
```

## preflight(env)

Check all services for environment. Dynamic — reads config.services[env].

```bash
SERVICES=config.services[env]
ALL_OK=true

for each service in SERVICES:
  RESULT=$(run_on_target "${service.check}" 2>&1)
  if exit_code == 0:
    echo "--- ${service.name} --- OK"
  else:
    if service.required == true:
      echo "--- ${service.name} --- REQUIRED, BLOCKING"
      ALL_OK=false
    else:
      echo "--- ${service.name} --- optional, down but continuing"

if ! ALL_OK:
  STOP: "Required services down. Fix before proceeding."
```

## test(env, type)

```bash
if type == "unit":
  run_on_target "$TEST_RUNNER"
elif type == "e2e":
  # E2E always via MCP Playwright (local, visible browser)
  # Orchestrator drives directly, not delegated to remote
  echo "E2E via MCP Playwright — see sandbox-test-e2e.md"
```

## typecheck(env)

```bash
# Use typecheck from config if defined, else default
TYPECHECK_CMD=config.environments[env].typecheck OR "$PACKAGE_MANAGER exec tsc --noEmit"
run_on_target "$TYPECHECK_CMD"
```

## contract_verify_grep(phase_dir, target)

Grep-based API contract verification. No AI needed.

`target` = "backend" | "frontend" | "both"

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
if [ ! -f "$CONTRACTS" ]; then
  echo "No API-CONTRACTS.md found. Skip contract verify."
  return 0
fi

MISMATCHES=0

if [ "$target" = "backend" ] || [ "$target" = "both" ]; then
  # Extract endpoints from contracts
  # grep BE routes + Zod schemas → compare
  # For each endpoint in contracts:
  #   grep -r "router\.(get|post|put|delete|patch).*{endpoint}" $API_ROUTES_PATH
  #   If not found → mismatch++
  #   If found → grep Zod schema fields → compare with contract fields
  echo "Checking BE routes vs contracts..."
fi

if [ "$target" = "frontend" ] || [ "$target" = "both" ]; then
  # grep FE api calls (fetch, axios, api.) → compare with contract endpoints
  # grep FE response field reads → compare with contract response fields
  echo "Checking FE API calls vs contracts..."
fi

if [ $MISMATCHES -gt 0 ]; then
  echo "BLOCK: $MISMATCHES contract mismatches found"
  return 1
fi
```

## contract_verify_curl(phase_dir)

Runtime API contract verification via curl + jq.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
# For each endpoint in contracts:
#   curl -sf "${BASE_URL}${endpoint}" | jq -r 'keys[]' > ${VG_TMP}/actual_keys
#   Extract expected keys from contracts > ${VG_TMP}/expected_keys
#   diff ${VG_TMP}/expected_keys ${VG_TMP}/actual_keys
#   Mismatch → report
```

## seed_smoke(env)

Run seed command (if configured) and verify data actually loaded.

```bash
SEED_CMD=config.environments[env].seed_command
if [ -z "$SEED_CMD" ]; then
  # No seed configured — skip silently (not a blocker)
  return 0
fi

echo "Running seed: $SEED_CMD"
run_on_target "$SEED_CMD"
SEED_EXIT=$?

if [ $SEED_EXIT -ne 0 ]; then
  echo "WARN: Seed command exited with code $SEED_EXIT"
  return $SEED_EXIT
fi

# After seed command exits 0, verify data actually loaded.
# ⛔ HARD GATE (tightened 2026-04-17): seed_verify_endpoint from config must return
# non-empty row count. Grep "ok" on a generic /health is insufficient — returned
# {"status":"healthy"} with empty DB passes grep but seed clearly failed.
if [ $SEED_EXIT -eq 0 ]; then
  if [ -n "$BASE_URL" ]; then
    # config.environments[env].seed_verify_endpoint — e.g., /api/sites?limit=1 OR /api/health/seed-count
    SEED_VERIFY_EP="${config.environments[env].seed_verify_endpoint:-/api/health}"
    SEED_VERIFY_JSONPATH="${config.environments[env].seed_verify_jsonpath:-.data | length}"
    SEED_VERIFY_MIN="${config.environments[env].seed_verify_min_count:-1}"

    SEED_BODY=$(curl -sf "${BASE_URL}${SEED_VERIFY_EP}" 2>/dev/null)
    if [ -z "$SEED_BODY" ]; then
      echo "⛔ Seed verify: ${BASE_URL}${SEED_VERIFY_EP} returned empty/error."
      echo "   Cannot confirm seed loaded data."
      return 1
    fi

    # Use jq to extract count — if jq unavailable, fall back to non-empty JSON array check
    if command -v jq >/dev/null 2>&1; then
      SEED_COUNT=$(echo "$SEED_BODY" | jq -r "$SEED_VERIFY_JSONPATH" 2>/dev/null)
    else
      # Fallback: count occurrences of '"_id"' or similar tokens in body
      SEED_COUNT=$(echo "$SEED_BODY" | grep -oE '"_id"|"id":' | wc -l | tr -d ' ')
    fi

    if [ -z "$SEED_COUNT" ] || ! [[ "$SEED_COUNT" =~ ^[0-9]+$ ]]; then
      SEED_COUNT=0
    fi

    if [ "$SEED_COUNT" -lt "$SEED_VERIFY_MIN" ]; then
      echo "⛔ Seed verify FAILED: ${SEED_VERIFY_EP} returned count=${SEED_COUNT} (min required: ${SEED_VERIFY_MIN})"
      echo "   Seed command exit 0 but DB appears empty. Check seed output + database connection."
      return 1
    fi

    echo "✓ Seed verify OK: count=${SEED_COUNT} at ${SEED_VERIFY_EP}"
  else
    echo "⛔ Seed succeeded but BASE_URL missing — cannot verify. Configure environments[env].base_url."
    return 1
  fi
fi
```

**Key behaviors:**
- **No seed_command in config**: skip silently, return 0
- **Seed exits non-zero**: warn and propagate exit code
- **Seed exits 0 but verify count < min**: HARD FAIL (no more silent "health OK grep")
- **Missing BASE_URL**: HARD FAIL (force config to be complete)
- **Called by**: review.md (2b-0), test.md (environment prep)

## element_count(file_path)

Count UI elements in a single file using scan_patterns from config.

```bash
FILE="$1"
COUNTS="{}"

for pattern_name in $SCAN_PATTERNS; do
  REGEX="${SCAN_PATTERNS[$pattern_name]}"
  # Join array into grep -E alternation: "pattern1|pattern2|pattern3"
  COUNT=$(grep -cE "$REGEX" "$FILE" 2>/dev/null || echo 0)
  COUNTS[$pattern_name]=$COUNT
done

echo "$COUNTS"  # JSON: {"modals": 3, "tabs": 2, "tables": 1, ...}
```

## credentials(env, role)

```
Read config.credentials[env]
Find entry where role == {role}
Return: { role, domain, email, password }
If not found: STOP — "No credentials for role '{role}' in environment '{env}'. Update vg.config.md."
```

## crossai_strategy()

Count CLIs from config.crossai_clis:

| Count | Strategy | Behavior |
|-------|----------|----------|
| 0 | Skip | Skip all CrossAI. Return verdict=pass (no review). |
| 1 | Single | Run 1 CLI. Verdict = its verdict. No consensus needed. |
| 2 | Fast-fail | Run both. Agree → done. Disagree → flag for user. |
| 3+ | Full/Fast | Full consensus for total-check. Fast-fail (first 2) for light reviews, 3rd on disagreement. |

Spawn command per CLI: read `config.crossai_clis[N].command`, substitute `{prompt}` and `{context}` placeholders.
