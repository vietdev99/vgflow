---
name: "vg-blueprint"
description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
metadata:
  short-description: "Plan + API contracts + verify + CrossAI review — 4 sub-steps before build"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI, translate tool calls using the table + patterns below.

### Tool mapping table

| Claude tool | Codex equivalent | Notes |
|---|---|---|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) | For multi-select, format as "1. Option / 2. Option" and parse reply |
| Task (agent spawn) | `codex exec --model <model> "<prompt>"` subprocess | Foreground: `codex exec ... > /tmp/out.txt`. Parallel: launch N subprocesses + `wait`. See "Agent spawn" below |
| TaskCreate/TaskUpdate/TodoWrite | N/A — use inline markdown headers + status narration | Codex does not have a persistent task tail UI. Write `## ━━━ Phase X: step ━━━` in stdout instead |
| Monitor | Bash loop with `echo` + `sleep 3` polling | Codex streams stdout directly, no separate monitor channel |
| ScheduleWakeup | N/A — Codex is one-shot; user must re-invoke | Skill must tolerate single-execution model; no sleeping |
| WebFetch | `curl -sfL <url>` or `gh api <path>` | For GitHub URLs prefer `gh` for auth handling |
| mcp__playwright{1-5}__* | See "Playwright MCP" below | Playwright MCP tools ARE available in Codex's main orchestrator |
| mcp__graphify__* | `python -c "from graphify import ..."` inline | Graphify CLI/module works identically in Codex |
| mcp__context7__*, mcp__exa__*, mcp__firecrawl__* | Skip or fall back to WebFetch | Only available via SDK; not bundled in Codex CLI |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively | No adapter needed |

### Agent spawn (Task → codex exec)

Claude Code spawns isolated agents via `Task(subagent_type=..., prompt=...)`. Codex equivalent:

```bash
# Single agent, foreground (wait for completion + read output)
codex exec --model gpt-5 "<full isolated prompt>" > /tmp/agent-result.txt 2>&1
RESULT=$(cat /tmp/agent-result.txt)

# Multiple agents, parallel (Claude's pattern of 1 message with N Task calls)
codex exec --model gpt-5 "<prompt 1>" > /tmp/agent-1.txt 2>&1 &
PID1=$!
codex exec --model gpt-5 "<prompt 2>" > /tmp/agent-2.txt 2>&1 &
PID2=$!
wait $PID1 $PID2
R1=$(cat /tmp/agent-1.txt); R2=$(cat /tmp/agent-2.txt)
```

**Critical constraints when spawning:**
- Subagent inherits working directory + env vars, but **no MCP server access** (Codex exec spawns fresh CLI instance without `--mcp` wired). Subagent CANNOT call `mcp__playwright*__`, `mcp__graphify__`, etc.
- Model mapping for this project: `models.planner` opus → `gpt-5`, `models.executor` sonnet → `gpt-4o`, `models.scanner` haiku → `gpt-4o-mini` (or project-configured equivalent). Check `.claude/vg.config.md` `models` section for actual values and adapt.
- Timeout: wrap in `timeout 600s codex exec ...` to prevent hung subagents.
- Return schema: if skill expects structured JSON back, prompt subagent with "Return ONLY a single JSON object with keys: {...}". Parse with `jq` or `python -c "import json,sys; ..."`.

### Playwright MCP — orchestrator-only rule

Playwright MCP tools (`mcp__playwright1__browser_navigate`, `_snapshot`, `_click`, etc.) ARE available to the main Codex orchestrator (same MCP servers as Claude Code). **BUT subagents spawned via `codex exec` do NOT inherit MCP access** — they are fresh CLI instances.

Implication for skills using Haiku scanner pattern (scanner spawns → uses Playwright):
- **Claude model:** spawn haiku agent with prompt → agent calls `mcp__playwright__` tools directly
- **Codex model:** TWO options:
  1. **Orchestrator-driven:** main orchestrator calls Playwright tools + passes snapshots/results to subagent as text → subagent returns instructions/analysis only (no tool calls). Slower but preserves parallelism benefit.
  2. **Single-agent:** orchestrator runs scanner workflow inline (no spawn). Simpler but no parallelism; suitable for 1-2 view scans but slow for 14+ views.

Default: **single-agent inline** unless skill explicitly documents the orchestrator-driven pattern for that step.

### Persistence probe (Layer 4) — execution model

For review/test skills that verify mutation persistence:
- Main orchestrator holds Playwright session (claimed via lock manager)
- Pre-snapshot + submit + refresh + re-read all run in orchestrator Playwright calls (not spawned)
- If skill delegates analysis to subagent, orchestrator must capture snapshots + pass text to subagent; subagent returns verdict JSON `{persisted: bool, pre: ..., post: ...}`

### Lock manager (Playwright)

Same as Claude:
```bash
SESSION_ID="codex-${skill}-${phase}-$$"
PLAYWRIGHT_SERVER=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
```

Pool name in Codex: `codex` (separate from Claude's `claude` pool). Lock manager handles both without collision.

## Invocation

This skill is invoked by mentioning `$vg-blueprint`. Treat all user text after `$vg-blueprint` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **CONTEXT.md required** — must exist before blueprint. No CONTEXT = BLOCK.
2. **4 sub-steps in order** — 2a Plan → 2b Contracts → 2c Verify → 2d CrossAI. No skipping.
3. **API contracts BEFORE build** — contracts are INPUT to build, not POST-build check.
4. **Verify is grep-only** — step 2c uses no AI. Pure grep diff. Fast (<5 seconds).
5. **Max 400 lines per agent** — planner gets ~300, contract gen gets ~200.
6. **ORG 6-dimension gate** — plan MUST answer: Infra, Env, Deploy, Smoke, Integration, Rollback.
7. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action, run:
   `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
   Preflight: `create_task_tracker` runs `filter-steps.py --command blueprint.md --profile $PROFILE --output-ids`
   and MUST create tasks matching exactly that list (count check). Step 3_complete verifies markers.
</rules>

<objective>
Step 2 of V5 pipeline. Heaviest planning step — 4 sub-steps produce PLAN.md + API-CONTRACTS.md, both verified.

Pipeline: specs → scope → **blueprint** → build → review → test → accept

Sub-steps:
- 2a: PLAN — GSD planner creates tasks + acceptance criteria (~300 lines)
- 2b: CONTRACTS — Generate API contracts from code/specs (~200 lines)
- 2c: VERIFY 1 — Grep diff contracts vs code/specs (no AI, <5 sec)
- 2d: CROSSAI REVIEW — 2 CLIs review plan + contracts + context
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

<step name="0_amendment_preflight">
## Step 0: Scope Amendment Preflight (v1.14.1+ NEW)

Before planning, enforce any `config_amendments_needed` locked during /vg:scope (e.g. new surfaces proposed in Round 2 via surface-gap detector). Running blueprint with stale config → tasks spawn against wrong surface paths → silent failure downstream.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/amendment-preflight.sh"

# Mode from flag
AMEND_MODE="block"   # default
if [[ "$ARGUMENTS" =~ --apply-amendments ]]; then
  AMEND_MODE="apply"
elif [[ "$ARGUMENTS" =~ --skip-amendment-check ]]; then
  AMEND_MODE="warn"
fi

amendment_block_if_pending "${PHASE_DIR}" ".claude/vg.config.md" "$AMEND_MODE"
preflight_rc=$?

if [ $preflight_rc -ne 0 ]; then
  echo ""
  echo "Retry options:"
  echo "  /vg:blueprint ${PHASE_NUMBER} --apply-amendments     # auto-apply to config"
  echo "  /vg:blueprint ${PHASE_NUMBER} --skip-amendment-check # debt mode"
  exit 1
fi

# If amendments were applied, commit the config change before proceeding
if [ "$AMEND_MODE" = "apply" ]; then
  if ! git diff --quiet .claude/vg.config.md 2>/dev/null; then
    git add .claude/vg.config.md
    git commit -m "config(${PHASE_NUMBER}): apply scope amendments

Auto-applied via /vg:blueprint ${PHASE_NUMBER} --apply-amendments.
See PHASE_DIR/CONTEXT.md scope decisions for rationale."
  fi
fi
```

Scanner is authoritative: reads `PIPELINE-STATE.steps.scope.config_amendments_needed[]` array (populated by `/vg:scope` step 5). Enrichment pulls surface name + paths + stack from decision YAML snippet in CONTEXT.md. Generic (non-surface) amendments require manual edit — preflight blocks, user edits, re-runs.

**Rationale:** surfaces config drives multi-surface gate, design-system lookup, multi-platform E2E routing. Missing surface → silent workflow misalignment. Forcing apply before tasks spawn ensures planner + executor see correct config.
</step>

<step name="1_parse_args">
Extract from `$ARGUMENTS`: phase_number (required), plus optional flags:
- `--skip-research`, `--gaps`, `--reviews`, `--text` — pass through to GSD planner
- `--crossai-only` — skip 2a/2b/2c, run only 2d (CrossAI review). Requires PLAN*.md + API-CONTRACTS.md to exist.
- `--skip-crossai` — run full blueprint but skip CrossAI review in 2d-6 (deterministic gate only). Faster + cheaper. Use when phase is small/iterative and CrossAI third-opinion adds little.
- `--from=2b` / `--from=2c` / `--from=2d` — resume from specific sub-step. Skip prior sub-steps (require their artifacts to exist).

Validate: phase exists. Determine `$PHASE_DIR`.

**Skip logic:**
- `--crossai-only` → jump directly to step 2d_crossai_review
- `--from=2b` → skip 2a, start at 2b_contracts (PLAN*.md must exist)
- `--from=2c` → skip 2a+2b, start at 2c_verify (PLAN*.md + API-CONTRACTS.md must exist)
- `--from=2d` → same as `--crossai-only`
</step>

<step name="create_task_tracker">
**Create sub-step task list for progress tracking.**

Create tasks for each sub-step in this command:
```
TaskCreate: "2a. Plan — GSD planner"           (activeForm: "Creating plans...")
TaskCreate: "2b. Contracts — API contracts"     (activeForm: "Generating API contracts...")
TaskCreate: "2b5. Test goals — generate goals"   (activeForm: "Generating TEST-GOALS...")
TaskCreate: "2b7. Flow detect — FLOW-SPEC"      (activeForm: "Detecting business flows...")
TaskCreate: "2c. Verify 1 — grep diff"          (activeForm: "Verifying contracts (grep)...")
TaskCreate: "2d. CrossAI review"               (activeForm: "Running CrossAI review...")
```

Store task IDs for updating status as each sub-step runs.
Each sub-step should: `TaskUpdate: status="in_progress"` at start, `status="completed"` at end.
</step>

<step name="2_verify_prerequisites">
**Phase profile detection (P5, v1.9.2) — done BEFORE prerequisite check.**

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  SKIP_ARTIFACTS=$(phase_profile_skip_artifacts "$PHASE_PROFILE")
  export PHASE_PROFILE SKIP_ARTIFACTS
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"
else
  PHASE_PROFILE="feature"
  SKIP_ARTIFACTS=""
fi
```

**CONTEXT.md required ONLY for feature profile** (other profiles skip scope + CONTEXT).

```bash
needs_context=true
for a in $SKIP_ARTIFACTS; do
  [ "$a" = "CONTEXT.md" ] && needs_context=false
done

if [ "$needs_context" = "true" ] && [ ! -f "${PHASES_DIR}/${phase_dir}/CONTEXT.md" ]; then
  echo "⛔ CONTEXT.md not found for Phase ${PHASE_NUMBER} (profile=${PHASE_PROFILE} requires it)."

  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="blueprint.2-verify-prereq"
    BR_GATE_CONTEXT="Feature profile requires CONTEXT.md (scope decisions). User must run /vg:scope first."
    BR_EVIDENCE=$(printf '{"profile":"%s","missing":"CONTEXT.md"}' "$PHASE_PROFILE")
    BR_CANDIDATES='[]'
    BR_RESULT=$(block_resolve "blueprint-no-context" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "blueprint-no-context" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
  fi
  echo "   Run first: /vg:scope ${PHASE_NUMBER}"
  exit 1
fi

# For non-feature profiles, skip scope and contracts generation.
# Blueprint for infra/hotfix/bugfix/migration/docs only produces PLAN (and ROLLBACK for migration).
if [ "$PHASE_PROFILE" != "feature" ]; then
  echo "ℹ Blueprint profile-aware mode: PHASE_PROFILE=${PHASE_PROFILE} — bỏ qua (skip) sub-steps 2b, 2b5, 2b7 (contracts/test-goals/flow)."
  echo "   Chỉ tạo PLAN.md (+ ROLLBACK.md nếu migration). CrossAI review vẫn áp dụng để kiểm tra PLAN quality."
  export BLUEPRINT_PROFILE_SHORT_CIRCUIT=true
fi
```

**Legacy fallback (profile detection unavailable):** Check `${PHASES_DIR}/{phase_dir}/CONTEXT.md` exists.

Missing → BLOCK:
```
CONTEXT.md not found for Phase {N}.
Run first: /vg:scope {phase}
```

**Design-extract auto-trigger (fixes G1):**

```bash
# If project has design assets configured, ensure they're normalized BEFORE planning
# (so R4 granularity check + executor design_context have something to point at)
if [ -n "${config.design_assets.paths[0]}" ]; then
  DESIGN_OUT="${config.design_assets.output_dir:-${PLANNING_DIR}/design-normalized}"
  DESIGN_MANIFEST="${DESIGN_OUT}/manifest.json"

  # Stale check: any source asset newer than manifest?
  NEEDS_EXTRACT=false
  if [ ! -f "$DESIGN_MANIFEST" ]; then
    NEEDS_EXTRACT=true
    REASON="manifest missing"
  else
    # Compare mtimes — if any asset newer than manifest, re-extract
    for pattern in "${config.design_assets.paths[@]}"; do
      if find $pattern -newer "$DESIGN_MANIFEST" 2>/dev/null | grep -q .; then
        NEEDS_EXTRACT=true
        REASON="assets changed since last extract"
        break
      fi
    done
  fi

  if [ "$NEEDS_EXTRACT" = true ]; then
    echo "Design assets detected, manifest $REASON. Auto-running /vg:design-extract..."
    # --auto flag inherits; manual run lets user approve
    if [[ "$ARGUMENTS" =~ --auto ]]; then
      SlashCommand: /vg:design-extract --auto
    else
      AskUserQuestion: "Extract design assets now? (Required for <design-ref> linkage)"
        Options: [Yes (recommended), Skip — build without design]
      # If Yes → SlashCommand: /vg:design-extract
    fi
  fi
fi
```

Skip gracefully when `design_assets.paths` empty (pure backend phase).
</step>

<step name="2a_plan">
## Sub-step 2a: PLAN

**CONTEXT.md format validation (quick, <5 sec):**

Before planning, verify CONTEXT.md has the enriched format scope.md should have produced:

```bash
CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"
# Check enriched format: at least some P{phase}.D-XX (or legacy D-XX) decisions should have Endpoints or Test Scenarios
HAS_ENDPOINTS=$(grep -c "^\*\*Endpoints:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
HAS_TESTS=$(grep -c "^\*\*Test Scenarios:\*\*" "$CONTEXT_FILE" 2>/dev/null || echo 0)
DECISION_COUNT=$(grep -cE "^### (P[0-9.]+\.)?D-" "$CONTEXT_FILE" 2>/dev/null || echo 0)

if [ "$DECISION_COUNT" -eq 0 ]; then
  echo "⛔ CONTEXT.md has 0 decisions. Run /vg:scope ${PHASE_NUMBER} first."
  exit 1
fi

if [ "$HAS_ENDPOINTS" -eq 0 ] && [ "$HAS_TESTS" -eq 0 ]; then
  echo "⚠ CONTEXT.md may be legacy format (no Endpoints/Test Scenarios sub-sections)."
  echo "  Blueprint will proceed but may produce less accurate plans."
  echo "  For best results: /vg:scope ${PHASE_NUMBER} (re-scope with enriched format)"
fi

echo "CONTEXT.md: ${DECISION_COUNT} decisions, ${HAS_ENDPOINTS} with endpoints, ${HAS_TESTS} with test scenarios"
```

Create execution plans using VG-native planner (self-contained, no GSD delegation).

**⛔ BUG #2 fix (2026-04-18): Auto-rebuild graphify BEFORE planner spawn.**

Mirrors `vg:build` step 4 auto-rebuild logic. Without this, planner plans against
stale graph (we observed 46h / 140 commits stale at audit) → planner references
symbols that no longer exist → tasks fabricated → executor fails or produces wrong code.

```bash
if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
  # Use graphify-safe wrapper — verifies mtime advances + retries on stuck rebuild
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"

  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')

  echo "Blueprint: graphify ${COMMITS_SINCE} commits since last build"

  if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
    vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "blueprint-phase-${PHASE_NUMBER}" || {
      echo "⚠ Planner will see stale graph — expect weaker task/sibling suggestions"
    }
  else
    echo "Graphify: up to date (0 commits since last build)"
  fi
fi
```

**Pre-spawn graphify context build (MANDATORY when `$GRAPHIFY_ACTIVE=true`):**

Before spawning the planner, extract structural context from graphify so the planner can
plan with blast-radius awareness instead of grep-only guesses. Without this, planners
produce `<edits-*>` annotations missing 60-90% of true downstream impact.

```bash
GRAPHIFY_BRIEF="${PHASE_DIR}/.graphify-brief.md"

if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
  # 1. God nodes (orchestrator MUST query via mcp__graphify__god_nodes — Claude tool call):
  #    Save top-20 god nodes ordered by community_size + edge_count. These are
  #    "touch with care" sentinels — planner MUST flag any task editing them.

  # 2. Communities relevant to phase:
  #    Grep CONTEXT.md endpoints + file paths → for each, query
  #    mcp__graphify__get_node + get_neighbors → collect community_id set.
  #    Save community summaries.

  # 3. Existing-symbol map for endpoints in CONTEXT (avoid re-introducing names):
  #    Grep CONTEXT.md "GET /api/..." patterns → query mcp__graphify__query_graph
  #    {"node_type":"route","path":"/api/v1/auth/login"} → emit "EXISTS at file:line"
  #    so planner annotates as REUSED, not NEW.

  # 4. Brief format (markdown, ≤150 lines, planner reads as injected context):
  cat > "$GRAPHIFY_BRIEF" <<EOF
# Graphify brief — Phase ${PHASE_NUMBER} structural context

Generated from graphify-out/graph.json (${GRAPH_NODE_COUNT} nodes, ${GRAPH_EDGE_COUNT} edges, mtime ${GRAPH_MTIME_HUMAN}).

## God nodes (touch with care)
$GOD_NODES_TABLE

## Phase-relevant communities
$COMMUNITY_TABLE

## Existing endpoints/symbols (REUSE, don't re-create)
$EXISTING_SYMBOLS_TABLE

## Sibling files (likely co-edited)
$SIBLINGS_TABLE
EOF
else
  # Fallback: emit a stub brief explaining graphify unavailable
  cat > "$GRAPHIFY_BRIEF" <<EOF
# Graphify brief — UNAVAILABLE
Graph not built or stale. Planner falls back to grep-only structural awareness.
Run: cd \$REPO_ROOT && \${PYTHON_BIN} -m graphify update .
EOF
fi
```

**Orchestrator note:** mcp__graphify__god_nodes / get_node / get_neighbors / query_graph
are Claude TOOL CALLS, not bash commands. Invoke directly via tool use after the
bash block computes the variable inputs (CONTEXT endpoint list, CONTEXT file path list).
DO NOT shell-out to graphify CLI — MCP tool round-trip is the supported path.

**v1.14.0+ C.5 — deploy_lessons injection** (silent, NO AskUserQuestion):

Trước khi spawn planner, extract lessons + env vars liên quan services mà phase này tác động, tiêm vào prompt planner dưới `<deploy_lessons>` block. Planner MUST reference khi đề cập ORG dimensions 3 (Deploy) + 4 (Smoke) + 6 (Rollback).

```bash
DEPLOY_LESSONS_BRIEF="${PHASE_DIR}/.deploy-lessons-brief.md"
DEPLOY_LESSONS_FILE=".vg/DEPLOY-LESSONS.md"
ENV_CATALOG_FILE=".vg/ENV-CATALOG.md"

if [ -f "$DEPLOY_LESSONS_FILE" ] || [ -f "$ENV_CATALOG_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$PHASE_DIR" "$DEPLOY_LESSONS_FILE" "$ENV_CATALOG_FILE" "$DEPLOY_LESSONS_BRIEF" <<'PY'
import re, sys
from pathlib import Path

phase_dir = Path(sys.argv[1])
lessons_file = Path(sys.argv[2])
env_file = Path(sys.argv[3])
brief_out = Path(sys.argv[4])

# 1. Infer services phase này touches (same heuristic aggregator)
service_hints = [
    ("apps/api",        [r"\bapi\b", r"fastify", r"modules?/", r"REST\s+API"]),
    ("apps/web",        [r"\bweb\b", r"\bdashboard\b", r"\bpage\b", r"\bReact\b", r"\bFE\b", r"\badvertiser\b", r"\bpublisher\b", r"\badmin\b"]),
    ("apps/rtb-engine", [r"\brtb[_-]?engine\b", r"\baxum\b", r"\bbid\s+request\b", r"\bauction\b"]),
    ("apps/workers",    [r"\bworkers?\b", r"\bconsumer\b", r"\bkafka\s+consumer\b", r"\bcron\b"]),
    ("apps/pixel",      [r"\bpixel\b", r"\bpostback\b", r"\btracking\b"]),
    ("infra/clickhouse",[r"\bclickhouse\b", r"\bOLAP\b", r"\banalytic\b"]),
    ("infra/mongodb",   [r"\bmongo(?:db)?\b", r"\bcollection\b"]),
    ("infra/kafka",     [r"\bkafka\b", r"\btopic\b", r"\bpartition\b"]),
    ("infra/redis",     [r"\bredis\b", r"\bcache\b"]),
]
services_touched = set()
for fname in ("SPECS.md", "CONTEXT.md"):
    f = phase_dir / fname
    if not f.exists():
        continue
    text = f.read_text(encoding="utf-8", errors="ignore").lower()
    for svc, pats in service_hints:
        for pat in pats:
            if re.search(pat, text, re.I):
                services_touched.add(svc)
                break

# Also infer from phase name
name_lower = phase_dir.name.lower()
for svc, pats in service_hints:
    for pat in pats:
        if re.search(pat, name_lower, re.I):
            services_touched.add(svc)
            break

# 2. Extract relevant lessons from DEPLOY-LESSONS View A (by service)
lessons_by_service = {}
if lessons_file.exists():
    text = lessons_file.read_text(encoding="utf-8", errors="ignore")
    # Parse View A: `### {service}` followed by `- **Phase X:** lesson`
    current_svc = None
    for line in text.splitlines():
        svc_m = re.match(r"^### ((?:apps|infra)/\S+)\s*$", line)
        if svc_m:
            current_svc = svc_m.group(1)
            lessons_by_service.setdefault(current_svc, [])
            continue
        # Stop at View B
        if line.startswith("## View B"):
            break
        if current_svc:
            bullet = re.match(r"^-\s+\*\*Phase ([\d.]+):\*\*\s+(.+)$", line)
            if bullet:
                lessons_by_service[current_svc].append((bullet.group(1), bullet.group(2)))

# 3. Extract env vars touched services from ENV-CATALOG
relevant_env = []
if env_file.exists():
    text = env_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        m = re.match(r"^\|\s*`(\w+)`\s*\|\s*([\d.]+)\s*\|\s*([^|]+)\s*\|", line)
        if not m:
            continue
        name, phase_added, service_list = m.groups()
        service_list = service_list.strip()
        # Match any service token trong cột Service với services_touched
        svc_tokens = re.split(r",\s*", service_list)
        if any(t.strip() in services_touched for t in svc_tokens):
            relevant_env.append((name, phase_added, service_list))

# 4. Write brief
out = ["# Deploy Lessons Brief — Phase-specific context cho planner", ""]
out.append(f"**Services touched:** {', '.join(sorted(services_touched)) or '(chưa xác định)'}")
out.append("")

if lessons_by_service:
    out.append("## Lessons từ phases trước (service-filtered)")
    out.append("")
    printed = 0
    for svc in sorted(services_touched):
        items = lessons_by_service.get(svc, [])
        if not items:
            continue
        out.append(f"### {svc}")
        for pid, lesson in items:
            out.append(f"- **Phase {pid}:** {lesson}")
            printed += 1
        out.append("")
    if printed == 0:
        out.append("_(Không có lesson nào liên quan service này.)_")
        out.append("")
else:
    out.append("_(DEPLOY-LESSONS.md chưa có lesson nào — phase đầu của v1.14.0+ flow.)_")
    out.append("")

if relevant_env:
    out.append("## Env vars liên quan (từ ENV-CATALOG)")
    out.append("")
    out.append("| Name | Added Phase | Service |")
    out.append("|---|---|---|")
    for name, pid, svc in relevant_env[:20]:  # limit 20 để prompt gọn
        out.append(f"| `{name}` | {pid} | {svc} |")
    if len(relevant_env) > 20:
        out.append(f"| _... và {len(relevant_env) - 20} env var nữa — xem ENV-CATALOG đầy đủ_ | | |")
    out.append("")
else:
    out.append("_(ENV-CATALOG trống hoặc không có env var nào map tới services của phase này.)_")
    out.append("")

out.append("## Hướng dẫn cho planner")
out.append("")
out.append("- ORG dimension 3 (Deploy): reference lessons về build/restart timing + pitfalls nếu có.")
out.append("- ORG dimension 4 (Smoke): include smoke check commands (xem SMOKE-PACK.md) cho services touched.")
out.append("- ORG dimension 6 (Rollback): nếu phase trước đã document rollback steps cùng service → reuse pattern.")
out.append("- Env vars liệt kê ở trên: nếu phase cần thêm var mới, tuân format reload/rotation/storage đã established.")
out.append("")

brief_out.write_text("\n".join(out), encoding="utf-8")
print(f"✓ deploy_lessons brief: {brief_out} (services={len(services_touched)}, lessons={sum(len(v) for v in lessons_by_service.values())}, env_vars={len(relevant_env)})")
PY
else
  echo "ℹ DEPLOY-LESSONS.md / ENV-CATALOG.md chưa tồn tại — skip deploy_lessons brief."
fi
```

Spawn planner agent với VG-specific rules + graphify brief + deploy_lessons brief:
```
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    <graphify_brief>
    @${PHASE_DIR}/.graphify-brief.md
    </graphify_brief>

    <deploy_lessons>
    @${PHASE_DIR}/.deploy-lessons-brief.md (if exists — v1.14.0+ C.5)
    </deploy_lessons>

    <specs>
    @${PHASE_DIR}/SPECS.md
    </specs>

    <context>
    @${PHASE_DIR}/CONTEXT.md
    </context>

    <contracts>
    @${PHASE_DIR}/API-CONTRACTS.md (if exists)
    </contracts>

    <goals>
    @${PHASE_DIR}/TEST-GOALS.md (if exists)
    </goals>

    <config>
    profile: ${PROFILE}
    typecheck_cmd: ${config.build_gates.typecheck_cmd}
    contract_format: ${config.contract_format.type}
    phase: ${PHASE_NUMBER}
    phase_dir: ${PHASE_DIR}
    graphify_active: ${GRAPHIFY_ACTIVE}
    </config>

    Create PLAN.md for phase ${PHASE_NUMBER}. Follow vg-planner-rules exactly.

    GRAPHIFY USAGE (when graphify_active=true):
    - graphify_brief lists god nodes + existing symbols + sibling files
    - For EVERY task touching code, set <edits-*> attributes (REQUIRED, not optional)
      so the post-plan caller-graph script (step 2a5) can compute blast radius
    - When task touches a god node listed in brief, prefix description with
      "BLAST-RADIUS: god node — ripple to N callers expected" and include
      mitigation note (gradual rollout / feature flag / regression suite)
    - When task lists an endpoint in <edits-endpoint>, check brief's existing
      symbols table — if found, mark as REUSED-MODIFY not NEW-CREATE

    DEPLOY_LESSONS USAGE (v1.14.0+ C.5, when brief exists):
    - Nếu deploy_lessons có service-specific lessons → reference TRỰC TIẾP trong task
      description của ORG dimensions 3/4/6. VD: "Rebuild incremental tsc (Phase 7.12
      lesson: force --skip-lib-check if node_modules freshly cleared)".
    - Nếu deploy_lessons có env vars liên quan → tasks add new env var PHẢI tuân
      format reload/rotation/storage đã establish trong ENV-CATALOG (90-day vault
      cho secrets, config-stable cho URLs, tuning-knob cho TTL/cache).
    - Không có lessons liên quan → OK, ignore block.

    Output: ${PHASE_DIR}/PLAN.md with waves, task attributes, goal coverage.
```

Wait for completion. Verify `PLAN.md` exists in `${PHASE_DIR}`.

**Post-plan ORG check** (mandatory):
Read all PLAN*.md files. Check that the 6 ORG dimensions are addressed:

| # | Dimension | How to check |
|---|-----------|-------------|
| 1 | Infra | Any task mentions installing/configuring services? |
| 2 | Env | Any task mentions new env vars, configs, secrets? |
| 3 | Deploy | Is there a task for deploying to target? |
| 4 | Smoke | Is there a task for verifying it's alive? |
| 5 | Integration | Is there a task for testing with existing services? |
| 6 | Rollback | Is there a recovery path documented? |

Missing dimension → add note to plan (auto-fix for minor, ask user for major).

**Post-plan granularity check** (mandatory — execute sát blueprint):

Parse all tasks from PLAN*.md. For each task, validate:

| Rule | Requirement | Severity |
|------|-------------|----------|
| R1: Exact file path | Task specifies `{file-path}` or equivalent (not vague "can be in ...") | HIGH |
| R2: Contract reference | If task touches API (has verb POST/GET/PUT/DELETE OR creates endpoint handler) → must cite `<contract-ref>` pointing to API-CONTRACTS.md line range | HIGH |
| R3: Goals covered | Task has `<goals-covered>[G-XX, G-YY]</goals-covered>` when applicable. If task is pure infra/tooling: `no-goal-impact` acceptable. | MED |
| R4: Design reference | If task builds FE page/component AND config.design_assets is non-empty → must cite `<design-ref>` pointing to design-specs or design-screenshots. | MED |
| R5: Scope size | Estimated LOC delta ≤ 250 lines. If larger → recommend split into sub-tasks. | MED |

**⛔ R2 contract-ref format (tightened 2026-04-17 — MUST match regex, not free-form):**

```
<contract-ref>API-CONTRACTS.md#{endpoint-id} lines {start}-{end}</contract-ref>
```

Regex: `^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$`

Valid examples:
- `<contract-ref>API-CONTRACTS.md#post-api-sites lines 45-80</contract-ref>`
- `<contract-ref>API-CONTRACTS.md#get-api-campaigns-id lines 130-175</contract-ref>`

Invalid (will fail commit-msg Gate 2b and build citation resolver):
- `<contract-ref>API-CONTRACTS.md#post-sites</contract-ref>` — missing line range
- `<contract-ref>API-CONTRACTS.md line 45-80</contract-ref>` — missing #endpoint-id
- `<contract-ref>contracts.md#post-sites lines 45-80</contract-ref>` — wrong filename

Validation (inline in plan checker):
```bash
for ref in $(grep -oE '<contract-ref>[^<]+</contract-ref>' "$PLAN_FILE"); do
  body=$(echo "$ref" | sed 's/<[^>]*>//g')
  if ! echo "$body" | grep -qE '^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$'; then
    echo "⛔ R2 malformed contract-ref: '$body' — expected 'API-CONTRACTS.md#{id} lines X-Y'"
    R2_MALFORMED=$((R2_MALFORMED + 1))
  fi
done
```

Malformed R2 is treated as HIGH (not MED) — downstream build citation check parses this string literally.

**Inject warnings into PLAN.md as HTML comments** (non-intrusive):
```markdown
## Task 04: Add POST /api/sites handler

**Scope:** apps/api/src/modules/sites/routes.ts

<!-- plan-warning:R2 missing <contract-ref> — task creates endpoint but doesn't cite API-CONTRACTS.md line range. Add: <contract-ref>API-CONTRACTS.md#post-api-sites line 45-80</contract-ref> -->

Implementation: ...
```

**Warning budget:**
- > 50% tasks have HIGH warnings → return to planner with feedback for regeneration (loop to 2a)
- > 30% tasks have MED warnings → proceed but surface in step 2d (CrossAI review catches + Auto-fix loop)

Display:
```
Plan granularity check:
  Total tasks: {N}
  R1 file-path missing: {N}
  R2 contract-ref missing: {N}  (HIGH → {block|warn})
  R3 goals-covered missing: {N}
  R4 design-ref missing: {N}
  R5 scope >250 LOC: {N}
  Warnings injected: {total}
```
</step>

<step name="2a5_cross_system_check">
## Sub-step 2a5: CROSS-SYSTEM CHECK (grep, no AI, <10 sec)

Scan the existing codebase and prior phases to detect conflicts/overlaps BEFORE writing contracts and code. This prevents phase isolation blindness.

**Check 1: Route conflicts**
```bash
# Grep all registered routes in existing code
EXISTING_ROUTES=$(grep -r "router\.\(get\|post\|put\|delete\|patch\)" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'/[^']+'" | sort)
# Compare with endpoints planned in CONTEXT.md decisions
# Flag: route already exists → plan must UPDATE, not CREATE
```

**Check 2: Schema/model field conflicts**
```bash
# Grep existing model/schema definitions
EXISTING_SCHEMAS=$(grep -r "z\.object\|Schema\|interface\s" "$API_ROUTES" --include="*.ts" --include="*.js" -l 2>/dev/null)
# For each model this phase touches (from CONTEXT.md):
#   Check if schema already has fields that conflict with planned changes
```

**Check 3: Shared component impact**
```bash
# Grep components this phase's pages import
# For each shared component: find ALL pages that import it
# Flag: shared component change affects N other pages outside this phase
grep -r "import.*from.*components" "$WEB_PAGES" --include="*.tsx" --include="*.jsx" -h 2>/dev/null | sort | uniq -c | sort -rn | head -20
```

**Check 4: Prior phase overlap**
```bash
# Read SUMMARY*.md from recent phases (last 3-5 phases)
# Check if any SUMMARY mentions same files/modules this phase plans to touch
for summary in $(ls ${PHASES_DIR}/*/SUMMARY*.md 2>/dev/null | tail -5); do
  grep -l "$(basename ${PHASE_DIR})" "$summary" 2>/dev/null
done
```

**Check 5: Database collection conflicts**
```bash
# Grep all collection references in existing code
grep -r "collection\(\|\.find\|\.insertOne\|\.updateOne" "$API_ROUTES" --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'[^']+'" | sort | uniq -c | sort -rn
# Flag: this phase adds fields to collection another phase also modifies
```

**Output:** Inject warnings into PLAN.md as `<!-- cross-system-warning: ... -->` markers.

```
Cross-System Check:
  Routes: {N} potential conflicts
  Schemas: {N} shared fields
  Components: {N} shared, affecting {M} other pages
  Prior phases: {N} overlaps
  Collections: {N} conflicts
  
  Warnings injected into PLAN.md: {count}
```

No block — warnings only. AI planner should address each warning in task descriptions.

### Cross-system check 2: Caller graph (semantic regression)

Build `.callers.json` — maps each PLAN task's `<edits-*>` symbols to all downstream files using them. Build step 4e consumes this; commit-msg hook enforces caller update or citation.

```bash
if [ "${config.semantic_regression.enabled:-true}" = "true" ]; then
  # ⛔ BUG #1 fix (2026-04-18): MUST pass --graphify-graph when active.
  # Without flag, script falls back to grep-only (misses path-alias imports
  # like `@/hooks/X`, misses cross-monorepo symbol callers).
  GRAPHIFY_FLAG=""
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
    --phase-dir "${PHASE_DIR}" \
    --config .claude/vg.config.md \
    $GRAPHIFY_FLAG \
    --output "${PHASE_DIR}/.callers.json"

  # Inject per-task warnings into PLAN.md listing downstream callers
  # Planner should ensure tasks updating shared symbols know their blast radius
  CALLER_COUNT=$(jq '.affected_callers | length' "${PHASE_DIR}/.callers.json")
  TOOLS_USED=$(jq -r '.tools_used | join(",")' "${PHASE_DIR}/.callers.json")
  echo "Semantic regression: tracked ${CALLER_COUNT} downstream callers (tools: ${TOOLS_USED})"

  # Sanity check: if graphify active but tools_used doesn't include 'graphify',
  # something went wrong — graph file unreadable or schema mismatch.
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ] && ! echo "$TOOLS_USED" | grep -q graphify; then
    echo "⚠ GRAPHIFY ENRICHMENT FAILED — graph active but caller-graph used grep-only."
    echo "  Inspect: ${PHASE_DIR}/.callers.json + check graphify-out/graph.json validity"
    echo "  Run: ${PYTHON_BIN} -c 'import json; json.load(open(\"$GRAPHIFY_GRAPH_PATH\"))'"
  fi
fi
```

Planner should convert each warning into task annotations: `<edits-schema>X</edits-schema>` so the graph can track changes reliably.

**⚠ Recurring problem (Phase 13 retro):** when planner produces 22 tasks but only 3 have `<edits-*>` annotations, the caller script can only compute blast-radius for those 3. The other 19 silently get zero callers — appearing safe when they may have many. See `vg-planner-rules.md` for the rule that EVERY code-touching task MUST have at least one `<edits-*>` attribute.
</step>

<step name="2b_contracts">
## Sub-step 2b: CONTRACTS (strict format — executable code block)

Read `.claude/skills/api-contract/SKILL.md` — Mode: Generate.
Read `config.contract_format` from `.claude/vg.config.md`:
- `type`: zod_code_block | openapi_yaml | typescript_interface | pydantic_model
- `compile_cmd`: how to validate syntax (used in 2c2)

**Input:** CONTEXT.md + code at `config.code_patterns.api_routes` and `config.code_patterns.web_pages`

**Process:**
1. Grep existing schemas in codebase (match config.contract_format type)
2. Grep HTML/JSX forms and tables (if web_pages path exists)
3. Extract endpoints from CONTEXT.md decisions — supports both formats:
   - **VG-native bullet format** (from /vg:scope): `- POST /api/v1/sites (auth: publisher, purpose: create site)`
     Match regex: `^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - **Legacy header format** (from manual/older CONTEXT.md): `### POST /api/v1/sites`
     Match regex: `^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)`
   - Collect all matched `(method, path)` pairs into endpoint list for contract generation
4. Cross-reference endpoint list with CONTEXT decisions (each decision with data/CRUD → endpoint)
5. AI drafts contract for any endpoint without existing schema

**STRICT OUTPUT FORMAT — each endpoint MUST have executable code block:**

Example for `contract_format.type == "zod_code_block"`:

**4 blocks per endpoint. Blocks 1-3 = executor copies. Block 4 = test consumes.**

````markdown
### POST /api/sites

**Purpose:** Create new site (publisher role)

```typescript
// === BLOCK 1: Auth + middleware (COPY VERBATIM to route handler) ===
// Executor: paste this EXACT line in the route registration
export const postSitesAuth = [requireAuth(), requireRole('publisher'), rateLimit(30)];
```

```typescript
// === BLOCK 2: Request/Response schemas (COPY VERBATIM — same as before) ===
export const PostApiSitesRequest = z.object({
  domain: z.string().url().max(255),
  name: z.string().min(1).max(100),
  categoryId: z.string().uuid(),
});
export type PostApiSitesRequest = z.infer<typeof PostApiSitesRequest>;

export const PostApiSitesResponse = z.object({
  id: z.string().uuid(),
  domain: z.string(),
  status: z.enum(['pending', 'active', 'rejected']),
  createdAt: z.string().datetime(),
});
export type PostApiSitesResponse = z.infer<typeof PostApiSitesResponse>;
```

```typescript
// === BLOCK 3: Error responses (COPY VERBATIM to error handler) ===
// Executor: use these EXACT shapes in catch blocks. FE reads error.message for toast.
export const PostSitesErrors = {
  400: { error: { code: 'VALIDATION_FAILED', message: 'Invalid site data' } },
  401: { error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } },
  403: { error: { code: 'FORBIDDEN', message: 'Publisher role required' } },
  409: { error: { code: 'DUPLICATE_DOMAIN', message: 'Domain already registered' } },
} as const;
// FE toast rule: always show `response.data.error.message` — never HTTP status text
```

```typescript
// === BLOCK 4: Valid test sample (for idempotency + smoke tests) ===
// Executor: do NOT copy this block into app code. Used by test.md step 5b-2.
export const PostSitesSample = {
  domain: "https://test-idem.example.com",
  name: "Idempotency Test Site",
  categoryId: "00000000-0000-0000-0000-000000000001",
} as const;
```

**Mutation evidence:** `sites collection count +1`
**Cross-ref tasks:** Task {N} (BE handler), Task {M} (FE form)
````

**4 blocks per endpoint. Blocks 1-3 = executor copies verbatim. Block 4 = test consumes (step 5b-2). Executor does NOT write auth, schema, or error handling from scratch.**

Format per type (all 4 blocks adapt to format):
- `zod_code_block` → `\`\`\`typescript` with z.object, requireRole, error map, sample const
- `openapi_yaml` → `\`\`\`yaml` with security schemes, schemas, error responses, example values
- `typescript_interface` → `\`\`\`typescript` with interfaces + error types + sample const
- `pydantic_model` → `\`\`\`python` with BaseModel + FastAPI Depends + HTTPException + sample dict

**Rationale:** Billing-403 bug class happens when AI "decides" auth role or error shape instead of
copying from contract. By generating executable code blocks for ALL 3 concerns, the executor has
zero decision points — it copies, it doesn't think. Same principle as Zod schema copy, extended to
auth middleware and error responses. Block 4 eliminates the second bug class: heuristic payload
generation in test.md step 5b-2 producing values that fail Zod validation (e.g. `idempotency-test-domain`
is not a valid URL). Contract author knows the schema best — they provide the valid sample.

**Error response shape** is project-wide consistent. Read `config.error_response_shape` (default:
`{ error: { code: string, message: string } }`) — every endpoint's Block 3 MUST use this shape.
FE code reads `response.data.error.message` for toast — never `response.statusText` or raw code.

**Block 4 rules:**
1. Each endpoint MUST have Block 4 with valid sample payload matching Block 2 schema.
2. Use realistic values: valid email (test@example.com), valid UUID (00000000-...-000001), valid URL (https://test.example.com), ISO date, etc.
3. Zod/Pydantic validation of Block 4 values must pass against Block 2 schema.
4. Block 4 is consumed by test.md step 5b-2 idempotency check — NOT copied into app code.
5. Sample const name convention: `{Method}{Resource}Sample` (e.g. `PostSitesSample`, `PutCampaignSample`).
6. Mark `as const` (TypeScript) or freeze (Python) to prevent accidental mutation.
7. GET endpoints do NOT need Block 4 (no mutation payload).
8. For endpoints with path params, include a comment with sample path: `// path: /api/sites/00000000-0000-0000-0000-000000000001`

**Context budget:** ~500 lines (increased from 400 — 4 blocks per endpoint). Agent reads:
- CONTEXT.md (decisions list, ~50 lines)
- Grep results from code (extracted field hints, ~100 lines)
- Contract format template from config (~150 lines)
- Existing auth middleware patterns in codebase (~100 lines)

**Output:** Write `${PHASE_DIR}/API-CONTRACTS.md`. Must contain at least 1 code block per endpoint.

If no API routes or web pages detected → write minimal contract with CONTEXT-derived endpoints only. Still enforce code block format.
</step>

<step name="2b5_test_goals">
## Sub-step 2b5: TEST GOALS

Generate TEST-GOALS.md from CONTEXT.md decisions + API-CONTRACTS.md endpoints.

**Agent context (~300 lines):**
- CONTEXT.md decisions (`P{phase}.D-01` through `P{phase}.D-XX`, or legacy `D-01..D-XX`) (~100 lines)
- API-CONTRACTS.md endpoints + fields (~100 lines)
- Output format template (~100 lines)

**Agent prompt:**
```
Convert CONTEXT decisions into testable GOALS.

For each decision (`P{phase}.D-XX`, or legacy `D-XX`), produce 1+ goals. Each goal:
- Has success criteria (what the user can do, what the system shows)
- Has mutation evidence (for create/update/delete: API response + UI change)
- Has dependencies (which goals must pass first)
- Has priority (critical = core feature, important = expected feature, nice-to-have = edge case/polish)

CONTEXT decisions:
[P{phase}.D-01 through P{phase}.D-XX — phase-scoped namespace, mandatory prefix]

API endpoints:
[from API-CONTRACTS.md]

RULES:
1. Every decision MUST have at least 1 goal
2. Goals describe WHAT to verify, not HOW (no selectors, no exact clicks)
3. Mutation evidence must be specific: "POST returns 201 AND row count +1" not "data changes"
3b. **Persistence check field (MANDATORY for mutation goals)**: Every goal with non-empty Mutation evidence MUST also have `**Persistence check:**` block describing Layer 4 verify (refresh + re-read + diff):
    ```
    **Persistence check:**
    - Pre-submit: read <field/row/state> value (e.g., role="editor")
    - Action: <what user does> (fill dropdown role="admin", click Save)
    - Post-submit wait: API 2xx + toast
    - Refresh: page.reload() OR navigate away + back
    - Re-read: <where to re-read> (re-open edit modal)
    - Assert: <field> = <new value> AND != <pre value> (role="admin", not "editor")
    ```
    Why mandatory: "ghost save" bug pattern — toast + API 200 + console clean NHƯNG refresh hiện data cũ. Only refresh-then-read detects backend silent skip / client optimistic rollback. Read-only goals (GET only) KHÔNG cần field này.
4. Dependencies must reference goal IDs (G-XX)
5. Priority assignment (deterministic rules, evaluate in order):
   a. Endpoints matching config `routing.critical_goal_domains` (auth, billing, auction, payout, compliance) → priority: critical
   b. Auth/session/token goals (login, logout, JWT refresh, session persist) → priority: critical
   c. Data mutation goals (POST/PUT/DELETE endpoints) → priority: important (minimum — upgrade to critical if also matches rule a/b)
   d. Read-only goals (GET endpoints, list/detail views) → priority: important (default)
   e. Cosmetic/display goals (formatting, sorting, empty states, UI polish) → priority: nice-to-have
6. Infrastructure dependency annotation (config-driven):
   If a goal requires services listed in config.infra_deps.services that are NOT part of this phase's build scope (e.g., ClickHouse, Kafka, pixel server), add:
   ```
   **Infra deps:** [clickhouse, kafka, pixel_server]
   ```
   Review Phase 4 auto-classifies goals with unmet infra_deps as INFRA_PENDING (skipped from gate).
   Determine infra scope by reading PLAN.md — services explicitly provisioned in tasks = in scope.
   Services referenced but not provisioned = external infra dep.

Output format:

# Test Goals — Phase {PHASE}

Generated from: CONTEXT.md decisions + API-CONTRACTS.md
Total: {N} goals ({critical} critical, {important} important, {nice} nice-to-have)

## Goal G-00: Authentication (F-06 or P{phase}.D-XX)
**Priority:** critical
**Success criteria:**
- User can log in with valid credentials
- Invalid credentials show error message
- Session persists across page navigation
**Mutation evidence:**
- Login: POST /api/auth/login returns 200 + token
**Dependencies:** none (root goal)
**Infra deps:** none

## Goal G-01: {Feature} (P{phase}.D-XX — or F-XX if foundation-sourced)
**Priority:** critical | important | nice-to-have
**Success criteria:**
- [what the user can do]
- [what the system shows]
- [error handling]
**Mutation evidence:**
- [Create: POST /api/X returns 201, table row +1]
- [Update: PUT /api/X/:id returns 200, row reflects change]
**Persistence check:**
- Pre-submit: read <field/row/state> (e.g., status="draft" in detail panel)
- Action: <what user does> (change status dropdown, click Save)
- Post-submit wait: API 2xx + toast "Updated"
- Refresh: page.reload()
- Re-read: re-open same record / navigate back to list
- Assert: <field> = <new value> AND != <pre value> (status="published", not "draft")
**Dependencies:** G-00

## Decision Coverage
| Decision | Goal IDs | Priority |
|----------|----------|----------|
| D-01 | G-01, G-02 | critical |
| D-02 | G-03 | important |
| ...  | ... | ... |

Coverage: {covered}/{total} decisions → {percentage}%
```

Write `${PHASE_DIR}/TEST-GOALS.md`.

**Bidirectional linkage with PLAN (mandatory post-gen):**

After TEST-GOALS.md is written, inject cross-references so build step 8 can quickly find context:

1. **Goals → Tasks** (in TEST-GOALS.md): for each G-XX, detect which tasks in PLAN*.md implement it (match by endpoint/file mentions). Add:
   ```markdown
   ## Goal G-03: Create site (D-02)
   **Implemented by:** Task 04 (BE handler), Task 07 (FE form)   ← NEW
   ...
   ```

2. **Tasks → Goals** (in PLAN*.md): for each task, inject `<goals-covered>` attribute if not already present. Auto-detect based on task description mentioning endpoint/feature that maps to goal's mutation evidence.

Algorithm (deterministic, no AI guess):
```
For each goal G-XX in TEST-GOALS.md:
  extract endpoints from "mutation evidence" (e.g., POST /api/sites)
  For each task in PLAN*.md:
    If task description contains matching endpoint OR feature-name from goal:
      append task to goal.implemented_by
      append goal to task.<goals-covered>

For orphan tasks (no goal match):
  inject <goals-covered>no-goal-impact</goals-covered>
  OR <goals-covered>UNKNOWN — review</goals-covered> (flag for user)

For orphan goals (no task match):
  inject **Implemented by:** ⚠ NONE (spec gap — plan regeneration needed)
```

Display:
```
Test Goals: {N} goals generated ({critical} critical, {important} important, {nice} nice-to-have)
Decision coverage: {covered}/{total} ({percentage}%)
Goal ↔ Task linkage:
  Goals linked to tasks: {N}/{total}
  Orphan goals (no task): {N}       ← spec gap, surfaced to 2d validation
  Orphan tasks (no goal): {N}       ← may be infra or spec bloat
```

**Surface classification (v1.9.1 R1 — lazy migration):**

Immediately after TEST-GOALS.md is written (including bidirectional linkage), classify each goal into a **test surface** (ui / ui-mobile / api / data / time-driven / integration / custom). This is what `/vg:review` and `/vg:test` use to pick runners — backend-only phases must not deadlock on browser discovery.

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
```

Behaviour by return code:
- `0` → all goals classified at ≥0.8 confidence (narration prints auto-count).
- `2` → 0.5..0.8 band needs Haiku tie-break. Read `${PHASE_DIR}/.goal-classifier-pending.tsv`, spawn ONE Haiku subagent per goal (pattern identical to `rationalization-guard` — subagent receives goal block + candidate surface + keywords found, returns `{surface, confidence}`). Call `classify_goals_apply` with the resolved TSV.
- `3` → some goals <0.5 confidence. BLOCK until user picks via `AskUserQuestion` (options = configured surface list + "custom"). Call `classify_goals_apply` with user answers.

After classification, include per-goal surface in blueprint narration:
```
🎯 Goal surfaces: 17 ui · 5 api · 3 data · 2 time-driven · 1 integration
```
</step>

<step name="2b6_ui_spec">
## Sub-step 2b6: UI SPEC (FE tasks only)

**Skip conditions:**
- No task has `file-path` matching `config.code_patterns.web_pages` → skip entirely
- `config.design_assets.paths` empty → skip (no visual reference to derive from)
- `${PHASE_DIR}/UI-SPEC.md` already exists and is newer than all PLAN*.md + design manifest → skip (already fresh)

**Purpose:** Produce UI contract executor reads alongside API-CONTRACTS. Answers: layout, component set, spacing tokens, interaction states, responsive breakpoints.

**Input (~600 lines agent context):**
- CONTEXT.md (design decisions if any, ~100 lines)
- Task file-paths of FE tasks + their `<design-ref>` attributes (~100 lines)
- `${DESIGN_OUTPUT_DIR}/manifest.json` — list of available screenshots + structural refs (~50 lines)
- Sample design refs (read 2-3 representative ones — `*.structural.html` + `*.interactions.md`) (~300 lines)

**Agent prompt:**
```
Generate UI-SPEC.md for phase {PHASE}. This is the design contract FE executors copy verbatim.

RULES:
1. Extract visible patterns from design-normalized refs — do NOT invent.
2. For each component used: name, markup structure (from structural.html), states (from interactions.md).
3. Spacing/color tokens only if consistent across refs. If refs conflict, flag for user.
4. Per-page section: layout (grid/flex), slots (header/sidebar/main), interaction patterns.
5. Reference screenshots by slug — executor opens them for pixel truth.

Output format:

# UI Spec — Phase {PHASE}

Source: ${DESIGN_OUTPUT_DIR}/  (screenshots + structural + interactions)
Derived: {YYYY-MM-DD}

## Design Tokens
| Token | Value | Source |
|-------|-------|--------|
| color.primary | #6366f1 | consistent across {slug-a}, {slug-b} |
| spacing.lg | 24px | ... |

## Component Library (observed in design)
### Button
- Variants: primary | secondary | ghost
- States: default | hover | disabled
- Markup: `<button class="btn btn-{variant}">...</button>`  (from {slug}.structural.html#btn-primary)

### Modal
- Pattern: overlay + centered card
- Open/close: `data-modal-open="{id}"` / `data-modal-close` (from {slug}.interactions.md)
...

## Per-Page Layout
### /publisher/sites (Task 07)
- Screenshot: ${DESIGN_OUTPUT_DIR}/screenshots/sites-list.default.png
- Layout: sidebar (fixed 240px) + main (flex-1)
- Sections: toolbar (search + Add button), table (5 cols), pagination footer
- States needed: empty | loading | populated | error
- Interactions: row click → detail drawer; Add button → modal (component ref above)

## Responsive Breakpoints
(only if design has multiple viewport screenshots)

## Conflicts / Ambiguities
(flag anything where design refs disagree — user decides)
```

Write `${PHASE_DIR}/UI-SPEC.md`. Build step 4/8c injects relevant section per FE task.

Display:
```
UI-SPEC:
  FE tasks detected: {N}
  Design refs consumed: {N}
  Tokens: {N} | Components: {N} | Pages: {N}
  Conflicts flagged: {N}
```
</step>

<step name="2b6b_ui_map" profile="web-fullstack,web-frontend-only">
## Sub-step 2b6b: UI-MAP (bản vẽ đích cây component)

**Mục tiêu:** Tạo `UI-MAP.md` chứa cây component kế hoạch đích (to-be blueprint) cho các
view mới/sửa trong phase này. Executor sẽ bám vào cây này khi viết code, verify-ui-structure.py
sẽ so sánh post-wave để phát hiện lệch hướng (drift).

**Khác biệt với 2b6_ui_spec:**
- `UI-SPEC.md` = spec cấp cao (design tokens, typography, interactions) — thường áp dụng toàn phase.
- `UI-MAP.md` = cây component cụ thể cho từng view — thứ executor bám theo từng dòng.

**Skip khi:**
- Phase không có task UI (profile backend-only)
- Config `ui_map.enabled: false`

```bash
# Đọc config ui_map
UI_MAP_ENABLED=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /enabled:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"' || echo "true")

if [ "$UI_MAP_ENABLED" != "true" ]; then
  echo "ℹ ui_map disabled in config — skipping UI-MAP generation"
  touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
else
  # Kiểm tra phase có touch FE không
  FE_TASKS=$(grep -cE "(\.tsx|\.jsx|\.vue|\.svelte)" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo "0")

  if [ "${FE_TASKS:-0}" -eq 0 ]; then
    echo "ℹ Phase không có task FE — skip UI-MAP"
    touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
  else
    echo "Phase có ${FE_TASKS} dòng task FE. Chuẩn bị UI-MAP.md..."

    # ─── Bước 1: Sinh as-is map nếu phase sửa view cũ ───
    # Detect: task có edit file UI đã tồn tại
    EXISTING_UI_FILES=$(grep -hE "^\s*-\s*(Edit|Modify):" "${PHASE_DIR}"/PLAN*.md 2>/dev/null | \
                        grep -oE "[a-z_-]+\.(tsx|jsx|vue|svelte)" | sort -u)

    if [ -n "$EXISTING_UI_FILES" ]; then
      echo "Phát hiện task sửa view cũ — sinh UI-MAP-AS-IS.md để planner hiểu cấu trúc hiện tại"

      UI_MAP_SRC=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /src:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')
      UI_MAP_ENTRY=$(awk '/^ui_map:/{f=1; next} f && /^[a-z_]+:/{f=0} f && /entry:/{print $2; exit}' .claude/vg.config.md 2>/dev/null | tr -d '"')

      if [ -n "$UI_MAP_SRC" ] && [ -n "$UI_MAP_ENTRY" ]; then
        node .claude/scripts/generate-ui-map.mjs \
          --src "$UI_MAP_SRC" \
          --entry "$UI_MAP_ENTRY" \
          --format both \
          --output "${PHASE_DIR}/UI-MAP-AS-IS.md" 2>&1 | tail -3
      else
        echo "⚠ ui_map.src / ui_map.entry chưa cấu hình — bỏ qua as-is scan"
      fi
    fi

    # ─── Bước 2: Planner viết UI-MAP.md (to-be blueprint) ───
    # Orchestrator spawn planner agent với:
    # - CONTEXT.md (decisions)
    # - PLAN*.md (tasks)
    # - UI-SPEC.md (component inventory nếu có)
    # - UI-MAP-AS-IS.md (cây hiện trạng nếu phase sửa view cũ)
    # - Design refs từ design-normalized/ (nếu có)
    #
    # Output: ${PHASE_DIR}/UI-MAP.md với:
    #   - Cây ASCII cho mỗi view mới/sửa
    #   - JSON tree (machine-readable, cho verify-ui-structure.py diff)
    #   - Layout notes (class layout + style keys mong muốn)
    #
    # Template ở ${REPO_ROOT}/.claude/commands/vg/_shared/templates/UI-MAP-template.md

    if [ ! -f "${PHASE_DIR}/UI-MAP.md" ]; then
      echo "▸ Orchestrator cần spawn planner agent (model=${MODEL_PLANNER:-opus}) để viết UI-MAP.md"
      echo "   Input: CONTEXT.md + PLAN*.md + UI-SPEC.md + UI-MAP-AS-IS.md (nếu có)"
      echo "   Output: ${PHASE_DIR}/UI-MAP.md"
      echo ""
      echo "   Planner prompt (tóm tắt):"
      echo "   'Với mỗi view tạo mới hoặc cải tạo trong phase này, vẽ cây component"
      echo "    dạng ASCII + JSON. Mỗi node component ghi: tên, file path đích, class"
      echo "    layout mong muốn, state/props gì quan trọng. Cây phải khả thi (executor"
      echo "    build theo được). Nếu sửa view cũ: điều chỉnh UI-MAP-AS-IS.md.'"
    else
      echo "ℹ UI-MAP.md đã có — skip regeneration. Xoá file này để regenerate."
    fi

    touch "${PHASE_DIR}/.step-markers/2b6b_ui_map.done"
  fi
fi
```

**Gate (chưa block, chỉ warn):** nếu phase có task FE nhưng UI-MAP.md không có, in warning — step 2d validation sẽ escalate.
</step>

<step name="2b7_flow_detect" profile="web-fullstack,web-frontend-only">
## Sub-step 2b7: FLOW-SPEC AUTO-DETECT (deterministic, no AI for detection)

**Purpose:** Detect goal dependency chains >= 3 in TEST-GOALS.md. When found, auto-generate
FLOW-SPEC.md skeleton so `/vg:test` step 5c-flow has flows to verify. Without this,
multi-page state-machine bugs (login → create → edit → delete) slip through because
per-goal tests verify each step independently but miss continuity failures.

**Skip conditions:**
- TEST-GOALS.md does not exist → skip (blueprint hasn't generated goals yet)
- Profile is `web-backend-only` or `cli-tool` or `library` → skip (no UI flows)

**Step 1: Parse dependency graph from TEST-GOALS.md**

```bash
# Extract goal IDs and their dependencies (deterministic grep, no AI)
CHAIN_OUTPUT=$(${PYTHON_BIN} - "${PHASE_DIR}/TEST-GOALS.md" <<'PYEOF'
import sys, re, json
from pathlib import Path
from collections import defaultdict

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse goals: ID, title, priority, dependencies
goals = {}
current = None
for line in text.splitlines():
    m = re.match(r'^## Goal (G-\d+):\s*(.+?)(?:\s*\(D-\d+\))?$', line)
    if m:
        current = m.group(1)
        goals[current] = {'title': m.group(2).strip(), 'deps': [], 'priority': 'important'}
        continue
    if current:
        dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
        if dm:
            deps_str = dm.group(1).strip()
            if deps_str.lower() not in ('none', 'none (root goal)', ''):
                goals[current]['deps'] = re.findall(r'G-\d+', deps_str)
        pm = re.match(r'\*\*Priority:\*\*\s*(\w+)', line)
        if pm:
            goals[current]['priority'] = pm.group(1).strip()

# Build dependency chains via DFS — find all maximal chains
def find_chains(goal_id, visited=None):
    if visited is None:
        visited = []
    visited = visited + [goal_id]
    deps = goals.get(goal_id, {}).get('deps', [])
    # Find goals that depend on this one (forward chains)
    dependents = [g for g, info in goals.items() if goal_id in info['deps'] and g not in visited]
    if not dependents:
        return [visited]
    chains = []
    for dep in dependents:
        chains.extend(find_chains(dep, visited))
    return chains

# Find root goals (no dependencies or only depend on auth)
roots = [g for g, info in goals.items() if not info['deps']]
all_chains = []
for root in roots:
    all_chains.extend(find_chains(root))

# Filter chains >= 3 goals (these are multi-step business flows)
long_chains = [c for c in all_chains if len(c) >= 3]
# Deduplicate (keep longest chain per root)
seen = set()
unique_chains = []
for chain in sorted(long_chains, key=len, reverse=True):
    key = tuple(chain[:2])  # dedup by first 2 elements
    if key not in seen:
        seen.add(key)
        unique_chains.append(chain)

output = {
    'total_goals': len(goals),
    'total_chains': len(unique_chains),
    'chains': [{'goals': c, 'length': len(c),
                'titles': [goals[g]['title'] for g in c if g in goals]}
               for c in unique_chains],
    'goals': {g: info for g, info in goals.items()}
}
print(json.dumps(output, indent=2))
PYEOF
)
```

**Step 2: Generate FLOW-SPEC.md skeleton (only if chains found)**

```bash
CHAIN_COUNT=$(echo "$CHAIN_OUTPUT" | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin)['total_chains'])" 2>/dev/null || echo "0")

if [ "$CHAIN_COUNT" -eq 0 ]; then
  echo "Flow detect: no dependency chains >= 3 found. Skipping FLOW-SPEC generation."
  # No FLOW-SPEC.md = 5c-flow will skip (expected for simple phases)
else
  echo "Flow detect: $CHAIN_COUNT chains >= 3 goals found. Generating FLOW-SPEC.md skeleton..."

  # Generate skeleton — AI fills in step details from goal success criteria
  Agent(subagent_type="general-purpose", model="${MODEL_TEST_GOALS}"):
    prompt: |
      Generate FLOW-SPEC.md for phase ${PHASE}. This defines multi-page test flows
      for the flow-runner skill.

      Input — detected dependency chains (goals that form sequential business flows):
      ${CHAIN_OUTPUT}

      Input — full TEST-GOALS.md:
      @${PHASE_DIR}/TEST-GOALS.md

      Input — API-CONTRACTS.md (for endpoint details):
      @${PHASE_DIR}/API-CONTRACTS.md

      RULES:
      1. Each chain becomes 1 flow. Flow = ordered sequence of steps.
      2. Each step maps to 1 goal in the chain.
      3. Step has: action (what user does), expected (what system shows), checkpoint (what to save for next step).
      4. Use goal success criteria + mutation evidence as step expected/checkpoint.
      5. Do NOT invent steps outside the chain — only goals in the chain.
      6. Do NOT specify selectors, CSS classes, or exact clicks — describe WHAT, not HOW.
      7. Flow names should describe the business operation: "Site CRUD lifecycle", "Campaign create-to-launch".

      Output format:

      # Flow Specs — Phase {PHASE}

      Generated from: TEST-GOALS.md dependency chains >= 3
      Total: {N} flows

      ## Flow F-01: {Business operation name}
      **Chain:** {G-00 → G-01 → G-03 → G-05}
      **Priority:** critical | important
      **Roles:** [{roles involved}]

      ### Step 1: {Action name} (G-00)
      **Action:** {what the user does}
      **Expected:** {what the system shows — from goal success criteria}
      **Checkpoint:** {state to verify/save for next step — from mutation evidence}

      ### Step 2: {Action name} (G-01)
      **Action:** ...
      **Expected:** ...
      **Checkpoint:** ...
      ...

      ## Flow Coverage
      | Flow | Goals covered | Priority |
      |------|--------------|----------|
      | F-01 | G-00, G-01, G-03, G-05 | critical |

      Write to: ${PHASE_DIR}/FLOW-SPEC.md
fi
```

Display:
```
Flow detection:
  Goals parsed: {N}
  Dependency chains >= 3: {CHAIN_COUNT}
  FLOW-SPEC.md: {generated|skipped (no chains)}
  Flows defined: {N}
```
</step>

<step name="2c_verify">
## Sub-step 2c: VERIFY 1 (grep only, no AI)

Automated contract verification. Must complete in <5 seconds.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
API_ROUTES="${config.code_patterns.api_routes}"
WEB_PAGES="${config.code_patterns.web_pages}"
MISMATCHES=0

# 1. Contract fields vs HTML form fields
if [ -n "$WEB_PAGES" ] && [ -d "$WEB_PAGES" ]; then
  # For each endpoint with request fields in contracts:
  #   grep form field names in web pages
  #   Missing field → mismatch++
fi

# 2. Contract fields vs Zod schema (if backend exists)
if [ -n "$API_ROUTES" ] && [ -d "$API_ROUTES" ]; then
  # For each endpoint with response fields in contracts:
  #   grep field names in Zod schemas
  #   Missing field → mismatch++
fi

# 3. Contract endpoints vs CONTEXT decisions
# Parse endpoints from CONTEXT.md — supports both formats:
#   VG-native bullet: "- POST /api/v1/sites (auth: publisher, purpose: create)"
#     regex: ^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)
#   Legacy header:   "### POST /api/v1/sites"
#     regex: ^###\s+(?:\d+\.\d+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)
# For each matched (method, path) pair:
#   Check at least one endpoint in contracts covers it
#   No endpoint → mismatch++
```

**Results:**
- 0 mismatches → PASS, proceed to 2d
- 1-3 mismatches → WARNING, auto-fix contracts, re-verify once
- 4+ mismatches → BLOCK, show mismatch table, ask user to review contracts

Display:
```
Verify 1 (grep): {N} endpoints checked, {M} field comparisons
Result: {PASS|WARNING|BLOCK} — {N} mismatches
```
</step>

<step name="2c_verify_plan_paths">
## Sub-step 2c1b: PLAN PATH VALIDATION (no AI, <5 sec)

Catches stale `<file-path>` tags in PLAN — the class of bug seen in Phase 10:
- Task 2 PLAN said `apps/api/src/infrastructure/clickhouse/migrations/0017_add_deal_columns.sql`
  but that directory doesn't exist (real CH schemas in apps/workers/src/consumer/clickhouse/schemas.js)
- Task 12 PLAN said `apps/rtb-engine/src/auction/pipeline.rs`
  but that directory doesn't exist (real auction entry at apps/rtb-engine/src/handlers/bid.rs)

Both were only caught when the executor agent opened the file. This step runs
at blueprint time — catches them before /vg:build spawns executors.

```bash
PATH_CHECKER=".claude/scripts/verify-plan-paths.py"
if [ -f "$PATH_CHECKER" ]; then
  echo ""
  echo "━━━ Sub-step 2c1b: PLAN path validation ━━━"
  ${PYTHON_BIN:-python} "$PATH_CHECKER" \
    --phase-dir "${PHASE_DIR}" \
    --repo-root "${REPO_ROOT:-.}"
  PATH_EXIT=$?

  case "$PATH_EXIT" in
    0)
      echo "✓ All PLAN paths valid"
      ;;
    2)
      echo "⚠ PLAN has path warnings — review output above."
      echo "  If paths are intentional new subsystems, proceed (non-blocking)."
      echo "  If paths are stale, fix PLAN now before /vg:build spawns executors against wrong paths."
      # Non-blocking — planner may be creating new subsystems. User inspects.
      ;;
    1)
      echo "⛔ PLAN has malformed paths — fix PLAN.md before proceeding."
      exit 1
      ;;
  esac
else
  echo "⚠ verify-plan-paths.py missing — skipping PLAN path validation (older install)"
fi
```

Classifications:
- `VALID` — file exists (editing) OR parent dir exists (new file in existing dir) OR parent dir will be created by another task
- `WARN` — parent dir doesn't exist and no other task creates it (likely stale, but could be intentional new subsystem)
- `FAIL` — malformed path (absolute / escapes repo via `..` / has `+` separator / empty)

WARN → non-blocking report. User can `<also-edits>foo/bar/` on an upstream task to declare the new dir is intentional.
FAIL → hard exit 1. PLAN author must fix.
</step>

<step name="2c1c_verify_utility_reuse">
## Sub-step 2c1c: UTILITY REUSE CHECK (no AI, <5 sec)

Catches PLAN tasks that redeclare helper functions already exported from the shared utility contract in `PROJECT.md` → `## Shared Utility Contract`. Root cause of ~1500-2500 LOC duplicate seen in Phase 10 audit (16 files declaring own `formatCurrency`, 52 occurrences of `Intl.NumberFormat currency` pattern).

```bash
UTILITY_CHECKER=".claude/scripts/verify-utility-reuse.py"
PROJECT_MD="${PLANNING_DIR}/PROJECT.md"

if [ -f "$UTILITY_CHECKER" ] && [ -f "$PROJECT_MD" ]; then
  echo ""
  echo "━━━ Sub-step 2c1c: Utility reuse check (prevent duplicate helpers) ━━━"
  ${PYTHON_BIN:-python} "$UTILITY_CHECKER" \
    --project "$PROJECT_MD" \
    --phase-dir "${PHASE_DIR}"
  UTIL_EXIT=$?

  case "$UTIL_EXIT" in
    0)
      echo "✓ No utility-reuse violations"
      ;;
    2)
      echo "⚠ Utility-reuse warnings — consider consolidating into @vollxssp/utils"
      echo "  Non-blocking. If phase legitimately needs new helper, add Task 0 (extend utils) in PLAN."
      ;;
    1)
      echo "⛔ PLAN redeclares helpers already in shared utility contract."
      echo "   Fix: replace re-declaration with import from @vollxssp/utils, OR"
      echo "        if PLAN needs an extended variant, add Task 0 (extend utils) + reuse across tasks."
      echo "   Rationale: every duplicate helper adds AST nodes (tsc slowdown) + graphify noise."
      echo ""
      echo "Override (NOT recommended): /vg:blueprint ${PHASE_NUMBER} --override-reason=<issue-id>"
      if [[ ! "${ARGUMENTS:-}" =~ --override-reason= ]]; then
        exit 1
      fi
      echo "⚠ --override-reason set — proceeding with utility duplication debt"
      echo "utility-reuse: $(date -u +%FT%TZ) phase=${PHASE_NUMBER} override=yes" >> "${PHASE_DIR}/build-state.log"
      ;;
  esac
else
  [ ! -f "$UTILITY_CHECKER" ] && echo "⚠ verify-utility-reuse.py missing — skipping utility-reuse check (older install)"
  [ ! -f "$PROJECT_MD" ] && echo "⚠ PROJECT.md missing — skipping utility-reuse check (run /vg:project first)"
fi
```

BLOCK conditions:
- Task declares a function name (via `function X`, `const X =`, `export function X`, "add helper X", etc.) AND that name exists in the contract table.
- EXCEPTION: task's `<file-path>` is inside `packages/utils/` — that IS the canonical place.

WARN conditions:
- Task declares NEW helper (not in contract) AND spans ≥2 non-utils file paths — suggests reuse that should start in utils.

**Override:** `--override-reason=<issue-id>` on `/vg:blueprint` allows passing with debt logged. Use only when the new helper is genuinely phase-local (e.g., deal-specific formatter only used in 1 file forever).
</step>

<step name="2c2_compile_check">
## Sub-step 2c2: CONTRACT COMPILE CHECK (no AI, <10 sec)

Extract executable code blocks from API-CONTRACTS.md → compile via `config.contract_format.compile_cmd`.
Catches contract syntax errors BEFORE build consumes them.

```bash
CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
COMPILE_CMD="${config.contract_format.compile_cmd}"
CONTRACT_TYPE="${config.contract_format.type}"

# Select code block language per contract_format.type:
#   zod_code_block / typescript_interface → ```typescript
#   openapi_yaml → ```yaml
#   pydantic_model → ```python
case "$CONTRACT_TYPE" in
  zod_code_block|typescript_interface) FENCE_LANG="typescript" ;;
  openapi_yaml)                        FENCE_LANG="yaml" ;;
  pydantic_model)                      FENCE_LANG="python" ;;
  *)                                   FENCE_LANG="typescript" ;;
esac

# Extract all matching fenced code blocks into tmp file
TMP_DIR=$(mktemp -d)
${PYTHON_BIN} - "$CONTRACTS" "$TMP_DIR" "$FENCE_LANG" "$CONTRACT_TYPE" <<'PYEOF'
import sys, re
from pathlib import Path
contracts, tmpdir, lang, ctype = sys.argv[1:5]
text = Path(contracts).read_text(encoding='utf-8')
pattern = re.compile(r"```" + re.escape(lang) + r"\s*\n(.*?)\n```", re.DOTALL)
blocks = pattern.findall(text)
if not blocks:
    print(f"NO_CODE_BLOCKS: expected ```{lang} blocks, found 0. Contract format violated.")
    sys.exit(3)

# Concatenate with appropriate prelude per type
prelude = ""
if ctype == "zod_code_block":
    prelude = "import { z } from 'zod';\n\n"
elif ctype == "pydantic_model":
    prelude = "from pydantic import BaseModel\nfrom typing import Optional, List, Literal\nfrom datetime import datetime\n\n"

ext = {"typescript": "ts", "yaml": "yaml", "python": "py"}.get(lang, "ts")
out = Path(tmpdir) / f"contracts-check.{ext}"
out.write_text(prelude + "\n\n".join(blocks), encoding='utf-8')
print(out)
PYEOF

COMPILE_INPUT=$(${PYTHON_BIN} ... last line)

# Run compile command on extracted file
if [ -n "$COMPILE_CMD" ]; then
  ACTUAL_CMD=$(echo "$COMPILE_CMD" | sed "s|{FILE}|$COMPILE_INPUT|g")
  # If no {FILE} placeholder, append file path
  [[ "$COMPILE_CMD" == *"{FILE}"* ]] || ACTUAL_CMD="$COMPILE_CMD $COMPILE_INPUT"

  eval "$ACTUAL_CMD" 2>&1 | tee "${PHASE_DIR}/contract-compile.log"
  EXIT=${PIPESTATUS[0]}
  if [ $EXIT -ne 0 ]; then
    echo "CONTRACT COMPILE FAILED — see ${PHASE_DIR}/contract-compile.log"
    echo "Fix contract syntax in ${PHASE_DIR}/API-CONTRACTS.md and re-run /vg:blueprint --from=2b"
    exit 1
  fi
fi
```

**Results:**
- PASS → contracts syntactically valid, proceed to 2d
- FAIL → BLOCK, show compile errors, user must fix API-CONTRACTS.md code blocks

Display:
```
Verify 2 (compile): {N} code blocks extracted
Compile check: {PASS|FAIL} via {config.contract_format.compile_cmd}
```
</step>

<step name="2d_validation_gate">
## Sub-step 2d: VALIDATION GATE + AUTO-FIX RETRY + CROSSAI

**Combined step:** deterministic validation (plan↔SPECS↔goals↔contracts) + auto-fix retry loop + existing CrossAI review.

**Skip conditions:** none — this is the quality gate before commit.

### 2d-1: Load or create blueprint-state.json

```bash
STATE_FILE="${PHASE_DIR}/blueprint-state.json"
if [ -f "$STATE_FILE" ]; then
  # Resume scenario — prompt user
  LAST_STEP=$(jq -r .current_step "$STATE_FILE")
  LAST_ITER=$(jq -r '.iterations | length' "$STATE_FILE")
  LAST_MODE=$(jq -r '.validation_mode_chosen // "unknown"' "$STATE_FILE")
  echo "Blueprint state found for ${PHASE}:"
  echo "  Last step: $LAST_STEP  (iterations: $LAST_ITER)"
  echo "  Mode: $LAST_MODE"
  # AskUserQuestion: Resume / Restart from step / Fresh
fi

# Fresh start — init state
jq -n --arg phase "$PHASE" --arg ts "$(date -u +%FT%TZ)" '{
  phase: $phase,
  pipeline_version: "vg-v5.2",
  started_at: $ts,
  updated_at: $ts,
  current_step: "2d_validation",
  last_step_completed: "2c2_compile_check",
  steps_status: {
    "2a_plan": "completed", "2a5_cross_system": "completed",
    "2b_contracts": "completed", "2b4_design_ref_linkage": "pending",
    "2b5_test_goals": "completed", "2b7_flow_detect": "pending",
    "2c_verify_grep": "completed",
    "2c2_compile_check": "completed", "2d_validation": "in_progress",
    "3_complete": "pending"
  },
  validation_mode_chosen: null,
  thresholds: null,
  iterations: [],
  user_overrides: []
}' > "$STATE_FILE"
```

### 2d-2: Runtime prompt — strictness mode

**Skip if --auto (use config.plan_validation.default_mode):**

```
AskUserQuestion:
  "Plan validation strictness — AI will auto-fix up to 3 iterations with gap feedback."
  [Recommended: Strict]
  Options:
    - Strict (10% D / 15% G / 5% endpoints miss → BLOCK)
    - Default (20% / 30% / 10%)
    - Loose (40% / 50% / 20%)
    - Custom (enter values)
```

Save mode + thresholds to blueprint-state.json.

### 2d-3: Validation checks (deterministic, no AI)

For current iteration N (starts at 1):

```
# Parse CONTEXT decisions
DECISIONS=$(grep -oE '^D-[0-9]+' "${PHASE_DIR}/CONTEXT.md" | sort -u)
# Parse PLAN tasks with goals-covered
TASKS=$(grep -oE '^## Task [0-9]+' "${PHASE_DIR}"/PLAN*.md | sort -u)
# Parse TEST-GOALS
GOALS=$(grep -oE '^## Goal G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | sort -u)
# Parse API-CONTRACTS endpoints
ENDPOINTS=$(grep -oE '^### (POST|GET|PUT|DELETE|PATCH) /' "${PHASE_DIR}/API-CONTRACTS.md" | sort -u)

# Cross-check (bidirectional — fixes I4):
# 1. Decisions ↔ Tasks (SPECS covered)
for D in $DECISIONS:
  if no task references D (check in PLAN*.md goals-covered or implements-decision attr):
    decisions_missing += D
# 2. Goals → Tasks (normal direction: task covers goal)
for G in $GOALS:
  if no task lists G in <goals-covered>:
    goals_missing += G
# 2-bis. Goals ← Tasks (orphan goals from 2b5 Implemented-by linkage)
#        A goal flagged "⚠ NONE" in TEST-GOALS.md means bidirectional linkage failed
#        → count it as missing even if some task coincidentally has its ID.
orphan_goals=$(grep -B1 "Implemented by:.*⚠ NONE" "${PHASE_DIR}/TEST-GOALS.md" | grep -oE '^## Goal G-[0-9]+')
goals_missing = unique(goals_missing ∪ orphan_goals)
# 3. Endpoints ↔ Tasks
for E in $ENDPOINTS:
  if no task creates handler for E:
    endpoints_missing += E

# Compute miss percentages (guard against zero division for empty phases)
decisions_miss_pct = (len(decisions_missing) / len(DECISIONS) * 100) if len(DECISIONS) > 0 else 0
goals_miss_pct = (len(goals_missing) / len(GOALS) * 100) if len(GOALS) > 0 else 0
endpoints_miss_pct = (len(endpoints_missing) / len(ENDPOINTS) * 100) if len(ENDPOINTS) > 0 else 0
```

### 2d-4: Gate decision

```
Threshold T = state.thresholds (per chosen mode)

if decisions_miss_pct <= T.decisions_miss_pct AND
   goals_miss_pct <= T.goals_miss_pct AND
   endpoints_miss_pct <= T.endpoints_miss_pct:
  → PASS (proceed to CrossAI review 2d-6)
else if iteration < max_auto_fix_iterations (default 3):
  → AUTO-FIX (step 2d-5)
else:
  → EXHAUSTED (step 2d-7)
```

### 2d-5: Auto-fix iteration

```
# Backup current plan
ITER=$(jq '.iterations | length' "$STATE_FILE")
NEXT_ITER=$((ITER + 1))
cp "${PHASE_DIR}"/PLAN*.md "${PHASE_DIR}/PLAN.md.v${NEXT_ITER}"

# Write gap report
cat > "${PHASE_DIR}/GAPS-REPORT.md" <<EOF
# Gaps Report — Iteration $NEXT_ITER (Phase ${PHASE})

## Missing decisions (plan↔SPECS)
${decisions_missing[@]}

## Missing goals (plan↔TEST-GOALS)
${goals_missing[@]}

## Missing endpoints (plan↔API-CONTRACTS)
${endpoints_missing[@]}

## Instruction for planner
APPEND tasks covering the missing items. DO NOT rewrite existing tasks.
Match each new task to 1 missing `P{phase}.D-XX` / `F-XX`, G-XX, or endpoint.
EOF

# Spawn planner via SlashCommand with gap context
Agent(subagent_type="general-purpose", model="${MODEL_PLANNER}"):
  prompt: |
    <vg_planner_rules>
    @.claude/commands/vg/_shared/vg-planner-rules.md
    </vg_planner_rules>

    PATCH MODE — do NOT replace existing PLAN.md. APPEND tasks covering gaps.
    Read ${PHASE_DIR}/GAPS-REPORT.md for specific missing items.
    Read ${PHASE_DIR}/PLAN.md for existing task structure.
    Add new tasks at the end as "Gap closure wave".
    Follow vg-planner-rules for task attribute schema.

# Update state
jq --arg n "$NEXT_ITER" --argjson gaps "$(cat ...)" \
   '.iterations += [{n: ($n|tonumber), gaps_found: $gaps, plan_backup: ("PLAN.md.v" + $n), status: "failed", timestamp: now|strftime("%FT%TZ")}] |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

# Re-run granularity check (2a post-check), bidirectional linkage (2b5 post-check),
# grep verify (2c), compile check (2c2)
# Then loop back to 2d-3 validation
```

### 2d-6: CrossAI review (when gate PASSED)

**Skip conditions (any match → go to 2d-8):**
- `config.crossai_clis` is empty (no CLIs configured)
- `$ARGUMENTS` contains `--skip-crossai` (per-run opt-out)

Prepare context file at `${VG_TMP}/vg-crossai-{phase}-blueprint-review.md`:

```markdown
# CrossAI Blueprint Review — Phase {PHASE}

Gate passed deterministic validation. CrossAI reviews qualitative:

## Checklist
1. Plan covers all CONTEXT decisions (quick re-verify)
2. API contracts consistent with plan tasks
3. ORG 6 dimensions addressed (Infra/Env/Deploy/Smoke/Integration/Rollback)
4. Contract fields reasonable between request/response pairs
5. No duplicate endpoints or conflicting field definitions
6. Acceptance criteria are testable (not vague)
7. Design-refs linked appropriately (if config.design_assets non-empty)

## Verdict Rules
- pass: all checks pass, score >=7
- flag: minor quality concerns, score >=5
- block: missing/wrong content (deterministic gate should have caught — CrossAI as safety net)

## Artifacts
---
[CONTEXT.md content]
---
[PLAN*.md content — concatenated]
---
[API-CONTRACTS.md content]
---
[TEST-GOALS.md content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="blueprint-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

**Handle findings:**
- Minor → auto-fix (update contracts or plan)
- Major/Critical → present to user via AskUserQuestion, re-verify if fixed

**MANDATORY when escalating CrossAI concerns to user (AskUserQuestion):**

For EACH user-judgment concern (e.g., schema-vs-storage choice, architectural fork, test-strategy
trade-off), the orchestrator MUST present options with an explicit recommended option. Pattern:

1. **Pick the recommended option** before showing the question — base on:
   - CrossAI consensus (if 2+ CLIs converge on same fix → that's the recommendation)
   - Project context (CONTEXT.md decision wins over post-hoc PLAN drift)
   - Codebase reality (if existing pattern in repo, prefer aligning to it)
   - Security / correctness > convenience
2. **Order options with recommended FIRST**, label with " (Recommended)" suffix.
3. **Explain WHY recommended** in the option's `description` field — not just what it is.
4. **Do NOT ask without recommendation** — silent multi-option choices put rationalization burden on user.
   Per global guidance: "If you recommend a specific option, make that the first option in the
   list and add '(Recommended)' at the end of the label."

Bad example (no recommendation):
```
AskUserQuestion: "Refresh storage backend?"
  - Redis-only
  - Mongo collection
  - Both
```

Good example (with recommendation):
```
AskUserQuestion: "Refresh token storage backend? Recommend Both — Mongo source-of-truth survives
restart + Redis JTI cache provides fast revocation. CrossAI Codex flagged single-layer as conflict-prone."
  - Both (Mongo persist + Redis cache) (Recommended)  — production-grade, audit-friendly, fast revocation
  - Mongo only — simpler, slower revocation (each refresh checks DB)
  - Redis only — fast but loses sessions on restart
```

Apply this pattern to ALL CrossAI-escalation questions. The user can still pick a non-recommended
option (or "Other") — the recommendation just provides a default path so they don't have to
re-derive the analysis CrossAI just did.

### 2d-7: Exhausted — user intervention

```
echo "Plan validation exhausted after ${max_auto_fix_iterations} iterations."
echo "Remaining gaps:"
echo "  Decisions missing: ${decisions_missing[@]}"
echo "  Goals missing: ${goals_missing[@]}"
echo "  Endpoints missing: ${endpoints_missing[@]}"
echo ""
echo "Options:"
echo "  (a) /vg:blueprint ${PHASE} --override        → accept gaps, proceed with warning"
echo "  (b) Edit PLAN.md manually → /vg:blueprint ${PHASE} --from=2d"
echo "  (c) /vg:scope ${PHASE}                       → refine SPECS/CONTEXT (root cause may be spec gap)"

# Mark state exhausted, preserve for resume
jq '.steps_status["2d_validation"] = "exhausted"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
exit 1
```

### 2d-8: PASSED — finalize state

```
jq '.steps_status["2d_validation"] = "completed" |
    .current_step = "3_complete" |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
```

Display:
```
Plan validation: PASSED (iteration $N/${max})
  Decisions covered: $C/$total ($pct%)
  Goals covered: $C/$total ($pct%)
  Endpoints covered: $C/$total ($pct%)
  Mode: $MODE
CrossAI review: $verdict ($score/10)
Proceeding to commit.
```
</step>

<step name="3_complete">
Count plans, endpoints, decisions. Display:
```
Blueprint complete for Phase {N}.
  Plans: {N} created
  API contracts: {N} endpoints defined
  Verify 1 (grep): {verdict}
  CrossAI: {verdict} ({score}/10)
  Next: /vg:build {phase}
```

Commit all artifacts:
```bash
git add ${PHASE_DIR}/PLAN*.md ${PHASE_DIR}/API-CONTRACTS.md ${PHASE_DIR}/crossai/
git commit -m "blueprint({phase}): plans + API contracts — CrossAI {verdict}"
```
</step>

</process>

<success_criteria>
- CONTEXT.md verified as prerequisite
- PLAN*.md created via GSD planner with ORG check
- API-CONTRACTS.md generated from code + CONTEXT
- Verify 1 (grep) passed — contracts match code
- CrossAI reviewed (or skipped if no CLIs)
- All artifacts committed
- Next step guidance shows /vg:build
</success_criteria>
