#!/bin/bash
# VGFlow Installer — copy pipeline files to target project
# Usage: ./install.sh [--refresh] /path/to/your/project
#
# Installs:
#   - Claude Code commands (.claude/commands/vg/)
#   - Claude Code skills (.claude/skills/api-contract/)
#   - Codex CLI skills + agents (.codex/skills/, .codex/agents/)
#   - Gemini CLI (CrossAI role only — no vg-* skills installed)
#   - Playwright lock manager (~/.claude/playwright-locks/)
#   - vg-ext helper script (project root)
#   - vg.config.md template

set -e

REFRESH=false
TARGET=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --refresh)
      REFRESH=true
      ;;
    -h|--help)
      echo "Usage: ./install.sh [--refresh] /path/to/your/project"
      echo "  --refresh  force-refresh VG managed files after backing them up"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      if [ -n "$TARGET" ]; then
        echo "Unexpected extra argument: $1" >&2
        exit 2
      fi
      TARGET="$1"
      ;;
  esac
  shift
done
TARGET="${TARGET:-.}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$TARGET" = "." ] && [ "$REFRESH" != "true" ]; then
  echo "Usage: ./install.sh /path/to/your/project"
  echo "  or:  ./install.sh .   (install in current directory)"
  echo ""
  read -p "Install VGFlow in current directory? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
  fi
fi

echo "Installing VGFlow to: $TARGET"
echo ""

if [ "$REFRESH" = "true" ]; then
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_DIR="$TARGET/.vgflow-refresh-backup/$TS"
  mkdir -p "$BACKUP_DIR"
  for path in \
    .claude/commands/vg \
    .claude/skills \
    .claude/scripts \
    .claude/schemas \
    .claude/templates/vg \
    .codex/skills \
    .codex/agents; do
    if [ -e "$TARGET/$path" ]; then
      mkdir -p "$BACKUP_DIR/$(dirname "$path")"
      cp -R "$TARGET/$path" "$BACKUP_DIR/$path"
    fi
  done
  echo "Refresh backup: $BACKUP_DIR"
  echo ""
fi

# ============================================================
# 1. Claude Code commands + skills + scripts + templates
# ============================================================
echo "[1/6] Claude Code commands + skills + scripts + templates..."
mkdir -p "$TARGET/.claude/commands/vg/_shared"
mkdir -p "$TARGET/.claude/skills"
mkdir -p "$TARGET/.claude/skills/api-contract"
mkdir -p "$TARGET/.claude/skills/vg-design-scanner"
mkdir -p "$TARGET/.claude/skills/vg-design-gap-hunter"
mkdir -p "$TARGET/.claude/skills/vg-haiku-scanner"
mkdir -p "$TARGET/.claude/skills/vg-crossai"
mkdir -p "$TARGET/.claude/skills/vg-codegen-interactive"   # v2.10 Phase 15 — D-16 matrix renderer
mkdir -p "$TARGET/.claude/scripts"
mkdir -p "$TARGET/.claude/scripts/lib"                     # v2.10 Phase 15 — threshold-resolver
mkdir -p "$TARGET/.claude/schemas"                         # v2.10 Phase 15 — JSON Schema draft-07 contracts
mkdir -p "$TARGET/.claude/templates/vg"
mkdir -p "$TARGET/.claude/commands/vg/_shared/templates"   # v2.10 Phase 15 — UAT + filter test templates

cp "$SCRIPT_DIR/commands/vg/"*.md "$TARGET/.claude/commands/vg/"
cp "$SCRIPT_DIR/commands/vg/_shared/"*.md "$TARGET/.claude/commands/vg/_shared/"

# v1.11.0 R5 — copy bash helpers (_shared/lib/*.sh + test-runners)
mkdir -p "$TARGET/.claude/commands/vg/_shared/lib"
cp "$SCRIPT_DIR/commands/vg/_shared/lib/"*.sh "$TARGET/.claude/commands/vg/_shared/lib/" 2>/dev/null || true
chmod +x "$TARGET/.claude/commands/vg/_shared/lib/"*.sh 2>/dev/null || true
LIB_COUNT=$(ls "$TARGET/.claude/commands/vg/_shared/lib/"*.sh 2>/dev/null | wc -l | tr -d ' ')
echo "  → ${LIB_COUNT} bash helpers in _shared/lib/"

# Copy test-runners if present
if [ -d "$SCRIPT_DIR/commands/vg/_shared/lib/test-runners" ]; then
  mkdir -p "$TARGET/.claude/commands/vg/_shared/lib/test-runners"
  cp "$SCRIPT_DIR/commands/vg/_shared/lib/test-runners/"*.sh "$TARGET/.claude/commands/vg/_shared/lib/test-runners/" 2>/dev/null || true
  chmod +x "$TARGET/.claude/commands/vg/_shared/lib/test-runners/"*.sh 2>/dev/null || true
fi

# Skills: install every canonical helper skill, including support assets.
# sync.sh already deploys the full skills/ tree; install.sh must match it so a
# fresh install is not weaker than a maintainer sync.
CLAUDE_SKILL_DEPLOYED=0
if [ -d "$SCRIPT_DIR/skills" ]; then
  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill="$(basename "$skill_dir")"
    mkdir -p "$TARGET/.claude/skills/$skill"
    cp -R "$skill_dir"/. "$TARGET/.claude/skills/$skill/"
    CLAUDE_SKILL_DEPLOYED=$((CLAUDE_SKILL_DEPLOYED + 1))
  done < <(find "$SCRIPT_DIR/skills" -mindepth 1 -maxdepth 1 -type d | sort)
fi
echo "  -> ${CLAUDE_SKILL_DEPLOYED} Claude skills installed (full helper surface)"

# All .claude/scripts/*.py and *.js go together — includes universal helpers
# (filter-steps, design-normalize, pre-executor-check, verify-goal-test-binding,
# phase-recon, etc.) plus mobile additions (maestro-mcp, verify-mobile-*)
# shipped under the same umbrella. Any future script dropped into
# vgflow/scripts/ is installed automatically.
if [ -d "$SCRIPT_DIR/scripts" ]; then
  # Flat top-level scripts
  cp "$SCRIPT_DIR/scripts/"*.py "$TARGET/.claude/scripts/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/"*.js "$TARGET/.claude/scripts/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/"*.mjs "$TARGET/.claude/scripts/" 2>/dev/null || true   # v2.10 Phase 15 — extract-subtree-haiku.mjs, generate-ui-map.mjs
  cp "$SCRIPT_DIR/scripts/"*.sh "$TARGET/.claude/scripts/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/"*.yaml "$TARGET/.claude/scripts/" 2>/dev/null || true

  # v2.5.2.4: copy sub-directories (previously skipped — caused validators +
  # orchestrator + tests to be missing in every new install).
  # validators/ — 60 validator scripts + registry.yaml (core of v2.5.2.x gates)
  # vg-orchestrator/ — __main__.py, allow_flag_gate.py, prompt_capture.py,
  #                    lock.py, journal.py, db.py (run-start/abort, HMAC gate)
  # tests/        — regression suite (so CI can run pytest .claude/scripts/tests/)
  # lib/          — v2.10 Phase 15 — threshold-resolver.py + future helpers
  for subdir in validators vg-orchestrator tests lib; do
    if [ -d "$SCRIPT_DIR/scripts/$subdir" ]; then
      mkdir -p "$TARGET/.claude/scripts/$subdir"
      cp -r "$SCRIPT_DIR/scripts/$subdir/"* "$TARGET/.claude/scripts/$subdir/" 2>/dev/null || true
    fi
  done

  chmod +x "$TARGET/.claude/scripts/"*.py 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/"*.sh 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/validators/"*.py 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/vg-orchestrator/"*.py 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/lib/"*.py 2>/dev/null || true
  find "$TARGET/.claude/scripts" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TARGET/.claude/scripts" -type f -name '*.pyc' -delete 2>/dev/null || true

  SCRIPT_COUNT=$(ls "$TARGET/.claude/scripts/"*.py "$TARGET/.claude/scripts/"*.sh 2>/dev/null | wc -l | tr -d ' ')
  VALIDATOR_COUNT=$(ls "$TARGET/.claude/scripts/validators/"*.py 2>/dev/null | wc -l | tr -d ' ')
  ORCH_COUNT=$(ls "$TARGET/.claude/scripts/vg-orchestrator/"*.py 2>/dev/null | wc -l | tr -d ' ')
  echo "  → ${SCRIPT_COUNT} top-level scripts + ${VALIDATOR_COUNT} validators + ${ORCH_COUNT} orchestrator modules installed"
fi

# v2.10 Phase 15 — JSON Schema draft-07 contracts (slug-registry, structural-json,
# ui-map 5-field-per-node lock, narration-strings UAT keys). Validators read these.
if [ -d "$SCRIPT_DIR/schemas" ]; then
  cp "$SCRIPT_DIR/schemas/"*.json "$TARGET/.claude/schemas/" 2>/dev/null || true
  SCHEMA_COUNT=$(ls "$TARGET/.claude/schemas/"*.json 2>/dev/null | wc -l | tr -d ' ')
  echo "  → ${SCHEMA_COUNT} JSON Schema contracts in .claude/schemas/"
fi

# v2.10 Phase 15 — _shared/templates (UAT narrative + filter/pagination test
# templates consumed by /vg:test step 5d_codegen + /vg:accept step 4b)
if [ -d "$SCRIPT_DIR/commands/vg/_shared/templates" ]; then
  cp "$SCRIPT_DIR/commands/vg/_shared/templates/"* "$TARGET/.claude/commands/vg/_shared/templates/" 2>/dev/null || true
  TPL_COUNT=$(ls "$TARGET/.claude/commands/vg/_shared/templates/" 2>/dev/null | wc -l | tr -d ' ')
  echo "  → ${TPL_COUNT} shared templates (UAT narrative + filter+pagination rigor pack)"
fi

# Commit-msg hook template (deployed to .git/hooks/commit-msg by /vg:init)
if [ -f "$SCRIPT_DIR/templates/vg/commit-msg" ]; then
  cp "$SCRIPT_DIR/templates/vg/commit-msg" "$TARGET/.claude/templates/vg/commit-msg"
  chmod +x "$TARGET/.claude/templates/vg/commit-msg" 2>/dev/null || true
  echo "  → commit-msg hook template (auto-deployed on /vg:init)"
fi

# Executor rules snippet (manual append to target's CLAUDE.md)
if [ -f "$SCRIPT_DIR/templates/vg/claude-md-executor-rules.md" ]; then
  cp "$SCRIPT_DIR/templates/vg/claude-md-executor-rules.md" "$TARGET/.claude/templates/vg/claude-md-executor-rules.md"
  echo "  → VG Executor Rules snippet — append to CLAUDE.md manually:"
  echo "     cat .claude/templates/vg/claude-md-executor-rules.md >> CLAUDE.md"
fi

if [ -f "$SCRIPT_DIR/VGFLOW-VERSION" ]; then
  cp "$SCRIPT_DIR/VGFLOW-VERSION" "$TARGET/.claude/VGFLOW-VERSION"
  echo "  -> .claude/VGFLOW-VERSION"

  INSTALLED_VERSION="$(cat "$SCRIPT_DIR/VGFLOW-VERSION" | tr -d '[:space:]')"
  if [ -n "$INSTALLED_VERSION" ]; then
    ANCESTOR_DIR="$TARGET/.claude/vgflow-ancestor/v${INSTALLED_VERSION#v}"
    rm -rf "$ANCESTOR_DIR"
    mkdir -p "$ANCESTOR_DIR"
    for entry in commands skills scripts schemas templates codex-skills playwright-locks migrations fixtures; do
      if [ -e "$SCRIPT_DIR/$entry" ]; then
        cp -R "$SCRIPT_DIR/$entry" "$ANCESTOR_DIR/$entry"
      fi
    done
    for file in VGFLOW-VERSION VERSION CHANGELOG.md README.md README.vi.md LICENSE install.sh sync.sh vg.config.template.md requirements.txt gate-manifest.json; do
      if [ -f "$SCRIPT_DIR/$file" ]; then
        cp "$SCRIPT_DIR/$file" "$ANCESTOR_DIR/$file"
      fi
    done
    echo "  -> .claude/vgflow-ancestor/v${INSTALLED_VERSION#v}"
  fi
fi

# ============================================================
# 2. Codex CLI skills + agents
# ============================================================
echo "[2/6] Codex CLI skills + agents (full VGFlow parity)..."

mkdir -p "$TARGET/.codex/skills" "$TARGET/.codex/agents"

SKILL_DEPLOYED=0
if [ -d "$SCRIPT_DIR/codex-skills" ]; then
  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill="$(basename "$skill_dir")"
    rm -rf "$TARGET/.codex/skills/$skill"
    mkdir -p "$TARGET/.codex/skills/$skill"
    cp -R "$skill_dir"/. "$TARGET/.codex/skills/$skill/"
    SKILL_DEPLOYED=$((SKILL_DEPLOYED + 1))
  done < <(find "$SCRIPT_DIR/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
fi

AGENT_DEPLOYED=0
if [ -d "$SCRIPT_DIR/templates/codex-agents" ]; then
  cp "$SCRIPT_DIR/templates/codex-agents/"*.toml "$TARGET/.codex/agents/" 2>/dev/null || true
  AGENT_DEPLOYED=$(ls "$TARGET/.codex/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
fi

if [ -d "$SCRIPT_DIR/templates/codex" ]; then
  cp "$SCRIPT_DIR/templates/codex/"* "$TARGET/.codex/" 2>/dev/null || true
fi

echo "  -> ${SKILL_DEPLOYED} Codex skills installed (full pipeline)"
echo "  -> ${AGENT_DEPLOYED} Codex agent template(s) installed"

if [ -d "$HOME/.codex" ]; then
  mkdir -p "$HOME/.codex/skills" "$HOME/.codex/agents"
  if [ -d "$SCRIPT_DIR/codex-skills" ]; then
    while IFS= read -r skill_dir; do
      [ -f "$skill_dir/SKILL.md" ] || continue
      skill="$(basename "$skill_dir")"
      rm -rf "$HOME/.codex/skills/$skill"
      mkdir -p "$HOME/.codex/skills/$skill"
      cp -R "$skill_dir"/. "$HOME/.codex/skills/$skill/"
    done < <(find "$SCRIPT_DIR/codex-skills" -mindepth 1 -maxdepth 1 -type d | sort)
  fi
  if [ -d "$SCRIPT_DIR/templates/codex-agents" ]; then
    cp "$SCRIPT_DIR/templates/codex-agents/"*.toml "$HOME/.codex/agents/" 2>/dev/null || true
  fi
  CODEX_CONFIG="$HOME/.codex/config.toml"
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
    config_file="$(codex_config_path "$HOME/.codex/agents/${name}.toml")"
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
  echo "  -> global ~/.codex skills/agents refreshed"
fi

if command -v codex &>/dev/null; then
  echo "  Codex CLI detected. Available examples: \$vg-project, \$vg-scope, \$vg-blueprint, \$vg-build, \$vg-review, \$vg-test, \$vg-accept"
else
  echo "  -> codex CLI not found; skills are installed but inactive until Codex is installed"
fi

# ============================================================
# 3. Gemini CLI — CrossAI-only role (no vg-* skills)
# ============================================================
echo "[3/6] Gemini CLI (CrossAI role only)..."
# After field testing, Gemini's vg-review/test quality was lower than Codex + Claude.
# Gemini is now reduced to CrossAI reviewer role (third opinion) only.
# vg-* workflow skills are NOT installed for Gemini.
# CrossAI invocation still works — see .claude/commands/vg/_shared/crossai-invoke.md
echo "  → Gemini vg-* skills NOT installed (reduced to CrossAI role)"
echo "  → CrossAI invocation via .claude/commands/vg/_shared/crossai-invoke.md still uses gemini CLI"

# ============================================================
# 4. Playwright lock manager
# ============================================================
echo "[4/6] Playwright lock manager..."
LOCK_DIR="$HOME/.claude/playwright-locks"
mkdir -p "$LOCK_DIR"

if [ ! -f "$LOCK_DIR/playwright-lock.sh" ]; then
  cp "$SCRIPT_DIR/playwright-locks/playwright-lock.sh" "$LOCK_DIR/"
  chmod +x "$LOCK_DIR/playwright-lock.sh"
  echo "  → $LOCK_DIR/playwright-lock.sh"
else
  echo "  → already exists, skipping"
fi

echo ""
echo "  Auto-configuring Playwright MCP for detected CLIs..."

# Use Python3 for safe JSON merge (jq may not be on Windows).
PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
  echo "  ⚠ Python not found — skipping auto-config. Install Python 3 and re-run this step."
  echo "  Manual snippet:"
  echo '    {"mcpServers":{"playwright1":{"command":"npx","args":["@playwright/mcp@latest","--user-data-dir","<profile-dir>"]}}}'
else

# JSON merge for Claude/Gemini (preserves existing keys, adds playwright1-5 if missing)
merge_json_mcp_py() {
  local settings="$1"
  local profile_prefix="$2"
  local cli_name="$3"
  "$PYTHON_BIN" - "$settings" "$profile_prefix" "$cli_name" <<'PYEOF'
import json, sys
from pathlib import Path
path, profile_prefix, cli_name = sys.argv[1], sys.argv[2], sys.argv[3]
p = Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
if p.exists() and p.stat().st_size > 0:
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        print(f"  ⚠ {cli_name}: {path} has invalid JSON — refusing to overwrite. Backup first.")
        sys.exit(1)
else:
    data = {}
data.setdefault("mcpServers", {})
added = []
for i in range(1, 6):
    key = f"playwright{i}"
    if key not in data["mcpServers"]:
        data["mcpServers"][key] = {
            "command": "npx",
            "args": ["@playwright/mcp@latest", "--user-data-dir", f"{profile_prefix}-{i}"]
        }
        added.append(key)
p.write_text(json.dumps(data, indent=2))
if added:
    print(f"  ✓ {cli_name}: added {', '.join(added)} → {path}")
else:
    print(f"  ✓ {cli_name}: already configured → {path}")
PYEOF
}

# Claude Code
if [ -d "$HOME/.claude" ] || command -v claude &>/dev/null; then
  merge_json_mcp_py "$HOME/.claude/settings.json" "$HOME/.claude/playwright-profile" "Claude"
fi

# Gemini CLI
if [ -d "$HOME/.gemini" ] || command -v gemini &>/dev/null; then
  merge_json_mcp_py "$HOME/.gemini/settings.json" "$HOME/.gemini/playwright-profile" "Gemini"
fi

# Codex CLI — TOML, simple append (idempotent via grep)
if [ -d "$HOME/.codex" ] || command -v codex &>/dev/null; then
  CODEX_CONFIG="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  touch "$CODEX_CONFIG"
  ADDED=""
  for i in 1 2 3 4 5; do
    if ! grep -q "^\[mcp_servers\.playwright$i\]" "$CODEX_CONFIG" 2>/dev/null; then
      cat >> "$CODEX_CONFIG" <<EOF

[mcp_servers.playwright$i]
command = "npx"
args = ["@playwright/mcp@latest", "--user-data-dir", "$HOME/.codex/playwright-profile-$i"]
EOF
      ADDED="$ADDED playwright$i"
    fi
  done
  if [ -n "$ADDED" ]; then
    echo "  ✓ Codex: added$ADDED → $CODEX_CONFIG"
  else
    echo "  ✓ Codex: already configured → $CODEX_CONFIG"
  fi
fi

fi  # end python check

MCP_VALIDATOR="$SCRIPT_DIR/scripts/validators/verify-playwright-mcp-config.py"
if [ -n "${PYTHON_BIN:-}" ] && [ -f "$MCP_VALIDATOR" ]; then
  if "$PYTHON_BIN" "$MCP_VALIDATOR" --repair --quiet \
      --lock-source "$SCRIPT_DIR/playwright-locks/playwright-lock.sh"; then
    echo "  ✓ Playwright MCP verified: Claude + Codex playwright1-5"
  else
    echo "  ⚠ Playwright MCP verification failed. Run:"
    echo "    $PYTHON_BIN $MCP_VALIDATOR --repair --lock-source \"$SCRIPT_DIR/playwright-locks/playwright-lock.sh\""
    exit 1
  fi
fi

echo "  Note: restart each CLI after install to load the new MCP servers."

# ============================================================
# 5. vg-ext helper script
# ============================================================
echo "[5/6] vg-ext helper..."
if [ -f "$SCRIPT_DIR/../vg-ext" ]; then
  cp "$SCRIPT_DIR/../vg-ext" "$TARGET/vg-ext"
  chmod +x "$TARGET/vg-ext"
  echo "  → vg-ext (terminal launcher for cross-CLI review)"
else
  echo "  → vg-ext not found in source, skipping"
fi

# ============================================================
# 5b. Enforcement hooks (v1.16.0 — runtime contract verification)
# ============================================================
# VG uses Claude Code hooks as the deterministic enforcement substrate. Without
# this, skill-MD gates are prose-only (70-90% compliance per Anthropic docs).
# Hooks run at Stop (verify runtime_contract) + PostToolUse (warn on skill edit).
# Project-local install so enforcement travels with the repo.
echo "[5b/7] Enforcement hooks..."
if [ -f "$TARGET/.claude/scripts/vg-hooks-install.py" ]; then
  ( cd "$TARGET" && python .claude/scripts/vg-hooks-install.py ) && {
    echo "  → Stop hook: verify runtime_contract side-effects"
    echo "  → PostToolUse hook: warn on VG skill edit (reload required)"
    echo "  → UserPromptSubmit hook: pre-seed vg-orchestrator run-start"
    echo "  → PostToolUse Bash hook: track step markers into events.db"

    # Self-test — prove the hooks actually execute (not just installed)
    if [ -f "$TARGET/.claude/scripts/vg-hooks-selftest.py" ]; then
      echo "  Running hook self-test..."
      if ( cd "$TARGET" && python .claude/scripts/vg-hooks-selftest.py >/dev/null 2>&1 ); then
        echo "  ✓ Hook self-test passed (hooks confirmed functional)"
      else
        echo "  ⚠ Hook self-test failed. Re-run: cd $TARGET && python .claude/scripts/vg-hooks-selftest.py"
      fi
    fi
  } || echo "  ⚠ Hooks install failed. Re-run: cd $TARGET && python .claude/scripts/vg-hooks-install.py"
else
  echo "  → vg-hooks-install.py not copied — skipping (check scripts step)"
fi
find "$TARGET/.claude/scripts" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$TARGET/.claude/scripts" -type f -name '*.pyc' -delete 2>/dev/null || true

# ============================================================
# 6. Config template
# ============================================================
echo "[6/7] Config template..."
if [ -f "$TARGET/.claude/vg.config.md" ]; then
  echo "  → vg.config.md already exists — skipping (run /vg:init to reconfigure)"
else
  cp "$SCRIPT_DIR/vg.config.template.md" "$TARGET/.claude/vg.config.md"
  echo "  → .claude/vg.config.md (template — run /vg:init to configure)"
fi

# ============================================================
# 7. Graphify (knowledge graph for token-saving sibling/caller context)
# ============================================================
echo "[7/7] Graphify (optional, recommended)..."
echo "  Graphify saves ~50% executor tokens by querying a code knowledge graph"
echo "  instead of dumping file content. Builds in ~30s, no LLM tokens consumed."
echo ""

GRAPHIFY_HELPER="$SCRIPT_DIR/scripts/ensure-graphify.py"
if [ "${VGFLOW_SKIP_GRAPHIFY_INSTALL:-false}" != "true" ] && [ -n "${PYTHON_BIN:-}" ] && [ -f "$GRAPHIFY_HELPER" ]; then
  if "$PYTHON_BIN" "$GRAPHIFY_HELPER" --target "$TARGET" --repair; then
    echo "  -> Graphify verified/repaired"
    VGFLOW_GRAPHIFY_HELPER_DONE=true
  else
    echo "  WARNING: Graphify helper failed; falling back to legacy installer path"
  fi
fi

if [ "${VGFLOW_SKIP_GRAPHIFY_INSTALL:-false}" = "true" ]; then
  echo "  -> graphify install skipped by VGFLOW_SKIP_GRAPHIFY_INSTALL=true"
elif [ "${VGFLOW_GRAPHIFY_HELPER_DONE:-false}" = "true" ]; then
  :
else

# Detect Python 3.10+
PY=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
      PY="$cmd"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "  ⚠ Python 3.10+ not found — graphify install skipped"
  echo "  After installing Python: pip install --user 'graphifyy[mcp]' && cd $TARGET && $PY -m graphify update ."
  echo "  Then set graphify.enabled=true in .claude/vg.config.md (default ON)"
else
  echo "  ✓ Python detected: $PY ($($PY --version))"

  # Check if already installed
  if "$PY" -c "import graphify" 2>/dev/null; then
    echo "  ✓ graphify already installed"
  else
    echo "  Installing graphifyy[mcp] (~50MB tree-sitter parsers)..."
    "$PY" -m pip install --user 'graphifyy[mcp]' --quiet 2>&1 | tail -3
    if "$PY" -c "import graphify" 2>/dev/null; then
      echo "  ✓ graphifyy installed"
    else
      echo "  ⚠ Install may have failed — check pip output above"
    fi
  fi

  # Install Claude Code skill + PreToolUse hook
  if "$PY" -c "import graphify" 2>/dev/null; then
    "$PY" -m graphify install --platform claude 2>&1 | tail -2
    "$PY" -m graphify claude install 2>&1 | tail -2

    # Write .graphifyignore if missing
    if [ ! -f "$TARGET/.graphifyignore" ]; then
      cat > "$TARGET/.graphifyignore" <<'GIGN'
# Auto-generated by vgflow installer
# --- Universal (web + mobile) ---
.planning/
.claude/
node_modules/
dist/
build/
target/
.next/
graphify-out/
test-results/
playwright-report/
*.generated.*
coverage/
# --- Mobile toolchain byproducts ---
ios/Pods/
ios/build/
ios/DerivedData/
ios/*.xcworkspace/xcuserdata/
android/.gradle/
android/app/build/
android/build/
android/local.properties
.dart_tool/
.flutter-plugins
.flutter-plugins-dependencies
.pub-cache/
# --- Platform noise ---
.DS_Store
Thumbs.db
GIGN
      echo "  ✓ Wrote $TARGET/.graphifyignore (web + mobile patterns)"
    fi

    # Register MCP server
    MCP_FILE="$TARGET/.mcp.json"
    if [ ! -f "$MCP_FILE" ]; then
      cat > "$MCP_FILE" <<'MCPJSON'
{
  "mcpServers": {
    "graphify": {
      "command": "python",
      "args": ["-m", "graphify.serve", "graphify-out/graph.json"],
      "env": {},
      "type": "stdio"
    }
  }
}
MCPJSON
      echo "  ✓ Created $MCP_FILE with graphify MCP server"
    else
      # Use Python to merge (preserve existing)
      "$PY" - <<MCPPY
import json
from pathlib import Path
p = Path("$MCP_FILE")
data = json.loads(p.read_text())
data.setdefault("mcpServers", {})
if "graphify" not in data["mcpServers"]:
    data["mcpServers"]["graphify"] = {
        "command": "python",
        "args": ["-m", "graphify.serve", "graphify-out/graph.json"],
        "env": {},
        "type": "stdio"
    }
    p.write_text(json.dumps(data, indent=2))
    print("  ✓ Added graphify to $MCP_FILE")
else:
    print("  ✓ graphify already in $MCP_FILE")
MCPPY
    fi

    # Add graphify-out/ to .gitignore if missing
    if [ -f "$TARGET/.gitignore" ] && ! grep -q "^graphify-out" "$TARGET/.gitignore"; then
      echo "" >> "$TARGET/.gitignore"
      echo "# Graphify knowledge graph (regenerable via 'python -m graphify update .')" >> "$TARGET/.gitignore"
      echo "graphify-out/" >> "$TARGET/.gitignore"
      echo "  ✓ Added graphify-out/ to .gitignore"
    fi

    # Note: Codex does NOT need MCP graphify. /vg:build sibling detection +
    # /vg:review Phase 1.5 ripple both use Python scripts (find-siblings.py,
    # build-caller-graph.py --changed-files-input). These scripts combine graphify
    # graph + git grep — work on any CLI without MCP setup.
    # Claude MCP (.mcp.json) is still configured for ad-hoc graph queries but is
    # NOT required for the workflow steps.

    echo ""
    echo "  → Build initial graph (one-time, ~30s, no LLM tokens):"
    echo "      cd $TARGET && $PY -m graphify update ."
    echo ""
    echo "  → /vg:build + /vg:review use Python scripts directly (no MCP required)."
    echo "  → Claude also gets MCP tools via .mcp.json for ad-hoc queries."
    echo "  → To disable: set graphify.enabled=false in .claude/vg.config.md"
  fi
fi

fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "═══════════════════════════════════════════════════"
echo "VGFlow installed successfully!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Claude Code (full VG commands + helper skills):"
echo "  .claude/commands/vg/specs.md          /vg:specs"
echo "  .claude/commands/vg/scope.md          /vg:scope"
echo "  .claude/commands/vg/blueprint.md      /vg:blueprint"
echo "  .claude/commands/vg/build.md          /vg:build"
echo "  .claude/commands/vg/review.md         /vg:review"
echo "  .claude/commands/vg/test.md           /vg:test"
echo "  .claude/commands/vg/test-prep.md      /vg:test-prep"
echo "  .claude/commands/vg/accept.md         /vg:accept"
echo "  .claude/commands/vg/phase.md          /vg:phase"
echo "  .claude/commands/vg/next.md           /vg:next"
echo "  .claude/commands/vg/init.md           /vg:init"
echo ""
echo "Codex CLI (full skills + agents):"
echo "  \$vg-project   \$vg-scope   \$vg-blueprint   \$vg-build"
echo "  \$vg-review    \$vg-test    \$vg-accept      \$vg-next"
echo ""
echo "Gemini CLI (CrossAI role only — no vg-* skills):"
echo "  Used via crossai-invoke.md for third-opinion review."
echo "  Not for primary workflow execution."
echo ""
echo "Cross-CLI:"
echo "  vg-ext                                bash vg-ext review <phase> <codex|claude>"
echo "  ~/.claude/playwright-locks/           Multi-tab Playwright lock manager"
echo ""
echo "Next steps:"
echo "  1. cd $TARGET"
echo "  2. Open Claude Code → /vg:init"
echo "     → For mobile projects pick a mobile-* profile when asked;"
echo "       /vg:init will expand the mobile: block in vg.config.md."
echo "     → Supported: mobile-rn | mobile-flutter | mobile-native-ios"
echo "                  | mobile-native-android | mobile-hybrid"
echo "     → iOS-only steps auto-skip on Windows/Linux hosts; enable"
echo "       mobile.deploy.cloud_fallback_for_ios=true for EAS/Codemagic."
echo "     → Install Maestro (universal: brew/curl/scoop) before /vg:review"
echo "       for mobile phases. Android SDK platform-tools (adb) works on any OS."
echo "     → See vgflow/README.md '## Mobile profiles (V1)' for the full matrix."
echo "  3. Open Codex -> \$vg-next  or  \$vg-phase <phase>"
echo "  (Gemini CLI used only for CrossAI review; no direct workflow)"

# === v1.11.0 R5 Bug Reporting consent (opt-out default) ===
if [ -f "$TARGET/.claude/commands/vg/_shared/lib/bug-reporter.sh" ]; then
  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo "  Help improve VG workflow"
  echo "═══════════════════════════════════════════════════════════════"
  echo ""
  echo "VG có thể tự động gửi bug reports + install telemetry tới"
  echo "vietdev99/vgflow GitHub issues để giúp cải thiện workflow."
  echo ""
  echo "Sẽ gửi (đã redact PII):"
  echo "  ✓ Schema violations, helper errors, user pushback"
  echo "  ✓ Install/update events (version, OS), command usage counts"
  echo ""
  echo "KHÔNG gửi:"
  echo "  ✗ Project code, decisions, file contents, PII"
  echo "  ✗ User email, project name (auto-redact)"
  echo ""
  echo "Send modes (3-tier):"
  echo "  1. gh CLI (nếu authenticated)"
  echo "  2. Pre-filled URL (browser submit anonymous)"
  echo "  3. Local queue (silent if neither work)"
  echo ""
  echo "Opt-out anytime: cd $TARGET && /vg:bug-report --disable-all"
  echo ""
  if [ -t 0 ] && [ -r /dev/tty ]; then
    printf "Enable bug reporting? [Y/n] (default: Y): "
    read -r BR_CONSENT < /dev/tty || BR_CONSENT="Y"
  else
    echo "No interactive TTY detected; using bug reporting default: enabled."
    BR_CONSENT="Y"
  fi
  BR_CONSENT="${BR_CONSENT:-Y}"

  case "$BR_CONSENT" in
    Y|y|yes|Yes) BR_ENABLED="true" ;;
    *)           BR_ENABLED="false" ;;
  esac

  CONFIG_FILE="$TARGET/.claude/vg.config.md"
  if [ -f "$CONFIG_FILE" ] && ! grep -qE "^bug_reporting:" "$CONFIG_FILE"; then
    cat >> "$CONFIG_FILE" <<EOF

# ─── Bug Reporting (v1.11.0 R5) ───────────────────────────────────────
# Auto-detect workflow bugs + telemetry → vietdev99/vgflow GitHub issues
# Consented at install: $(date -u +%Y-%m-%dT%H:%M:%SZ)
bug_reporting:
  enabled: ${BR_ENABLED}
  repo: "vietdev99/vgflow"
  severity_threshold: "minor"
  auto_send_minor: true
  redact_project_paths: true
  redact_project_names: true
  auto_assign: "vietdev99"
  default_labels: ["bug-auto", "needs-triage"]
  max_per_session: 5
  queue_path: ".claude/.bug-reports-queue.jsonl"
  sent_cache_path: ".claude/.bug-reports-sent.jsonl"
EOF
    if [ "$BR_ENABLED" = "true" ]; then
      echo "✓ Bug reporting enabled"
      ( cd "$TARGET" && \
        source .claude/commands/vg/_shared/lib/bug-reporter.sh 2>/dev/null && \
        report_telemetry "install_success" "{\"version\":\"$(cat .claude/VGFLOW-VERSION 2>/dev/null || echo unknown)\",\"installer\":\"install.sh\"}" ) 2>/dev/null || true
    else
      echo "✓ Bug reporting disabled. Re-enable: /vg:bug-report --enable"
    fi
  fi
fi
