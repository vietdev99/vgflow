---
name: vg:map
description: Rebuild graphify knowledge graph + extract codebase-map.md for pipeline consumption
argument-hint: "[--force]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "map.started"
    - event_type: "map.completed"
---

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
