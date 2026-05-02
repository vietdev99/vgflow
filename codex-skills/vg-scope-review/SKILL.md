---
name: "vg-scope-review"
description: "Cross-phase scope validation — detect conflicts, overlaps, and gaps across all scoped phases"
metadata:
  short-description: "Cross-phase scope validation — detect conflicts, overlaps, and gaps across all scoped phases"
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
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
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

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

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
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

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

Invoke this skill as `$vg-scope-review`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **Run AFTER scoping, BEFORE blueprint** — this is a cross-phase gate between scope and blueprint.
4. **Automated checks first** — 5 deterministic checks run before any AI review.
5. **DISCUSSION-LOG.md is APPEND-ONLY** — never overwrite, never delete existing content.
6. **Resolution is interactive** — conflicts and gaps require user decision, not AI auto-fix.
7. **Minimum 2 phases** — warn (not block) if only 1 phase scoped.
8. **Incremental by default (tăng cường theo delta)** — scope is narrowed to changed + new + dependent phases via `${PLANNING_DIR}/.scope-review-baseline.json`. Use `--full` for complete rescan (mốc gốc — full baseline rebuild).
</rules>

<objective>
Cross-phase scope validation gate. Run after scoping all (or multiple) phases, before starting blueprint on any of them.
Detects decision conflicts, module overlaps, endpoint collisions, dependency gaps, and scope creep across phases.

Output: ${PLANNING_DIR}/SCOPE-REVIEW.md (report with gate verdict)

Pipeline position: specs -> scope -> **scope-review** -> blueprint -> build -> review -> test -> accept
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_collect">
## Step 0: Parse arguments + collect phase data

```bash
# Parse arguments
SKIP_CROSSAI=false
PHASE_FILTER=""
FULL_RESCAN=false

for arg in $ARGUMENTS; do
  case "$arg" in
    --skip-crossai) SKIP_CROSSAI=true ;;
    --phases=*) PHASE_FILTER="${arg#--phases=}" ;;
    --full) FULL_RESCAN=true ;;
  esac
done
```

**Scan for scoped phases:**
```bash
SCOPED_PHASES=()
for dir in ${PHASES_DIR}/*/; do
  if [ -f "${dir}CONTEXT.md" ]; then
    PHASE_NAME=$(basename "$dir")
    # If --phases filter provided, only include matching phases
    if [ -n "$PHASE_FILTER" ]; then
      PHASE_NUM=$(echo "$PHASE_NAME" | grep -oE '^[0-9]+(\.[0-9]+)*')
      if echo ",$PHASE_FILTER," | grep -q ",${PHASE_NUM},"; then
        SCOPED_PHASES+=("$dir")
      fi
    else
      SCOPED_PHASES+=("$dir")
    fi
  fi
done
```

**Validate:**
- If 0 phases found -> BLOCK: "No phases with CONTEXT.md found. Run /vg:scope first."
- If 1 phase found -> WARN: "Only 1 phase scoped ({phase}). Cross-phase review works best with 2+ phases. Proceeding with single-phase structural check."

**Extract from each CONTEXT.md:**
For every scoped phase (filtered later by Step 0.5 if incremental), parse and collect:
- **Decisions:** D-XX title, category, full text
- **Endpoints:** method + path + auth role + purpose (from decision Endpoints: sub-sections)
- **Module names:** inferred from endpoint paths (e.g., `/api/v1/sites` -> sites module) and UI component names
- **Test scenarios:** TS-XX descriptions
- **Dependencies:** any "Depends on Phase X" or "Requires output from Phase X" mentions
- **Files/directories likely touched:** inferred from module names + `config.code_patterns` paths

Store all extracted data in a structured format for cross-referencing in Step 1.

**Also check for DONE phases:**
Scan for phases with completed PIPELINE-STATE.json (`steps.accept.status = "done"`) or existing UAT.md. These are "shipped" phases — used for scope creep detection (Check E).
</step>

<step name="incremental_check">
## Step 0.5: INCREMENTAL SCAN (baseline delta)

Purpose: narrow scan scope to phases whose CONTEXT.md / SPECS.md changed since last successful scope-review (baseline — mốc gốc). At 50+ phases full O(n²) rescan is too slow and users skip the gate; incremental (tăng cường theo delta) keeps it cheap so it runs every time.

**Baseline path:** `${PLANNING_DIR}/.scope-review-baseline.json`

**Schema:**
```json
{
  "ts": "2026-04-17T09:12:33Z",
  "phases": {
    "7.6": {"context_sha256": "abc...", "spec_sha256": "def..."},
    "7.8": {"context_sha256": "ghi...", "spec_sha256": "jkl..."}
  }
}
```

**Logic:**

```bash
BASELINE_PATH="${PLANNING_DIR}/.scope-review-baseline.json"
INCREMENTAL=true
SCAN_SET=()       # phase IDs to actually scan this run
SKIPPED_SET=()    # phase IDs unchanged since baseline
CHANGED_COUNT=0
NEW_COUNT=0
REMOVED_COUNT=0
BASELINE_TS="(none)"

if [ "$FULL_RESCAN" = "true" ]; then
  INCREMENTAL=false
  echo "ℹ Full rescan (--full) — bypassing baseline (mốc gốc bị bỏ qua)."
elif [ ! -f "$BASELINE_PATH" ]; then
  INCREMENTAL=false
  echo "ℹ No baseline (chưa có mốc gốc) — running full scan to seed baseline."
else
  # Compute current hashes + compare to baseline
  DELTA_JSON=$(${PYTHON_BIN:-python3} - "$BASELINE_PATH" "$PHASES_DIR" <<'PY'
import json, hashlib, sys, os
from pathlib import Path

baseline_path = Path(sys.argv[1])
phases_dir = Path(sys.argv[2])

baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
baseline_phases = baseline.get("phases", {})

def sha256_file(p):
    if not p.exists(): return None
    return hashlib.sha256(p.read_bytes()).hexdigest()

def phase_id(name):
    # e.g. "07.12-conversion-tracking-pixel" -> "7.12" ; "7.6-sites" -> "7.6"
    import re
    m = re.match(r'^0*([0-9]+(?:\.[0-9]+)*)', name)
    return m.group(1) if m else name

current = {}
for d in sorted(phases_dir.iterdir()):
    if not d.is_dir(): continue
    ctx = d / "CONTEXT.md"
    spec = d / "SPECS.md"
    if not ctx.exists(): continue  # only care about scoped phases
    pid = phase_id(d.name)
    current[pid] = {
        "context_sha256": sha256_file(ctx),
        "spec_sha256": sha256_file(spec),
        "dir_name": d.name,
    }

changed, new, removed, unchanged = [], [], [], []
for pid, info in current.items():
    base = baseline_phases.get(pid)
    if not base:
        new.append(pid)
    elif base.get("context_sha256") != info["context_sha256"] or \
         base.get("spec_sha256") != info["spec_sha256"]:
        changed.append(pid)
    else:
        unchanged.append(pid)
for pid in baseline_phases:
    if pid not in current:
        removed.append(pid)

print(json.dumps({
    "baseline_ts": baseline.get("ts", "(unknown)"),
    "changed": sorted(changed),
    "new": sorted(new),
    "removed": sorted(removed),
    "unchanged": sorted(unchanged),
    "current_map": {k: v["dir_name"] for k, v in current.items()},
}, ensure_ascii=False))
PY
)
  BASELINE_TS=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(json.loads(sys.stdin.read())['baseline_ts'])")
  CHANGED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['changed']))")
  NEW_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['new']))")
  REMOVED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['removed']))")
  UNCHANGED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['unchanged']))")

  CHANGED_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['changed']))")
  NEW_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['new']))")
  REMOVED_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['removed']))")

  if [ "$CHANGED_COUNT" = "0" ] && [ "$NEW_COUNT" = "0" ] && [ "$REMOVED_COUNT" = "0" ]; then
    echo "✓ No phases changed since ${BASELINE_TS}. Scope-review is already current."
    echo "  Use --full to force rescan."
    # Early-exit optimization: still emit telemetry + skip to baseline rewrite
    type emit_telemetry_v2 >/dev/null 2>&1 && \
      emit_telemetry_v2 "gate_hit" "" "scope-review.incremental" \
        "scope-review-incremental" "PASS" \
        "{\"changed_count\":0,\"new_count\":0,\"removed_count\":0,\"early_exit\":true,\"conflicts_found\":0}"
    # Still refresh baseline timestamp, then exit.
    # (baseline hashes unchanged; just bump ts)
    exit 0
  fi

  # Build SCAN_SET = changed + new + their dependents (ROADMAP.md "Depends on" cascade)
  SCAN_JSON=$(${PYTHON_BIN:-python3} - "$PLANNING_DIR" "$CHANGED_LIST" "$NEW_LIST" <<'PY'
import sys, re, json
from pathlib import Path

planning_dir = Path(sys.argv[1])
changed = [p for p in sys.argv[2].split(',') if p]
new = [p for p in sys.argv[3].split(',') if p]
seed = set(changed + new)

# Parse ROADMAP.md for "Depends on: X.Y, A.B" per phase row
roadmap = planning_dir / "ROADMAP.md"
deps_reverse = {}   # phase -> set of phases that depend ON it
if roadmap.exists():
    content = roadmap.read_text(encoding='utf-8', errors='ignore')
    # Strategy: find "Phase X.Y" heading followed by "Depends on: ..." within block
    # Supports: "Depends on: 7.6, 7.8" OR "- Depends on Phase 7.6"
    phase_blocks = re.split(r'^\s*#{1,4}\s*Phase\s+', content, flags=re.MULTILINE)
    for block in phase_blocks[1:]:
        head = re.match(r'([0-9]+(?:\.[0-9]+)*)', block)
        if not head: continue
        pid = head.group(1)
        # Find dependency mentions
        dep_matches = re.findall(
            r'[Dd]epends\s+on[:\s]+((?:Phase\s+)?[0-9.,\s]+)', block)
        for m in dep_matches:
            for dep in re.findall(r'([0-9]+(?:\.[0-9]+)*)', m):
                deps_reverse.setdefault(dep, set()).add(pid)

# Cascade: for every seed, add all phases that depend on it (transitive)
scan = set(seed)
frontier = set(seed)
while frontier:
    next_frontier = set()
    for pid in frontier:
        for dependent in deps_reverse.get(pid, []):
            if dependent not in scan:
                scan.add(dependent)
                next_frontier.add(dependent)
    frontier = next_frontier

print(json.dumps({"scan": sorted(scan)}, ensure_ascii=False))
PY
)
  SCAN_LIST=$(echo "$SCAN_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['scan']))")

  # Narrow SCOPED_PHASES down to SCAN_LIST members
  NARROWED_PHASES=()
  IFS=',' read -ra SCAN_ARR <<< "$SCAN_LIST"
  for dir in "${SCOPED_PHASES[@]}"; do
    pname=$(basename "$dir")
    pnum=$(echo "$pname" | grep -oE '^0*[0-9]+(\.[0-9]+)*' | sed 's/^0*//')
    for target in "${SCAN_ARR[@]}"; do
      [ "$pnum" = "$target" ] && NARROWED_PHASES+=("$dir") && break
    done
  done
  # Track which phases were skipped
  IFS=',' read -ra UNCH_ARR <<< "$UNCHANGED_LIST"
  for u in "${UNCH_ARR[@]}"; do
    # Unchanged phases NOT pulled in as dependents of changed phases
    skipped=true
    for target in "${SCAN_ARR[@]}"; do
      [ "$u" = "$target" ] && skipped=false && break
    done
    $skipped && SKIPPED_SET+=("$u")
  done

  SCOPED_PHASES=("${NARROWED_PHASES[@]}")
  SCAN_SET=("${SCAN_ARR[@]}")

  echo ""
  echo "📊 Incremental scan (quét tăng cường theo delta): ${CHANGED_COUNT} phases changed since ${BASELINE_TS}, ${NEW_COUNT} new"
  echo "   Scope this run: [${SCAN_LIST}]"
  echo "   Skipped (unchanged — bỏ qua vì không đổi): ${#SKIPPED_SET[@]} phases"
  [ "$REMOVED_COUNT" != "0" ] && echo "   Removed from disk (xoá khỏi đĩa): ${REMOVED_LIST}"
  echo ""
fi
```

**Notes:**
- If `$PHASE_FILTER` is also set (from `--phases=...`), its filter intersects SCAN_SET (user explicit > baseline).
- Dependents cascade uses ROADMAP.md "Depends on" — if roadmap missing or phase not listed, no cascade (just changed+new).
- Early-exit when nothing changed saves the full Step 1 scan.
</step>

<step name="1_cross_reference">
## Step 1: CROSS-REFERENCE (automated, fast)

Run 5 deterministic checks. No AI reasoning — pure string matching and comparison.

### Check A — DECISION CONFLICTS

Compare decisions across phases. Look for:
- Same technology mentioned with different approaches (e.g., Phase 7.6 says "Redis caching", Phase 7.8 says "in-memory caching")
- Same module/service with conflicting architecture (e.g., Phase 7.6 says "monolith handler", Phase 7.8 says "microservice")
- Contradictory business rules (e.g., Phase 7.6 says "admin-only", Phase 7.8 says "public access" for same resource)

For each pair of phases, compare decision text for keyword overlap + contradiction signals.

**Output format:**
```
Check A — Decision Conflicts: {N found | CLEAN}
```
If found, collect: `{ id: "C-XX", phase_a, phase_b, decision_a, decision_b, issue, recommendation }`

### Check B — MODULE OVERLAP

Two or more phases modify the same file or module directory. Compare:
- Endpoint paths: same `/api/v1/{module}/` prefix in 2+ phases
- UI component names: same component name in 2+ phases
- Inferred directories: same `apps/api/src/modules/{name}` or `apps/web/src/pages/{name}`

This is not always a problem (phases can extend the same module), but must be flagged for review.

**Output format:**
```
Check B — Module Overlap: {N found | CLEAN}
```
If found, collect: `{ id: "O-XX", phases: [], shared_resource, recommendation }`

### Check C — ENDPOINT COLLISION

Same HTTP method + path defined in 2 different phases. This is always a conflict.

Compare all extracted endpoints: `${METHOD} ${PATH}` pairs across phases.

**Output format:**
```
Check C — Endpoint Collision: {N found | CLEAN}
```
If found, collect: `{ id: "EC-XX", phase_a, phase_b, method, path, recommendation }`

### Check D — DEPENDENCY GAPS

Phase A assumes output from Phase B, but Phase B's CONTEXT.md doesn't define that output.
Or: Phase A references a module/service that no phase creates.

Check:
- Explicit dependencies ("Depends on Phase X" in CONTEXT.md)
- Implicit dependencies (Phase A endpoint references a collection/service that only Phase B creates)

**Output format:**
```
Check D — Dependency Gaps: {N found | CLEAN}
```
If found, collect: `{ id: "DG-XX", phase, missing_dependency, recommendation }`

### Check E — SCOPE CREEP

Decisions in scoped phases overlap with already-DONE phases.
Compare decision endpoints and module names against shipped phases.

Check:
- Endpoint in a new phase already exists in a DONE phase (re-implementation risk)
- UI component in a new phase duplicates one from a DONE phase
- Business rule contradicts a shipped decision

**Output format:**
```
Check E — Scope Creep: {N found | CLEAN}
```
If found, collect: `{ id: "SC-XX", new_phase, done_phase, overlap, recommendation }`

### Summary after all checks:
```
Cross-Reference Results:
  Check A (decision conflicts):  {N} found
  Check B (module overlap):      {N} found
  Check C (endpoint collision):  {N} found
  Check D (dependency gaps):     {N} found
  Check E (scope creep):         {N} found
  Total issues: {sum}
```
</step>

<step name="2_crossai_review">
## Step 2: CROSSAI REVIEW (config-driven)

**Skip if:** `$SKIP_CROSSAI` flag is set, OR `config.crossai_clis` is empty, OR only 1 phase scoped.

Prepare context file at `${VG_TMP}/vg-crossai-scope-review.md`:

```markdown
# CrossAI Cross-Phase Scope Review

Review these {N} phase scopes for conflicts, overlaps, gaps, and inconsistencies.

## Focus Areas
1. Architectural consistency across phases
2. Data model evolution (does Phase B's schema break Phase A's assumptions?)
3. Auth model consistency (same role, same permissions across phases?)
4. Integration points (do phases that must connect actually define compatible interfaces?)
5. Ordering risks (does Phase B NEED Phase A to ship first? Is that captured?)

## Verdict Rules
- pass: no critical conflicts, all integration points compatible
- flag: minor inconsistencies that are manageable
- block: critical conflict or missing dependency that will cause build failure

## Phase Artifacts
---
{For each scoped phase: include full CONTEXT.md content, separated by phase headers}
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PLANNING_DIR}/crossai"`, `$LABEL="scope-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

Collect CrossAI findings into the report.
</step>

<step name="3_write_report">
## Step 3: WRITE REPORT

Write to `${PLANNING_DIR}/SCOPE-REVIEW.md`:

```markdown
# Scope Review — {ISO date}

**Mode:** {INCREMENTAL (tăng cường theo delta) | FULL (quét toàn bộ)}
{If incremental:}
📊 Incremental scan: {CHANGED_COUNT} phases changed since {BASELINE_TS}, {NEW_COUNT} new
   Scope this run: [{SCAN_LIST}]
   Skipped (unchanged — bỏ qua vì không đổi): {len(SKIPPED_SET)} phases
   {If REMOVED_COUNT>0:}Removed from disk (xoá khỏi đĩa): {REMOVED_LIST}

Phases reviewed: {phase list with names}
Total decisions across phases: {N}
Total endpoints across phases: {N}

## Conflicts (MUST RESOLVE)

| ID | Phase A | Phase B | Issue | Recommendation |
|----|---------|---------|-------|----------------|
| C-01 | {phase} D-{XX} | {phase} D-{XX} | {description} | {recommendation} |

{If no conflicts: "No decision conflicts found."}

## Endpoint Collisions (MUST RESOLVE)

| ID | Phase A | Phase B | Endpoint | Recommendation |
|----|---------|---------|----------|----------------|
| EC-01 | {phase} | {phase} | {METHOD /path} | {recommendation} |

{If no collisions: "No endpoint collisions found."}

## Overlaps (REVIEW)

| ID | Phases | Shared Resource | Recommendation |
|----|--------|-----------------|----------------|
| O-01 | {phases} | {module/file/component} | {recommendation} |

{If no overlaps: "No module overlaps found."}

## Dependency Gaps (MUST FILL)

| ID | Phase | Missing Dependency | Recommendation |
|----|-------|--------------------|----------------|
| DG-01 | {phase} | {what's missing} | {recommendation} |

{If no gaps: "No dependency gaps found."}

## Scope Creep (REVIEW)

| ID | New Phase | Done Phase | Overlap | Recommendation |
|----|-----------|------------|---------|----------------|
| SC-01 | {phase} | {done_phase} | {description} | {recommendation} |

{If no creep: "No scope creep detected."}

## CrossAI Findings

{CrossAI consensus results, or "Skipped (--skip-crossai or no CLIs configured)"}

## Gate

**Status: {PASS | BLOCK}**

Criteria:
- Conflicts (Check A): {N} — {MUST be 0 for PASS}
- Endpoint Collisions (Check C): {N} — {MUST be 0 for PASS}
- Dependency Gaps (Check D): {N} — {MUST be 0 for PASS}
- Overlaps (Check B): {N} — {reviewed, may be intentional}
- Scope Creep (Check E): {N} — {reviewed, may be intentional}
- CrossAI: {verdict} — {block verdicts count toward BLOCK}

**Verdict: {PASS — ready for blueprint | BLOCK — resolve {N} issues first}**
```

**Gate logic:**
- PASS if: 0 conflicts (A) + 0 endpoint collisions (C) + 0 dependency gaps (D) + CrossAI not "block"
- BLOCK if: any conflict OR any collision OR any dependency gap OR CrossAI "block"
- Overlaps (B) and Scope Creep (E) are informational — do not block, but must be reviewed
</step>

<step name="4_resolution">
## Step 4: RESOLUTION (if BLOCK)

If gate status is BLOCK, for each blocking issue:

```
AskUserQuestion:
  header: "Resolve: {issue_id} — {short description}"
  question: |
    **Issue:** {full description}
    **Phase A:** {phase} — {decision}
    **Phase B:** {phase} — {decision}
    **Recommendation:** {AI recommendation}

    How to resolve?
  options:
    - "Update Phase A scope — will need /vg:scope {phase_a} to re-discuss"
    - "Update Phase B scope — will need /vg:scope {phase_b} to re-discuss"
    - "Add dependency — update ROADMAP.md with ordering constraint"
    - "Accept as-is — mark as acknowledged risk"
```

Track resolutions:
- "Update Phase X" -> note which phases need re-scoping, suggest commands at end
- "Add dependency" -> append dependency note to ROADMAP.md (if exists)
- "Accept as-is" -> mark issue as "acknowledged" in SCOPE-REVIEW.md, downgrade from BLOCK

**After all resolutions:**
Re-evaluate gate. If all blocking issues resolved (updated scope or acknowledged):
- Update SCOPE-REVIEW.md gate status to PASS (with "acknowledged" notes)
- If any phases need re-scoping, do NOT auto-pass — list them:
  ```
  Gate conditionally PASS. Phases requiring re-scope:
    - /vg:scope {phase_a} (conflict C-01)
    - /vg:scope {phase_b} (gap DG-02)

  After re-scoping, run /vg:scope-review again to verify.
  ```
</step>

<step name="4.5_baseline_write_and_telemetry">
## Step 4.5: WRITE BASELINE + TELEMETRY (baseline = mốc gốc)

After gate verdict settles (PASS, conditional PASS, or even BLOCK — baseline always reflects current disk state so next incremental run has accurate delta), write the updated baseline:

```bash
# Count conflicts detected (sum across checks A..E)
CONFLICTS_FOUND=$(( ${CHECK_A_COUNT:-0} + ${CHECK_C_COUNT:-0} + ${CHECK_D_COUNT:-0} ))

# Write baseline atomically (via .tmp + mv)
BASELINE_PATH="${PLANNING_DIR}/.scope-review-baseline.json"
BASELINE_TMP="${BASELINE_PATH}.tmp"

${PYTHON_BIN:-python3} - "$PHASES_DIR" "$BASELINE_TMP" <<'PY'
import json, hashlib, sys, re, datetime
from pathlib import Path

phases_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def phase_id(name):
    m = re.match(r'^0*([0-9]+(?:\.[0-9]+)*)', name)
    return m.group(1) if m else name

phases = {}
for d in sorted(phases_dir.iterdir()):
    if not d.is_dir(): continue
    ctx = d / "CONTEXT.md"
    if not ctx.exists(): continue
    pid = phase_id(d.name)
    phases[pid] = {
        "context_sha256": sha(ctx),
        "spec_sha256": sha(d / "SPECS.md"),
    }

baseline = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "phases": phases,
}
out_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"✓ Baseline staged: {len(phases)} phases")
PY

mv "$BASELINE_TMP" "$BASELINE_PATH"
echo "✓ Baseline (mốc gốc) written: ${BASELINE_PATH}"

# Emit telemetry for incremental gate hit
# Reference: .claude/commands/vg/_shared/telemetry.md (emit_telemetry_v2)
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "gate_hit" "" "scope-review.incremental" \
    "scope-review-incremental" "PASS" \
    "{\"changed_count\":${CHANGED_COUNT:-0},\"new_count\":${NEW_COUNT:-0},\"removed_count\":${REMOVED_COUNT:-0},\"incremental\":${INCREMENTAL},\"conflicts_found\":${CONFLICTS_FOUND}}"
fi
```

**Rules:**
- Baseline write is NON-FATAL — if it fails, warn but do not block the gate decision.
- Baseline is always refreshed (even on BLOCK) so user's next re-run with fixes gets accurate delta.
- `.scope-review-baseline.json` should be committed alongside `SCOPE-REVIEW.md` in Step 5.
</step>

<step name="5_commit_and_next">
## Step 5: Commit + suggest next

```bash
git add "${PLANNING_DIR}/SCOPE-REVIEW.md" "${PLANNING_DIR}/.scope-review-baseline.json"
git commit -m "scope-review: ${#SCOPED_PHASES[@]} phases — ${GATE_VERDICT}"
```

**Display:**
```
Scope Review Complete.
  Phases: {N} reviewed
  Conflicts: {N} | Collisions: {N} | Overlaps: {N} | Gaps: {N} | Creep: {N}
  CrossAI: {verdict | skipped}
  Gate: {PASS | BLOCK}
```

**If PASS:**
```
  Ready for blueprint. Start with:
    /vg:blueprint {first-unblueprinted-phase}
```

**If BLOCK (still unresolved):**
```
  Resolve blocking issues before proceeding to blueprint.
  Re-run: /vg:scope-review after fixes.
```

**If conditional PASS (acknowledged risks):**
```
  Proceeding with acknowledged risks.
  {N} issues marked as accepted. See SCOPE-REVIEW.md for details.
  
  Next: /vg:blueprint {first-unblueprinted-phase}
```
</step>

</process>

<success_criteria>
- All phases with CONTEXT.md collected and parsed (or scoped down via incremental delta)
- Incremental mode active by default: baseline read, delta computed, SCAN_SET narrowed to changed + new + dependents
- `--full` flag forces rescan of every scoped phase, bypassing baseline
- 5 automated cross-reference checks executed (A through E) against SCAN_SET
- CrossAI review ran (or skipped if flagged/no CLIs/single phase)
- SCOPE-REVIEW.md written with structured report + delta summary header + gate verdict
- Baseline (`.scope-review-baseline.json`) written atomically after every run (even on BLOCK)
- Telemetry event `scope-review-incremental` emitted with changed/new/conflicts counts
- All blocking issues presented to user with resolution options
- Gate resolves to PASS (clean, conditional, or all-acknowledged) before suggesting blueprint
- Report + baseline committed to git
- Next step guidance shows /vg:blueprint for first unblueprinted phase
</success_criteria>
