#!/bin/bash
# vg-expand-round-wrapper.sh — safe fd-3 capture for dimension-expander (v1.9.5 R3.4+)
#
# Previously orchestrators had to remember exact redirection:
#   PROMPT=$(expand_dimensions ... 3>&1 1>/dev/null 2>/dev/null)
# A missed redirect = silent empty-string prompt = subagent fail-silent.
# This wrapper encapsulates the pattern so skills just call:
#   PROMPT=$(vg-expand-round-wrapper.sh "$ROUND" "$TOPIC" "$ACCUMULATED" [FOUNDATION_PATH])
#
# Usage:
#   bash .claude/commands/vg/_shared/lib/vg-expand-round-wrapper.sh \
#        "$ROUND" "$TOPIC" "$ROUND_QA_ACCUMULATED" [FOUNDATION_PATH]
#
# Output (stdout): full prompt CONTENT ready to pass as Task subagent prompt parameter.
# Exit: 0 on success, 1 if expand_dimensions helper missing/errored.

set -u

if [ "$#" -lt 3 ]; then
  echo "usage: vg-expand-round-wrapper.sh ROUND TOPIC ACCUMULATED_ANSWERS [FOUNDATION_PATH]" >&2
  exit 1
fi

ROUND="$1"
TOPIC="$2"
ACCUMULATED="$3"
FOUNDATION="${4:-${PLANNING_DIR:-.planning}/FOUNDATION.md}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dimension-expander.sh" 2>/dev/null || {
  echo "⛔ vg-expand-round-wrapper: dimension-expander.sh not found at ${SCRIPT_DIR}" >&2
  exit 1
}

if ! type -t expand_dimensions >/dev/null 2>&1; then
  echo "⛔ vg-expand-round-wrapper: expand_dimensions function not exported" >&2
  exit 1
fi

# fd-3 content capture, suppressing other streams
# (v1.9.5 R3.4: helper emits prompt content on fd 3, not a file path)
expand_dimensions "$ROUND" "$TOPIC" "$ACCUMULATED" "$FOUNDATION" 3>&1 1>/dev/null 2>/dev/null
