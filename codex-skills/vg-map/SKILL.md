---
name: "vg-map"
description: "Rebuild graphify knowledge graph + extract codebase-map.md for pipeline consumption"
metadata:
  short-description: "Rebuild graphify knowledge graph + extract codebase-map.md for pipeline consumption"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code and Codex now both have project-local hook substrates. VGFlow
`sync.sh`/`install.sh` installs `.codex/hooks.json` plus
`.codex/config.toml` with `[features].codex_hooks = true`. Codex hooks
wrap the same orchestrator that writes `.vg/events.db`, while command-body
guards remain mandatory because Codex hook coverage is still tool-path scoped:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Codex wrapper accepts both `/vg:cmd` and `$vg-cmd`; command-body `vg-orchestrator run-start` is still mandatory and must BLOCK if missing/failing |
| `PreToolUse` Bash -> `hooks/vg-pre-tool-use-bash.sh` | Blocks `vg-orchestrator step-active` until tasklist projection evidence is signed | Codex wrapper sets `CLAUDE_SESSION_ID`/`CLAUDE_HOOK_SESSION_ID` from Codex `session_id` and forwards to the same gate |
| `PreToolUse` Write/Edit -> `hooks/vg-pre-tool-use-write.sh` | Blocks direct writes to protected evidence, marker, and event paths | Codex `apply_patch` wrapper at `codex-hooks/vg-pre-tool-use-apply-patch.py` blocks the same protected paths before patch application |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Codex wrapper forwards Bash results to the same tracker; explicit `vg-orchestrator mark-step` lines remain required |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Codex wrapper runs the same verifier; command-body terminal `vg-orchestrator run-complete` is still required before claiming completion |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Codex hook processes cannot mutate the environment of later shell tool calls.
If a command-body shell lacks `CLAUDE_SESSION_ID`, `vg-orchestrator` recovers
the session from `.vg/.session-context.json` and the matching
`.vg/active-runs/<session>.json`. Do not create a fresh run when the
UserPromptSubmit hook already registered the same command/phase.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Do not manually retype long command-body heredocs into nested shell strings.
Prefer deterministic Codex helpers shipped in `.claude/scripts/`. For
`/vg:blueprint` STEP 3.1, run `codex-vg-env.py` and
`codex-blueprint-plan-prep.py` exactly as documented in
`_shared/blueprint/plan-overview.md`; then spawn the planner from the prepared
prompt. This avoids zsh glob/quote expansion corrupting Python heredocs before
Bash executes them.

Before running any command-body snippet that calls validators, orchestrator
helpers, or `${PYTHON_BIN:-python3}`, execute the Python detection block from
`.claude/commands/vg/_shared/config-loader.md` in that same Bash shell and
export the selected `PYTHON_BIN`. Do not reset `PYTHON_BIN=python3` after
detection: on macOS, bare `python3` is often an older interpreter without
PyYAML, which makes VG validators fail even though a valid Homebrew/Python.org
interpreter is installed.

Each Codex shell tool call starts with a fresh environment. If a later command
invokes `.claude/scripts/*`, validators, or `vg-orchestrator`, redetect
`PYTHON_BIN` or carry the previously detected absolute interpreter into that
same command. Do not run `python3 .claude/scripts/...` directly for VG
validators/orchestrator calls.

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

For tasklist projection, Codex must write evidence as soon as
`tasklist-contract.json` exists: after `emit-tasklist.py`, run
`vg-orchestrator tasklist-projected --adapter codex` as its own tool call.
Do not group `tasklist-projected` and `step-active` in one shell command;
PreToolUse evaluates the entire command before the evidence file exists and
will block the grouped command. Some command preflights have bootstrap steps
before `emit-tasklist.py`; only those declared bootstrap steps may run before
the tasklist contract exists.

For top-level VG commands that include a mandatory `git commit` step, ensure
the parent Codex session can write Git metadata. Some Codex
`workspace-write` sandboxes deny `.git/index.lock`; when that happens,
BLOCK and ask the operator to rerun with a sandbox/profile that permits Git
metadata writes instead of skipping or forging the commit marker.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --spawn-role "<vg-subagent-role>" \
  --spawn-id "<stable-spawn-id>" \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.
When `--spawn-role` is set, it also writes Codex spawn evidence to
`.vg/runs/<run_id>/codex-spawns/` and appends
`.vg/runs/<run_id>/.codex-spawn-manifest.jsonl`. Codex Bash hooks block
heavy-step markers and `wave-complete` when required spawn evidence or
build wave `.spawn-count.json` is missing.

When creating prompt files for `codex-spawn.sh`, use a single-quoted heredoc
delimiter such as `cat > "$PROMPT_FILE" <<'EOF'` or write from an existing
template. Do not use unquoted `<<EOF` for prompts that contain backticks,
`$...`, command substitutions, or markdown code fences: the shell will
expand them before Codex sees the prompt and can corrupt the child contract.
If runtime variables must be injected, prefer a small controlled render step
that substitutes placeholders after the quoted template is written.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-map`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for graphify settings, PYTHON_BIN, REPO_ROOT.
3. **Graphify required** — this command depends on graphify being installed and enabled in config.
4. **Stale detection** — warn if codebase-map.md exists but graph is outdated (> N commits).
5. **Idempotent** — safe to re-run. Overwrites codebase-map.md with fresh data.
6. **Read-only except codebase-map.md** — does not modify source code.
</rules>

<objective>
Rebuild the graphify knowledge graph from current codebase state and extract a structured codebase-map.md that other VG pipeline commands consume for context (god nodes, communities, cross-module edges).

Output: `${PLANNING_DIR}/codebase-map.md` (+ graphify-out/ updated as side effect)

Pipeline: project → roadmap → **map** → prioritize → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
## Step 0: Load Config

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

Variables needed from config-loader:
- `$PYTHON_BIN` — Python 3.10+ interpreter
- `$REPO_ROOT` — absolute path to repo root
- `$GRAPHIFY_ENABLED` — "true" or "false" from config
- `$GRAPHIFY_GRAPH_PATH` — absolute path to graph.json
- `$GRAPHIFY_ACTIVE` — "true" if enabled AND graph file exists
- `$GRAPHIFY_STALE_WARN` — commit threshold for staleness warning
- `$PLANNING_DIR` — planning directory path

```bash
# Parse flags
FORCE_REBUILD=false
for arg in $ARGUMENTS; do
  case "$arg" in
    --force) FORCE_REBUILD=true ;;
  esac
done

CODEBASE_MAP="${PLANNING_DIR}/codebase-map.md"
GRAPH_DIR=$(dirname "$GRAPHIFY_GRAPH_PATH")
GRAPH_REPORT="${GRAPH_DIR}/GRAPH_REPORT.md"
```
</step>

<step name="1_validate_graphify">
## Step 1: Validate Graphify Installation

**Check graphify is available:**

```bash
${PYTHON_BIN} -c "import graphify; print(graphify.__version__)" 2>/dev/null
```

If import fails:
```
Graphify is not installed. Install it:

  ${PYTHON_BIN} -m pip install 'graphifyy[mcp]'

Then enable in .claude/vg.config.md:
  graphify:
    enabled: true
    graph_path: "graphify-out/graph.json"
```
→ STOP.

**Check config enabled:**

If `$GRAPHIFY_ENABLED` != "true":
```
Graphify is installed but not enabled in config.
Enable in .claude/vg.config.md:
  graphify:
    enabled: true
```
→ STOP.
</step>

<step name="2_stale_detection">
## Step 2: Stale Detection

**If codebase-map.md exists AND --force is NOT set:**

```bash
# Check how many commits since codebase-map.md was last written
MAP_EPOCH=$(stat -c %Y "$CODEBASE_MAP" 2>/dev/null || stat -f %m "$CODEBASE_MAP" 2>/dev/null)
if [ -n "$MAP_EPOCH" ]; then
  COMMITS_SINCE_MAP=$(git log --since="@${MAP_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')
fi
```

**If graph.json exists:**

```bash
GRAPH_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
if [ -n "$GRAPH_EPOCH" ]; then
  COMMITS_SINCE_GRAPH=$(git log --since="@${GRAPH_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')
fi
```

**Decision logic:**

```
IF codebase-map.md exists AND COMMITS_SINCE_MAP <= 5 AND NOT FORCE_REBUILD:
  Print: "codebase-map.md is fresh (${COMMITS_SINCE_MAP} commits since last build). Use --force to rebuild."
  Print contents summary (node count, community count from existing file)
  → STOP (skip rebuild).

IF COMMITS_SINCE_MAP > $GRAPHIFY_STALE_WARN:
  Print: "Warning: ${COMMITS_SINCE_MAP} commits since last map build. Rebuilding..."

IF codebase-map.md does NOT exist:
  Print: "No codebase-map.md found. Building from scratch..."
```

Always proceed to step 3 if: no codebase-map.md, --force, or stale (>5 commits).
</step>

<step name="3_rebuild_graph">
## Step 3: Rebuild Knowledge Graph (incremental-aware, tightened 2026-04-17)

**NEW F12 incremental gate:** Before full rebuild, ask `graphify-incremental.py` whether full rebuild is actually needed. If only markdown/planning/doc files changed → skip. If structural files (package.json, tsconfig, vg.config) changed → full rebuild. If only code files changed → incremental (current graphify API only supports full rebuild; emit event for telemetry + do full).

```bash
MARKER="${CONFIG_PATHS_PLANNING_DIR:-.vg}/.graphify-last-rebuild"

if [[ ! "$ARGUMENTS" =~ --force ]] && [[ ! "$ARGUMENTS" =~ --full ]]; then
  DECISION=$(${PYTHON_BIN} .claude/scripts/graphify-incremental.py decide \
    --graph "$GRAPHIFY_GRAPH_PATH" \
    --marker "$MARKER" 2>/dev/null)
  RC=$?

  case "$DECISION" in
    skip:*)
      echo "⚡ $DECISION"
      if type -t emit_telemetry >/dev/null 2>&1; then
        emit_telemetry "graphify_skip" "" "map" "{\"reason\":\"${DECISION#skip: }\"}"
      fi
      # Proceed with codebase-map.md extraction only (steps 4+)
      SKIP_REBUILD=true
      ;;
    incremental:*)
      echo "🔄 $DECISION"
      # Current graphify API: full rebuild. Future: per-file incremental.
      # Emit event so telemetry tracks this as efficiency opportunity.
      if type -t emit_telemetry >/dev/null 2>&1; then
        N=$(echo "$DECISION" | grep -oE '[0-9]+' | head -1)
        emit_telemetry "graphify_incremental" "" "map" "{\"files_changed\":${N:-0}}"
      fi
      SKIP_REBUILD=false
      ;;
    full:*)
      echo "🔨 $DECISION — full rebuild required"
      SKIP_REBUILD=false
      ;;
  esac
fi

if [ "${SKIP_REBUILD:-false}" != "true" ]; then
  echo "Rebuilding graphify knowledge graph..."

  ${PYTHON_BIN} -c "
from graphify.watch import _rebuild_code
from pathlib import Path
_rebuild_code(Path('${REPO_ROOT}'))
" 2>&1

  if [ $? -ne 0 ]; then
    echo "Graph rebuild failed. Check graphify installation and repo structure."
    echo "Try: ${PYTHON_BIN} -m graphify update '${REPO_ROOT}'"
    # STOP on failure
  else
    echo "Graph rebuilt successfully."
    # Mark successful rebuild (F12)
    ${PYTHON_BIN} .claude/scripts/graphify-incremental.py mark --marker "$MARKER" 2>/dev/null || true
  fi
fi
```

**Verify output:**

```bash
# Confirm graph.json was written/updated
if [ ! -f "$GRAPHIFY_GRAPH_PATH" ]; then
  echo "Error: graph.json not found at $GRAPHIFY_GRAPH_PATH after rebuild."
  # STOP
fi
```
</step>

<step name="4_extract_stats">
## Step 4: Extract Graph Statistics

```bash
# Extract node count, edge count from graph.json
STATS=$(${PYTHON_BIN} -c "
import json
with open('${GRAPHIFY_GRAPH_PATH}', encoding='utf-8') as f:
    g = json.load(f)
nodes = g.get('nodes', [])
edges = g.get('edges', g.get('links', []))
print(f'{len(nodes)} {len(edges)}')
")
NODE_COUNT=$(echo "$STATS" | cut -d' ' -f1)
EDGE_COUNT=$(echo "$STATS" | cut -d' ' -f2)

echo "Graph: ${NODE_COUNT} nodes, ${EDGE_COUNT} edges"
```
</step>

<step name="5_extract_god_nodes">
## Step 5: Extract God Nodes (Top 10)

God nodes are files/modules with the highest connectivity (most imports/exports). They represent the architectural backbone.

```bash
${PYTHON_BIN} -c "
import json

with open('${GRAPHIFY_GRAPH_PATH}', encoding='utf-8') as f:
    g = json.load(f)

nodes = g.get('nodes', [])
edges = g.get('edges', g.get('links', []))

# Build degree map
degree = {}
for n in nodes:
    nid = n.get('id', n.get('name', ''))
    degree[nid] = {'in': 0, 'out': 0, 'label': n.get('label', nid)}

for e in edges:
    src = e.get('source', e.get('from', ''))
    tgt = e.get('target', e.get('to', ''))
    if src in degree:
        degree[src]['out'] += 1
    if tgt in degree:
        degree[tgt]['in'] += 1

# Sort by total degree
ranked = sorted(degree.items(), key=lambda x: x[1]['in'] + x[1]['out'], reverse=True)

print('| Rank | Node | In | Out | Total |')
print('|------|------|----|-----|-------|')
for i, (nid, d) in enumerate(ranked[:10], 1):
    total = d['in'] + d['out']
    label = d['label'] if d['label'] != nid else nid
    print(f'| {i} | {label} | {d[\"in\"]} | {d[\"out\"]} | {total} |')
" > "${VG_TMP}/god-nodes.txt" 2>&1
```

Store result for writing to codebase-map.md.
</step>

<step name="6_extract_communities">
## Step 6: Extract Communities

**Primary source:** Read `${GRAPH_REPORT}` if it exists (graphify generates GRAPH_REPORT.md with community analysis).

```bash
if [ -f "$GRAPH_REPORT" ]; then
  # Extract communities section from GRAPH_REPORT.md
  # Look for "## Communities" or "## Clusters" section
  COMMUNITIES_SECTION=$(${PYTHON_BIN} -c "
import re
with open('${GRAPH_REPORT}', encoding='utf-8') as f:
    content = f.read()

# Find communities section (## Communities or ## Clusters)
match = re.search(r'(## (?:Communities|Clusters).*?)(?=\n## |\Z)', content, re.DOTALL)
if match:
    print(match.group(1))
else:
    print('No communities section found in GRAPH_REPORT.md')
")
fi
```

**Fallback:** If GRAPH_REPORT.md has no communities section, derive from graph.json:

```bash
${PYTHON_BIN} -c "
import json
from collections import Counter

with open('${GRAPHIFY_GRAPH_PATH}', encoding='utf-8') as f:
    g = json.load(f)

nodes = g.get('nodes', [])

# Group by community/cluster field
communities = {}
for n in nodes:
    comm = n.get('community', n.get('cluster', n.get('group', 'uncategorized')))
    comm = str(comm)
    if comm not in communities:
        communities[comm] = []
    communities[comm].append(n.get('label', n.get('id', n.get('name', '?'))))

print(f'Found {len(communities)} communities')
print()
print('| Community | Nodes | Key Members |')
print('|-----------|-------|-------------|')
for comm_id, members in sorted(communities.items(), key=lambda x: -len(x[1])):
    top = ', '.join(members[:5])
    if len(members) > 5:
        top += f' (+{len(members)-5} more)'
    print(f'| {comm_id} | {len(members)} | {top} |')
" > "${VG_TMP}/communities.txt" 2>&1
```

Also extract cross-module edges (edges connecting nodes in different communities):

```bash
${PYTHON_BIN} -c "
import json

with open('${GRAPHIFY_GRAPH_PATH}', encoding='utf-8') as f:
    g = json.load(f)

nodes = g.get('nodes', [])
edges = g.get('edges', g.get('links', []))

# Build node → community map
node_comm = {}
for n in nodes:
    nid = n.get('id', n.get('name', ''))
    node_comm[nid] = str(n.get('community', n.get('cluster', n.get('group', '?'))))

# Find cross-community edges
cross = {}
for e in edges:
    src = e.get('source', e.get('from', ''))
    tgt = e.get('target', e.get('to', ''))
    c_src = node_comm.get(src, '?')
    c_tgt = node_comm.get(tgt, '?')
    if c_src != c_tgt:
        key = f'{c_src} → {c_tgt}'
        cross[key] = cross.get(key, 0) + 1

print('| From Community | To Community | Edge Count |')
print('|----------------|--------------|------------|')
for pair, count in sorted(cross.items(), key=lambda x: -x[1])[:15]:
    parts = pair.split(' → ')
    print(f'| {parts[0]} | {parts[1]} | {count} |')
" > "${VG_TMP}/cross-edges.txt" 2>&1
```
</step>

<step name="7_write_codebase_map">
## Step 7: Write codebase-map.md

Combine all extracted data into a structured document:

```markdown
# Codebase Map — {PROJECT_NAME}

Generated: {ISO date}
Graph: {NODE_COUNT} nodes, {EDGE_COUNT} edges, {COMMUNITY_COUNT} communities
Source: graphify knowledge graph (${GRAPHIFY_GRAPH_PATH})

## God Nodes (Top 10 by connectivity)

{god-nodes table from step 5}

**Interpretation:** God nodes are architectural hotspots. Changes to these files have the highest ripple effect. Phase plans touching god nodes need extra review.

## Communities

{communities table from step 6}

**Interpretation:** Each community is a cluster of tightly-connected files — roughly maps to a feature area or module.

## Cross-Module Edges

{cross-edges table from step 6}

**Interpretation:** High cross-edge count between communities indicates tight coupling. Phases touching multiple high-coupling communities may need sequential execution (not parallel).

## Usage in VG Pipeline

- **`/vg:scope`** — reads god nodes to identify high-risk decisions
- **`/vg:blueprint`** — reads communities to suggest task grouping
- **`/vg:build`** — reads cross-edges to detect file conflicts between parallel tasks
- **`/vg:review`** — reads god nodes to prioritize scan depth
```

Write to `${CODEBASE_MAP}`:

```bash
mkdir -p "${PLANNING_DIR}"
# Write codebase-map.md (content generated above)
```
</step>

<step name="8_summary">
## Step 8: Print Summary

```
Codebase map built.
  Graph: {NODE_COUNT} nodes, {EDGE_COUNT} edges, {COMMUNITY_COUNT} communities
  God nodes: {top 3 names}
  Written: ${CODEBASE_MAP}

  Next: /vg:prioritize — rank phases by impact + readiness
```

**Do NOT git commit** — codebase-map.md is a derived artifact (regenerated on demand). It should be gitignored or treated as ephemeral. Only commit if user explicitly requests it.
</step>

</process>

<success_criteria>
- graphify knowledge graph rebuilt successfully (graph.json updated)
- codebase-map.md written with: god nodes table, communities table, cross-module edges table
- Node count, edge count, community count reported accurately
- Stale detection works: skips rebuild if fresh (<= 5 commits), warns if very stale (> threshold)
- --force flag bypasses freshness check
- Error handling: clear messages if graphify not installed, not enabled, or rebuild fails
</success_criteria>
</output>
