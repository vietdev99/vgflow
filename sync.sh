#!/usr/bin/env bash
# VGFlow sync - deploy this repository's canonical workflow files.
#
# This repository is the source of truth. Sync is intentionally one-way:
#   vgflow-repo/{commands,skills,scripts,codex-skills,templates}
#     -> $DEV_ROOT/.claude and $DEV_ROOT/.codex
#     -> ~/.codex (unless --no-global)
#
# Usage:
#   ./sync.sh              # apply sync to current repo, plus global Codex
#   DEV_ROOT=/project ./sync.sh
#   ./sync.sh --check      # dry-run, exits 1 if drift exists
#   ./sync.sh --verify     # run functional Codex mirror equivalence check
#   ./sync.sh --no-global  # skip ~/.codex deploy

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
SKIP_GLOBAL=false
VERIFY_ONLY=false
DEPRECATED_NO_SOURCE=false

for arg in "$@"; do
  case "$arg" in
    --check) MODE_CHECK=true ;;
    --verify) VERIFY_ONLY=true ;;
    --no-global) SKIP_GLOBAL=true ;;
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

echo "2b. Ensure Claude enforcement hooks"
if [ -z "$PYTHON_BIN" ]; then
  note "MISSING python: cannot verify/install Claude hooks"
  MISSING=$((MISSING + 1))
elif [ -f "$TARGET_ROOT/.claude/scripts/vg-hooks-install.py" ]; then
  if [ "$MODE_CHECK" = "true" ]; then
    if ! ( cd "$TARGET_ROOT" && "$PYTHON_BIN" .claude/scripts/vg-hooks-install.py --check >/dev/null 2>&1 ); then
      note "UPDATED: claude-hooks:.claude/settings.local.json"
      CHANGED=$((CHANGED + 1))
    fi
  else
    if ( cd "$TARGET_ROOT" && "$PYTHON_BIN" .claude/scripts/vg-hooks-install.py >/tmp/vgflow-hooks-install.log 2>&1 ); then
      echo "  OK: hooks installed/repaired in .claude/settings.local.json"
      if [ -f "$TARGET_ROOT/.claude/scripts/vg-hooks-selftest.py" ]; then
        if ( cd "$TARGET_ROOT" && "$PYTHON_BIN" .claude/scripts/vg-hooks-selftest.py >/tmp/vgflow-hooks-selftest.log 2>&1 ); then
          echo "  OK: hook self-test passed"
        else
          echo "  WARN: hook self-test failed; run: cd \"$TARGET_ROOT\" && $PYTHON_BIN .claude/scripts/vg-hooks-selftest.py"
        fi
      fi
    else
      note "FAILED: claude-hooks install; run cd $TARGET_ROOT && $PYTHON_BIN .claude/scripts/vg-hooks-install.py"
    fi
  fi
else
  note "MISSING target hook installer: .claude/scripts/vg-hooks-install.py"
  MISSING=$((MISSING + 1))
fi
if [ "$MODE_CHECK" = "false" ]; then
  find "$TARGET_ROOT/.claude/scripts" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TARGET_ROOT/.claude/scripts" -type f -name '*.pyc' -delete 2>/dev/null || true
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
  echo "4. Global Codex deploy skipped"
  echo ""
fi

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
