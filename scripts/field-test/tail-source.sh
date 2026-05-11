#!/usr/bin/env bash
# /vg:field-test tail wrapper — pipes source output through redact-stream.py
# then prefix-iso.py before writing to disk. Capture-time redaction closes
# the disk-exposure window v1 left open.
#
# v2.1 (Task 7c folded): 3-strike respawn loop on transient pipe death.
# After 3 failed respawns, logs "tail.dead" and exits non-zero. Clean SIGTERM
# from orchestrator (exit code > 128) does NOT respawn.
set -euo pipefail

TYPE=""
TARGET=""
OUT=""
REDACT_PATTERN="default"
while [ $# -gt 0 ]; do
  case "$1" in
    --type)    TYPE="$2";          shift 2 ;;
    --target)  TARGET="$2";        shift 2 ;;
    --out)     OUT="$2";           shift 2 ;;
    --redact)  REDACT_PATTERN="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

if [ -z "$TYPE" ] || [ -z "$TARGET" ] || [ -z "$OUT" ]; then
  echo "usage: tail-source.sh --type {file|command} --target <arg> --out <path> [--redact <pattern>]" >&2
  exit 64
fi

mkdir -p "$(dirname "$OUT")"
: > "$OUT"
ERR_LOG="${OUT}.tail-err"
: > "$ERR_LOG"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REDACTOR="$SCRIPT_DIR/redact-stream.py"
PREFIXER="$SCRIPT_DIR/prefix-iso.py"

CHILD_PID=""

kill_child_tree() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  kill -0 "$pid" 2>/dev/null || return 0

  # The child bash owns the tail/redactor/prefix pipeline. If we kill only
  # that wrapper, grandchildren can be re-parented and keep pytest pipes open.
  if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -P "$pid" 2>/dev/null || true
  fi
  kill -TERM "$pid" 2>/dev/null || true
  sleep 0.3
  if command -v pkill >/dev/null 2>&1; then
    pkill -KILL -P "$pid" 2>/dev/null || true
  fi
  kill -KILL "$pid" 2>/dev/null || true
}

cleanup() {
  kill_child_tree "${CHILD_PID:-}"
  exit 0
}
trap cleanup TERM INT

run_pipeline_once() {
  # Wrap the entire pipeline in a single bash -c invocation so $! captures
  # the PID of the wrapper process tree (not just the last pipe stage).
  # This makes cleanup TERM propagate to all stages AND `wait` returns the
  # pipeline's true exit code (pipefail catches mid-pipe failures).
  case "$TYPE" in
    file)
      if [ ! -e "$TARGET" ]; then
        "$PYTHON_BIN" -c "import datetime as d, sys; print(d.datetime.now(d.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'), 'tail-source: waiting for', sys.argv[1], 'to exist')" -- "$TARGET" >> "$OUT"
      fi
      bash -c '
        set -o pipefail
        cleanup_child() { for pid in $(jobs -pr); do kill -TERM "$pid" 2>/dev/null || true; done; }
        trap "cleanup_child; exit 143" TERM INT
        tail -F -n 0 "$1" 2>>"$5" \
          | "$3" "$4" --pattern "$6" \
          | "$3" "$7" >> "$2"
      ' -- "$TARGET" "$OUT" "$PYTHON_BIN" "$REDACTOR" "$ERR_LOG" "$REDACT_PATTERN" "$PREFIXER" &
      CHILD_PID=$!
      ;;
    command)
      bash -c '
        set -o pipefail
        cleanup_child() { for pid in $(jobs -pr); do kill -TERM "$pid" 2>/dev/null || true; done; }
        trap "cleanup_child; exit 143" TERM INT
        bash -c "$1" 2>>"$5" \
          | "$3" "$4" --pattern "$6" \
          | "$3" "$7" >> "$2"
      ' -- "$TARGET" "$OUT" "$PYTHON_BIN" "$REDACTOR" "$ERR_LOG" "$REDACT_PATTERN" "$PREFIXER" &
      CHILD_PID=$!
      ;;
    *)
      echo "unknown --type: $TYPE" >&2
      return 64
      ;;
  esac

  # Poll-wait loop — bare `wait` doesn't reliably interrupt on trapped signal
  # in non-interactive bash on some platforms.
  while kill -0 "$CHILD_PID" 2>/dev/null; do
    sleep 0.5
  done
  # Reap and capture true exit code — NO `|| true` (was C2 bug).
  wait "$CHILD_PID" 2>/dev/null
  local rc=$?
  return "$rc"
}

# v2.1 MUST-1: 3-strike respawn loop on transient pipe death.
# Clean signal exit (rc > 128) is NOT a respawn case — orchestrator killed us.
respawn_count=0
max_respawn=3
while [ "$respawn_count" -lt "$max_respawn" ]; do
  set +e
  run_pipeline_once
  rc=$?
  set -e
  if [ "$rc" -eq 0 ] || [ "$rc" -gt 128 ]; then
    exit "$rc"
  fi
  respawn_count=$((respawn_count + 1))
  echo "[$(date -u +%FT%TZ)] tail-source respawn $respawn_count/$max_respawn (rc=$rc)" >> "$ERR_LOG"
  sleep 1
done
echo "[$(date -u +%FT%TZ)] tail.dead — gave up after $max_respawn respawns" >> "$ERR_LOG"
exit 1
