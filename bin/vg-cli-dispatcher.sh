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
    # v2.80.0 Stage 4.1/4.2: wire --mode global|project + write
    # .vg/.install-target marker so find_vg_home() resolves correctly.
    target="global"
    for arg in "$@"; do
      case "$arg" in
        --global)  target="global" ;;
        --project) target="project" ;;
      esac
    done
    project_root="$(pwd)"
    if [ "$target" = "global" ]; then
      bash "${VG_HOME}/scripts/hooks/install-hooks.sh" \
        --target "${HOME}/.claude/settings.json" \
        --mode global
      echo "vgflow: hooks installed at ~/.claude/settings.json (mode=global, VG_HOME=${VG_HOME})"
    else
      bash "${VG_HOME}/scripts/hooks/install-hooks.sh" \
        --target "${project_root}/.claude/settings.json" \
        --mode project
      echo "vgflow: hooks installed at ${project_root}/.claude/settings.json (mode=project)"
    fi
    # Write project install-target marker when invoked from a git repo.
    # Skip when cwd is the user's home or has no .git anchor (avoid littering
    # random dirs with stray .vg/ folders).
    if [ -d "${project_root}/.git" ] || [ -f "${project_root}/.vg/.install-target" ]; then
      mkdir -p "${project_root}/.vg"
      printf '%s\n' "$target" > "${project_root}/.vg/.install-target"
      echo "vgflow: wrote ${project_root}/.vg/.install-target=${target}"
    fi
    ;;

  sync|update)
    # v2.80.0 Stage 4.4: prefer git pull when VG_HOME is a git clone (dev
    # install), else hint at npm. Project-mode users should run /vg:update
    # inside Claude Code/Codex (uses 3-way merge), not this CLI sync which
    # only refreshes the static harness.
    if [ -d "${VG_HOME}/.git" ]; then
      echo "vgflow: pulling latest from upstream (${VG_HOME})..."
      (cd "${VG_HOME}" && git pull --ff-only origin main)
      echo "vgflow: updated to $(cat "${VG_HOME}/VERSION" 2>/dev/null || echo unknown)"
    elif command -v npm >/dev/null 2>&1; then
      echo "vgflow: VG_HOME is not a git clone — upgrading via npm..."
      npm install -g vgflow@latest
      echo "vgflow: updated. Run 'vg version' to confirm."
    else
      echo "vgflow: VG_HOME=${VG_HOME} is not a git clone and npm not on PATH." >&2
      echo "  Install npm or re-clone: git clone https://github.com/vietdev99/vgflow ${VG_HOME}" >&2
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
    # v2.80.0 Stage 4.3: remove VG hook entries from target settings.json.
    # Backs the file up first (.bak.<epoch>) and rewrites without VG hooks.
    # Does NOT delete VG_HOME (~/.vgflow/) or project .vg/ — pure hook removal.
    target="global"
    for arg in "$@"; do
      case "$arg" in
        --global)  target="global" ;;
        --project) target="project" ;;
      esac
    done
    if [ "$target" = "global" ]; then
      settings="${HOME}/.claude/settings.json"
    else
      settings="$(pwd)/.claude/settings.json"
    fi
    if [ ! -f "$settings" ]; then
      echo "vgflow: nothing to uninstall — ${settings} does not exist"
      exit 0
    fi
    backup="${settings}.bak.$(date +%s)"
    cp "$settings" "$backup"
    python3 - "$settings" <<'PY'
import json, sys
from pathlib import Path

target = Path(sys.argv[1])
data = json.loads(target.read_text(encoding="utf-8"))
hooks = data.get("hooks") or {}

def is_vg_entry(entry):
    inner = entry.get("hooks") or [] if isinstance(entry, dict) else []
    return any("vg-" in (h.get("command") or "") for h in inner if isinstance(h, dict))

removed = 0
for event, entries in list(hooks.items()):
    if not isinstance(entries, list):
        continue
    kept = [e for e in entries if not is_vg_entry(e)]
    removed += len(entries) - len(kept)
    if kept:
        hooks[event] = kept
    else:
        del hooks[event]

if hooks:
    data["hooks"] = hooks
elif "hooks" in data:
    del data["hooks"]

target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
print(f"vgflow: removed {removed} VG hook entr{'y' if removed == 1 else 'ies'} from {target}")
PY
    echo "vgflow: backup saved at ${backup}"
    if [ "$target" = "project" ] && [ -f ".vg/.install-target" ]; then
      rm -f ".vg/.install-target"
      echo "vgflow: removed .vg/.install-target (run 'vg install' to re-attach)"
    fi
    ;;

  *)
    echo "vg: unknown command '${cmd}'" >&2
    echo "Run 'vg help' for usage." >&2
    exit 2
    ;;
esac
