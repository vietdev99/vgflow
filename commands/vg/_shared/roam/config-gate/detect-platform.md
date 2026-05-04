# Config gate sub-step 2 — platform + tool availability check

<HARD-GATE>
`0a_detect_platform_tools` MUST run before mode selection. The mode list
in `confirm-env-model-mode.md` is FILTERED by the offered set this ref
writes to `.tmp/modes-avail.txt`. Skipping it = offering modes that
persist-config.md will reject (see round-2 F4 spawn-mobile fix).
</HARD-GATE>

**Marker:** `0a_detect_platform_tools`
**Source:** Pre-prompt 1.5 (73 lines, v2.42.11) of original `0a_env_model_mode_gate`.

Roam shouldn't blindly assume web + codex CLI. Detect what platform the phase
targets (web / mobile-native / desktop / api-only) from CONTEXT.md + surfaces.
Check which executor tools are present. Filter the mode options in
`confirm-env-model-mode.md` by availability — don't offer modes that will fail.

## Detection

```bash
vg-orchestrator step-active 0a_detect_platform_tools

# Platform detection — heuristic from phase artifacts
ROAM_PLATFORM="web"
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  CONTEXT_LOWER=$(tr '[:upper:]' '[:lower:]' < "${PHASE_DIR}/CONTEXT.md" 2>/dev/null)
  echo "$CONTEXT_LOWER" | grep -qE 'react native|flutter|android sdk|ios simulator|maestro' && ROAM_PLATFORM="mobile-native"
  echo "$CONTEXT_LOWER" | grep -qE 'electron|tauri|desktop app' && ROAM_PLATFORM="desktop"
  if echo "$CONTEXT_LOWER" | grep -qE 'api[ -]only|backend[ -]only|no ui|server[ -]only|webhook'; then
    if ! echo "$CONTEXT_LOWER" | grep -qE 'admin (ui|panel|dashboard)|merchant (ui|app)|vendor (ui|app)'; then
      ROAM_PLATFORM="api-only"
    fi
  fi
fi
export ROAM_PLATFORM

# Tool availability
TOOL_PLAYWRIGHT_MCP="missing"
grep -qE '"mcp__playwright[1-5]?__' .claude/settings.json .claude/settings.local.json 2>/dev/null && TOOL_PLAYWRIGHT_MCP="present"
[ -f ~/.claude/settings.json ] && grep -q 'playwright' ~/.claude/settings.json 2>/dev/null && TOOL_PLAYWRIGHT_MCP="present"
TOOL_MAESTRO=$(command -v maestro >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_ADB=$(command -v adb >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_CODEX=$(command -v codex >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_GEMINI=$(command -v gemini >/dev/null 2>&1 && echo "present" || echo "missing")
export TOOL_PLAYWRIGHT_MCP TOOL_MAESTRO TOOL_ADB TOOL_CODEX TOOL_GEMINI

# Mode availability matrix per platform + tools
#
# Round-2 F4 fix: only modes that persist-config.md accepts AND that
# spawn-executors.md actually implements may be offered here. The accepted
# set is {self, spawn, manual}. `spawn-mobile` was offered for
# mobile-native phases but had no executor implementation and was rejected
# by persist-config.md validate — silent drift. Until /vg:setup-mobile
# wires a real Maestro/adb executor branch, mobile-native falls back to
# `manual` (user pastes prompt to a CLI that has Maestro available).
declare -a MODES_AVAIL
case "$ROAM_PLATFORM" in
  web)
    [ "$TOOL_PLAYWRIGHT_MCP" = "present" ] && MODES_AVAIL+=("self")
    { [ "$TOOL_CODEX" = "present" ] || [ "$TOOL_GEMINI" = "present" ]; } && MODES_AVAIL+=("spawn")
    MODES_AVAIL+=("manual")  # always available — user pastes elsewhere
    ;;
  mobile-native)
    # `spawn-mobile` deliberately NOT offered — no executor branch exists
    # in spawn-executors.md and persist-config.md would reject it. Surface
    # the install hint so the user knows the tooling status, but route them
    # through `manual` for now.
    if [ "$TOOL_MAESTRO" != "present" ] || [ "$TOOL_ADB" != "present" ]; then
      echo "  ℹ Mobile tooling missing (maestro=${TOOL_MAESTRO} adb=${TOOL_ADB})." >&2
      echo "    Run /vg:setup-mobile to install. roam will continue in manual mode." >&2
    fi
    MODES_AVAIL+=("manual")
    ;;
  desktop|api-only)
    [ "$TOOL_PLAYWRIGHT_MCP" = "present" ] && MODES_AVAIL+=("self")
    MODES_AVAIL+=("manual")
    ;;
esac

echo "▸ Platform: ${ROAM_PLATFORM}"
echo "  Tools: playwright_mcp=${TOOL_PLAYWRIGHT_MCP} codex=${TOOL_CODEX} gemini=${TOOL_GEMINI} maestro=${TOOL_MAESTRO} adb=${TOOL_ADB}"
echo "  Available modes: ${MODES_AVAIL[*]:-NONE}"

if [ ${#MODES_AVAIL[@]} -eq 0 ]; then
  echo ""
  echo "⛔ No executor mode available for platform=${ROAM_PLATFORM} with current tools."
  case "$ROAM_PLATFORM" in
    mobile-native)
      echo "   Run /vg:setup-mobile to install adb + Maestro + Android SDK + AVD."
      ;;
    *)
      echo "   Install at least one of: codex CLI, gemini CLI, or enable Playwright MCP servers."
      ;;
  esac
  exit 1
fi

# Persist for downstream use (mode question filtering, brief composer)
mkdir -p "${ROAM_DIR}/.tmp"
echo "$ROAM_PLATFORM" > "${ROAM_DIR}/.tmp/platform.txt"
printf '%s\n' "${MODES_AVAIL[@]}" > "${ROAM_DIR}/.tmp/modes-avail.txt"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_detect_platform_tools" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_detect_platform_tools.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 0a_detect_platform_tools 2>/dev/null || true
```

## Downstream usage

When building the mode question in `confirm-env-model-mode.md`, AI MUST read
`.tmp/modes-avail.txt` and ONLY include the modes listed there. Do not
present `self` if Playwright MCP is missing; do not present `spawn` if
codex/gemini missing. If `manual` is the only available mode, still present
the question (for user awareness) but mark it Recommended.

When platform = `mobile-native` and Maestro/adb missing, AI MUST surface the
`/vg:setup-mobile` install suggestion via AskUserQuestion BEFORE the
env+model+mode batch (give user choice: install now / abort / fall back to
manual).

Next: read `enrich-env.md`.
