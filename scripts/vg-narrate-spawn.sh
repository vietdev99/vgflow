#!/usr/bin/env bash
# vg-narrate-spawn — print colored-background tag for subagent spawn lifecycle.
#
# UX: GSD-style "chip" rendering — name appears as colored pill in chat,
# making subagent transitions visually distinct from regular AI text.
#
# USAGE
#   bash scripts/vg-narrate-spawn.sh <subagent-name> [<state>] [<context>]
#     state: spawning (default) | returned | failed
#     context: optional one-line description (e.g., "writing PLAN/index.md")
#
# OUTPUT
#   ANSI-colored tag + state + optional context. Renders as colored pill
#   in terminals supporting ANSI (Claude Code, Codex CLI, iTerm, etc.).
#   For non-ANSI clients, falls back to plain bracketed text.
#
# EXAMPLES
#   bash scripts/vg-narrate-spawn.sh vg-blueprint-planner
#     →  vg-blueprint-planner  spawning
#   bash scripts/vg-narrate-spawn.sh vg-blueprint-planner returned "PLAN/ written, 12 tasks"
#     →  vg-blueprint-planner  returned · PLAN/ written, 12 tasks
#   bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts failed "missing INTERFACE-STANDARDS"
#     →  vg-blueprint-contracts  failed · missing INTERFACE-STANDARDS

set -euo pipefail

NAME="${1:?usage: vg-narrate-spawn <subagent-name> [<state>] [<context>]}"
STATE="${2:-spawning}"
CONTEXT="${3:-}"

# State → ANSI background color (24-bit when supported).
# 42 = green bg, 46 = cyan bg, 41 = red bg, 30 = black fg, 37 = white fg, 1 = bold.
case "$STATE" in
  spawning)  BG=42 FG=30 ;;  # green bg, black fg — about to spawn
  returned)  BG=46 FG=30 ;;  # cyan bg, black fg — completed successfully
  failed)    BG=41 FG=37 ;;  # red bg, white fg — error/timeout/refused
  *)         BG=47 FG=30 ;;  # white bg, black fg — unknown state
esac

# Default: emit ANSI escape codes — Claude Code chat + Codex CLI + most
# terminals render them as colored pill. Set VG_NO_ANSI=1 for plain output
# (logs, CI, grep, etc.).
if [ "${VG_NO_ANSI:-0}" = "1" ]; then
  TAG="[$NAME]"
else
  # Bold + colored bg + colored fg, then reset. Renders as green pill.
  TAG=$(printf "\033[1;%sm\033[%sm %s \033[0m" "$BG" "$FG" "$NAME")
fi

if [ -n "$CONTEXT" ]; then
  printf "%s  %s · %s\n" "$TAG" "$STATE" "$CONTEXT"
else
  printf "%s  %s\n" "$TAG" "$STATE"
fi
