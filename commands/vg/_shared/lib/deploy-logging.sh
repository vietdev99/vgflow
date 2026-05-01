# shellcheck shell=bash
# Deploy Logging — bash function library
# Companion runtime for: .claude/commands/vg/_shared/deploy-logging.md
#
# Exposed functions:
#   - deploy_log_init PHASE_DIR
#   - deploy_exec TAG CMD...                    # wraps + logs + returns cmd's rc
#   - deploy_log_snapshot PHASE_DIR             # captures infra state post-deploy
#   - deploy_log_end PHASE_DIR [OVERALL_RC]
#   - deploy_logging_enabled                    # check if logging active (guard)
#
# Log format (3 lines per command):
#   [ISO_TS] [TAG] BEGIN <cmd>
#   [ISO_TS] [TAG] END rc=<n> duration=<s>s
#   [ISO_TS] [TAG] STDOUT_LAST_LINES:           (optional, if stdout captured)
#     → <last 5 lines>
#
# File sink: .vg/phases/{phase}/.deploy-log.txt (append-only)

deploy_logging_enabled() {
  # Default ON; opt-out via env or config
  [ "${CONFIG_DEPLOY_LOGGING_ENABLED:-true}" = "true" ]
}

_deploy_iso_now() {
  date -u +%FT%TZ 2>/dev/null || python3 -c 'from datetime import datetime,timezone;print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
}

_deploy_epoch_now() {
  date -u +%s 2>/dev/null || python3 -c 'import time;print(int(time.time()))'
}

deploy_log_init() {
  local phase_dir="$1"
  if [ -z "$phase_dir" ]; then
    echo "⚠ deploy_log_init: PHASE_DIR missing" >&2
    return 1
  fi

  deploy_logging_enabled || return 0

  mkdir -p "$phase_dir" 2>/dev/null
  export DEPLOY_LOG="${phase_dir}/.deploy-log.txt"

  local now
  now=$(_deploy_iso_now)
  {
    echo "# Deploy log — phase $(basename "$phase_dir")"
    echo "# Session started: $now"
    echo "# Caller: ${CLAUDE_COMMAND:-unknown}"
    echo ""
  } > "$DEPLOY_LOG"

  return 0
}

deploy_exec() {
  local tag="$1"
  shift
  local cmd="$*"

  if ! deploy_logging_enabled; then
    eval "$cmd"
    return $?
  fi

  if [ -z "${DEPLOY_LOG:-}" ]; then
    # Logger not initialized — fallback exec without logging
    eval "$cmd"
    return $?
  fi

  local begin_ts begin_epoch
  begin_ts=$(_deploy_iso_now)
  begin_epoch=$(_deploy_epoch_now)

  echo "[$begin_ts] [$tag] BEGIN $cmd" >> "$DEPLOY_LOG"

  # Execute + capture stdout to temp for last-lines snippet (stderr passes through)
  local stdout_tmp
  stdout_tmp=$(mktemp 2>/dev/null || echo "/tmp/deploy_exec.$$.tmp")

  eval "$cmd" > >(tee "$stdout_tmp") 2>&1
  local rc=$?

  local end_ts end_epoch duration
  end_ts=$(_deploy_iso_now)
  end_epoch=$(_deploy_epoch_now)
  duration=$((end_epoch - begin_epoch))

  echo "[$end_ts] [$tag] END rc=$rc duration=${duration}s" >> "$DEPLOY_LOG"

  # Last 5 stdout lines if file non-empty (helps parser extract build summary, etc.)
  if [ -s "$stdout_tmp" ]; then
    echo "[$end_ts] [$tag] STDOUT_LAST_LINES:" >> "$DEPLOY_LOG"
    tail -n 5 "$stdout_tmp" 2>/dev/null | sed 's/^/  → /' >> "$DEPLOY_LOG"
  fi

  rm -f "$stdout_tmp" 2>/dev/null
  return $rc
}

deploy_log_snapshot() {
  local phase_dir="$1"
  if [ -z "$phase_dir" ]; then
    echo "⚠ deploy_log_snapshot: PHASE_DIR missing" >&2
    return 1
  fi

  deploy_logging_enabled || return 0

  local snapshot="${phase_dir}/.deploy-snapshot.txt"
  local now
  now=$(_deploy_iso_now)

  {
    echo "# Post-deploy infra snapshot"
    echo "# Captured: $now"
    echo "# Phase: $(basename "$phase_dir")"
    echo ""
    echo "## SSH target — runtime versions"

    # SSH alias resolved from vg.config.md (config.environments.sandbox.run_prefix
    # is "ssh vollx" by default; strip leading "ssh " to get bare alias).
    # Allow env-var override for non-default deployments.
    local ssh_alias="${VG_SSH_ALIAS:-${RUN_PREFIX#ssh }}"
    ssh_alias="${ssh_alias:-vollx}"   # final fallback if config not loaded

    # Try SSH, fail gracefully if target unreachable (local-only run)
    if command -v ssh >/dev/null 2>&1; then
      ssh -o ConnectTimeout=5 -o BatchMode=yes "$ssh_alias" \
        'node --version 2>/dev/null || echo "node: not installed"; \
         pnpm --version 2>/dev/null || echo "pnpm: not installed"; \
         python3 --version 2>/dev/null || echo "python3: not installed"; \
         cargo --version 2>/dev/null | head -1 || echo "cargo: not installed"; \
         uname -a; \
         cat /etc/os-release 2>/dev/null | head -3' 2>/dev/null \
        | sed 's/^/  /' \
        || echo "  (ssh $ssh_alias unreachable — skipping SSH snapshot)"
    else
      echo "  (ssh CLI not available — skipping)"
    fi

    echo ""
    echo "## PM2 services ($ssh_alias)"
    if command -v ssh >/dev/null 2>&1; then
      ssh -o ConnectTimeout=5 -o BatchMode=yes "$ssh_alias" 'pm2 jlist 2>/dev/null' 2>/dev/null \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not data:
        print('  (no pm2 services)')
    else:
        for p in data:
            name = p.get('name', '?')
            env = p.get('pm2_env', {})
            status = env.get('status', '?')
            restarts = env.get('restart_time', 0)
            print(f'  {name:<30} status={status:<8} restarts={restarts}')
except Exception as e:
    print(f'  (pm2 jlist parse failed: {e})')
" 2>/dev/null || echo "  (pm2 jlist fetch failed)"
    fi

    echo ""
    echo "## Disk ($ssh_alias /)"
    if command -v ssh >/dev/null 2>&1; then
      ssh -o ConnectTimeout=5 -o BatchMode=yes "$ssh_alias" 'df -h / 2>/dev/null' 2>/dev/null \
        | sed 's/^/  /' \
        || echo "  (df failed)"
    fi

    echo ""
    echo "## Local workspace (this machine)"
    node --version 2>/dev/null | sed 's/^/  node: /' || echo "  node: not installed"
    pnpm --version 2>/dev/null | sed 's/^/  pnpm: /' || echo "  pnpm: not installed"
    python3 --version 2>/dev/null | sed 's/^/  /' || echo "  python3: not installed"

  } > "$snapshot" 2>&1

  export DEPLOY_SNAPSHOT="$snapshot"
  echo "▸ Snapshot ghi vào: $snapshot" >&2
  return 0
}

deploy_log_end() {
  local phase_dir="$1"
  local overall_rc="${2:-0}"

  deploy_logging_enabled || return 0
  [ -z "${DEPLOY_LOG:-}" ] && return 0

  local now
  now=$(_deploy_iso_now)

  {
    echo ""
    echo "# Session ended: $now"
    echo "# Overall rc: $overall_rc"
  } >> "$DEPLOY_LOG"

  return 0
}
