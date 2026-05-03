# shellcheck shell=bash
# Surface Probe — bash function library (v1.9.2.3)
#
# Problem this solves:
#   v1.9.1 R1 shipped surface classification (ui/api/data/integration/time-driven)
#   + pure-backend fast-path (UI_GOAL_COUNT==0 → skip browser entirely).
#
#   BUT for mixed phase (some UI + some backend goals), backend goals don't get
#   probed — they fall to "no goal_sequences → NOT_SCANNED" in review phase 4b.
#
#   Example: phase 07.12 has 6 UI + 33 backend goals. Pure-backend fast-path
#   doesn't trigger. 33 backend goals → NOT_SCANNED → 4c-pre gate BLOCK.
#
# Design:
#   - 4 probe functions (one per non-ui surface), pure grep + config lookup
#   - Dispatcher `run_surface_probe(gid, surface, phase_dir)` routes to probe
#   - Fail-closed: unknown surface / missing config → no change (caller sees NOT_SCANNED)
#   - Config-driven: read code_patterns + infra_deps from vg.config.md, no stack assumption
#
# Exposed functions:
#   - run_surface_probe GOAL_ID SURFACE PHASE_DIR [TEST_GOALS_FILE]
#     → stdout: STATUS|EVIDENCE  (pipe-separated)
#     → STATUS ∈ {READY, BLOCKED, INFRA_PENDING, UNREACHABLE, SKIPPED}
#     → EVIDENCE: short string describing grep hit or missing piece
#
# Usage in review.md phase 4b (before NOT_SCANNED branch):
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-probe.sh"
#   PROBE=$(run_surface_probe "$gid" "$surface" "$PHASE_DIR" "$PHASE_DIR/TEST-GOALS.md")
#   STATUS=$(echo "$PROBE" | cut -d'|' -f1)
#   EVIDENCE=$(echo "$PROBE" | cut -d'|' -f2-)
#   # Apply to matrix; only fall to NOT_SCANNED if status == SKIPPED

# ═══════════════════════════════════════════════════════════════════════
# Helper: extract goal block from TEST-GOALS.md by ID
# ═══════════════════════════════════════════════════════════════════════
_surface_probe_get_goal_block() {
  local gid="$1"
  local test_goals="$2"
  [ -f "$test_goals" ] || { echo ""; return 1; }
  # Extract block starting at goal heading until next goal heading or EOF.
  # Tolerates these heading formats (all observed in real projects):
  #   ## Goal G-XX: title       (vgflow canonical)
  #   ## Goal G-XX — title      (em-dash variant)
  #   ## G-XX — title           (project format, "Goal" word omitted)
  #   ## G-XX: title
  #   ## G-XX - title           (ASCII hyphen)
  # Match logic: heading starts with `^## ` then optional `Goal `, then gid,
  # then any non-alphanumeric separator (space/colon/em-dash/hyphen/tab).
  awk -v gid="$gid" '
    $0 ~ "^##[ ]+(Goal[ ]+)?" gid "[^A-Za-z0-9_]" { in_block=1; print; next }
    in_block && $0 ~ "^##[ ]+(Goal[ ]+)?G-[0-9]+[^A-Za-z0-9_]" { exit }
    in_block { print }
  ' "$test_goals"
}

# Extract "Success criteria" bullets from goal block — multi-line
_surface_probe_get_criteria() {
  local block="$1"
  echo "$block" | awk '
    /^\*\*Success criteria:\*\*/ { in_sec=1; next }
    in_sec && /^\*\*/ { exit }
    in_sec { print }
  '
}

# ═══════════════════════════════════════════════════════════════════════
# probe_api — grep for route handler matching endpoint pattern
# ═══════════════════════════════════════════════════════════════════════
# Input: goal_id + goal_block (text)
# Logic: extract endpoint pattern (e.g. "POST /api/v1/xxx") from success_criteria
#        → grep apps/api/src (or similar from config) for matching route
# Returns: READY (handler found) | BLOCKED (no handler) | SKIPPED (can't parse endpoint)
probe_api() {
  local gid="$1"
  local block="$2"
  local phase_dir="${3:-}"
  local criteria
  criteria=$(_surface_probe_get_criteria "$block")

  # Extract HTTP method + path from criteria
  # Patterns: "GET /api/v1/xxx", "POST pixel.vollx.com/yyy", "PUT /foo"
  local endpoint_line
  endpoint_line=$(echo "$criteria" | grep -oE '\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+[/a-zA-Z0-9][a-zA-Z0-9._/:{}\-]*' | head -1)

  # Fallback 1: criteria written in natural language often omit explicit
  # method+path. Try path-only patterns (e.g. "/api/v1/credits/grant" or
  # "/internal/credit/use") that appear without an HTTP verb prefix.
  if [ -z "$endpoint_line" ]; then
    local path_only
    path_only=$(echo "$criteria" | grep -oE '/(api|internal|public)/[a-zA-Z0-9._/:{}\-]+' | head -1)
    if [ -n "$path_only" ]; then
      # Synthesize a method-agnostic endpoint_line; downstream grep treats
      # path as the discriminator anyway (frag extraction starts from path).
      endpoint_line="ANY ${path_only}"
    fi
  fi

  # Fallback 2: cross-reference goal_id in API-CONTRACTS.md (when phase_dir
  # is provided). Real-world TEST-GOALS often defer endpoint shape to the
  # contract artifact and only reference the goal by id.
  if [ -z "$endpoint_line" ] && [ -n "$phase_dir" ] && [ -f "${phase_dir}/API-CONTRACTS.md" ]; then
    local contract_endpoint
    contract_endpoint=$(grep -B2 -A4 "\b${gid}\b" "${phase_dir}/API-CONTRACTS.md" 2>/dev/null \
                        | grep -oE '\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+[/a-zA-Z0-9][a-zA-Z0-9._/:{}\-]*' \
                        | head -1)
    if [ -n "$contract_endpoint" ]; then
      endpoint_line="$contract_endpoint"
    fi
  fi

  if [ -z "$endpoint_line" ]; then
    echo "SKIPPED|no_endpoint_in_criteria_or_contracts"
    return 0
  fi

  local method path
  method=$(echo "$endpoint_line" | awk '{print $1}')
  path=$(echo "$endpoint_line" | awk '{print $2}')

  # Clean path — strip hostname + params — keep full relative path
  local path_clean
  path_clean=$(echo "$path" | sed -E 's|^https?://[^/]+||; s|^[^/]+/|/|' | \
               sed -E 's|\{[^}]+\}|.|g')

  # Extract ALL meaningful path fragments (longest → shortest) for multi-level grep
  # e.g. "/api/v1/conversion-goals" → ["/api/v1/conversion-goals", "/conversion-goals"]
  local frags=()
  frags+=("$path_clean")
  # Last segment (most distinctive — e.g. "conversion-goals" from "/api/v1/conversion-goals")
  local last_seg
  last_seg=$(echo "$path_clean" | grep -oE '/[a-zA-Z0-9][a-zA-Z0-9._\-]*' | tail -1)
  [ -n "$last_seg" ] && [ "$last_seg" != "$path_clean" ] && frags+=("$last_seg")

  # Search patterns
  local scan_paths="apps/api/src apps/pixel/src apps/workers/src packages/api"
  local scan_exts="ts tsx js jsx mjs rs py go rb"
  local include_args=""
  for ext in $scan_exts; do include_args="$include_args --include=*.$ext"; done

  local hit=""
  local matched_frag=""
  for frag in "${frags[@]}"; do
    for dir in $scan_paths; do
      [ -d "$dir" ] || continue
      # Match frag as substring within string/template literal (not necessarily whole)
      # e.g. prefix: '/api/v1/conversion-goals' contains 'conversion-goals'
      hit=$(grep -rEnl $include_args "['\"\`][^'\"\`]*${frag}[^'\"\`]*['\"\`]" "$dir" 2>/dev/null | head -3)
      if [ -n "$hit" ]; then
        matched_frag="$frag"
        break 2
      fi
    done
  done

  if [ -n "$hit" ]; then
    local first_hit
    first_hit=$(echo "$hit" | head -1)
    echo "READY|handler=${first_hit}|matched=${matched_frag}"
  else
    echo "BLOCKED|no_handler_for:${method} ${path_clean}"
  fi
}

# ═══════════════════════════════════════════════════════════════════════
# probe_data — grep for table/collection migration + check infra_deps
# ═══════════════════════════════════════════════════════════════════════
# Input: goal_id + goal_block (text)
# Logic: extract table/collection name from criteria + mutation
#        → grep migrations/schema files → READY if found
#        → check infra_deps for service → INFRA_PENDING if unavailable
probe_data() {
  local gid="$1"
  local block="$2"
  local criteria mutation
  criteria=$(_surface_probe_get_criteria "$block")
  mutation=$(echo "$block" | awk '/^\*\*Mutation evidence:\*\*/{inside=1; next} inside && /^\*\*/{exit} inside{print}')
  local combined="${criteria}
${mutation}"

  # Extract table/collection name: common patterns
  # "`conversion_events` collection", "`clicks` table", "ClickHouse table `conversions`"
  local table
  table=$(echo "$combined" | grep -oE '`[a-z_][a-z_0-9]*`\s*(table|collection|MV)?' | \
          sed -E 's/`([^`]+)`.*/\1/' | \
          grep -vE '^(id|status|name|value|count)$' | head -1)

  if [ -z "$table" ]; then
    # Try uppercase SQL identifier pattern: "FROM tableName", "INSERT INTO xxx"
    table=$(echo "$combined" | grep -oE '(FROM|INTO|UPDATE)\s+[a-z_][a-z_0-9]*' | \
            awk '{print $2}' | head -1)
  fi

  if [ -z "$table" ]; then
    # Fallback: bare snake_case identifier after common keywords
    # "inserts documents into conversion_goals", "Kafka topic vollx.conversion",
    # "ClickHouse row XXX", "Redis SET members"
    table=$(echo "$combined" | grep -oE '(into|topic|collection|rows?|table)\s+[a-z_][a-z_0-9]*' | \
            awk '{print $2}' | grep -vE '^(row|rows|table|topic|collection|inserts|documents)$' | head -1)
  fi

  if [ -z "$table" ]; then
    # Last resort: any snake_case identifier ≥ 6 chars that looks like a table name
    # (lowercase, has underscore or is ≥ 8 chars pure)
    table=$(echo "$combined" | grep -oE '\b[a-z][a-z_0-9]{7,}\b' | \
            grep -vE '^(attribution|conversion|mutation|evidence|response|request|endpoint)$' | \
            head -1)
  fi

  if [ -z "$table" ]; then
    echo "SKIPPED|no_table_identifier_in_criteria"
    return 0
  fi

  # Search migrations + schema files
  local scan_paths="infra/clickhouse/migrations infra/clickhouse/schema apps/api/src/db/migrations packages/db/migrations migrations db/migrations schema"
  local hit=""
  for dir in $scan_paths; do
    [ -d "$dir" ] || continue
    hit=$(grep -rEnl "(CREATE TABLE|CREATE COLLECTION|create_table|createCollection)\s+[\"\`]?${table}[\"\`]?\b" "$dir" 2>/dev/null | head -1)
    [ -n "$hit" ] && break
  done

  # If not found via CREATE, try schema literal references
  if [ -z "$hit" ]; then
    for dir in $scan_paths; do
      [ -d "$dir" ] || continue
      hit=$(grep -rEl "\b${table}\b" "$dir" 2>/dev/null | head -1)
      [ -n "$hit" ] && break
    done
  fi

  if [ -z "$hit" ]; then
    echo "BLOCKED|no_migration_for_table:${table}"
    return 0
  fi

  # Found migration — but is the service running? Check infra_deps if goal declares it
  local infra_deps
  infra_deps=$(echo "$block" | grep -oE '^\*\*Infra deps:\*\* \[[^]]+\]' | sed -E 's/^\*\*Infra deps:\*\* \[([^]]+)\]/\1/' | tr ',' '\n' | tr -d ' ')

  # If infra_deps not declared, assume READY based on migration existing
  if [ -z "$infra_deps" ]; then
    echo "READY|migration=${hit}|table=${table}"
    return 0
  fi

  # Any declared dep can be checked — read config.infra_deps.services.<dep>.check
  local unavailable=""
  for dep in $infra_deps; do
    local check_cmd
    check_cmd=$(${PYTHON_BIN:-python3} -c "
import re, sys
cfg = open('.claude/vg.config.md', encoding='utf-8').read()
dep = '$dep'
# Find infra_deps.services.<dep>.check_<ENV> line — try sandbox then local
for env in ('sandbox', 'local'):
    m = re.search(rf'services:.*?{dep}:.*?check_{env}:\s*[\"']([^\"']+)[\"']', cfg, re.S)
    if m:
        print(m.group(1)); sys.exit(0)
" 2>/dev/null)
    [ -z "$check_cmd" ] && continue
    if ! eval "$check_cmd" >/dev/null 2>&1; then
      unavailable="${unavailable}${dep} "
    fi
  done

  if [ -n "$unavailable" ]; then
    echo "INFRA_PENDING|unavailable:${unavailable%% }|table=${table}"
  else
    echo "READY|migration=${hit}|table=${table}|infra_ok:${infra_deps}"
  fi
}

# ═══════════════════════════════════════════════════════════════════════
# probe_integration — verify downstream caller + fixture presence
# ═══════════════════════════════════════════════════════════════════════
probe_integration() {
  local gid="$1"
  local block="$2"
  local phase_dir="$3"

  # Look for fixture file convention first
  local fixture="${phase_dir}/test-runners/fixtures/${gid}.integration.sh"
  if [ -f "$fixture" ]; then
    echo "READY|fixture=${fixture}"
    return 0
  fi

  # Extract service/hook keyword from goal block (e.g. "postback", "webhook", "Kafka")
  local keyword
  keyword=$(echo "$block" | grep -oiE '\b(postback|webhook|callback|kafka|pubsub|sns|sqs|producer|consumer)\b' | head -1 | tr '[:upper:]' '[:lower:]')

  if [ -z "$keyword" ]; then
    echo "SKIPPED|no_integration_keyword"
    return 0
  fi

  # Grep source for producer/consumer code
  local scan_paths="apps/api/src apps/workers/src apps/pixel/src apps/rtb-engine/src packages"
  local hit=""
  for dir in $scan_paths; do
    [ -d "$dir" ] || continue
    hit=$(grep -rEl -i "\b${keyword}\b" "$dir" 2>/dev/null | head -1)
    [ -n "$hit" ] && break
  done

  if [ -n "$hit" ]; then
    echo "READY|caller=${hit}|keyword=${keyword}"
  else
    echo "BLOCKED|no_integration_code_for:${keyword}"
  fi
}

# ═══════════════════════════════════════════════════════════════════════
# probe_time_driven — grep for scheduler/cron registration
# ═══════════════════════════════════════════════════════════════════════
probe_time_driven() {
  local gid="$1"
  local block="$2"

  # Extract time keyword (cron schedule, interval, window)
  local keyword
  keyword=$(echo "$block" | grep -oiE '\b(cron|schedule|setInterval|setTimeout|TTL|expire|expiry|window|job)\b' | head -1 | tr '[:upper:]' '[:lower:]')

  if [ -z "$keyword" ]; then
    echo "SKIPPED|no_time_keyword"
    return 0
  fi

  # Grep workers + api for scheduler registration
  local scan_paths="apps/workers/src apps/api/src packages"
  local hit=""
  for dir in $scan_paths; do
    [ -d "$dir" ] || continue
    hit=$(grep -rEl "(CronJob|cron\.schedule|new Cron|schedule\(|setInterval\(|BullQueue|Agenda)" "$dir" 2>/dev/null | head -1)
    [ -n "$hit" ] && break
  done

  if [ -n "$hit" ]; then
    echo "READY|scheduler=${hit}"
  else
    echo "BLOCKED|no_scheduler_registration"
  fi
}

# ═══════════════════════════════════════════════════════════════════════
# run_surface_probe — dispatcher
# ═══════════════════════════════════════════════════════════════════════
run_surface_probe() {
  local gid="$1"
  local surface="$2"
  local phase_dir="$3"
  local test_goals="${4:-${phase_dir}/TEST-GOALS.md}"

  # Strip CR (Windows line endings) + surrounding whitespace
  gid=$(echo "$gid" | tr -d '\r' | xargs)
  surface=$(echo "$surface" | tr -d '\r' | xargs)

  if [ -z "$gid" ] || [ -z "$surface" ] || [ ! -d "$phase_dir" ]; then
    echo "SKIPPED|bad_args"
    return 1
  fi

  local block
  block=$(_surface_probe_get_goal_block "$gid" "$test_goals")
  if [ -z "$block" ]; then
    echo "SKIPPED|goal_block_not_found:${gid}"
    return 0
  fi

  case "$surface" in
    api)          probe_api "$gid" "$block" "$phase_dir" ;;
    data)         probe_data "$gid" "$block" ;;
    integration)  probe_integration "$gid" "$block" "$phase_dir" ;;
    time-driven)  probe_time_driven "$gid" "$block" ;;
    ui|ui-mobile) echo "SKIPPED|ui_goals_use_browser_not_probe" ;;
    *)            echo "SKIPPED|unknown_surface:${surface}" ;;
  esac
}
