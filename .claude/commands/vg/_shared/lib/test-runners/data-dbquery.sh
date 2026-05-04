# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: data (DB query)
# Reads DB client from vg.config.md.test_strategy.surfaces.data.runner_config.client
# (psql | sqlite3 | clickhouse-client | mongosh | auto). Fixture supplies the
# query + expected row/count assertion.
#
# Fixture format (bash, sourced):
#   DB_CLIENT    — optional override (else config)
#   DB_CONN      — connection string appropriate for client (URL / file / --host args)
#   QUERY        — SQL or Mongo command
#   EXPECT_TYPE  — "count-eq" | "count-gte" | "nonempty" | "jq-expr"
#   EXPECT_VALUE — integer for count-*, or jq expression for jq-expr

_data_detect_client() {
  for cand in clickhouse-client psql mongosh sqlite3; do
    command -v "$cand" >/dev/null 2>&1 && { echo "$cand"; return 0; }
  done
  echo ""
}

_data_configured_client() {
  local cfg="${VG_CONFIG_PATH:-.claude/vg.config.md}"
  [ -f "$cfg" ] || return 0
  ${PYTHON_BIN:-python3} - "$cfg" <<'PY'
import re, sys
try: txt = open(sys.argv[1], encoding='utf-8').read()
except Exception: sys.exit(0)
m = re.search(r'runner_config:\s*\{([^}]*client:\s*"?([^",}\s]+))', txt)
if m: print(m.group(2))
PY
}

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local fixture="${fixture_dir}/${goal_id}.data.sh"
  [ -f "$fixture" ] || fixture="${phase_dir}/test-runners/fixtures/${goal_id}.data.sh"
  if [ ! -f "$fixture" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-data-fixture:${goal_id}\tSURFACE=data"
    return 2
  fi
  local log="${phase_dir}/test-runners/${goal_id}-data.log"
  mkdir -p "$(dirname "$log")" 2>/dev/null || true

  ( . "$fixture"
    local client="${DB_CLIENT:-}"
    [ -z "$client" ] && client=$(_data_configured_client)
    if [ -z "$client" ] || [ "$client" = "auto" ]; then
      client=$(_data_detect_client)
    fi
    if [ -z "$client" ]; then
      echo "STATUS=FAILED\tEVIDENCE=no-db-client-available\tSURFACE=data"; exit 1
    fi
    : "${QUERY:?fixture must set QUERY}"
    : "${EXPECT_TYPE:?fixture must set EXPECT_TYPE}"
    local out rc=0
    case "$client" in
      psql)              out=$(psql "${DB_CONN:-}" -At -c "$QUERY" 2>>"$log") || rc=$? ;;
      sqlite3)           out=$(sqlite3 "${DB_CONN:-}" "$QUERY" 2>>"$log") || rc=$? ;;
      clickhouse-client) out=$(clickhouse-client ${DB_CONN:+--$DB_CONN} --query "$QUERY" 2>>"$log") || rc=$? ;;
      mongosh)           out=$(mongosh "${DB_CONN:-}" --quiet --eval "$QUERY" 2>>"$log") || rc=$? ;;
      *) echo "STATUS=FAILED\tEVIDENCE=unknown-client:${client}\tSURFACE=data"; exit 1 ;;
    esac
    echo "client=${client} rc=${rc} out=${out}" >>"$log"
    [ "$rc" -ne 0 ] && { echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=data"; exit 1; }
    case "$EXPECT_TYPE" in
      count-eq)
        [ "$out" = "${EXPECT_VALUE:-0}" ] \
          && { echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=data"; exit 0; } \
          || { echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=data"; exit 1; } ;;
      count-gte)
        if [ "${out:-0}" -ge "${EXPECT_VALUE:-1}" ] 2>/dev/null; then
          echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=data"; exit 0
        fi
        echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=data"; exit 1 ;;
      nonempty)
        [ -n "$out" ] \
          && { echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=data"; exit 0; } \
          || { echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=data"; exit 1; } ;;
      jq-expr)
        if command -v jq >/dev/null 2>&1 && echo "$out" | jq -e "${EXPECT_VALUE}" >>"$log" 2>&1; then
          echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=data"; exit 0
        fi
        echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=data"; exit 1 ;;
      *) echo "STATUS=FAILED\tEVIDENCE=unknown-expect-type:${EXPECT_TYPE}\tSURFACE=data"; exit 1 ;;
    esac
  )
}
