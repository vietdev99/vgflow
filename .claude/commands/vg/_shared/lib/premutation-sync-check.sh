#!/bin/bash
# premutation-sync-check.sh — fast-path Codex mirror drift detection
# called at the entry of every mutating VG command before run-start.
#
# Purpose: Before AI can mutate repo state, verify that Codex mirrors
# (.codex/skills, ~/.codex/skills) are in sync with .claude/commands/vg/.
# If drift → BLOCK with instruction to run `/vg:sync`.
#
# Performance: fast path (mtime + size comparison), skips SHA256 computation.
# Budget: <100ms per call. Falls back to full SHA256 verify if fast check
# is inconclusive OR if $VG_SYNC_CHECK_FULL=true.
#
# Usage (from skill file bash block):
#   source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/premutation-sync-check.sh"
#   vg_premutation_sync_check || exit 1
#
# Exit codes:
#   0 = sync OK OR check disabled
#   1 = drift detected, BLOCK
#   2 = invariant violation (script error)

# Cache file — invalidates after ≥24h OR on commit
_VG_SYNC_CACHE_DIR=".vg/.cache"
_VG_SYNC_CACHE_FILE="${_VG_SYNC_CACHE_DIR}/mirror-sync-check.json"
_VG_SYNC_TTL_SECONDS=$((24 * 3600))

vg_premutation_sync_check() {
  # Check if disabled entirely
  if [ "${VG_SYNC_CHECK_DISABLED:-false}" = "true" ]; then
    return 0
  fi

  # Resolve repo root
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
  if [ -z "$repo_root" ]; then
    # Not in git repo — can't determine scope, skip
    return 0
  fi

  cd "$repo_root" || return 2

  # Check cache freshness
  mkdir -p "${_VG_SYNC_CACHE_DIR}" 2>/dev/null
  if [ -f "${_VG_SYNC_CACHE_FILE}" ]; then
    local cache_epoch
    cache_epoch=$(stat -c %Y "${_VG_SYNC_CACHE_FILE}" 2>/dev/null || \
                  stat -f %m "${_VG_SYNC_CACHE_FILE}" 2>/dev/null || echo 0)
    local now_epoch
    now_epoch=$(date +%s)
    local age=$((now_epoch - cache_epoch))

    if [ "$age" -lt "$_VG_SYNC_TTL_SECONDS" ] && \
       [ "${VG_SYNC_CHECK_FULL:-false}" != "true" ]; then
      # Cache fresh + not forced-full — trust cache
      local cached_verdict
      cached_verdict=$(grep -oE '"in_sync"[[:space:]]*:[[:space:]]*[a-z]+' \
                       "${_VG_SYNC_CACHE_FILE}" 2>/dev/null | \
                       awk -F: '{print $2}' | tr -d ' ')
      if [ "$cached_verdict" = "true" ]; then
        return 0
      fi
      # If cache says drift → fall through to full check
    fi
  fi

  # Fast path: mtime comparison (if any source mtime > any mirror mtime → suspect)
  if [ "${VG_SYNC_CHECK_FULL:-false}" != "true" ]; then
    local newest_source
    newest_source=$(find .claude/commands/vg -name "*.md" -type f \
                    -printf "%T@\n" 2>/dev/null | \
                    sort -rn | head -1)
    local newest_codex_local
    newest_codex_local=$(find .codex/skills -name "SKILL.md" -type f \
                         -printf "%T@\n" 2>/dev/null | \
                         sort -rn | head -1)

    # If no source files found, can't verify — skip
    if [ -z "$newest_source" ]; then
      return 0
    fi

    # If mirror newer than source by ≥60s, assume sync was recent — trust fast path
    # If source newer than mirror by ≥60s, definite drift
    if [ -n "$newest_codex_local" ]; then
      local diff_sec
      diff_sec=$(awk "BEGIN {print int($newest_codex_local - $newest_source)}" 2>/dev/null)
      if [ "${diff_sec:-0}" -gt 60 ]; then
        # Mirror is newer than source → recent sync, trust it
        _vg_write_cache_ok
        return 0
      fi
    fi
  fi

  # Full path: delegate to verify-codex-skill-mirror-sync.py
  local validator=".claude/scripts/validators/verify-codex-skill-mirror-sync.py"
  if [ ! -f "$validator" ]; then
    # Validator not installed yet — don't block pre-v2.5.2 commands
    return 0
  fi

  local py_bin="${PYTHON_BIN:-python3}"
  # Prefer python over python3 on Windows where only python works
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    py_bin="python"
  fi
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    # No Python available — can't verify, skip (don't block)
    return 0
  fi

  local verify_output
  local verify_exit
  verify_output=$(PYTHONIOENCODING=utf-8 "$py_bin" "$validator" \
                  --quiet --json --skip-vgflow 2>&1)
  verify_exit=$?

  # Cache result for next invocation
  if [ $verify_exit -eq 0 ]; then
    _vg_write_cache_ok
    return 0
  fi

  # Drift detected — write cache + emit instruction
  echo "$verify_output" > "${_VG_SYNC_CACHE_FILE}" 2>/dev/null

  local drift_count
  drift_count=$(echo "$verify_output" | \
                grep -oE '"drift_count"[[:space:]]*:[[:space:]]*[0-9]+' | \
                awk -F: '{print $2}' | tr -d ' ')

  cat >&2 <<EOF

⛔ VG mirror drift detected — ${drift_count:-?} skill(s) out of sync.
   Codex agents are reading stale skill content → trust parity breach.

   Fix (choose one):
     (a) python .claude/scripts/sync-vg-skills.py      # automated
     (b) DEV_ROOT="\$PWD" bash ../vgflow-repo/sync.sh  # direct sync.sh
     (c) Export VG_SYNC_CHECK_DISABLED=true             # emergency bypass
                                                          (logs debt)

   Detail: python .claude/scripts/validators/verify-codex-skill-mirror-sync.py
EOF

  return 1
}

_vg_write_cache_ok() {
  local cache_dir
  cache_dir=$(dirname "${_VG_SYNC_CACHE_FILE}")
  mkdir -p "$cache_dir" 2>/dev/null || return 0
  printf '{"in_sync": true, "ts": %s, "ttl_seconds": %s}' \
         "$(date +%s)" "$_VG_SYNC_TTL_SECONDS" \
         > "${_VG_SYNC_CACHE_FILE}" 2>/dev/null
}
