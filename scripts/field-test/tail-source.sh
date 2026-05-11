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

cleanup() {
  if [ -n "${CHILD_PID:-}" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "$CHILD_PID" 2>/dev/null || true
    sleep 0.3
    kill -KILL "$CHILD_PID" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

run_pipeline_once() {
  case "$TYPE" in
    file)
      if [ ! -e "$TARGET" ]; then
        "$PYTHON_BIN" -c "import datetime as d; print(d.datetime.now(d.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'tail-source: waiting for $TARGET to exist')" >> "$OUT"
      fi
      tail -F -n 0 "$TARGET" 2>>"$ERR_LOG" \
        | "$PYTHON_BIN" "$REDACTOR" --pattern "$REDACT_PATTERN" \
        | "$PYTHON_BIN" "$PREFIXER" \
        >> "$OUT" &
      ;;
    command)
      bash -c "$TARGET" 2>>"$ERR_LOG" \
        | "$PYTHON_BIN" "$REDACTOR" --pattern "$REDACT_PATTERN" \
        | "$PYTHON_BIN" "$PREFIXER" \
        >> "$OUT" &
      ;;
    *)
      echo "unknown --type: $TYPE" >&2
      exit 64
      ;;
  esac
  CHILD_PID=$!
  # Poll-wait: bash `wait` in non-interactive shell is not interrupted by
  # trapped signals on all platforms. Polling with short sleeps allows the
  # trap handler to fire between iterations.
  while kill -0 "$CHILD_PID" 2>/dev/null; do
    sleep 0.5
  done
  wait "$CHILD_PID" 2>/dev/null || true
  return $?
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
