#!/bin/bash
# build-commit-queue.sh — serialize git staging + commit across parallel VG executors.
#
# Problem it solves:
#   When /vg:build spawns N executor agents in parallel (same wave, different files,
#   no file-path conflict), each agent independently calls `git add` then `git commit`.
#   Git serializes only the final `commit` via `.git/index.lock`, but the index
#   itself is shared state across concurrent `git add` calls. If agent-A stages
#   `fileA.ts` and agent-B stages `fileB.ts` before either commits, whoever commits
#   first absorbs BOTH files into their commit, leaving the other agent with nothing
#   to commit.
#
#   This surfaced in Phase 10 Wave 1: Task 2's `schemas.js` was absorbed into
#   Task 3's `feat(10-03)` commit, and Task 2 had to produce a follow-up `docs`
#   commit with an audit trail since history was already corrupted.
#
# Strategy:
#   mkdir-based mutex (atomic on all POSIX-compliant filesystems + NTFS). Each
#   executor acquires the lock before `git add + commit`, releases after. flock
#   would be cleaner but isn't shipped with Git Bash on Windows, and VG must run
#   on Windows + macOS + Linux equivalently.
#
# Contract for executor agents:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/build-commit-queue.sh"
#   vg_commit_queue_acquire "task-${TASK_NUM}"   # blocks until lock held
#   git add <only-my-files>                       # no cross-agent staging interleave
#   git commit -m "..."                           # isolated commit
#   vg_commit_queue_release                       # releases for next waiter
#
# Timeouts + safety:
#   - Default 180s wait per acquire (tunable via arg 2)
#   - Stale-lock breaking: if holder > 600s old, assume crashed agent, break + retry
#   - Holder file records task_id + pid + timestamp for debugging
#   - On script exit (clean or signal), trap releases the lock if still held

set -u

# Location of the shared mutex directory. Must be outside .git (git cleans it)
# and outside .planning/.vg phase dirs (noise in scope).
VG_COMMIT_LOCK_DIR="${VG_COMMIT_LOCK_DIR:-.vg/.build-queue/commit.lock}"
VG_COMMIT_LOCK_STALE_SECONDS="${VG_COMMIT_LOCK_STALE_SECONDS:-600}"
VG_COMMIT_LOCK_POLL_INTERVAL_MS="${VG_COMMIT_LOCK_POLL_INTERVAL_MS:-300}"

# Convert ms to bash-friendly sleep arg (0.3 for 300ms etc.)
_vg_commit_queue_sleep() {
  local ms="${1:-300}"
  local sec_int=$((ms / 1000))
  local sec_frac=$((ms % 1000))
  # Pad fraction to 3 digits
  printf -v sec_frac_str '%03d' "$sec_frac"
  sleep "${sec_int}.${sec_frac_str}"
}

_vg_commit_queue_now() {
  date -u +%s
}

# Cross-platform mtime of a path (directory or file) in epoch seconds.
_vg_commit_queue_mtime() {
  local p="$1"
  stat -c %Y "$p" 2>/dev/null || stat -f %m "$p" 2>/dev/null || echo 0
}

# Acquire the global commit mutex. Blocks until lock held or timeout.
#   Arg 1 (required): task_id — recorded in holder.txt for debugging
#   Arg 2 (optional): max_wait_seconds — default 180
# Exit codes:
#   0 — lock acquired
#   1 — timeout (no lock held, do NOT proceed to git add/commit)
#   2 — usage error (no task_id)
vg_commit_queue_acquire() {
  local task_id="${1:-}"
  local max_wait="${2:-180}"

  if [ -z "$task_id" ]; then
    echo "⛔ vg_commit_queue_acquire: task_id required" >&2
    return 2
  fi

  mkdir -p "$(dirname "$VG_COMMIT_LOCK_DIR")"

  local start
  start=$(_vg_commit_queue_now)
  local attempt=0

  while true; do
    # Atomic acquire via mkdir. `mkdir` fails if dir exists; succeeds
    # exclusively for the first caller.
    if mkdir "$VG_COMMIT_LOCK_DIR" 2>/dev/null; then
      # Record holder metadata so stale-lock detection can decide.
      printf '%s:pid=%d:ts=%d\n' "$task_id" "$$" "$(_vg_commit_queue_now)" \
        > "$VG_COMMIT_LOCK_DIR/holder.txt"

      # Bug #9 fix (2026-04-19): auto-clean orphan staged files from a crashed
      # prior holder. SIGKILL / OOM / power loss bypass the trap, so files can
      # stay in the git index even after lock is stale-broken. If we acquired
      # the lock AND the index has staged files that aren't ours (we haven't
      # staged anything yet this critical section), reset them. Safe — our
      # own staging happens AFTER acquire.
      local pre_acquire_staged
      pre_acquire_staged=$(git diff --cached --name-only 2>/dev/null | head -1)
      if [ -n "$pre_acquire_staged" ]; then
        echo "⚠ vg_commit_queue: orphan staged files detected on acquire (from crashed prior holder)" >&2
        echo "   Unstaging before critical section (working tree preserved)" >&2
        git reset HEAD -- . >/dev/null 2>&1 || true
      fi

      # Register trap to release on exit so a crashing agent does not deadlock
      # the wave. Only register once per shell — guarded by VG_COMMIT_LOCK_HELD.
      if [ "${VG_COMMIT_LOCK_HELD:-0}" != "1" ]; then
        trap 'vg_commit_queue_release 2>/dev/null || true' EXIT INT TERM
        export VG_COMMIT_LOCK_HELD=1
      fi

      # Auto-hook progress tracking if caller exports VG_BUILD_PHASE_DIR +
      # VG_BUILD_TASK_NUM. This keeps .build-progress.json in sync across
      # compacts — we can always see who's currently in the critical section.
      if [ -n "${VG_BUILD_PHASE_DIR:-}" ] && [ -n "${VG_BUILD_TASK_NUM:-}" ]; then
        if type -t vg_build_progress_mutex_acquired >/dev/null 2>&1; then
          vg_build_progress_mutex_acquired "$VG_BUILD_PHASE_DIR" "$VG_BUILD_TASK_NUM" 2>/dev/null || true
        fi
      fi

      return 0
    fi

    # Lock exists — check for timeout
    local now elapsed
    now=$(_vg_commit_queue_now)
    elapsed=$((now - start))
    if [ $elapsed -gt $max_wait ]; then
      local holder=""
      [ -f "$VG_COMMIT_LOCK_DIR/holder.txt" ] && \
        holder=$(cat "$VG_COMMIT_LOCK_DIR/holder.txt" 2>/dev/null)
      echo "⛔ vg_commit_queue: timeout after ${max_wait}s waiting for lock" >&2
      echo "   Task:   $task_id" >&2
      echo "   Holder: ${holder:-unknown}" >&2
      return 1
    fi

    # Stale-lock detection (break if existing lock older than threshold)
    local lock_mtime lock_age
    lock_mtime=$(_vg_commit_queue_mtime "$VG_COMMIT_LOCK_DIR")
    lock_age=$((now - lock_mtime))
    if [ $lock_age -gt $VG_COMMIT_LOCK_STALE_SECONDS ]; then
      local stale_holder=""
      [ -f "$VG_COMMIT_LOCK_DIR/holder.txt" ] && \
        stale_holder=$(cat "$VG_COMMIT_LOCK_DIR/holder.txt" 2>/dev/null)
      echo "⚠ vg_commit_queue: breaking stale lock (${lock_age}s old, holder: ${stale_holder:-unknown})" >&2
      rm -rf "$VG_COMMIT_LOCK_DIR" 2>/dev/null
      # Loop and retry mkdir
      continue
    fi

    attempt=$((attempt + 1))
    # Every 20 polls (~6s at default 300ms), log waiting state so user sees progress
    if [ $((attempt % 20)) -eq 0 ]; then
      local cur_holder=""
      [ -f "$VG_COMMIT_LOCK_DIR/holder.txt" ] && \
        cur_holder=$(cat "$VG_COMMIT_LOCK_DIR/holder.txt" 2>/dev/null)
      echo "   vg_commit_queue: ${task_id} waiting ${elapsed}s (holder: ${cur_holder:-unknown})" >&2
    fi

    _vg_commit_queue_sleep "$VG_COMMIT_LOCK_POLL_INTERVAL_MS"
  done
}

# Release the global commit mutex. Safe to call if not holding — no-op.
vg_commit_queue_release() {
  if [ -d "$VG_COMMIT_LOCK_DIR" ]; then
    rm -rf "$VG_COMMIT_LOCK_DIR" 2>/dev/null
  fi
  unset VG_COMMIT_LOCK_HELD
}

# Diagnostic: show current lock state (who holds it, for how long).
vg_commit_queue_status() {
  if [ ! -d "$VG_COMMIT_LOCK_DIR" ]; then
    echo "vg_commit_queue: FREE (no lock held)"
    return 0
  fi
  local holder age
  holder=$(cat "$VG_COMMIT_LOCK_DIR/holder.txt" 2>/dev/null || echo "unknown")
  local mtime
  mtime=$(_vg_commit_queue_mtime "$VG_COMMIT_LOCK_DIR")
  age=$(($(_vg_commit_queue_now) - mtime))
  echo "vg_commit_queue: HELD"
  echo "  holder: $holder"
  echo "  age:    ${age}s"
  echo "  dir:    $VG_COMMIT_LOCK_DIR"
}

# Wrap a full "stage + commit" operation in the mutex. Convenience for agents
# that want one-line safety.
#
# Usage:
#   vg_commit_queue_wrap "task-10-02" 180 \
#     "git add apps/workers/src/consumer/clickhouse/schemas.js && \
#      git commit -m 'feat(10-02): extend ClickHouse schemas for deals'"
#
# Returns the exit code of the inner command, or 1 on lock timeout.
vg_commit_queue_wrap() {
  local task_id="$1"
  local max_wait="${2:-180}"
  local cmd="$3"

  vg_commit_queue_acquire "$task_id" "$max_wait" || return $?
  local rc
  eval "$cmd"
  rc=$?
  vg_commit_queue_release
  return $rc
}

# Issue #38 (2026-04-29): atomic "stage + commit" inside the mutex with an
# explicit file list. Eliminates the cross-absorb bug where parallel
# executors `git add` BEFORE acquiring the lock — by the time they hit
# the mutex, the index already contains another task's staged files.
#
# This helper is the SAFE primitive — agents should call it instead of
# `git add` + `vg_commit_queue_acquire` + `git commit` separately.
#
# Usage:
#   echo "feat(10-02): extend ClickHouse schemas
#
#   Per CONTEXT.md D-15
#   " > /tmp/msg-10-02.txt
#   vg_commit_with_files "task-10-02" 180 /tmp/msg-10-02.txt \
#     apps/workers/src/consumer/clickhouse/schemas.js \
#     apps/workers/src/consumer/clickhouse/migration.sql
#
# Args:
#   1: task_id (required) — recorded in holder.txt for debugging
#   2: max_wait_seconds — passed to acquire
#   3: msg_file — path to commit message file (consumed via `git commit -F`)
#   4..N: files to stage with `git add` (each path separately, no globs)
#
# Exit codes:
#   0 — committed successfully
#   1 — lock acquire timeout (no change)
#   2 — usage error (missing args / msg_file not found)
#   * — propagates `git add` or `git commit` exit code on failure
#
# Why explicit file list (not glob): glob expansion happens in the caller's
# context BEFORE acquire, defeating the purpose. List the files literally.
vg_commit_with_files() {
  local task_id="${1:-}"
  local max_wait="${2:-180}"
  local msg_file="${3:-}"
  shift 3 || true

  if [ -z "$task_id" ] || [ -z "$msg_file" ] || [ "$#" -eq 0 ]; then
    echo "⛔ vg_commit_with_files usage: vg_commit_with_files <task_id> <max_wait> <msg_file> <file>..." >&2
    return 2
  fi

  # v2.46.0 (Issue #76) — detect the common msg-first misuse:
  #   vg_commit_with_files "feat(10-02): subject" file1 file2 ...
  # When task_id looks like a Conventional Commit subject, the caller almost
  # certainly conflated this helper with `git commit -m`. Emit a targeted
  # error before letting the malformed call fall through to the file-not-found
  # branch (which produces a confusing message).
  case "$task_id" in
    feat\(*|fix\(*|docs\(*|style\(*|refactor\(*|perf\(*|test\(*|chore\(*|build\(*|ci\(*|revert\(*|feat:\ *|fix:\ *|docs:\ *|chore:\ *)
      cat >&2 <<EOF
⛔ vg_commit_with_files: detected msg-as-first-arg misuse.
   You called: vg_commit_with_files "$task_id" ...
   Correct shape: vg_commit_with_files <task_id> <max_wait_secs> <msg_file_path> <file>...
     - task_id is a SHORT identifier (e.g. "task-10-02"), NOT the commit subject
     - msg_file is a PATH to a file containing the commit message (e.g. /tmp/msg-10-02.txt)
   Example (from commands/vg/_shared/vg-executor-rules.md):
     echo "feat(10-02): subject\\n\\nBody" > /tmp/msg-10-02.txt
     vg_commit_with_files "task-10-02" 180 /tmp/msg-10-02.txt path/to/file.ts
EOF
      return 2
      ;;
  esac

  if [ ! -f "$msg_file" ]; then
    echo "⛔ vg_commit_with_files: msg_file not found: $msg_file" >&2
    return 2
  fi

  # Pre-flight check: warn if the index already has staged files belonging
  # to OTHER tasks. This is the #38 symptom — caller broke discipline.
  # We don't auto-fix here (acquire's orphan-clean handles crash recovery);
  # this is just diagnostic.
  local pre_staged
  pre_staged=$(git diff --cached --name-only 2>/dev/null)
  if [ -n "$pre_staged" ]; then
    echo "⚠ vg_commit_with_files($task_id): index has pre-staged files BEFORE acquire:" >&2
    echo "$pre_staged" | sed 's/^/   /' >&2
    echo "   These will be absorbed into THIS task's commit. If they belong to" >&2
    echo "   another task, abort now (Ctrl-C) — issue #38 cross-absorb pattern." >&2
  fi

  vg_commit_queue_acquire "$task_id" "$max_wait" || return $?

  local rc=0
  # Stage AFTER acquire — this is the only correct sequencing.
  local f
  for f in "$@"; do
    if ! git add -- "$f"; then
      echo "⛔ vg_commit_with_files: git add failed for $f" >&2
      rc=$?
      break
    fi
  done

  if [ "$rc" -eq 0 ]; then
    git commit -F "$msg_file"
    rc=$?
  fi

  vg_commit_queue_release
  return $rc
}
