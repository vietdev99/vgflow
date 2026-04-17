---
name: vg:review
description: Post-build review — code scan + browser discovery + fix loop + goal comparison → RUNTIME-MAP
argument-hint: "<phase> [--resume] [--skip-scan] [--skip-discovery] [--fix-only] [--skip-crossai] [--evaluate-only] [--retry-failed] [--full-scan]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
---

<TODOWRITE_POLICY>
**⛔ TODOWRITE PROTOCOL (read FIRST — prevents stuck UI tail across runs)**

If you (the executing model) use TodoWrite to track progress through this command:
1. **Your VERY FIRST tool call** must be a TodoWrite that REPLACES any stale todos from previous interrupted runs. Pass a fresh complete list (or even a single placeholder item) — TodoWrite overwrites the entire list, displacing items like "Phase 2b-1: Navigator" that hang from prior sessions.
2. **Mark each item completed immediately** when done — don't batch.
3. **Before returning (success OR error path)**: TodoWrite must end with NO `pending`/`in_progress` items. Mark anything remaining `completed` (even if not actually done — add a final item like "review-aborted-at-step-X" if needed).
4. **Better default**: prefer `narrate_phase` (echo to stdout) over TodoWrite for granular per-step progress. Echo lines don't kẹt UI tail. Reserve TodoWrite for ≤7 top-level milestones the user wants visible across the whole run.

This is a HARD requirement — stuck TodoWrite items from interrupted reviews are visible in user's UI tail until session restart.
</TODOWRITE_POLICY>

<rules>
1. **SUMMARY*.md required** — build must have completed. Missing = BLOCK.
2. **API-CONTRACTS.md required** — contracts must exist. Missing = BLOCK.
3. **Discovery-first** — AI explores the running app organically. No hardcoded checklists. No pre-scripted paths.
4. **Bấm → Nhìn → List → Đánh giá** — at every view: snapshot, evaluate data + actions, click each, observe result.
5. **Fix in review, verify in test** — review handles discovery + fix. Test handles clean goal verification only.
6. **RUNTIME-MAP is ground truth** — produced from actual browser interaction, not code guessing.
7. **Flexible format** — AI chooses best representation per page (tree, list, flow). No mandated table structure.
8. **State persistence** — discovery progress saved to discovery-state.json. Resumable after failure.
9. **Exploration limits** — max 50 actions/view, 200 total, 30 min wall time. Prevents runaway.
10. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
11. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    `create_task_tracker` preflight runs filter-steps.py to count expected steps for `$PROFILE`.
    Browser-based steps (phase 2 discovery) carry `profile="web-fullstack,web-frontend-only"` — skipped for backend-only/cli/library.
</rules>

<objective>
Step 4 of V5.1 pipeline. Replaces old "audit" step. Combines static code scan + live browser discovery + iterative fix loop + goal comparison.

Pipeline: specs → scope → blueprint → build → **review** → test → accept

4 Phases:
- Phase 1: CODE SCAN — grep contracts + count elements (fast, automated, <10 sec)
- Phase 2: BROWSER DISCOVERY — MCP Playwright organic exploration → RUNTIME-MAP
- Phase 3: FIX LOOP — errors found → fix → redeploy → re-discover (max 3 iterations)
- Phase 4: GOAL COMPARISON — map TEST-GOALS to discovered paths → weighted gate
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

<CRITICAL_MCP_RULE>
**BEFORE any browser interaction**, you MUST run the Playwright lock claim:
```bash
SESSION_ID="vg-${PHASE}-review-$$"
PLAYWRIGHT_SERVER=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
# Auto-release lock on exit (normal/error/interrupt). Prevents leak if process dies mid-scan.
trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
```
Then use `mcp__${PLAYWRIGHT_SERVER}__` as prefix for ALL browser tool calls.

**NEVER call `plugin:playwright:playwright` directly.** Other sessions (Codex, other tabs) may be using it.
If claim returns `playwright3`, your tools are `mcp__playwright3__browser_navigate`, `mcp__playwright3__browser_snapshot`, etc.
If ALL 5 servers locked → BLOCK. The lock manager auto-sweeps stale locks (TTL 1800s + dead-PID check)
on every claim — if still no slot free, it's genuinely contended. Do NOT manually cleanup other sessions' locks.
</CRITICAL_MCP_RULE>

<step name="00_session_lifecycle">
**Session lifecycle (tightened 2026-04-17) — clean tail UI across runs.**

Follow `.claude/commands/vg/_shared/session-lifecycle.md` helper.

```bash
PHASE_NUMBER=$(echo "$ARGUMENTS" | awk '{print $1}')
PHASE_DIR_CANDIDATE=$(ls -d .planning/phases/${PHASE_NUMBER}* 2>/dev/null | head -1)

# Emit session-start banner → distinct separator for Claude Code tail UI
session_start "review" "${PHASE_NUMBER:-unknown}"
# Register EXIT trap emitting "━━━ review Phase X EXITED at step=Y ━━━" on any exit path
# Sweep stale state from previous interrupted runs (>config.session.stale_hours old)
[ -n "$PHASE_DIR_CANDIDATE" ] && stale_state_sweep "review" "$PHASE_DIR_CANDIDATE"
# Kill orphan dev servers on declared ports before pre-flight
[ "${CONFIG_SESSION_PORT_SWEEP_ON_START:-true}" = "true" ] && session_port_sweep "pre-flight"

session_mark_step "0-parse-args"
```
</step>

<step name="0_parse_and_validate">
Parse `$ARGUMENTS`: phase_number, flags.

Flags:
- `--resume` — load discovery-state.json, continue from last position
- `--skip-scan` — skip Phase 1 (code scan), go directly to browser discovery
- `--skip-discovery` — skip Phase 2 (browser discovery), use existing RUNTIME-MAP for Phase 4
- `--fix-only` — skip to Phase 3 (requires RUNTIME-MAP with errors)
- `--skip-crossai` — skip CrossAI review at end
- `--evaluate-only` — skip Phase 1 + 2 (discovery already done by Codex/Gemini), read existing scan JSONs from ${PHASE_DIR}, go directly to Phase 2b-3 (collect + merge) → Phase 3 (fix) → Phase 4 (goal comparison). Requires: nav-discovery.json + scan-*.json already exist.
- `--retry-failed` — skip Phase 1 + Phase 2 navigator, re-scan ONLY views mapped to failed/blocked goals in GOAL-COVERAGE-MATRIX.md. Requires: GOAL-COVERAGE-MATRIX.md + RUNTIME-MAP.json already exist. Use when: review already ran but goals < 100%, code was fixed, need targeted re-scan without full re-discovery.
- `--full-scan` — disable sidebar suppression. Haiku agents see full page (sidebar/header/footer) in every snapshot. Use when: app has non-standard layout, geometry detection fails, or debugging suppression issues.
- `--with-probes` — enable mutation probe variations (edit/boundary/repeat) in step 2b-3 step 9. Adds 1 Haiku per mutation goal. Default OFF — let /vg:test handle variations via Playwright codegen (deterministic, cheaper).

Validate:
- `${PHASE_DIR}/SUMMARY*.md` exists → build completed
- `${PHASE_DIR}/API-CONTRACTS.md` exists → contracts available

Missing → BLOCK with guidance.

**Update PIPELINE-STATE.json:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'reviewing'; s['pipeline_step'] = 'review'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```
</step>

<step name="create_task_tracker">
Create tasks for progress tracking — granular sub-steps so user sees exactly what's happening:
```
TaskCreate: "1a: Contract verify (grep)"            (activeForm: "Grepping BE routes vs contracts...")
TaskCreate: "1b: Element inventory"                 (activeForm: "Counting UI elements per file...")
TaskCreate: "1.5: Graphify ripple analysis"         (activeForm: "Scanning cross-module callers...")
TaskCreate: "2a: Deploy + preflight"                (activeForm: "Deploying to {ENV}, checking health...")
TaskCreate: "2b-1: Navigator discovers views"       (activeForm: "Haiku navigator scanning sidebar...")
TaskCreate: "2b-2: Haiku scanners (per view)"       (activeForm: "Spawning {N} Haiku agents for {N} views...")
TaskCreate: "2b-3: Merge + evaluate scan results"   (activeForm: "Merging Haiku results, evaluating coverage...")
TaskCreate: "2.5: Visual integrity checks"          (activeForm: "Checking fonts, overflow, responsive...")
TaskCreate: "3: Fix loop"                           (activeForm: "Fixing {N} issues, iteration {I}/3...")
TaskCreate: "4a: Load goals + filter infra deps"    (activeForm: "Parsing {N} goals, checking infra availability...")
TaskCreate: "4b: Map goals to RUNTIME-MAP"          (activeForm: "Mapping {N} goals to discovered views...")
TaskCreate: "4c: Weighted gate evaluation"          (activeForm: "Evaluating gate: critical 100%, important 80%...")
TaskCreate: "4d: Write GOAL-COVERAGE-MATRIX"        (activeForm: "Writing coverage matrix...")
```

**Dynamic update rule:** As each sub-step runs, update activeForm with concrete values:
- "2b-2: Spawning Haiku scanners" → "2b-2: Scanning /conversions as advertiser (3/7 views)"
- "3: Fix loop" → "3: Fixing Bug #2: S2SSecretSection crash (iter 1/3)"
- "4a: Load goals" → "4a: 38 goals loaded, 16 INFRA_PENDING (ClickHouse, pixel_server)"
</step>

<step name="phase1_code_scan">
## Phase 1: CODE SCAN (automated, <10 sec)

**If --skip-scan, skip this phase.**

### 1a: Contract Verify (grep)

Read `.claude/skills/api-contract/SKILL.md` — Mode: Verify-Grep.
Read `.claude/commands/vg/_shared/env-commands.md` — contract_verify_grep(phase_dir, "both").

Run contract_verify_grep against `$SCAN_PATTERNS` paths from config:
- BE routes vs API-CONTRACTS.md endpoints
- FE API calls vs API-CONTRACTS.md endpoints

Result:
- 0 mismatches → PASS
- Mismatches → WARNING (not block — browser discovery will confirm)

### 1b: Element Inventory (grep — reference data, NOT gate)

Count UI elements using `$SCAN_PATTERNS` from config:

```
For each source file matching config.code_patterns.web_pages:
  Run element_count(file) from env-commands.md
  → uses SCAN_PATTERNS keys (modals, tables, forms, actions, etc.)
```

Write `${PHASE_DIR}/element-counts.json` — **reference data** for discovery (not a gate).

### 1c: i18n Key Resolution Check (config-gated)

**Skip conditions:**
- `config.i18n.enabled` is false or absent → skip entirely
- `config.i18n.locale_dir` is empty → skip

**Purpose:** Verify every i18n key used in phase-changed FE files actually resolves to a
translation string. Missing keys = user sees raw key like `dashboard.title` instead of text.

```bash
I18N_ENABLED="${config.i18n.enabled:-false}"
if [ "$I18N_ENABLED" = "true" ]; then
  LOCALE_DIR="${config.i18n.locale_dir}"
  DEFAULT_LOCALE="${config.i18n.default_locale:-en}"
  KEY_FN="${config.i18n.key_function:-t}"

  # Get FE files changed in this phase
  CHANGED_FE=$(git diff --name-only HEAD~${COMMIT_COUNT:-5} HEAD -- "${config.code_patterns.web_pages}" 2>/dev/null)

  if [ -n "$CHANGED_FE" ] && [ -d "$LOCALE_DIR" ]; then
    # Extract all i18n keys from changed files
    I18N_KEYS=$(echo "$CHANGED_FE" | xargs grep -ohE "${KEY_FN}\(['\"]([^'\"]+)['\"]\)" 2>/dev/null | \
      grep -oE "['\"][^'\"]+['\"]" | tr -d "'" | tr -d '"' | sort -u)

    # Check each key resolves in default locale file
    LOCALE_FILE=$(find "$LOCALE_DIR" -path "*/${DEFAULT_LOCALE}*" -name "*.json" 2>/dev/null | head -1)
    MISSING_KEYS=0

    if [ -n "$LOCALE_FILE" ] && [ -n "$I18N_KEYS" ]; then
      while IFS= read -r KEY; do
        [ -z "$KEY" ] && continue
        # Check key exists in JSON (dot-path → nested lookup)
        EXISTS=$(${PYTHON_BIN} -c "
import json, sys
from pathlib import Path
data = json.loads(Path('$LOCALE_FILE').read_text())
keys = '$KEY'.split('.')
ref = data
for k in keys:
    if isinstance(ref, dict) and k in ref:
        ref = ref[k]
    else:
        print('MISSING')
        sys.exit(0)
print('OK')
" 2>/dev/null)
        if [ "$EXISTS" = "MISSING" ]; then
          echo "  WARN: i18n key '$KEY' not found in ${LOCALE_FILE}"
          MISSING_KEYS=$((MISSING_KEYS + 1))
        fi
      done <<< "$I18N_KEYS"
    fi

    echo "i18n check: $(echo "$I18N_KEYS" | wc -l) keys, ${MISSING_KEYS} missing"
  fi
fi
```

Result routing: `MISSING_KEYS > 0` → GAPS_FOUND (not block — may be added in later commit).

Display:
```
Phase 1 Code Scan:
  Contract verify: {PASS|WARNING — N mismatches}
  Element inventory: {N} files, ~{M} interactive elements
  i18n key check: {N keys checked, M missing|skipped (disabled)}
  (Reference data for Phase 2 — not a gate)
```
</step>

<step name="phase1_5_ripple_and_god_node">
## Phase 1.5: GRAPHIFY IMPACT ANALYSIS (cross-module ripple + god node coupling)

**Purpose**: retroactive safety net for changes that affect callers outside the phase's changed-files list. Complement to /vg:build's proactive caller graph.

**Prereq**: `_shared/config-loader.md` already resolved `$GRAPHIFY_ACTIVE`, `$GRAPHIFY_GRAPH_PATH`, `$PYTHON_BIN`, `$REPO_ROOT`, `$VG_TMP` at command start.

```bash
if [ "$GRAPHIFY_ACTIVE" != "true" ]; then
  echo "ℹ Graphify not available — skipping Phase 1.5"
  touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"
  # skip to Phase 2
fi
```

If graphify active, proceed:

### A. Collect phase's changed files (in bash)

```bash
# Prefer phase commit range if available (git tag from /vg:build step 8b: "vg-build-{phase}-wave-{N}-start")
PHASE_START_TAG=$(git tag --list "vg-build-${PHASE_NUMBER}-wave-*-start" | sort -t'-' -k5,5n | head -1)
if [ -n "$PHASE_START_TAG" ]; then
  CHANGED_FILES=$(git diff --name-only "$PHASE_START_TAG" HEAD | sort -u)
else
  # Fallback: diff against merge-base with main
  CHANGED_FILES=$(git diff --name-only $(git merge-base HEAD main) HEAD | sort -u)
fi

# Filter to source files only (exclude .planning/, .claude/, node_modules, etc)
CHANGED_SRC=$(echo "$CHANGED_FILES" | grep -vE '^\.(planning|claude|codex)/|/node_modules/|/dist/|/build/|/target/|^graphify-out/' || true)

echo "Phase changed $(echo "$CHANGED_SRC" | wc -l) source files"
echo "$CHANGED_SRC" > "${PHASE_DIR}/.ripple-input.txt"
```

### B. Ripple analysis (bash — hybrid script, no MCP)

**Why script not MCP**: graphify TS extractor doesn't resolve path aliases (e.g., `@/hooks/X` → `src/hooks/X`). Pure MCP queries miss alias-imported callers. The hybrid script uses graphify + git grep, catches both.

```bash
${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
  --changed-files-input "${PHASE_DIR}/.ripple-input.txt" \
  --config .claude/vg.config.md \
  --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
  --output "${PHASE_DIR}/.ripple.json"
```

Output (`.ripple.json`):
```json
{
  "mode": "ripple",
  "tools_used": ["grep(rg|git)", "graphify"],
  "changed_files_count": N,
  "ripples": [
    {
      "changed_file": "<path>",
      "exports_at_risk": ["SymbolA", "SymbolB"],
      "callers": [
        {"file": "<caller>", "line": N, "symbol": "SymbolA", "source": ["grep(...)"]}
      ]
    }
  ],
  "affected_callers": ["<unique caller paths>"]
}
```

Script extracts exports via stack-agnostic regex (TS/JS/Rust/Python/Go), then searches scope_apps for each symbol using grep + graphify enrichment. Every caller NOT in the changed list = at-risk.

### C. God node coupling check (bash — Python API, no MCP)

```bash
${PYTHON_BIN} - <<'PY' > "${PHASE_DIR}/.god-nodes.json"
import json
from graphify.analyze import god_nodes
from graphify.build import build_from_json
from networkx.readwrite import json_graph
from pathlib import Path
data = json.loads(Path("${GRAPHIFY_GRAPH_PATH}").read_text(encoding="utf-8"))
G = json_graph.node_link_graph(data, edges="links")
gods = god_nodes(G)[:20]  # top-20 highest-degree nodes
print(json.dumps([{"label": g.get("label"), "source_file": g.get("source_file"), "degree": g.get("degree")} for g in gods], indent=2))
PY
```

Then for each god node, check if `git diff $PHASE_START_TAG HEAD` includes lines adding an import pointing to god_node's source_file — flag as coupling warning (language-aware via config.scan_patterns).

### D. Classify caller severity (orchestrator memory, post-script)

Script returns `callers` list per changed file. Orchestrator classifies:
- **HIGH**: caller's `symbol` match is a function/class/schema name (likely direct usage)
- **LOW**: caller matches only via barrel import (symbol is the filename itself, or in a re-export block)

Default LOW for ambiguous — reverse of earlier design. Rationale: too many HIGH = noise → users ignore. Start LOW, escalate via evidence.

### D. Write RIPPLE-ANALYSIS.md

Write `${PHASE_DIR}/RIPPLE-ANALYSIS.md`:

```markdown
# Phase {N} — Ripple Analysis (Graphify)

**Generated**: {ISO timestamp}
**Changed files in phase**: {N}
**Graph**: `graphify-out/graph.json` ({node_count} nodes)

## High-Severity Ripples (REVIEW REQUIRED)

Callers of changed code that were NOT updated in this phase. Verify these callers still work with the new symbol shapes.

| Caller File | Calls Changed Symbol | Changed In | Severity |
|---|---|---|---|
| {caller.file} | {symbol} | {changed.file} | HIGH |
| ... | ... | ... | ... |

## Low-Severity Ripples (likely safe — scan for regressions)

| Caller File | Import Type | Changed In |
|---|---|---|
| {caller.file} | barrel re-export | {changed.file} |

## God Node Coupling Warnings

| God Node | Degree | New Edge From | Recommendation |
|---|---|---|---|
| {god.label} | {N} | {changed.file} | Refactor consideration |

## Summary

- HIGH ripples: {N}  (review these callers manually or via browser)
- LOW ripples: {N}
- God node warnings: {N}
- Action: Phase 2 browser discovery will prioritize checking HIGH-ripple caller paths first
```

### E. Inject findings into Phase 2 + Phase 4

**Phase 2 priority hint**: if ripple affects a specific view, browser discovery should navigate there first (higher priority in scan queue). Save `.ripple-browser-priorities.json`:

```json
{ "priority_urls": ["route1", "route2"], "reason": "high-ripple callers live here" }
```

**Phase 4 goal comparison input**: include RIPPLE-ANALYSIS.md as evidence. If a goal says "Feature X works" and Feature X uses a HIGH-ripple caller that wasn't verified → flag as UNVERIFIED instead of READY.

### Fallback (graphify disabled, empty graph, or MCP errors)

Skip Phase 1.5 with warning:
```
ℹ Phase 1.5 skipped — graphify not active. Cross-module ripple bugs may
  only be caught at Phase 2 browser discovery or Phase 5 test. To enable:
  set graphify.enabled=true in .claude/vg.config.md + graphify update .
```

Still write empty `RIPPLE-ANALYSIS.md` stub so Phase 4 doesn't error on missing file:
```
# Phase {N} — Ripple Analysis (SKIPPED)

Graphify inactive. Enable for cross-module impact detection.
```

Final action: `touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"`
</step>

<step name="phase2_browser_discovery" profile="web-fullstack,web-frontend-only">
## Phase 2: BROWSER DISCOVERY (MCP Playwright — organic)

**🎬 Live narration protocol (tightened 2026-04-17 — user theo dõi flow):**

Orchestrator PHẢI in dòng tiếng người BEFORE mỗi sub-phase + BEFORE mỗi view/goal đang xử lý. Khác test.md: review chạy parallel nhiều Haiku, narration ở orchestrator level không cần per-step.

```bash
narrate_phase() {
  # $1=phase_name, $2=intent tiếng Việt
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "🔎 $1"
  echo "   $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

narrate_view_scan() {
  # $1=view_url, $2=idx, $3=total, $4=roles, $5=element_count
  echo "  [${2}/${3}] 📄 Đang scan: ${1}  (role: ${4}, ~${5} elements)"
}

narrate_view_done() {
  # $1=view_url, $2=status, $3=issues_count, $4=duration_s
  case "$2" in
    ok)      echo "       ✓ Scan xong — ${3} issues phát hiện (${4}s)" ;;
    partial) echo "       ⚠ Scan 1 phần — ${3} issues (${4}s)" ;;
    fail)    echo "       ❌ Scan lỗi — xem discovery-state.json" ;;
  esac
}

narrate_goal_flow() {
  # $1=gid, $2=title, $3=idx, $4=total
  echo ""
  echo "  ▶ Flow [${3}/${4}] ${1}: ${2}"
}

narrate_goal_flow_step() {
  # $1=n, $2=total, $3=action_vn, $4=target
  echo "      ${1}/${2} → ${3} ${4}"
}

narrate_goal_flow_end() {
  # $1=gid, $2=status (passed|failed|blocked), $3=steps_captured, $4=reason
  case "$2" in
    passed)  echo "      ✅ Flow ${1} ghi ${3} bước, ready for /vg:test" ;;
    failed)  echo "      ❌ Flow ${1} fail — ${4}" ;;
    blocked) echo "      ⚠ Flow ${1} blocked — ${4}" ;;
  esac
}
```

Ví dụ user thấy khi `/vg:review` chạy:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2a — Deploy + preflight
   Triển khai code lên sandbox, kiểm tra health + seed data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Deploy OK (sha abc1234)
  ✓ Health: https://sandbox.example.com/health → 200
  ✓ Seed: 12 sites, 48 campaigns loaded

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-1 — Navigator (Haiku)
   Login, đọc sidebar, liệt kê tất cả views
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Phát hiện 14 views: /sites, /campaigns, /reports, /settings, ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-2 — Parallel scanners (8 Haiku agents)
   Mỗi agent scan 1 view: modals, forms, interactions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1/14] 📄 Đang scan: /sites  (role: publisher, ~32 elements)
         ✓ Scan xong — 2 issues phát hiện (12s)
  [2/14] 📄 Đang scan: /campaigns  (role: advertiser, ~48 elements)
         ✓ Scan xong — 0 issues (8s)
  [3/14] 📄 Đang scan: /reports  (role: admin, ~15 elements)
         ⚠ Scan 1 phần — 3 issues (14s)
  ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 2b-3 — Goal sequence recording
   Ghi lại chuỗi thao tác cho từng business goal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ▶ Flow [1/8] G-01: Tạo site mới với domain + brand safety
      1/5 → 📍 Mở /sites
      2/5 → 👆 Bấm "New Site"
      3/5 → ⌨️  Điền domain
      4/5 → 🔽 Chọn category
      5/5 → ✓ Xác nhận toast "Site created"
      ✅ Flow G-01 ghi 5 bước, ready for /vg:test

  ▶ Flow [2/8] G-02: Edit site floor price
      1/4 → ...
      ❌ Flow G-02 fail — button "Edit" không tìm thấy trên row

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔎 Phase 3 — Fix loop (iteration 1/3)
   Sửa các bug MINOR, re-verify affected views
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Fixed: /reports missing empty-state (1 file changed)
  ✓ Re-scan /reports: 0 issues
  ⚠ 2 MAJOR issues escalated to REVIEW-FEEDBACK.md
```

**Rule:** narrator gọi ở các điểm sau trong phase 2:
- Trước 2a deploy → `narrate_phase "Phase 2a — Deploy" "Triển khai + health"`
- Trước 2b-1 navigator → `narrate_phase "Phase 2b-1 — Navigator" "Login, đọc sidebar..."`
- Sau navigator → in `Phát hiện N views: ...`
- Trước 2b-2 spawn → `narrate_phase "Phase 2b-2 — Parallel scanners"` + `Spawning N Haiku agents...`
- Khi mỗi Haiku scan xong (poll scan-*.json) → `narrate_view_scan` + `narrate_view_done`
- Trước goal sequence recording → `narrate_phase "Phase 2b-3 — Goal flows" "Ghi chuỗi thao tác..."`
- Mỗi goal → `narrate_goal_flow` + step loop + `narrate_goal_flow_end`
- Trước Phase 3 fix → `narrate_phase "Phase 3 — Fix loop" "Iteration {i}/3..."`

**If --skip-discovery, skip to Phase 4.**
**If --resume, load discovery-state.json and continue from queue.**
**If --evaluate-only, skip to Phase 2b-3 (collect + merge scan results) → Phase 3 → Phase 4.**
  Validate: ${PHASE_DIR}/nav-discovery.json AND at least 1 scan-*.json must exist.
  Missing → BLOCK: "Run discovery first: `$vg-review {phase} --discovery-only` in Codex/Gemini."

**If --retry-failed:**
  Validate: ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md AND ${PHASE_DIR}/RUNTIME-MAP.json exist.
  Missing → BLOCK: "Run `/vg:review {phase}` first to generate initial artifacts."

  Parse GOAL-COVERAGE-MATRIX.md → collect all goals where status ≠ READY (BLOCKED, UNREACHABLE, FAILED, PARTIAL).
  If none found → print "All goals already READY. Nothing to retry." → skip to Phase 4.

  Parse RUNTIME-MAP.json → for each failed goal_id:
    start_view = goal_sequences[goal_id].start_view
  RETRY_VIEWS[] = unique(all start_views), with roles from RUNTIME-MAP views[start_view].role

  Print: "Retry mode: {N} failed goals → {M} views to re-scan: {RETRY_VIEWS[]}"

  Skip Phase 1 (code scan). Skip 2b-0 (seed). Skip 2b-1 (navigator — reuse existing nav-discovery.json).
  Go directly to 2b-2 using RETRY_VIEWS[] as view_assignments (NOT view-assignments.json).

### 2a: Deploy + Environment Prep

Deploy to target environment:
```
1. Record SHAs (local + target)
2. Build + restart on target
3. Health check → if fail → PRE-FLIGHT BLOCK (see below)
4. DB seed (if configured): run_on_target "${config.environments[ENV].seed_command}"
   (skip if seed_command not in config — portable)
5. Auth bootstrap (if configured):
   For each role in config.credentials[ENV]:
     Run config.environments[ENV].auth_command with role credentials
     Save response token for API checks below
   (skip if auth_command not in config — MCP login handles auth instead)
```

Read `.claude/commands/vg/_shared/env-commands.md` — deploy(env) + preflight(env).

### 2a-preflight: INFRASTRUCTURE READINESS GATE

**Review fix loop can only fix CODE bugs. Infra failures (missing config, app down, domain unreachable) must be fixed BEFORE review can work.**

Before entering Phase 2 browser discovery, verify:

```
PRE-FLIGHT CHECKLIST:
[ ] Build succeeded (exit 0, no TS/Rust compile errors)
[ ] Restart succeeded (pm2/systemd/dev_command exited 0, service running)
[ ] Health endpoint(s) return 200 — all entries in config.services[ENV]
[ ] All role domains from config.credentials[ENV] resolve + return any response (not ERR_CONNECTION)
[ ] At least 1 role can login successfully (curl auth endpoint, or MCP smoke login)
```

**If ANY pre-flight fails → BLOCK review with DIAGNOSTIC + FIX GUIDANCE:**

```
⛔ PRE-FLIGHT FAILED — review cannot proceed.

The review step fixes code bugs, not infrastructure. Fix the infra issue below, then re-run.

Issues detected:
  [1] {category}: {specific error}
      Example: "Build: ecosystem.config.js missing at apps/api/"
      Example: "Health: api.{domain}/health returned 502"
      Example: "Domain: advertiser.{domain} ERR_CONNECTION_REFUSED"
      Example: "Login: admin@{domain} POST /auth/login returned 500"

┌─ What to fix (by category) ─────────────────────────────────┐
│ Build failure      → Check compile errors, missing files,   │
│                      dependency conflicts. Fix then retry.  │
│                      Common: missing ecosystem.config.js,   │
│                      .env, turbo task, tsconfig paths.      │
│                                                             │
│ Health endpoint    → Service didn't start or crashed.       │
│                      Check logs: pm2 logs / journalctl /    │
│                      dev server output. Usually missing     │
│                      env var, DB down, port conflict.       │
│                                                             │
│ Domain unreachable → Hostname not resolving or not served.  │
│                      Local: check /etc/hosts + dev proxy.   │
│                      Sandbox: check DNS + HAProxy/nginx.    │
│                                                             │
│ Login failure      → Auth broken server-side (not code bug  │
│                      review can catch later). Check DB      │
│                      seed ran, user exists, JWT secret set. │
└─────────────────────────────────────────────────────────────┘

Next actions — choose scenario that matches your error, follow the exact commands:

  First: read deploy log to identify exact error
  `cat .planning/phases/{phase}/deploy-review.json`

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario A — Deploy command WRONG in config                             │
  │   (e.g., pm2 but no ecosystem.config.js, dev_command points to missing  │
  │    script, services[ENV] lists non-existent health endpoint)            │
  │                                                                         │
  │   Fix:  edit `.claude/vg.config.md` → environments.{ENV}.deploy.*       │
  │         or run: /vg:init        (interactive config wizard)             │
  │   Then: /vg:review {phase}                                              │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario B — Service crashed / code error                               │
  │   (logs show stack trace, 500 errors, module not found, port in use)    │
  │                                                                         │
  │   Fix:  inspect logs (pm2 logs / journalctl / dev output), fix code     │
  │   Then: /vg:review {phase} --retry-failed                               │
  │         (--retry-failed only re-scans failed views → 5-10× faster)     │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario C — Feature genuinely NOT BUILT (status UNREACHABLE)           │
  │   Verify first: grep code for expected page file / route / handler.    │
  │   If grep returns NOTHING → truly not built.                            │
  │   Symptoms: route missing, page file doesn't exist, sidebar link absent │
  │                                                                         │
  │   Fix:  /vg:build {phase} --gaps-only   (builds missing plans)          │
  │   Then: /vg:review {phase} --retry-failed                               │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario C2 — Code BUILT but review didn't replay (status NOT_SCANNED)  │
  │   Verify first: grep confirms page file/route/handler EXIST.            │
  │   Common causes:                                                        │
  │     • Multi-step wizard / mutation flow needs dedicated browser session │
  │     • Orphan route not linked from sidebar → discovery missed it        │
  │     • Haiku scan timed out / hit max_actions for that view              │
  │     • --retry-failed was run but goal wasn't in the retry scope         │
  │                                                                         │
  │   Fix: pick by cause:                                                   │
  │     (a) Complex flow → /vg:test {phase}                                 │
  │         (codegen + Playwright auto-walks wizard, fills all steps)       │
  │     (b) Orphan route → add sidebar link or update nav-discovery seed,  │
  │         then /vg:review {phase} --retry-failed                         │
  │     (c) Timeout/scope → /vg:review {phase} --retry-failed              │
  │         (fresh re-scan of only failed views, bypass cache)              │
  │                                                                         │
  │   DO NOT run /vg:build --gaps-only — it'll regenerate plans for code   │
  │   that already exists and waste tokens.                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario D — Auth/DB setup missing                                      │
  │   (login 500, seed user not found, JWT signature invalid)               │
  │                                                                         │
  │   Fix:  run project seed (e.g., pnpm db:seed), verify .env has secrets  │
  │   Then: /vg:review {phase} --retry-failed                               │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario E — Cross-CLI (reduce token cost by splitting work)            │
  │                                                                         │
  │   Discovery (cheap, any CLI with browser):                              │
  │     $vg-review {phase} --retry-failed --discovery-only    (Codex)       │
  │     /vg-review {phase} --retry-failed --discovery-only    (Gemini)      │
  │   Evaluate + fix (Claude only):                                         │
  │     /vg:review {phase} --evaluate-only                                  │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Scenario F — External infra unavailable (ClickHouse, Kafka, pixel srv) │
  │   Some goals need services not running on current ENV.                 │
  │   Symptoms: 500 on events/stats endpoints, 502 on postback test,      │
  │   ClickHouse table not found, Kafka ECONNREFUSED.                      │
  │                                                                        │
  │   This is NOT a code bug — code is correct but infra missing.          │
  │                                                                        │
  │   Present to user:                                                     │
  │   AskUserQuestion:                                                     │
  │     header: "Infra unavailable — choose review strategy"               │
  │     question: |                                                        │
  │       {N} services unavailable on {ENV}: {service_list}                │
  │       {M} goals depend on these (will classify as INFRA_PENDING).      │
  │                                                                        │
  │       Options:                                                         │
  │       A) Continue local — review what's testable, skip infra goals     │
  │          (fast, covers code quality, ~{pct}% goals testable)           │
  │       B) Switch to sandbox — deploy to VPS where infra exists          │
  │          (slower, covers 100% goals if VPS has ClickHouse/Kafka)       │
  │       C) Partial sandbox — review code local, then re-run              │
  │          --retry-failed on sandbox for infra goals only                │
  │     options:                                                           │
  │       - "A — continue local (skip infra goals)"                        │
  │       - "B — switch to sandbox now"                                    │
  │       - "C — partial: local now + sandbox retry later"                 │
  │                                                                        │
  │   If A → set config.infra_deps.unmet_behavior="skip", continue         │
  │   If B → switch ENV=sandbox, re-run deploy + preflight                 │
  │   If C → continue local with skip, save INFRA_PENDING goals list       │
  │          for sandbox retry (`--retry-failed` later)                    │
  └─────────────────────────────────────────────────────────────────────────┘

  Verify smoke test before any re-run:
    curl {config.services[ENV][0].health}                      # must return 200
    curl -I https://{config.credentials[ENV][0].domain}        # NOT ERR_CONNECTION
```

**Only when ALL pre-flight checks pass** → proceed to Phase 2b Browser Discovery.

API integration check — curl each endpoint in API-CONTRACTS.md:
```
For each endpoint parsed from API-CONTRACTS.md:
  If endpoint requires auth → include auth token header
  curl endpoint on target → record status code + response shape
```

### 2b: Discovery — 2-Tier Deep Scan (Opus + Haiku)

**Architecture: Opus discovers views (minimal browser), Haiku agents scan exhaustively (1 per view).**
- **Opus**: list views (1 sidebar snapshot + read SPECS), spawn Haiku, merge results, evaluate
- **Haiku**: fixed workflow scanner — click ALL elements, fill ALL forms, recurse into ALL modals. Context tiny → no lazy behavior.

**Why Haiku, not Sonnet**: AI laziness correlates with context length. Haiku agents receive a short prompt + 1 URL = near-zero context = maximum depth. Each Haiku scans 1 view exhaustively rather than skimming many views.

**MCP Server Selection:** Each Haiku agent auto-claims its own Playwright server via lock manager.
Up to 5 parallel browser sessions (5 Playwright slots configured).

#### 2b-0: Seed Data (if configured)

```
Read vg.config.md → check if seed_command exists for current ENV
IF seed_command exists:
  Run: {RUN_PREFIX} "{seed_command}"
  Wait for completion → log output
  Purpose: ensure diverse data (multiple statuses, types) so Haiku can sample representative rows
IF seed_command missing: skip silently (not a blocker)
```

#### 2b-1: Discover Views (Haiku navigator — Opus does NOT touch browser)

```
Opus reads files only (no browser):
1. Read SPECS.md → extract "In Scope" → grep route patterns
   Read PLAN.md → extract task descriptions → grep URL patterns
   Read SUMMARY.md → extract "files changed" → map to routes
   → expected_views = ["/sites", "/sites/:id", "/ad-units", ...]

2. **⛔ REGISTERED ROUTES scan (tightened 2026-04-17 — fix critical miss):**

   Sidebar DOM chỉ show top-level nav. Sub-routes đăng ký trong router config
   (ví dụ React Router `<Route path="...">`, Next.js app/pages dir, Vue Router,
   Flutter GoRouter) thường KHÔNG hiện trong sidebar → scanner miss → mark UNREACHABLE.

   **Trước khi spawn navigator, đọc route registrations từ code — pure config-driven, no defaults:**

   ```bash
   REGISTERED_ROUTES=""

   # Source 1 (preferred): graphify query — chỉ chạy khi có cả graph + predicate
   ROUTE_PRED="${config.graphify.route_predicate:-}"
   if [ "$GRAPHIFY_ACTIVE" = "true" ] && [ -n "$ROUTE_PRED" ]; then
     REGISTERED_ROUTES=$(ROUTE_PRED="$ROUTE_PRED" \
                        ROUTE_EXTRACT="${config.graphify.route_path_extract:-}" \
                        ${PYTHON_BIN} -c "
import json, os, re, sys
pred = os.environ.get('ROUTE_PRED', '')
extract = os.environ.get('ROUTE_EXTRACT', '')
if not pred or not extract:
    sys.exit(0)  # config incomplete → skip
graph_path = os.environ.get('GRAPHIFY_GRAPH_PATH')
if not graph_path or not os.path.exists(graph_path):
    sys.exit(0)
graph = json.load(open(graph_path, encoding='utf-8'))
hits = set()
for n in graph.get('nodes', []):
    blob = ' '.join(str(n.get(k,'')) for k in ('label','type','file'))
    if not re.search(pred, blob): continue
    m = re.search(extract, blob)
    if m:
        hits.add(m.group(1) if m.groups() else m.group(0))
for h in sorted(hits): print(h)
" 2>/dev/null)
   fi

   # Source 2 (fallback): grep files theo config — chỉ chạy khi có cả glob + regex
   ROUTE_GLOB="${config.code_patterns.frontend_routes:-}"
   ROUTE_REGEX="${config.code_patterns.route_path_regex:-}"
   if [ -z "$REGISTERED_ROUTES" ] && [ -n "$ROUTE_GLOB" ] && [ -n "$ROUTE_REGEX" ]; then
     REGISTERED_ROUTES=$(grep -rhoE "$ROUTE_REGEX" $ROUTE_GLOB 2>/dev/null | sort -u)
   fi

   # Report state
   if [ -n "$REGISTERED_ROUTES" ]; then
     COUNT=$(echo "$REGISTERED_ROUTES" | wc -l | tr -d ' ')
     echo "✓ Found ${COUNT} route registrations từ code (source: $([ "$GRAPHIFY_ACTIVE" = true ] && [ -n "$ROUTE_PRED" ] && echo graphify || echo grep))"
   elif [ -z "$ROUTE_PRED" ] && [ -z "$ROUTE_GLOB" ]; then
     echo "⚠ Route discovery KHÔNG được cấu hình (neither config.graphify.route_predicate"
     echo "  nor config.code_patterns.frontend_routes + route_path_regex set)."
     echo "  Review sẽ CHỈ dựa sidebar DOM → CÓ THỂ miss routes không trên menu."
     echo "  Add vào vg.config.md (pick 1 source, ví dụ theo stack của bạn — workflow không đoán hộ):"
     echo ""
     echo "  # Via grep (universal, cần regex ngôn ngữ):"
     echo "  code_patterns:"
     echo "    frontend_routes: '<glob tới route config files>'"
     echo "    route_path_regex: '<regex extract path với capture group>'"
     echo ""
     echo "  # HOẶC via graphify knowledge graph:"
     echo "  graphify:"
     echo "    route_predicate: '<regex match node.label/type/file>'"
     echo "    route_path_extract: '<regex extract path with capture group>'"
   else
     echo "⚠ Route config partial (need BOTH pattern+extract hoặc predicate+extract) → skip code scan."
   fi
   ```

   **Config keys (pure config-driven, workflow KHÔNG có stack defaults):**
   - `code_patterns.frontend_routes` — glob tới file chứa route declarations
   - `code_patterns.route_path_regex` — regex với capture group trả về route path
   - `graphify.route_predicate` — regex matching graphify node (label/type/file) identify route
   - `graphify.route_path_extract` — regex với capture group extract path từ matched node

   **Nguyên tắc:** Thiếu cả 2 source → warn + sidebar-only. Project quyết định stack, workflow chỉ là engine.
   (Examples per stack để tham khảo user-side; KHÔNG fallback trong code workflow.)

3. Load KNOWN-ISSUES.json (if exists):
   Filter: issues where suggested_phase == current phase OR status == "open"

4. Create GOAL-COVERAGE-MATRIX.md (all ⬜ UNTESTED)

5. Spawn 1 Haiku navigator agent (Agent tool, model="haiku"):
   prompt = """
   You are a navigator agent. Login and extract all navigation URLs.

   ## CONNECTION
   SESSION_ID="haiku-nav-{phase}-$$"
   MCP_PREFIX=$(bash "~/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
   trap "bash '~/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
   Use returned $MCP_PREFIX as server for all browser tool calls.

   ## TASK
   1. Login: {domain}/login | {email} | {password}  (use first role from config)
   2. browser_snapshot → read sidebar/nav menu (top-level visible links)
   3. Extract ALL visible navigation URLs
   4. **⛔ HARD RULE (tightened 2026-04-17): REGISTERED_ROUTES list được inject vào prompt.**
      Agent PHẢI visit EVERY route trong REGISTERED_ROUTES list, KHÔNG CHỈ sidebar.
      Route không có trong sidebar = "hidden_but_registered" → truy cập qua direct URL.
      Nếu visit route bị redirect (ví dụ → /login, → /403), ghi lại reason.
   5. For each URL with :id params:
      Navigate to list page → snapshot → pick first row → extract real URL
   6. Write ${PHASE_DIR}/nav-discovery.json với schema mở rộng:
      {
        "sidebar_views": ["/sites", "/campaigns"],
        "registered_routes_visited": ["/sites", "/audit-log", "/settings/roles", ...],
        "hidden_but_registered": ["/audit-log", "/settings/roles"],
        "redirected": {"/settings/billing": "/403"},
        "actual_views": ["/sites", "/campaigns", "/audit-log", "/settings/roles", ...]
      }
   7. browser_close
   8. bash "~/.claude/playwright-locks/playwright-lock.sh" release "haiku-nav-{phase}-$$"

   ## INJECTED DATA
   REGISTERED_ROUTES = [{from step 2 above — list from code scan}]
   SIDEBAR_ONLY_HINT = false  # default: visit all registered routes
   """

6. Wait for Haiku navigator → Read nav-discovery.json
   actual_views = parsed JSON .actual_views[]  (already union of sidebar + registered)

7. Merge: union(expected_views, actual_views), deduplicated, within phase scope
   Flag `hidden_but_registered` routes explicitly trong view-assignments.json
   (Haiku scanner phase 2b-2 thấy flag này → biết access qua direct URL, không click sidebar)

8. **IMMEDIATELY write view-assignments.json** — do NOT hold in context:
   Write ${PHASE_DIR}/view-assignments.json:
   {
     "phase": "{phase}",
     "generated_at": "{ISO timestamp}",
     "views": [
       { "url": "/sites", "roles": ["admin", "publisher"], "param_example": null, "source": "sidebar" },
       { "url": "/sites/123", "roles": ["publisher"], "param_example": "123", "source": "sidebar" },
       { "url": "/audit-log", "roles": ["admin"], "param_example": null, "source": "registered_hidden", "access_via": "direct_url" },
       { "url": "/settings/roles", "roles": ["admin"], "param_example": null, "source": "registered_hidden", "access_via": "direct_url" }
     ]
   }
   Trường `source` giúp Haiku scanner biết cách navigate:
   - `sidebar` → click từ menu
   - `registered_hidden` → `browser_navigate` direct URL (không có menu entry)
   
   After writing: DISCARD view list from context. Read from file when needed.

Output: view-assignments.json written to disk. Context cleared.
```

<FLUSH_RULE>
After step 8 writes view-assignments.json, you MUST NOT keep the view list in your response text.
Do NOT summarize the views found. Do NOT repeat the list.
Simply write: "view-assignments.json written — {N} views × {M} roles = {K} scan jobs."
Then immediately proceed to 2b-2 (spawn Haiku).
</FLUSH_RULE>

#### 2b-2: Spawn Haiku Scanners (parallel per view)

<MANDATORY_GATE>
**You MUST spawn Haiku agents in step 2b-2.** This is NOT optional.
- Do NOT skip this step because "phase is small" or "I already covered everything in 2b-1"
- Do NOT replace spawning with "I'll click through views myself"
- MINIMUM: spawn at least 1 Haiku agent per view discovered in 2b-1
- The Agent tool with model="haiku" MUST be called. If it's not called, 2b-2 is incomplete.
</MANDATORY_GATE>

<REREAD_REQUIRED>
**Before spawning Haiku agents, you MUST re-read `view-assignments.json` via the Read tool
(fixes I5).** The `<FLUSH_RULE>` in step 2b-1 required discarding the view list from context
to save tokens. That means right now you don't have it — do NOT guess view URLs or roles
from memory. Call Read on `${PHASE_DIR}/view-assignments.json` FIRST, then iterate the
parsed `.views[]` to spawn one Haiku per (view × role) pair.

If `--retry-failed` mode, read `view-assignments-retry.json` instead. Both files share
the same schema; iteration logic is identical.
</REREAD_REQUIRED>

**Spawn 1 Haiku agent per view** using Agent tool with `model="haiku"`.
Each agent scans 1 view exhaustively with a FIXED workflow — no discretion to skip.

IF --retry-failed:
  Normalize RETRY_VIEWS[] → view-assignments-retry.json (same schema as view-assignments.json):
    {
      "phase": "{phase}",
      "generated_at": "{ISO}",
      "mode": "retry-failed",
      "views": [{"url": "/sites", "roles": ["publisher"], "param_example": null}, ...]
    }
  READ view-assignments-retry.json
ELSE:
  READ ${PHASE_DIR}/view-assignments.json
  (both paths → same schema → downstream code identical)

view_assignments = parsed .views[]

**🎬 Pre-spawn briefing (tightened 2026-04-17 — user biết agent sẽ làm gì):**

Trước mỗi spawn, orchestrator phải:
1. Load goals map từ TEST-GOALS.md → tìm goals có `start_view == view.url` HOẶC flow references view
2. Print briefing block với: view, role, goals_covered, expected_interactions, expected_mutations
3. Set `description` của Agent tool theo format structured, không freeform

```bash
briefing_for_view() {
  local VIEW_URL="$1" ROLE="$2" IDX="$3" TOTAL="$4"
  # Parse TEST-GOALS.md → collect goals whose start_view or flow touches this view
  local BRIEFING=$(${PYTHON_BIN} - <<PY 2>/dev/null
import re, os, sys
view_url = "$VIEW_URL"
phase_dir = os.environ.get("PHASE_DIR", ".")
import glob
tg_files = glob.glob(f"{phase_dir}/*TEST-GOALS*.md")
if not tg_files:
    sys.exit(0)
tg = open(tg_files[0], encoding="utf-8").read()
# Parse goal blocks: "## Goal G-XX: title\n...**Start view:** /path\n**Success criteria:** ...\n**Mutation evidence:** ..."
blocks = re.split(r'^##\s*Goal\s+', tg, flags=re.M)
hits = []
for blk in blocks[1:]:
    m = re.match(r'(G-\d+)[:\s]+(.+?)\n', blk)
    if not m: continue
    gid, title = m.group(1), m.group(2).strip()
    # Match by start_view OR mention in flow
    start = re.search(r'\*\*Start view:\*\*\s*(\S+)', blk)
    touches = (start and start.group(1) == view_url) or (view_url in blk)
    if not touches: continue
    crit = re.search(r'\*\*Success criteria:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.S)
    mut  = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.S)
    prio = re.search(r'\*\*Priority:\*\*\s*(\w+)', blk)
    hits.append({
        "gid": gid, "title": title[:80],
        "priority": (prio.group(1) if prio else "important").lower(),
        "criteria": (crit.group(1).strip()[:120] if crit else ""),
        "mutation": (mut.group(1).strip()[:100] if mut else ""),
    })
for h in hits:
    print(f"{h['gid']}|{h['priority']}|{h['title']}|{h['criteria']}|{h['mutation']}")
PY
  )

  echo ""
  echo "┌─────────────────────────────────────────────────────────────"
  echo "│ [${IDX}/${TOTAL}] Haiku scanner briefing"
  echo "├─────────────────────────────────────────────────────────────"
  echo "│ 📄 View:  ${VIEW_URL}"
  echo "│ 👤 Role:  ${ROLE}"
  if [ -z "$BRIEFING" ]; then
    echo "│ 🎯 Goals: (none mapped — exploratory scan, fill gaps)"
  else
    echo "│ 🎯 Goals sẽ cover:"
    while IFS='|' read -r gid prio title crit mut; do
      [ -z "$gid" ] && continue
      echo "│   • ${gid} [${prio}] ${title}"
      [ -n "$crit" ] && echo "│       ✓ Expect: ${crit}"
      [ -n "$mut" ]  && echo "│       Δ Mutation: ${mut}"
    done <<< "$BRIEFING"
  fi
  echo "│ 🔎 Agent sẽ:"
  echo "│   - Login as ${ROLE} → navigate to ${VIEW_URL}"
  echo "│   - Snapshot + enumerate all modals/forms/interactive elements"
  echo "│   - For each goal above: replay interaction flow, capture evidence"
  echo "│   - Log console.error + network 4xx/5xx per step"
  echo "│   - Output: scan-${VIEW_URL//\//_}-${ROLE}.json"
  echo "└─────────────────────────────────────────────────────────────"
}
```

Then spawn with **structured description** (thay vì freeform):

```
For each view in view_assignments:
  For each role that can access this view (from config.credentials):
    IDX=$((IDX + 1))
    briefing_for_view "{view.url}" "{role}" "$IDX" "$TOTAL"

    Agent(
      model="haiku",
      description="[{IDX}/{TOTAL}] {ROLE}@{view.url} — verify {N} goals: {G-XX,G-YY,...}"
    ):
      prompt = """
      Read skill: vg-haiku-scanner (at .claude/skills/vg-haiku-scanner/SKILL.md)
      Follow it exactly. Inject these args into the workflow:

        PHASE          = "{phase}"
        VIEW_URL       = "{view.url — substitute param_example if :id pattern}"
        VIEW_SLUG      = "{filesystem-safe slug from VIEW_URL}"
        ROLE           = "{role}"
        BOUNDARY       = "{allowed URL pattern for this view}"
        DOMAIN         = "{role.domain from config.credentials[ENV]}"
        EMAIL          = "{role.email}"
        PASSWORD       = "{role.password}"
        PHASE_DIR      = "{absolute ${PHASE_DIR}}"
        SCREENSHOTS_DIR= "{absolute ${SCREENSHOTS_DIR}}"
        FULL_SCAN      = {true if --full-scan flag set else false}
        GOALS_COVERED  = [{G-XX, G-YY, ...} — from briefing_for_view parse]
        GOAL_BRIEFS    = {gid: {title, criteria, mutation, priority} — full context for prompts}

      The skill contains the full workflow (login, sidebar suppression, STEP 1-5,
      element interaction rules, output JSON schema, hard rules, cleanup).
      Do NOT invent variations. Execute skill verbatim.

      Report progress back in description updates (Agent tool surfaces `description`
      in main terminal — update per goal processed so user sees progress).
      """
      # Inline prompt collapsed — full workflow lives in skill file to keep context small.
```

**Description format (structured, parseable):**
- `[{idx}/{total}] {role}@{view} — verify {N} goals: {G-list}` — lúc spawn
- `[{idx}/{total}] {role}@{view} — G-03/5 filling form...` — trong lúc chạy (Haiku update)
- `[{idx}/{total}] {role}@{view} — ✓ 4/5 goals, 1 regression` — khi xong

User sẽ thấy banner đầy đủ BEFORE spawn + structured description trong/sau spawn.
```

**Limits (per Haiku agent):**
- Max 200 actions per view (prevents runaway on huge pages)
- Max 10 min wall time per agent
- Stagnation: same state 3x = stuck, move on
- Up to 5 Haiku agents run in parallel (limited by Playwright slots)

#### 2b-3: Collect, Cross-Check, Fill Gaps (Opus, no browser)

```
1. Wait for all Haiku agents to complete

2. Read SUMMARIES ONLY (not full JSON):
   For each scan-{view}-{role}.json:
     Read only the top-level fields: view, role, elements_total, elements_visited,
     elements_stuck, errors[] count, forms[] count, sub_views_discovered[]
   → Build slim overview: { view, visited_pct, error_count, stuck_count }
   
   IF a view has error_count > 0 OR stuck_count > 3 OR visited_pct < 90%:
     THEN read that view's full scan-{view}-{role}.json for detail
   ELSE: discard full JSON content — do NOT load into context

3. Cross-check coverage vs SPECS:
   - SPECS says phase has payments feature → Haiku found /payments? ✓
   - PLAN says 3 modals built → Haiku found 3 modals? ✓
   - Haiku discovered sub-views not in original list? → note for gap-filling
   
4. Gaps detected:
   - View listed but Haiku couldn't reach → Opus investigates (wrong URL? auth?)
   - Haiku found sub-views (e.g., /sites/123/settings) → spawn more Haiku
   - Elements marked "stuck" (file upload, complex wizard) → Opus handles or defers
   
5. Spawn additional Haiku agents if gaps found → collect → merge

6. MERGE all scan results into coverage-map:
   views = all Haiku view results
   errors = concatenate + deduplicate
   stuck = concatenate
   forms = concatenate
   
7. QUALITY CHECK (Opus judgment on Haiku results):
   Flag suspicious results:
     - elements_visited < elements_total without stuck explanation → mark INCOMPLETE
     - Form submitted but no network request recorded → mark SUSPICIOUS
     - Console errors present but Haiku didn't report them → mark NEEDS_REVIEW
     - elements_total very low for a complex page → mark SHALLOW (Haiku may have missed scroll/lazy-load)

8. UPDATE GOAL-COVERAGE-MATRIX:
   For each TEST-GOALS goal, check if Haiku scan results cover it:
   - Form submitted matching goal's mutation → ⬜ → 🔍 SCAN-COVERED
   - View explored but goal-specific action not triggered → ⬜ → ⚠️ SCAN-PARTIAL
   - View not scanned → ⬜ → ❌ NOT-COVERED
   
   Note: Haiku scanners don't pursue goals — they scan exhaustively.
   Goal coverage mapping is done by Opus reading scan results.

9. PROBE VARIATIONS (OPT-IN — only runs if --with-probes flag set):
   Default OFF: /vg:test generates deterministic Playwright probes via codegen — cheaper,
     more reliable than LLM-driven probes, and already covers edit/boundary/repeat patterns.
   Only set --with-probes when: test codegen can't cover the mutation (e.g., complex data
     setup, external service stubs), or debugging a goal that passed scan but failed probes.

   IF NOT --with-probes: skip to step 10.

   For each goal marked SCAN-COVERED that involves mutations (create/edit/delete):
   
   Spawn Haiku probe agent (model="haiku"):
   """
   You are a probe agent. Test mutation variations for goal: {goal_id}.
   
   URL: {view_url} | Login: {credentials}
   Primary action: {what Haiku scan already did — from scan JSON}
   
   Run 3 probes:
   
   Probe 1 — EDIT: Navigate to the record just created/modified.
     Open edit form → change 1-2 fields (different valid data) → submit
     → Record: {changed_fields, result, network[], console_errors[]}
   
   Probe 2 — BOUNDARY: Open same form again.
     Fill with edge values: empty optional fields, max-length "A"×255,
     special chars "O'Brien <script>", zero for numbers, past dates
     → Submit → Record: {values_description, result, validation_errors[]}
   
   Probe 3 — REPEAT: Open same form again.
     Fill with EXACT same data as primary scan → submit
     → Expect: success OR proper duplicate error — NOT crash/500
     → Record: {result, is_duplicate_handled}
   
   Write to: {PHASE_DIR}/probe-{goal_id}.json
   """
   
   Collect all probe JSONs → merge into goal_sequences[goal_id].probes[]
   Update matrix: SCAN-COVERED + probes passed → 🔍 PROBE-VERIFIED

10. For NOT-COVERED or SHALLOW items:
   Opus does targeted investigation using its own MCP Playwright:
   - Claim 1 server
   - Navigate to specific view/element
   - Investigate why Haiku missed it
   - Release server

<CHECKPOINT_RULE>
**SAVE STATE after EVERY major step (2b-1, 2b-2, 2b-3, step 8, step 9, step 10):**
  Write ${PHASE_DIR}/discovery-state.json with:
    - completed_phase: "2b-1" | "2b-2" | "2b-3" | "goals" | "probes" | "investigate"
    - completed_views[] — views already scanned
    - completed_goals[] — goals already verified
    - scan_files[] — list of scan-*.json already written
  Write ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md (overwrite with latest)
  → If token/session dies, `--resume` reads discovery-state.json → skips completed steps.
  → Scan JSONs + probe JSONs already on disk are NOT re-run.
</CHECKPOINT_RULE>
```

**Session model (from config):**
- `$SESSION_MODEL` = "multi-context": each Haiku agent uses own browser context (natural fit)
- "single-context": agents run sequentially sharing 1 context (fallback)
- Roles come from `config.credentials[ENV]` — NOT hardcoded

### 2d: Build RUNTIME-MAP

**3-layer schema: navigation graph + interactive elements + goal action sequences.**

No component-type classification (no "modal", "table", "card" types). Elements are binary: interactive or not. State changes are observed via fingerprint diff (URL + element count + DOM hash), not classified.

Write `${PHASE_DIR}/RUNTIME-MAP.json`:
```json
{
  "phase": "{phase}",
  "build_sha": "{sha}",
  "discovered_at": "{ISO timestamp}",
  
  "views": {
    "{view_path}": {
      "role": "{role from config.credentials}",
      "arrive_via": "{click sequence to get here — e.g. sidebar > menu item}",
      "snapshot_summary": "{free text — AI describes what it sees, chooses best format}",
      "fingerprint": { "url": "{url}", "element_count": 0, "dom_hash": "{sha256[:16]}" },
      "elements": [
        { "selector": "{from snapshot}", "label": "{visible text}", "visited": false }
      ],
      "issues": [],
      "screenshots": ["{phase}-{view}-{state}.png"]
    }
  },
  
  "goal_sequences": {
    "{goal_id}": {
      "start_view": "{view_path}",
      "result": "passed|failed",
      "steps": [
        { "do": "click", "selector": "{from snapshot}", "label": "{text}" },
        { "do": "fill", "selector": "{from snapshot}", "value": "{test data}" },
        { "do": "select", "selector": "{from snapshot}", "value": "{option}" },
        { "do": "wait", "for": "{condition — state_changed|network_idle|element_visible}" },
        { "observe": "{what_changed}", "network": [{"method": "POST", "url": "{observed}", "status": 201}], "console_errors": [] },
        { "assert": "{criterion from TEST-GOALS}", "passed": true }
      ],
      "probes": [
        { "type": "edit", "changed_fields": ["{field}"], "result": "passed|failed", "network": [], "console_errors": [] },
        { "type": "boundary", "values_description": "{what AI tried}", "result": "passed|failed", "network": [], "console_errors": [] },
        { "type": "repeat", "result": "passed|failed", "network": [], "console_errors": [] }
      ],
      "evidence": ["{screenshot paths}"]
    }
  },
  
  "free_exploration": [
    { "view": "{view_path}", "element_selector": "{selector}", "element_label": "{text}", "result": "{free text}", "issue": null }
  ],
  
  "errors": [],
  "coverage": {
    "views": 0,
    "goals_attempted": 0,
    "goals_passed": 0,
    "elements_visited": 0,
    "elements_total": 0,
    "pass_1_time": "{duration}",
    "pass_2_time": "{duration}"
  }
}
```

**Schema design principles (from research):**
- **No component types** — elements are just `{ selector, label, visited }`. AI doesn't classify "button" vs "link" vs "row action". Binary: interactive or not. (browser-use approach)
- **State change = fingerprint diff** — URL changed? element_count changed? dom_hash changed? = "something changed". AI describes *what* changed in free text `observe` steps. (browser-use PageFingerprint approach)
- **Goal sequences = replayable action chains** — each step is `do` (action) or `observe` (observation) or `assert` (verification). Test step replays these 1:1. Codegen converts to .spec.ts nearly 1:1. (Playwright codegen approach)
- **Free exploration = flat list** — unstructured, just records what AI found outside goal scope. Issues go to Phase 3.
- **All values from runtime observation** — selectors from browser_snapshot, labels from visible text, observations from what AI actually sees. Nothing invented.

Derive `${PHASE_DIR}/RUNTIME-MAP.md` from JSON (human-readable summary):
```markdown
# Runtime Map — Phase {phase}
Generated from: RUNTIME-MAP.json | Build: {sha}

## Views ({N} discovered)
### {view_path} ({role})
{snapshot_summary}
Elements: {N} interactive ({visited}/{total} visited)

## Goal Sequences ({passed}/{total} passed)
### {goal_id}: {description}
  1. {do}: {label} → {observe}
  2. {do}: {label} → {observe}
  ...
  Result: {passed|failed}

## Free Exploration ({N} elements, {issues} issues found)
## Errors ({N})
```

**JSON is the source of truth.** Markdown is derived. Downstream steps (test, codegen) read JSON.
</step>

<step name="phase2_mobile_discovery" profile="mobile-*">
## Phase 2 (mobile): DEVICE DISCOVERY (Maestro — equivalent of browser scan)

Fires when `profile ∈ {mobile-rn, mobile-flutter, mobile-native-ios,
mobile-native-android, mobile-hybrid}`. Web projects skip this step
because filter-steps.py resolves `mobile-*` to the 5 mobile profiles.

**⛔ Preflight gate.** Before any maestro call:

```bash
# 1. Verify wrapper present
WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
if [ ! -f "$WRAPPER" ]; then
  echo "⛔ maestro-mcp.py missing. Run vgflow installer."
  exit 1
fi

# 2. Check tool availability per host
PREREQ=$(${PYTHON_BIN} "$WRAPPER" --json check-prereqs)
echo "$PREREQ" | jq . >/dev/null 2>&1 || { echo "$PREREQ"; echo "⛔ prereqs JSON malformed"; exit 1; }
CAN_ANDROID=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['capabilities']['android_flows'])")
CAN_IOS=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['capabilities']['ios_flows'])")
HOST_OS=$(echo "$PREREQ" | ${PYTHON_BIN} -c "import json,sys;print(json.load(sys.stdin)['host_os'])")

echo "Mobile discovery prereqs: host=${HOST_OS}, android=${CAN_ANDROID}, ios=${CAN_IOS}"
```

**Platform gating vs target_platforms:**

Config `mobile.target_platforms` is the user's intent (what the app
ships to). Host OS caps what this machine can actually discover on.
Combine:

```bash
TARGETS=$(${PYTHON_BIN} -c "
import re,pathlib
t = pathlib.Path('.claude/vg.config.md').read_text(encoding='utf-8')
m = re.search(r'^target_platforms:\s*\[([^\]]*)\]', t, re.MULTILINE)
print(m.group(1) if m else '')")

DISCOVERY_PLATFORMS=()
for plat in $(echo "$TARGETS" | tr ',' ' ' | tr -d '"' | tr -d "'"); do
  plat=$(echo "$plat" | xargs)
  case "$plat" in
    ios)
      if [ "$CAN_IOS" = "True" ]; then
        DISCOVERY_PLATFORMS+=("ios")
      else
        echo "⚠ target=ios but host cannot run iOS simulator — skipping iOS discovery"
        echo "  Use /vg:test --sandbox (cloud EAS) for iOS verification."
      fi ;;
    android)
      if [ "$CAN_ANDROID" = "True" ]; then
        DISCOVERY_PLATFORMS+=("android")
      else
        echo "⚠ target=android but adb/maestro missing — skipping Android discovery"
      fi ;;
    *)
      echo "  target '${plat}' not exercised by mobile discovery (web/macos defer to other phases)"
      ;;
  esac
done

if [ ${#DISCOVERY_PLATFORMS[@]} -eq 0 ]; then
  echo "⛔ No discoverable platforms on this host. Options:"
  echo "  (a) Install Android SDK platform-tools + Maestro (universal Linux/Mac/Win)"
  echo "  (b) Run /vg:review on a macOS host for iOS discovery"
  echo "  (c) Run /vg:test --sandbox to use cloud provider (skips local discovery)"
  exit 1
fi

echo "Will discover on: ${DISCOVERY_PLATFORMS[*]}"
```

**Discovery loop — per (platform × role):**

For each platform in `$DISCOVERY_PLATFORMS` and each role in
`config.credentials.{ENV}` (same role model as web):

```bash
# a) Launch app on the target device (name from config.mobile.devices)
if [ "$PLATFORM" = "ios" ]; then
  DEVICE=$(awk '/^\s+ios:/{f=1;next} /^\s+[a-z]+:/{f=0} f && /simulator_name:/{gsub(/["'"'"']/,"");print $2;exit}' .claude/vg.config.md)
elif [ "$PLATFORM" = "android" ]; then
  DEVICE=$(awk '/^\s+android:/{f=1;next} /^\s+[a-z]+:/{f=0} f && /emulator_name:/{gsub(/["'"'"']/,"");print $2;exit}' .claude/vg.config.md)
fi

if [ -z "$DEVICE" ]; then
  echo "⚠ Device name empty for $PLATFORM in config.mobile.devices — skipping"
  continue
fi

BUNDLE_ID=$(node -e "console.log(require('./app.json').expo?.ios?.bundleIdentifier || require('./app.json').expo?.android?.package || '')" 2>/dev/null)
[ -z "$BUNDLE_ID" ] && {
  echo "⚠ bundle_id not detectable from app.json — user must provide via MAESTRO_APP_ID env"
  BUNDLE_ID="${MAESTRO_APP_ID:-}"
}

${PYTHON_BIN} "$WRAPPER" --json launch-app --bundle-id "$BUNDLE_ID" --device "$DEVICE" > "${PHASE_DIR}/launch-${PLATFORM}.json"

# b) Discovery snapshot per goal from TEST-GOALS.md
for GOAL_ID in $(grep -oE 'G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" | sort -u); do
  narrate_view_scan "${GOAL_ID}@${PLATFORM}" "" "" "${ROLE}" ""
  ${PYTHON_BIN} "$WRAPPER" --json discover \
    --flow "${GOAL_ID}-${PLATFORM}" \
    --device "$DEVICE" \
    --out-dir "${PHASE_DIR}/discover" \
    > "${PHASE_DIR}/discover/${GOAL_ID}-${PLATFORM}.json"

  # Output gets: { artifacts: { screenshot, hierarchy } }
  # Pass both to Haiku scanner (see step phase2_haiku_scan_mobile below)
done
```

**Haiku scanner — mobile variant:**

The scanner skill (`vg-haiku-scanner`) accepts either browser snapshot
(web path) or Maestro screenshot+hierarchy (mobile path). When mobile
artifacts are present, skill reads `hierarchy.json` (Maestro's view
hierarchy export) as element tree instead of DOM snapshot. See
`vgflow/skills/vg-haiku-scanner/SKILL.md` section "Mobile input mode".

Per goal, spawn a Haiku agent with prompt:

```
Context:
  Goal: {G-XX title + success criteria from TEST-GOALS.md}
  Platform: {ios|android}
  Screenshot: {PHASE_DIR}/discover/{G-XX}-{PLATFORM}.png
  Hierarchy: {PHASE_DIR}/discover/{G-XX}-{PLATFORM}.hierarchy.json
  Mode: mobile

Output: scan-{G-XX}-{PLATFORM}.json with findings per same schema as web
  (view_found, elements_count, issues[], goal_status).
```

**Bounded parallelism:**

Same as web — cap at 5 concurrent Haiku agents to avoid rate-limit.
Device concurrency is 1 per physical/simulator instance (maestro holds
exclusive connection), so platforms run sequentially per device but
multiple devices (iOS sim + Android emu) can run parallel.

**Artifact contract (MUST match web schema):**

Every mobile scan writes `scan-{G-XX}-{PLATFORM}.json` identical in
shape to web `scan-{G-XX}.json`. Downstream steps (`phase3_fix_loop`,
`phase4_goal_comparison`, `/vg:test` codegen) do not branch on profile
at artifact-read level — they read scan-*.json agnostic of source.

This keeps Phase 3/4 code zero-touch in the mobile rollout.
</step>

<step name="phase2_5_visual_checks" profile="web-fullstack,web-frontend-only">
## Phase 2.5: VISUAL INTEGRITY CHECK

**Config gate:** Read `visual_checks` from vg.config.md. If `visual_checks.enabled` != true → skip.

**Prereq:** Phase 2 must have produced RUNTIME-MAP.json with at least 1 view. Missing → skip.

**MCP Server:** Reuse same `$PLAYWRIGHT_SERVER` from Phase 2. Do NOT claim new lock.

```bash
VISUAL_ISSUES=()
VISUAL_SCREENSHOTS_DIR="${PHASE_DIR}/visual-checks"
mkdir -p "$VISUAL_SCREENSHOTS_DIR"
```

For each view in RUNTIME-MAP.json:

### 1. FONT CHECK (if visual_checks.font_check = true)

```
browser_evaluate:
  JavaScript: |
    await document.fonts.ready;
    const failed = [...document.fonts].filter(f => f.status !== 'loaded');
    return failed.map(f => ({ family: f.family, weight: f.weight, style: f.style, status: f.status }));
```

- Empty → PASS. Non-empty with status "error" → MAJOR. Status "unloaded" → MINOR.

### 2. OVERFLOW CHECK (if visual_checks.overflow_check = true)

```
browser_evaluate:
  JavaScript: |
    const overflowed = [];
    document.querySelectorAll('*').forEach(el => {
      const style = getComputedStyle(el);
      if (['scroll','auto'].includes(style.overflowY) || ['scroll','auto'].includes(style.overflowX)) return;
      if (style.display === 'none' || style.visibility === 'hidden') return;
      const vO = el.scrollHeight > el.clientHeight + 2 && style.overflowY === 'hidden';
      const hO = el.scrollWidth > el.clientWidth + 2 && style.overflowX === 'hidden';
      if (vO || hO) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        overflowed.push({
          selector: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '') +
            (el.className && typeof el.className === 'string' ? '.'+el.className.trim().split(/\s+/).join('.') : ''),
          type: vO ? 'vertical' : 'horizontal',
          rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
        });
      }
    });
    return overflowed;
```

- Main content (rect.left > config sidebar_width) → MAJOR. Sidebar/nav → MINOR.

### 3. RESPONSIVE CHECK (per viewport in visual_checks.responsive_viewports, default [1920, 375])

```
browser_resize: { width: viewport_width, height: 900 }
browser_evaluate: "await new Promise(r => setTimeout(r, 500)); return null;"
browser_take_screenshot: { path: "${VISUAL_SCREENSHOTS_DIR}/${view_slug}-${viewport_width}w.png" }
browser_evaluate:
  JavaScript: |
    return {
      hasHorizontalScroll: document.body.scrollWidth > window.innerWidth,
      clippedElements: [...document.querySelectorAll('*')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.right > window.innerWidth + 5 && r.width > 0 && r.height > 0; })
        .slice(0, 10)
        .map(el => ({ selector: el.tagName + (el.id ? '#'+el.id : ''), overflow: Math.round(el.getBoundingClientRect().right - window.innerWidth) }))
    };
```

- Desktop (>=1024) horizontal scroll → MAJOR. Mobile (<1024) → MINOR.

After all viewports: `browser_resize: { width: 1920, height: 900 }`

### 4. Z-INDEX CHECK (only views with modals in RUNTIME-MAP)

For each modal: trigger open → check topmost via `document.elementFromPoint` at center + corners → screenshot → close.
- Modal not topmost OR <75% corners visible → MAJOR.

### 5. Write visual-issues.json

```json
[{"view":"...","check_type":"font_load_failure","severity":"MAJOR","element":"Inter","viewport":null}]
```

Issues feed into Phase 3 fix loop: MAJOR = priority fix, MINOR = logged.

```
Phase 2.5 Visual Integrity:
  Views: {N}, Font: {pass}/{total}, Overflow: {pass}/{total}
  Responsive: {viewports} x {views} ({issues} issues)
  Z-index: {modals} modals ({issues} issues)
  MAJOR: {N} → Phase 3 fix loop | MINOR: {N} → logged
```

Final action: `touch "${PHASE_DIR}/.step-markers/phase2_5_visual_checks.done"`
</step>

<step name="phase2_5_mobile_visual_checks" profile="mobile-*">
## Phase 2.5 (mobile): VISUAL INTEGRITY CHECK

**Config gate:**
Read `visual_checks.enabled` from vg.config.md. If not true → skip with message
and jump to Phase 3.

**Prereq:** phase2_mobile_discovery produced screenshots in `${PHASE_DIR}/discover/`.
Missing → skip + warn: "No mobile discovery artifacts — visual checks require device snapshot first."

**Why this step differs from web:** mobile devices have fixed viewports per
model (an iPhone 15 Pro IS its viewport). There's no browser resize loop.
Instead we capture multi-device if user listed multiple emulators/simulators
in `config.mobile.devices.<plat>[]`, or re-check the already-captured
screenshots against per-platform sanity rules.

```bash
VISUAL_ISSUES=()
VIS_DIR="${PHASE_DIR}/visual-checks"
mkdir -p "$VIS_DIR"
WRAPPER="${REPO_ROOT}/.claude/scripts/maestro-mcp.py"
```

### Check 1: Font / text rendering (per captured screenshot)

Parse each `${PHASE_DIR}/discover/*.hierarchy.json`. For every text node
with non-empty `text`, verify corresponding element has `frame.height > 0`
(i.e. rendered, not invisible font). Missing → MINOR (font not loaded or
style override hiding text).

```bash
for HIER in "${PHASE_DIR}"/discover/*.hierarchy.json; do
  [ -f "$HIER" ] || continue
  MISSING=$(${PYTHON_BIN} - "$HIER" <<'PY'
import json, sys
from pathlib import Path
h = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
def walk(node, out):
    if isinstance(node, dict):
        text = (node.get('text') or node.get('attributes', {}).get('text') or '').strip()
        frame = node.get('frame') or node.get('bounds') or {}
        hgt = frame.get('height') if isinstance(frame, dict) else None
        if text and isinstance(hgt, (int, float)) and hgt <= 0:
            out.append({'text': text[:40], 'height': hgt})
        for c in (node.get('children') or []):
            walk(c, out)
    elif isinstance(node, list):
        for c in node:
            walk(c, out)
out = []
walk(h, out)
print(json.dumps(out))
PY
  )
  echo "$MISSING" > "$VIS_DIR/font-missing-$(basename "$HIER" .hierarchy.json).json"
done
```

Severity: any text-with-zero-height = MINOR (log in VISUAL_ISSUES).

### Check 2: Off-screen content (mobile equivalent of overflow check)

Parse frame coordinates. For each element with `frame.y + frame.height > device_height`
or `frame.x + frame.width > device_width`, flag as MAJOR if it's in main
content area, MINOR if near navigation bar.

Device dimensions come from screenshot metadata (PIL image size) — no
hardcoded per-device map needed.

### Check 3: Multi-device sanity (if config lists multiple emulator/simulator names)

If `config.mobile.devices.android.emulator_name` lists N values (as array
rather than single string), capture a screenshot on each and compare:
- Do text labels fit without truncation (`...` or ellipsis heuristic)?
- Do tap targets have ≥44pt minimum size (iOS HIG) or ≥48dp (Material)?

Single-device setups skip this check.

### Check 4: Z-index / modal occlusion

If any hierarchy shows a node with `role=Modal` or `accessibilityTrait=modal`,
verify its frame covers the center of the screen AND no sibling has higher
z-order. Maestro hierarchy exposes sibling order via array index; elements
later in array are on top.

### Reporting

```bash
cat > "${PHASE_DIR}/visual-issues.json" <<EOF
{
  "platform_coverage": $(ls "${PHASE_DIR}"/discover/*.hierarchy.json 2>/dev/null | wc -l),
  "issues": [ /* MINOR/MAJOR items collected */ ],
  "summary": {"major": N, "minor": N}
}
EOF
```

MAJOR → handled in Phase 3 fix loop. MINOR → logged only.

Final action: `touch "${PHASE_DIR}/.step-markers/phase2_5_mobile_visual_checks.done"`
</step>

<step name="phase3_fix_loop">
## Phase 3: FIX LOOP (max 3 iterations)

→ `narrate_phase "Phase 3 — Fix loop (iteration ${I}/3)" "Sửa bug MINOR, escalate MODERATE/MAJOR"`

**If no errors found in Phase 2 → skip to Phase 4.**
**If --fix-only → load RUNTIME-MAP, find errors, fix them.**

### 3a: Error Summary

Collect errors from ALL sources:
- RUNTIME-MAP.json: `errors[]` array + per-view `issues[]` + failed `goal_sequences` + `free_exploration` issues
- `${PHASE_DIR}/REVIEW-FEEDBACK.md` (if exists — written by /vg:test when MODERATE/MAJOR issues found):
  Parse issues table → add to error list with severity from test classification
  These are issues test couldn't fix — review MUST address them in this fix loop
- `${PLANNING_DIR}/KNOWN-ISSUES.json`: issues matching current phase/views (already loaded at init)

### 3b: Classify Errors

For each error:
- **CODE BUG** → fix immediately (wrong logic, missing validation, UI mismatch)
- **INFRA ISSUE** → escalate to user (service unavailable, config wrong)
- **SPEC GAP** → record in SPEC-GAPS.md (see 3b-spec-gaps) — feature not built, decision missing from CONTEXT/PLAN
- **PRE-EXISTING** → don't fix, write to `${PLANNING_DIR}/KNOWN-ISSUES.json` (see below)

### 3b-spec-gaps: Feed SPEC_GAPS back to blueprint (fixes G9)

When ≥3 SPEC_GAP errors accumulate, or any critical-priority goal maps to SPEC_GAP, emit `${PHASE_DIR}/SPEC-GAPS.md` and surface to user with a concrete re-plan command:

```markdown
# Spec Gaps — Phase {phase}

Detected during /vg:review phase 3b. Listed issues trace to missing CONTEXT decisions or un-tasked PLAN items — not code bugs. Review cannot fix these; blueprint must re-plan.

## Gaps
| # | Observed Issue | Related Goal | Likely Missing | Source Evidence |
|---|----------------|--------------|----------------|-----------------|
| 1 | Site delete has no confirmation modal | G-08 (delete site) | D-XX: "delete requires confirmation" decision | screenshot {phase}-sites-delete-error.png |
| 2 | Bulk import UI absent | G-12 (bulk import) | Task for CSV upload handler + FE form | grep "bulk" in code returns 0 matches |
...

## Recommended action

This is NOT a code bug. Re-run blueprint in patch mode to append tasks covering these gaps:

    /vg:blueprint {phase} --from=2a

This spawns planner with the gap list as input. Existing tasks preserved; missing ones appended. Then re-run build → review.

Do NOT attempt to fix these in the review fix loop — the fix loop targets code bugs, not missing scope.
```

Threshold + auto-suggestion:
```bash
SPEC_GAP_COUNT=$(count of SPEC_GAP-classified errors)
CRITICAL_SPEC_GAPS=$(count where related goal is priority:critical)

if [ $SPEC_GAP_COUNT -ge 3 ] || [ $CRITICAL_SPEC_GAPS -ge 1 ]; then
  echo "⚠ ${SPEC_GAP_COUNT} spec gaps detected (${CRITICAL_SPEC_GAPS} critical)."
  echo "See: ${PHASE_DIR}/SPEC-GAPS.md"
  echo ""
  echo "This is a planning gap, not a code bug. Recommended:"
  echo "   /vg:blueprint ${PHASE} --from=2a   (re-plan with gap feedback)"
  echo ""
  echo "Review fix loop will continue for code bugs only; spec gaps stay open until blueprint re-run."
fi
```

Do NOT block review — let fix loop handle code bugs. Just surface spec gaps with the right next command.

### 3b-known: Write PRE-EXISTING to KNOWN-ISSUES.json

Shared file across all phases: `${PLANNING_DIR}/KNOWN-ISSUES.json`

```
Read existing KNOWN-ISSUES.json (create if missing)

For each PRE-EXISTING error:
  Check if already recorded (match by view + description)
  IF new → append:
    {
      "id": "KI-{auto_increment}",
      "found_in_phase": "{current phase}",
      "view": "{view_path where observed}",
      "description": "{what's wrong}",
      "evidence": { "network": [...], "console_errors": [...], "screenshot": "..." },
      "affects_views": ["{list of views where this issue appears}"],
      "suggested_phase": "{phase that owns this area — AI infers from code_patterns}",
      "severity": "low|medium|high",
      "status": "open"
    }

Write back KNOWN-ISSUES.json
```

**Future phases auto-consume:** At the start of every review (Phase 2, before discovery), read KNOWN-ISSUES.json → filter issues where `suggested_phase` matches current phase OR `affects_views` overlaps with views being reviewed → display to AI as "known issues to verify/fix in this phase".

### 3c: Fix + Ripple Check + Redeploy

**🎯 3-tier fix routing (tightened 2026-04-17 — cost + context isolation):**

Sau khi bug classified ở 3a/3b (MINOR/MODERATE/MAJOR + size metadata), route tới model phù hợp theo config. Main model KHÔNG tự fix mọi thứ — MODERATE phải spawn để isolate context và save main-model tokens.

**Config (pure user-side, workflow không giả định model vendor/tier):**

```yaml
# vg.config.md
models:
  # Existing keys: planner, executor, debugger
  review_fix_inline: <model-id>    # model cho MINOR inline (thường = main/planner tier)
  review_fix_spawn:  <model-id>    # model cheaper cho MODERATE + MINOR-big-scope

review:
  fix_routing:
    minor:
      inline_when:
        max_files: <int>
        max_loc_estimate: <int>
      else: "spawn"                # route to models.review_fix_spawn
    moderate:
      action: "spawn"              # always route to models.review_fix_spawn
      parallel: <bool>
      max_concurrent: <int>
    major:
      action: "escalate"           # REVIEW-FEEDBACK.md, không auto-fix
    tripwire:
      minor_bloat_loc: <int>
      action: "warn|rollback"
```

Workflow CHỈ đọc model id từ `config.models.review_fix_inline` / `review_fix_spawn`. Không hardcode tên vendor (Claude/GPT/Gemini), tier (Opus/Sonnet/Haiku, o3/gpt-4o), hay capability.

Thiếu config → fallback: inline = main model hiện tại, spawn = cùng model (degraded — không có cost optimization nhưng vẫn có context isolation).

**Algorithm per CODE BUG:**

```
1. Load severity từ error classification (step 3b)
2. Estimate fix scope trước khi fix:
   - files_to_touch = heuristic từ error location + related callers
   - loc_estimate = peek file around error line, count context
3. Route theo severity:
```

**MINOR + small scope → inline (fast path, main model):**
```
If severity == MINOR AND files <= config.review.fix_routing.minor.inline_when.max_files
                   AND loc_estimate <= config.review.fix_routing.minor.inline_when.max_loc_estimate:
  Main model reads file + edits inline (current behavior)
  narrate_fix "[inline] MINOR ${bug_title} (${files} files, ~${loc} LOC)"
```

**MINOR big scope OR MODERATE → spawn (config-driven model):**
```
SPAWN_MODEL="${config.models.review_fix_spawn:-${config.models.executor}}"

Agent(
  model="$SPAWN_MODEL",
  description="[fix ${idx}/${total}] ${severity} ${file}:${line} — ${bug_type}"
):
  prompt = """
  Fix this reviewed bug. Focused scope — no tangent changes.

  ## BUG
  Severity: ${severity}
  Observed: ${error_description}
  Expected: ${expected_behavior}
  View: ${view_url}
  File hint: ${suspected_file}
  Evidence: ${console_errors}, ${network_failures}, ${screenshot}

  ## CONSTRAINTS
  - Touch only files related to this bug
  - No refactor/rename unless required for fix
  - Write test if missing (project convention)
  - Commit: fix(${phase}): ${short description}
  - Per CONTEXT.md D-XX OR Covers goal: G-XX in commit body

  ## RETURN
  - Files changed (list)
  - LOC delta
  - One-line summary
  """

narrate_fix "[spawn:sonnet] ${severity} ${bug_title}"
```

**MAJOR → escalate (no auto-fix):**
```
Append to REVIEW-FEEDBACK.md:
| bug_id | view | severity | description | why_escalated |

narrate_fix "[escalated] MAJOR ${bug_title} → REVIEW-FEEDBACK.md"
```

**Parallel spawning:**

Nếu `config.review.fix_routing.moderate.parallel: true` và có >1 MODERATE bugs độc lập (no shared files):
- Group bugs by affected file → spawn Sonnet parallel per group
- Max `config.review.fix_routing.moderate.max_concurrent` at once
- Wait all → aggregate commits

**Post-fix tripwire (catch misclassification):**

```bash
TRIPWIRE_LOC="${config.review.fix_routing.tripwire.minor_bloat_loc:-0}"
TRIPWIRE_ACTION="${config.review.fix_routing.tripwire.action:-warn}"

if [ "$TRIPWIRE_LOC" -gt 0 ]; then
  # Check each MINOR-routed-inline fix
  for commit in $MINOR_INLINE_COMMITS; do
    ACTUAL_LOC=$(git show --stat "$commit" | tail -1 | grep -oE '[0-9]+ insertion' | grep -oE '^[0-9]+')
    if [ "${ACTUAL_LOC:-0}" -gt "$TRIPWIRE_LOC" ]; then
      case "$TRIPWIRE_ACTION" in
        rollback)
          echo "⛔ MINOR inline fix bloated ($ACTUAL_LOC > $TRIPWIRE_LOC LOC) — rolling back, re-route Sonnet"
          git reset --hard "${commit}^"
          # Re-queue bug với severity upgrade → MODERATE → spawn Sonnet
          ;;
        warn|*)
          echo "⚠ MINOR fix ($commit) bloated: $ACTUAL_LOC LOC > $TRIPWIRE_LOC threshold. Consider re-classify."
          echo "tripwire: $commit actual_loc=$ACTUAL_LOC severity=MINOR" >> "${PHASE_DIR}/build-state.log"
          ;;
      esac
    fi
  done
fi
```

**Narration format:**

```
  ▶ Fix 1/5: [inline] MINOR edit button label mismatch
       ✓ Fixed 1 file, 2 LOC

  ▶ Fix 2/5: [spawn] MODERATE form validation missing on /sites/new
       ✓ Agent completed: 3 files, 24 LOC  (model: ${SPAWN_MODEL})

  ▶ Fix 3/5: [escalated] MAJOR bulk import UI absent
       → REVIEW-FEEDBACK.md

  ▶ Fix 4/5: [inline] MINOR CSS overflow on mobile
       ⚠ Tripwire hit: 45 LOC > 15 threshold — flagged for re-classify
```

Narrator chỉ hiển thị model id user đã config, KHÔNG hardcode "Sonnet"/"GPT-4o"/etc.

**Then for each fixed bug (inline OR via Sonnet):**

1. Read the relevant source file
2. Fix the issue
3. **Ripple check (graphify-powered, if active):**
   ```bash
   if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
     # Get files changed by this fix
     FIXED_FILES=$(git diff --name-only HEAD)
     echo "$FIXED_FILES" > "${PHASE_DIR}/.fix-ripple-input.txt"

     # Run ripple analysis on fixed files
     ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
       --changed-files-input "${PHASE_DIR}/.fix-ripple-input.txt" \
       --config .claude/vg.config.md \
       --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
       --output "${PHASE_DIR}/.fix-ripple.json"

     # Check if fix affects callers outside the fixed file
     RIPPLE_COUNT=$(${PYTHON_BIN} -c "
     import json
     d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
     callers = d.get('affected_callers', [])
     print(len(callers))
     ")

     if [ "$RIPPLE_COUNT" -gt 0 ]; then
       echo "⚠ Fix ripple: ${RIPPLE_COUNT} callers may be affected by this change"
       echo "  Adding caller views to re-verify list (step 3d)"
       # Map caller files → views for re-verification in step 3d
       RIPPLE_VIEWS=$(${PYTHON_BIN} -c "
       import json
       d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
       for c in d.get('affected_callers', []):
         print(c)
       ")
     fi
   fi
   ```
   Without graphify: step 3d re-verifies affected views by git diff only (may miss indirect callers).
4. Commit with message: `fix({phase}): {description}`

After all fixes:
```
Redeploy using env-commands.md deploy(env)
Health check → if fail → rollback
```

### 3d: Re-verify (Sonnet parallel — focused on fixed zones)

After fix+redeploy, spawn Sonnet agents to re-verify affected views + ripple zones:

```
1. Get new SHA: git rev-parse HEAD
2. git diff old_sha..new_sha → list changed files
3. Map changed files to views (using code_patterns from config):
   - Changed API routes → views that call those endpoints
   - Changed page components → those specific views
   - Graphify ripple callers (from step 3c) → views importing those callers
4. Group affected views + ripple views into zones

5. Spawn Sonnet agents (parallel) for affected zones ONLY:
   Agent prompt: "Re-verify these fixed actions in {zone}.
     Previous errors: {error list from 3a}
     Expected: errors should be resolved.
     Test each previously-failed action.
     Also check: did the fix break anything else on this view?
     Report: {action, was_broken, now_works, new_issues}"

6. Wait all → merge results:
   - Fixed errors → update matrix: ❌ → 🔍 REVIEW-PASSED
   - Still broken → keep ❌, increment iteration
   - New errors from fix → add to error list
   - Update RUNTIME-MAP with corrected observations
   - Update discovery-state.json build_sha
```

### 3e: Iterate

Repeat 3a-3d until:
- RUNTIME-MAP is **stable** (no new errors between 2 iterations)
- Zero CODE BUG errors remaining
- Max 3 iterations reached

Display after each iteration:
```
Fix iteration {N}/3:
  Errors fixed: {N}
  Errors remaining: {N} (infra: {N}, spec-gap: {N}, pre-existing: {N})
  Sonnet agents spawned: {N} (re-verified {M} views)
  New errors found: {N}
  Matrix coverage: {review_passed}/{total} goals
  Map stable: {YES|NO}
```
</step>

<step name="phase4_goal_comparison">
## Phase 4: GOAL COMPARISON

→ `narrate_phase "Phase 4 — Goal comparison" "So khớp ${N} goals từ TEST-GOALS với views đã khám phá"`

### 4a: Load Goals

Read `${PHASE_DIR}/TEST-GOALS.md` (generated by /vg:blueprint).
If missing → generate from CONTEXT.md + API-CONTRACTS.md (fallback).

Parse goals: ID, description, success criteria, mutation evidence, dependencies, priority.

**Infra dependency filter (config-driven):**

If goal has `**Infra deps:**` field (e.g., `[clickhouse, kafka, pixel_server]`):
```bash
# Check each infra dep against current environment
for dep in goal.infra_deps:
  SERVICE_CHECK=$(read config.infra_deps.services[dep].check_${ENV})
  if ! eval "$SERVICE_CHECK" 2>/dev/null; then
    goal.status = "INFRA_PENDING"
    goal.skip_reason = "${dep} not available on ${ENV}"
  fi
done
```

Goals classified as `INFRA_PENDING` are **excluded from gate calculation** (when `config.infra_deps.unmet_behavior == "skip"`). They don't count as BLOCKED or FAIL — they're simply not testable on current environment.

Display: `INFRA_PENDING ({dep})` in matrix with distinct icon.

**Console noise filter (config-driven):**

When evaluating console errors from Phase 2 discovery, filter against `config.console_noise.patterns`:
```bash
if [ "${config_console_noise_enabled}" = "true" ]; then
  for pattern in config.console_noise.patterns:
    # Remove matching errors from bug list — classify as INFRA_NOISE
    REAL_ERRORS=$(echo "$ALL_CONSOLE_ERRORS" | grep -viE "$pattern")
  done
  NOISE_COUNT=$((TOTAL_ERRORS - REAL_ERROR_COUNT))
  echo "Console: ${REAL_ERROR_COUNT} real errors, ${NOISE_COUNT} infra noise (filtered)"
fi
```

Only REAL_ERRORS (not matching noise patterns) count as view failures.

### 4b: Map Goals to RUNTIME-MAP

For each goal, check goal_sequences in RUNTIME-MAP.json:

```
For each goal:
  IF goal_sequences[goal_id] exists AND result == "passed":
    → STATUS: READY (goal was verified during Pass 2a)

  IF goal_sequences[goal_id] exists AND result == "failed":
    → STATUS: BLOCKED (with specific failure steps from goal_sequence)

  IF goal_sequences[goal_id] does NOT exist:
    # Before marking UNREACHABLE, verify code presence to distinguish
    # true "not built" from "built but not scanned"
    code_exists = check via grep against config.code_patterns:
      - Does goal's expected page file exist? (e.g., FloorRulesListPage.tsx)
      - Is the route registered? (e.g., /floor-rules in router)
      - Do related API endpoints have handlers? (grep API-CONTRACTS vs apps/api/)

    IF code_exists == FALSE:
      → STATUS: UNREACHABLE (feature not built — fix with /vg:build --gaps-only)

    IF code_exists == TRUE:
      → STATUS: NOT_SCANNED (intermediate only — MUST resolve before review exits)
      Root cause likely one of:
        - Multi-step wizard/mutation needs dedicated browser session
        - Goal path not reachable from discovered sidebar (orphan route)
        - Review ran --retry-failed but this goal wasn't in retry set
        - Haiku agent timed out or skipped
        - Goal has no UI surface but TEST-GOALS didn't mark infra_deps
      → RESOLUTION (tightened 2026-04-17 — NOT_SCANNED không được defer sang /vg:test):
        NOT_SCANNED là trạng thái TRUNG GIAN, KHÔNG phải kết luận hợp lệ.
        Review PHẢI resolve thành 1 trong 4 status kết luận: READY | BLOCKED | UNREACHABLE | INFRA_PENDING
        Cách resolve (pick 1):
          a) /vg:review {phase} --retry-failed với deeper probe (nếu timeout/depth issue)
          b) Goal không có UI surface → update TEST-GOALS với `**Infra deps:** [<user-defined no-ui tag>]` → re-classify INFRA_PENDING (tag value do user định nghĩa trong config.infra_deps, workflow không hardcode)
          c) Orphan/hidden route → verify config.code_patterns.frontend_routes đã cover pattern đó
          d) Genuinely unreachable (feature đã build nhưng UX path không exist) → manually mark UNREACHABLE with reason note
```

**Status semantics (tightened 2026-04-17):**

4 **status kết luận hợp lệ** (chỉ 4 status này được write vào GOAL-COVERAGE-MATRIX final):

| Status | Meaning | Fix command |
|---|---|---|
| READY | Goal verified, evidence in goal_sequences | none |
| BLOCKED | View found, scan ran, criteria failed | fix code → `--retry-failed` |
| UNREACHABLE | Code not in repo / UX path không exist | `/vg:build --gaps-only` |
| INFRA_PENDING | Goal needs service/infra not available on ENV | deploy infra or sandbox |

2 **status trung gian** (PHẢI resolve trước khi exit Phase 4):

| Status | Meaning | Action BẮT BUỘC |
|---|---|---|
| NOT_SCANNED | Code exists, review didn't replay | `--retry-failed` HOẶC re-classify thành 1 trong 4 status trên |
| FAILED | Scan timeout/exception | check logs → `--retry-failed` |

**⛔ GLOBAL RULE: KHÔNG được defer NOT_SCANNED sang /vg:test.**

Lý do: `/vg:test` codegen LẤY steps từ `goal_sequences[]` mà review ghi. NOT_SCANNED = review không ghi sequence = codegen không có input. Test không phải fallback cho review miss.

Goals không có UI surface đúng ra phải mark `infra_deps: [<no-ui tag>]` trong TEST-GOALS (tag value do project config quy ước) → skip ở review (INFRA_PENDING) → test qua integration/unit layer ở build phase, KHÔNG qua /vg:test E2E.

### 4c-pre: ⛔ NOT_SCANNED resolution gate (tightened 2026-04-17)

Trước khi chạy weighted gate, PHẢI resolve mọi `NOT_SCANNED` + `FAILED` thành 1 trong 4 kết luận.

```bash
NOT_SCANNED_COUNT=$(count goals where status == "NOT_SCANNED")
FAILED_COUNT=$(count goals where status == "FAILED")
INTERMEDIATE=$((NOT_SCANNED_COUNT + FAILED_COUNT))

if [ "$INTERMEDIATE" -gt 0 ]; then
  echo "⛔ Review cannot exit Phase 4 — ${INTERMEDIATE} intermediate goals:"
  echo "   NOT_SCANNED: ${NOT_SCANNED_COUNT}"
  echo "   FAILED:      ${FAILED_COUNT}"
  echo ""
  echo "Intermediate ≠ conclusion. Resolve before exit:"
  echo "  a) /vg:review ${PHASE_NUMBER} --retry-failed  (deeper probe)"
  echo "  b) Update TEST-GOALS with 'Infra deps: [backend_only]' nếu goal không có UI"
  echo "     → re-classify INFRA_PENDING"
  echo "  c) Fix config.code_patterns.frontend_routes nếu route ẩn khỏi sidebar"
  echo "  d) Manual re-classify UNREACHABLE (feature không tồn tại) với reason note"
  echo ""
  echo "⛔ KHÔNG ĐƯỢC defer sang /vg:test để 'cover' NOT_SCANNED goals."
  echo "   Test codegen lấy input từ goal_sequences review ghi. NOT_SCANNED = no input."
  echo ""
  echo "Override (NOT RECOMMENDED — creates debt):"
  echo "  /vg:review ${PHASE_NUMBER} --allow-intermediate"
  echo "  → Auto-convert remaining NOT_SCANNED → UNREACHABLE với reason='review-skip'"
  echo "  → Logged to GOAL-COVERAGE-MATRIX.md 'Debt' section"

  if [[ ! "$ARGUMENTS" =~ --allow-intermediate ]]; then
    exit 1
  else
    # Auto-convert intermediate → UNREACHABLE với audit trail
    for gid in $INTERMEDIATE_GOALS; do
      update_goal_status $gid "UNREACHABLE" --reason "review-skip-${original_status}"
    done
    echo "intermediate-override: ${INTERMEDIATE} goals auto-converted UNREACHABLE ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/build-state.log"
  fi
fi
```

### 4c: Weighted Gate Evaluation

**Chỉ chạy sau khi 4c-pre pass (tất cả goals đã ở 1 trong 4 kết luận).**

```
Gate weights by priority (from design):
  critical:     100% must be READY
  important:     80% must be READY
  nice-to-have:  50% must be READY

For each priority level:
  ready_count = goals with STATUS=READY at this priority
  total_count = total goals at this priority
  threshold   = weight for this priority
  
  IF ready_count / total_count < threshold → BLOCK at this level

Overall gate:
  ANY critical goal NOT READY → BLOCK
  Important ready% < 80% → BLOCK
  Nice-to-have ready% < 50% → BLOCK (warning, not hard block if critical+important pass)
  All thresholds met → PASS

Note: UNREACHABLE/INFRA_PENDING goals count trong total_count nhưng KHÔNG trong ready_count
      → kéo ready% xuống → gate sẽ block nếu nhiều goals unresolved.
      Đây là cơ chế tự nhiên pressure user fix thay vì accumulate tech debt.
```

### 4d: Write GOAL-COVERAGE-MATRIX.md

```markdown
# Goal Coverage Matrix — Phase {phase}

## Summary
- Goals: {total}
- Ready: {N} | Blocked: {N} | Unreachable: {N}

## By Priority
| Priority | Ready | Total | Threshold | Status |
|----------|-------|-------|-----------|--------|
| critical | {N} | {N} | 100% | {PASS|BLOCK} |
| important | {N} | {N} | 80% | {PASS|BLOCK} |
| nice-to-have | {N} | {N} | 50% | {PASS|BLOCK} |

## Goal Details
| Goal | Priority | Status | RUNTIME-MAP Path | Notes |
|------|----------|--------|------------------|-------|
(populated from runtime mapping — values from RUNTIME-MAP.json)

## Gate: {PASS|BLOCK}
{If BLOCK: specific goals that failed threshold + suggested action}
```

### 4e: Gate Decision

```
IF BLOCK:
  Show which priority level failed threshold
  Show specific goals causing the block
  Suggest action:
    - Blocked goals → "Fix blockers → re-run /vg:review --fix-only"
    - Unreachable goals → "Go back to /vg:build {phase} --gaps-only"

IF PASS:
  Proceed to write artifacts
```
</step>

<step name="crossai_review">
## CrossAI Review (optional)

**If config.crossai_clis is empty OR --skip-crossai, skip.**

Prepare context with RUNTIME-MAP + GOAL-COVERAGE-MATRIX + TEST-GOALS.
Set `$LABEL="review-check"`. Follow crossai-invoke.md.
</step>

<step name="write_artifacts">
## Write Final Artifacts

**Write order: JSON first, then derive MD from it.**

**1. `${PHASE_DIR}/RUNTIME-MAP.json`** — canonical JSON (source of truth). MUST be written FIRST.
**2. `${PHASE_DIR}/RUNTIME-MAP.md`** — derived from JSON (human-readable). Written AFTER JSON.
**3. `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`** — from Phase 4
**4. `${PHASE_DIR}/element-counts.json`** — from Phase 1b
**5. `${PHASE_DIR}/discovery-state.json`** — persisted during discovery (kept for --resume)

### MANDATORY ARTIFACT VALIDATION (do NOT skip)

After writing all files, verify they exist before committing:
```
Required files — BLOCK commit if ANY missing:
  ✓ ${PHASE_DIR}/RUNTIME-MAP.json     ← downstream /vg:test reads this, NOT .md
  ✓ ${PHASE_DIR}/RUNTIME-MAP.md
  ✓ ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md

Use Glob to confirm each file exists. If RUNTIME-MAP.json is missing,
you MUST create it before proceeding. The .md alone is NOT sufficient.
```

Commit:
```bash
git add ${PHASE_DIR}/RUNTIME-MAP.json ${PHASE_DIR}/RUNTIME-MAP.md \
       ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md ${PHASE_DIR}/element-counts.json \
       ${SCREENSHOTS_DIR}/
git commit -m "review({phase}): RUNTIME-MAP — {views} views, {actions} actions, gate {PASS|BLOCK}"
```
</step>

<step name="complete">
**Update PIPELINE-STATE.json:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'reviewed'; s['pipeline_step'] = 'review-complete'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null
```

Display:
```
Review complete for Phase {N}.
  Code scan: contract {PASS|WARNING}, {N} elements inventoried
  Discovery: {views} views, {actions} actions tested
  Fix loop: {iterations} iterations, {fixes} fixes applied
  Goals: {ready}/{total} ready (critical: {N}/{N}, important: {N}/{N})
  Gate: {PASS|BLOCK} (weighted: critical 100%, important 80%, nice-to-have 50%)
  Artifacts: RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md
  State: STATE.md updated (reviewed)
  Next: /vg:test {phase}
```
</step>

</process>

<success_criteria>
- Code scan completed (contract verify + element inventory)
- Browser discovery explored all reachable views organically
- RUNTIME-MAP.json produced with actual runtime observations (canonical JSON)
- RUNTIME-MAP.md derived from JSON (human-readable)
- Fix loop resolved code bugs (if any)
- TEST-GOALS mapped to discovered paths
- GOAL-COVERAGE-MATRIX.md shows weighted goal readiness
- Gate passed (weighted: 100% critical, 80% important, 50% nice-to-have)
- Discovery state saved (resumable)
</success_criteria>
