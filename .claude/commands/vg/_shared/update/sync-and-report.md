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

# v3.6.6 global-only contract: never deploy Codex skills into the project.
# Project-local .codex is a stale duplicate surface; prune it with backup via
# the same uninstall helper used by `vg install`/dispatcher update.
UNINSTALL_HELPER="${REPO_ROOT}/.claude/scripts/vg_uninstall.py"
if [ -f "$UNINSTALL_HELPER" ]; then
  python3 "$UNINSTALL_HELPER" --root "$REPO_ROOT" --apply
  echo "Codex project deploy: disabled (global-only); project-local VG files pruned"
else
  echo "Codex project deploy: disabled (global-only); vg_uninstall.py missing, manual project cleanup may be needed"
fi

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

# Global ~/.codex deploy is mandatory in global-only mode.
mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"
if [ -d "${CODEX_SOURCE}/codex-skills" ]; then
  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill="$(basename "$skill_dir")"
    rm -rf "$HOME/.codex/skills/${skill}"
    mkdir -p "$HOME/.codex/skills/${skill}"
    cp -R "$skill_dir"/. "$HOME/.codex/skills/${skill}/"
    CODEX_SKILLS_UPDATED=$((CODEX_SKILLS_UPDATED + 1))
  done < <(find "${CODEX_SOURCE}/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
fi
if [ -d "${CODEX_SOURCE}/templates/codex-agents" ]; then
  cp "${CODEX_SOURCE}/templates/codex-agents/"*.toml "$HOME/.codex/agents/" 2>/dev/null || true
  CODEX_AGENTS_UPDATED=$(ls "$HOME/.codex/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
fi
CODEX_CONFIG="$HOME/.codex/config.toml"
touch "$CODEX_CONFIG"
register_codex_agent "$CODEX_CONFIG" "vgflow-orchestrator" "VGFlow phase orchestrator for Codex. Coordinates VG skills, gates, and artifact writes."
register_codex_agent "$CODEX_CONFIG" "vgflow-executor" "VGFlow bounded code executor for Codex child tasks."
register_codex_agent "$CODEX_CONFIG" "vgflow-classifier" "VGFlow cheap classifier/scanner for read-only summaries and triage."
CODEX_HOOK_INSTALLER="${CODEX_SOURCE}/scripts/codex-hooks-install.py"
if [ -f "$CODEX_HOOK_INSTALLER" ]; then
  python3 "$CODEX_HOOK_INSTALLER" --codex-home "$HOME/.codex" --vg-home "$CODEX_SOURCE"
  echo "Codex hooks: refreshed ~/.codex/hooks.json"
else
  echo "⚠ Codex hooks: installer missing; Codex review may rely on manual markers"
fi
echo "Codex global deploy: refreshed ~/.codex skills/agents (global-only)"

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
