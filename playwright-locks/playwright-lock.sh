#!/bin/bash
# Playwright MCP Server Lock Manager
# Usage:
#   playwright-lock.sh claim [session_id] [pool]   → claim first available, print server name
#   playwright-lock.sh release [session_id] [pool] → release lock for session
#   playwright-lock.sh status [pool]               → show all locks (pool: claude|codex|gemini|all)
#   playwright-lock.sh cleanup [max_age_s] [pool]  → remove stale locks (default: 3600s, pool: all)
#   playwright-lock.sh force-release <name> [pool] → force release server + kill browsers
#
# Pools:
#   (empty / "claude") → playwright1.lock .. playwright5.lock       (Claude Code sessions)
#   "codex"            → codex-pw-1.lock .. codex-pw-5.lock         (Codex sessions)
#   "gemini"           → gemini-pw-1.lock .. gemini-pw-5.lock       (Gemini sessions)

LOCK_DIR="C:/Users/Lionel Messi/.claude/playwright-locks"

# Auto-TTL: claim step auto-sweeps locks older than this (seconds).
# Haiku scan budget = 10 min max; buffer 20 min = 1800s.
# Override via env: PLAYWRIGHT_LOCK_TTL=900
AUTO_TTL="${PLAYWRIGHT_LOCK_TTL:-1800}"

# Check if a PID is alive (cross-platform-ish)
_pid_alive() {
  local pid="$1"
  [ -z "$pid" ] && return 1
  # Pure numeric only — agents may pass non-PID session IDs
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  if command -v tasklist >/dev/null 2>&1; then
    # Windows: tasklist
    tasklist //FI "PID eq $pid" 2>/dev/null | grep -q "$pid"
  else
    # Unix: kill -0
    kill -0 "$pid" 2>/dev/null
  fi
}

# Auto-sweep: drop locks where (age > AUTO_TTL) OR (PID dead). Silent; called by claim.
_auto_sweep() {
  local pool="$1"
  local now
  now=$(date +%s)
  for num in $(_get_servers "$pool"); do
    local LOCK_FILE
    LOCK_FILE=$(_lock_file "$pool" "$num")
    if [ -f "$LOCK_FILE" ]; then
      local locked_by locked_at age
      locked_by=$(awk '{print $1}' "$LOCK_FILE")
      locked_at=$(awk '{print $2}' "$LOCK_FILE")
      age=$(( now - ${locked_at:-0} ))
      # Stale by TTL → drop
      if [ "$age" -gt "$AUTO_TTL" ]; then
        rm -f "$LOCK_FILE"
        continue
      fi
      # PID-looking session ID but process is gone → drop
      if [[ "$locked_by" =~ ^[0-9]+$ ]] && ! _pid_alive "$locked_by"; then
        rm -f "$LOCK_FILE"
      fi
    fi
  done
}

_get_prefix() {
  local pool="${1:-claude}"
  case "$pool" in
    codex)  echo "codex-pw-" ;;
    gemini) echo "gemini-pw-" ;;
    *)      echo "playwright" ;;
  esac
}

_get_servers() {
  local pool="${1:-claude}"
  case "$pool" in
    codex)  echo "1 2 3 4 5" ;;
    gemini) echo "1 2 3 4 5" ;;
    *)      echo "1 2 3 4 5" ;;
  esac
}

_lock_file() {
  local pool="$1" num="$2"
  local prefix
  prefix=$(_get_prefix "$pool")
  echo "$LOCK_DIR/${prefix}${num}.lock"
}

_server_name() {
  local pool="$1" num="$2"
  # All pools use MCP server names playwright1-5 in their respective tool configs
  echo "playwright${num}"
}

case "$1" in
  claim)
    SESSION_ID="${2:-$$}"
    POOL="${3:-claude}"
    # Auto-sweep stale/dead-process locks before trying to claim (fixes B2 leak).
    _auto_sweep "$POOL"
    for num in $(_get_servers "$POOL"); do
      LOCK_FILE=$(_lock_file "$POOL" "$num")
      if [ ! -f "$LOCK_FILE" ]; then
        echo "$SESSION_ID $(date +%s)" > "$LOCK_FILE"
        _server_name "$POOL" "$num"
        exit 0
      fi
    done
    echo "ERROR: All 5 playwright servers are locked (pool: $POOL)" >&2
    exit 1
    ;;

  release)
    SESSION_ID="${2:-$$}"
    POOL="${3:-claude}"
    for num in $(_get_servers "$POOL"); do
      LOCK_FILE=$(_lock_file "$POOL" "$num")
      if [ -f "$LOCK_FILE" ]; then
        LOCKED_BY=$(awk '{print $1}' "$LOCK_FILE")
        if [ "$LOCKED_BY" = "$SESSION_ID" ]; then
          rm -f "$LOCK_FILE"
          echo "Released: $(_server_name "$POOL" "$num") (pool: $POOL)"
          exit 0
        fi
      fi
    done
    echo "No lock found for session $SESSION_ID (pool: $POOL)" >&2
    exit 1
    ;;

  status)
    POOL="${2:-all}"
    show_pool() {
      local p="$1"
      echo "--- Pool: $p ---"
      for num in $(_get_servers "$p"); do
        LOCK_FILE=$(_lock_file "$p" "$num")
        SERVER=$(_server_name "$p" "$num")
        if [ -f "$LOCK_FILE" ]; then
          LOCKED_BY=$(awk '{print $1}' "$LOCK_FILE")
          LOCKED_AT=$(awk '{print $2}' "$LOCK_FILE")
          AGE=$(( $(date +%s) - LOCKED_AT ))
          echo "  $SERVER: LOCKED by $LOCKED_BY (${AGE}s ago)"
        else
          echo "  $SERVER: FREE"
        fi
      done
    }
    if [ "$POOL" = "all" ]; then
      show_pool claude
      show_pool codex
      show_pool gemini
    else
      show_pool "$POOL"
    fi
    ;;

  cleanup)
    MAX_AGE="${2:-3600}"
    POOL="${3:-all}"
    NOW=$(date +%s)
    cleanup_pool() {
      local p="$1"
      for num in $(_get_servers "$p"); do
        LOCK_FILE=$(_lock_file "$p" "$num")
        if [ -f "$LOCK_FILE" ]; then
          LOCKED_AT=$(awk '{print $2}' "$LOCK_FILE")
          AGE=$(( NOW - LOCKED_AT ))
          if [ "$AGE" -gt "$MAX_AGE" ]; then
            rm -f "$LOCK_FILE"
            echo "Cleaned stale lock: $(_server_name "$p" "$num") pool=$p (was ${AGE}s old)"
          fi
        fi
      done
    }
    if [ "$POOL" = "all" ]; then
      cleanup_pool claude
      cleanup_pool codex
      cleanup_pool gemini
    else
      cleanup_pool "$POOL"
    fi
    ;;

  force-release)
    SERVER="${2:-}"
    POOL="${3:-claude}"
    if [ -z "$SERVER" ]; then
      echo "Usage: playwright-lock.sh force-release <server_name_or_number> [pool]" >&2
      exit 1
    fi
    # Accept both "playwright1" and "1"
    NUM="${SERVER//playwright/}"
    LOCK_FILE=$(_lock_file "$POOL" "$NUM")
    if [ -f "$LOCK_FILE" ]; then
      rm -f "$LOCK_FILE"
      echo "Force released: $(_server_name "$POOL" "$NUM") (pool: $POOL)"
    else
      echo "Lock file not found: $LOCK_FILE" >&2
    fi
    # Kill orphaned Chromium processes for this pool's user-data-dir
    DIR_SUFFIX=""
    case "$POOL" in
      codex)  DIR_SUFFIX="-codex-${NUM}" ;;
      gemini) DIR_SUFFIX="-gemini-${NUM}" ;;
      *)      DIR_SUFFIX="-${NUM}" ;;
    esac
    for pid in $(wmic process where "CommandLine like '%playwright-mcp${DIR_SUFFIX}%'" get ProcessId 2>/dev/null | grep -o '[0-9]*'); do
      taskkill //PID "$pid" //F 2>/dev/null && echo "  Killed orphaned browser PID $pid"
    done
    ;;

  *)
    echo "Usage: playwright-lock.sh {claim|release|status|cleanup|force-release} [args]"
    echo "  claim [session_id] [pool]       - pool: claude(default)|codex|gemini"
    echo "  release [session_id] [pool]"
    echo "  status [pool|all(default)]"
    echo "  cleanup [max_age_s] [pool|all]"
    echo "  force-release <server> [pool]   - server: playwright1 or 1"
    exit 1
    ;;
esac
