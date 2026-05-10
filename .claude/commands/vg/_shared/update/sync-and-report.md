<!-- v2.73.0 T6-T10 extraction — verbatim step blocks from commands/vg/update.md -->
<!-- Group: sync-and-report | Steps: 8_sync_codex, 8b_repair_playwright_mcp, 8c_ensure_graphify, 9_report -->

<process>

<step name="8_sync_codex">
```bash
# Standard installs do NOT include vgflow/sync.sh. Deploy Codex mirrors
# directly from the rotated release ancestor so Claude and Codex update
# together without clobbering user-merged .claude files.
echo ""
echo "Syncing Codex mirror from updated release assets..."

CODEX_SOURCE="${NEW_ANCESTOR}"
CODEX_SKILLS_UPDATED=0
CODEX_AGENTS_UPDATED=0

# Project .codex deploy tri-state (v2.76.0+, symmetric with VG_UPDATE_GLOBAL_CODEX):
# Tri-state VG_UPDATE_PROJECT_CODEX:
#   1     -> always deploy to project .codex (legacy default — backwards compat)
#   0     -> never deploy to project .codex (opt-out — useful when user keeps
#            vgflow in ~/.codex global only; prevents duplicate-flow bug at
#            project-side instead of global-side)
#   unset -> auto: deploy ONLY if .codex/skills/vg-update already exists
#            (i.e., project previously had vgflow installed locally)
#
# Default 'auto' makes /vg:update non-destructive: if user opted out of project
# install (e.g. after running cleanup to keep global only), /vg:update will not
# silently re-create the duplicate. install.sh remains the canonical first-time
# project installer — it always populates .codex/skills/vg-update, which then
# auto-detects on subsequent updates.
PROJECT_CODEX_HAS_VGFLOW=0
if [ -d "${REPO_ROOT}/.codex/skills/vg-update" ]; then
  PROJECT_CODEX_HAS_VGFLOW=1
fi

VG_PROJECT_CODEX_DECISION="skip"
case "${VG_UPDATE_PROJECT_CODEX:-auto}" in
  1)
    VG_PROJECT_CODEX_DECISION="deploy-explicit"
    ;;
  0)
    VG_PROJECT_CODEX_DECISION="skip-explicit"
    ;;
  auto)
    if [ "$PROJECT_CODEX_HAS_VGFLOW" = "1" ]; then
      VG_PROJECT_CODEX_DECISION="deploy-auto"
    else
      VG_PROJECT_CODEX_DECISION="skip-auto"
    fi
    ;;
esac

case "$VG_PROJECT_CODEX_DECISION" in
  deploy-explicit|deploy-auto)
    if [ -d "${CODEX_SOURCE}/codex-skills" ]; then
      mkdir -p "${REPO_ROOT}/.codex/skills"
      while IFS= read -r skill_dir; do
        [ -f "$skill_dir/SKILL.md" ] || continue
        skill="$(basename "$skill_dir")"
        rm -rf "${REPO_ROOT}/.codex/skills/${skill}"
        mkdir -p "${REPO_ROOT}/.codex/skills/${skill}"
        cp -R "$skill_dir"/. "${REPO_ROOT}/.codex/skills/${skill}/"
        CODEX_SKILLS_UPDATED=$((CODEX_SKILLS_UPDATED + 1))
      done < <(find "${CODEX_SOURCE}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
    fi

    if [ -d "${CODEX_SOURCE}/templates/codex-agents" ]; then
      mkdir -p "${REPO_ROOT}/.codex/agents"
      cp "${CODEX_SOURCE}/templates/codex-agents/"*.toml "${REPO_ROOT}/.codex/agents/" 2>/dev/null || true
      CODEX_AGENTS_UPDATED=$(ls "${REPO_ROOT}/.codex/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
    fi

    if [ -d "${CODEX_SOURCE}/templates/codex" ]; then
      mkdir -p "${REPO_ROOT}/.codex"
      cp "${CODEX_SOURCE}/templates/codex/"* "${REPO_ROOT}/.codex/" 2>/dev/null || true
    fi

    if [ "$VG_PROJECT_CODEX_DECISION" = "deploy-auto" ]; then
      echo "Codex project deploy: refreshed .codex skills/agents (auto-detected prior project install)"
    else
      echo "Codex project deploy: VG_UPDATE_PROJECT_CODEX=1 — refreshed .codex skills/agents"
    fi
    ;;
  skip-explicit)
    echo "Codex project deploy: skipped (VG_UPDATE_PROJECT_CODEX=0 — explicit opt-out)"
    if [ "$PROJECT_CODEX_HAS_VGFLOW" = "1" ]; then
      echo "  ⚠ Stale vgflow detected at .codex/skills — Codex CLI may register each flow TWICE."
      echo "    Resolve: rerun without VG_UPDATE_PROJECT_CODEX=0 (auto-refresh) OR manually:"
      echo "      rm -rf .codex/skills/vg-* && rm -rf .codex/skills/{api-contract,flow-codegen,flow-runner,flow-scan,flow-spec,sandbox-test,test-depth,test-gen,test-review,test-scan,write-test-spec} && rm -f .codex/agents/vgflow-*.toml"
    fi
    ;;
  skip-auto)
    echo "Codex project deploy: skipped (no prior project vgflow detected; set VG_UPDATE_PROJECT_CODEX=1 to deploy)"
    ;;
esac

codex_config_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$path"
  else
    printf '%s\n' "$path"
  fi
}

register_codex_agent() {
  local config="$1"
  local name="$2"
  local desc="$3"
  local config_file
  config_file="$(codex_config_path "$HOME/.codex/agents/${name}.toml")"
  if ! grep -q "^\[agents\.${name}\]" "$config" 2>/dev/null; then
    cat >> "$config" <<EOF

[agents.${name}]
description = "${desc}"
config_file = "${config_file}"
EOF
  fi
}

# Global ~/.codex deploy auto-detect (v2.75.1):
# Codex CLI loads skills from BOTH ~/.codex/skills (global) AND .codex/skills
# (project). If a prior `install.sh --global-codex` populated ~/.codex/skills/,
# /vg:update must refresh it OR Codex CLI registers each flow TWICE — once
# from stale global, once from fresh project = duplicate-flow bug (#duplicate-flow).
#
# Tri-state VG_UPDATE_GLOBAL_CODEX:
#   1     -> always refresh global (legacy opt-in)
#   0     -> never refresh global (explicit opt-out, even if global vgflow exists)
#   unset -> auto: refresh ONLY if ~/.codex/skills/vg-update already exists
#            (i.e., user previously installed vgflow globally)
GLOBAL_CODEX_HAS_VGFLOW=0
if [ -d "$HOME/.codex/skills/vg-update" ]; then
  GLOBAL_CODEX_HAS_VGFLOW=1
fi

VG_GLOBAL_CODEX_DECISION="skip"
case "${VG_UPDATE_GLOBAL_CODEX:-auto}" in
  1)
    VG_GLOBAL_CODEX_DECISION="refresh-explicit"
    ;;
  0)
    VG_GLOBAL_CODEX_DECISION="skip-explicit"
    ;;
  auto)
    if [ "$GLOBAL_CODEX_HAS_VGFLOW" = "1" ]; then
      VG_GLOBAL_CODEX_DECISION="refresh-auto"
    else
      VG_GLOBAL_CODEX_DECISION="skip-auto"
    fi
    ;;
esac

case "$VG_GLOBAL_CODEX_DECISION" in
  refresh-explicit|refresh-auto)
    if [ ! -d "$HOME/.codex" ]; then
      echo "Codex global deploy: ~/.codex missing — skipped"
    else
      mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"
      if [ -d "${CODEX_SOURCE}/codex-skills" ]; then
        while IFS= read -r skill_dir; do
          [ -f "$skill_dir/SKILL.md" ] || continue
          skill="$(basename "$skill_dir")"
          rm -rf "$HOME/.codex/skills/${skill}"
          mkdir -p "$HOME/.codex/skills/${skill}"
          cp -R "$skill_dir"/. "$HOME/.codex/skills/${skill}/"
        done < <(find "${CODEX_SOURCE}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
      fi
      if [ -d "${CODEX_SOURCE}/templates/codex-agents" ]; then
        cp "${CODEX_SOURCE}/templates/codex-agents/"*.toml "$HOME/.codex/agents/" 2>/dev/null || true
      fi
      CODEX_CONFIG="$HOME/.codex/config.toml"
      touch "$CODEX_CONFIG"
      register_codex_agent "$CODEX_CONFIG" "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
      register_codex_agent "$CODEX_CONFIG" "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
      register_codex_agent "$CODEX_CONFIG" "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
      if [ "$VG_GLOBAL_CODEX_DECISION" = "refresh-auto" ]; then
        echo "Codex global deploy: refreshed ~/.codex skills/agents (auto-detected prior global vgflow install — prevents duplicate-flow bug)"
      else
        echo "Codex global deploy: VG_UPDATE_GLOBAL_CODEX=1 — refreshed ~/.codex skills/agents"
      fi
    fi
    ;;
  skip-explicit)
    echo "Codex global deploy: skipped (VG_UPDATE_GLOBAL_CODEX=0 — explicit opt-out)"
    if [ "$GLOBAL_CODEX_HAS_VGFLOW" = "1" ]; then
      echo "  ⚠ Stale vgflow detected at ~/.codex/skills — Codex CLI may register each flow TWICE."
      echo "    Resolve: rerun without VG_UPDATE_GLOBAL_CODEX=0 (auto-refresh) OR manually:"
      echo "      rm -rf ~/.codex/skills/vg-* && rm -rf ~/.codex/skills/{api-contract,flow-codegen,flow-runner,flow-scan,flow-spec,sandbox-test,test-depth,test-gen,test-review,test-scan,write-test-spec}"
    fi
    ;;
  skip-auto)
    echo "Codex global deploy: skipped (no prior global vgflow detected; set VG_UPDATE_GLOBAL_CODEX=1 to deploy)"
    ;;
esac

echo "Codex mirror: skills=${CODEX_SKILLS_UPDATED} agents=${CODEX_AGENTS_UPDATED}"

if [ -f "${REPO_ROOT}/.claude/scripts/verify-codex-mirror-equivalence.py" ]; then
  VERIFY_OUT="${PATCHES_DIR}/codex-mirror-verify.json"
  if REPO_ROOT="${REPO_ROOT}" python3 "${REPO_ROOT}/.claude/scripts/verify-codex-mirror-equivalence.py" --json > "$VERIFY_OUT"; then
    echo "Codex mirror verify: PASS"
  else
    echo "⚠ Codex mirror verify: DRIFT — see ${VERIFY_OUT}"
    echo "   If conflicts were parked, resolve them with /vg:reapply-patches then run /vg:sync --verify."
    if [ "${CONFLICTS}" -eq 0 ]; then
      exit 1
    fi
  fi
fi
```
</step>

<step name="8b_repair_playwright_mcp">
```bash
echo ""
echo "Verifying Playwright MCP workers..."
MCP_VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-playwright-mcp-config.py"
LOCK_SOURCE="${NEW_ANCESTOR}/playwright-locks/playwright-lock.sh"
if [ -f "$MCP_VALIDATOR" ]; then
  if python3 "$MCP_VALIDATOR" --repair --lock-source "$LOCK_SOURCE"; then
    echo "Playwright MCP verify: PASS (Claude + Codex playwright1-5)"
  else
    echo "⛔ Playwright MCP verify failed."
    echo "   Fix settings, then run:"
    echo "   python3 \"$MCP_VALIDATOR\" --repair --lock-source \"$LOCK_SOURCE\""
    exit 1
  fi
else
  echo "⛔ Playwright MCP validator missing after update: $MCP_VALIDATOR"
  exit 1
fi
```
</step>

<step name="8c_ensure_graphify">
```bash
echo ""
echo "Verifying Graphify tooling..."
GRAPHIFY_HELPER="${REPO_ROOT}/.claude/scripts/ensure-graphify.py"
if [ "${VGFLOW_SKIP_GRAPHIFY_INSTALL:-false}" = "true" ]; then
  echo "Graphify verify: SKIP (VGFLOW_SKIP_GRAPHIFY_INSTALL=true)"
elif [ -f "$GRAPHIFY_HELPER" ]; then
  if python3 "$GRAPHIFY_HELPER" --target "$REPO_ROOT" --repair; then
    echo "Graphify verify: PASS (installed/configured or intentionally disabled)"
  else
    echo "⚠ Graphify verify failed."
    echo "   /vg:build can still use grep fallback unless graphify.fallback_to_grep=false."
    echo "   Manual repair: python3 \"$GRAPHIFY_HELPER\" --target \"$REPO_ROOT\" --repair"
  fi
else
  echo "⚠ Graphify helper missing after update: $GRAPHIFY_HELPER"
fi
```
</step>

<step name="9_report">
```bash
echo ""
echo "========================================"
echo "  VG update complete"
echo "  v${INSTALLED} -> v${LATEST}"
echo "----------------------------------------"
echo "  Files updated:    ${UPDATED}"
echo "  New files:        ${NEW_FILES}"
echo "  Conflicts parked: ${CONFLICTS}"
echo "  Skipped (meta):   ${SKIPPED}"
echo "========================================"

GATE_CONFLICTS_MD="${REPO_ROOT}/${PLANNING_DIR:-.claude}/vgflow-patches/gate-conflicts.md"
NEEDS_REAPPLY=false
REAPPLY_ARGS=""
if [ "$CONFLICTS" -gt 0 ]; then
  NEEDS_REAPPLY=true
  echo ""
  echo "Conflicts parked: ${CONFLICTS} under .claude/vgflow-patches/"
fi
if [ -f "$GATE_CONFLICTS_MD" ]; then
  NEEDS_REAPPLY=true
  REAPPLY_ARGS="--verify-gates"
  echo ""
  echo "Gate conflicts parked: ${GATE_CONFLICTS_MD}"
fi

if [ "$NEEDS_REAPPLY" = "true" ]; then
  echo ""
  echo "▶ NEXT_ACTION=/vg:reapply-patches${REAPPLY_ARGS:+ ${REAPPLY_ARGS}}"
  echo ""
  echo "===== AI ASSISTANT DIRECTIVE (runtime-agnostic) ====="
  echo "Conflicts above are interactive — they need a human decision per entry."
  echo "Do NOT wait for the user to type the next command. In the very next turn,"
  echo "invoke /vg:reapply-patches${REAPPLY_ARGS:+ ${REAPPLY_ARGS}} directly so the"
  echo "user can answer the per-conflict prompts in one continuous session."
  echo "Applies to Claude Code (skill invocation) and Codex (skill invocation)."
  echo "====================================================="
fi

echo ""
echo "NOTE: Restart Claude Code / Codex session to load updated commands/skills."
```
</step>

</process>
