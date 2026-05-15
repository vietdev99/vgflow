#!/usr/bin/env bash
# Install VG git hooks into local .git/hooks/.
# Idempotent: re-running overwrites prior install.
#
# Usage: bash scripts/git-hooks/install.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

HOOKS_SRC="${REPO_ROOT}/scripts/git-hooks"
HOOKS_DST="${REPO_ROOT}/.git/hooks"

if [ ! -d "$HOOKS_DST" ]; then
  echo "⛔ Not a git repo (no .git/hooks dir): ${REPO_ROOT}" >&2
  exit 1
fi

mkdir -p "$HOOKS_DST"

# Install pre-push (Batch 44 codex mirror guard)
if [ -f "$HOOKS_SRC/pre-push" ]; then
  cp "$HOOKS_SRC/pre-push" "$HOOKS_DST/pre-push"
  chmod +x "$HOOKS_DST/pre-push" 2>/dev/null || true
  echo "✓ Installed pre-push hook (Batch 44 codex mirror guard)"
else
  echo "⚠ scripts/git-hooks/pre-push not found — skipped" >&2
fi

echo ""
echo "Local git hooks installed. To bypass in emergency:"
echo "  VG_SKIP_CODEX_GUARD=1 git push origin main --tags"
echo ""
echo "To uninstall: rm ${HOOKS_DST}/pre-push"
