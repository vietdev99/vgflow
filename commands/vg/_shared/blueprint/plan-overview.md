# blueprint plan group — STEP 3 (2a_plan)

HEAVY step. Original spec ~673 lines. You MUST delegate to the
`vg-blueprint-planner` subagent (tool name `Agent`, NOT `Task`).

<HARD-GATE>
You MUST spawn `vg-blueprint-planner` for step 2a_plan.
You MUST NOT generate PLAN.md inline.

The PreToolUse Bash hook blocks `vg-orchestrator step-active 2a_plan` until
TodoWrite signed evidence exists at
`.vg/runs/<run_id>/.tasklist-projected.evidence.json`.
</HARD-GATE>

---

## Orchestration order

The main agent runs THIS file's bash steps (pre-spawn setup, then spawn,
then post-spawn validation + marker). The agent prompt itself lives in
`plan-delegation.md` — read that file before calling Agent().

1. **Pre-spawn**: validate CONTEXT.md, rebuild graphify, build briefs, R5 size gate.
2. **Spawn**: `Agent(subagent_type="vg-blueprint-planner", prompt=<from delegation.md>)`
3. **Post-spawn**: validate path+sha256, run ORG check, granularity check,
   schema validation, mark-step + telemetry.

---

## STEP 3.1 — pre-spawn setup

### CONTEXT.md format validation (<5 sec)

```bash
vg-orchestrator step-active 2a_plan

CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"
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

### Auto-rebuild graphify BEFORE planner spawn

Mirrors `vg:build` step 4 logic. Without this, planner plans against stale
graph → references symbols that no longer exist → tasks fabricated.

```bash
if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
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

### Pre-spawn graphify context build (when GRAPHIFY_ACTIVE=true)

Extract structural context from graphify so planner can plan with
blast-radius awareness instead of grep-only guesses.

```bash
GRAPHIFY_BRIEF="${PHASE_DIR}/.graphify-brief.md"

if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
  # Orchestrator MUST query via mcp__graphify__god_nodes (Claude tool call):
  # 1. God nodes (top 20 by community_size + edge_count) — touch with care.
  # 2. Communities relevant to phase (grep CONTEXT endpoints + paths,
  #    query mcp__graphify__get_node + get_neighbors).
  # 3. Existing-symbol map for endpoints (avoid re-introducing names):
  #    grep CONTEXT "GET /api/..." → mcp__graphify__query_graph
  #    {"node_type":"route","path":"..."} → "EXISTS at file:line".
  # 4. Brief format (markdown, ≤150 lines):
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
  cat > "$GRAPHIFY_BRIEF" <<EOF
# Graphify brief — UNAVAILABLE
Graph not built or stale. Planner falls back to grep-only structural awareness.
Run: cd \$REPO_ROOT && \${PYTHON_BIN} -m graphify update .
EOF
fi
```

**Tool call note:** `mcp__graphify__god_nodes`, `get_node`, `get_neighbors`,
`query_graph` are Claude TOOL CALLS, not bash commands. Invoke via tool use
after the bash block computes variable inputs (CONTEXT endpoint list, file
path list). DO NOT shell-out — MCP round-trip is the supported path.

### deploy_lessons brief injection

Extract phase-relevant lessons + env vars from `.vg/DEPLOY-LESSONS.md` +
`.vg/ENV-CATALOG.md`, write `${PHASE_DIR}/.deploy-lessons-brief.md` for
planner injection.

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

# Infer services touched (grep heuristics)
service_hints = [
    ("apps/api",        [r"\bapi\b", r"fastify", r"modules?/", r"REST\s+API"]),
    ("apps/web",        [r"\bweb\b", r"\bdashboard\b", r"\bpage\b", r"\bReact\b", r"\bFE\b"]),
    ("apps/rtb-engine", [r"\brtb[_-]?engine\b", r"\baxum\b", r"\bbid\s+request\b"]),
    ("apps/workers",    [r"\bworkers?\b", r"\bconsumer\b", r"\bkafka\s+consumer\b"]),
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

name_lower = phase_dir.name.lower()
for svc, pats in service_hints:
    for pat in pats:
        if re.search(pat, name_lower, re.I):
            services_touched.add(svc)
            break

# Extract lessons by service from DEPLOY-LESSONS View A
lessons_by_service = {}
if lessons_file.exists():
    text = lessons_file.read_text(encoding="utf-8", errors="ignore")
    current_svc = None
    for line in text.splitlines():
        svc_m = re.match(r"^### ((?:apps|infra)/\S+)\s*$", line)
        if svc_m:
            current_svc = svc_m.group(1)
            lessons_by_service.setdefault(current_svc, [])
            continue
        if line.startswith("## View B"):
            break
        if current_svc:
            bullet = re.match(r"^-\s+\*\*Phase ([\d.]+):\*\*\s+(.+)$", line)
            if bullet:
                lessons_by_service[current_svc].append((bullet.group(1), bullet.group(2)))

# Extract env vars touched services from ENV-CATALOG
relevant_env = []
if env_file.exists():
    text = env_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        m = re.match(r"^\|\s*`(\w+)`\s*\|\s*([\d.]+)\s*\|\s*([^|]+)\s*\|", line)
        if not m:
            continue
        name, phase_added, service_list = m.groups()
        svc_tokens = re.split(r",\s*", service_list.strip())
        if any(t.strip() in services_touched for t in svc_tokens):
            relevant_env.append((name, phase_added, service_list.strip()))

out = ["# Deploy Lessons Brief — Phase-specific context cho planner", ""]
out.append(f"**Services touched:** {', '.join(sorted(services_touched)) or '(chưa xác định)'}")
out.append("")
if lessons_by_service:
    out.append("## Lessons từ phases trước (service-filtered)")
    out.append("")
    for svc in sorted(services_touched):
        items = lessons_by_service.get(svc, [])
        if not items:
            continue
        out.append(f"### {svc}")
        for pid, lesson in items:
            out.append(f"- **Phase {pid}:** {lesson}")
        out.append("")
else:
    out.append("_(DEPLOY-LESSONS.md chưa có lesson — phase đầu của v1.14.0+ flow.)_")
    out.append("")
if relevant_env:
    out.append("## Env vars liên quan (từ ENV-CATALOG)")
    out.append("")
    out.append("| Name | Added Phase | Service |")
    out.append("|---|---|---|")
    for name, pid, svc in relevant_env[:20]:
        out.append(f"| `{name}` | {pid} | {svc} |")
    out.append("")
out.append("## Hướng dẫn cho planner")
out.append("- ORG dim 3 (Deploy): reference lessons về build/restart timing.")
out.append("- ORG dim 4 (Smoke): include smoke check commands cho services touched.")
out.append("- ORG dim 6 (Rollback): reuse pattern từ phase trước cùng service.")
out.append("- Env vars liệt kê: tuân format reload/rotation/storage đã establish.")
brief_out.write_text("\n".join(out), encoding="utf-8")
print(f"✓ deploy_lessons brief: {brief_out} (services={len(services_touched)}, lessons={sum(len(v) for v in lessons_by_service.values())}, env_vars={len(relevant_env)})")
PY
else
  echo "ℹ DEPLOY-LESSONS.md / ENV-CATALOG.md chưa tồn tại — skip brief."
fi
```

### R5 prompt size gate (BLOCK if planner context > hard max)

Rule 5: max ~300 lines planner context recommended. Hard max from
`config.blueprint.planner_max_lines` (default 1200). Vượt = BLOCK.

```bash
R5_FILES=(
  "${PHASE_DIR}/.graphify-brief.md"
  "${PHASE_DIR}/.deploy-lessons-brief.md"
  "${PHASE_DIR}/SPECS.md"
  "${PHASE_DIR}/CONTEXT.md"
  ".claude/commands/vg/_shared/vg-planner-rules.md"
)
R5_TOTAL=0
R5_PER_FILE=""
for f in "${R5_FILES[@]}"; do
  if [ -f "$f" ]; then
    n=$(wc -l < "$f" 2>/dev/null | tr -d ' ')
    R5_TOTAL=$((R5_TOTAL + n))
    R5_PER_FILE="${R5_PER_FILE}\n    $(basename "$f"): ${n}"
  fi
done

R5_HARD_MAX="${CONFIG_BLUEPRINT_PLANNER_MAX_LINES:-1200}"
if [ "$R5_TOTAL" -gt "$R5_HARD_MAX" ]; then
  echo "⛔ R5 planner prompt overflow: ${R5_TOTAL} lines > hard max ${R5_HARD_MAX}"
  printf "Per-file breakdown:%b\n" "$R5_PER_FILE"
  echo ""
  echo "Nguyên nhân: SPECS.md/CONTEXT.md quá dài hoặc graphify god-node table to."
  echo "Override: /vg:blueprint ${PHASE_NUMBER} --override-reason='<reason>' (log debt)"
  echo "Raise: config.blueprint.planner_max_lines = ${R5_TOTAL} trong vg.config.md"
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    exit 1
  else
    type -t emit_telemetry_v2 >/dev/null 2>&1 && \
      emit_telemetry_v2 "blueprint_r5_planner_overflow" "${PHASE_NUMBER}" "blueprint.2a" "blueprint_r5_planner_overflow" "FAIL" "{}"
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "blueprint-r5-planner-overflow" "${PHASE_NUMBER}" "planner prompt ${R5_TOTAL} lines > ${R5_HARD_MAX}" "$PHASE_DIR"
    echo "⚠ --override-reason set — proceeding despite R5 breach"
  fi
else
  echo "✓ R5 planner prompt: ${R5_TOTAL} lines (hard max ${R5_HARD_MAX})"
fi
```

### Bootstrap rules injection

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"
```

---

## STEP 3.2 — spawn planner

Now read `plan-delegation.md` and use its prompt template to call:

```
Agent(subagent_type="vg-blueprint-planner", prompt=<rendered template>)
```

Wait for completion. Verify `${PHASE_DIR}/PLAN.md` exists.

---

## STEP 3.3 — post-spawn validation

### Validate planner return

1. Open returned `path`, recompute `sha256sum`, assert match.
2. Confirm PLAN.md ≥ 500 bytes.
3. Confirm `bindings_satisfied` covers required `must_cite_bindings`.
4. If any check fails: retry up to 2 times, then `AskUserQuestion` (Layer 3).

### Post-plan ORG 6-dimension check (Rule 6 — executable gate)

Deterministic parse via keyword matching per dimension. Missing CRITICAL
(Deploy/Rollback) → BLOCK. Missing NON-CRITICAL (Infra/Env/Smoke/Integration)
→ WARN + log.

```bash
ORG_CHECK_FILE="${PHASE_DIR}/.org-check-result.json"

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "${PHASE_DIR}" "${ORG_CHECK_FILE}" <<'PY'
import re, json, sys, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])

plan_files = sorted(glob.glob(str(phase_dir / "PLAN*.md")))
if not plan_files:
    print("⚠ ORG check: no PLAN*.md — skip gate")
    sys.exit(0)

plan_text = "\n".join(Path(p).read_text(encoding='utf-8', errors='ignore') for p in plan_files)
plan_lower = plan_text.lower()

DIMENSIONS = {
    1: {"name": "Infra",       "critical": False, "patterns": [r"\binstall\s+(clickhouse|redis|kafka|mongodb|postgres|nginx|haproxy)", r"\bansible\b.*\b(playbook|role)\b", r"\bprovision\b", r"\bn/a\s*[—-].*no\s+new\s+(infra|service)", r"\b(infra|service)\s+(existing|already|unchanged)"]},
    2: {"name": "Env",         "critical": False, "patterns": [r"\b(env|environment)\s+(var|variable|vars)", r"\.env\b", r"\bsecret(s)?\b.*\b(add|new|rotate)", r"\bvault\b", r"\benv\.j2\b", r"\bn/a\s*[—-].*no\s+new\s+env"]},
    3: {"name": "Deploy",      "critical": True,  "patterns": [r"\bdeploy\s+(to|on)\b", r"\brsync\b", r"\bpm2\s+(reload|restart|start)", r"\bsystemctl\s+(restart|start)", r"\bbuild\s+(and|then)\s+(deploy|restart)", r"\brun\s+on\s+(target|vps|sandbox)"]},
    4: {"name": "Smoke",       "critical": False, "patterns": [r"\bsmoke\s+(test|check)", r"\bhealth\s+check", r"\b/health\b", r"\bcurl\b.*\b(health|status|ping)", r"\bverif(y|ying)\s+(alive|running|up)"]},
    5: {"name": "Integration", "critical": False, "patterns": [r"\bintegration\s+(test|with)", r"\bE2E\b", r"\bconsumer\s+receives\b", r"\bend[-\s]to[-\s]end\b", r"\b(works|working)\s+with\s+(existing|phase)"]},
    6: {"name": "Rollback",    "critical": True,  "patterns": [r"\brollback\b", r"\brecover(y|y path)?\b", r"\bgit\s+(revert|reset)", r"\brestore\s+(from|backup|previous)", r"\brollback\s+plan", r"\bn/a\s*[—-].*(additive|backward|no\s+rollback\s+needed)"]},
}

results = {"dimensions": {}, "missing_critical": [], "missing_non_critical": []}
for num, dim in DIMENSIONS.items():
    addressed = any(re.search(pat, plan_lower, re.IGNORECASE) for pat in dim["patterns"])
    results["dimensions"][str(num)] = {"name": dim["name"], "critical": dim["critical"], "addressed": addressed}
    if not addressed:
        bucket = "missing_critical" if dim["critical"] else "missing_non_critical"
        results[bucket].append(f"{num}.{dim['name']}")

out_path.write_text(json.dumps(results, indent=2), encoding='utf-8')

addressed_count = sum(1 for d in results["dimensions"].values() if d["addressed"])
print(f"ORG check: {addressed_count}/{len(DIMENSIONS)} dimensions addressed")
for num, d in sorted(results["dimensions"].items()):
    marker = "✓" if d["addressed"] else "✗"
    crit = " [CRITICAL]" if d["critical"] else ""
    print(f"   {marker} {num}. {d['name']}{crit}")

if results["missing_critical"]:
    print(f"\n⛔ Rule 6 violation: missing CRITICAL: {', '.join(results['missing_critical'])}")
    print("   Deploy + Rollback are MANDATORY for any phase with code change.")
    sys.exit(2)
elif results["missing_non_critical"]:
    print(f"\n⚠ ORG warn: missing non-critical: {', '.join(results['missing_non_critical'])}")
    sys.exit(0)
else:
    print("✓ Rule 6: all 6 ORG dimensions addressed")
    sys.exit(0)
PY

ORG_RC=$?
if [ "$ORG_RC" = "2" ]; then
  echo "blueprint-r6-org-missing phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/blueprint-state.log"
  type -t emit_telemetry_v2 >/dev/null 2>&1 && \
    emit_telemetry_v2 "blueprint_r6_org_missing" "${PHASE_NUMBER}" "blueprint.2a5" "blueprint_r6_org_missing" "FAIL" "{}"
  if [[ "$ARGUMENTS" =~ --allow-missing-org ]]; then
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "blueprint-missing-org-critical" "${PHASE_NUMBER}" "missing critical ORG dims (Deploy/Rollback)" "$PHASE_DIR"
    echo "⚠ --allow-missing-org set — proceeding despite R6 breach"
  else
    echo "   Override (NOT recommended): --allow-missing-org"
    exit 1
  fi
fi
```

### Post-plan granularity check (R1-R5)

For each task in PLAN*.md, validate:

| Rule | Requirement | Severity |
|---|---|---|
| R1 file path | Task specifies `{file-path}` (not vague "can be in ...") | HIGH |
| R2 contract-ref | If task touches API → must cite `<contract-ref>API-CONTRACTS.md#{id} lines X-Y</contract-ref>` | HIGH |
| R3 goals-covered | Task has `<goals-covered>[G-XX]</goals-covered>` (or `no-goal-impact`) | MED |
| R4 design-ref | If FE page/component AND design_assets non-empty → cite `<design-ref>` | MED |
| R5 scope ≤ 250 LOC | Estimated LOC delta ≤ 250 | MED |

R2 contract-ref regex: `^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$`

```bash
R2_MALFORMED=0
for ref in $(grep -hoE '<contract-ref>[^<]+</contract-ref>' "${PHASE_DIR}"/PLAN*.md); do
  body=$(echo "$ref" | sed 's/<[^>]*>//g')
  if ! echo "$body" | grep -qE '^API-CONTRACTS\.md#[a-z0-9-]+ lines [0-9]+-[0-9]+$'; then
    echo "⛔ R2 malformed contract-ref: '$body' — expected 'API-CONTRACTS.md#{id} lines X-Y'"
    R2_MALFORMED=$((R2_MALFORMED + 1))
  fi
done
```

Inject warnings into PLAN.md as HTML comments (non-intrusive):

```markdown
## Task 04: Add POST /api/sites handler
**Scope:** apps/api/src/modules/sites/routes.ts

<!-- plan-warning:R2 missing <contract-ref> — task creates endpoint but doesn't cite API-CONTRACTS.md line range. -->

Implementation: ...
```

Warning budget:
- > 50% tasks have HIGH warnings → return to planner with feedback (loop to 2a)
- > 30% tasks have MED warnings → proceed; CrossAI review catches in step 2d

### Schema validation (BLOCK on PLAN.md frontmatter drift)

```bash
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact plan \
  > "${PHASE_DIR}/.tmp/artifact-schema-plan.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ PLAN.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-plan.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-plan.json"
  exit 2
fi
```

### Mark step + emit telemetry

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2a_plan" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2a_plan.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a_plan 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event blueprint.plan_written --phase "${PHASE_NUMBER}" 2>/dev/null || true
```

---

## STEP 3.4 — cross-system check (2a5_cross_system_check)

Scan existing codebase + prior phases to detect conflicts/overlaps BEFORE
contracts/code generation. Prevents phase isolation blindness.

**5 grep checks (no AI, <10 sec) + caller graph build:**

```bash
vg-orchestrator step-active 2a5_cross_system_check

API_ROUTES="${CONFIG_CODE_PATTERNS_API_ROUTES:-apps/api/src}"
WEB_PAGES="${CONFIG_CODE_PATTERNS_WEB_PAGES:-apps/web/src}"

# Check 1: Route conflicts — flag routes that already exist
EXISTING_ROUTES=$(grep -r "router\.\(get\|post\|put\|delete\|patch\)" "$API_ROUTES" \
  --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'/[^']+'" | sort -u)
if [ -n "$EXISTING_ROUTES" ]; then
  ROUTE_CONFLICTS=0
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    path=$(echo "$ep" | awk '{print $2}')
    if echo "$EXISTING_ROUTES" | grep -qF "'$path'"; then
      echo "⚠ route conflict: ${ep} — already exists in code, plan must UPDATE not CREATE"
      ROUTE_CONFLICTS=$((ROUTE_CONFLICTS + 1))
    fi
  done <<< "$(grep -oE '^### (POST|GET|PUT|DELETE|PATCH) /\S+' "${PHASE_DIR}/CONTEXT.md" 2>/dev/null)"
fi

# Check 2: Schema/model field conflicts (warn-only — model overlap requires AI judgment)
EXISTING_SCHEMAS=$(grep -r "z\.object\|Schema\|interface\s" "$API_ROUTES" \
  --include="*.ts" --include="*.js" -l 2>/dev/null | wc -l | tr -d ' ')
echo "Existing schema files in code: ${EXISTING_SCHEMAS}"

# Check 3: Shared component impact — high-traffic imports affecting other pages
SHARED_IMPACT=$(grep -r "import.*from.*components" "$WEB_PAGES" \
  --include="*.tsx" --include="*.jsx" -h 2>/dev/null | sort | uniq -c | sort -rn | head -20)
if [ -n "$SHARED_IMPACT" ]; then
  echo "Top-20 shared component imports (touch with care):"
  echo "$SHARED_IMPACT"
fi

# Check 4: Prior phase overlap — files this phase touches that prior SUMMARY*.md mentioned
PRIOR_OVERLAP=""
for summary in $(ls "${PHASES_DIR:-.vg/phases}"/*/SUMMARY*.md 2>/dev/null | tail -5); do
  if grep -lq "$(basename ${PHASE_DIR})" "$summary" 2>/dev/null; then
    PRIOR_OVERLAP="${PRIOR_OVERLAP}\n   - ${summary}"
  fi
done
[ -n "$PRIOR_OVERLAP" ] && printf "Prior phase overlap detected:%b\n" "$PRIOR_OVERLAP"

# Check 5: Database collection conflicts (mongo-style)
COLL_HOTSPOTS=$(grep -r "collection\(\|\.find\|\.insertOne\|\.updateOne" "$API_ROUTES" \
  --include="*.ts" --include="*.js" -h 2>/dev/null | grep -oE "'[^']+'" | sort | uniq -c | sort -rn | head -10)
[ -n "$COLL_HOTSPOTS" ] && echo "Top collection hotspots: $COLL_HOTSPOTS"

echo ""
echo "Cross-System Check summary:"
echo "  Route conflicts: ${ROUTE_CONFLICTS:-0}"
echo "  Existing schema files: ${EXISTING_SCHEMAS:-0}"
echo "  Prior phase overlap: $(echo -e "${PRIOR_OVERLAP:-}" | grep -c . || echo 0)"
echo "  Warnings injected into PLAN.md as <!-- cross-system-warning: ... -->"
echo ""
echo "No BLOCK — warnings only. Planner should address each in task descriptions."
```

**Caller graph build (semantic regression — Phase 13 retro fix):**

Build `.callers.json` mapping each PLAN task's `<edits-*>` symbols to all
downstream files using them. Build step 4e consumes this; commit-msg hook
enforces caller update or citation.

```bash
if [ "$(vg_config_get semantic_regression.enabled true)" = "true" ]; then
  GRAPHIFY_FLAG=""
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
    --phase-dir "${PHASE_DIR}" \
    --config .claude/vg.config.md \
    $GRAPHIFY_FLAG \
    --output "${PHASE_DIR}/.callers.json"

  CALLER_COUNT=$(jq '.affected_callers | length' "${PHASE_DIR}/.callers.json" 2>/dev/null || echo 0)
  TOOLS_USED=$(jq -r '.tools_used | join(",")' "${PHASE_DIR}/.callers.json" 2>/dev/null || echo "")
  echo "Semantic regression: tracked ${CALLER_COUNT} downstream callers (tools: ${TOOLS_USED})"

  # Sanity: graphify active but tools_used missing 'graphify' = grep-only fallback fired
  if [ "${GRAPHIFY_ACTIVE:-false}" = "true" ] && ! echo "$TOOLS_USED" | grep -q graphify; then
    echo "⚠ GRAPHIFY ENRICHMENT FAILED — graph active but caller-graph used grep-only."
    echo "  Inspect: ${PHASE_DIR}/.callers.json"
    echo "  Run: ${PYTHON_BIN} -c 'import json; json.load(open(\"$GRAPHIFY_GRAPH_PATH\"))'"
  fi
fi
```

**Phase 13 retro reminder:** when planner produces 22 tasks but only 3 have
`<edits-*>` annotations, caller script can only compute blast-radius for those
3. Other 19 silently get zero callers — appearing safe when many have downstream
impact. See `vg-planner-rules.md` — EVERY code-touching task MUST have ≥1
`<edits-*>` attribute.

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2a5_cross_system_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2a5_cross_system_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2a5_cross_system_check 2>/dev/null || true
```

After 2a5 marker touched, return to entry SKILL.md → STEP 4 (contracts).
