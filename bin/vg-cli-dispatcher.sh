#!/usr/bin/env bash
# vgflow CLI dispatcher — routes `vg <subcmd>` to skills/scripts under VG_HOME.
#
# VG_HOME is exported by bin/vg.js (Node entry point) and points at the
# installed package root (e.g., ~/.vgflow/ when installed globally, or
# the npm install dir when invoked via local node_modules).

set -euo pipefail

if [ -z "${VG_HOME:-}" ]; then
  # Fallback: resolve from this script's location.
  VG_HOME="$(cd "$(dirname "$0")/.." && pwd)"
  export VG_HOME
fi

usage() {
  cat <<EOF
vgflow — deterministic AI-driven development harness

Usage:
  vg <command> [args...]

Commands:
  install [--global|--project]   Install hooks into Claude Code / Codex
  sync                           Pull latest from upstream + re-install
  update                         Alias for sync
  doctor                         Verify install + project state health
  health                         Per-phase manifest status
  version                        Print installed version
  uninstall [--global|--project] Remove VG hooks + scripts
  help                           This message

Inside a Claude Code or Codex session, prefer slash commands:
  /vg:project, /vg:specs, /vg:scope, /vg:blueprint, /vg:build,
  /vg:review, /vg:test, /vg:accept, /vg:deploy, /vg:doctor, ...

Documentation: https://github.com/vietdev99/vgflow
Issues:        https://github.com/vietdev99/vgflow/issues
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  version|--version|-v)
    if [ -f "${VG_HOME}/VERSION" ]; then
      cat "${VG_HOME}/VERSION"
    else
      echo "unknown"
    fi
    ;;

  help|--help|-h|"")
    usage
    ;;

  install)
    target="global"
    for arg in "$@"; do
      case "$arg" in
        --global)  target="global" ;;
        --project) target="project" ;;
      esac
    done
    if [ "$target" = "global" ]; then
      bash "${VG_HOME}/scripts/hooks/install-hooks.sh" --target "${HOME}/.claude/settings.json"
      echo "vgflow: hooks installed at ~/.claude/settings.json"
      echo "vgflow: VG_HOME=${VG_HOME}"
    else
      project_root="$(pwd)"
      bash "${VG_HOME}/scripts/hooks/install-hooks.sh" --target "${project_root}/.claude/settings.json"
      echo "vgflow: hooks installed at ${project_root}/.claude/settings.json"
    fi
    ;;

  sync|update)
    if [ -d "${VG_HOME}/.git" ]; then
      echo "vgflow: pulling latest from upstream..."
      (cd "${VG_HOME}" && git pull origin main)
      echo "vgflow: updated to $(cat "${VG_HOME}/VERSION" 2>/dev/null || echo unknown)"
    else
      echo "vgflow: VG_HOME is not a git clone — re-install via npm:" >&2
      echo "  npm install -g vgflow@latest" >&2
      exit 1
    fi
    ;;

  doctor)
    echo "vgflow doctor:"
    echo "  VG_HOME:    ${VG_HOME}"
    echo "  VERSION:    $(cat "${VG_HOME}/VERSION" 2>/dev/null || echo unknown)"
    echo "  CWD:        $(pwd)"
    echo "  Node:       $(node --version 2>/dev/null || echo missing)"
    echo "  Bash:       $(bash --version 2>/dev/null | head -1 || echo missing)"
    echo "  Python:     $(python3 --version 2>/dev/null || python --version 2>/dev/null || echo missing)"
    echo "  Git:        $(git --version 2>/dev/null || echo missing)"
    if [ -f "${HOME}/.claude/settings.json" ]; then
      vg_hooks=$(grep -c "vgflow\|vg-orchestrator\|vg-pre-tool-use\|vg-post-tool-use\|vg-user-prompt-submit\|vg-stop\|vg-session-start" "${HOME}/.claude/settings.json" 2>/dev/null || echo 0)
      echo "  Claude hooks: ${vg_hooks} VG entries in ~/.claude/settings.json"
    fi
    if [ -d ".vg" ]; then
      echo "  Project .vg/: present at $(pwd)/.vg/"
      [ -f ".vg/.install-target" ] && echo "  Install target: $(cat .vg/.install-target)"
    fi
    ;;

  health)
    # Delegate to vg-orchestrator if available
    if command -v python3 >/dev/null 2>&1 && [ -f "${VG_HOME}/scripts/vg-orchestrator/__main__.py" ]; then
      VG_REPO_ROOT="$(pwd)" python3 "${VG_HOME}/scripts/vg-orchestrator" health "$@"
    else
      echo "vgflow: orchestrator not available" >&2
      exit 1
    fi
    ;;

  uninstall)
    target="global"
    for arg in "$@"; do
      case "$arg" in
        --global)  target="global" ;;
        --project) target="project" ;;
      esac
    done
    echo "vgflow: uninstall ${target} not yet implemented"
    echo "Manual: edit settings.json and remove VG entries"
    exit 1
    ;;

  *)
    echo "vg: unknown command '${cmd}'" >&2
    echo "Run 'vg help' for usage." >&2
    exit 2
    ;;
esac
