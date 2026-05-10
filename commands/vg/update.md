---
name: vg:update
description: Pull latest VG release from GitHub, 3-way merge with local, park conflicts for /vg:reapply-patches
argument-hint: "[--check] [--accept-breaking] [--repo=vietdev99/vgflow]"
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "update.started"
    - event_type: "update.completed"
---

<rules>
1. **Atomic** — VERSION file + ancestor dir rotated only after all merges complete.
2. **Non-destructive on conflict** — conflicted files are parked under `.claude/vgflow-patches/`, never clobber user edits.
3. **All logic in Python** — this markdown wraps `.claude/scripts/vg_update.py`; no version math / SHA / merge logic in bash.
4. **Honor repo override** — `--repo=owner/name` flag flows through to `vg_update.py`.
5. **Honor args literally** — use `${ARGUMENTS}`, never `$*`/`$@` to avoid arg splitting.
</rules>

<objective>
Sync local VG install (`.claude/commands/vg/`, `.claude/skills/`, `.claude/scripts/`, `.claude/templates/`)
to latest GitHub release of `vietdev99/vgflow`. Logic lives in `.claude/scripts/vg_update.py`.
High-level flow:

1. Preflight: verify `git`, `curl`, `python3`, helper script present.
2. `--check` mode → just print version state + exit.
3. Query `GET /repos/{repo}/releases/latest` via helper → compare with `.claude/VGFLOW-VERSION`.
4. Show changelog preview for versions `> installed, <= latest`.
5. Ask user to confirm.
6. Breaking-change gate: major bump requires `--accept-breaking` + shows migration doc.
7. Download tarball + verify SHA256 + extract to `.vgflow-cache/v{ver}/`.
8. Walk extracted tree, 3-way merge each file against `.claude/vgflow-ancestor/v{installed}/`.
9. Clean merges → apply; conflicts → `.claude/vgflow-patches/{rel}.conflict` + manifest entry.
10. Rotate ancestor dir + bump `.claude/VGFLOW-VERSION`.
11. Sync Codex mirrors directly from the updated release assets.
12. Verify/repair Claude + Codex Playwright MCP workers (`playwright1`..`playwright5`).
13. Verify/install Graphify tooling when `graphify.enabled=true`.
14. Report counts + restart reminder.
</objective>

<process>

### Preflight section (extracted v2.73.0 T6)

Read `_shared/update/preflight.md` and follow it exactly.
Includes 2 steps: 0_preflight, 1_check_only_mode.

Step coverage: 0_preflight, 1_check_only_mode.


### Version + changelog (extracted v2.73.0 T7)

Read `_shared/update/version-and-changelog.md` and follow it exactly.
Includes 3 steps: 2_version_compare, 3_changelog_preview, 4_breaking_gate.

Step coverage: 2_version_compare, 3_changelog_preview, 4_breaking_gate.


### Fetch + merge (extracted v2.73.0 T8)

Read `_shared/update/fetch-and-merge.md` and follow it exactly.
Includes 3 steps: 5_fetch_tarball, 6_three_way_merge_per_file, 6b_verify_gate_integrity.

Step coverage: 5_fetch_tarball, 6_three_way_merge_per_file, 6b_verify_gate_integrity.


### Rotate + repair (extracted v2.73.0 T9)

Read `_shared/update/rotate-and-repair.md` and follow it exactly.
Includes 2 steps: 7_rotate_ancestor_and_version, 7b_repair_hooks.

Step coverage: 7_rotate_ancestor_and_version, 7b_repair_hooks.


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

# Project-local Codex deploy is unconditional (handled above into
# ${REPO_ROOT}/.codex). Global ~/.codex deploy is OFF by default to match
# install.sh + sync.sh convention; opt in via VG_UPDATE_GLOBAL_CODEX=1.
if [ "${VG_UPDATE_GLOBAL_CODEX:-0}" = "1" ] && [ -d "$HOME/.codex" ]; then
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
  echo "Codex global deploy: VG_UPDATE_GLOBAL_CODEX=1 — refreshed ~/.codex skills/agents"
else
  echo "Codex global deploy: skipped (default; set VG_UPDATE_GLOBAL_CODEX=1 to opt in)"
fi

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

<success_criteria>
- `/vg:update --check` prints `current=... latest=... state=...` and exits cleanly.
- Non-check run: shows changelog preview, asks confirmation, either applies or exits on cancel.
- Clean merges applied silently; conflicts parked to `.claude/vgflow-patches/{rel}.conflict` with manifest entry.
- Major-version bump blocked unless `--accept-breaking` is passed AND migration doc displayed.
- `.claude/VGFLOW-VERSION` bumped to `${LATEST}`; old `vgflow-ancestor/v{INSTALLED}` removed; new `vgflow-ancestor/v{LATEST}` populated.
- Claude Code hooks are installed/repaired after update (`UserPromptSubmit`, `Stop`, `PostToolUse` edit warning, `PostToolUse` Bash step tracker).
- Project-local Codex mirrors in `.codex/skills` and `.codex/agents` are refreshed directly from the updated release assets. Global `~/.codex` deploy is OFF by default (matches `install.sh` + `sync.sh` convention); opt in via `VG_UPDATE_GLOBAL_CODEX=1 /vg:update` when global Codex install is desired.
- Functional Codex mirror equivalence is verified after update; drift without merge conflicts fails the update.
- Playwright MCP workers are verified/repaired after update for both Claude and Codex (`playwright1`..`playwright5`) and stale hardcoded lock scripts are replaced.
- Graphify tooling is verified/repaired after update when `graphify.enabled=true`; missing package installs `graphifyy[mcp]`, `.mcp.json` is repaired, and `.graphifyignore` / `.gitignore` are maintained.
- Final report lists updated / new / conflict counts. When `CONFLICTS > 0` OR `gate-conflicts.md` exists, the report emits a runtime-agnostic AI directive (`▶ NEXT_ACTION=/vg:reapply-patches[ --verify-gates]`) instructing the assistant to chain into `/vg:reapply-patches` in the next turn without waiting for a fresh user prompt. Applies to Claude Code and Codex.
- Meta files (VERSION, CHANGELOG.md, README.md, LICENSE, install.sh, sync.sh, vg.config.template.md) never written to `.claude/`.
</success_criteria>
