#!/usr/bin/env bash
# VGFlow sync - deploy this repository's canonical workflow files.
#
# This repository is the source of truth. Sync is intentionally one-way:
#   vgflow-repo/{commands,skills,scripts,codex-skills,templates}
#     -> $DEV_ROOT/.claude and $DEV_ROOT/.codex
#     -> ~/.codex (unless --no-global)
#
# Usage:
#   ./sync.sh              # apply sync to current repo; global Codex skipped
#   DEV_ROOT=/project ./sync.sh
#   ./sync.sh --check      # dry-run, exits 1 if drift exists
#   ./sync.sh --verify     # run functional Codex mirror equivalence check
#   ./sync.sh --global-codex  # also deploy ~/.codex skills/agents
#   ./sync.sh --no-global     # accepted for compatibility; default behavior

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_ROOT="${DEV_ROOT:-$SCRIPT_DIR}"
BASH_BIN="${BASH:-bash}"
if [ -n "${BASH:-}" ]; then
  # Windows can resolve `find` to C:\Windows\System32\find.exe when Git Bash
  # is launched non-login from PowerShell/Codex. Prefer the active Bash toolchain
  # so sync_tree uses POSIX find/sort/diff/cp/rm consistently.
  export PATH="$(dirname "$BASH"):$PATH"
fi
PYTHON_BIN="$(command -v python3 || command -v python || true)"

MODE_CHECK=false
SKIP_GLOBAL=true
VERIFY_ONLY=false
DEPRECATED_NO_SOURCE=false

for arg in "$@"; do
  case "$arg" in
    --check) MODE_CHECK=true ;;
    --verify) VERIFY_ONLY=true ;;
    --no-global) SKIP_GLOBAL=true ;;
    --global-codex) SKIP_GLOBAL=false ;;
    --no-source) DEPRECATED_NO_SOURCE=true ;;
    -h|--help)
      sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [ "$VERIFY_ONLY" = "true" ]; then
  if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python3 or python is required for --verify" >&2
    exit 127
  fi
  "$PYTHON_BIN" "$SCRIPT_DIR/scripts/verify-codex-mirror-equivalence.py"
  exit $?
fi

if [ "$MODE_CHECK" = "true" ]; then
  echo "VGFlow sync check: global-only mode; project-local .claude/.codex deploy disabled."
  echo "Source: $SCRIPT_DIR"
  echo "Target cleanup root: $TARGET_ROOT"
  exit 0
fi

echo "VGFlow sync: global-only mode"
echo "  source: $SCRIPT_DIR"
echo "  target project for cleanup/marker: $TARGET_ROOT"
echo ""
"$BASH_BIN" "$SCRIPT_DIR/scripts/generate-codex-skills.sh" --force >/tmp/vgflow-codex-generate.log
tail -5 /tmp/vgflow-codex-generate.log || true
(
  cd "$TARGET_ROOT"
  VG_HOME="$SCRIPT_DIR" bash "$SCRIPT_DIR/bin/vg-cli-dispatcher.sh" install --global
)
exit $?

SUMMARY=()
CHANGED=0
MISSING=0
MCP_FAILED=false

note() {
  SUMMARY+=("$1")
}

compare() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [ ! -f "$src" ]; then
    note "MISSING source: $label ($src)"
    MISSING=$((MISSING + 1))
    return
  fi

  if [ ! -f "$dst" ]; then
    note "NEW: $label -> $dst"
    CHANGED=$((CHANGED + 1))
    if [ "$MODE_CHECK" = "false" ]; then
      mkdir -p "$(dirname "$dst")"
      cp "$src" "$dst"
    fi
    return
  fi

  if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
    note "UPDATED: $label"
    CHANGED=$((CHANGED + 1))
    if [ "$MODE_CHECK" = "false" ]; then
      cp "$src" "$dst"
    fi
  fi
}

sync_tree() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"

  [ -d "$src_dir" ] || return

  while IFS= read -r src_file; do
    local rel="${src_file#$src_dir/}"
    compare "$src_file" "$dst_dir/$rel" "$label:$rel"
  done < <(find "$src_dir" -type f \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' 2>/dev/null | sort)
}

sync_codex_agents() {
  local dst_root="$1"
  [ -d "$SCRIPT_DIR/templates/codex-agents" ] || return
  sync_tree "$SCRIPT_DIR/templates/codex-agents" "$dst_root/agents" "codex-agent"
}

sync_codex_skills_exact() {
  local dst_root="$1"
  local label="$2"
  [ -d "$SCRIPT_DIR/codex-skills" ] || return
  mkdir -p "$dst_root/skills"

  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    local skill
    skill="$(basename "$skill_dir")"
    local dst_dir="$dst_root/skills/$skill"
    if [ "$MODE_CHECK" = "false" ]; then
      rm -rf "$dst_dir"
    fi
    sync_tree "$skill_dir" "$dst_dir" "$label:$skill"
  done < <(find "$SCRIPT_DIR/codex-skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
}

# v3.6.1 — prune duplicate Codex skills when global + project both populated.
#
# Bug: Codex picker reads BOTH ~/.codex/skills/ AND <project>/.codex/skills/.
# When sync deployed to both (--global-codex previously, then default project
# sync), every vg-* skill shows up twice in the picker. Users can't tell which
# is current.
#
# Fix: when both have the same skill name, prune one. Resolution rule:
#   - If $TARGET_ROOT/.vg/.install-target == "global" → prune project copy (~/.codex wins)
#   - If $TARGET_ROOT/.vg/.install-target == "project" → prune global copy if it matches our codex-skills/ source list
#   - No marker → prune project copy (default: prefer global, matches v3.0.0 architecture)
prune_duplicate_codex_skills() {
  local target_root="$1"
  local home_codex="$HOME/.codex/skills"
  local proj_codex="$target_root/.codex/skills"
  local marker_file="$target_root/.vg/.install-target"
  local install_target=""
  [ -f "$marker_file" ] && install_target="$(tr -d '[:space:]' < "$marker_file" 2>/dev/null || true)"

  [ -d "$home_codex" ] || [ -d "$proj_codex" ] || return 0
  if [ "$MODE_CHECK" = "true" ]; then
    return 0
  fi

  local pruned=0
  local prune_target=""
  case "$install_target" in
    project)
      # Project install — global ~/.codex skill that overlaps our deployed list is stale
      prune_target="$home_codex"
      ;;
    global|"")
      # Global install (or unmarked legacy) — prune project copy
      prune_target="$proj_codex"
      ;;
    *)
      return 0
      ;;
  esac

  # Build list of skills WE own (canonical names from $SCRIPT_DIR/codex-skills)
  while IFS= read -r src_skill_dir; do
    [ -d "$src_skill_dir" ] || continue
    local skill_name
    skill_name="$(basename "$src_skill_dir")"
    local dup_dir="$prune_target/$skill_name"
    if [ -d "$dup_dir" ] && [ "$prune_target" != "$home_codex" ] || \
       { [ "$prune_target" = "$home_codex" ] && [ -d "$dup_dir" ] && [ -d "$proj_codex/$skill_name" ]; }; then
      rm -rf "$dup_dir" 2>/dev/null && pruned=$((pruned + 1))
    fi
  done < <(find "$SCRIPT_DIR/codex-skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)

  if [ "$pruned" -gt 0 ]; then
    note "PRUNED ${pruned} duplicate Codex skill dirs from ${prune_target} (install_target=${install_target:-unset})"
    CHANGED=$((CHANGED + 1))
  fi
}

codex_config_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$path"
  else
    printf '%s\n' "$path"
  fi
}

register_global_codex_agents() {
  local config="$HOME/.codex/config.toml"
  touch "$config"

  register_one() {
    local name="$1"
    local desc="$2"
    local config_file
    config_file="$(codex_config_path "$HOME/.codex/agents/${name}.toml")"
    if ! grep -q "^\[agents\.${name}\]" "$config" 2>/dev/null; then
      cat >> "$config" <<EOF

[agents.${name}]
description = "${desc}"
config_file = "${config_file}"
EOF
      note "REGISTERED global Codex agent: $name"
      CHANGED=$((CHANGED + 1))
    fi
  }

  register_one "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
  register_one "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
  register_one "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
}

disable_legacy_codex_hooks() {
  local root="$1"
  local label="$2"

  [ -d "$root/.codex" ] || return
  if [ -z "$PYTHON_BIN" ]; then
    note "MISSING python: cannot disable legacy Codex hooks for $label"
    MISSING=$((MISSING + 1))
    return
  fi

  local result
  result="$("$PYTHON_BIN" - "$root" "$MODE_CHECK" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
check = sys.argv[2] == "true"
changed = False

def vg_owned_command(cmd: str) -> bool:
    return (
        ".claude/scripts/codex-hooks/" in cmd
        or ("VG_RUNTIME=codex" in cmd and ".claude/scripts/vg-entry-hook.py" in cmd)
    )

hooks_path = root / ".codex" / "hooks.json"
if hooks_path.exists():
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    if isinstance(data, dict) and isinstance(data.get("hooks"), dict):
        new_hooks = {}
        for event, entries in data["hooks"].items():
            if not isinstance(entries, list):
                new_hooks[event] = entries
                continue
            kept_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    kept_entries.append(entry)
                    continue
                hook_list = entry.get("hooks")
                if not isinstance(hook_list, list):
                    kept_entries.append(entry)
                    continue
                kept_hooks = [
                    h for h in hook_list
                    if not (isinstance(h, dict) and vg_owned_command(str(h.get("command", ""))))
                ]
                if kept_hooks:
                    updated = dict(entry)
                    updated["hooks"] = kept_hooks
                    kept_entries.append(updated)
            if kept_entries:
                new_hooks[event] = kept_entries
        if new_hooks != data["hooks"]:
            changed = True
            if not check:
                if new_hooks:
                    hooks_path.write_text(json.dumps({"hooks": new_hooks}, indent=2) + "\n", encoding="utf-8")
                else:
                    hooks_path.unlink()

config_path = root / ".codex" / "config.toml"
if config_path.exists():
    lines = config_path.read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if not line.strip().startswith("codex_hooks")]
    if filtered != lines:
        changed = True
        if not check:
            text = "\n".join(filtered).strip()
            if text in ("", "[features]"):
                config_path.unlink()
            else:
                config_path.write_text(text + "\n", encoding="utf-8")

print("changed" if changed else "clean")
PY
)"
  if [ "$result" = "changed" ]; then
    note "UPDATED: $label legacy Codex hooks disabled"
    CHANGED=$((CHANGED + 1))
    if [ "$MODE_CHECK" = "false" ]; then
      echo "  OK: legacy Codex hooks disabled for $label"
    fi
  fi
}

prune_legacy_claude_local_hooks() {
  local root="$1"
  local settings="$root/.claude/settings.local.json"

  [ -f "$settings" ] || return 0
  if [ -z "$PYTHON_BIN" ]; then
    note "MISSING python: cannot prune legacy Claude local hooks"
    MISSING=$((MISSING + 1))
    return
  fi

  local result
  result="$("$PYTHON_BIN" - "$settings" "$MODE_CHECK" <<'PY'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
check = sys.argv[2] == "true"

legacy_scripts = (
    "vg-verify-claim.py",
    "vg-edit-warn.py",
    "vg-entry-hook.py",
    "vg-step-tracker.py",
    "vg-agent-spawn-guard.py",
)
hook_runner_markers = (
    "vg-run-bash-hook.py",
    "vg-user-prompt-submit.sh",
    "vg-session-start.sh",
    "vg-pre-tool-use-bash.sh",
    "vg-pre-tool-use-write.sh",
    "vg-pre-tool-use-agent.sh",
    "vg-post-tool-use-todowrite.sh",
    "vg-stop.sh",
    ".claude/scripts/hooks/",
)
vg_hook_markers = (*legacy_scripts, *hook_runner_markers)

try:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
except Exception:
    print("unreadable")
    raise SystemExit(0)

hooks = data.get("hooks")
if not isinstance(hooks, dict):
    print("clean")
    raise SystemExit(0)

changed = False
new_hooks = {}
for event, entries in hooks.items():
    if not isinstance(entries, list):
        new_hooks[event] = entries
        continue
    kept_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            kept_entries.append(entry)
            continue
        hook_list = entry.get("hooks")
        if not isinstance(hook_list, list):
            kept_entries.append(entry)
            continue
        kept_hook_list = []
        for hook in hook_list:
            command = str(hook.get("command", "")) if isinstance(hook, dict) else ""
            is_legacy_vg = any(marker in command for marker in vg_hook_markers)
            if is_legacy_vg:
                changed = True
            else:
                kept_hook_list.append(hook)
        if kept_hook_list:
            updated = dict(entry)
            updated["hooks"] = kept_hook_list
            kept_entries.append(updated)
        elif hook_list:
            changed = True
    if kept_entries:
        new_hooks[event] = kept_entries
    elif entries:
        changed = True

if not changed:
    print("clean")
    raise SystemExit(0)

if not check:
    if new_hooks:
        data["hooks"] = new_hooks
    else:
        data.pop("hooks", None)
    settings_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print("changed")
PY
)"

  case "$result" in
    changed)
      note "UPDATED: claude-hooks:.claude/settings.local.json VG hooks pruned"
      CHANGED=$((CHANGED + 1))
      if [ "$MODE_CHECK" = "false" ]; then
        echo "  OK: VG hooks pruned from .claude/settings.local.json"
      fi
      ;;
    unreadable)
      note "WARN: cannot parse .claude/settings.local.json for legacy hook pruning"
      ;;
  esac
}

echo "VGFlow sync"
echo "  source: $SCRIPT_DIR"
echo "  target: $TARGET_ROOT"
echo ""

if [ "$DEPRECATED_NO_SOURCE" = "true" ]; then
  note "INFO: --no-source is deprecated and ignored; vgflow-repo is now canonical"
fi

if [ "$MODE_CHECK" = "false" ]; then
  echo "1. Regenerate Codex skills"
  "$BASH_BIN" "$SCRIPT_DIR/scripts/generate-codex-skills.sh" --force >/tmp/vgflow-codex-generate.log
  tail -5 /tmp/vgflow-codex-generate.log
  chmod +x "$SCRIPT_DIR/scripts/generate-codex-skills.sh" 2>/dev/null || true
  chmod +x "$SCRIPT_DIR/commands/vg/_shared/lib/"*.sh 2>/dev/null || true
  echo ""
else
  echo "1. Check mode: skip regeneration; run without --check to refresh codex-skills"
  echo ""
fi

echo "2. Deploy Claude workflow to target project"
sync_tree "$SCRIPT_DIR/commands/vg" "$TARGET_ROOT/.claude/commands/vg" "claude-command"
sync_tree "$SCRIPT_DIR/skills" "$TARGET_ROOT/.claude/skills" "claude-skill"
sync_tree "$SCRIPT_DIR/scripts" "$TARGET_ROOT/.claude/scripts" "claude-script"
sync_tree "$SCRIPT_DIR/schemas" "$TARGET_ROOT/.claude/schemas" "claude-schema"
sync_tree "$SCRIPT_DIR/templates/vg" "$TARGET_ROOT/.claude/templates/vg" "claude-template"
# RFC v9 PR-research-augment: catalog/ holds the local edge-case pattern store
# consumed by scripts/runtime/pattern_catalog.py. Skip silently when source
# absent (older vgflow versions don't ship it).
[ -d "$SCRIPT_DIR/catalog" ] && \
  sync_tree "$SCRIPT_DIR/catalog" "$TARGET_ROOT/.claude/catalog" "claude-catalog"
compare "$SCRIPT_DIR/VGFLOW-VERSION" "$TARGET_ROOT/.claude/VGFLOW-VERSION" "claude-version"
if [ "$MODE_CHECK" = "false" ]; then
  chmod +x "$TARGET_ROOT/.claude/commands/vg/_shared/lib/"*.sh 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/commands/vg/_shared/lib/test-runners/"*.sh 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/"*.py 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/"*.sh 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/validators/"*.py 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/vg-orchestrator/"*.py 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/lib/"*.py 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/templates/vg/commit-msg" 2>/dev/null || true
  find "$TARGET_ROOT/.claude/scripts" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TARGET_ROOT/.claude/scripts" -type f -name '*.pyc' -delete 2>/dev/null || true
fi
echo ""

echo "2b. Remove legacy Claude local hooks"
prune_legacy_claude_local_hooks "$TARGET_ROOT"
if [ "$MODE_CHECK" = "false" ]; then
  find "$TARGET_ROOT/.claude/scripts" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TARGET_ROOT/.claude/scripts" -type f -name '*.pyc' -delete 2>/dev/null || true
fi
echo ""

# R1a pilot: sync custom subagents + install R1a enforcement hooks into settings.json
echo "2b-r1a. Sync R1a subagents + install R1a hooks"
if [ -d "$SCRIPT_DIR/agents" ]; then
  sync_tree "$SCRIPT_DIR/agents" "$TARGET_ROOT/.claude/agents" "claude-agent"
fi
# v3.6.1 — chmod +x for .claude/scripts/hooks/*.sh ALWAYS runs (was previously
# nested under agents/ existence check, which left hooks non-executable on
# fresh installs). Stop hook on Mac/Linux fails with `Permission denied` if
# this is skipped because Claude Code falls back to /bin/sh + the script
# isn't marked +x.
if [ "$MODE_CHECK" = "false" ]; then
  chmod +x "$TARGET_ROOT/.claude/scripts/hooks/"*.sh 2>/dev/null || true
  chmod +x "$TARGET_ROOT/.claude/scripts/hooks/"*.py 2>/dev/null || true
fi
# Install R1a hooks into .claude/settings.json (idempotent merge).
# Disable with VG_INSTALL_HOOKS=0 if user manages settings.json manually.
if [ "${VG_INSTALL_HOOKS:-1}" = "1" ] && [ "$MODE_CHECK" = "false" ] \
    && [ -f "$SCRIPT_DIR/scripts/hooks/install-hooks.sh" ]; then
  if VG_PLUGIN_ROOT="$SCRIPT_DIR" bash "$SCRIPT_DIR/scripts/hooks/install-hooks.sh" \
        --target "$TARGET_ROOT/.claude/settings.json" \
        >/tmp/vgflow-r1a-hooks-install.log 2>&1; then
    echo "  OK: R1a hooks merged into .claude/settings.json"
  else
    note "FAILED: R1a hook install; see /tmp/vgflow-r1a-hooks-install.log"
  fi
fi
echo ""

echo "2c. Ensure Playwright MCP workers"
MCP_VALIDATOR="$SCRIPT_DIR/scripts/validators/verify-playwright-mcp-config.py"
if [ -z "$PYTHON_BIN" ]; then
  note "MISSING python: cannot verify Playwright MCP config"
  MISSING=$((MISSING + 1))
elif [ -f "$MCP_VALIDATOR" ]; then
  if [ "$MODE_CHECK" = "true" ]; then
    if ! "$PYTHON_BIN" "$MCP_VALIDATOR" --quiet >/dev/null 2>&1; then
      note "UPDATED: playwright-mcp-config:~/.claude + ~/.codex"
      CHANGED=$((CHANGED + 1))
    fi
  else
    if "$PYTHON_BIN" "$MCP_VALIDATOR" --repair --quiet \
        --lock-source "$SCRIPT_DIR/playwright-locks/playwright-lock.sh"; then
      echo "  OK: playwright1-5 configured for Claude/Codex"
    else
      note "FAILED: Playwright MCP config; run $PYTHON_BIN $MCP_VALIDATOR --repair"
      MISSING=$((MISSING + 1))
      MCP_FAILED=true
    fi
  fi
else
  note "MISSING source validator: scripts/validators/verify-playwright-mcp-config.py"
  MISSING=$((MISSING + 1))
  MCP_FAILED=true
fi
echo ""

echo "2d. Ensure Graphify"
GRAPHIFY_HELPER="$SCRIPT_DIR/scripts/ensure-graphify.py"
if [ "${VGFLOW_SKIP_GRAPHIFY_INSTALL:-false}" = "true" ]; then
  echo "  skipped by VGFLOW_SKIP_GRAPHIFY_INSTALL=true"
elif [ -z "$PYTHON_BIN" ]; then
  note "MISSING python: cannot verify/install Graphify"
  MISSING=$((MISSING + 1))
elif [ -f "$GRAPHIFY_HELPER" ]; then
  if [ "$MODE_CHECK" = "true" ]; then
    if ! "$PYTHON_BIN" "$GRAPHIFY_HELPER" --target "$TARGET_ROOT" --quiet >/dev/null 2>&1; then
      note "UPDATED: graphify-install:${TARGET_ROOT}"
      CHANGED=$((CHANGED + 1))
    fi
  else
    if "$PYTHON_BIN" "$GRAPHIFY_HELPER" --target "$TARGET_ROOT" --repair --quiet; then
      echo "  OK: graphify installed/configured or intentionally disabled"
    else
      note "FAILED: Graphify setup; run $PYTHON_BIN $GRAPHIFY_HELPER --target $TARGET_ROOT --repair"
    fi
  fi
else
  note "MISSING source helper: scripts/ensure-graphify.py"
  MISSING=$((MISSING + 1))
fi
echo ""

echo "3. Deploy Codex workflow to target project"
sync_codex_skills_exact "$TARGET_ROOT/.codex" "codex-skill"
sync_codex_agents "$TARGET_ROOT/.codex"
sync_tree "$SCRIPT_DIR/templates/codex" "$TARGET_ROOT/.codex" "codex-template"
disable_legacy_codex_hooks "$TARGET_ROOT" "project-codex"
echo ""

if [ "$SKIP_GLOBAL" = "false" ] && [ -d "$HOME/.codex" ]; then
  echo "4. Deploy global Codex skills/agents"
  sync_codex_skills_exact "$HOME/.codex" "global-codex-skill"
  sync_codex_agents "$HOME/.codex"
  if [ "$MODE_CHECK" = "false" ]; then
    register_global_codex_agents
  fi
  echo ""
else
  echo "4. Global Codex deploy skipped (default; pass --global-codex to opt in)"
  echo ""
fi

# v3.6.1 — dedupe Codex skills if both global + project populated.
# Codex picker reads both dirs and shows duplicate entries; this removes
# the duplicate copy per .vg/.install-target marker (or default to pruning
# project copy when marker absent / global install).
echo "4b. Dedupe Codex skills (global vs project)"
prune_duplicate_codex_skills "$TARGET_ROOT"
echo ""

echo "5. Functional Codex mirror check"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 or python is required for functional mirror check" >&2
  exit 127
fi
VERIFY_JSON="$(mktemp)"
if "$PYTHON_BIN" "$SCRIPT_DIR/scripts/verify-codex-mirror-equivalence.py" --json >"$VERIFY_JSON"; then
  CHECKED="$("$PYTHON_BIN" - "$VERIFY_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    print(json.load(fh)["checked"])
PY
)"
  echo "  OK: ${CHECKED} source/mirror pairs equivalent"
else
  cat "$VERIFY_JSON"
  exit 1
fi
rm -f "$VERIFY_JSON"
echo ""

echo "Summary"
if [ "${#SUMMARY[@]}" -eq 0 ]; then
  echo "  All in sync."
else
  printf '  %s\n' "${SUMMARY[@]}"
  echo ""
  echo "  Changed: $CHANGED"
  echo "  Missing sources: $MISSING"
fi

if [ "$MODE_CHECK" = "true" ]; then
  echo ""
  echo "Dry run only. Re-run without --check to apply."
  [ "$CHANGED" -gt 0 ] && exit 1 || exit 0
fi

if [ "$MCP_FAILED" = "true" ]; then
  exit 1
fi
