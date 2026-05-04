# shellcheck shell=bash
# VG v1.9.1 R1 — Surface runner: integration (mock receiver)
# Spins up a minimal HTTP receiver on a random free port, executes the service
# under test (which should POST/GET the mock), asserts the mock captured the
# expected request (method, path substring, body substring).
#
# Fixture format (bash):
#   INVOKE_CMD       — command that triggers the downstream call (must use $MOCK_URL)
#   EXPECT_METHOD    — e.g. GET | POST
#   EXPECT_PATH_SUB  — substring that must appear in request path
#   EXPECT_BODY_SUB  — optional substring of captured request body
#   WAIT_SECONDS     — optional (default 5) how long to wait for the call

_mock_start() {
  local port="$1" logfile="$2"
  ${PYTHON_BIN:-python3} - "$port" "$logfile" <<'PY' &
import sys, json, time
from http.server import BaseHTTPRequestHandler, HTTPServer
port, logf = int(sys.argv[1]), sys.argv[2]
class H(BaseHTTPRequestHandler):
    def _capture(self, method):
        ln = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(ln).decode("utf-8", errors="replace") if ln else ""
        rec = {"method": method, "path": self.path, "body": body, "ts": time.time()}
        with open(logf, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_GET(self):  self._capture("GET")
    def do_POST(self): self._capture("POST")
    def do_PUT(self):  self._capture("PUT")
    def log_message(self, *a, **k): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
  echo $!
}

_find_free_port() {
  ${PYTHON_BIN:-python3} -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()"
}

run_goal() {
  local goal_id="$1" phase_dir="$2" fixture_dir="${3:-}"
  local fixture="${fixture_dir}/${goal_id}.integration.sh"
  [ -f "$fixture" ] || fixture="${phase_dir}/test-runners/fixtures/${goal_id}.integration.sh"
  if [ ! -f "$fixture" ]; then
    echo "STATUS=PARTIAL\tEVIDENCE=no-integration-fixture:${goal_id}\tSURFACE=integration"
    return 2
  fi
  local log="${phase_dir}/test-runners/${goal_id}-integration.log"
  local captured="${phase_dir}/test-runners/${goal_id}-mock.jsonl"
  mkdir -p "$(dirname "$log")" 2>/dev/null || true
  : > "$captured"

  local port pid
  port=$(_find_free_port)
  pid=$(_mock_start "$port" "$captured")
  export MOCK_URL="http://127.0.0.1:${port}"
  # shellcheck disable=SC1090
  ( . "$fixture"
    : "${INVOKE_CMD:?fixture must set INVOKE_CMD}"
    : "${EXPECT_METHOD:?fixture must set EXPECT_METHOD}"
    : "${EXPECT_PATH_SUB:?fixture must set EXPECT_PATH_SUB}"
    local wait="${WAIT_SECONDS:-5}"
    bash -c "$INVOKE_CMD" >>"$log" 2>&1 || true
    # Wait up to $wait seconds for mock capture
    local elapsed=0
    while [ "$elapsed" -lt "$wait" ]; do
      [ -s "$captured" ] && break
      sleep 1; elapsed=$((elapsed + 1))
    done
    kill "$pid" 2>/dev/null || true
    if [ ! -s "$captured" ]; then
      echo "STATUS=FAILED\tEVIDENCE=${log}:no-capture\tSURFACE=integration"; exit 1
    fi
    if ! grep -q "\"method\": \"${EXPECT_METHOD}\"" "$captured"; then
      echo "STATUS=FAILED\tEVIDENCE=${captured}:method-mismatch\tSURFACE=integration"; exit 1
    fi
    if ! grep -q "${EXPECT_PATH_SUB}" "$captured"; then
      echo "STATUS=FAILED\tEVIDENCE=${captured}:path-mismatch\tSURFACE=integration"; exit 1
    fi
    if [ -n "${EXPECT_BODY_SUB:-}" ] && ! grep -q "${EXPECT_BODY_SUB}" "$captured"; then
      echo "STATUS=FAILED\tEVIDENCE=${captured}:body-mismatch\tSURFACE=integration"; exit 1
    fi
    echo "STATUS=READY\tEVIDENCE=${captured}\tSURFACE=integration"
  )
  local rc=$?
  kill "$pid" 2>/dev/null || true
  return $rc
}
