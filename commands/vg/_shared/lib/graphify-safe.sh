#!/usr/bin/env bash
# graphify-safe.sh — hardened graphify rebuild with mtime verification + retry.
#
# Source this from commands that auto-rebuild graphify (blueprint, build, review)
# so silent rebuild failures are caught instead of proceeding with stale graph.
#
# Usage:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
#   vg_graphify_rebuild_safe "${GRAPHIFY_GRAPH_PATH}" "blueprint"
#
# Returns 0 on success (mtime advanced), 1 on failure after retry.
#
# Historical context: Phase 10 audit (2026-04-19) found graph stale 10h during
# build + 0 rebuild events in telemetry. Rebuild code existed but silent fails
# went undetected. This wrapper closes the observability gap.

# Get current mtime of a file (cross-platform)
_vg_graphify_mtime() {
  local path="$1"
  stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null || echo "0"
}

# Run rebuild command, return 0 if graph.json mtime advanced.
_vg_graphify_attempt_rebuild() {
  local graph_path="$1"
  local label="$2"

  ${PYTHON_BIN:-python3} -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('${REPO_ROOT:-.}'))" 2>&1 | tail -5
  return $?
}

_vg_graphify_emit() {
  local event_type="$1"
  local outcome="${2:-INFO}"
  local payload="${3:-}"
  local step="${4:-build.graphify}"
  local phase="${PHASE_NUMBER:-${VG_CURRENT_PHASE:-}}"

  if [ -z "$payload" ]; then
    payload="{}"
  fi

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "$event_type" "$phase" "$step" "graphify" "$outcome" "$payload" >/dev/null 2>&1 || true
  elif type -t telemetry_emit >/dev/null 2>&1; then
    telemetry_emit "$event_type" "$phase" "$step" "$payload" >/dev/null 2>&1 || true
  fi

  if [ -e "${REPO_ROOT:-.}/.claude/scripts/vg-orchestrator" ]; then
    (
      cd "${REPO_ROOT:-.}" && \
      ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event "$event_type" \
        --step "$step" --outcome "$outcome" --payload "$payload" >/dev/null 2>&1
    ) || true
  fi
}

# Main: rebuild + verify + retry-once-on-no-progress.
# Loud warnings on silent failure (previously this failed silently).
vg_graphify_rebuild_safe() {
  local graph_path="${1:-${GRAPHIFY_GRAPH_PATH:-graphify-out/graph.json}}"
  local trigger="${2:-unknown}"

  if [ ! -f "$graph_path" ]; then
    echo "⚠ vg_graphify_rebuild_safe: graph not found at $graph_path"
    echo "   Building from scratch..."
    _vg_graphify_attempt_rebuild "$graph_path" "$trigger-cold"
    if [ ! -f "$graph_path" ]; then
      echo "⛔ Graph still missing after rebuild — build failed silently"
      _vg_graphify_emit "graphify_rebuild_failed" "BLOCK" \
        "{\"trigger\":\"${trigger}\",\"reason\":\"graph_not_created\"}"
      return 1
    fi
    _vg_graphify_emit "graphify_auto_rebuild" "PASS" \
      "{\"trigger\":\"${trigger}\",\"mode\":\"cold_bootstrap\",\"success\":true}"
    return 0
  fi

  local mtime_before
  mtime_before=$(_vg_graphify_mtime "$graph_path")

  _vg_graphify_attempt_rebuild "$graph_path" "$trigger"

  local mtime_after
  mtime_after=$(_vg_graphify_mtime "$graph_path")

  # Verify mtime advanced
  if [ "$mtime_after" -le "$mtime_before" ] 2>/dev/null; then
    echo ""
    echo "⚠⚠⚠ vg_graphify_rebuild_safe: mtime did NOT advance (before=${mtime_before}, after=${mtime_after})"
    echo "    Rebuild may have silently failed. Retrying once..."
    echo ""

    _vg_graphify_attempt_rebuild "$graph_path" "$trigger-retry"
    mtime_after=$(_vg_graphify_mtime "$graph_path")

    if [ "$mtime_after" -le "$mtime_before" ] 2>/dev/null; then
      echo "⛔ Graphify rebuild FAILED after retry. Graph remains stale."
      echo "   Downstream steps using stale graph will produce misleading context."
      echo "   Manual: ${PYTHON_BIN:-python3} -m graphify update ."
      _vg_graphify_emit "graphify_rebuild_failed" "BLOCK" \
        "{\"trigger\":\"${trigger}\",\"reason\":\"mtime_stuck\",\"mtime\":${mtime_before}}"
      return 1
    fi
  fi

  # Success path
  local delta=$((mtime_after - mtime_before))
  echo "✓ Graphify rebuilt (mtime +${delta}s, trigger=${trigger})"
  _vg_graphify_emit "graphify_auto_rebuild" "PASS" \
    "{\"trigger\":\"${trigger}\",\"mtime_delta_sec\":${delta},\"success\":true}"
  return 0
}

# Guard: detect silent rebuild skip — when config says rebuild but no mtime change
# happened between two checkpoints. Call before + after expected rebuild window.
vg_graphify_snapshot_mtime() {
  _vg_graphify_mtime "${GRAPHIFY_GRAPH_PATH:-graphify-out/graph.json}"
}

vg_graphify_assert_rebuilt_since() {
  local mtime_baseline="$1"
  local context="${2:-unknown}"
  local mtime_now
  mtime_now=$(vg_graphify_snapshot_mtime)
  if [ "$mtime_now" -le "$mtime_baseline" ] 2>/dev/null; then
    echo "⚠ vg_graphify_assert_rebuilt_since: graph NOT rebuilt during ${context}"
    echo "   baseline=${mtime_baseline} now=${mtime_now}"
    _vg_graphify_emit "graphify_rebuild_skipped" "WARN" \
      "{\"context\":\"${context}\",\"baseline\":${mtime_baseline}}"
    return 1
  fi
  return 0
}
