#!/usr/bin/env bash
# dast-runner.sh — DAST (Dynamic Application Security Testing) cascade wrapper.
#
# Phase B.5 v2.5 (2026-04-23): tier 2 dynamic scan. Spawns ZAP baseline /
# Nuclei / or fallback to static-only based on `security_testing:` config in
# .claude/vg.config.md. Callable from review.md + test.md step hooks.
#
# Usage:
#   dast-runner.sh <phase_num> <target_url> <scan_mode> [output_file]
#
#   phase_num    — e.g. "07.6" (resolves to .vg/phases/07.6-*/)
#   target_url   — live endpoint, e.g. https://sandbox.vollx.com
#   scan_mode    — baseline | full | api
#   output_file  — default .vg/phases/{phase}/dast-report.json
#
# Exit codes:
#   0 — scan completed (findings may be present, validator decides severity)
#   2 — no DAST tool available in cascade (caller decides block vs warn)
#
# Historical context: Phase B.1 shipped tier-1 static validators. B.5 adds
# dynamic scan for mutation endpoints. Cascade lets ops run ZAP when Docker
# is available, fall back to Nuclei binary, or skip gracefully when neither.

set -uo pipefail

REPO_ROOT="${VG_REPO_ROOT:-$(pwd)}"
CONFIG_PATH="${REPO_ROOT}/.claude/vg.config.md"
EVENTS_DIR="${REPO_ROOT}/.vg/events"

# ─── Args ──────────────────────────────────────────────────────────────
if [ "$#" -lt 3 ]; then
  echo "usage: dast-runner.sh <phase_num> <target_url> <scan_mode> [output_file]" >&2
  exit 2
fi
PHASE_NUM="$1"
TARGET_URL="$2"
SCAN_MODE="$3"
OUTPUT_FILE="${4:-}"

# Resolve phase dir (prefix match)
_resolve_phase_dir() {
  local phase="$1"
  local phases_dir="${REPO_ROOT}/.vg/phases"
  [ -d "$phases_dir" ] || { echo ""; return; }
  local hit
  hit=$(find "$phases_dir" -maxdepth 1 -type d -name "${phase}-*" 2>/dev/null | head -1)
  if [ -z "$hit" ] && [ -d "${phases_dir}/${phase}" ]; then
    hit="${phases_dir}/${phase}"
  fi
  echo "$hit"
}

PHASE_DIR=$(_resolve_phase_dir "$PHASE_NUM")
if [ -z "$OUTPUT_FILE" ]; then
  if [ -n "$PHASE_DIR" ]; then
    OUTPUT_FILE="${PHASE_DIR}/dast-report.json"
  else
    OUTPUT_FILE="${REPO_ROOT}/.vg/dast-report.json"
  fi
fi
mkdir -p "$(dirname "$OUTPUT_FILE")" 2>/dev/null || true
mkdir -p "$EVENTS_DIR" 2>/dev/null || true

# ─── Config reader ─────────────────────────────────────────────────────
# Parse `security_testing:` block in vg.config.md with grep/sed — minimal
# YAML parser, sufficient for flat scalar + single array we need.
_cfg_scalar() {
  local key="$1" default="$2"
  [ -f "$CONFIG_PATH" ] || { echo "$default"; return; }
  local val
  val=$(awk -v k="$key" '
    /^security_testing:/ { in_block=1; next }
    in_block && /^[^[:space:]]/ { in_block=0 }
    in_block && $1 == k":" {
      sub(/^[[:space:]]*[^:]+:[[:space:]]*/, "")
      gsub(/^["'"'"']|["'"'"']$/, "")
      gsub(/[[:space:]]*#.*$/, "")
      print; exit
    }
  ' "$CONFIG_PATH")
  if [ -z "$val" ]; then echo "$default"; else echo "$val"; fi
}

_cfg_list() {
  # Parse `key: ["a", "b", "c"]` inline list into space-separated tokens.
  local key="$1" default="$2"
  [ -f "$CONFIG_PATH" ] || { echo "$default"; return; }
  local raw
  raw=$(awk -v k="$key" '
    /^security_testing:/ { in_block=1; next }
    in_block && /^[^[:space:]]/ { in_block=0 }
    in_block && $1 == k":" {
      sub(/^[[:space:]]*[^:]+:[[:space:]]*/, "")
      print; exit
    }
  ' "$CONFIG_PATH")
  if [ -z "$raw" ]; then echo "$default"; return; fi
  # Strip brackets + quotes + commas
  raw=$(echo "$raw" | sed -e 's/[][,"'"'"']/ /g')
  echo "$raw"
}

DAST_TOOL=$(_cfg_scalar "dast_tool" "")
DAST_CASCADE=$(_cfg_list "dast_cascade" "zap nuclei grep-only")
DAST_TIMEOUT=$(_cfg_scalar "dast_timeout_seconds" "600")

# ─── Event emitter ────────────────────────────────────────────────────
_emit_event() {
  local evtype="$1" payload="$2"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local file="${EVENTS_DIR}/$(date +%s)-${evtype}.json"
  printf '{"ts":"%s","type":"%s","phase":"%s","payload":%s}\n' \
    "$ts" "$evtype" "$PHASE_NUM" "$payload" > "$file" 2>/dev/null || true
}

# ─── Tool runners ─────────────────────────────────────────────────────
_have() { command -v "$1" >/dev/null 2>&1; }

_run_with_timeout() {
  # Portable timeout wrapper ($1 = seconds, rest = command).
  local secs="$1"; shift
  if _have timeout; then
    timeout "$secs" "$@"
  else
    # Fallback: background + kill
    "$@" &
    local pid=$!
    ( sleep "$secs" && kill -9 "$pid" 2>/dev/null ) &
    local killer=$!
    wait "$pid" 2>/dev/null
    local rc=$?
    kill -9 "$killer" 2>/dev/null || true
    return $rc
  fi
}

_try_zap() {
  _have docker || return 10
  local zap_img="ghcr.io/zaproxy/zaproxy:stable"
  # Skip pull if image already cached (silent check)
  if ! docker image inspect "$zap_img" >/dev/null 2>&1; then
    docker pull "$zap_img" >/dev/null 2>&1 || return 10
  fi
  local script="zap-baseline.py"
  case "$SCAN_MODE" in
    full) script="zap-full-scan.py" ;;
    api)  script="zap-api-scan.py" ;;
    *)    script="zap-baseline.py" ;;
  esac
  local start_ts end_ts dur rc
  start_ts=$(date +%s)
  _run_with_timeout "$DAST_TIMEOUT" docker run --rm \
    -v /tmp:/zap/wrk "$zap_img" \
    "$script" -t "$TARGET_URL" -J "/zap/wrk/$(basename "$OUTPUT_FILE")" \
    >/dev/null 2>&1
  rc=$?
  end_ts=$(date +%s); dur=$((end_ts - start_ts))
  # Copy out of /tmp into phase dir
  if [ -f "/tmp/$(basename "$OUTPUT_FILE")" ]; then
    cp "/tmp/$(basename "$OUTPUT_FILE")" "$OUTPUT_FILE" 2>/dev/null || true
  fi
  # ZAP exit 0=clean, 1/2/3=findings — all "completed"
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ] || [ "$rc" -eq 2 ] || [ "$rc" -eq 3 ]; then
    _emit_event "security.dast_tool_used" \
      "{\"tool\":\"zap\",\"mode\":\"$SCAN_MODE\",\"duration_sec\":$dur,\"exit\":$rc}"
    return 0
  fi
  return 10
}

_try_nuclei() {
  _have nuclei || return 10
  nuclei --version >/dev/null 2>&1 || return 10
  local start_ts end_ts dur rc
  start_ts=$(date +%s)
  _run_with_timeout "$DAST_TIMEOUT" nuclei -u "$TARGET_URL" \
    -severity critical,high,medium \
    -json-export "$OUTPUT_FILE" >/dev/null 2>&1
  rc=$?
  end_ts=$(date +%s); dur=$((end_ts - start_ts))
  if [ "$rc" -eq 0 ] || [ -s "$OUTPUT_FILE" ]; then
    _emit_event "security.dast_tool_used" \
      "{\"tool\":\"nuclei\",\"mode\":\"$SCAN_MODE\",\"duration_sec\":$dur,\"exit\":$rc}"
    return 0
  fi
  return 10
}

_try_greponly() {
  # Phase B.1 static validators already ran — emit skip event, exit 0.
  _emit_event "security.dast_skipped" \
    "{\"reason\":\"grep-only fallback\",\"note\":\"static tier-1 validators already executed\"}"
  # Write a minimal empty report so downstream validator has a file.
  printf '{"format":"grep-only","findings":[],"note":"DAST skipped per cascade"}\n' \
    > "$OUTPUT_FILE" 2>/dev/null || true
  return 0
}

# ─── Cascade execution ─────────────────────────────────────────────────
_try_tool() {
  case "$1" in
    zap)       _try_zap ;;
    nuclei)    _try_nuclei ;;
    grep-only) _try_greponly ;;
    *) return 10 ;;
  esac
}

if [ -n "$DAST_TOOL" ]; then
  # Explicit: try only this tool, no fallback.
  if _try_tool "$DAST_TOOL"; then
    exit 0
  fi
  echo "⛔ dast-runner: explicit tool '$DAST_TOOL' unavailable or failed" >&2
  _emit_event "security.dast_tool_unavailable" \
    "{\"requested\":\"$DAST_TOOL\",\"cascade_used\":false}"
  exit 2
fi

# Cascade mode
for tool in $DAST_CASCADE; do
  if _try_tool "$tool"; then
    exit 0
  fi
done

echo "⛔ dast-runner: no DAST tool in cascade succeeded ($DAST_CASCADE)" >&2
_emit_event "security.dast_tool_unavailable" \
  "{\"cascade\":\"$DAST_CASCADE\",\"all_failed\":true}"
exit 2
