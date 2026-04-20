#!/bin/bash
# VGFlow Installer — copy pipeline files to target project
# Usage: ./install.sh /path/to/your/project
#
# Installs:
#   - Claude Code commands (.claude/commands/vg/)
#   - Claude Code skills (.claude/skills/api-contract/)
#   - Codex CLI skill (.codex/skills/vg-review/)
#   - Gemini CLI (CrossAI role only — no vg-* skills installed)
#   - Playwright lock manager (~/.claude/playwright-locks/)
#   - vg-ext helper script (project root)
#   - vg.config.md template

set -e

TARGET="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$TARGET" = "." ]; then
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

# ============================================================
# 1. Claude Code commands + skills + scripts + templates
# ============================================================
echo "[1/6] Claude Code commands + skills + scripts + templates..."
mkdir -p "$TARGET/.claude/commands/vg/_shared"
mkdir -p "$TARGET/.claude/skills/api-contract"
mkdir -p "$TARGET/.claude/skills/vg-design-scanner"
mkdir -p "$TARGET/.claude/skills/vg-design-gap-hunter"
mkdir -p "$TARGET/.claude/skills/vg-haiku-scanner"
mkdir -p "$TARGET/.claude/skills/vg-crossai"
mkdir -p "$TARGET/.claude/scripts"
mkdir -p "$TARGET/.claude/templates/vg"

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

# Skills: api-contract + design scanner/hunter + haiku-scanner (review) + crossai (multi-CLI engine)
cp "$SCRIPT_DIR/skills/api-contract/SKILL.md" "$TARGET/.claude/skills/api-contract/"
if [ -f "$SCRIPT_DIR/skills/vg-design-scanner/SKILL.md" ]; then
  cp "$SCRIPT_DIR/skills/vg-design-scanner/SKILL.md" "$TARGET/.claude/skills/vg-design-scanner/"
  cp "$SCRIPT_DIR/skills/vg-design-gap-hunter/SKILL.md" "$TARGET/.claude/skills/vg-design-gap-hunter/"
  echo "  → design-extract skills installed (Haiku scanner + gap hunter)"
fi
if [ -f "$SCRIPT_DIR/skills/vg-haiku-scanner/SKILL.md" ]; then
  cp "$SCRIPT_DIR/skills/vg-haiku-scanner/SKILL.md" "$TARGET/.claude/skills/vg-haiku-scanner/"
  echo "  → vg-haiku-scanner installed (used by /vg:review view scan)"
fi
if [ -f "$SCRIPT_DIR/skills/vg-crossai/SKILL.md" ]; then
  cp "$SCRIPT_DIR/skills/vg-crossai/SKILL.md" "$TARGET/.claude/skills/vg-crossai/"
  echo "  → vg-crossai installed (multi-CLI review engine — referenced by _shared/crossai-invoke.md)"
fi

# All .claude/scripts/*.py and *.js go together — includes universal helpers
# (filter-steps, design-normalize, pre-executor-check, verify-goal-test-binding,
# phase-recon, etc.) plus mobile additions (maestro-mcp, verify-mobile-*)
# shipped under the same umbrella. Any future script dropped into
# vgflow/scripts/ is installed automatically.
if [ -d "$SCRIPT_DIR/scripts" ]; then
  cp "$SCRIPT_DIR/scripts/"*.py "$TARGET/.claude/scripts/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/"*.js "$TARGET/.claude/scripts/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/"*.sh "$TARGET/.claude/scripts/" 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/"*.py 2>/dev/null || true
  chmod +x "$TARGET/.claude/scripts/"*.sh 2>/dev/null || true
  SCRIPT_COUNT=$(ls "$TARGET/.claude/scripts/"*.py "$TARGET/.claude/scripts/"*.sh 2>/dev/null | wc -l | tr -d ' ')
  echo "  → ${SCRIPT_COUNT} helper scripts installed (python + shell — design, filter-steps, verify-*, mobile tooling setup)"
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

# ============================================================
# 2. Codex CLI skill
# ============================================================
echo "[2/6] Codex CLI skills (verification subset — review onwards)..."
# v1.11.3: Codex chỉ chạy phần verification (post-build). Không phải tất cả 36 skills.
# Codex tốt cho: review/test/accept (E2E browser), regression sweep, diagnostics.
# Generation-heavy commands (scope/blueprint/build) belong to Claude/main IDE.
#
# Subset deployed to .codex/skills/:
CODEX_SKILLS=(
  vg-review       # post-build code scan + browser discovery
  vg-test         # goal verification + codegen
  vg-accept       # human UAT
  vg-regression   # full regression sweep
  vg-next         # auto-advance pipeline
  vg-progress     # status dashboard
  vg-bug-report   # auto-report workflow bugs
  vg-doctor       # health/integrity dispatcher
  vg-health       # project health
  vg-integrity    # artifact manifest verify
  vg-recover      # stuck phase recovery
  vg-update       # pull latest
  vg-reapply-patches  # post-update conflict resolve
)

SKILL_DEPLOYED=0
for skill in "${CODEX_SKILLS[@]}"; do
  src="$SCRIPT_DIR/codex-skills/$skill/SKILL.md"
  if [ -f "$src" ]; then
    mkdir -p "$TARGET/.codex/skills/$skill"
    cp "$src" "$TARGET/.codex/skills/$skill/"
    SKILL_DEPLOYED=$((SKILL_DEPLOYED + 1))
  fi
done

echo "  → ${SKILL_DEPLOYED}/${#CODEX_SKILLS[@]} codex skills installed (verification subset)"
if command -v codex &>/dev/null; then
  echo "  Codex CLI detected. Available: \$vg-review, \$vg-test, \$vg-accept, \$vg-regression, \$vg-next, \$vg-progress, ..."
  echo "  Note: scope/blueprint/build use Claude (heavier reasoning)."
else
  echo "  → codex CLI not found — skills installed inactive until codex installed"
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
PYTHON_BIN=$(command -v python3 || command -v python)
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

    # Self-test — prove the hooks actually execute (not just installed)
    if [ -f "$TARGET/.claude/scripts/vg-hooks-selftest.py" ]; then
      echo "  Running hook self-test..."
      if ( cd "$TARGET" && python .claude/scripts/vg-hooks-selftest.py >/dev/null 2>&1 ); then
        echo "  ✓ Hook self-test: 4/4 passed (hooks confirmed functional)"
      else
        echo "  ⚠ Hook self-test failed. Re-run: cd $TARGET && python .claude/scripts/vg-hooks-selftest.py"
      fi
    fi
  } || echo "  ⚠ Hooks install failed. Re-run: cd $TARGET && python .claude/scripts/vg-hooks-install.py"
else
  echo "  → vg-hooks-install.py not copied — skipping (check scripts step)"
fi

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

# ============================================================
# Summary
# ============================================================
echo ""
echo "═══════════════════════════════════════════════════"
echo "VGFlow installed successfully!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Claude Code (11 commands + 4 shared + 1 skill):"
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
echo "Codex CLI (4 skills — project-scoped in .codex/skills/):"
echo "  \$vg-review <phase>   \$vg-test <phase>"
echo "  \$vg-next [phase]     \$vg-accept <phase>"
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
echo "  3. Open Codex → \$vg-next  or  \$vg-review <phase>"
echo "  (Gemini CLI used only for CrossAI review — no direct workflow)"

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
  printf "Enable bug reporting? [Y/n] (default: Y): "
  read -r BR_CONSENT < /dev/tty 2>/dev/null || BR_CONSENT="Y"
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
