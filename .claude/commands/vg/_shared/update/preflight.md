<!-- v2.73.0 T6-T10 extraction — verbatim step blocks from commands/vg/update.md -->
<!-- v2.88.0 marker-aware: read .vg/.install-target so global mode bypasses
     project-local merge in favor of ~/.vgflow/ refresh + stale cleanup -->
<!-- Group: preflight | Steps: 0_preflight, 0b_marker_branch, 1_check_only_mode -->

<process>

<step name="0_preflight">
```bash
set -u

REPO_ROOT="$(pwd)"
ARGS="${ARGUMENTS:-}"

# Parse --repo= (defaults to vietdev99/vgflow)
REPO="$(printf '%s' "$ARGS" | grep -oE -- '--repo=[^ ]+' | sed 's/^--repo=//' | head -n1)"
REPO="${REPO:-vietdev99/vgflow}"

# Preflight tooling
command -v git      >/dev/null 2>&1 || { echo "git CLI required"; exit 1; }
command -v curl     >/dev/null 2>&1 || { echo "curl required"; exit 1; }
command -v python3  >/dev/null 2>&1 || { echo "python3 required"; exit 1; }

# v3.6.6: global-only update. Marker is read for narration only; project and
# absent markers are coerced to global so update prunes project-local VG files.
INSTALL_TARGET="global"
MARKER_TARGET=""
if [ -f "${REPO_ROOT}/.vg/.install-target" ]; then
  MARKER_TARGET="$(tr -d '[:space:]' < "${REPO_ROOT}/.vg/.install-target")"
fi
if [ -n "$MARKER_TARGET" ] && [ "$MARKER_TARGET" != "global" ]; then
  echo "install-target marker: ${MARKER_TARGET} (deprecated — coercing to global-only)"
else
  echo "install-target marker: ${MARKER_TARGET:-(absent)} (global-only update)"
fi

HELPER="${REPO_ROOT}/.claude/scripts/vg_update.py"
# Project-mode helper is no longer required. Global-mode update doesn't touch
# project .claude/ helpers except to prune stale VG-owned files.
if [ "$INSTALL_TARGET" != "global" ] && [ ! -f "$HELPER" ]; then
  echo "vg_update.py missing at ${HELPER}"
  echo "Legacy install detected. Re-install vgflow first:"
  echo "  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
  exit 1
fi

echo "repo=${REPO}"
```
</step>

<step name="0b_marker_branch">
**v2.88.0 — marker-aware divergence.**

When `.vg/.install-target=global`, the project's harness lives in `~/.vgflow/`,
not `.claude/`. `/vg:update` MUST refresh `~/.vgflow/` (via npm or git pull),
re-install hooks at `~/.claude/settings.json` with `--mode global`, AND clean
up any stale legacy files left in `.claude/` that should have been removed
during the original v3 migration but remained from a partial run.

Project and absent markers are coerced to this same global path. The legacy
project-local 3-way merge path is retained only as dead compatibility text for
older skill mirrors; global-only update exits before it can run.

```bash
if [ "$INSTALL_TARGET" = "global" ]; then
  echo ""
  echo "Global update path (marker=global) — refreshing ~/.vgflow/..."

  DISPATCHER=""
  for candidate in \
    "${VG_HOME:-}/bin/vg-cli-dispatcher.sh" \
    "${HOME}/.vgflow/bin/vg-cli-dispatcher.sh"; do
    if [ -f "$candidate" ]; then
      DISPATCHER="$candidate"
      break
    fi
  done
  if [ -n "$DISPATCHER" ]; then
    echo "  Delegating to global dispatcher: ${DISPATCHER}"
    VG_HOME="$(dirname "$(dirname "$DISPATCHER")")" bash "$DISPATCHER" update
    exit $?
  fi

  HOME_VGFLOW="${HOME}/.vgflow"
  GLOBAL_OK=0

  # Strategy 1: git pull when ~/.vgflow/.git exists (dev clone)
  if [ -d "${HOME_VGFLOW}/.git" ]; then
    echo "  ~/.vgflow is a git clone — running git pull --ff-only origin main"
    if (cd "$HOME_VGFLOW" && git pull --ff-only origin main >/dev/null 2>&1); then
      GLOBAL_OK=1
      echo "  ✓ ~/.vgflow updated to $(cat "${HOME_VGFLOW}/VERSION" 2>/dev/null || echo unknown)"
    else
      echo "  ⚠ git pull failed — falling back to npm"
    fi
  fi

  # Strategy 2: npm global update
  if [ "$GLOBAL_OK" = "0" ] && command -v npm >/dev/null 2>&1; then
    echo "  Updating via npm install -g vgflow@latest..."
    if npm install -g vgflow@latest >/dev/null 2>&1; then
      NPM_ROOT="$(npm root -g 2>/dev/null || true)"
      NPM_VGFLOW="${NPM_ROOT%/}/vgflow"
      if [ -f "${NPM_VGFLOW}/bin/vg-cli-dispatcher.sh" ]; then
        echo "  ✓ npm install -g vgflow@latest done"
        echo "  Delegating to npm-installed dispatcher so ~/.vgflow is canonicalized..."
        VG_HOME="$NPM_VGFLOW" bash "${NPM_VGFLOW}/bin/vg-cli-dispatcher.sh" update
        exit $?
      fi
      echo "  ⚠ npm install succeeded but dispatcher not found at ${NPM_VGFLOW}"
    else
      echo "  ⚠ npm install failed"
    fi
  fi

  if [ "$GLOBAL_OK" = "0" ]; then
    echo "⛔ Could not update global ~/.vgflow/. Either:"
    echo "   - Make ~/.vgflow a git clone:  git clone https://github.com/${REPO} ~/.vgflow"
    echo "   - Or install npm + run:        npm install -g vgflow@latest"
    exit 1
  fi

  # Re-install hooks with --mode global so settings.json points at ~/.vgflow/
  INSTALL_HOOKS=""
  for candidate in \
    "${HOME_VGFLOW}/scripts/hooks/install-hooks.sh" \
    "${REPO_ROOT}/.claude/scripts/hooks/install-hooks.sh"; do
    if [ -f "$candidate" ]; then
      INSTALL_HOOKS="$candidate"
      break
    fi
  done
  if [ -n "$INSTALL_HOOKS" ]; then
    echo "  Re-installing hooks at ~/.claude/settings.json (--mode global)..."
    if bash "$INSTALL_HOOKS" --target "${HOME}/.claude/settings.json" --mode global >/dev/null 2>&1; then
      echo "  ✓ hooks refreshed"
    else
      echo "  ⚠ hook re-install failed — run manually:"
      echo "     bash ${INSTALL_HOOKS} --target ${HOME}/.claude/settings.json --mode global"
    fi
  fi

  # Refresh global Codex skills/agents from the updated global harness.
  # The global update branch exits before sync-and-report, so it must keep
  # ~/.codex current here instead of relying on the later Codex deploy step.
  CODEX_DEPLOYED=0
  if [ -d "${HOME_VGFLOW}/codex-skills" ]; then
    mkdir -p "${HOME}/.codex/skills" "${HOME}/.codex/agents"
    while IFS= read -r skill_dir; do
      [ -f "$skill_dir/SKILL.md" ] || continue
      skill="$(basename "$skill_dir")"
      rm -rf "${HOME}/.codex/skills/${skill}"
      mkdir -p "${HOME}/.codex/skills/${skill}"
      cp -R "$skill_dir"/. "${HOME}/.codex/skills/${skill}/"
      CODEX_DEPLOYED=$((CODEX_DEPLOYED + 1))
    done < <(find "${HOME_VGFLOW}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
    if [ -d "${HOME_VGFLOW}/templates/codex-agents" ]; then
      cp "${HOME_VGFLOW}/templates/codex-agents/"*.toml "${HOME}/.codex/agents/" 2>/dev/null || true
    fi
    CODEX_CONFIG="${HOME}/.codex/config.toml"
    touch "$CODEX_CONFIG"
    codex_config_path() {
      local path="$1"
      if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$path"
      else
        printf '%s\n' "$path"
      fi
    }
    register_codex_agent() {
      local name="$1"
      local desc="$2"
      local config_file
      config_file="$(codex_config_path "${HOME}/.codex/agents/${name}.toml")"
      if ! grep -q "^\[agents\.${name}\]" "$CODEX_CONFIG" 2>/dev/null; then
        cat >> "$CODEX_CONFIG" <<EOF

[agents.${name}]
description = "${desc}"
config_file = "${config_file}"
EOF
      fi
    }
    register_codex_agent "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
    register_codex_agent "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
    register_codex_agent "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
    echo "  ✓ global Codex refreshed (${CODEX_DEPLOYED} skill dirs)"
  fi
  CODEX_HOOK_INSTALLER="${HOME_VGFLOW}/scripts/codex-hooks-install.py"
  if [ -f "$CODEX_HOOK_INSTALLER" ]; then
    python3 "$CODEX_HOOK_INSTALLER" --codex-home "${HOME}/.codex" --vg-home "$HOME_VGFLOW"
    echo "  ✓ Codex hooks refreshed at ~/.codex/hooks.json"
  else
    echo "  ⚠ codex-hooks-install.py not found — Codex review may rely on manual markers"
  fi

  # Clean project-local Claude/Codex VG surfaces. This must remove all
  # VG-owned support skills too (api-contract, flow-*, test-*, etc.), not
  # only .claude/skills/vg-*.
  UNINSTALL_HELPER=""
  for candidate in \
    "${HOME_VGFLOW}/scripts/vg_uninstall.py" \
    "${REPO_ROOT}/.claude/scripts/vg_uninstall.py"; do
    if [ -f "$candidate" ]; then
      UNINSTALL_HELPER="$candidate"
      break
    fi
  done
  if [ -n "$UNINSTALL_HELPER" ]; then
    echo "  Cleaning stale project-local VG files via vg_uninstall.py..."
    python3 "$UNINSTALL_HELPER" --root "$REPO_ROOT" --apply
    echo "  ✓ stale project-local VG cleanup done"
  else
    echo "  ⚠ vg_uninstall.py not found — stale project-local VG files may remain"
  fi

  # Bump VGFLOW-VERSION marker for global mode tracking
  mkdir -p "${REPO_ROOT}/.vg"
  printf '%s\n' "global" > "${REPO_ROOT}/.vg/.install-target"
  if [ -f "${HOME_VGFLOW}/VERSION" ]; then
    cp "${HOME_VGFLOW}/VERSION" "${REPO_ROOT}/.vg/.global-vgflow-version" 2>/dev/null || true
  fi

  echo ""
  echo "✓ Global /vg:update complete. Restart Claude Code / Codex session to load updated harness."
  exit 0
fi

# Unreachable in global-only mode; retained for legacy mirrors only.
```
</step>

<step name="1_check_only_mode">
```bash
if printf '%s' "$ARGS" | grep -qE -- '(^|[[:space:]])--check([[:space:]]|$)'; then
  python3 "$HELPER" check --repo "$REPO"
  exit $?
fi
```
</step>

</process>
