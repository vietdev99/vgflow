# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: api (curl + jq)
# Executes one HTTP request per goal and asserts status code + JSON shape.
# Project provides fixtures at:
#   ${fixture_dir}/${goal_id}.api.sh  OR
#   ${phase_dir}/test-runners/fixtures/${goal_id}.api.sh
# Fixture must export: METHOD, URL, [BODY], [HEADERS_FILE], EXPECT_STATUS,
#                      [EXPECT_JQ] (jq expression returning true on success).

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local fixture="${fixture_dir}/${goal_id}.api.sh"
  [ -f "$fixture" ] || fixture="${phase_dir}/test-runners/fixtures/${goal_id}.api.sh"
  if [ ! -f "$fixture" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-api-fixture:${goal_id}\tSURFACE=api"
    return 2
  fi

  # shellcheck disable=SC1090
  ( . "$fixture"
    : "${METHOD:?fixture must set METHOD}"
    : "${URL:?fixture must set URL}"
    : "${EXPECT_STATUS:?fixture must set EXPECT_STATUS}"
    local body_file log
    log="${phase_dir}/test-runners/${goal_id}-api.log"
    mkdir -p "$(dirname "$log")" 2>/dev/null || true
    local curl_args=(-s -o "${log}.body" -w "%{http_code}" -X "$METHOD")
    [ -n "${HEADERS_FILE:-}" ] && [ -f "$HEADERS_FILE" ] && curl_args+=(-H "@${HEADERS_FILE}")
    if [ -n "${BODY:-}" ]; then
      body_file="${log}.req"
      printf '%s' "$BODY" > "$body_file"
      curl_args+=(-H 'Content-Type: application/json' --data-binary "@${body_file}")
    fi
    local actual
    actual=$(curl "${curl_args[@]}" "$URL" 2>>"$log")
    echo "HTTP ${METHOD} ${URL} → ${actual} (expected ${EXPECT_STATUS})" >>"$log"
    if [ "$actual" != "$EXPECT_STATUS" ]; then
      echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=api"; exit 1
    fi
    if [ -n "${EXPECT_JQ:-}" ] && command -v jq >/dev/null 2>&1; then
      if ! jq -e "$EXPECT_JQ" "${log}.body" >>"$log" 2>&1; then
        echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=api"; exit 1
      fi
    fi
    echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=api"
  )
}
