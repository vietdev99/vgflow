---
name: "vg-accept"
description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
metadata:
  short-description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
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

This skill is invoked by mentioning `$vg-accept`. Treat all user text after `$vg-accept` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **All pipeline artifacts required** — SPECS → CONTEXT → PLAN → API-CONTRACTS → TEST-GOALS → SUMMARY → RUNTIME-MAP → GOAL-COVERAGE-MATRIX → SANDBOX-TEST. Missing = BLOCK.
2. **Step markers mandatory** — every profile-applicable step from /vg:build, /vg:review, /vg:test MUST have its `.step-markers/{step}.done` file. Missing = BLOCK (AI skipped silently).
3. **SANDBOX-TEST verdict gate** — must be `PASSED` or `GAPS_FOUND`. `FAILED` → BLOCK with redirect.
4. **UAT is data-driven** — checklist items are GENERATED from VG artifacts (`P{phase}.D-XX` from CONTEXT, `F-XX` from FOUNDATION if cited in any phase artifact, G-XX from TEST-GOALS, HIGH callers from RIPPLE-ANALYSIS, design-refs from PLAN). No hardcoded checks. Bare `D-XX` treated as legacy — displayed with "(legacy)" suffix.
5. **No auto-accept** — every non-N/A item requires explicit user Pass/Fail/Skip.
6. **Ripple gate** — if RIPPLE-ANALYSIS has HIGH severity callers, user MUST acknowledge each before proceeding.
7. **Write UAT.md atomic** — at end, all results persisted. Rejected phase still writes UAT.md (audit trail).
8. **Zero hardcode** — all paths from `$REPO_ROOT`, `$PHASE_DIR`, `$PYTHON_BIN`, etc. resolved by config-loader.
</rules>

<objective>
Step 6 of V6 pipeline (final). Data-driven Human UAT over VG artifacts — not a generic GSD verify pass. User reviews each decision, goal, ripple, design ref explicitly.

Pipeline: specs → scope → blueprint → build → review → test → **accept**
</objective>

<process>

<step name="0_gate_integrity_precheck">
**T8 gate (cổng) integrity precheck — blocks accept if /vg:update left unresolved gate conflicts (xung đột).**

If `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` exists, a prior `/vg:update` detected that the 3-way merge (gộp) altered one or more HARD gate blocks. BLOCK (chặn) until resolved via `/vg:reapply-patches --verify-gates`.

```bash
if [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved — run /vg:reapply-patches --verify-gates first."
  exit 1
fi
```
</step>

<step name="0_load_config">
Follow `.claude/commands/vg/_shared/config-loader.md`.

Resolves: `$REPO_ROOT`, `$PYTHON_BIN`, `$VG_TMP`, `$GRAPHIFY_GRAPH_PATH`, `$GRAPHIFY_ACTIVE`, `$PROFILE` (from config).

Parse first positional argument → `PHASE_ARG`.
```bash
PHASE_ARG="${1:-}"
if [ -z "$PHASE_ARG" ]; then
  echo "⛔ Phase number required. Usage: /vg:accept <phase>"
  exit 1
fi

# Locate phase dir (handles both "7.6" and "07.6")
PHASE_DIR=$(find ${PLANNING_DIR}/phases -maxdepth 1 -type d \( -name "${PHASE_ARG}*" -o -name "0${PHASE_ARG}*" \) 2>/dev/null | head -1)
if [ -z "$PHASE_DIR" ]; then
  echo "⛔ Phase dir not found for: $PHASE_ARG"
  exit 1
fi
PHASE_NUMBER=$(basename "$PHASE_DIR" | grep -oE '^[0-9]+(\.[0-9]+)*')
echo "Phase: $PHASE_NUMBER ($PHASE_DIR)"
```
</step>

<step name="1_artifact_precheck">
**Gate 1: All required artifacts exist**

```bash
MISSING=""
REQUIRED=(
  "SPECS.md"
  "CONTEXT.md"
  "API-CONTRACTS.md"
  "TEST-GOALS.md"
  "GOAL-COVERAGE-MATRIX.md"
)
for f in "${REQUIRED[@]}"; do
  [ -f "${PHASE_DIR}/${f}" ] || MISSING="$MISSING $f"
done
# Plans (numbered or not)
ls "${PHASE_DIR}"/*PLAN*.md >/dev/null 2>&1 || MISSING="$MISSING PLAN*.md"
ls "${PHASE_DIR}"/*SUMMARY*.md >/dev/null 2>&1 || MISSING="$MISSING SUMMARY*.md"
ls "${PHASE_DIR}"/*SANDBOX-TEST.md >/dev/null 2>&1 || MISSING="$MISSING SANDBOX-TEST.md"
# RUNTIME-MAP only required for web profiles
case "$PROFILE" in
  web-fullstack|web-frontend-only)
    [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || MISSING="$MISSING RUNTIME-MAP.json"
    ;;
  mobile-*)
    # Mobile profile: build-state.log MUST exist (it holds mobile-gate-* entries).
    # Screenshots from phase2_mobile_discovery are optional — host may lack simulator/emulator.
    [ -f "${PHASE_DIR}/build-state.log" ] || MISSING="$MISSING build-state.log"
    ;;
esac

if [ -n "$MISSING" ]; then
  echo "⛔ Missing required artifacts:$MISSING"
  echo "   Run prior pipeline steps first (/vg:build, /vg:review, /vg:test)"
  exit 1
fi
```
</step>

<step name="2_marker_precheck">
**Gate 2: Step markers (deterministic — AI did not skip silently)**

Profile determines which steps must have markers. Use `filter-steps.py` to compute the expected set per command, then verify each marker exists.

```bash
MARKER_DIR="${PHASE_DIR}/.step-markers"
mkdir -p "$MARKER_DIR"

MISSED=""
for cmd in build review test; do
  CMD_FILE=".claude/commands/vg/${cmd}.md"
  [ -f "$CMD_FILE" ] || continue
  EXPECTED=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
    --command "$CMD_FILE" --profile "$PROFILE" --output-ids 2>/dev/null)
  [ -z "$EXPECTED" ] && continue
  for step in $(echo "$EXPECTED" | tr ',' ' '); do
    if [ ! -f "${MARKER_DIR}/${step}.done" ]; then
      MISSED="$MISSED ${cmd}:${step}"
    fi
  done
done

if [ -n "$(echo "$MISSED" | xargs)" ]; then
  echo "⛔ Missing step markers — pipeline incomplete per profile '$PROFILE':"
  for m in $MISSED; do echo "   - $m"; done
  echo ""
  echo "   Resume: /vg:next  (auto-detects which step to rerun)"
  exit 1
fi
echo "✓ All expected step markers present for profile: $PROFILE"
```
</step>

<step name="3_sandbox_verdict_gate">
**Gate 3: Test verdict**

```bash
SANDBOX=$(ls "${PHASE_DIR}"/*SANDBOX-TEST.md 2>/dev/null | head -1)
VERDICT=$(grep -iE "^\s*\*\*Verdict:?\*\*|^\s*Verdict:" "$SANDBOX" | head -1 | grep -oiE "PASSED|GAPS_FOUND|FAILED" | tr '[:lower:]' '[:upper:]')

case "$VERDICT" in
  PASSED|GAPS_FOUND)
    echo "✓ Test verdict: $VERDICT"
    ;;
  FAILED)
    # ⛔ HARD GATE: FAILED blocks accept.
    # v1.9.1 R2+R4: block-resolver trước khi raw exit 1 — L1 thử gaps-only rebuild,
    # L2 architect đề xuất structural change (refactor / sub-phase / config tuning).
    echo "⛔ Test verdict: FAILED. Cannot accept."
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.test-verdict"
      BR_CTX="SANDBOX-TEST verdict=FAILED. Accept blocked. L1 may attempt gaps-only rebuild + retest; L2 may propose refactor / sub-phase / config change."
      BR_EV=$(printf '{"sandbox_test":"%s","verdict":"FAILED"}' "${SANDBOX}")
      BR_CANDS='[{"id":"gaps-only-rebuild","cmd":"echo L1-SAFE: orchestrator would run /vg:build '"${PHASE_NUMBER}"' --gaps-only then /vg:test '"${PHASE_NUMBER}"'; skipping in shell resolver safe mode","confidence":0.5,"rationale":"gap-rebuild is documented first response"}]'
      BR_RES=$(block_resolve "test-verdict-failed" "$BR_CTX" "$BR_EV" "$PHASE_DIR" "$BR_CANDS")
      BR_LVL=$(echo "$BR_RES" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LVL" = "L1" ]; then
        echo "✓ Block resolver L1 applied gaps-only rebuild — re-run /vg:accept ${PHASE_NUMBER}"
        exit 0
      elif [ "$BR_LVL" = "L2" ]; then
        block_resolve_l2_handoff "test-verdict-failed" "$BR_RES" "$PHASE_DIR"
        exit 2
      else
        block_resolve_l4_stuck "test-verdict-failed" "L1 gaps-rebuild declined, L2 architect unavailable"
      fi
    fi
    echo "   Fix failures first: /vg:build ${PHASE_NUMBER} --gaps-only → /vg:test ${PHASE_NUMBER}"
    exit 1
    ;;
  *)
    echo "⛔ Test verdict not parseable from $SANDBOX — cannot determine pass/fail state."
    echo "   Re-run /vg:test ${PHASE_NUMBER} to regenerate SANDBOX-TEST with a clear verdict."
    exit 1
    ;;
esac

# ⛔ HARD GATE (tightened 2026-04-17): build-state regression overrides surface here.
# If build was accepted with --override-reason=, accept step must acknowledge.
BUILD_STATE="${PHASE_DIR}/build-state.log"
if [ -f "$BUILD_STATE" ]; then
  OVERRIDES=$(grep -E "^(override|regression-guard.*OVERRIDE|regression-guard.*WARN|skip-design-check|missing-summaries)" "$BUILD_STATE" 2>/dev/null)
  if [ -n "$OVERRIDES" ]; then
    echo "⚠ Build-phase overrides detected (require human acknowledgment):"
    echo "$OVERRIDES" | sed 's/^/   /'
    echo ""
    echo "   Proceeding will record these in UAT.md 'Build Overrides' section."
    # Write to be picked up by write_uat_md step
    echo "$OVERRIDES" > "${VG_TMP}/uat-build-overrides.txt"
  fi
fi

# Git cleanliness check (non-blocking, informational)
DIRTY=$(git status --porcelain 2>/dev/null | head -5)
if [ -n "$DIRTY" ]; then
  echo "⚠ Working tree has uncommitted changes — may or may not be intentional:"
  echo "$DIRTY" | head -5 | sed 's/^/   /'
fi

# ⛔ HARD GATE (tightened 2026-04-17): regression surface check
# If /vg:regression ran and REGRESSION-REPORT.md has REGRESSION_COUNT > 0 without --fix,
# block accept unless user explicitly overrides.
REG_REPORT=$(ls "${PHASE_DIR}"/REGRESSION-REPORT*.md 2>/dev/null | head -1)
if [ -n "$REG_REPORT" ]; then
  REG_COUNT=$(grep -oE 'REGRESSION_COUNT:\s*[0-9]+' "$REG_REPORT" | grep -oE '[0-9]+' | head -1)
  REG_FIXED=$(grep -q "fix-loop: applied" "$REG_REPORT" && echo "yes" || echo "no")
  if [ -n "$REG_COUNT" ] && [ "$REG_COUNT" -gt 0 ] && [ "$REG_FIXED" != "yes" ]; then
    echo "⛔ Regressions detected in ${REG_REPORT}: ${REG_COUNT} goals regressed, fix-loop NOT run."
    echo "   Fix: /vg:regression --fix  (auto-fix loop then re-run accept)"
    if [[ ! "$ARGUMENTS" =~ --override-regressions= ]]; then
      # v1.9.2 P4 — block-resolver before exit
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.regression-gate"
        BR_GATE_CONTEXT="${REG_COUNT} regressed goals detected in ${REG_REPORT}. Fix-loop was NOT run. Shipping now would ship known broken behavior."
        BR_EVIDENCE=$(printf '{"reg_count":"%s","reg_report":"%s","reg_fixed":"%s"}' "$REG_COUNT" "$REG_REPORT" "$REG_FIXED")
        BR_CANDIDATES='[{"id":"run-regression-fix","cmd":"echo \"/vg:regression --fix required — orchestrator must dispatch slash command\" && exit 1","confidence":0.5,"rationale":"Standard remediation path"}]'
        BR_RESULT=$(block_resolve "accept-regression" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        [ "$BR_LEVEL" = "L1" ] && echo "✓ L1 — regression fix-loop applied" >&2 && REG_FIXED="yes"
        [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "accept-regression" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
        [ "$REG_FIXED" != "yes" ] && exit 1
      else
        exit 1
      fi
    else
      echo "⚠ --override-regressions set — recording in UAT.md"
    fi
  fi
fi
```
</step>

<step name="3b_unreachable_triage_gate">
**Gate 3b: UNREACHABLE triage gate (added 2026-04-17)**

⛔ HARD GATE: if `/vg:review` produced `.unreachable-triage.json` and any verdict is `bug-this-phase`, `cross-phase-pending:*`, or `scope-amend`, BLOCK accept unless `--allow-unreachable` + `--reason='...'` is supplied.

Rationale: UNREACHABLE goals previously got "tracked separately" and shipped silently. They are bugs (or fictional roadmap entries) until proven otherwise. The triage produced by `/vg:review` distinguishes legitimate cross-phase ownership from bugs — only `cross-phase:{X.Y}` (owner already accepted + runtime-verified) is acceptance-safe.

```bash
TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"

if [ -f "$TRIAGE_JSON" ]; then
  # Parse blocking verdicts
  BLOCKING_LIST=$(${PYTHON_BIN} - "$TRIAGE_JSON" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
blocking = []
for gid, v in data.get("verdicts", {}).items():
    if v.get("blocks_accept"):
        blocking.append(f"{gid}|{v['verdict']}|{v['title'][:80]}")
print("\n".join(blocking))
PY
)

  if [ -n "$BLOCKING_LIST" ]; then
    BLOCKING_COUNT=$(echo "$BLOCKING_LIST" | wc -l)
    echo ""
    echo "⛔ /vg:accept BLOCKED — ${BLOCKING_COUNT} UNREACHABLE goals need resolution before phase ${PHASE_NUMBER} can ship:"
    echo ""
    echo "$BLOCKING_LIST" | while IFS='|' read -r gid verdict title; do
      echo "  • ${gid} [${verdict}] — ${title}"
    done
    echo ""
    echo "See ${PHASE_DIR}/UNREACHABLE-TRIAGE.md for evidence + required actions."
    echo ""
    echo "Fix paths by verdict:"
    echo "  bug-this-phase       → /vg:build ${PHASE_NUMBER} --gaps-only"
    echo "  cross-phase-pending  → wait for owning phase to reach 'accepted', OR /vg:amend ${PHASE_NUMBER}"
    echo "  scope-amend          → /vg:amend ${PHASE_NUMBER}  (remove goal or move to new phase)"
    echo ""

    # v1.9.2 P4 — attempt block_resolve before hard exit (only when no --allow-unreachable)
    if [[ ! "$ARGUMENTS" =~ --allow-unreachable ]]; then
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="accept.unreachable-gate"
        BR_GATE_CONTEXT="${BLOCKING_COUNT} UNREACHABLE goals block accept. Verdicts include bug-this-phase / cross-phase-pending / scope-amend. Shipping without resolution = phantom-done phase."
        BR_EVIDENCE=$(printf '{"blocking_count":"%s","triage_file":"%s"}' "$BLOCKING_COUNT" "$TRIAGE_JSON")
        BR_CANDIDATES='[{"id":"auto-scope-amend","cmd":"echo \"would open /vg:amend for scope_amend items — requires orchestrator\" && exit 1","confidence":0.35,"rationale":"scope-amend verdicts often resolvable by moving goal to new phase"}]'
        BR_RESULT=$(block_resolve "accept-unreachable" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        case "$BR_LEVEL" in
          L1) echo "✓ L1 resolved — triage updated inline" >&2 ;;
          L2) block_resolve_l2_handoff "accept-unreachable" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
          *)  exit 1 ;;
        esac
      fi
    fi

    if [[ "$ARGUMENTS" =~ --allow-unreachable ]]; then
      REASON=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
      if [ -z "$REASON" ]; then
        echo "⛔ --allow-unreachable requires --reason='<why shipping with known gaps>'"
        exit 1
      fi
      # v1.9.0 T1: rationalization guard — shipping with known UNREACHABLE goals is critical bypass.
      RATGUARD_RESULT=$(rationalization_guard_check "unreachable-triage" \
        "UNREACHABLE with bug-this-phase/cross-phase-pending/scope-amend verdict = known gap. Shipping without fix or amend creates phantom-done phases." \
        "blocking_list=${BLOCKING_LIST} reason=${REASON}")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "unreachable-triage" "--allow-unreachable" "$PHASE_NUMBER" "accept.unreachable-gate" "$REASON"; then
        exit 1
      fi
      echo "⚠ --allow-unreachable set with reason: ${REASON}"
      echo "   Recording to override-debt register + UAT.md 'Unreachable Debt' section"
      # Log to override-debt (helper from _shared/override-debt.md)
      override_debt_record "unreachable-accept" "$PHASE_NUMBER" "$REASON" 2>/dev/null || \
        echo "unreachable-accept: phase=${PHASE_NUMBER} reason=\"${REASON}\" ts=$(date -u +%FT%TZ)" \
          >> "${PHASE_DIR}/build-state.log"
      # Stash for write_uat_md to surface
      echo "$BLOCKING_LIST" > "${VG_TMP}/uat-unreachable-debt.txt"
      echo "$REASON" > "${VG_TMP}/uat-unreachable-reason.txt"
    else
      exit 1
    fi
  fi

  # Surface RESOLVED (cross-phase) entries — informational, requires acknowledgment in UAT
  RESOLVED_LIST=$(${PYTHON_BIN} - "$TRIAGE_JSON" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
resolved = []
for gid, v in data.get("verdicts", {}).items():
    if not v.get("blocks_accept") and v["verdict"].startswith("cross-phase:"):
        owner = v["verdict"].split(":", 1)[1]
        resolved.append(f"{gid}|{owner}|{v['title'][:80]}")
print("\n".join(resolved))
PY
)
  if [ -n "$RESOLVED_LIST" ]; then
    echo "✓ UNREACHABLE triage resolved (cross-phase, owner accepted):"
    echo "$RESOLVED_LIST" | while IFS='|' read -r gid owner title; do
      echo "  • ${gid} → owned by Phase ${owner} — ${title}"
    done
    echo "$RESOLVED_LIST" > "${VG_TMP}/uat-unreachable-resolved.txt"
  fi
fi
```
</step>

<step name="3c_override_resolution_gate">
**Gate 3c: Override resolution gate (T5 — event-based, v1.8.0+)**

⛔ HARD GATE: if the override-debt register contains OPEN entries that are NOT resolved by a telemetry event (and NOT explicitly `--wont-fix`), BLOCK accept. Time-based expiry is BANNED — an override only clears when its bypassed gate re-runs cleanly OR the user explicitly declines to fix.

Rationale (from M9 claude reviewer): prior `auto_expire_days` model silently forgave real debt. An override entry must stay OPEN until either (a) the bypassed gate re-runs cleanly (auto-resolved via telemetry `override_resolved` event correlation), or (b) the user explicitly marks `--wont-fix` with justification.

```bash
# Load helpers (v1.9.0 T3: source .sh, NOT .md — .md contains YAML frontmatter
# that bash cannot source. If .sh missing → real install bug, surface it.)
source .claude/commands/vg/_shared/lib/override-debt.sh 2>/dev/null || \
  echo "⚠ override-debt.sh missing — override resolution gate degraded" >&2

# Migrate any pre-v1.8.0 legacy entries (idempotent — adds legacy:true flag)
override_migrate_legacy 2>/dev/null || true

# List unresolved entries
UNRESOLVED_JSON=$(override_list_unresolved 2>/dev/null || echo "[]")
UNRESOLVED_COUNT=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)

if [ "${UNRESOLVED_COUNT:-0}" -gt 0 ]; then
  # Filter to blocking-severity entries for THIS phase only
  BLOCKING_SEV="${CONFIG_DEBT_BLOCKING_SEVERITY:-critical}"
  BLOCKING_LIST=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} - "$BLOCKING_SEV" "$PHASE_NUMBER" <<'PY'
import json, sys
entries = json.load(sys.stdin)
blocking_sev = set(sys.argv[1].split())
phase = sys.argv[2]
out = []
for e in entries:
    if e.get("severity") in blocking_sev and e.get("phase") == phase:
        age_days = "?"
        try:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(e["logged_ts"].replace("Z","+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).days
        except Exception: pass
        legacy_tag = " [LEGACY (cũ)]" if e.get("legacy") else ""
        out.append(f"  • {e['id']} [{e['severity']}] {e['flag']} · gate={e.get('gate_id') or 'n/a'} · age={age_days}d{legacy_tag}")
        out.append(f"     step: {e['step']}")
        out.append(f"     reason: {e['reason']}")
print("\n".join(out))
PY
)

  if [ -n "$BLOCKING_LIST" ]; then
    echo ""
    echo "⛔ Override resolution gate BLOCKED — unresolved overrides (bỏ qua, chưa giải quyết) for phase ${PHASE_NUMBER}:"
    echo ""
    echo "$BLOCKING_LIST"
    echo ""
    echo "Resolution paths (giải quyết):"
    echo "  1. Re-run the bypassed gate cleanly → auto-resolved via telemetry event (preferred)"
    echo "     Example: /vg:build ${PHASE_NUMBER} --gaps-only  OR  /vg:review ${PHASE_NUMBER}  OR  /vg:test ${PHASE_NUMBER}"
    echo ""
    echo "  2. /vg:override-resolve <DEBT-ID> --reason='<why>' [--wont-fix]"
    echo "     (v1.9.0+ — for overrides without natural re-run trigger. --wont-fix = permanent decline via AskUserQuestion confirmation. Marks WONT_FIX, logs telemetry.)"
    echo ""
    echo "  3. /vg:accept ${PHASE_NUMBER} --allow-unresolved-overrides --reason='<justification>'"
    echo "     (Accept path — logs NEW debt entry, still blocks the NEXT accept. Not a forgive, a defer.)"
    echo ""

    if [[ "$ARGUMENTS" =~ --allow-unresolved-overrides ]]; then
      REASON=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
      if [ -z "$REASON" ]; then
        echo "⛔ --allow-unresolved-overrides requires --reason='<why shipping with unresolved overrides>'"
        exit 1
      fi
      # v1.9.0 T1: rationalization guard — meta-override (forgive prior overrides). Highest-risk gate.
      RATGUARD_RESULT=$(rationalization_guard_check "override-resolution-gate" \
        "Accept gate blocks while critical OPEN overrides are unresolved. --allow-unresolved-overrides compounds debt — a meta-override forgiving prior overrides." \
        "unresolved_count=${UNRESOLVED_COUNT} reason=${REASON}")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "override-resolution-gate" "--allow-unresolved-overrides" "$PHASE_NUMBER" "accept.override-resolution-gate" "$REASON"; then
        exit 1
      fi
      echo "⚠ --allow-unresolved-overrides set with reason: ${REASON}"
      echo "   Recording NEW debt entry (this acceptance itself becomes tracked debt)."
      # Log as new override-debt entry (critical severity — shows up on NEXT accept too)
      if type -t log_override_debt >/dev/null 2>&1; then
        log_override_debt "--allow-unresolved-overrides" "$PHASE_NUMBER" \
          "accept.override-resolution-gate" "$REASON" "override-resolution-gate"
      fi
      # Emit telemetry
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "override_used" "$PHASE_NUMBER" "accept.override-resolution-gate" \
          "override-resolution-gate" "OVERRIDE" \
          "{\"flag\":\"--allow-unresolved-overrides\",\"reason\":\"${REASON//\"/\\\"}\",\"unresolved_count\":${UNRESOLVED_COUNT}}"
      fi
      # Stash for UAT.md surfacing
      echo "$BLOCKING_LIST" > "${VG_TMP}/uat-unresolved-overrides.txt"
      echo "$REASON" > "${VG_TMP}/uat-unresolved-override-reason.txt"
    else
      exit 1
    fi
  fi

  # Surface legacy (pre-v1.8.0) entries informationally — they need triage but don't auto-block
  # unless they're also at blocking severity (already caught above)
  LEGACY_LIST=$(echo "$UNRESOLVED_JSON" | ${PYTHON_BIN} <<'PY'
import json, sys
entries = json.load(sys.stdin)
legacy = [e for e in entries if e.get("legacy")]
for e in legacy:
    print(f"  • {e['id']} [{e['severity']}] {e['flag']} — logged {e['logged_ts']}")
PY
)
  if [ -n "$LEGACY_LIST" ]; then
    echo ""
    echo "⚠ Legacy (cũ) override entries detected — pre-v1.8.0, no telemetry gate_id link:"
    echo "$LEGACY_LIST"
    echo "   These need manual triage. Recommended: re-run the original gate OR mark --wont-fix."
  fi
fi
```

**NEW command placeholder:** `/vg:override-resolve {gate_id} --wont-fix --reason='...'` — explicit decline path for overrides that will never be clean-resolved. Ships in v1.9+. Until then, use `--allow-unresolved-overrides` inline path (logs new debt entry, still blocks next accept — forces eventual confrontation).
</step>

<step name="4_build_uat_checklist">
**Build data-driven UAT checklist from VG artifacts.**

The checklist has 5 sections. Each section pulls directly from phase data — no hardcoded items.

### Section A: Decisions (from CONTEXT.md — phase-scoped) + Section A.1: Foundation Decisions (from FOUNDATION.md — if cited)

Parse `CONTEXT.md` for `P{phase}.D-XX` blocks (new) or legacy `D-XX`. Each becomes a UAT item: "Was decision {ID} implemented as specified?"

```bash
${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-decisions.txt"
import re
from pathlib import Path
text = Path("${PHASE_DIR}/CONTEXT.md").read_text(encoding="utf-8")
# Match P{phase}.D-XX heading (new v1.8.0 namespace) OR legacy D-XX heading
# Patterns: "### P7.10.1.D-01: title" OR "### D-01: title" (legacy)
for m in re.finditer(r'^##?#?\s*(P[0-9.]+\.D-\d+|D-\d+)[:\s-]+([^\n]+)', text, re.MULTILINE):
    did = m.group(1)
    title = m.group(2).strip().rstrip('*').strip()[:100]
    # Mark legacy bare D-XX with suffix for UAT display (migration reminder)
    suffix = "\t(legacy — run migrate-d-xx-namespace.py)" if re.match(r'^D-\d+$', did) else ""
    print(f"{did}\t{title}{suffix}")
PY

# Section A.1 — scan all phase artifacts (PLAN, SUMMARY, UAT, etc.) for F-XX references from FOUNDATION.md
# If cited, include FOUNDATION.md decision in UAT (to verify F-XX assumption still holds)
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
if [ -f "$FOUNDATION_FILE" ]; then
  ${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-foundation.txt"
import re
from pathlib import Path

phase_dir = Path("${PHASE_DIR}")
cited_ids = set()
# Scan phase artifacts for F-XX citations
for md_file in phase_dir.rglob("*.md"):
    try:
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'\bF-(\d+)\b', text):
            cited_ids.add(f"F-{m.group(1)}")
    except Exception:
        pass

if not cited_ids:
    # No FOUNDATION decisions cited → emit nothing (Section A.1 shown empty)
    pass
else:
    # Parse FOUNDATION.md for each cited F-XX → get title
    foundation_text = Path("${FOUNDATION_FILE}").read_text(encoding="utf-8")
    for fid in sorted(cited_ids):
        m = re.search(rf'^##?#?\s*{re.escape(fid)}[:\s-]+([^\n]+)', foundation_text, re.MULTILINE)
        title = m.group(1).strip().rstrip('*').strip()[:100] if m else "(not found in FOUNDATION.md — stale cite?)"
        print(f"{fid}\t{title}")
PY
fi
```

### Section B: Goals (from TEST-GOALS.md + GOAL-COVERAGE-MATRIX.md)

Parse goals + their coverage status. Items: "Goal G-XX verified working?" for each READY goal. BLOCKED/UNREACHABLE goals flagged as known gaps.

```bash
${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-goals.txt"
import re
from pathlib import Path
goals_text = Path("${PHASE_DIR}/TEST-GOALS.md").read_text(encoding="utf-8")
coverage_path = Path("${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md")
coverage = coverage_path.read_text(encoding="utf-8") if coverage_path.exists() else ""

for m in re.finditer(r'^##?\s*(G-\d+)[:\s-]+([^\n]+)', goals_text, re.MULTILINE):
    gid = m.group(1)
    title = m.group(2).strip().rstrip('*').strip()[:100]
    # Look up status in coverage matrix (simple substring)
    status = "UNKNOWN"
    for line in coverage.splitlines():
        if gid in line:
            for tag in ("READY", "BLOCKED", "UNREACHABLE", "PARTIAL"):
                if tag in line.upper():
                    status = tag
                    break
            break
    print(f"{gid}\t{status}\t{title}")
PY
```

### Section C: Ripple acknowledgment (from RIPPLE-ANALYSIS.md or .ripple.json)

If ripple data exists, HIGH-severity callers need explicit acknowledgment.

```bash
RIPPLE_JSON="${PHASE_DIR}/.ripple.json"
RIPPLE_MD="${PHASE_DIR}/RIPPLE-ANALYSIS.md"

if [ -f "$RIPPLE_JSON" ]; then
  ${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-ripples.txt"
import json
from pathlib import Path
d = json.loads(Path("$RIPPLE_JSON").read_text(encoding="utf-8"))
count = 0
for r in d.get("ripples", []):
    for c in r.get("callers", []):
        # Print one line per unique caller (dedup in bash later)
        print(f"{c['file']}:{c.get('line','?')}\t{c.get('symbol','?')}\t{r['changed_file']}")
        count += 1
print(f"# TOTAL_CALLERS={count}", flush=True)
PY
elif [ -f "$RIPPLE_MD" ]; then
  # Check if RIPPLE-ANALYSIS.md is a "SKIPPED" stub (graphify was unavailable)
  if grep -qi "SKIPPED\|unavailable\|not available\|stub" "$RIPPLE_MD" 2>/dev/null; then
    echo "# RIPPLE_SKIPPED=true" > "${VG_TMP}/uat-ripples.txt"
  else
    : > "${VG_TMP}/uat-ripples.txt"
  fi
else
  # No ripple data at all — no gate
  : > "${VG_TMP}/uat-ripples.txt"
fi
```

### Section D: Design fidelity (if phase has <design-ref>)

Extract <design-ref> attributes from PLAN tasks. Each becomes a spot-check item.
For mobile profiles, ALSO emit simulator/emulator screenshots captured during
`phase2_mobile_discovery` — each screenshot is a "built output" candidate to
visually compare against the design-ref.

```bash
${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-designs.txt"
import re
from pathlib import Path
for plan in Path("${PHASE_DIR}").glob("*PLAN*.md"):
    text = plan.read_text(encoding="utf-8")
    for m in re.finditer(r'<design-ref>([^<]+)</design-ref>', text):
        ref = m.group(1).strip()
        # ref format like "sites-list.default" or "sites-list.modal-add"
        print(ref)
PY
# Dedupe
sort -u "${VG_TMP}/uat-designs.txt" -o "${VG_TMP}/uat-designs.txt"

# Mobile-only: collect simulator/emulator screenshots from phase2_mobile_discovery.
# These sit in ${PHASE_DIR}/discover/ and are named like "G-XX-ios.png", "G-XX-android.png".
# We write them to uat-mobile-screenshots.txt — interactive step shows path so user
# opens file manager to compare vs design-normalized ref.
: > "${VG_TMP}/uat-mobile-screenshots.txt"
case "$PROFILE" in
  mobile-*)
    if [ -d "${PHASE_DIR}/discover" ]; then
      find "${PHASE_DIR}/discover" -maxdepth 2 -type f \
        \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' \) 2>/dev/null \
        | sort > "${VG_TMP}/uat-mobile-screenshots.txt"
    fi
    ;;
esac

### Section E: Deliverables summary (from SUMMARY*.md — for spot-check only)

High-level summary of what was built — presented to user as context, not gated.

```bash
${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-summary.txt"
import re
from pathlib import Path
for summary in sorted(Path("${PHASE_DIR}").glob("*SUMMARY*.md")):
    text = summary.read_text(encoding="utf-8")
    # Extract "## Task N — title" or similar
    for m in re.finditer(r'^##?\s*(Task\s+\d+|Deliverable\s*\d+)[:\s-]+([^\n]+)', text, re.MULTILINE):
        title = m.group(2).strip().rstrip('*').strip()[:100]
        print(f"{summary.name}\t{m.group(1)}\t{title}")
PY
```

### Section F: Mobile gates (mobile profiles only)

Parse `build-state.log` for `mobile-gate-N: <name> status=<passed|failed|skipped> [reason=...] ts=...`
lines. Each gate becomes an acknowledgment row: user confirms the outcome makes
sense (e.g., "Gate 7 skipped because signing certs not yet provisioned — OK").

For web profiles this file stays empty and Section F is suppressed.

```bash
: > "${VG_TMP}/uat-mobile-gates.txt"
case "$PROFILE" in
  mobile-*)
    BUILD_LOG="${PHASE_DIR}/build-state.log"
    if [ -f "$BUILD_LOG" ]; then
      ${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-mobile-gates.txt"
import re
from pathlib import Path
log = Path("${BUILD_LOG}").read_text(encoding="utf-8")
# Keep only the last entry per gate id — later runs overwrite earlier ones.
latest = {}
for m in re.finditer(r'mobile-gate-(\d+):\s*([a-z_]+)\s+status=(\w+)(?:\s+reason=([^\s]+))?\s*(?:ts=(\S+))?', log):
    gid, name, status, reason, ts = m.group(1), m.group(2), m.group(3), m.group(4) or '', m.group(5) or ''
    latest[gid] = (name, status, reason, ts)
# Emit in gate-id order (6,7,8,9,10)
for gid in sorted(latest.keys(), key=int):
    name, status, reason, ts = latest[gid]
    print(f"G{gid}\t{name}\t{status}\t{reason}\t{ts}")
PY
    fi
    ;;
esac

# Also collect mobile security audit findings if present (from /vg:test step 5f_mobile_security_audit)
: > "${VG_TMP}/uat-mobile-security.txt"
case "$PROFILE" in
  mobile-*)
    SEC_REPORT="${PHASE_DIR}/mobile-security/report.md"
    if [ -f "$SEC_REPORT" ]; then
      # Surface the summary counts only (details live in the report file)
      grep -E "^(CRITICAL|HIGH|MEDIUM|LOW)\|" "$SEC_REPORT" > "${VG_TMP}/uat-mobile-security.txt" 2>/dev/null || true
    fi
    ;;
esac
```

**Now present SECTION COUNTS to user:**
```
UAT Checklist for Phase {PHASE_NUMBER}:
  Section A — Decisions (CONTEXT P{phase}.D-XX): {count} items
  Section A.1 — Foundation cites (F-XX):    {count} items (0 = none cited)
  Section B — Goals (TEST-GOALS G-XX):      {count} items
  Section C — Ripple callers (HIGH):        {count} callers need acknowledgment
  Section D — Design refs:                  {count} refs + {mobile_count} simulator shots
  Section E — Deliverables (summary):       {count} tasks
  Section F — Mobile gates (mobile only):   {count} gate rows + {N} sec findings  [OMITTED for web]
  Test verdict:                              {VERDICT from Gate 3}

Proceed with UAT? (y/n/abort)
```

If user aborts → stop, write UAT.md with status `ABORTED`.
</step>

<step name="5_interactive_uat">
**Run interactive checklist — one item at a time.**

For each section:

### A. Decisions
For each line in `${VG_TMP}/uat-decisions.txt`:
```
AskUserQuestion:
  "Decision {ID} (P{phase}.D-XX from CONTEXT, or legacy D-XX): {title}
   Was this implemented as specified in CONTEXT.md?

   [p] Pass — verified in code/runtime
   [f] Fail — not implemented correctly (note the issue)
   [s] Skip — cannot verify right now (deferred)"
```

### B. Goals
For each line in `${VG_TMP}/uat-goals.txt` where status = READY:
```
AskUserQuestion:
  "Goal {G-XX}: {title}   [STATUS: READY per coverage matrix]
   Verified working in runtime?

   [p] Pass — functions as TEST-GOALS.md success criteria
   [f] Fail — doesn't work / wrong behavior
   [s] Skip — not testable here (deferred)"
```

For BLOCKED/UNREACHABLE goals: show info block, no question asked:
```
  ⚠ Goal {G-XX}: {title}   [STATUS: BLOCKED/UNREACHABLE]
      Known gap — not gated here. Address in next phase or /vg:build --gaps-only.
```

### C. Ripple acknowledgment (MANDATORY if any HIGH callers)

**If `uat-ripples.txt` contains `RIPPLE_SKIPPED=true`** (graphify was unavailable):
```
⚠ Cross-module ripple analysis was SKIPPED (graphify unavailable during review).
  Downstream callers of changed symbols were NOT checked.
  Manual regression testing of affected modules is strongly advised.

  [y] Acknowledged — I will manually verify affected modules
  [s] Accept risk — proceed without ripple verification (recorded in UAT.md)
  [n] Abort — need to enable graphify and re-run /vg:review first
```

**Otherwise**, present the list, ask single acknowledgment question:
```
AskUserQuestion:
  "Ripple callers (HIGH severity) that were NOT updated in this phase:

   [list first 10, + '... and N more' if > 10]

   Each should have been manually reviewed or explicitly cited.
   Have you verified these callers still work with the changed symbols?

   [y] Yes — verified (per RIPPLE-ANALYSIS.md + code review)
   [n] No — need to review before accepting (ABORT UAT)
   [s] Skip — accept risk (record in UAT.md)"
```

If `n` → abort UAT, write UAT.md status = `DEFERRED_PENDING_RIPPLE_REVIEW`.

### D. Design fidelity (if design refs exist)
For each unique design-ref in `${VG_TMP}/uat-designs.txt`:
```
AskUserQuestion:
  "Design ref: {ref}
   Screenshot: ${PLANNING_DIR}/design-normalized/screenshots/{ref}.png (or similar)
   Built output matches screenshot (layout, spacing, components)?

   [p] Pass — visual match
   [f] Fail — significant drift (describe)
   [s] Skip — no design ref available / cannot verify"
```

**Mobile extension** (runs ONLY when `$PROFILE` matches `mobile-*`):
For each simulator/emulator screenshot in `${VG_TMP}/uat-mobile-screenshots.txt`:
```
AskUserQuestion:
  "Simulator capture: {path}
   Captured by /vg:review phase2_mobile_discovery. Compare against closest
   design-ref (above) — does the running app match the intended layout?

   [p] Pass — visual match vs design-ref
   [f] Fail — drift (typography, color, spacing, or content off)
   [s] Skip — no matching design-ref to compare against"
```
If no screenshots exist (host lacked simulator/emulator), inform user:
```
  ⚠ No mobile screenshots captured — host OS/tooling could not run simulator/emulator.
    Section D mobile sub-checks skipped (expected on Windows for iOS).
```

### E. Deliverables (informational only — no per-item question)
Present `${VG_TMP}/uat-summary.txt` as a final summary block. No questions.

### F. Mobile gates (mobile profiles only — skipped for web)

Present the gate table from `${VG_TMP}/uat-mobile-gates.txt`. Example:
```
  G6  permission_audit        passed
  G7  cert_expiry             skipped (disabled)
  G8  privacy_manifest        passed
  G9  native_module_linking   skipped (no-tool)
  G10 bundle_size             passed
```

Plus security audit findings (if any) from `${VG_TMP}/uat-mobile-security.txt`:
```
  CRITICAL|hardcoded_secrets|3 match(es) — see mobile-security/hardcoded-secrets.txt
  MEDIUM|weak_crypto|1 MD5 usage — see mobile-security/weak-crypto.txt
```

```
AskUserQuestion (once, covers entire Section F):
  "Mobile gate outcomes look correct for this phase?
   (e.g. 'cert_expiry skipped because no signing yet' = OK if pre-release;
    'hardcoded_secrets=3' requires explanation before accept)

   [y] Acknowledged — outcomes match phase intent
   [n] Not OK — gate output points to an actual issue (ABORT / REJECT)
   [s] Skip — accept risk (record in UAT.md)"
```

If `n` → abort UAT, set phase verdict = REJECTED with reason `mobile-gate-review-fail`.

After all sections, present totals:
```
UAT Progress:
  Decisions (A):     {N} passed / {N} failed / {N} skipped
  Goals (B):         {N} passed / {N} failed / {N} skipped (+ {N} known gaps)
  Ripples (C):       {acknowledged | abort | accepted-risk}
  Designs (D):       {N} passed / {N} failed / {N} skipped  ({Nmob} mobile screenshots)
  Mobile gates (F):  {acknowledged | rejected | risk-accepted}  [only for mobile-*]
```

### Final verdict question
```
AskUserQuestion:
  "Overall phase verdict?

   [a] ACCEPT — phase complete (all critical items pass)
   [r] REJECT — issues found, need /vg:build --gaps-only
   [d] DEFER — partial accept, revisit later (record open items)"
```

Record all responses with timestamps in orchestrator memory for step 6.
</step>

<step name="6_write_uat_md">
Write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with ALL collected data.

```markdown
# Phase {PHASE_NUMBER} — UAT Results

**Date:** {ISO timestamp}
**Tester:** {git user.name} (human UAT driven by VG artifacts)
**Profile:** {PROFILE}
**Verdict:** {ACCEPTED | REJECTED | DEFERRED}
**Test verdict (pre-UAT):** {VERDICT from SANDBOX-TEST.md}

## A. Decisions (CONTEXT.md P{phase}.D-XX — or legacy D-XX)
| ID | Title | Result | Note |
|----|-------|--------|------|
| P7.10.1.D-01 | {...} | PASS / FAIL / SKIP | {...} |
| D-02 (legacy) | {...} | PASS | run migrate-d-xx-namespace.py to normalize |
| ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S

## A.1 Foundation Citations (FOUNDATION.md F-XX — only populated if cited in phase artifacts)
| F-XX | Title | Result | Note |
|------|-------|--------|------|
| F-01 | Platform = web-saas | PASS / FAIL / SKIP | verified F-XX assumption holds for this phase |
| ... | ... | ... | ... |

Empty if no F-XX references found in phase artifacts.

## B. Goals (TEST-GOALS.md G-XX)
| G-XX | Title | Coverage Status | UAT Result | Note |
|------|-------|----------------|------------|------|
| G-01 | {...} | READY | PASS | {...} |
| G-02 | {...} | BLOCKED | — | Known gap |
| ... | ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S  (+ {N} pre-known gaps not gated)

## B.1 UNREACHABLE Triage (from UNREACHABLE-TRIAGE.md)

Surfaced only when `/vg:review` produced triage. Each entry shows verdict + resolution path.

### Resolved (cross-phase, owner accepted) — informational
| G-XX | Owning phase | Title |
|------|-------------|-------|
| (populated from `${VG_TMP}/uat-unreachable-resolved.txt`) |

### Unreachable Debt (only present when `--allow-unreachable` was used)
**Override reason:** {from `${VG_TMP}/uat-unreachable-reason.txt`}

| G-XX | Verdict | Title | Required follow-up |
|------|---------|-------|---------------------|
| (populated from `${VG_TMP}/uat-unreachable-debt.txt`) |

These goals shipped with known gaps. Auto-tracked in override-debt register; will surface in `/vg:telemetry` and milestone audit until cleared.

## C. Ripple Acknowledgment (RIPPLE-ANALYSIS.md)
- Total HIGH callers: {N}
- Response: {acknowledged | risk-accepted | review-deferred}
- Affected files: {first 20}

## D. Design Fidelity (PLAN <design-ref>)
| Design ref | Result | Note |
|------------|--------|------|
| {ref} | PASS / FAIL / SKIP | {...} |

Totals: {passed}P / {failed}F / {skipped}S

### D.1 Mobile simulator captures (mobile-* only; omit for web)
| Screenshot path | Compared against | Result | Note |
|-----------------|------------------|--------|------|
| {phase/discover/G-01-ios.png} | {design-ref} | PASS / FAIL / SKIP | {...} |

## E. Deliverables (informational, from SUMMARY)
- {N} tasks built, see SUMMARY*.md

## F. Mobile Gates (mobile-* profiles only; omit for web)

Parsed from `build-state.log` (latest occurrence per gate kept).

| Gate | Name | Status | Reason | Timestamp |
|------|------|--------|--------|-----------|
| G6 | permission_audit | passed / failed / skipped | {disabled | no-paths | ...} | {UTC iso} |
| G7 | cert_expiry | ... | ... | ... |
| G8 | privacy_manifest | ... | ... | ... |
| G9 | native_module_linking | ... | ... | ... |
| G10 | bundle_size | ... | ... | ... |

### F.1 Mobile security audit findings (from /vg:test 5f_mobile_security_audit)

| Severity | Category | Summary | Evidence file |
|----------|----------|---------|---------------|
| {CRITICAL | HIGH | MEDIUM | LOW} | {category} | {count} match(es) | mobile-security/{category}.txt |

Reviewer acknowledgment: {ACK / REJECT / RISK-ACCEPTED}

## Issues Found
{bulleted list of FAIL items across all sections, or "None"}

## Overall Summary
- Total items: {N_total}
- Passed: {N_passed}
- Failed: {N_failed}
- Skipped/deferred: {N_skipped}
- Known pre-existing gaps (not gated): {N_gaps}

## Next Step
{
  ACCEPTED: "Phase complete. Run /vg:next or proceed to next phase.",
  REJECTED: "Address failed items via /vg:build ${PHASE_NUMBER} --gaps-only, then re-run /vg:test + /vg:accept.",
  DEFERRED: "Partial accept — open items: {list}. Revisit with /vg:accept ${PHASE_NUMBER} --resume."
}

---
_Generated by /vg:accept — data-driven UAT over VG artifacts._
```

Touch marker:
```bash
touch "${PHASE_DIR}/.step-markers/accept.done"
```
</step>

<step name="7_post_accept_actions">
### If ACCEPTED

**Cleanup scan intermediates** (large JSON files from review, not needed after accept):
```bash
rm -f "${PHASE_DIR}"/scan-*.json
rm -f "${PHASE_DIR}"/probe-*.json
rm -f "${PHASE_DIR}"/nav-discovery.json
rm -f "${PHASE_DIR}"/discovery-state.json
rm -f "${PHASE_DIR}"/view-assignments.json
rm -f "${PHASE_DIR}"/element-counts.json
rm -f "${PHASE_DIR}"/.ripple-input.txt
rm -f "${PHASE_DIR}"/.ripple.json     # aggregated into UAT.md
rm -f "${PHASE_DIR}"/.callers.json    # served its purpose during build
rm -f "${PHASE_DIR}"/.god-nodes.json
rm -rf "${PHASE_DIR}"/.wave-context
rm -rf "${PHASE_DIR}"/.wave-tasks

# Keep: SPECS, CONTEXT, PLAN*, API-CONTRACTS, TEST-GOALS, SUMMARY*,
#       RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md,
#       RIPPLE-ANALYSIS.md, UAT.md, .step-markers/
```

**Cleanup root-leaked screenshots** (banned location per project convention):
```bash
rm -f ./${PHASE_NUMBER}-*.png 2>/dev/null || true
```

**Prune git worktrees + playwright locks**:
```bash
git worktree prune 2>/dev/null || true
[ -x "${HOME}/.claude/playwright-locks/playwright-lock.sh" ] && \
  bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" cleanup 0 all 2>/dev/null || true
```

**Update VG-native state:**
```bash
# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'complete'; s['pipeline_step'] = 'accepted'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# VG-native ROADMAP update (grep + sed)
if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* complete/" "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi

# v1.14.0+ A.4 — flip CROSS-PHASE-DEPS rows chờ phase này
# Khi phase X được accept → mọi row `Depends On == X` chưa flip sẽ được đánh dấu Flipped At = now
# Script cũng gợi ý /vg:review {source} --reverify-deferred cho các phase bị ảnh hưởng
CPD_SCRIPT="${REPO_ROOT:-.}/.claude/scripts/vg_cross_phase_deps.py"
if [ -f "$CPD_SCRIPT" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$CPD_SCRIPT" flip "$PHASE_NUMBER" 2>&1 | sed 's/^/  /' || true
fi

# v1.14.0+ C.3 — DEPLOY-RUNBOOK lifecycle
# Flow: auto-draft (nếu có .deploy-log.txt) → prompt user fill section 5
# (skip nếu offline → PENDING-LESSONS-REVIEW) → promote staged → aggregator refresh
RUNBOOK_DRAFTER="${REPO_ROOT:-.}/.claude/scripts/vg_deploy_runbook_drafter.py"
RUNBOOK_AGGREGATOR="${REPO_ROOT:-.}/.claude/scripts/vg_deploy_aggregator.py"
DEPLOY_LOG="${PHASE_DIR}/.deploy-log.txt"
RUNBOOK_STAGED="${PHASE_DIR}/DEPLOY-RUNBOOK.md.staged"
RUNBOOK_CANONICAL="${PHASE_DIR}/DEPLOY-RUNBOOK.md"

if [ -f "$RUNBOOK_DRAFTER" ] && { [ -f "$DEPLOY_LOG" ] || [ -f "$RUNBOOK_STAGED" ] || [ -f "$RUNBOOK_CANONICAL" ]; }; then
  # Luôn re-draft staged từ log mới nhất (idempotent)
  if [ -f "$DEPLOY_LOG" ]; then
    echo ""
    echo "━━━ Sổ tay triển khai (DEPLOY-RUNBOOK) ━━━"
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$RUNBOOK_DRAFTER" "$PHASE_DIR" 2>&1 | sed 's/^/  /'
  fi

  # Promote staged → canonical (if exists)
  if [ -f "$RUNBOOK_STAGED" ]; then
    # Keep canonical content nếu user đã edit section 5 (human-filled)
    # Heuristic: nếu canonical EXISTS và có dấu "LESSONS_USER_INPUT_PENDING" → overwrite;
    # else preserve (user đã fill, merge sẽ phức tạp — giữ nguyên canonical)
    if [ -f "$RUNBOOK_CANONICAL" ] && ! grep -q "LESSONS_USER_INPUT_PENDING" "$RUNBOOK_CANONICAL" 2>/dev/null; then
      echo "  ℹ Canonical RUNBOOK có section 5 filled — giữ nguyên, staged bỏ."
      rm -f "$RUNBOOK_STAGED"
    else
      mv -f "$RUNBOOK_STAGED" "$RUNBOOK_CANONICAL"
      echo "  ✓ Promoted: DEPLOY-RUNBOOK.md.staged → DEPLOY-RUNBOOK.md"
    fi
  fi

  # Check pending lessons — add to queue nếu chưa fill
  if [ -f "$RUNBOOK_CANONICAL" ] && grep -q "LESSONS_USER_INPUT_PENDING" "$RUNBOOK_CANONICAL" 2>/dev/null; then
    mkdir -p .vg
    PENDING_LESSONS=".vg/PENDING-LESSONS-REVIEW.md"
    PHASE_PENDING_LINE="| ${PHASE_NUMBER} | ${PHASE_DIR}/DEPLOY-RUNBOOK.md | $(date -u +%FT%TZ) |"

    if [ ! -f "$PENDING_LESSONS" ]; then
      cat > "$PENDING_LESSONS" <<'EOT'
# Pending Lessons Review — hàng đợi RUNBOOK chờ điền section 5

Mỗi row = 1 phase đã accept nhưng section 5 (Lessons) còn marker
`<!-- LESSONS_USER_INPUT_PENDING -->`. User điền khi online, xoá
marker để de-queue.

| Phase | RUNBOOK Path | Accepted At |
|---|---|---|
EOT
    fi

    # Idempotent: chỉ append nếu phase chưa có row
    if ! grep -q "^| ${PHASE_NUMBER} " "$PENDING_LESSONS" 2>/dev/null; then
      echo "$PHASE_PENDING_LINE" >> "$PENDING_LESSONS"
      echo "  ⏳ Section 5 (Lessons) chưa fill — queued vào .vg/PENDING-LESSONS-REVIEW.md"
      echo "     Mở DEPLOY-RUNBOOK.md, điền phần 'User-filled', xoá marker để de-queue."
    fi
  fi

  # Aggregator refresh (6 outputs project-wide)
  if [ -f "$RUNBOOK_AGGREGATOR" ]; then
    echo ""
    echo "━━━ Làm mới Bộ tổng hợp (aggregators) ━━━"
    PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$RUNBOOK_AGGREGATOR" 2>&1 | sed 's/^/  /' || true
  fi
else
  echo "ℹ Phase ${PHASE_NUMBER} không có `.deploy-log.txt` — skip RUNBOOK flow."
  echo "   (Phase này không chạy qua --sandbox mode với deploy-logging bật.)"
fi
```

**Commit UAT.md + RUNBOOK + cross-phase artifacts**:
```bash
# Base artifacts
git add "${PHASE_DIR}/${PHASE_NUMBER}-UAT.md" "${PHASE_DIR}/.step-markers/accept.done"

# v1.14.0+ C.3 — RUNBOOK canonical (nếu đã promoted)
[ -f "${PHASE_DIR}/DEPLOY-RUNBOOK.md" ] && git add "${PHASE_DIR}/DEPLOY-RUNBOOK.md"

# v1.14.0+ A.4 + C.4 — project-wide aggregators có thể đã update
for f in .vg/CROSS-PHASE-DEPS.md \
         .vg/DEPLOY-LESSONS.md .vg/ENV-CATALOG.md \
         .vg/DEPLOY-FAILURE-REGISTER.md .vg/DEPLOY-RECIPES.md \
         .vg/DEPLOY-PERF-BASELINE.md .vg/SMOKE-PACK.md \
         .vg/PENDING-LESSONS-REVIEW.md; do
  [ -f "$f" ] && git add "$f"
done

git commit -m "docs(${PHASE_NUMBER}-accept): UAT accepted — {N_passed}/{N_total} items pass

Covers goal: accept phase ${PHASE_NUMBER}"
```

Display:
```
Phase {PHASE_NUMBER} ACCEPTED ✓
Artifacts preserved: SPECS, CONTEXT, PLAN, API-CONTRACTS, TEST-GOALS, SUMMARY,
                     RUNTIME-MAP, GOAL-COVERAGE-MATRIX, SANDBOX-TEST, RIPPLE-ANALYSIS, UAT,
                     DEPLOY-RUNBOOK (v1.14.0+)
Updated aggregators (v1.14.0+): CROSS-PHASE-DEPS, DEPLOY-LESSONS, ENV-CATALOG,
                     DEPLOY-FAILURE-REGISTER, DEPLOY-RECIPES, DEPLOY-PERF-BASELINE, SMOKE-PACK
Cleaned: scan-*.json, probe-*.json, .wave-context, discovery intermediates
State: GSD roadmap updated (if installed)
▶ /vg:next
```

### If REJECTED

Extract failed items from UAT.md per section into a gap list. Suggest next step:
```
Phase {PHASE_NUMBER} REJECTED — {N_failed} issues.

Failed items:
  [A] Decisions: {list of failed D-XX}
  [B] Goals:     {list of failed G-XX}
  [C] Ripples:   {if deferred}
  [D] Designs:   {list of failed refs}

Next: /vg:build ${PHASE_NUMBER} --gaps-only  (auto-creates gap-closure plans from UAT.md FAIL items)
      Then: /vg:test ${PHASE_NUMBER} → /vg:accept ${PHASE_NUMBER}
```

### If DEFERRED

```bash
# ⛔ HARD GATE (tightened 2026-04-17): DEFERRED marks phase incomplete.
# /vg:next must BLOCK until these items are resolved — previously DEFERRED silently
# allowed next phase to start, compounding tech debt.
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'deferred-incomplete'
s['deferred_at'] = __import__('datetime').datetime.now().isoformat()
s['deferred_items_count'] = ${N_failed:-0}
p.write_text(json.dumps(s, indent=2))
"
touch "${PHASE_DIR}/.deferred-incomplete"
```

```
Phase {PHASE_NUMBER} DEFERRED — partial accept.

⛔ /vg:next is BLOCKED for this phase until deferred items resolved.
   Open items recorded in UAT.md ({N_failed} FAIL items).
   
Resume with: /vg:accept ${PHASE_NUMBER} --resume  (reopens deferred items only)
Force-advance (NOT RECOMMENDED): /vg:next --allow-deferred
```
</step>

</process>

<success_criteria>
- All artifacts + step markers verified BEFORE UAT starts
- Checklist items generated FROM VG data (not hardcoded)
- Every D-XX, G-XX (READY), HIGH-ripple caller, design-ref addressed by user
- UAT.md written atomically with structured pass/fail/skip per section
- If ACCEPTED: cleanup + commit + state update
- If REJECTED: clear gap list pointing to /vg:build --gaps-only
- No dependency on GSD verify-work (VG-native)
- **Mobile (mobile-*) only**: Section D iterates simulator captures from
  `${PHASE_DIR}/discover/`; Section F presents gate outcomes parsed from
  `build-state.log` + security findings from `mobile-security/report.md`.
  User acknowledgment of Section F is required — rejection aborts UAT.
- **Cross-platform portability**: all paths are config-relative; no
  hardcoded device names, sim names, team IDs, or OS-specific commands.
</success_criteria>
