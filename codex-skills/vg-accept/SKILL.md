---
name: "vg-accept"
description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
metadata:
  short-description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
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

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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

Invoke this skill as `$vg-accept`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **All pipeline artifacts required** — SPECS → CONTEXT → PLAN → API-CONTRACTS → TEST-GOALS → SUMMARY → RUNTIME-MAP → GOAL-COVERAGE-MATRIX → SANDBOX-TEST. CRUD-SURFACES is required when the phase touches CRUD/resource behavior. Missing = BLOCK.
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
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-accept" "0_gate_integrity_precheck" 2>&1 || true

# v2.2 — T8 gate now routes through block_resolve. L1 auto-clears stale
# file when all entries carry resolution markers. Only genuine conflicts BLOCK.
if [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh" ]; then
  [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" ] && \
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh"
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh"
  t8_gate_check "${PLANNING_DIR}" "accept"
  T8_RC=$?
  [ "$T8_RC" -eq 2 ] && exit 2
  [ "$T8_RC" -eq 1 ] && exit 1
elif [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved — run /vg:reapply-patches --verify-gates first."
  exit 1
fi
```
</step>

```bash
# v2.2 — register run with orchestrator (idempotent with UserPromptSubmit hook)
# OHOK-8 round-4 Codex fix: parse PHASE_NUMBER BEFORE run-start
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:accept "${PHASE_NUMBER}" "${ARGUMENTS}" || { echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2; exit 1; }
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 0_gate_integrity_precheck 2>/dev/null || true
```

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

# v1.15.2 — register run so Stop hook can verify runtime_contract evidence
type -t vg_run_start >/dev/null 2>&1 && \
  vg_run_start "vg:accept" "${PHASE_NUMBER}" "${ARGUMENTS:-}"

# v2.5.1 anti-forge: show task list at flow start so user sees planned steps
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:accept" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true
```
</step>

<step name="0c_telemetry_suggestions">
## Step 0c — Reactive Telemetry Suggestions (v2.5 Phase E)

Surface suggestions (skip/reorder/override-abuse). UNQUARANTINABLE security validators NEVER suggested for skip.

```bash
if [ -f ".claude/scripts/telemetry-suggest.py" ]; then
  SUGGESTIONS=$(${PYTHON_BIN:-python3} .claude/scripts/telemetry-suggest.py --command vg:accept 2>/dev/null || echo "")
  if [ -n "$SUGGESTIONS" ]; then
    COUNT=$(echo "$SUGGESTIONS" | grep -c '^{' || echo 0)
    if [ "${COUNT:-0}" -gt 0 ]; then
      echo "▸ Telemetry suggestions for vg:accept (${COUNT}, advisory — skip never suggested for security):"
      echo "$SUGGESTIONS" | head -3 | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line); t=d.get('type','?')
        if t=='skip': print(f\"  [skip] {d.get('validator','?')} — {d.get('pass_rate',0):.0%} over {d.get('samples',0)}\")
        elif t=='reorder': print(f\"  [reorder-late] {d.get('validator','?')} p95={d.get('p95_ms',0)}ms\")
        elif t=='override_abuse': print(f\"  [override-abuse] {d.get('flag','?')} used {d.get('count_30d',0)}x/30d\")
    except Exception: pass
" 2>/dev/null
    fi
  fi
fi
touch "${PHASE_DIR}/.step-markers/0c_telemetry_suggestions.done"
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

CRUD_VAL="${REPO_ROOT:-.}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT:-.}/.claude/vg.config.md" \
    > "${PHASE_DIR}/.tmp/crud-surface-accept.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD-SURFACES.md contract invalid — see ${PHASE_DIR}/.tmp/crud-surface-accept.json"
    exit 2
  fi
fi

# Harness v2.6.1 (2026-04-26): rule-cards drift gate. WARN if any
# .codex/skills/vg-*/SKILL.md is newer than its RULES-CARDS.md sibling.
# Per AUDIT.md D4 finding (drift gate not wired into accept pipeline).
# Non-blocking — operator runs extract-rule-cards.py to refresh.
if [ -f "${REPO_ROOT:-.}/.claude/scripts/validators/verify-rule-cards-fresh.py" ]; then
  echo ""
  echo "━━━ Rule-cards freshness check ━━━"
  "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rule-cards-fresh.py 2>&1 | tail -5
  echo ""
fi
```
</step>

<step name="2_marker_precheck">
**Gate 2: Step markers (deterministic — AI did not skip silently)**

Profile determines which steps must have markers. Use `filter-steps.py` to compute the expected set per command, then verify each marker exists.

```bash
MARKER_DIR="${PHASE_DIR}/.step-markers"
mkdir -p "$MARKER_DIR"

# Load marker schema library (OHOK Batch 5b / E1) — content-aware verify
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/marker-schema.sh" 2>/dev/null || true

MISSED=""
FORGED=""
LEGACY=""
for cmd in build review test; do
  CMD_FILE=".claude/commands/vg/${cmd}.md"
  [ -f "$CMD_FILE" ] || continue
  EXPECTED=$(${PYTHON_BIN} .claude/scripts/filter-steps.py \
    --command "$CMD_FILE" --profile "$PROFILE" --output-ids 2>/dev/null)
  [ -z "$EXPECTED" ] && continue
  for step in $(echo "$EXPECTED" | tr ',' ' '); do
    # v2.5.2.11 — marker path dual-convention fallback.
    # Historical: flat `${MARKER_DIR}/${step}.done`.
    # Current:    subdir  `${MARKER_DIR}/${cmd}/${step}.done` (prevents name
    #             collisions across commands, e.g. build:1_parse_args vs
    #             review:1_parse_args). Subdir convention is what the skills
    #             actually write today. Accept gate must look for either.
    MARKER_FILE_FLAT="${MARKER_DIR}/${step}.done"
    MARKER_FILE_SUBDIR="${MARKER_DIR}/${cmd}/${step}.done"
    if [ -f "$MARKER_FILE_SUBDIR" ]; then
      MARKER_FILE="$MARKER_FILE_SUBDIR"
    elif [ -f "$MARKER_FILE_FLAT" ]; then
      MARKER_FILE="$MARKER_FILE_FLAT"
    else
      MISSED="$MISSED ${cmd}:${step}"
      continue
    fi
    # Content-aware verification (CrossAI R6 Batch 5b fix)
    if type -t verify_marker >/dev/null 2>&1; then
      verify_marker "$MARKER_FILE" "$PHASE_NUMBER" "$step" 30 2>/dev/null
      rc=$?
      case $rc in
        0) : ;;  # valid
        2) LEGACY="$LEGACY ${cmd}:${step}" ;;  # empty marker (pre-5b)
        3|4|5|6|7) FORGED="$FORGED ${cmd}:${step}(rc=$rc)" ;;
      esac
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

# Batch 5b: hard-block on content integrity violations (forged/mismatched/stale)
if [ -n "$(echo "$FORGED" | xargs)" ]; then
  echo "⛔ Marker content integrity violations detected (forgery / mismatch / stale):" >&2
  for m in $FORGED; do echo "   - $m" >&2; done
  echo "" >&2
  echo "   rc=3 schema, rc=4 phase mismatch, rc=5 step mismatch," >&2
  echo "   rc=6 git_sha not ancestor of HEAD (likely forged via touch)," >&2
  echo "   rc=7 marker older than 30 days (stale run state)." >&2
  echo "" >&2
  echo "   Re-run the affected step to emit a fresh valid marker." >&2
  echo "   Override (NOT recommended): --allow-forged-markers (log debt)." >&2
  if [[ ! "${ARGUMENTS:-}" =~ --allow-forged-markers ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.marker_forgery_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"count\":$(echo $FORGED | wc -w)}" >/dev/null 2>&1 || true
    exit 1
  fi
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-marker-forgery" "${PHASE_NUMBER}" \
    "forged/mismatched/stale markers: $(echo $FORGED | xargs)" "${PHASE_DIR}"
fi

# Legacy empty markers — WARN only, nudge user to migrate
if [ -n "$(echo "$LEGACY" | xargs)" ]; then
  LEGACY_COUNT=$(echo $LEGACY | wc -w)
  echo "⚠ ${LEGACY_COUNT} legacy empty markers (pre-Batch-5b format):" >&2
  for m in $LEGACY; do echo "   - $m" >&2; done
  echo "   Run once: python .claude/scripts/marker-migrate.py --planning ${PLANNING_DIR:-.vg}" >&2
  echo "   Strict mode: export VG_MARKER_STRICT=1 to BLOCK on legacy markers." >&2
fi

echo "✓ All expected step markers present for profile: $PROFILE"
```
</step>

<step name="3_sandbox_verdict_gate">
**Gate 3: Test verdict**

```bash
SANDBOX=$(ls "${PHASE_DIR}"/*SANDBOX-TEST.md 2>/dev/null | head -1)
# OHOK-8 round-4 Codex fix: accept emits verdict in 3 formats across versions.
# Parser now accepts all:
#   `**Verdict:** PASSED`           (bold inline)
#   `Verdict: PASSED`                (plain prefix)
#   `## Verdict: PASSED`             (markdown heading — test.md canonical)
#   `status: passed` (YAML frontmatter, lowercased values)
# Previous regex only matched the first two → test.md's heading format
# produced a false BLOCK "verdict not parseable" after a valid /vg:test.
VERDICT=$(grep -iE "^\s*#+\s*Verdict:?|^\s*\*\*Verdict:?\*\*|^\s*Verdict:|^\s*status:" "$SANDBOX" \
  | head -1 \
  | grep -oiE "PASSED|GAPS_FOUND|FAILED|passed|gaps_found|failed" \
  | head -1 \
  | tr '[:lower:]' '[:upper:]')

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

### Section B.1: CRUD surfaces (from CRUD-SURFACES.md)

Parse each resource contract into UAT rows. These are the human-facing
checkpoints for list/read/create/update/delete surfaces: headings,
descriptions, filters, search, sort, paging, table columns/actions, form
validation, duplicate-submit guard, delete confirmation, object/field auth,
CSRF/XSS posture, rate limit, abuse guards, audit log, and performance budget.

```bash
${PYTHON_BIN} - <<PY > "${VG_TMP}/uat-crud-surfaces.txt"
import json
import re
from pathlib import Path

path = Path("${PHASE_DIR}/CRUD-SURFACES.md")
if not path.exists():
    raise SystemExit(0)
text = path.read_text(encoding="utf-8", errors="replace")
m = re.search(r"```(?:json|crud-surface)\s*(\{.*?\})\s*```", text, re.DOTALL)
raw = m.group(1) if m else text.strip()
try:
    data = json.loads(raw)
except Exception as exc:
    print(f"INVALID\tparse-error\t{exc}")
    raise SystemExit(0)

for resource in data.get("resources", []):
    if not isinstance(resource, dict):
        continue
    name = resource.get("name", "<unnamed>")
    ops = ",".join(resource.get("operations", []))
    platforms = resource.get("platforms", {}) if isinstance(resource.get("platforms"), dict) else {}
    overlays = ",".join(sorted(platforms.keys()))
    checkpoints = []
    if "web" in platforms:
        checkpoints.extend(["web:list/form/delete", "web:url-state", "web:a11y-states"])
    if "mobile" in platforms:
        checkpoints.extend(["mobile:deep-link", "mobile:tap-target", "mobile:offline/network"])
    if "backend" in platforms:
        checkpoints.extend(["backend:query-contract", "backend:authz/csrf", "backend:abuse/perf"])
    base = resource.get("base", {}) if isinstance(resource.get("base"), dict) else {}
    if base:
        checkpoints.extend(["base:business-flow", "base:security", "base:delete-policy"])
    print(f"{name}\t{ops}\t{overlays}\t{', '.join(dict.fromkeys(checkpoints))}")
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
```

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
  Section B.1 — CRUD surfaces:              {count} resource rows
  Section C — Ripple callers (HIGH):        {count} callers need acknowledgment
  Section D — Design refs:                  {count} refs + {mobile_count} simulator shots
  Section E — Deliverables (summary):       {count} tasks
  Section F — Mobile gates (mobile only):   {count} gate rows + {N} sec findings  [OMITTED for web]
  Test verdict:                              {VERDICT from Gate 3}

Proceed with UAT? (y/n/abort)
```

If user aborts → stop, write UAT.md with status `ABORTED`.
</step>

<step name="4b_uat_narrative_autofire">
**Phase 15 D-10 — Auto-generate UAT-NARRATIVE.md before interactive UAT (NEW, 2026-04-27).**

Before stepping into the interactive checklist, render the per-prompt UAT
narrative document so the human tester opens it side-by-side with their
browser. The narrative is built from 4 frontmatter fields per goal
(`entry_url`, `navigation_steps`, `precondition`, `expected_behavior`)
plus design-ref blocks where present (D-10 spec). Strings come ONLY from
narration-strings.yaml — no hardcoded labels (D-18 strict enforcement).

The generator (`scripts/build-uat-narrative.py`) is deterministic, takes
no Sonnet round-trip, and idempotently overwrites `UAT-NARRATIVE.md`
each run so re-acceptance always reflects the latest TEST-GOALS state.
A sibling `UAT-NARRATIVE-OVERRIDES.md` (if present) is appended verbatim
at the end so manual prose can survive regeneration.

```bash
NARRATIVE_OUT="${PHASE_DIR}/UAT-NARRATIVE.md"
NARRATIVE_GEN="${REPO_ROOT}/.claude/scripts/build-uat-narrative.py"

if [ ! -f "$NARRATIVE_GEN" ]; then
  echo "⚠ build-uat-narrative.py missing — skipping narrative auto-fire (Phase 15 T5.1 not installed)" >&2
else
  ${PYTHON_BIN} "$NARRATIVE_GEN" \
      --phase-dir "${PHASE_DIR}" \
      --vg-config "${REPO_ROOT}/vg.config.md" \
      --output    "$NARRATIVE_OUT" \
      || {
        echo "⛔ UAT narrative generation failed — see stderr above." >&2
        echo "   Inspect TEST-GOALS frontmatter for missing entry_url / navigation_steps / precondition / expected_behavior." >&2
        exit 1
      }
  echo "✓ UAT-NARRATIVE.md written → ${NARRATIVE_OUT}"
fi

# D-05/06/07 — verify the 4 mandatory fields per prompt
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uat-narrative-fields.py" \
    --phase "${PHASE_NUMBER}" \
    > "${VG_TMP}/uat-narrative-fields.json" 2>&1
NARR_VERDICT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/uat-narrative-fields.json')).get('verdict','BLOCK'))" 2>/dev/null)
case "$NARR_VERDICT" in
  PASS|WARN) echo "✓ UAT narrative fields validator: $NARR_VERDICT" ;;
  *) echo "⛔ UAT narrative fields validator: $NARR_VERDICT — see ${VG_TMP}/uat-narrative-fields.json" >&2; exit 1 ;;
esac

# D-18 — verify no hardcoded UAT strings leaked into the rendered narrative
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-uat-strings-no-hardcode.py" \
    --phase "${PHASE_NUMBER}" \
    --narrative "$NARRATIVE_OUT" \
    > "${VG_TMP}/uat-strings.json" 2>&1
STR_VERDICT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/uat-strings.json')).get('verdict','BLOCK'))" 2>/dev/null)
case "$STR_VERDICT" in
  PASS|WARN) echo "✓ UAT strings hardcode scan: $STR_VERDICT" ;;
  *) echo "⛔ UAT strings hardcode scan: $STR_VERDICT — narrative contains literal labels not from narration-strings.yaml. See ${VG_TMP}/uat-strings.json" >&2; exit 1 ;;
esac

echo ""
echo "▸ UAT-NARRATIVE.md ready. Open it side-by-side with your browser:"
echo "    ${NARRATIVE_OUT}"
echo ""
```

The interactive UAT in step 5 references this document — testers walk each
prompt with the narrative open in another window. The narrative does NOT
replace the interactive checklist; it provides the WHY/HOW context that
used to live only in tester memory.
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

### Response persistence (OHOK Batch 3 B4 — REQUIRED for quorum gate)

**AI MUST write each AskUserQuestion response to `${PHASE_DIR}/.uat-responses.json` immediately after the user answers.** This is the source of truth read by step `5_uat_quorum_gate` below. Without persistence, the quorum gate BLOCKs (treats unset state as "user skipped everything").

Format:
```json
{
  "decisions": {"pass": 0, "fail": 0, "skip": 0, "items": [{"id": "P7.D-01", "verdict": "p|f|s", "ts": "..."}]},
  "goals": {"pass": 0, "fail": 0, "skip": 0, "items": [{"id": "G-01", "status_before": "READY", "verdict": "p|f|s", "ts": "..."}]},
  "ripples": {"verdict": "y|n|s|acknowledged|risk-accepted", "ts": "..."},
  "designs": {"pass": 0, "fail": 0, "skip": 0, "items": [{"ref": "sites-list.default", "verdict": "p|f|s", "ts": "..."}]},
  "mobile_gates": {"verdict": "y|n|s", "ts": "..."},
  "final": {"verdict": "ACCEPT|REJECT|DEFER", "ts": "..."}
}
```

AI can write/update this JSON via Bash heredoc after each section completes. Missing sections that are N/A for this profile (e.g. mobile_gates for web) should be omitted or set to `{"verdict": "n/a"}`.

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_interactive_uat" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_interactive_uat.done"
```
</step>

<step name="5_uat_quorum_gate">
**⛔ UAT QUORUM GATE (OHOK Batch 3 B4 — block theatre UAT).**

Before Batch 3 UAT was pure theatre — every AskUserQuestion offered `[s] Skip`, user could skip decisions + goals + ripples + designs all via `[s]`, phase ships with "DEFERRED" verdict, next phase reads note and proceeds. No mechanism enforced minimum due diligence.

This gate counts SKIPs on critical sections (A decisions, B READY goals) and BLOCKs if over threshold. Config-driven via `config.accept.max_uat_skips_critical` (default 0 — strict).

```bash
# Config thresholds (default strict: 0 critical skips allowed)
MAX_CRIT_SKIPS=$(${PYTHON_BIN:-python3} - <<'PY' 2>/dev/null || echo 0
import re
from pathlib import Path
p = Path(".claude/vg.config.md")
if not p.exists():
    print(0); exit()
text = p.read_text(encoding="utf-8", errors="replace")
m = re.search(r"^\s*accept\s*:\s*\n(?:\s+[a-z_]+:.*\n)*?\s+max_uat_skips_critical\s*:\s*(\d+)", text, re.MULTILINE)
print(m.group(1) if m else "0")
PY
)

RESP_JSON="${PHASE_DIR}/.uat-responses.json"

# Gate 1: response file must exist with content
if [ ! -s "$RESP_JSON" ]; then
  echo "⛔ UAT quorum gate: .uat-responses.json missing or empty." >&2
  echo "   AI must persist each AskUserQuestion response in step 5." >&2
  echo "   Silence / verbal-only answers = BLOCK (prevents theatre UAT)." >&2
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-uat ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"no_response_json\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-empty" "${PHASE_NUMBER}" "UAT ran without persisted responses" "${PHASE_DIR}"
fi

# Gate 1b: response JSON coverage cross-check (CrossAI R6 fix).
# Without this, attacker could write {"decisions":{"skip":0,"total":0}} and
# pass quorum trivially. Now: responses must cover every expected decision
# + READY goal derived from artifacts.
COVERAGE_CHECK=$(${PYTHON_BIN:-python3} - "$RESP_JSON" "$PHASE_DIR" 2>/dev/null <<'PY' || echo "PARSE_ERROR"
import json, re, sys
from pathlib import Path

resp_path = Path(sys.argv[1])
phase_dir = Path(sys.argv[2])

# Expected decisions = count of D-XX / P{phase}.D-XX headings in CONTEXT.md
expected_dec = 0
ctx = phase_dir / "CONTEXT.md"
if ctx.exists():
    t = ctx.read_text(encoding="utf-8", errors="replace")
    expected_dec = len(re.findall(r'^###\s+(?:P[0-9.]+\.)?D-\d+', t, re.MULTILINE))

# Expected READY goals = count of READY rows in GOAL-COVERAGE-MATRIX.md
expected_goals = 0
matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
if matrix.exists():
    t = matrix.read_text(encoding="utf-8", errors="replace")
    expected_goals = len(re.findall(r'\|\s*READY\s*\|', t))

# Responses actually recorded
try:
    data = json.loads(resp_path.read_text(encoding="utf-8"))
except Exception:
    print(f"MALFORMED:expected_dec={expected_dec},expected_goals={expected_goals}")
    sys.exit()

dec_section = data.get("decisions") or {}
goal_section = data.get("goals") or {}
# Sum of all verdicts (a/y/s/n) in decisions — attacker can't shrink this
# without removing items. Use items[] if present, else summed counters.
dec_items = dec_section.get("items") or []
dec_covered = len(dec_items) if dec_items else sum(
    int(dec_section.get(k, 0)) for k in ("accept", "edit", "skip", "reject", "a", "y", "s", "n")
)
goal_items = goal_section.get("items") or []
goal_covered = len(goal_items) if goal_items else sum(
    int(goal_section.get(k, 0)) for k in ("a", "y", "s", "n", "accept", "skip")
)

missing_dec = max(0, expected_dec - dec_covered)
missing_goal = max(0, expected_goals - goal_covered)
print(f"expected_dec={expected_dec},dec_covered={dec_covered},missing_dec={missing_dec},"
      f"expected_goals={expected_goals},goal_covered={goal_covered},missing_goal={missing_goal}")
PY
)

# Parse coverage output
MISSING_DEC=$(echo "$COVERAGE_CHECK" | sed -n 's/.*missing_dec=\([0-9]*\).*/\1/p')
MISSING_GOAL=$(echo "$COVERAGE_CHECK" | sed -n 's/.*missing_goal=\([0-9]*\).*/\1/p')
MISSING_DEC=${MISSING_DEC:-0}
MISSING_GOAL=${MISSING_GOAL:-0}

if [ "${MISSING_DEC:-0}" -gt 0 ] || [ "${MISSING_GOAL:-0}" -gt 0 ]; then
  echo "⛔ UAT coverage gate: responses don't cover all expected items" >&2
  echo "   $COVERAGE_CHECK" >&2
  echo "   Missing decisions=${MISSING_DEC}, Missing READY goals=${MISSING_GOAL}" >&2
  echo "   AI must ask + record ONE response per expected item. Partial-coverage" >&2
  echo "   JSON = attacker bypass, rejected." >&2
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-uat ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_coverage_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing_dec\":${MISSING_DEC},\"missing_goal\":${MISSING_GOAL}}" >/dev/null 2>&1 || true
    exit 1
  fi
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-undercoverage" "${PHASE_NUMBER}" \
    "responses missing: dec=${MISSING_DEC}, goals=${MISSING_GOAL}" "${PHASE_DIR}"
fi

# Gate 2: count critical skips (decisions + READY goals)
CRITICAL_SKIPS=$(${PYTHON_BIN:-python3} - "$RESP_JSON" 2>/dev/null <<'PY' || echo 999
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0); exit()
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print(999); exit()  # malformed = treat as max skips

dec_skip = (data.get("decisions") or {}).get("skip", 0)
# Only count READY-goal skips as critical; BLOCKED/UNREACHABLE goals aren't asked
goal_items = (data.get("goals") or {}).get("items", [])
goal_skip_ready = sum(
    1 for it in goal_items
    if it.get("verdict") == "s" and it.get("status_before") == "READY"
)
# Fallback: if items[] not populated, use overall skip count
if not goal_items:
    goal_skip_ready = (data.get("goals") or {}).get("skip", 0)

print(int(dec_skip) + int(goal_skip_ready))
PY
)

TOTAL_SKIPS=$(${PYTHON_BIN:-python3} - "$RESP_JSON" 2>/dev/null <<'PY' || echo 0
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0); exit()
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print(0); exit()
total = 0
for section in ("decisions", "goals", "designs"):
    total += (data.get(section) or {}).get("skip", 0)
print(total)
PY
)

echo "▸ UAT quorum: critical skips=${CRITICAL_SKIPS} (threshold=${MAX_CRIT_SKIPS}), total skips=${TOTAL_SKIPS}"

if [ "${CRITICAL_SKIPS:-0}" -gt "${MAX_CRIT_SKIPS:-0}" ]; then
  echo "⛔ UAT quorum FAILED: ${CRITICAL_SKIPS} critical skips > ${MAX_CRIT_SKIPS} (max)." >&2
  echo "" >&2
  echo "Critical = decisions (A) + READY goals (B). These MUST be verified, not skipped." >&2
  echo "" >&2
  echo "Options:" >&2
  echo "  (a) Re-run /vg:accept ${PHASE_NUMBER} and actually verify the [s]-skipped items" >&2
  echo "  (b) Raise threshold in config: accept.max_uat_skips_critical: N" >&2
  echo "  (c) --allow-uat-skips override (logs to debt, DEFERRED verdict forced)" >&2

  if [[ ! "${ARGUMENTS}" =~ --allow-uat-skips ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"critical_skips\":${CRITICAL_SKIPS},\"threshold\":${MAX_CRIT_SKIPS}}" >/dev/null 2>&1 || true
    exit 1
  fi

  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-quorum" "${PHASE_NUMBER}" \
    "${CRITICAL_SKIPS} critical UAT skips (threshold ${MAX_CRIT_SKIPS})" "${PHASE_DIR}"

  echo "⚠ --allow-uat-skips — proceeding, forced DEFERRED verdict (not ACCEPTED)" >&2
  # Rewrite final verdict to DEFER so downstream /vg:next still blocks
  ${PYTHON_BIN:-python3} - "$RESP_JSON" <<'PY'
import json, sys
from datetime import datetime
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding="utf-8"))
d.setdefault("final", {})
d["final"]["verdict"] = "DEFER"
d["final"]["forced_by"] = "uat_quorum_override"
d["final"]["ts"] = datetime.utcnow().isoformat() + "Z"
p.write_text(json.dumps(d, indent=2))
PY
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_passed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"critical_skips\":${CRITICAL_SKIPS},\"total_skips\":${TOTAL_SKIPS}}" >/dev/null 2>&1 || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_uat_quorum_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_uat_quorum_gate.done"
```
</step>

<step name="6b_security_baseline">
## Step 6b — Project-wide Security Baseline Gate (v2.5 Phase B.3)

Trước khi write UAT, verify project-wide security baseline (TLS/headers/
secrets/cookie flags/CORS/lockfile) đang đạt tầng 2+3 của security. Đây
là gate LAST defense trước production — nếu baseline drift sau các phase
trước, block accept + require fix.

Validator `verify-security-baseline.py` grep codebase + deploy scripts
(idempotent, khoảng 2-3 giây). Gate HARD cho critical findings (TLS
outdated, wildcard CORS + credentials, real secret trong .env.example),
WARN cho missing headers/cookie flags/lockfile.

```bash
echo ""
echo "━━━ Step 6b — Project-wide Security Baseline ━━━"

BASELINE_OUT=$(${PYTHON_BIN:-python3} \
  .claude/scripts/validators/verify-security-baseline.py \
  --phase "${PHASE_NUMBER}" --scope all 2>&1)
BASELINE_RC=$?

# Surface verdict + evidence
echo "$BASELINE_OUT" | tail -1 | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    verdict = d.get('verdict', '?')
    ev = d.get('evidence', [])
    print(f'  verdict: {verdict} ({len(ev)} finding(s))')
    for e in ev[:5]:
        print(f'    - {e.get(\"type\")}: {e.get(\"message\",\"\")[:200]}')
    if len(ev) > 5:
        print(f'    ... +{len(ev)-5} more — see full output')
except Exception as exc:
    print(f'  (parse error: {exc})')
" 2>/dev/null || true

if [ "$BASELINE_RC" -ne 0 ]; then
  if [[ "$ARGUMENTS" =~ --allow-baseline-drift ]]; then
    echo "⚠ Security baseline drift — OVERRIDE accepted via --allow-baseline-drift"
    type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
      "--allow-baseline-drift" "$PHASE_NUMBER" "accept.6b.security-baseline" \
      "critical baseline drift accepted by user" \
      "accept-baseline-${PHASE_NUMBER}"
    echo "override: baseline-drift phase=${PHASE_NUMBER} ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/accept-state.log" 2>/dev/null || true
  else
    echo ""
    echo "⛔ Security baseline failed project-wide check."
    echo "   Fix the findings above (TLS/CORS/secrets/headers/cookies/lockfile),"
    echo "   re-run /vg:accept ${PHASE_NUMBER}."
    echo ""
    echo "   Override (NOT recommended, logs to override-debt):"
    echo "     /vg:accept ${PHASE_NUMBER} --allow-baseline-drift"
    exit 1
  fi
else
  echo "  ✓ Project-wide security baseline PASS"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6b_security_baseline" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6b_security_baseline.done"
```
</step>

<step name="6c_learn_auto_surface">
## Step 6c — Learn Auto-Surface (v2.5 Phase H)

Invoke tier-based candidate surface to close the UX loop. Previously user had to
remember `/vg:learn --review` + duyệt 10+ candidate cùng lúc → fatigue → defer-all.
Phase H limits surface to max 2 Tier B candidates per phase with dedupe pre-pass.

Config gate: skip entirely if `bootstrap.auto_surface_at_accept: false`.

```bash
AUTO_SURFACE=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*auto_surface_at_accept:\s*(true|false)', line, re.IGNORECASE)
    if m: print(m.group(1).lower()); break
" 2>/dev/null || echo "true")

if [ "$AUTO_SURFACE" != "true" ]; then
  echo "ℹ Learn auto-surface disabled (bootstrap.auto_surface_at_accept=false). Skip."
  touch "${PHASE_DIR}/.step-markers/6c_learn_auto_surface.done"
else
  echo ""
  echo "━━━ Step 6c — Learn Auto-Surface (Phase H v2.5) ━━━"

  CAND_FILE=".vg/bootstrap/CANDIDATES.md"
  if [ ! -f "$CAND_FILE" ]; then
    echo "  (no CANDIDATES.md — reflector hasn't drafted any yet, skip)"
  else
    # 1. Dedupe pass — merge title-similar candidates in-place
    ${PYTHON_BIN:-python3} .claude/scripts/learn-dedupe.py --apply 2>&1 | tail -5 || \
      echo "  (dedupe dry-run or failed, non-blocking)"

    # 2a. (v2.6 Phase A) Shadow evaluator — compute adaptive correctness rate per candidate.
    #     Output JSONL fed to classifier as --shadow-jsonl override. Critic flag
    #     opt-in via bootstrap.critic_enabled in vg.config.md.
    SHADOW_JSONL="${PHASE_DIR}/.shadow-eval.jsonl"
    CRITIC_ENABLED=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*critic_enabled:\s*(true|false)', line, re.IGNORECASE)
    if m: print(m.group(1).lower()); break
" 2>/dev/null || echo "false")
    SHADOW_ARGS=""
    [ "$CRITIC_ENABLED" = "true" ] && SHADOW_ARGS="--critic"
    ${PYTHON_BIN:-python3} .claude/scripts/bootstrap-shadow-evaluator.py \
      $SHADOW_ARGS --output-jsonl "$SHADOW_JSONL" 2>/dev/null || \
      echo "  (shadow evaluator unavailable — classifier falls back to fixed-threshold)"

    # 2b. Classify all pending candidates by tier (adaptive override when shadow JSONL exists)
    if [ -s "$SHADOW_JSONL" ]; then
      TIER_JSONL=$(${PYTHON_BIN:-python3} .claude/scripts/learn-tier-classify.py \
        --all --shadow-jsonl "$SHADOW_JSONL" 2>/dev/null || echo "")
    else
      TIER_JSONL=$(${PYTHON_BIN:-python3} .claude/scripts/learn-tier-classify.py --all 2>/dev/null || echo "")
    fi

    if [ -z "$TIER_JSONL" ]; then
      echo "  (no pending candidates to surface)"
    else
      # 3. Tier A auto-promote (silent, 1-line log per promote)
      TIER_A_IDS=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d = json.loads(line)
        if d.get('tier') == 'A':
            print(d['id'])
    except Exception: pass
")
      A_COUNT=0
      for AID in $TIER_A_IDS; do
        [ -z "$AID" ] && continue
        echo "  ✓ Auto-promoted Tier A candidate ${AID} (adaptive shadow correctness ≥ threshold)"
        # Emit telemetry — actual promote happens via /vg:learn --promote (orchestrator must invoke)
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.rule_promoted" "PASS" "{\"id\":\"${AID}\",\"tier\":\"A\",\"auto\":true,\"path\":\"shadow_adaptive\"}" 2>/dev/null || true
        A_COUNT=$((A_COUNT+1))
      done
      [ "$A_COUNT" -gt 0 ] && echo ""

      # 3a. (v2.6 Phase A) Stale Tier A demotion — evaluator flagged demote=true
      #     for promoted rules whose correctness dropped below shadow_correctness_important.
      DEMOTE_IDS=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('demote') is True:
            print(d['id'])
    except Exception: pass
")
      for DID in $DEMOTE_IDS; do
        [ -z "$DID" ] && continue
        echo "  ⚠ Stale Tier A demote: ${DID} (correctness dropped below threshold over stale_phases window)"
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.rule_demoted" "WARN" "{\"id\":\"${DID}\",\"reason\":\"stale_low_correctness\"}" 2>/dev/null || true
      done

      # 4. Tier B surface — cap via config, interactive y/n/e/s
      TIER_B_MAX=$(${PYTHON_BIN:-python3} -c "
import re
for line in open('.claude/vg.config.md', encoding='utf-8'):
    m = re.match(r'^\s*tier_b_max_per_phase:\s*(\d+)', line)
    if m: print(m.group(1)); break
" 2>/dev/null || echo "2")

      TIER_B_COUNT=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
n=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('tier')=='B': n+=1
    except Exception: pass
print(n)
")

      if [ "${TIER_B_COUNT:-0}" -gt 0 ]; then
        echo "  ▸ ${TIER_B_COUNT} Tier B candidate(s) pending. Surface max ${TIER_B_MAX} now;"
        echo "    rest defer to next phase. Access all via: /vg:learn --review --all"
        echo ""

        # v2.6 Phase D — show proposed phase_pattern alongside each Tier B candidate.
        # Reflector populates phase_pattern based on evidence commit majors. Operator
        # can widen/narrow via e (edit) mode in the y/n/e/s gate before promotion.
        echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
    except Exception: continue
    if d.get('tier') != 'B': continue
    pat = d.get('phase_pattern', '.*')
    pat_note = '' if pat == '.*' else ' [phase_pattern=' + pat + ']'
    print('    • {id}{note}: {title}'.format(
        id=d.get('id','?'),
        note=pat_note,
        title=d.get('title','(untitled)')[:80],
    ))
" 2>/dev/null || true

        # Orchestrator must call /vg:learn --auto-surface interactively for user y/n/e/s
        echo "  → Invoking /vg:learn --auto-surface (interactive)"
        # Emit surfaced event
        type -t emit_telemetry >/dev/null 2>&1 && \
          emit_telemetry "bootstrap.candidate_surfaced" "PASS" "{\"phase\":\"${PHASE_NUMBER}\",\"tier_b_count\":${TIER_B_COUNT},\"tier_b_limit\":${TIER_B_MAX}}" 2>/dev/null || true
      else
        echo "  (no Tier B candidates pending surface)"
      fi

      # 5. Tier C silent — access only via --review --all
      TIER_C_COUNT=$(echo "$TIER_JSONL" | ${PYTHON_BIN:-python3} -c "
import json, sys
n=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        if d.get('tier')=='C': n+=1
    except Exception: pass
print(n)
")
      [ "${TIER_C_COUNT:-0}" -gt 0 ] && echo "  (Tier C parking: ${TIER_C_COUNT} low-confidence, silent — /vg:learn --review --all to view)"
    fi

    # v2.6 Phase C — pairwise conflict surface. Reuses the SAME y/n/e/s loop
    # as Tier B above (no new step number). When a contradiction is detected
    # between two ACTIVE candidates (similar prose OR opposing verbs), the
    # operator chooses to retire the loser, defer, edit, or skip. Winner is
    # auto-suggested via Phase A correctness → evidence_count fallback.
    CONFLICT_JSONL="${PHASE_DIR}/.conflict-pairs.jsonl"
    ${PYTHON_BIN:-python3} .claude/scripts/bootstrap-conflict-detector.py \
      --output-jsonl "$CONFLICT_JSONL" >/dev/null 2>&1 || \
      echo "  (conflict detector unavailable — skip conflict surface)"

    if [ -s "$CONFLICT_JSONL" ]; then
      CONFLICT_COUNT=$(wc -l < "$CONFLICT_JSONL" | tr -d ' ')
      echo ""
      echo "  ▸ ${CONFLICT_COUNT} conflict pair(s) detected between ACTIVE candidates."
      echo "    Each pair surfaces in the same y/n/e/s prompt loop as Tier B above."
      echo "    Options: y=retire loser+keep winner, n=defer both, e=edit, s=skip."
      echo ""
      ${PYTHON_BIN:-python3} -c "
import json, sys
with open(r'''${CONFLICT_JSONL}''', encoding='utf-8') as fh:
    for line in fh:
        line = line.strip()
        if not line: continue
        try:
            c = json.loads(line)
        except Exception:
            continue
        verb = c.get('opposing_verb')
        sim = c.get('similarity', 0.0)
        winner = c.get('winner') or 'TIE — operator decides'
        ec_a = c.get('evidence_count_a', 0)
        ec_b = c.get('evidence_count_b', 0)
        co_a = c.get('correctness_a')
        co_b = c.get('correctness_b')
        co_str = lambda v: f'{v:.2f}' if isinstance(v,(int,float)) else 'n/a'
        print(f\"    • {c['id_a']} vs {c['id_b']}\")
        sig = f'similarity={sim:.2f}'
        if verb: sig += f', opposing={verb}'
        print(f'      {sig}')
        print(f\"      winner suggestion: {winner} \"
              f\"(correctness {co_str(co_a)}/{co_str(co_b)}, evidence {ec_a}/{ec_b})\")
"
      # Orchestrator must call /vg:learn --auto-surface interactively to
      # process conflict pairs in the same loop as Tier B candidates.
      echo "  → Invoking /vg:learn --auto-surface (conflict resolution interactive)"
      type -t emit_telemetry >/dev/null 2>&1 && \
        emit_telemetry "bootstrap.conflict_surfaced" "PASS" "{\"phase\":\"${PHASE_NUMBER}\",\"conflict_count\":${CONFLICT_COUNT}}" 2>/dev/null || true
    fi
  fi

  touch "${PHASE_DIR}/.step-markers/6c_learn_auto_surface.done"
fi
```

**Orchestrator hook:** khi step này echo `→ Invoking /vg:learn --auto-surface`, orchestrator MUST call the slash command inline so user can make y/n/e/s decisions. Non-interactive fallback: Tier B candidates stay in CANDIDATES.md for next phase's accept surface.

**v2.6 Phase C — conflict pair handler:** trong cùng prompt loop, nếu user chọn `y` cho pair (id_a vs id_b, winner=L-WIN), orchestrator MUST call:

```bash
source .claude/commands/vg/_shared/lib/override-debt.sh
override_auto_resolve_clean_run --target rule-retire <LOSER_ID> "winner=<WINNER_ID> conflict-resolved-at-accept"
```

Loser is whichever id ≠ winner; if winner=null (tie) and user picks `y`, prompt for a manual winner first. Mirrors override-debt auto-resolve pattern (single helper, two consumers).
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

## B.1 CRUD Surfaces (CRUD-SURFACES.md)

| Resource | Operations | Platform overlays | UAT Result | Note |
|----------|------------|-------------------|------------|------|
| Campaign | list,create,update,delete | web,backend | PASS / FAIL / SKIP | verify heading/filter/table/form/delete/security contract |
| ... | ... | ... | ... | ... |

Totals: {passed}P / {failed}F / {skipped}S

## B.2 UNREACHABLE Triage (from UNREACHABLE-TRIAGE.md)

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
# v2.7 Phase E — schema validation post-write (BLOCK on UAT.md frontmatter drift).
# Validator resolves both canonical UAT.md and legacy ${phase}-UAT.md forms.
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact uat \
  > "${PHASE_DIR}/.tmp/artifact-schema-uat.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ UAT.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-uat.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-uat.json"
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "accept" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/accept.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept accept 2>/dev/null || true
# v1.15.2 — fulfill runtime_contract markers declared in frontmatter
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "1_artifact_precheck" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_artifact_precheck.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 1_artifact_precheck 2>/dev/null || true
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2_marker_precheck" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_marker_precheck.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 2_marker_precheck 2>/dev/null || true
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "3_sandbox_verdict_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_sandbox_verdict_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 3_sandbox_verdict_gate 2>/dev/null || true

# (OHOK-3 2026-04-22) Legacy `vg_run_complete` bash helper call removed —
# canonical `python vg-orchestrator run-complete` runs at step 7 below.
# One path only; no dual lifecycle.
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

# Keep: SPECS, CONTEXT, PLAN*, API-CONTRACTS, TEST-GOALS, CRUD-SURFACES, SUMMARY*,
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

**Bootstrap rule outcome attribution (Gap 3 fix):**

For each bootstrap rule that fired during this phase, emit a
`bootstrap.outcome_recorded` event so `/vg:bootstrap --efficacy` can update
`hits` + `hit_outcomes` in ACCEPTED.md. Without this, rules accumulate
`hits=0` forever even after firing — we can't prove a promoted rule is
actually affecting behavior.

```bash
# Get phase verdict (final state after UAT quorum gate)
PHASE_VERDICT="success"
if grep -qE '^\*\*Verdict:\*\*\s*(DEFER|REJECTED|FAILED)' "${PHASE_DIR}"/*UAT.md 2>/dev/null; then
  PHASE_VERDICT="fail"
fi

# Query events.db for bootstrap.rule_fired events in this phase
if [ -f ".vg/events.db" ] && command -v sqlite3 >/dev/null 2>&1; then
  FIRED_RULES=$(sqlite3 .vg/events.db \
    "SELECT DISTINCT json_extract(payload, '\$.rule_id')
     FROM events
     WHERE event_type='bootstrap.rule_fired'
       AND json_extract(payload, '\$.phase')='${PHASE_NUMBER}'
       AND json_extract(payload, '\$.rule_id') IS NOT NULL;" 2>/dev/null)

  for RID in $FIRED_RULES; do
    [ -z "$RID" ] && continue
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "bootstrap.outcome_recorded" \
      --payload "{\"rule_id\":\"${RID}\",\"phase\":\"${PHASE_NUMBER}\",\"outcome\":\"${PHASE_VERDICT}\"}" \
      >/dev/null 2>&1 || true
  done

  # Auto-update ACCEPTED.md efficacy counters
  "${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-hygiene.py efficacy --apply \
    2>&1 | tail -5 || echo "(efficacy update returned non-zero, non-blocking)"
fi
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
Artifacts preserved: SPECS, CONTEXT, PLAN, API-CONTRACTS, TEST-GOALS, CRUD-SURFACES, SUMMARY,
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

```bash
# v2.2 — terminal emit + run-complete for /vg:accept
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_post_accept_actions" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_post_accept_actions.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 7_post_accept_actions 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ accept run-complete BLOCK — review orchestrator output + fix" >&2
  exit $RUN_RC
fi
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
