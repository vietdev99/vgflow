---
# VG Workflow Config — Template (v1.13.0+)
# Rendered by /vg:project Round 7 via .claude/scripts/vg_generate_config.py.
# Foundation-derived fields use {{token}} substitution; the remainder stays as defaults.
# After generation, the file is promoted to .claude/vg.config.md (atomic rename).
#
# Token schema (Python generator reads from draft foundation JSON):
#   {{project_name}}, {{project_description}}, {{package_manager}}, {{profile}}
#   {{db_name}}, {{ports.database}}, {{backend.health}}, {{backend.port}}, {{frontend.port}}
#   {{i18n.default_locale}}, {{ssh_alias}}, {{domain}}
# CROSSAI_CLIS_BLOCK / MODELS_BLOCK / SERVICES_BLOCK / CREDENTIALS_BLOCK / APPS_BLOCK are dynamic
# sections replaced by the generator (see vg_generate_config.py).
# Remove this header before shipping to a project (generator strips it automatically).

# === Project Identity ===
project_name: "{{project_name}}"
project_description: "{{project_description}}"
package_manager: "{{package_manager}}"          # pnpm | npm | yarn | bun

# === Profile ===
# Determines which pipeline steps run. Orchestrator filters <step profile="..."> tags.
# Valid values: web-fullstack | web-frontend-only | web-backend-only | cli-tool | library
profile: "{{profile}}"

# === Multi-Surface Project (v1.10.0 R4 — NEW) =========================
# For projects with multiple platforms (web + mobile + CLI + backend),
# declare each surface explicitly so workflow knows which phase touches which.
# If single-surface project, omit this block — workflow uses `profile` alone.
#
# Each surface has:
#   type          — profile type (web-fullstack/web-frontend/mobile-rn/cli-tool/...)
#   stack         — tech stack identifier (fastify/react/swift/kotlin/rust)
#   paths         — monorepo dirs that belong to this surface
#   scanner_mode  — override review scanner mode for this surface (auto/parallel/sequential/none)
#   design        — role name mapping to .planning/design/{role}/DESIGN.md
#
# Phase SPECS declares touched surfaces via "surfaces:" field → workflow
# applies per-surface gates (review/test/build tool setup).
#
# Generic example (uncomment + customize if project has multiple surfaces):
# surfaces:
#   api:
#     type: "web-backend-only"
#     stack: "{{backend.framework}}"
#     paths: ["apps/api"]
#   web:
#     type: "web-frontend-only"
#     stack: "{{frontend.framework}}"
#     paths: ["apps/web"]
#     design: "default"
#   mobile:
#     type: "mobile-rn"            # or mobile-flutter / mobile-native
#     stack: "react-native"
#     paths: ["apps/mobile"]

# === Environments ===
# Workflow selects env via: --local, --sandbox, or step_env default
environments:
  local:
    os: "{{env.local.os}}"        # win32 | linux | darwin
    shell: "bash"
    run_prefix: ""                # empty = run directly on host
    project_path: ""              # auto-detected from cwd
    deploy:
      build: "{{package_manager}} install && {{package_manager}} run build"
      restart: "echo local-dev-restart-skipped"
      health: "curl -sf http://localhost:{{backend.port}}{{backend.health}}"
      rollback: "echo local-dev-rollback-skipped"
    test_runner: "{{test_runner_local}}"    # e.g., npx vitest run | pytest | cargo test
    dev_command: "{{package_manager}} dev"  # hotreload dev server
    dev_health_timeout: 30            # seconds to wait for health after dev_command
    # infra_start/stop/status — project-specific scripts for local infra (DB, cache, queue).
    # Uncomment + customize if project has local docker-compose or script-based infra:
    # infra_start: "docker compose -f docker-compose.dev.yml up -d"
    # infra_stop: "docker compose -f docker-compose.dev.yml down"
    # infra_status: "docker compose -f docker-compose.dev.yml ps"

  sandbox:
    os: "linux"
    shell: "bash"
    run_prefix: "ssh {{ssh_alias}}"
    project_path: "{{sandbox.project_path}}"
    deploy:
      pre: "git push origin main"
      build: "git pull origin main && {{package_manager}} install && {{package_manager}} run build"
      restart: "{{deploy.restart_cmd}}"     # e.g., pm2 reload app --update-env
      health: "curl -sf http://localhost:{{backend.port}}{{backend.health}}"
      rollback: "{{deploy.rollback_cmd}}"
    test_runner: "{{test_runner_sandbox}}"

# Default environment per pipeline step
# Override per-command with --local or --sandbox
step_env:
  execute: "local"
  sandbox_test: "local"            # changed: test local first (hotreload), --sandbox for VPS
  verify: "local"                  # changed: accept local, --sandbox for final verify

# === AI Models (per pipeline role) ===
# Controls which Claude model each pipeline step uses for Agent spawns.
# Valid: "opus" | "sonnet" | "haiku"
# Parent conversation model is always the orchestrator — these control SPAWNED agents only.
# Cost: opus ~$15/M, sonnet ~$3/M, haiku ~$0.25/M (input tokens)
# Model selection depends on team_size (cost vs quality):
#   solo → sonnet executor + opus planner (cost-aware)
#   team → opus across critical roles (quality priority)
# ⟪ MODELS_BLOCK ⟫

# === Worktree Port Offsets ===
# Each worktree uses base_port + offset to avoid collisions
# main = offset 0, worktree1 = offset 10, worktree2 = offset 20
worktree_ports:
  base:
    api: {{backend.port}}
    web: {{frontend.port}}
    # Add extra services as needed (e.g., rtb: 3000, pixel: 3003)
  offset_per_worktree: 10
  # Example: worktree1 → API:(api+10), Web:(web+10)
  # Example: worktree2 → API:(api+20), Web:(web+20)

# === Deploy Profile ===
deploy_profile: "{{deploy_profile}}"   # pm2 | docker | systemd | git_push | custom
deploy_profiles:
  pm2:
    restart: "pm2 restart all"
    status: "pm2 jlist 2>/dev/null | node -e \"process.stdin.on('data',d=>{const p=JSON.parse(d);p.forEach(s=>console.log(s.name,s.pm2_env.status))})\""
    rollback_extra: "pm2 stop all"
  docker:
    restart: "docker compose up -d"
    status: "docker compose ps"
    rollback_extra: "docker compose down"
  systemd:
    restart: "sudo systemctl restart {service_name}"
    status: "sudo systemctl status {service_name}"
    rollback_extra: "sudo systemctl stop {service_name}"

# === Services (per environment, fully dynamic) ===
# Generator emits services based on foundation.data + backend stack.
# Add/remove services here after generation to match your project.
# ⟪ SERVICES_BLOCK ⟫

# === Test Credentials (per environment) ===
# Generator emits credentials based on foundation.auth.roles.
# Defaults to ["admin", "user"] if no roles declared.
# Replace placeholder passwords before going to production.
# ⟪ CREDENTIALS_BLOCK ⟫

# === CrossAI CLIs (adaptive — 0 to N) ===
# 0 = skip CrossAI | 1 = single review | 2 = fast-fail | 3+ = full consensus
# Generator emits CLI list based on foundation.team_size:
#   solo  → 1 CLI  (Claude — cost-aware)
#   2-5   → 2 CLIs (Codex + Claude — fast-fail consensus)
#   6+    → 3 CLIs (Codex + Gemini + Claude — full consensus, quality priority)
# ⟪ CROSSAI_CLIS_BLOCK ⟫

# === Paths (relative to project root) ===
paths:
  planning: ".vg"
  phases: ".vg/phases"
  screenshots: "apps/web/e2e/screenshots"
  e2e_tests: "apps/web/e2e"
  flow_tests: "apps/web/e2e/flows"
  generated_tests: "apps/web/e2e/generated"  # NEW: codegen output

# === Code Patterns (for test-scan component detection) ===
code_patterns:
  api_routes: "apps/api/src/modules"
  web_pages: "apps/web/src/pages"
  state_signals: ["STATES", "STATUS", "LIFECYCLE", "TRANSITIONS"]
  deep_signals: ["useMutation", "api.", "useAuth", "router.push"]
  interactive_signals: ["onClick", "onChange"]

# === Scan Patterns (for audit element counting) ===
# Grep patterns to count UI elements per file. Stack-specific.
# Review step 1b uses patterns matching config.scan_patterns.stack
scan_patterns:
  stack: "typescript"   # typescript | rust | go | python

  typescript:
    modals: ['[Mm]odal', 'Dialog', 'useDisclosure', 'isOpen.*modal']
    tabs: ['[Tt]ab[Pp]anel', 'TabList', 'role="tabpanel"']
    tables: ['<table', '<Table', 'DataTable', 'useTable']
    forms: ['<form', '<Form', 'useForm', 'handleSubmit']
    dropdowns: ['<select', 'Select', 'Dropdown', 'Combobox']
    actions: ['onClick', 'onSubmit', 'handleClick', 'handleDelete']
    tooltips: ['[Tt]ooltip', 'title=']

  rust:
    handlers: ['async fn \w+\(.*Request', '#\[(get|post|put|delete|patch)\]']
    structs: ['#\[derive.*Deserialize', 'pub struct \w+']
    tests: ['#\[tokio::test\]', '#\[test\]', '#\[cfg\(test\)\]']
    impls: ['^impl\s+\w+', 'pub fn \w+']

  go:
    # TODO: fill when using Go stack
    # handlers: ['func \(.*\) (Get|Post|Put|Delete)\w+\(']
    # structs: ['^type \w+ struct \{']
    # tests: ['func Test\w+\(t \*testing\.T\)']

  python:
    # TODO: fill when using Python stack
    # handlers: ['@(app|router)\.(get|post|put|delete)']
    # schemas: ['class \w+\(BaseModel\)']
    # tests: ['def test_\w+\(']

# === Playwright MCP Server ===
# Auto-claimed via lock manager at ~/.claude/playwright-locks/playwright-lock.sh
# Available servers: playwright1, playwright2, playwright3, playwright4, playwright5 (all with unique user-data-dir)
# Each session auto-claims first free server — no manual config needed.
# To check status: bash ~/.claude/playwright-locks/playwright-lock.sh status

# === Session Model (for cross-role E2E testing) ===
# Each role gets its own browser context (parallel, not logout/login).
session_model:
  strategy: "multi-context"        # multi-context | single-context
  # multi-context: each role = new browser context (recommended)
  # single-context: logout/login between roles (legacy)

# === Monorepo Apps (for selective build/test) ===
# Generator emits apps block based on foundation.monorepo.tool + detected workspaces.
# Add/remove entries after generation as needed.
# ⟪ APPS_BLOCK ⟫

# === Critical Domains (idempotency check — test.md step 5b-2) ===
# Comma-separated keywords. Review + test treat these as must-pass domains.
critical_domains: "{{critical_domains}}"

# === Visual Integrity Checks (Phase 2.5 in /vg:review) ===
visual_checks:
  enabled: true
  font_check: true              # check @font-face loaded via document.fonts API
  text_encoding_check: true     # ALWAYS ON — detect garbled UTF-8 (???, â€™, Ã©). No toggle — too critical
  overflow_check: true          # detect hidden content overflow (scrollHeight > clientHeight)
  responsive_viewports: [1920, 375]
  z_index_check: true
  sidebar_width: 256
  header_height: 64
  # L4 (4-layer pixel pipeline) — design-fidelity SSIM gate at /vg:review.
  # Compares live UI screenshots against design-extract baseline PNGs per
  # view in RUNTIME-MAP. Drift % > threshold = BLOCK (override --allow-design-drift).
  # Lower number = stricter. Tune by project: marketing pages 2.0, dense
  # internal tools 5.0–8.0 to absorb dynamic data without false positives.
  design_fidelity_threshold_pct: 5.0
  # L5 (P19 D-05) — design-fidelity-guard: separate-model semantic adjudication
  # at /vg:build step 9. Spawns Haiku zero-context with design PNG + commit
  # diff to catch component-level drift that pixel-similar UI happens to miss.
  # OFF by default — flip true after dogfood. Requires `claude` CLI on PATH.
  vision_self_verify:
    enabled: false
    model: "claude-haiku-4-5-20251001"
    timeout_s: 30

# === Commit-msg design citation gate (P19 D-08) ===
# Enforces PR #15 L-002 rule at the commit boundary: FE files require
# "Per design/{slug}.png", "Design: no-asset (reason)", or "Design: refactor-only"
# in the commit body. Disable per-project if your repo doesn't track design assets.
design_citation:
  enabled: true

# === Design Asset Pipeline ===
design_assets:
  # paths/output_dir/handlers — already documented above.
  # P19 D-02 — view-decomposition: spawns vision-capable Opus per slug,
  # produces VIEW-COMPONENTS.md (canonical per-slug component list). UI-SPEC
  # step 2b6 + L5 design-fidelity-guard consume it. Cost ~$0.05-0.10/slug
  # Opus vision; cache by PNG mtime so re-runs are free.
  view_decomposition:
    enabled: false
    model: "claude-opus-4-7"
    min_components_per_slug: 3

# === Performance Budgets ===
# Generic defaults — adjust per project SLA.
perf_budgets:
  api_response_p95_ms: 200
  page_load_s: 3

# === Pipeline Routing ===
# Which pipeline step to use based on what changed
routing:
  # Files matching these patterns → full pipeline (browser discovery needed)
  ui_patterns: ["apps/web/**", "apps/api/src/modules/*/routes*"]
  # Files matching these patterns → skip browser discovery (API/backend only)
  backend_only_patterns: ["apps/workers/**", "apps/api/src/modules/*/services*"]
  # Domain gates — these goal categories must be 100% (not 80%)
  critical_goal_domains: ["auth", "billing", "compliance"]

# === Review Phase 3 Fix Routing (v1.9.1 R2) ===
# 3-tier severity-based fix routing in /vg:review Phase 3:
#   MINOR     → inline main agent fix (fast, no context switch)
#   MODERATE  → spawn Sonnet subagent (isolated, cheaper, bounded)
#   MAJOR     → escalate to user (requires human judgment)
# Severity classified by: fix_scope (files), blast_radius (callers), contract changes.
review:
  # ─── Scanner spawn mode (v1.9.4 R3.3 — mobile sequential gate) ──────
  # Controls how Phase 2b-2 spawns Haiku scanner agents:
  #   auto       → derive from profile (mobile-*=sequential, cli/library=none, web-*=parallel)
  #   parallel   → up to 5 concurrent agents (web default, multi-browser contexts)
  #   sequential → 1 agent at a time (mobile iOS sim / Android emu = single instance)
  #   none       → skip UI scan entirely (cli-tool, library)
  # Override: force sequential even for web projects if CI has limited browser slots.
  scanner_spawn_mode: "auto"

  # ─── v1.14.0+ Cổng 100% + autonomous fix-first ──────────────────────
  # Triết lý: rà soát phải đạt 100% goals (READY + DEFERRED + MANUAL).
  # BLOCKED = 0. Không grey zone. Không defer sang /vg:test.
  gate_threshold: 100                   # cứng — chỉ --legacy-mode mới dùng gate_threshold_legacy
  gate_threshold_legacy: 80             # chỉ áp với --legacy-mode flag, expire sau 2 milestones
  try_infra_start: true                 # auto chạy config.environments.{env}.infra_start khi gặp INFRA_PENDING; trap infra_stop ở EXIT
  fix_loop_on_unreachable: true         # UNREACHABLE:bug → spawn fix agent inline (không chỉ log)
  auto_amend_additive: true             # UNREACHABLE:scope additive amendment auto-apply; destructive vẫn ask
  block_cross_phase_without_tag: true   # UNREACHABLE:cross-phase mà goal không có tag depends_on_phase → hard block

  fix_routing:
    enabled: true                       # master switch — false disables Phase 3 routing (fallback: all inline)
    inline_threshold_loc: 20            # fixes <= N lines stay inline (main agent)
    spawn_threshold_loc: 150            # fixes > N lines but < escalate threshold → spawn Sonnet
    escalate_threshold_loc: 500         # fixes > N lines → block + escalate to user
    escalate_on_contract_change: true   # API-CONTRACTS.md touched → always escalate (no inline)
    escalate_on_critical_domain: true   # touches critical_goal_domains → always escalate
    max_iterations: 3                   # max fix iterations before giving up (3-strike rule)

# === Design System (v1.10.0 R4 — NEW) ==========================
# Integrates getdesign.md ecosystem DESIGN.md (58 brand variants: Stripe,
# Linear, Vercel, Apple, Ferrari, BMW, Claude, Cursor, ...).
#
# Multi-design support: project can have multiple design systems per role.
# Resolution priority (highest first):
#   1. Phase-level:   .planning/phases/XX/DESIGN.md
#   2. Role-level:    .planning/design/{role}/DESIGN.md
#   3. Project-level: .planning/design/DESIGN.md
#
# Commands:
#   /vg:design-system --browse              # list 58 brands grouped
#   /vg:design-system --import stripe       # project-level DESIGN.md
#   /vg:design-system --import linear --role=dsp-admin  # role-specific
#   /vg:design-system --view --role=dsp-admin
#   /vg:design-system --validate            # check code hex vs DESIGN.md palette
design_system:
  enabled: true
  source_repo: "Meliwat/awesome-design-md-pre-paywall"
  project_level: ".planning/design/DESIGN.md"
  role_dir: ".planning/design"
  phase_override_pattern: "{phase_dir}/DESIGN.md"
  inject_on_build: true       # build task prompts receive DESIGN.md content
  validate_on_review: true    # /vg:review Phase 2.5 checks hex drift

# === Design Assets (for /vg:design-extract) ===
# Normalizer converts any format → PNG + optional structural ref
# AI vision consumes screenshots directly — no markdown prose middleman
design_assets:
  # Glob patterns for design assets (relative to repo root unless absolute).
  # Leave empty list if project has no static design references.
  paths: []
    # - "designs/*.html"                                # static HTML mockups
    # - "designs/*.png"                                 # raw mockup images
    # - "designs/*.fig"                                 # Figma exports
  # Per-format handler (auto-detected by extension, override here if needed)
  handlers:
    html: playwright_render     # Playwright headless → PNG + cleaned HTML
    htm:  playwright_render
    png:  passthrough           # direct copy
    jpg:  passthrough
    jpeg: passthrough
    webp: passthrough
    fig:  figma_fallback        # MCP if available, else user export manually
    pb:   penboard_render       # PenBoard headless render via Electron/CanvasKit
    xml:  pencil_xml            # Pencil CLI export (fallback skip)
  # Capture interactive states (click triggers → modal/hover screenshots)
  render_states: true
  # Output directory (per-project)
  output_dir: ".planning/design-normalized"
  # Haiku scanner tuning (see /vg:design-extract)
  max_parallel_haiku: 5
  normalizer_timeout_sec: 60

# === Test Strategy (v1.9.1 R1 — surface-driven test taxonomy) ===
# Routes each TEST-GOALS goal to a runner based on `surface:`.
# 5 defaults ship with VG; project may extend with custom surfaces (e.g. rtb-engine).
test_strategy:
  default_surface: "ui"
  surfaces:
    ui:
      runner: "ui-playwright"
      detect_keywords: ["click", "form", "modal", "page", "tab", "button", "sidebar", "dropdown", "submit", "badge", "snippet"]
    ui-mobile:
      runner: "ui-mobile-maestro"
      detect_keywords: ["tap", "swipe", "screen", "navigation", "gesture"]
    api:
      runner: "api-curl"
      detect_keywords: ["endpoint", "POST", "GET", "PUT", "DELETE", "PATCH", "returns", "status code", "/api/", "/postback", "/health", "/audience", "/event", "response contains", "401", "403", "404", "409", "422", "429", "502", "HMAC", "sig"]
    data:
      runner: "data-dbquery"
      runner_config: { client: "auto" }
      detect_keywords: ["row", "count", "aggregate", "table", "collection", "document", "ClickHouse", "MongoDB", "Redis", "SET", "SISMEMBER", "TTL", "partition", "materialized view", "conversion_events", "dedup"]
    time-driven:
      runner: "time-faketime"
      detect_keywords: ["after", "expires", "cron", "schedule", "window", "interval", "hourly", "daily", "attribution window", "grace period", "days ago", "last 24h"]
    integration:
      runner: "integration-mock"
      detect_keywords: ["downstream", "postback", "webhook", "callback", "external service", "produced to", "Kafka", "vollx.conversion", "topic", "tracker", "redirect 301"]
  auto_threshold: 0.80
  haiku_threshold: 0.50

# === CRUD Surface Contract (v2.12+) ===
# Blueprint writes CRUD-SURFACES.md as the parent contract for resource list,
# read, create, update, delete behavior. Existing paging/list/security
# descriptions become extension packs under this contract.
crud_surface_contract:
  enabled: true
  schema_version: "1"
  missing_contract: "block"          # block | warn; block for new feature phases
  require_for_profiles: ["web-fullstack", "web-frontend-only", "web-backend-only", "mobile-app", "mobile-fullstack"]
  extension_packs:
    interactive_controls: true       # TEST-GOALS web filter/search/sort/paging URL-state details
    security_checks: true            # CSRF/XSS/object-auth/rate-limit/mass-assignment details
    performance_budget: true         # list p95 + mutation p95 budget references
  web:
    require_url_state_for_lists: true
    require_table_headers: true
    require_loading_empty_error: true
  mobile:
    require_deep_link_state: true
    require_tap_target_min_px: 44
    require_offline_network_state: true
  backend:
    require_filter_sort_allowlist: true
    require_idempotency_for_mutations: true
    require_audit_log_for_delete: true

# === Contract Format (for API-CONTRACTS.md generation + compile check) ===
# Controls what code block format blueprint 2b outputs
contract_format:
  type: "{{contract_format.type}}"        # zod_code_block | openapi_yaml | typescript_interface | pydantic_model
  compile_cmd: "{{contract_format.compile_cmd}}"   # run after extract to validate contract syntax
  generated_types_path: "packages/types/contracts"             # where executor should import from (if codegen applies)
  error_response_shape: "{ error: { code: string, message: string } }"  # project-wide error body

# === Build Gates (for post-wave strict verify) ===
# Commands run after each wave completes. Fail = BLOCK next wave.
build_gates:
  typecheck_cmd: "{{build_gates.typecheck_cmd}}"
  build_cmd: "{{build_gates.build_cmd}}"
  test_unit_cmd: "{{build_gates.test_unit_cmd}}"      # can be empty "" if test_unit_required=false
  # L3 build-time visual gate — leave default unless your dev server runs
  # on a non-standard host/port. The gate auto-SKIPs if server is down,
  # Playwright/Node missing, or pixelmatch+PIL not installed.
  dev_server_url: "http://localhost:{{frontend.port}}"
  visual_threshold_pct: 5.0          # max pixel diff % vs design baseline before BLOCK
  test_unit_required: true                    # if true AND cmd empty + src/ changed → BLOCK with guidance
  contract_verify_grep: true                  # reuse existing contract_verify_grep from env-commands.md
  # Gate 5 — goal-test binding. Every task with <goals-covered>G-XX</goals-covered>
  # must commit a test file referencing goal id or success-criteria keyword.
  #   strict → BLOCK wave on any mismatch (TDD-style enforcement)
  #   warn   → log mismatches, continue (soft gate — rely on phase-end check in /vg:test)
  #   off    → skip entirely
  goal_test_binding: "warn"
  # Phase-end goal-test binding (runs in /vg:test after codegen). Always strict
  # because at phase end EVERY goal must be covered by some test (unit or generated E2E).
  goal_test_binding_phase_end: "strict"

  # === Adaptive typecheck (v1.14.3+) ===
  # Auto-picks full/narrow/bootstrap mode per package based on size + OOM history.
  # Handles the "cold tsc OOM on large apps" scenario universally.
  typecheck_adaptive:
    enabled: true
    # Weighted file count thresholds (weighted = ts + tsx*3, JSX is RAM-heavy):
    small_threshold: 300        # below → always full incremental (fast cold)
    large_threshold: 1200       # above → try bootstrap, then narrow fallback
    # Heap in MB for regular incremental vs bootstrap (cold) runs
    heap_mb: 8192
    heap_bootstrap_mb: 16384
    # Cache bootstrap strategy when tsbuildinfo missing:
    #   auto     → detect tsgo → else watch → else chunked
    #   watch    → tsc -w background, poll for cache, kill on success
    #   tsgo     → native tsc reimpl (requires: npm i -g @typescript/native-preview)
    #   chunked  → split tsconfig.include into N-file chunks, seed cache over runs
    #   skip     → never bootstrap, always fall back to narrow
    cache_bootstrap_strategy: auto
    cache_bootstrap_watch_timeout_s: 300
    cache_bootstrap_chunk_size: 400
    # OOM history file per pkg (gitignored): .tsbuildinfo-oom-log
    # 7-day rolling window. One recent OOM → narrow mode auto.

# === Semantic Regression (cross-module caller analysis) ===
# Prevents "fix A breaks B" by injecting downstream caller context into executor.
# Blueprint-time: warning in PLAN.md. Build-time: <downstream_callers> block per task.
semantic_regression:
  enabled: true
  track_schemas: true        # Zod/Pydantic/interface exports
  track_functions: true      # named function exports
  track_endpoints: true      # API route paths (FE → BE)
  track_collections: true    # DB collection names
  track_topics: true         # Kafka topic names
  track_css_classes: false   # apps/web shared classNames (opt-in — noisy)
  track_i18n_keys: false     # apps/web t('key.path') (opt-in — noisy)
  scope_apps: ["apps/api", "apps/web", "packages"]  # where to grep — adjust per monorepo layout

# === Graphify Knowledge Graph (token-saving sibling/caller context) ===
# When enabled, /vg:build queries graph.json via MCP for sibling + caller context
# instead of grep-dumping file contents. Saves ~50% executor tokens for these blocks.
# When disabled OR graph missing, falls back to grep-based path (build-caller-graph.py).
# Setup: pip install graphifyy[mcp] && graphify install && graphify .
# ─── v1.12.6 patch: 11 fields workflow reads but /vg:project missed ─────
# (See .vg/CONFIG-AUDIT.md for full audit. v1.13.0 will move to template-based generation.)

# DB name (used by build, review, test for collection/table naming)
db_name: "{{db_name}}"

# Dev server failure detection (used by /vg:build dev-stack startup)
dev_failure_log_tail: 80
dev_failure_patterns:
  - "error TS[0-9]+"
  - "ESLint:"
  - "ENOENT"
  - "EADDRINUSE"
  - "Cannot find module"
  - "FATAL"
  - "panic:"
dev_os_limits:
  max_processes: 200
  max_open_files: 4096
dev_process_markers:
  - "{{package_manager}} dev"
  - "vite"
  - "next dev"
  - "turbo run dev"

# Flat alias (some skills read this directly, not via contract_format.error_response_shape)
error_response_shape: "{ error: { code: string, message: string } }"

# i18n configuration (used by scope/build/review for translation key extraction)
i18n:
  enabled: {{i18n.enabled}}
  default_locale: "{{i18n.default_locale}}"
  key_function: "t"               # i18next style: t('key.path')
  locale_dir: "apps/web/src/i18n/locales"

# Flat ports (alias — worktree_ports.base also exists for offset support)
ports:
  database: {{ports.database}}

# Rationalization guard model (gate-skip adjudicator subagent)
rationalization_guard:
  model: "haiku"                  # haiku (cheap) for routine, opus for security/architecture gates

# Multi-surface declaration (single-surface default — if multi-surface added, see Multi-Surface block above)
surfaces:
  web:
    type: "{{profile}}"
    paths: ["apps/web", "apps/api"]
    stack: "{{frontend.framework}}+{{backend.framework}}"

# ─── End v1.12.6 patch ──────────────────────────────────────────────────

# ─── v1.13.2: UI Component Map (Bản đồ cây component) ──────────────────────
# Tool: .claude/scripts/generate-ui-map.mjs — phân tích AST React/Vue/Svelte,
# vẽ cây component dạng ASCII + JSON. Gate: .claude/scripts/verify-ui-structure.py
# so sánh cây thực tế sau build vs UI-MAP.md (bản vẽ đích do planner viết).
ui_map:
  enabled: true                                # true = auto-generate UI map ở blueprint + verify drift ở build
  src: "{{frontend.src_dir}}"                  # vd "apps/web/src" — dir chứa component (đọc đệ quy)
  entry: "{{frontend.entry_file}}"             # vd "apps/web/src/App.tsx" — file gốc để bắt đầu dò import
  router: ""                                   # hint: expo-router|next-app|react-router|tanstack-router|none
                                               # để trống = tự dò qua import signature
  aliases:                                     # path alias (phải khớp tsconfig.paths)
    - "@={{frontend.src_dir}}"                 # vd "@=apps/web/src"
  max_missing: 0                               # số component trong UI-MAP kế hoạch nhưng không có trong code → BLOCK nếu > N
  max_unexpected: 3                            # số component trong code nhưng không có trong UI-MAP → BLOCK nếu > N
  layout_advisory: true                        # true = chỉ warn khi class layout khác, không BLOCK

graphify:
  enabled: true                                # true = use graphify | false = grep fallback
  graph_path: "graphify-out/graph.json"        # snapshot location relative to repo root
  mcp_server: "graphify"                       # MCP server name (matches .mcp.json registration)
  fallback_to_grep: true                       # if graph missing/stale, fallback grep instead of BLOCK
  rebuild_on_phase_start: true                 # v2.12.4: /vg:build cold/stale-rebuilds when enabled
  staleness_warn_commits: 50                   # warn if N commits since last build (suggest manual rebuild)
  block_on_stale: false                        # v1.12.5: when true, config-loader exits 1 if stale (fail-closed). Default false = warn-only (backward compat).
  ignore_patterns:                             # written to .graphifyignore
    - ".planning/"
    - ".claude/"
    - "node_modules/"
    - "dist/"
    - "build/"
    - "target/"
    - ".next/"
    - "graphify-out/"
    - "test-results/"
    - "playwright-report/"
    - "*.generated.*"
    - "coverage/"

# === Plan Validation Gate (blueprint step 2d) ===
# Runtime prompt asks user; this is fallback for --auto mode
plan_validation:
  default_mode: "strict"                      # strict | default | loose | custom
  # Thresholds: % of items allowed to miss before BLOCK
  thresholds:
    strict:  { decisions_miss_pct: 10, goals_miss_pct: 15, endpoints_miss_pct: 5 }
    default: { decisions_miss_pct: 20, goals_miss_pct: 30, endpoints_miss_pct: 10 }
    loose:   { decisions_miss_pct: 40, goals_miss_pct: 50, endpoints_miss_pct: 20 }
  custom_thresholds: { decisions_miss_pct: 10, goals_miss_pct: 15, endpoints_miss_pct: 5 }
  max_auto_fix_iterations: 3                  # AI retries to patch plan before giving up

# === Commit Message Hook ===
commit_msg_hook:
  enabled: true
  require_contract_cite: true                 # commit touching src/ must cite API-CONTRACTS or CONTEXT
  pattern: '^(feat|fix|refactor|test|chore|docs)\([0-9]+(\.[0-9]+)*-[0-9]+\): '

# === Console Noise Filter (review Phase 2 — suppress known infra errors) ===
# Console errors matching these patterns are classified as INFRA_NOISE, not code bugs.
# Review Phase 2 discovery: only alert on errors NOT matching these patterns.
# Pattern format: regex applied to console error text (case-insensitive).
console_noise:
  enabled: true
  patterns:
    - "net::ERR_CONNECTION_REFUSED"                 # generic unreachable service
    - "Failed to fetch.*health"                     # health endpoint during startup
  # Custom per-project patterns (add yours here):
  # - "your-noisy-pattern"

# === Infrastructure Dependencies (per phase goal classification) ===
# Maps service names to their availability check.
# TEST-GOALS.md goals with `infra_deps: [service]` auto-classify as INFRA_PENDING
# when the listed service's check fails on current environment.
# Review Phase 4 skips INFRA_PENDING goals instead of marking them BLOCKED.
infra_deps:
  # Generator emits services block based on foundation.data + foundation.cache + backend.queue.
  # Add more service entries after generation if project has custom infra.
  services:
    # ⟪ INFRA_DEPS_BLOCK ⟫
    no_ui_e2e:
      check_local: "false"
      check_sandbox: "false"
      label: "No-UI E2E (backend integration test required, not /vg:test)"
    test_fixture_required:
      check_local: "false"
      check_sandbox: "false"
      label: "Test fixture (time-travel/bulk insert/curated UA vectors)"
  # How review Phase 4 handles goals with unmet infra_deps:
  # - "skip" = don't count toward pass/fail gate (recommended)
  # - "warn" = count as WARN, not BLOCK
  # - "block" = strict — require all infra (use for production readiness)
  unmet_behavior: "skip"

# ─── F3 Override Debt Register (2026-04-17) ─────────────────────────
debt:
  register_path: ".planning/OVERRIDE-DEBT.md"
  auto_expire_days: 14
  blocking_severity: ["critical"]
  severities:
    critical:
      - "--allow-missing-commits"
      - "--override-reason"
      - "--override-regressions"
      - "--force-accept-with-debt"
    high:
      - "--allow-no-tests"
      - "--skip-design-check"
      - "--allow-intermediate"
      - "--skip-context-rebuild"
    medium:
      - "--skip-crossai"
      - "--skip-research"
      - "--allow-deferred"

# ─── F6 i18n Narration (2026-04-17) ─────────────────────────────────
narration:
  locale: "vi"
  fallback_locale: "en"
  string_table_path: ".claude/commands/vg/_shared/narration-strings.yaml"

# ─── F8 Scope Adversarial Answer Challenger (v1.9.1 R3, 2026-04-17) ─
# Spawns isolated OPUS subagent after every user answer in /vg:scope
# rounds and /vg:project foundation rounds. Challenges via 8 lenses (v1.9.3):
# contradiction / hidden_assumption / edge_case / foundation_conflict /
# security / performance / failure_mode / integration_chain.
# Model upgraded Haiku→Opus in v1.9.3 R3.2 — scope needs reasoning depth
# to find real gaps, not superficial checks.
# Disable for rapid prototyping projects where challenge friction > value.
scope:
  adversarial_check: true               # master switch — set false to skip all challenges
  adversarial_model: "opus"             # subagent model (zero parent context) — v1.9.3: upgraded from haiku
  adversarial_max_rounds: 3             # loop guard: max challenges per phase (incl. /vg:project run)
  adversarial_skip_trivial: true        # skip Y/N single-word confirmations (helper auto-detects)

  # ─── v1.9.3 R3.2 Dimension Expander ────────────────────────────────
  # Proactive gap-finding at END of each round (1 call/round, not per-answer).
  # Separate from answer-challenger: expander asks "what dimensions have we NOT
  # covered?" whereas challenger asks "is this specific answer wrong?".
  dimension_expand_check: true          # master switch — set false to skip all round-end expansions
  dimension_expand_model: "opus"        # Opus for reasoning depth (dimensions require senior-engineer breadth)
  dimension_expand_max: 6               # loop guard: max expansions per phase (5 rounds + 1 deep probe)

# ─── F7 Telemetry (2026-04-17) ──────────────────────────────────────
telemetry:
  enabled: true
  path: ".planning/telemetry.jsonl"
  retention_days: 90
  sample_rate: 1.0
  event_types_skip: []

# ─── F9 Security Register (2026-04-17) ──────────────────────────────
security:
  register_path: ".planning/SECURITY-REGISTER.md"
  taxonomy: ["stride", "owasp_top_10", "custom"]
  severity_scale: ["info", "low", "medium", "high", "critical"]
  decay_policy:
    mitigated_archive_days: 90
    unresolved_escalate_days: 30
  composite_rules:
    - name: "auth-weakness + privilege-escalation"
      patterns: ["broken-auth", "broken-access"]
      resulting_severity: "critical"
      phases_min: 2
    - name: "info-disclosure-chain"
      patterns: ["info-disclosure", "sensitive-data"]
      resulting_severity: "high"
      phases_min: 2
  accept_gate:
    block_on_open: ["critical"]
  milestone_audit:
    required_before_milestone_complete: true

# ─── Session Lifecycle (2026-04-17) ─────────────────────────────────
session:
  stale_hours: 1                    # state files older than N hours → auto-sweep at session_start
  port_sweep_on_start: true         # kill orphan dev servers on declared ports before pre-flight

# ─── P5 Phase Profiles (v1.9.2, 2026-04-17) ─────────────────────────
# Orthogonal to R1 surface taxonomy — surface routes GOALS to runners,
# phase profile routes PHASES to pipelines.
# Detection rules live in _shared/lib/phase-profile.sh (pure bash function).
# Override per-phase by adding `phase_profile: <name>` at top of SPECS.md.
phase_profiles:
  feature:
    required_artifacts: [SPECS.md, CONTEXT.md, PLAN.md, API-CONTRACTS.md, TEST-GOALS.md, CRUD-SURFACES.md, SUMMARY.md]
    skip_artifacts: []
    review_mode: "full"                       # browser discover + surface routing
    test_mode: "full"                         # per-surface runners
    goal_coverage: "TEST-GOALS"
  infra:
    required_artifacts: [SPECS.md, PLAN.md, SUMMARY.md]
    skip_artifacts: [TEST-GOALS.md, CRUD-SURFACES.md, API-CONTRACTS.md, CONTEXT.md, RUNTIME-MAP.json]
    review_mode: "infra-smoke"                # parse success_criteria bash → run each → READY/FAILED
    test_mode: "infra-smoke"                  # same as review
    goal_coverage: "SPECS.success_criteria"   # implicit goals S-01..S-NN from checklist
  hotfix:
    required_artifacts: [SPECS.md, PLAN.md, SUMMARY.md]
    skip_artifacts: [TEST-GOALS.md, CRUD-SURFACES.md, API-CONTRACTS.md, CONTEXT.md]
    inherits_from: "parent_phase"             # read parent_phase TEST-GOALS if exists
    review_mode: "delta"                      # focus on delta changes + parent goals re-verify
    test_mode: "parent-goals-regression"
    goal_coverage: "parent_phase.TEST-GOALS"
  bugfix:
    required_artifacts: [SPECS.md, PLAN.md, SUMMARY.md]
    skip_artifacts: [API-CONTRACTS.md, CONTEXT.md]
    review_mode: "regression"
    test_mode: "issue-specific"
    goal_coverage: "SPECS.fixes_bug"
  migration:
    required_artifacts: [SPECS.md, PLAN.md, SUMMARY.md, ROLLBACK.md]
    skip_artifacts: [API-CONTRACTS.md, TEST-GOALS.md, CRUD-SURFACES.md, RUNTIME-MAP.json]
    review_mode: "schema-verify"
    test_mode: "schema-roundtrip"
    goal_coverage: "SPECS.migration_plan"
  docs:
    required_artifacts: [SPECS.md]
    skip_artifacts: [CONTEXT.md, PLAN.md, API-CONTRACTS.md, TEST-GOALS.md, CRUD-SURFACES.md, RUNTIME-MAP.json, SUMMARY.md]
    review_mode: "link-check"
    test_mode: "markdown-lint"
    goal_coverage: "SPECS.doc_targets"

# ─── v1.14.0+ Kiểm thử tiền kiểm + deep-probe ──────────────────────
# Phase 0 preflight: phát hiện data thiếu (goal_sequences rỗng, light-mode review,
# ...), tự chọn path A (heal) / B (synth) / C (defer) theo heuristic, chỉ ask khi
# confidence < threshold. Deep-probe sinh edge-case variants sau codegen happy-path.
test:
  # Phase 0 preflight + autonomous path select
  preflight_enabled: true
  preflight_smart_recommend: true           # heuristic (phase age + regression flags + session budget)
  preflight_autoheal_log: ".vg/phases/{phase}/TEST-AUTOHEAL-LOG.md"

  # Codegen
  codegen_enabled: true
  codegen_output_dir: "apps/web/e2e/generated/{phase}"
  codegen_skip_deferred: true               # DEFERRED goals không codegen (target phase chưa deploy)
  codegen_manual_annotate_skip: true        # MANUAL goals → generate skeleton với .skip() + comment

  # Deep-probe (edge-case variants beyond happy path)
  deep_probe_enabled: true
  deep_probe_variants_per_goal: 3
  deep_probe_model_primary: "sonnet"        # 5× rẻ hơn Opus, đủ cho pattern-match codegen
  deep_probe_adversarial_chain:             # ưu tiên từ trên xuống, skip entry nếu CLI không available
    - "codex"                               # 1st — GPT-5.4 mạnh cho edge-case synth
    - "gemini"                              # fallback nếu codex CLI missing
    - "claude-haiku"                        # fallback cuối — rẻ, không diversification nhưng vẫn cross-check
  deep_probe_adversarial_skip_if_unavailable: false
  deep_probe_escalate_to_opus_on_conflict: true
  deep_probe_max_opus_escalations_per_phase: 2
  deep_probe_variant_fail_behavior:
    hard: "block"
    advisory: "warn"

# ─── v1.14.0+ Sổ tay triển khai (Deploy Runbook lifecycle) ──────────
deploy_runbook:
  auto_draft_from_log: true
  lessons_auto_inject: true
  lessons_tolerate_empty: true
  required_sections:
    - "prerequisites"
    - "deploy_sequence"
    - "verification"
    - "rollback"
    - "lessons"
    - "references"
    - "infra_snapshot"
  aggregator_outputs:
    - ".vg/DEPLOY-LESSONS.md"
    - ".vg/ENV-CATALOG.md"
    - ".vg/DEPLOY-FAILURE-REGISTER.md"
    - ".vg/DEPLOY-RECIPES.md"
    - ".vg/DEPLOY-PERF-BASELINE.md"
    - ".vg/SMOKE-PACK.md"
  perf_regression_threshold: 1.5
  pending_lessons_review: ".vg/PENDING-LESSONS-REVIEW.md"

# ─── v1.14.0+ Autonomous-first principle ────────────────────────────
autonomous:
  confidence_threshold: 0.70
  auto_decision_log: ".vg/AUTO-DECISION-LOG.md"
  pending_user_review_queue: ".vg/PENDING-USER-REVIEW.md"
  auto_amend_additive_allowed: true
  auto_amend_destructive_allowed: false
  auto_decision_log_reversible: true

# ─── v1.14.0+ Ngôn ngữ output (Việt hoá mặc định) ───────────────────
language:
  primary: "vi"
  legacy_en_allowed: false
  lint_enabled: true
  lint_forbidden_terms_extra: []
  lint_allowed_context:
    - "command_identifier"
    - "file_name"
    - "format_identifier"
    - "code_identifier"

# ─── v1.14.0+ Cross-phase DEFERRED tracker ──────────────────────────
cross_phase_deps:
  register_path: ".vg/CROSS-PHASE-DEPS.md"
  reverify_on_target_accept: true
  milestone_gate_block_unflipped: true

# ─── v1.14.0+ REGRESSION-DEFERRED registry ──────────────────────────
regression_deferred:
  register_path: ".vg/REGRESSION-DEFERRED-REGISTER.md"
  milestone_warn_threshold_pct: 20
  milestone_block_threshold_pct: 50

# ─── F11 Visual Regression (2026-04-17) ─────────────────────────────
visual_regression:
  enabled: false                   # opt-in per project (requires pip install pixelmatch pillow)
  tool: "auto"
  threshold_pct: 2.0
  baseline_dir: "apps/web/e2e/screenshots/baseline"
  current_dir: "apps/web/e2e/screenshots"
  diff_output_dir: ".planning/phases/{phase}/visual-diffs"
  report_path: ".planning/phases/{phase}/visual-diff.json"
  ignore_regions: []
  auto_promote_on_first_run: true
---

# ─── Bug Reporting (v1.11.0+) ──────────────────────────────────────
# Auto-detect workflow bugs + send to vgflow GitHub issues for triage.
# Default points to upstream vgflow repo. Flip `enabled: false` if your project
# doesn't want automatic bug telemetry to the upstream maintainer.
bug_reporting:
  enabled: false                                    # opt-in per project
  repo: "vietdev99/vgflow"                          # upstream vgflow repo
  severity_threshold: "minor"
  auto_send_minor: true
  redact_project_paths: true
  redact_project_names: true
  auto_assign: "vietdev99"
  default_labels: ["bug-auto", "needs-triage"]
  max_per_session: 5
  queue_path: ".claude/.bug-reports-queue.jsonl"
  sent_cache_path: ".claude/.bug-reports-sent.jsonl"
