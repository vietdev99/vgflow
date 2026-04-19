#!/bin/bash
# vg-challenge-answer-wrapper.sh — safe fd-3 capture for answer-challenger (v1.9.5 R3.4+)
#
# Wraps the answer-challenger helper's fd-3 content emission so orchestrators
# don't have to remember exact redirection pattern. A single missed redirect
# causes silent empty-prompt → subagent fails silently → gate skips.
#
# Usage:
#   PROMPT=$(bash .claude/commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
#            "$USER_ANSWER" "$ROUND_LABEL" "$COMMAND_NAME" "$ACCUMULATED_DRAFT")
#
# Output (stdout): full prompt CONTENT ready to pass to Task subagent.
# Exit: 0 on success, 1 if helper missing/errored, 2 if answer is trivial (no challenge needed).

set -u

if [ "$#" -lt 3 ]; then
  echo "usage: vg-challenge-answer-wrapper.sh USER_ANSWER ROUND_LABEL COMMAND_NAME [ACCUMULATED_DRAFT]" >&2
  exit 1
fi

USER_ANSWER="$1"
ROUND_LABEL="$2"
COMMAND_NAME="$3"
ACCUMULATED="${4:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/answer-challenger.sh" 2>/dev/null || {
  echo "⛔ vg-challenge-answer-wrapper: answer-challenger.sh not found at ${SCRIPT_DIR}" >&2
  exit 1
}

if ! type -t challenge_answer >/dev/null 2>&1; then
  echo "⛔ vg-challenge-answer-wrapper: challenge_answer function not exported" >&2
  exit 1
fi

# Trivial-answer auto-skip — helper has own detector
if type -t challenger_is_trivial >/dev/null 2>&1; then
  if challenger_is_trivial "$USER_ANSWER"; then
    exit 2
  fi
fi

# fd-3 content capture, suppress stdout/stderr noise
challenge_answer "$USER_ANSWER" "$ROUND_LABEL" "$COMMAND_NAME" "$ACCUMULATED" 3>&1 1>/dev/null 2>/dev/null
