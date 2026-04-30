# shellcheck shell=bash
# zsh-compat.sh — 1-line shim sourced by other helpers to make skill bash
# blocks iterate string vars correctly under Claude Code's /bin/zsh shell.
#
# Background:
#   Claude Code's Bash tool runs commands under /bin/zsh on macOS (and zsh
#   on most modern Linux distros if user picked it). zsh leaves unquoted
#   `$VAR` unsplit by default — `for a in $REQUIRED; do ...` (where
#   REQUIRED is a whitespace-separated string) iterates ONCE with `$a`
#   bound to the entire string instead of N times with each token.
#   45+ skill bash blocks under commands/vg/ rely on the bash semantics
#   (audited via grep -rE 'for\s+\w+\s+in\s+\$[A-Z_]+').
#
# Fix:
#   `setopt SH_WORD_SPLIT` enables bash-style word-splitting for the
#   sourcing shell. Per-tool-call scope (each Bash tool invocation is a
#   fresh shell), so this shim must be sourced from the start of every
#   bash block. We ship it from inside other commonly-sourced libs
#   (inject-rule-cards.sh, phase-profile.sh, etc.) so skill blocks that
#   already source one of those get the fix transparently.
#
# Usage:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/zsh-compat.sh"
#   # ...rest of bash block...
#
# No-op under bash (setopt is a zsh builtin; redirect swallows the
# "command not found" error). No-op when already enabled.

[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT 2>/dev/null
