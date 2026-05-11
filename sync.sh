#!/usr/bin/env bash
# VGFlow sync - global-only refresh and project cleanup.
#
# Source of truth:
#   commands/vg, skills, scripts, codex-skills, templates live in this repo or
#   in ~/.vgflow. Sync never deploys VG workflow files into a project-local
#   .claude or .codex tree.
#
# Usage:
#   ./sync.sh                 # regenerate Codex skills, refresh global hooks, prune current project
#   DEV_ROOT=/project ./sync.sh
#   ./sync.sh --check         # no writes; exits 1 when stale project VG files remain
#   ./sync.sh --verify        # run functional Codex mirror equivalence check
#   ./sync.sh --no-global     # deprecated no-op; global deploy is mandatory
#   ./sync.sh --global-codex  # deprecated no-op; global deploy is mandatory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_ROOT="${DEV_ROOT:-$(pwd)}"
BASH_BIN="${BASH:-bash}"
PYTHON_BIN="$(command -v python3 || command -v python || true)"

MODE_CHECK=false
VERIFY_ONLY=false
DEPRECATED_FLAGS=()

for arg in "$@"; do
  case "$arg" in
    --check) MODE_CHECK=true ;;
    --verify) VERIFY_ONLY=true ;;
    --no-global|--global-codex|--no-source)
      DEPRECATED_FLAGS+=("$arg")
      ;;
    -h|--help)
      sed -n '1,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 or python is required" >&2
  exit 127
fi

if [ "$VERIFY_ONLY" = "true" ]; then
  "$PYTHON_BIN" "$SCRIPT_DIR/scripts/verify-codex-mirror-equivalence.py"
  exit $?
fi

for flag in "${DEPRECATED_FLAGS[@]:-}"; do
  [ -n "$flag" ] || continue
  echo "VGFlow sync: ${flag} is deprecated; global deploy is mandatory in global-only mode."
done

is_source_repo_target() {
  local source_real target_real
  source_real="$(cd "$SCRIPT_DIR" && pwd -P)"
  target_real="$(cd "$TARGET_ROOT" 2>/dev/null && pwd -P || true)"
  [ -n "$target_real" ] || return 1
  [ "$source_real" = "$target_real" ] || return 1
  [ -d "$SCRIPT_DIR/commands/vg" ] && [ -d "$SCRIPT_DIR/codex-skills" ]
}

owned_skill_name() {
  case "$1" in
    vg-*|flow-*|test-*|api-contract|sandbox-test|write-test-spec) return 0 ;;
    *) return 1 ;;
  esac
}

collect_project_local_vg_surfaces() {
  local root="$1"
  local rel
  for rel in \
    ".claude/commands/vg" \
    ".claude/scripts" \
    ".claude/schemas" \
    ".claude/templates/vg" \
    ".claude/catalog" \
    ".claude/vgflow-ancestor" \
    ".claude/vgflow-patches" \
    ".claude/VGFLOW-VERSION" \
    ".codex/config.template.toml"; do
    [ -e "$root/$rel" ] && printf '%s\n' "$rel"
  done

  if [ -d "$root/.claude/skills" ]; then
    while IFS= read -r dir; do
      owned_skill_name "$(basename "$dir")" && printf '%s\n' "${dir#$root/}"
    done < <(find "$root/.claude/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
  fi

  if [ -d "$root/.claude/agents" ]; then
    while IFS= read -r file; do
      printf '%s\n' "${file#$root/}"
    done < <(find "$root/.claude/agents" -maxdepth 1 -type f \( -name 'vg-*.md' -o -name 'vgflow-*.md' \) 2>/dev/null | sort)
  fi

  if [ -d "$root/.codex/skills" ]; then
    while IFS= read -r dir; do
      owned_skill_name "$(basename "$dir")" && printf '%s\n' "${dir#$root/}"
    done < <(find "$root/.codex/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
  fi

  if [ -d "$root/.codex/agents" ]; then
    while IFS= read -r file; do
      printf '%s\n' "${file#$root/}"
    done < <(find "$root/.codex/agents" -maxdepth 1 -type f -name 'vgflow-*.toml' 2>/dev/null | sort)
  fi
}

check_global_surface() {
  local missing=0
  [ -d "$HOME/.vgflow" ] || { echo "MISSING global source: ~/.vgflow"; missing=1; }
  [ -d "$HOME/.codex/skills" ] || { echo "MISSING global Codex skills: ~/.codex/skills"; missing=1; }
  [ -f "$HOME/.codex/hooks.json" ] || { echo "MISSING global Codex hooks: ~/.codex/hooks.json"; missing=1; }
  [ -f "$HOME/.claude/settings.json" ] || { echo "MISSING global Claude hooks: ~/.claude/settings.json"; missing=1; }
  return "$missing"
}

if [ "$MODE_CHECK" = "true" ]; then
  echo "VGFlow sync check: global-only mode"
  echo "  source: $SCRIPT_DIR"
  echo "  target project: $TARGET_ROOT"
  echo ""

  failed=0
  if ! check_global_surface; then
    failed=1
  fi

  if ! is_source_repo_target; then
    stale="$(collect_project_local_vg_surfaces "$TARGET_ROOT" || true)"
    if [ -n "$stale" ]; then
      echo "STALE project-local VG surfaces:"
      printf '%s\n' "$stale" | sed 's/^/  - /'
      failed=1
    else
      echo "Project cleanup: clean"
    fi
  else
    echo "Project cleanup: skipped for VGFlow source repo target"
  fi

  if [ "$failed" -ne 0 ]; then
    echo ""
    echo "Fix: run 'vg sync' or 'DEV_ROOT=/path/to/project bash sync.sh'."
    exit 1
  fi

  echo "Global sync check: clean"
  exit 0
fi

echo "VGFlow sync: global-only mode"
echo "  source: $SCRIPT_DIR"
echo "  target project: $TARGET_ROOT"
echo ""

GEN_LOG="$(mktemp "${TMPDIR:-/tmp}/vgflow-codex-generate.XXXXXX.log")"
"$BASH_BIN" "$SCRIPT_DIR/scripts/generate-codex-skills.sh" --force >"$GEN_LOG"
tail -5 "$GEN_LOG" || true

RUN_ROOT="$TARGET_ROOT"
if is_source_repo_target; then
  RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/vgflow-sync.XXXXXX")"
  echo "VGFlow source repo detected as cwd; project cleanup skipped unless DEV_ROOT is set."
fi

(
  cd "$RUN_ROOT"
  VG_HOME="$SCRIPT_DIR" "$BASH_BIN" "$SCRIPT_DIR/bin/vg-cli-dispatcher.sh" install --global
)

if ! is_source_repo_target; then
  stale_after="$(collect_project_local_vg_surfaces "$TARGET_ROOT" || true)"
  if [ -n "$stale_after" ]; then
    echo "ERROR: project-local VG surfaces remain after sync:" >&2
    printf '%s\n' "$stale_after" | sed 's/^/  - /' >&2
    exit 1
  fi
fi

echo ""
echo "VGFlow sync complete."
echo "  global source: ~/.vgflow"
echo "  Claude hooks:  ~/.claude/settings.json"
echo "  Codex skills:  ~/.codex/skills"
echo "  Codex hooks:   ~/.codex/hooks.json"
echo "  project:       ${TARGET_ROOT}"
echo ""
echo "Restart Claude Code / Codex session to load refreshed global workflow."
