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
  install [--global]             Install global hooks into Claude Code / Codex
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

ensure_home_vgflow() {
  local home_vgflow="${HOME}/.vgflow"
  local vg_real=""
  local home_real=""

  vg_real="$(cd "$VG_HOME" 2>/dev/null && pwd -P || true)"
  if [ -z "$vg_real" ]; then
    echo "vgflow: cannot resolve VG_HOME=${VG_HOME}" >&2
    return 1
  fi

  if [ -e "$home_vgflow" ] || [ -L "$home_vgflow" ]; then
    home_real="$(cd "$home_vgflow" 2>/dev/null && pwd -P || true)"
    if [ -n "$home_real" ] && [ "$home_real" = "$vg_real" ]; then
      export VG_HOME="$vg_real"
      return 0
    fi

    if [ -d "$home_vgflow" ] && [ ! -L "$home_vgflow" ]; then
      local backup="${home_vgflow}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
      mv "$home_vgflow" "$backup"
      echo "vgflow: backed up stale ~/.vgflow to ${backup}"
    else
      rm -f "$home_vgflow"
    fi
  fi

  mkdir -p "${HOME}"
  if ln -s "$vg_real" "$home_vgflow" 2>/dev/null; then
    export VG_HOME="$vg_real"
    echo "vgflow: linked ~/.vgflow -> ${vg_real}"
    return 0
  fi

  # Some Windows shells cannot create symlinks. Fall back to an exact copy so
  # hook paths under ~/.vgflow still resolve to the active package.
  mkdir -p "$home_vgflow"
  cp -R "$vg_real"/. "$home_vgflow"/
  export VG_HOME="$home_vgflow"
  echo "vgflow: copied active install into ~/.vgflow"
}

run_project_uninstall_helper() {
  local project_root="$1"
  local py=""
  for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then
      py="$cand"
      break
    fi
  done
  if [ -z "$py" ] || [ ! -f "${VG_HOME}/scripts/vg_uninstall.py" ]; then
    echo "vgflow: project cleanup helper unavailable; skipping project-local file cleanup"
    return 0
  fi
  "$py" "${VG_HOME}/scripts/vg_uninstall.py" --root "$project_root" --apply
}

refresh_global_cli_link() {
  local src="${HOME}/.vgflow/bin/vg.js"
  local dst="${HOME}/.local/bin/vg"
  local existing=""

  if [ ! -f "$src" ]; then
    src="${VG_HOME}/bin/vg.js"
  fi
  if [ ! -f "$src" ]; then
    echo "vgflow: warning: CLI source missing (${src}); skipping CLI link" >&2
    return 0
  fi

  chmod +x "$src" "${VG_HOME}/bin/vg-cli-dispatcher.sh" 2>/dev/null || true

  existing="$(command -v vg 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "vgflow: CLI available at ${existing}"
    return 0
  fi

  mkdir -p "${HOME}/.local/bin"
  if [ -L "$dst" ]; then
    rm -f "$dst"
  elif [ -e "$dst" ]; then
    echo "vgflow: warning: ${dst} exists and is not a symlink; skipping CLI link" >&2
    return 0
  fi

  if ln -s "$src" "$dst" 2>/dev/null; then
    echo "vgflow: linked CLI ${dst} -> ${src}"
  else
    cp "$src" "$dst"
    chmod +x "$dst" 2>/dev/null || true
    echo "vgflow: copied CLI into ${dst}"
  fi
}

refresh_global_claude_commands() {
  local src="${HOME}/.vgflow/commands/vg"
  local dst="${HOME}/.claude/commands/vg"
  local src_real=""
  local dst_real=""

  if [ ! -d "$src" ]; then
    src="${VG_HOME}/commands/vg"
  fi
  if [ ! -d "$src" ]; then
    echo "vgflow: warning: Claude command source missing (${src}); skipping command refresh" >&2
    return 0
  fi

  src_real="$(cd "$src" 2>/dev/null && pwd -P || true)"
  mkdir -p "${HOME}/.claude/commands"

  if [ -L "$dst" ]; then
    dst_real="$(cd "$dst" 2>/dev/null && pwd -P || true)"
    if [ -n "$src_real" ] && [ "$dst_real" = "$src_real" ]; then
      echo "vgflow: Claude commands already linked at ~/.claude/commands/vg"
      return 0
    fi
    rm -f "$dst"
  elif [ -e "$dst" ]; then
    local backup="${dst}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$dst" "$backup"
    echo "vgflow: backed up stale ~/.claude/commands/vg to ${backup}"
  fi

  if ln -s "$src" "$dst" 2>/dev/null; then
    echo "vgflow: linked Claude commands ~/.claude/commands/vg -> ${src}"
    return 0
  fi

  mkdir -p "$dst"
  cp -R "$src"/. "$dst"/
  echo "vgflow: copied Claude commands into ~/.claude/commands/vg"
}

codex_config_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$path"
  else
    printf '%s\n' "$path"
  fi
}

register_global_codex_agent() {
  local name="$1"
  local desc="$2"
  local config="$HOME/.codex/config.toml"
  local config_file
  mkdir -p "$HOME/.codex"
  touch "$config"
  config_file="$(codex_config_path "$HOME/.codex/agents/${name}.toml")"
  if ! grep -q "^\[agents\.${name}\]" "$config" 2>/dev/null; then
    cat >> "$config" <<EOF

[agents.${name}]
description = "${desc}"
config_file = "${config_file}"
EOF
  fi
}

refresh_global_codex() {
  local skills_src="${VG_HOME}/codex-skills"
  local agents_src="${VG_HOME}/templates/codex-agents"
  local deployed=0

  mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"
  if [ -d "$skills_src" ]; then
    while IFS= read -r skill_dir; do
      [ -f "$skill_dir/SKILL.md" ] || continue
      local skill
      skill="$(basename "$skill_dir")"
      rm -rf "$HOME/.codex/skills/$skill"
      mkdir -p "$HOME/.codex/skills/$skill"
      cp -R "$skill_dir"/. "$HOME/.codex/skills/$skill/"
      deployed=$((deployed + 1))
    done < <(find "$skills_src" -mindepth 1 -maxdepth 1 -type d | sort)
  fi
  if [ -d "$agents_src" ]; then
    cp "$agents_src/"*.toml "$HOME/.codex/agents/" 2>/dev/null || true
  fi
  register_global_codex_agent "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
  register_global_codex_agent "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
  register_global_codex_agent "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
  echo "vgflow: refreshed ${deployed} global Codex skill(s) in ~/.codex/skills"
}

repair_playwright_mcp() {
  local py=""
  for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then
      py="$cand"
      break
    fi
  done
  local validator="${VG_HOME}/scripts/validators/verify-playwright-mcp-config.py"
  if [ -n "$py" ] && [ -f "$validator" ]; then
    "$py" "$validator" --repair --quiet \
      --lock-source "${VG_HOME}/playwright-locks/playwright-lock.sh" || {
      echo "vgflow: warning: Playwright MCP repair failed; run '$py $validator --repair'" >&2
      return 0
    }
    echo "vgflow: Playwright MCP configured for Claude + Codex"
  fi
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
    # v3.6.6: global-only install. Project-local .claude/.codex VG surfaces
    # are pruned every install so Claude and Codex load one canonical harness.
    target="global"
    for arg in "$@"; do
      case "$arg" in
        --global)  target="global" ;;
        --project)
          echo "vgflow: --project is deprecated; installing global-only and pruning project-local VG files"
          target="global"
          ;;
      esac
    done
    project_root="$(pwd)"
    ensure_home_vgflow
    run_project_uninstall_helper "$project_root"
    refresh_global_cli_link
    refresh_global_claude_commands
    refresh_global_codex
    repair_playwright_mcp
    bash "${VG_HOME}/scripts/hooks/install-hooks.sh" \
      --target "${HOME}/.claude/settings.json" \
      --mode global
    echo "vgflow: hooks installed at ~/.claude/settings.json (mode=global, VG_HOME=${VG_HOME})"
    # Write project install-target marker when invoked from a git repo.
    # Skip when cwd is the user's home or has no .git anchor (avoid littering
    # random dirs with stray .vg/ folders).
    if [ -d "${project_root}/.git" ] || [ -f "${project_root}/.vg/.install-target" ]; then
      mkdir -p "${project_root}/.vg"
      printf '%s\n' "global" > "${project_root}/.vg/.install-target"
      echo "vgflow: wrote ${project_root}/.vg/.install-target=global"
    fi
    ;;

  sync|update)
    # v3.6.6: global-only update. Refresh VG_HOME/~/.vgflow, refresh global
    # Codex, prune project-local Claude/Codex VG files, install global hooks,
    # and force .vg/.install-target=global for the current project.
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
    ensure_home_vgflow
    refresh_global_cli_link
    refresh_global_claude_commands
    refresh_global_codex
    repair_playwright_mcp
    run_project_uninstall_helper "$(pwd)"
    bash "${VG_HOME}/scripts/hooks/install-hooks.sh" \
      --target "${HOME}/.claude/settings.json" \
      --mode global
    if [ -d "$(pwd)/.git" ] || [ -f "$(pwd)/.vg/.install-target" ]; then
      mkdir -p "$(pwd)/.vg"
      printf '%s\n' "global" > "$(pwd)/.vg/.install-target"
    fi
    echo "vgflow: global hooks refreshed and project-local VG files pruned"
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
    echo "  VG CLI:     $(command -v vg 2>/dev/null || echo missing)"
    if [ -f "${HOME}/.claude/settings.json" ]; then
      vg_hooks=$(grep -c "vgflow\|vg-orchestrator\|vg-pre-tool-use\|vg-post-tool-use\|vg-user-prompt-submit\|vg-stop\|vg-session-start" "${HOME}/.claude/settings.json" 2>/dev/null || echo 0)
      echo "  Claude hooks: ${vg_hooks} VG entries in ~/.claude/settings.json"
    fi
    if [ -d "${HOME}/.claude/commands/vg" ]; then
      vg_commands=$(find "${HOME}/.claude/commands/vg/" -maxdepth 1 -type f -name "*.md" 2>/dev/null | wc -l | tr -d '[:space:]')
      echo "  Claude commands: ${vg_commands} file(s) in ~/.claude/commands/vg"
    else
      echo "  Claude commands: missing ~/.claude/commands/vg"
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
      if [ "$target" = "project" ]; then
        run_project_uninstall_helper "$(pwd)"
        if [ -f ".vg/.install-target" ]; then
          rm -f ".vg/.install-target"
          echo "vgflow: removed .vg/.install-target (run 'vg install' to re-attach)"
        fi
      fi
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
    if [ "$target" = "project" ]; then
      run_project_uninstall_helper "$(pwd)"
      if [ -f ".vg/.install-target" ]; then
        rm -f ".vg/.install-target"
        echo "vgflow: removed .vg/.install-target (run 'vg install' to re-attach)"
      fi
    fi
    ;;

  *)
    echo "vg: unknown command '${cmd}'" >&2
    echo "Run 'vg help' for usage." >&2
    exit 2
    ;;
esac
