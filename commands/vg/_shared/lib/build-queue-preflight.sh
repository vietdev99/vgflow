#!/bin/bash
# build-queue-preflight.sh — preflight check for /vg:build.
#
# Catches leftover state from prior crashed runs BEFORE tagging wave-start:
#   1. Stale commit-queue lock (age > 10 min) → auto-break
#   2. Active commit-queue lock (age < threshold) → block unless --reset-queue
#   3. Staged-but-uncommitted files → block unless --reset-queue (would
#      silently leak into wave-start baseline, corrupting attribution)
#   4. Unresolved merge conflicts → always block
#
# Rationale:
#   The mutex helper (build-commit-queue.sh) auto-releases via EXIT trap on
#   normal/error/signal termination. But SIGKILL, power loss, or OS crash
#   skip the trap → lock dir persists. Without this preflight, the next
#   /vg:build run would deadlock at the first agent's acquire attempt (until
#   stale threshold breaks the lock — 10 min wasted).
#
#   Staged files from a crashed run are a different hazard: they're not the
#   mutex's concern (git index state), but they'd land inside wave-start tag
#   (HEAD) and then every executor commit after would look like it's
#   over-claiming those files. Attribution audit would flag the whole wave.
#
# Usage (sourced from build.md):
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/build-queue-preflight.sh"
#   vg_build_queue_preflight "$RESET_QUEUE_FLAG" "$PHASE_ARG"
#
# Returns:
#   0 — clean, proceed
#   1 — blocked, printed diagnostics + fix options

set -u

# Source the queue helper for mtime fn reuse
_VG_QUEUE_PREFLIGHT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./build-commit-queue.sh
source "${_VG_QUEUE_PREFLIGHT_DIR}/build-commit-queue.sh"

vg_build_queue_preflight() {
  local reset_queue="${1:-false}"
  local phase_arg="${2:-<phase>}"
  local blockers=()

  # --- 1. --reset-queue: wipe state + unstage leftovers ---
  if [ "$reset_queue" = "true" ]; then
    echo "⚠ --reset-queue — wiping build queue state"
    if [ -d ".vg/.build-queue" ]; then
      rm -rf .vg/.build-queue/ 2>/dev/null && echo "  ✓ cleared .vg/.build-queue/"
    fi
    # Unstage leftovers from prior run (keep working tree changes)
    if ! git diff --cached --quiet 2>/dev/null; then
      local n_staged
      n_staged=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
      git reset HEAD -- . >/dev/null 2>&1 && echo "  ✓ unstaged ${n_staged} file(s) (working tree untouched)"
    fi
    # Short-circuit — post-reset state is clean by construction
    return 0
  fi

  # --- 2. Stale lock detection ---
  if [ -d ".vg/.build-queue/commit.lock" ]; then
    local holder age
    holder=$(cat .vg/.build-queue/commit.lock/holder.txt 2>/dev/null || echo "unknown")
    age=$(( $(_vg_commit_queue_now) - $(_vg_commit_queue_mtime .vg/.build-queue/commit.lock) ))

    local stale_threshold="${VG_COMMIT_LOCK_STALE_SECONDS:-600}"
    if [ $age -gt $stale_threshold ]; then
      echo "⚠ Stale commit lock (${age}s old, holder: ${holder}) — auto-breaking"
      rm -rf .vg/.build-queue/commit.lock 2>/dev/null
      echo "  ✓ lock broken, proceeding"
    else
      echo "⛔ Commit queue lock held by another process"
      echo "     holder: ${holder}"
      echo "     age:    ${age}s (stale threshold: ${stale_threshold}s)"
      echo ""
      echo "   Options:"
      echo "     1. Wait — if another /vg:build is actively running elsewhere, let it finish"
      echo "     2. Break — /vg:build ${phase_arg} --reset-queue  (wipes lock + unstages leftovers)"
      echo "     3. Manual — rm -rf .vg/.build-queue/commit.lock  (if you know holder is dead)"
      blockers+=("lock")
    fi
  fi

  # --- 3. Staged-but-uncommitted files ---
  # These would land in wave-start tag HEAD and corrupt attribution audit for
  # every subsequent wave commit. Block unconditionally (or force --reset-queue).
  if ! git diff --cached --quiet 2>/dev/null; then
    local n_staged staged_sample
    n_staged=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
    staged_sample=$(git diff --cached --name-only 2>/dev/null | head -5)
    echo "⛔ ${n_staged} staged file(s) from a prior run — would leak into wave-start baseline"
    echo "$staged_sample" | sed 's/^/     /'
    [ "$n_staged" -gt 5 ] && echo "     ... (+$((n_staged - 5)) more)"
    echo ""
    echo "   Fix options:"
    echo "     1. git reset HEAD            # unstage, keep working tree"
    echo "     2. git stash                 # stash everything (pop after build)"
    echo "     3. git commit -m '...'       # commit now (if intentional)"
    echo "     4. /vg:build ${phase_arg} --reset-queue  # unstage automatically"
    blockers+=("staged")
  fi

  # --- 4. Unresolved merge conflicts — always block ---
  local conflicts
  conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null)
  if [ -n "$conflicts" ]; then
    echo "⛔ Unresolved merge conflicts (cannot build on conflicted working tree):"
    echo "$conflicts" | head -5 | sed 's/^/     /'
    echo ""
    echo "   Fix: resolve via your merge tool, then re-run /vg:build ${phase_arg}"
    blockers+=("conflicts")
  fi

  if [ "${#blockers[@]}" -gt 0 ]; then
    echo ""
    echo "Preflight blocked: ${blockers[*]}"
    return 1
  fi

  return 0
}
