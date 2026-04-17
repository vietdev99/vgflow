# Config Loader (Shared Reference)

Referenced by ALL vg/ commands. Read this FIRST in every command.

## Cross-Platform Helpers (run ONCE at command start)

```bash
# --- Repo root (absolute) ---
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# --- Python interpreter detection + version check ---
# Mac/Linux usually have python3, Windows official installer only puts python on PATH
PYTHON_BIN=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1; then
    # Verify version >= 3.10 (graphify + build-caller-graph.py use 3.10+ syntax)
    VER=$("$cand" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    MAJOR=${VER%.*}
    MINOR=${VER#*.}
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ] 2>/dev/null; then
      PYTHON_BIN="$cand"
      break
    fi
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "⛔ No Python 3.10+ found. Tried: python3, python, py. Install from https://python.org"
  exit 1
fi

# --- Temp directory (cross-platform: POSIX /tmp works in Git Bash too) ---
VG_TMP="${TMPDIR:-/tmp}"
mkdir -p "$VG_TMP" 2>/dev/null

# --- Graphify detection (single source of truth) ---
GRAPHIFY_ENABLED=$(awk '/^graphify:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /enabled:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "false")

# graph_path from config, then resolve to absolute via $REPO_ROOT
GRAPH_REL=$(awk '/^graphify:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /graph_path:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
GRAPH_REL="${GRAPH_REL:-graphify-out/graph.json}"
if [[ "$GRAPH_REL" = /* ]] || [[ "$GRAPH_REL" =~ ^[A-Za-z]: ]]; then
  GRAPHIFY_GRAPH_PATH="$GRAPH_REL"   # already absolute
else
  GRAPHIFY_GRAPH_PATH="${REPO_ROOT}/${GRAPH_REL}"
fi

GRAPHIFY_FALLBACK=$(awk '/^graphify:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /fallback_to_grep:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "true")
GRAPHIFY_STALE_WARN=$(awk '/^graphify:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /staleness_warn_commits:/{print $2; exit}' .claude/vg.config.md 2>/dev/null || echo "50")

GRAPHIFY_ACTIVE="false"
if [ "$GRAPHIFY_ENABLED" = "true" ] && [ -f "$GRAPHIFY_GRAPH_PATH" ]; then
  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  if [ -n "$GRAPH_BUILD_EPOCH" ]; then
    COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')
    if [ "${COMMITS_SINCE:-0}" -gt "${GRAPHIFY_STALE_WARN:-50}" ] 2>/dev/null; then
      echo "⚠ Graph stale: $COMMITS_SINCE commits since last build"
      echo "  Rebuild: cd $REPO_ROOT && ${PYTHON_BIN} -m graphify update ."
    fi
  fi
  GRAPHIFY_ACTIVE="true"
elif [ "$GRAPHIFY_ENABLED" = "true" ]; then
  if [ "$GRAPHIFY_FALLBACK" = "true" ]; then
    echo "⚠ Graphify enabled but graph missing at $GRAPHIFY_GRAPH_PATH"
    echo "  Build: ${PYTHON_BIN} -m graphify update ."
    echo "  Falling back to grep-only for this run."
  else
    echo "⛔ Graphify enabled, graph missing, fallback_to_grep=false → BLOCK"
    echo "  Build: ${PYTHON_BIN} -m graphify update ."
    exit 1
  fi
fi
```

```bash
# --- Model selection (per pipeline role) ---
# Parse models section from config. Commands use these to set Agent model: parameter.
MODEL_PLANNER=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /planner:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "opus")
MODEL_CONTRACT_GEN=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /contract_gen:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "sonnet")
MODEL_TEST_GOALS=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /test_goals:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "sonnet")
MODEL_EXECUTOR=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /executor:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "sonnet")
MODEL_DEBUGGER=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /debugger:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "opus")
MODEL_SCANNER=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /scanner:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "haiku")
MODEL_TEST_CODEGEN=$(awk '/^models:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /test_codegen:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "sonnet")
```

After sourcing: all bash blocks MUST use `${PYTHON_BIN}`, `${VG_TMP}/`, `${REPO_ROOT}`, `${GRAPHIFY_GRAPH_PATH}`, `${GRAPHIFY_ACTIVE}`, and model variables `${MODEL_PLANNER}`, `${MODEL_EXECUTOR}`, etc. (instead of duplicating detection logic).

## How to Load Config

1. **Read** `.claude/vg.config.md` — parse YAML frontmatter into variables
2. **If file missing** → STOP: "Config not found. Run `/vg:init` to create `.claude/vg.config.md`"

### BOM Strip + Required Field Validation

```bash
# Strip BOM (Windows editors may add UTF-8 BOM) — tightened 2026-04-17
# Write stripped content to a clean temp file so downstream parsers can use it.
CONFIG_CLEAN="${VG_TMP:-/tmp}/vg.config.clean.md"
sed '1s/^\xEF\xBB\xBF//' .claude/vg.config.md > "$CONFIG_CLEAN"
CONFIG_RAW=$(cat "$CONFIG_CLEAN")

# Check required fields — use CLEAN file (grep on raw file misses first-field if BOM present)
for FIELD in project_name package_manager profile; do
  if ! grep -q "^${FIELD}:" "$CONFIG_CLEAN"; then
    echo "⛔ CONFIG ERROR: required field '${FIELD}' missing in .claude/vg.config.md"
    echo "  Run /vg:init to generate config."
    exit 1
  fi
done

# Validate model keys (tightened 2026-04-17) — missing models.* keys default silently to "opus"
# which is wasteful on cheap tasks. Explicit validation surfaces config gaps.
for MK in models_executor models_planner models_debugger; do
  MK_DOTTED=$(echo "$MK" | tr '_' '.')  # models_executor → models.executor
  if ! grep -qE "^\s*${MK_DOTTED}:|^\s*$(echo $MK | cut -d_ -f2):" "$CONFIG_CLEAN"; then
    echo "⚠ CONFIG: ${MK_DOTTED} missing — defaulting. Run /vg:init to explicitly set model profile."
  fi
done

# v1.9.2.6 — config schema drift detection
# New sections added in v1.9.x that user configs may not have yet.
# Each missing section → WARN + hint to user (no block — workflow falls back silently).
declare -A CONFIG_V1_9_SECTIONS=(
  ["review.fix_routing"]="Phase 3 fix loop 3-tier routing (v1.9.1 R2) — inline/spawn/escalate thresholds"
  ["phase_profiles"]="Phase profile system (v1.9.2 P5) — feature/infra/hotfix/bugfix/migration/docs"
  ["test_strategy"]="Surface taxonomy (v1.9.1 R1) — ui/api/data/integration/time-driven runners"
  ["scope"]="Scope adversarial check (v1.9.1 R3) — adversarial_check, adversarial_model"
  ["models.review_fix_inline"]="Review fix inline model (v1.9.1 R2) — main tier for small MINOR fixes"
  ["models.review_fix_spawn"]="Review fix spawn model (v1.9.1 R2) — cheaper tier for MODERATE/large fixes"
)

DRIFT_COUNT=0
DRIFT_MSG=""
for section in "${!CONFIG_V1_9_SECTIONS[@]}"; do
  # Dotted path → grep pattern. review.fix_routing → look for "review:" then "fix_routing:"
  main_key="${section%%.*}"
  if ! grep -qE "^${main_key}:" "$CONFIG_CLEAN"; then
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    DRIFT_MSG="${DRIFT_MSG}  - ${section} — ${CONFIG_V1_9_SECTIONS[$section]}\n"
  fi
done

if [ "$DRIFT_COUNT" -gt 0 ]; then
  echo ""
  echo "⚠ CONFIG DRIFT — ${DRIFT_COUNT} v1.9.x sections missing from .claude/vg.config.md:"
  echo -e "$DRIFT_MSG"
  echo "  Impact: workflow falls back to defaults — features may silent-skip (e.g., review fix routing fallback)"
  echo "  Fix: run '/vg:init' to regenerate config OR manually add sections from vgflow/vg.config.template.md"
  echo "  Continue on fallback? Safe for most phases, ship-blocker only if phase hits deferred feature."
  echo ""
fi
```

Use `$CONFIG_RAW` for downstream parsing instead of re-reading the file.

## How to Resolve Environment

Determine `$ENV` for this command:

1. If `--local` in `$ARGUMENTS` → `ENV=local`
2. If `--sandbox` in `$ARGUMENTS` → `ENV=sandbox`
3. Else → `ENV=step_env[{current_step}]` from config
   - `current_step` mapping:
     - scope, blueprint → use `step_env.execute` (planning steps, local)
     - build → use `step_env.execute`
     - review → use `step_env.sandbox_test` (browser discovery needs running app)
     - test → use `step_env.sandbox_test`
     - accept → use `step_env.verify`

## How to Resolve Worktree Ports

Multi-port support for parallel worktree sessions. Each worktree gets unique ports to avoid conflicts.

```
# 1. Detect worktree index
WORKTREE_INDEX = env var $VG_WORKTREE_INDEX OR 0

# Auto-detect from git worktree path (if env var not set):
if WORKTREE_INDEX == 0 AND git worktree is not main:
  # Parse worktree name for index: "wt1" → 1, "wt2" → 2, "feature-x" → hash % 10 + 1
  WORKTREE_NAME = basename of current git worktree
  if WORKTREE_NAME matches /wt(\d+)/:
    WORKTREE_INDEX = captured number
  else:
    WORKTREE_INDEX = (hash of WORKTREE_NAME) % 9 + 1   # 1-9, avoid 0 (main)

# 2. Calculate port offset
PORT_OFFSET = WORKTREE_INDEX * config.worktree_ports.offset_per_worktree   # default: 10

# 3. Compute actual ports — DYNAMIC from config keys (no hardcoded names)
PORTS = {}    # map of port_name → resolved_port
for each key in config.worktree_ports.base:
  PORTS[key] = config.worktree_ports.base[key] + PORT_OFFSET
  # e.g. base = { api: 3001, web: 5173 }
  #      wt1  → { api: 3011, web: 5183 }

# 4. Compute DB name (isolation per worktree)
if WORKTREE_INDEX > 0:
  DB_NAME = config.db_name OR "app"
  DB_NAME = "${DB_NAME}_wt${WORKTREE_INDEX}"
else:
  DB_NAME = config.db_name OR "app"

# 5. Replace placeholders in ALL command strings
# For each key in PORTS, placeholder {key_port} is available:
#   base keys: api → {api_port}, web → {web_port}, rtb → {rtb_port}, etc.
#   ANY key defined in config.worktree_ports.base becomes a placeholder
#   {db_name} is always available
# Used in: deploy.*, dev_command, credentials[*].domain, services[*].check
```

**Environment variables set after resolution:**

| Variable | Source | Example (main) | Example (wt1) |
|----------|--------|---------------|---------------|
| `$WORKTREE_INDEX` | env or auto-detect | 0 | 1 |
| `$PORT_OFFSET` | index * offset | 0 | 10 |
| `$PORTS` | map from config keys | {api:3001, web:5173} | {api:3011, web:5183} |
| `$DB_NAME` | db_name + suffix | myapp | myapp_wt1 |

Each key in `config.worktree_ports.base` becomes `$PORTS[key]` and placeholder `{key_port}`.
No fixed port variable names — workflow reads whatever the project defines.

**How to use in config (placeholders):**
```yaml
worktree_ports:
  base:
    api: 3001          # → {api_port}
    web: 5173          # → {web_port}
    # add any app-specific ports here — they auto-become placeholders
  offset_per_worktree: 10

deploy:
  health: "curl -sf http://localhost:{api_port}/health"
dev_command: "API_PORT={api_port} VITE_PORT={web_port} pnpm dev"
credentials:
  local:
    - role: "admin"
      domain: "localhost:{web_port}"
```

**For sandbox env:** worktree ports are ignored (sandbox uses fixed ports on VPS).
Only local env uses worktree port resolution.

## How to Run Commands on Target

Build the command runner from environment config:

```
ENV_CONFIG = config.environments[ENV]
RUN_PREFIX = ENV_CONFIG.run_prefix
PROJECT_PATH = ENV_CONFIG.project_path

function run_on_target(command):
  if RUN_PREFIX is empty:
    # Local — run directly
    bash: {command}
  else:
    # Remote — wrap with SSH
    bash: {RUN_PREFIX} "cd {PROJECT_PATH} && {command}"
```

## How to Resolve Deploy Commands

Merge deploy profile into environment deploy config:

```
PROFILE = config.deploy_profiles[config.deploy_profile]
ENV_DEPLOY = ENV_CONFIG.deploy

# Merged deploy commands:
BUILD    = ENV_DEPLOY.build    (already set per env)
RESTART  = ENV_DEPLOY.restart  OR PROFILE.restart
HEALTH   = ENV_DEPLOY.health
ROLLBACK = ENV_DEPLOY.rollback OR "{PROFILE.rollback_extra} && git checkout {prev_sha} && {BUILD} && {PROFILE.restart}"
```

Replace `{package_manager}` in any command string with `config.package_manager`.

## How to Get Credentials

```
function get_credentials(env, role):
  return config.credentials[env].find(c => c.role == role)
  # Returns: { role, domain, email, password }
```

## How to Get Services

```
function get_services(env):
  return config.services[env]
  # Returns: [{ name, check, required }]
```

## Variables Available After Loading

After config-loader, every vg/ command has access to:

| Variable | Source |
|----------|--------|
| `$PROJECT_NAME` | config.project_name |
| `$PACKAGE_MANAGER` | config.package_manager |
| `$ENV` | resolved environment name |
| `$RUN_PREFIX` | environments[ENV].run_prefix |
| `$PROJECT_PATH` | environments[ENV].project_path |
| `$DEPLOY_BUILD` | merged build command |
| `$DEPLOY_RESTART` | merged restart command |
| `$DEPLOY_HEALTH` | merged health command |
| `$DEPLOY_ROLLBACK` | merged rollback command |
| `$TEST_RUNNER` | environments[ENV].test_runner |
| `$PLANNING_DIR` | config.paths.planning |
| `$PHASES_DIR` | config.paths.phases |
| `$SCREENSHOTS_DIR` | config.paths.screenshots |
| `$SCAN_PATTERNS` | config.scan_patterns (object with grep arrays) |
| `$SESSION_MODEL` | config.session_model.strategy |
| `$GENERATED_TESTS_DIR` | config.paths.generated_tests |
| `$WORKTREE_INDEX` | 0 (main) or N (worktree) |
| `$PORT_OFFSET` | WORKTREE_INDEX * offset_per_worktree |
| `$PORTS` | dynamic map: {key: base+offset} from config.worktree_ports.base |
| `$DB_NAME` | db_name or db_name_wtN |
| `$PLAYWRIGHT_SERVER` | auto-claimed from lock manager |
| `$MCP_PREFIX` | `mcp__{PLAYWRIGHT_SERVER}__` (tool name prefix) |
| `$MODEL_PLANNER` | config.models.planner (default: opus) |
| `$MODEL_CONTRACT_GEN` | config.models.contract_gen (default: sonnet) |
| `$MODEL_TEST_GOALS` | config.models.test_goals (default: sonnet) |
| `$MODEL_EXECUTOR` | config.models.executor (default: sonnet) |
| `$MODEL_DEBUGGER` | config.models.debugger (default: opus) |
| `$MODEL_SCANNER` | config.models.scanner (default: haiku) |
| `$MODEL_TEST_CODEGEN` | config.models.test_codegen (default: sonnet) |

## How to Update Pipeline State

Every VG command MUST update `PIPELINE-STATE.json` in the phase directory at **start** and **end** of its step. This enables `/vg:progress` to show accurate status.

**File**: `${PHASES_DIR}/{phase_dir}/PIPELINE-STATE.json`

**Schema**:
```json
{
  "phase": "7.6",
  "updated_at": "2026-04-13T14:30:00Z",
  "steps": {
    "specs":     { "status": "done",        "started_at": "...", "finished_at": "..." },
    "scope":     { "status": "done",        "started_at": "...", "finished_at": "..." },
    "blueprint": { "status": "done",        "started_at": "...", "finished_at": "..." },
    "build":     { "status": "done",        "started_at": "...", "finished_at": "..." },
    "review":    { "status": "in_progress", "started_at": "...", "sub_step": "phase2_discovery", "detail": "Pass 2a: goal 3/8" },
    "test":      { "status": "pending" },
    "accept":    { "status": "pending" }
  },
  "errors": [],
  "last_action": "review: spawned 5 Haiku scanners"
}
```

**Status values**: `pending` | `in_progress` | `done` | `failed` | `skipped`

**How to write** (at start of any step):
```
Read existing PIPELINE-STATE.json (or create if missing)
Set steps[{current_step}].status = "in_progress"
Set steps[{current_step}].started_at = current ISO timestamp
Set updated_at = current ISO timestamp
Write PIPELINE-STATE.json
```

**How to write** (at end of any step):
```
Read PIPELINE-STATE.json
Set steps[{current_step}].status = "done" (or "failed")
Set steps[{current_step}].finished_at = current ISO timestamp
Remove sub_step and detail fields
Set last_action = "{step}: {summary}"
Write PIPELINE-STATE.json
```

**Sub-step tracking** (optional, for review/test which have multiple phases):
```
Set steps.review.sub_step = "phase1_code_scan" | "phase2_discovery" | "phase3_fix_loop" | "phase4_goal_comparison"
Set steps.review.detail = "Pass 2a: goal 3/8" | "Haiku scanning 5 views" | "Fix iteration 2/3"
```

**IMPORTANT**: This file is for status tracking only. Pipeline logic still uses artifact detection (CONTEXT.md, PLAN.md, etc.) for routing decisions. PIPELINE-STATE.json adds timing, sub-step visibility, and error history.

## How to Acquire Playwright MCP Server (Auto-Lock)

When a VG command needs browser interaction (review, test), it MUST auto-claim a free server.
**Do NOT read `playwright_server` from config** — use the lock manager instead.

### Claim (run ONCE at start of browser-using step)

```bash
LOCK_SCRIPT="${HOME}/.claude/playwright-locks/playwright-lock.sh"
SESSION_ID="vg-{phase}-{step}-$$"    # unique per session, e.g. "vg-7.6-review-12345"

# Auto-claim first free server
PLAYWRIGHT_SERVER=$(bash "$LOCK_SCRIPT" claim "$SESSION_ID")

if [ $? -ne 0 ]; then
  # All 5 servers locked — ask user to close a tab or wait
  BLOCK: "All 5 Playwright servers are in use. Close a tab or run: bash $LOCK_SCRIPT cleanup"
fi

MCP_PREFIX="mcp__${PLAYWRIGHT_SERVER}__"
```

### Release (run at END of browser-using step, or on error)

```bash
bash "$LOCK_SCRIPT" release "$SESSION_ID"
```

**IMPORTANT:** Always release in a finally/cleanup block. Stale locks auto-expire after 1 hour via `cleanup`.

### Tool calls use the prefix

```
{MCP_PREFIX}browser_navigate
{MCP_PREFIX}browser_snapshot
{MCP_PREFIX}browser_click
{MCP_PREFIX}browser_fill_form
{MCP_PREFIX}browser_take_screenshot
```

### Status check (debug)

```bash
bash "$LOCK_SCRIPT" status    # show all locks
bash "$LOCK_SCRIPT" cleanup   # remove locks older than 1 hour
```

**NEVER hardcode** any server name like `mcp__playwright1__`. Always use `$MCP_PREFIX` from auto-claim.
