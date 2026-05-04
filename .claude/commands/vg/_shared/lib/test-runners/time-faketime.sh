# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: time-driven (faketime)
# Wraps a handler invocation under `faketime` (libfaketime) to simulate clock
# shift (cron windows, attribution-window expiry, schedulers). Falls back to
# TZ+SOURCE_DATE_EPOCH if faketime unavailable.
#
# Fixture format (bash):
#   FAKE_TIME   — e.g. "+31d" or "2026-05-01 00:00:00"
#   INVOKE_CMD  — command to run under the faked clock (exits 0 on success)
#   EXPECT_POST_CMD — optional post-check (any command; exits 0 to pass)

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local fixture="${fixture_dir}/${goal_id}.time.sh"
  [ -f "$fixture" ] || fixture="${phase_dir}/test-runners/fixtures/${goal_id}.time.sh"
  if [ ! -f "$fixture" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-time-fixture:${goal_id}\tSURFACE=time-driven"
    return 2
  fi
  local log="${phase_dir}/test-runners/${goal_id}-time.log"
  mkdir -p "$(dirname "$log")" 2>/dev/null || true

  ( . "$fixture"
    : "${FAKE_TIME:?fixture must set FAKE_TIME}"
    : "${INVOKE_CMD:?fixture must set INVOKE_CMD}"
    local rc=0
    if command -v faketime >/dev/null 2>&1; then
      faketime "$FAKE_TIME" bash -c "$INVOKE_CMD" >>"$log" 2>&1 || rc=$?
    else
      # Fallback: best-effort via SOURCE_DATE_EPOCH (python-based helper)
      local epoch
      epoch=$(${PYTHON_BIN:-python3} -c "
import sys, datetime, re
t = '$FAKE_TIME'
if t.startswith('+') or t.startswith('-'):
  m = re.match(r'([+-])(\d+)([dhms])', t)
  if m:
    sign = 1 if m.group(1)=='+' else -1
    n = int(m.group(2)); u = m.group(3)
    delta = {'d':86400,'h':3600,'m':60,'s':1}[u] * n * sign
    import time
    print(int(time.time()) + delta); sys.exit(0)
try:
  dt = datetime.datetime.fromisoformat(t)
  print(int(dt.timestamp()))
except Exception:
  import time
  print(int(time.time()))
")
      SOURCE_DATE_EPOCH="$epoch" bash -c "$INVOKE_CMD" >>"$log" 2>&1 || rc=$?
      echo "[faketime unavailable — used SOURCE_DATE_EPOCH=$epoch]" >>"$log"
    fi
    if [ "$rc" -ne 0 ]; then
      echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=time-driven"; exit 1
    fi
    if [ -n "${EXPECT_POST_CMD:-}" ]; then
      if ! bash -c "$EXPECT_POST_CMD" >>"$log" 2>&1; then
        echo "STATUS=FAILED\tEVIDENCE=${log}\tSURFACE=time-driven"; exit 1
      fi
    fi
    echo "STATUS=READY\tEVIDENCE=${log}\tSURFACE=time-driven"
  )
}
