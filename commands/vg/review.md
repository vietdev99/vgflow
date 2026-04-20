---
name: vg:review
description: Post-build review — code scan + browser discovery + fix loop + goal comparison → RUNTIME-MAP
argument-hint: "<phase> [--skip-scan] [--skip-discovery] [--fix-only] [--skip-crossai] [--evaluate-only] [--retry-failed] [--full-scan]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - AskUserQuestion
  - BashOutput
runtime_contract:
  # Review MUST produce RUNTIME-MAP (ground truth of discovered UI) + coverage
  # matrix. If review "ran" without these, discovery was hallucinated.
  must_write:
    - "${PHASE_DIR}/RUNTIME-MAP.json"
    - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
  must_touch_markers:
    - "0_parse_and_validate"
    - "0b_goal_coverage_gate"
    - "complete"
  must_emit_telemetry:
    - event_type: "review.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--override-reason"
    - "--skip-scan"
    - "--skip-discovery"
    - "--fix-only"
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate in this command.**

Why: those tools persist items in Claude Code's status tail across sessions. If a long step (Haiku scanner, Bash, Task subagent) interrupts before items get marked completed, they hang forever in the UI ("Phase 2b-1: Navigator", "Start pnpm dev + wait health" stuck for runs after).

**Use these instead:**
1. **Markdown headers in YOUR text output** between tool calls — e.g., `## ━━━ Phase 2b-1: Navigator ━━━` written in plain text. Appears in message stream, does NOT persist after session ends.
2. **`run_in_background: true` for any Bash > 30s** (dev server boot, health wait, parallel scanner spawn). Then poll with `BashOutput` so user sees stdout live instead of waiting blind.
3. **For Task subagents** that take > 2 min: write a 1-line status in your text output BEFORE spawning ("Spawning Haiku scanner for /users + /settings..."), then a 1-line summary AFTER it returns ("Scanner found 12 elements, 0 errors"). User sees both in the message stream.
4. **Bash echo narration** (`narrate_phase`, `session_start` banner) lands in tool result block — useful for audit log but NOT visible during long runs. Don't rely on it as primary progress signal.
5. **Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `BLOCK (chặn)`, `Foundation (nền tảng) drift detected (phát hiện lệch hướng)`, `legacy-v1 (định dạng cũ v1)`, `UNREACHABLE (không tiếp cận được)`. Không áp dụng: file path, code identifier (`D-XX`, `git`, `pnpm`), config tag values, lần lặp lại trong cùng message.

This is a HARD rule — TodoWrite is the wrong abstraction for a 30-min orchestrator with parallel subagents.
</NARRATION_POLICY>

<rules>
1. **Phase profile drives prerequisites (P5, v1.9.2)** — `detect_phase_profile` chooses WHICH artifacts are required:
   - `feature` (default) → SPECS + CONTEXT + PLAN + API-CONTRACTS + TEST-GOALS + SUMMARY
   - `infra` → SPECS + PLAN + SUMMARY (no TEST-GOALS, no API-CONTRACTS — goals from SPECS success_criteria)
   - `hotfix` / `bugfix` → SPECS + PLAN + SUMMARY (reuse parent goals or issue ref)
   - `migration` → SPECS + PLAN + SUMMARY + ROLLBACK
   - `docs` → SPECS only
   Missing required artifact → BLOCK via `block_resolve` (L2 architect proposal), NOT anti-pattern "list 3 options".
2. **Review mode branches on profile** — `feature=full` (browser + surfaces) | `infra=infra-smoke` (parse + run success_criteria bash) | `hotfix=delta` | `bugfix=regression` | `migration=schema-verify` | `docs=link-check`.
3. **Discovery-first** — AI explores the running app organically. No hardcoded checklists. No pre-scripted paths.
4. **Bấm → Nhìn → List → Đánh giá** — at every view: snapshot, evaluate data + actions, click each, observe result.
5. **Fix in review, verify in test** — review handles discovery + fix. Test handles clean goal verification only.
6. **RUNTIME-MAP is ground truth** — produced from actual browser interaction, not code guessing.
7. **Flexible format** — AI chooses best representation per page (tree, list, flow). No mandated table structure.
8. **Exploration limits (hard-enforced, v1.14.4+)** — max 50 actions/view, 200 total, 30 min wall time. Counted by `phase2_exploration_limits` step after discovery. Threshold breach → WARN + log to PIPELINE-STATE.json metrics (not block; discovery already done, but signals noisy RUNTIME-MAP). Thresholds overridable via `config.review.max_actions_per_view|max_actions_total|max_wall_minutes`.
9. **Zero hardcode** — no endpoint, role, page name, or project-specific value in this workflow. All values from config or runtime observation.
10. **Profile enforcement (UNIVERSAL)** — every `<step>` MUST, as FINAL action:
    `touch "${PHASE_DIR}/.step-markers/{STEP_NAME}.done"`.
    `create_task_tracker` preflight runs filter-steps.py to count expected steps for `$PROFILE`.
    Browser-based steps (phase 2 discovery) carry `profile="web-fullstack,web-frontend-only"` — skipped for backend-only/cli/library.
11. **Resume model (v1.14.4+)** — no mid-phase-2 resume. Step-level idempotency via `.step-markers/*.done` + per-view atomic `scan-*.json` is sufficient. If discovery dies mid-run, re-run `/vg:review {phase}` from scratch OR `/vg:review {phase} --retry-failed` (requires RUNTIME-MAP already written).
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

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `.claude/commands/vg/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

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

<step name="00_gate_integrity_precheck">
**T8 gate (cổng) integrity precheck — blocks review if /vg:update left unresolved gate conflicts (xung đột).**

If `${PLANNING_DIR}/vgflow-patches/gate-conflicts.md` exists, a prior `/vg:update` detected that the 3-way merge (gộp) altered one or more HARD gate blocks. BLOCK (chặn) until resolved via `/vg:reapply-patches --verify-gates`.

```bash
if [ -f "${PLANNING_DIR}/vgflow-patches/gate-conflicts.md" ]; then
  echo "⛔ Gate integrity conflicts unresolved — run /vg:reapply-patches --verify-gates first."
  exit 1
fi
```
</step>

<step name="00_session_lifecycle">
**Session lifecycle (tightened 2026-04-17) — clean tail UI across runs.**

Follow `.claude/commands/vg/_shared/session-lifecycle.md` helper.

```bash
PHASE_NUMBER=$(echo "$ARGUMENTS" | awk '{print $1}')
# v1.9.2.2 — handle zero-padding (`7.12` → `07.12-*`) via shared resolver
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-resolver.sh" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR_CANDIDATE=$(resolve_phase_dir "$PHASE_NUMBER" 2>/dev/null || echo "")
else
  PHASE_DIR_CANDIDATE=$(ls -d ${PLANNING_DIR}/phases/${PHASE_NUMBER}* 2>/dev/null | head -1)
fi

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
- `--skip-scan` — skip Phase 1 (code scan), go directly to browser discovery
- `--skip-discovery` — skip Phase 2 (browser discovery), use existing RUNTIME-MAP for Phase 4
- `--fix-only` — skip to Phase 3 (requires RUNTIME-MAP with errors)
- `--skip-crossai` — skip CrossAI review at end
- `--evaluate-only` — skip Phase 1 + 2 (discovery already done by Codex/Gemini), read existing scan JSONs from ${PHASE_DIR}, go directly to Phase 2b-3 (collect + merge) → Phase 3 (fix) → Phase 4 (goal comparison). Requires: nav-discovery.json + scan-*.json already exist.
- `--retry-failed` — skip Phase 1 + Phase 2 navigator, re-scan ONLY views mapped to failed/blocked goals in GOAL-COVERAGE-MATRIX.md. Requires: GOAL-COVERAGE-MATRIX.md + RUNTIME-MAP.json already exist. Use when: review already ran but goals < 100%, code was fixed, need targeted re-scan without full re-discovery.
- `--full-scan` — disable sidebar suppression. Haiku agents see full page (sidebar/header/footer) in every snapshot. Use when: app has non-standard layout, geometry detection fails, or debugging suppression issues.
- `--with-probes` — enable mutation probe variations (edit/boundary/repeat) in step 2b-3 step 9. Adds 1 Haiku per mutation goal. Default OFF — let /vg:test handle variations via Playwright codegen (deterministic, cheaper).

**Phase profile detection (P5, v1.9.2) — FIRST ACTION before any blanket check:**

```bash
# Source phase-profile.sh — pure function, no side effects
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true

if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  export PHASE_PROFILE
  REVIEW_MODE=$(phase_profile_review_mode "$PHASE_PROFILE")
  REQUIRED_ARTIFACTS=$(phase_profile_required_artifacts "$PHASE_PROFILE")
  SKIP_ARTIFACTS=$(phase_profile_skip_artifacts "$PHASE_PROFILE")
  GOAL_COVERAGE_SRC=$(phase_profile_goal_coverage_source "$PHASE_PROFILE")
  export REVIEW_MODE REQUIRED_ARTIFACTS SKIP_ARTIFACTS GOAL_COVERAGE_SRC

  # Narrate detected profile (Vietnamese) — stderr so user sees reasoning.
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"
else
  # Graceful fallback for legacy workflows where helper not yet installed
  PHASE_PROFILE="feature"
  REVIEW_MODE="full"
  REQUIRED_ARTIFACTS="SPECS.md CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md SUMMARY.md"
  SKIP_ARTIFACTS=""
  GOAL_COVERAGE_SRC="TEST-GOALS"
  echo "⚠ phase-profile.sh missing — defaulting to profile=feature" >&2
fi
```

**Profile-aware prerequisite gate (replaces hardcoded SUMMARY+API-CONTRACTS check):**

```bash
MISSING=""
for artifact in $REQUIRED_ARTIFACTS; do
  # SUMMARY.md check is glob-aware — SUMMARY*.md counts
  if [ "$artifact" = "SUMMARY.md" ]; then
    ls "${PHASE_DIR}"/SUMMARY*.md >/dev/null 2>&1 || MISSING="${MISSING} ${artifact}"
  else
    [ -f "${PHASE_DIR}/${artifact}" ] || MISSING="${MISSING} ${artifact}"
  fi
done
MISSING=$(echo "$MISSING" | xargs)

if [ -n "$MISSING" ]; then
  echo "⛔ Review prerequisites missing for profile='${PHASE_PROFILE}': ${MISSING}" >&2

  # v1.9.1 R2+R4 + v1.9.2 P4: block-resolver — spawn architect proposal
  # instead of anti-pattern "list 3 options, stop, wait".
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.0-prerequisites"
    BR_GATE_CONTEXT="Review prerequisites missing for profile='${PHASE_PROFILE}'. Required: ${REQUIRED_ARTIFACTS}. Missing: ${MISSING}. Profile detected from SPECS.md (parent_phase/issue_id/success_criteria bash commands/migration keywords)."
    BR_EVIDENCE=$(printf '{"phase_profile":"%s","required":"%s","missing":"%s","skip":"%s"}' \
                  "$PHASE_PROFILE" "$REQUIRED_ARTIFACTS" "$MISSING" "$SKIP_ARTIFACTS")
    # L1 fix candidates — try to generate missing artifact inline.
    # Only safe auto-fixes (SUMMARY backfill from build-state, never TEST-GOALS which needs decisions).
    BR_CANDIDATES='[
      {"id":"summary-backfill","cmd":"[ -f \"'"$PHASE_DIR"'/build-state.log\" ] && echo \"SUMMARY could be backfilled from build-state.log — user must review\" && exit 1","confidence":0.4,"rationale":"SUMMARY missing but build-state.log exists → narrate user can backfill, but not auto-generate without human eye"},
      {"id":"profile-retry-detect","cmd":"source \"'"$REPO_ROOT"'/.claude/commands/vg/_shared/lib/phase-profile.sh\"; P=$(detect_phase_profile \"'"$PHASE_DIR"'\"); test \"$P\" != \"'"$PHASE_PROFILE"'\" && echo \"profile changed to $P, re-check needed\" || exit 1","confidence":0.3,"rationale":"Re-detect in case SPECS was updated between runs"}
    ]'
    BR_RESULT=$(block_resolve "review-prereq-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
    BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
    if [ "$BR_LEVEL" = "L1" ]; then
      echo "✓ Block resolver L1 self-resolved — prerequisites now satisfied, re-check below" >&2
      # Re-check MISSING after L1 — fall through if still missing
      MISSING=""
      for artifact in $REQUIRED_ARTIFACTS; do
        if [ "$artifact" = "SUMMARY.md" ]; then
          ls "${PHASE_DIR}"/SUMMARY*.md >/dev/null 2>&1 || MISSING="${MISSING} ${artifact}"
        else
          [ -f "${PHASE_DIR}/${artifact}" ] || MISSING="${MISSING} ${artifact}"
        fi
      done
      MISSING=$(echo "$MISSING" | xargs)
      [ -z "$MISSING" ] || {
        echo "⚠ L1 did not fully resolve — proceeding to L2 architect" >&2
      }
    fi
    if [ -n "$MISSING" ] && [ "$BR_LEVEL" = "L2" ]; then
      block_resolve_l2_handoff "review-prereq-missing" "$BR_RESULT" "$PHASE_DIR"
      exit 2
    elif [ -n "$MISSING" ]; then
      # L4 — genuinely stuck (resolver disabled or architect unavailable)
      echo "Fix paths by profile:" >&2
      echo "  feature   → /vg:blueprint ${PHASE_NUMBER} (generates PLAN + API-CONTRACTS + TEST-GOALS)" >&2
      echo "  infra     → add '## Success criteria' bash checklist to SPECS, commit PLAN + SUMMARY" >&2
      echo "  hotfix    → ensure SPECS has 'Parent phase:' field + PLAN + SUMMARY" >&2
      echo "  bugfix    → add 'issue_id:' or 'bug_ref:' to SPECS + PLAN + SUMMARY" >&2
      echo "  migration → add ROLLBACK.md with down-migration steps" >&2
      echo "  docs      → only SPECS.md required" >&2
      exit 1
    fi
  else
    # Resolver unavailable → classic hard block (still better than 3-option anti-pattern)
    echo "Required for profile='${PHASE_PROFILE}': ${REQUIRED_ARTIFACTS}" >&2
    echo "Run /vg:blueprint or equivalent to produce missing artifacts, then retry." >&2
    exit 1
  fi
fi
```

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

<step name="0b_goal_coverage_gate">
**MANDATORY GATE — every automated goal must have TS-XX binding in at least one test file.**

Prevents Phase 10 scenario: goals declared but tests never reference them, review marks "NOT_SCANNED" without root cause visible. Build post-mortem already runs this advisory; review enforces.

```bash
echo ""
echo "━━━ Goal coverage gate ━━━"
${PYTHON_BIN} .claude/scripts/verify-goal-coverage-phase.py \
  --phase-dir "${PHASE_DIR}" \
  --repo-root "${REPO_ROOT}"
GOAL_RC=$?

if [ "$GOAL_RC" -eq 2 ]; then
  echo ""
  echo "⛔ Review BLOCKED by goal coverage gate."
  echo "   Every automated goal in TEST-GOALS.md must have a test case with matching TS-XX marker."
  echo "   Either: add test referencing TS-XX, OR mark goal verification: deferred|manual."
  echo ""
  echo "Override (NOT recommended, logs to OVERRIDE-DEBT register):"
  echo "  /vg:review ${PHASE_NUMBER} --skip-goal-coverage"
  if [[ ! "${ARGUMENTS}" =~ --skip-goal-coverage ]]; then
    exit 1
  fi
  # Override path: log as debt
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "review-goal-coverage" "${PHASE_NUMBER}" "unbound automated goals" "${PHASE_DIR}"
  fi
fi

touch "${PHASE_DIR}/.step-markers/0b_goal_coverage_gate.done" 2>/dev/null || true
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

<step name="phase_profile_branch">
## Phase profile branch (P5, v1.9.2)

**If `REVIEW_MODE` ≠ `full`, short-circuit before code scan + browser discovery.**

Each non-full review mode has a dedicated handler. After handler completes,
jump straight to `write_goal_coverage_matrix` (step 4d equivalent) and exit.
The `phase_profile_branch` step is a router — see dedicated `phaseP_*` steps below.

```bash
case "$REVIEW_MODE" in
  full)
    # Classic path — Phase 1 code scan → Phase 2 browser → Phase 3 fix → Phase 4 goal compare
    echo "▸ Review mode: full (feature profile) — running classic discovery pipeline"
    ;;
  infra-smoke)
    echo "▸ Review mode: infra-smoke (${PHASE_PROFILE} profile) — parsing SPECS success_criteria"
    # Handled by `phaseP_infra_smoke` below. Jumps to goal-coverage-matrix write + exit.
    ;;
  delta)
    echo "▸ Review mode: delta (hotfix profile) — focus on delta + parent goals re-verify"
    # Handled by `phaseP_delta` below.
    ;;
  regression)
    echo "▸ Review mode: regression (bugfix profile) — regression sweep around issue"
    # Handled by `phaseP_regression` below.
    ;;
  schema-verify)
    echo "▸ Review mode: schema-verify (migration profile) — schema round-trip check"
    # Handled by `phaseP_schema_verify` below.
    ;;
  link-check)
    echo "▸ Review mode: link-check (docs profile) — markdown link validation"
    # Handled by `phaseP_link_check` below.
    ;;
  *)
    echo "⚠ Unknown REVIEW_MODE='${REVIEW_MODE}' — falling back to full pipeline" >&2
    REVIEW_MODE="full"
    ;;
esac
```

**Dispatcher rule:** Orchestrator runs EXACTLY ONE of: `phaseP_infra_smoke` | `phaseP_delta` | `phaseP_regression` | `phaseP_schema_verify` | `phaseP_link_check` | classic `phase1_code_scan → phase4_goal_comparison`. Infra-smoke etc. write `GOAL-COVERAGE-MATRIX.md` directly (implicit goals from SPECS), skip browser + RUNTIME-MAP entirely.
</step>

<step name="phaseP_infra_smoke" profile="web-fullstack,web-backend-only,cli-tool,library">
## Review mode: infra-smoke (P5, v1.9.2)

**Runs when `REVIEW_MODE=infra-smoke` (infra profile).**

Logic: parse SPECS `## Success criteria` checklist → run each bash command on target env → map to implicit goals `S-01..S-NN` → gate on all READY.

```bash
if [ "$REVIEW_MODE" != "infra-smoke" ]; then
  echo "↷ Skipping phaseP_infra_smoke (REVIEW_MODE=$REVIEW_MODE)"
else
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true

  # 1. Parse SPECS success_criteria
  SMOKE_JSON=$(parse_success_criteria "$PHASE_DIR")
  SMOKE_COUNT=$(${PYTHON_BIN} -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$SMOKE_JSON" 2>/dev/null || echo 0)

  if [ "$SMOKE_COUNT" -eq 0 ]; then
    echo "⛔ SPECS has no '## Success criteria' checklist bullets — infra-smoke needs implicit goals." >&2
    echo "   Fix: add markdown checklist ('- [ ] `cmd` → expected') to SPECS.md" >&2
    exit 1
  fi

  echo "▸ Infra-smoke: phát hiện ${SMOKE_COUNT} implicit goals từ success_criteria"
  echo "$SMOKE_JSON" > "${PHASE_DIR}/.success-criteria.json"

  # 2. Determine run_prefix from env (--sandbox flag or config.step_env.verify)
  RUN_PREFIX=""
  ENV_NAME="${VG_ENV:-}"
  if [ -z "$ENV_NAME" ]; then
    if [[ "$ARGUMENTS" =~ --sandbox ]]; then ENV_NAME="sandbox"
    elif [[ "$ARGUMENTS" =~ --local ]]; then ENV_NAME="local"
    else ENV_NAME="${CONFIG_STEP_ENV_VERIFY:-local}"
    fi
  fi
  # NOTE: commands in SPECS typically already include `ssh vollx`; don't double-prefix
  # when command already has the run_prefix. phase-profile keeps this simple — run as-is.

  # 3. Run each bullet, record status
  RESULTS_JSON="${PHASE_DIR}/.infra-smoke-results.json"
  ${PYTHON_BIN} - "$SMOKE_JSON" "$RESULTS_JSON" "$ENV_NAME" <<'PY'
import json, sys, subprocess, shlex, time
smoke = json.loads(sys.argv[1])
out_path = sys.argv[2]
env_name = sys.argv[3]
results = []
for entry in smoke:
    sid = entry['id']
    cmd = entry.get('cmd','').strip()
    expected = entry.get('expected','').strip()
    raw = entry.get('raw','')
    if not cmd:
        results.append({"id":sid,"status":"UNREACHABLE","reason":"no bash command in bullet","raw":raw})
        continue
    if cmd.startswith('/vg:') or cmd.startswith('/gsd:'):
        # Slash commands — not directly runnable here. Mark DEFERRED.
        results.append({"id":sid,"status":"DEFERRED","reason":f"slash command requires orchestrator: {cmd}","raw":raw})
        continue
    try:
        t0 = time.time()
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        dur = round(time.time() - t0, 2)
        ok = p.returncode == 0
        if ok and expected:
            # Expected substring must appear in combined output
            combined = (p.stdout or '') + (p.stderr or '')
            ok = expected.split()[0] in combined or expected in combined
        status = "READY" if ok else "BLOCKED"
        tail = ((p.stdout or '')[-300:] + (p.stderr or '')[-200:]).replace('\n',' | ')
        results.append({"id":sid,"status":status,"exit":p.returncode,"dur":dur,"expected":expected,"evidence":tail[:600],"raw":raw})
    except subprocess.TimeoutExpired:
        results.append({"id":sid,"status":"BLOCKED","reason":"timeout 60s","raw":raw})
    except Exception as e:
        results.append({"id":sid,"status":"FAILED","reason":str(e),"raw":raw})
with open(out_path,'w',encoding='utf-8') as f:
    json.dump({"env":env_name,"results":results,"generated_at":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}, f, ensure_ascii=False, indent=2)
PY

  # 4. Display human-readable summary
  ${PYTHON_BIN} - "$RESULTS_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
r = d['results']
ready = sum(1 for x in r if x['status']=='READY')
blocked = sum(1 for x in r if x['status']=='BLOCKED')
failed = sum(1 for x in r if x['status']=='FAILED')
deferred = sum(1 for x in r if x['status']=='DEFERRED')
unreach = sum(1 for x in r if x['status']=='UNREACHABLE')
print(f"\n┌─ Infra-smoke results (env={d['env']}) ─────────────────")
for x in r:
    icon = {'READY':'✓','BLOCKED':'⛔','FAILED':'✗','DEFERRED':'⟳','UNREACHABLE':'⚠'}.get(x['status'],'?')
    print(f"│ {icon} {x['id']} [{x['status']}] {x.get('raw','')[:70]}")
    if x['status'] in ('BLOCKED','FAILED'):
        print(f"│   └─ {x.get('reason') or x.get('evidence','')[:160]}")
print(f"├─ Summary: READY={ready} BLOCKED={blocked} FAILED={failed} DEFERRED={deferred} UNREACHABLE={unreach} (total={len(r)})")
print("└──────────────────────────────────────────────────────────")
PY

  # 5. Write GOAL-COVERAGE-MATRIX.md with implicit goals
  ${PYTHON_BIN} - "$RESULTS_JSON" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PHASE_PROFILE" <<'PY'
import json, sys
from datetime import datetime
results = json.load(open(sys.argv[1], encoding='utf-8'))['results']
out_path = sys.argv[2]
phase = sys.argv[3]
profile = sys.argv[4]
lines = [
    f"# Goal Coverage Matrix — Phase {phase}",
    "",
    f"**Profile:** {profile}  ",
    f"**Source:** SPECS.success_criteria (implicit goals)  ",
    f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    f"**Review mode:** infra-smoke",
    "",
    "## Implicit Goals (from SPECS `## Success criteria`)",
    "",
    "| Goal | Status | Command | Evidence |",
    "|------|--------|---------|----------|",
]
for r in results:
    raw = r.get('raw','').replace('|',r'\|')[:120]
    ev = (r.get('evidence') or r.get('reason') or '').replace('|',r'\|')[:120]
    lines.append(f"| {r['id']} | {r['status']} | {raw} | {ev} |")

ready = sum(1 for r in results if r['status']=='READY')
total = len(results)
pct = round(100*ready/total, 1) if total else 0
lines += ["", f"## Gate", "", f"**Pass rate:** {ready}/{total} ({pct}%) READY  ",
          f"**Verdict:** {'PASS' if ready == total else 'BLOCK'}", ""]
open(out_path,'w',encoding='utf-8').write('\n'.join(lines) + '\n')
print(f"✓ GOAL-COVERAGE-MATRIX.md written with {total} implicit goals ({ready} READY)")
PY

  # 6. Gate check + block_resolve fallback
  READY_COUNT=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(sum(1 for r in d['results'] if r['status']=='READY'))")
  TOTAL=$(${PYTHON_BIN} -c "import json; d=json.load(open('$RESULTS_JSON')); print(len(d['results']))")
  if [ "$READY_COUNT" -ne "$TOTAL" ]; then
    echo "⛔ Infra-smoke gate: ${READY_COUNT}/${TOTAL} goals READY — phase NOT yet provisioned."

    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.infra-smoke"
      BR_GATE_CONTEXT="Infra-smoke review: ${TOTAL} SPECS success_criteria checked, only ${READY_COUNT} READY. Remaining BLOCKED/FAILED/DEFERRED imply provisioning incomplete on env='${ENV_NAME}'."
      BR_EVIDENCE=$(cat "$RESULTS_JSON")
      BR_CANDIDATES='[{"id":"re-run-ansible","cmd":"echo would re-run ansible-playbook (user must chạy explicitly)","confidence":0.3,"rationale":"re-run provisioning may fix BLOCKED infra"}]'
      BR_RESULT=$(block_resolve "infra-smoke-not-ready" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      [ "$BR_LEVEL" = "L2" ] && { block_resolve_l2_handoff "infra-smoke-not-ready" "$BR_RESULT" "$PHASE_DIR"; exit 2; }
    fi
    exit 1
  fi

  echo "✓ Infra-smoke PASS (${READY_COUNT}/${TOTAL}) — phase provisioned as specified."
  touch "${PHASE_DIR}/.step-markers/phaseP_infra_smoke.done"
  # Exit review early — subsequent steps (browser, goal comparison) N/A for infra profile.
  exit 0
fi
```
</step>

<step name="phaseP_delta">
## Review mode: delta (P5, v1.9.2)

**Runs when `REVIEW_MODE=delta` (hotfix profile).**

Logic: hotfix patches a parent phase. Review focuses on:
- (a) parent phase's failed/blocked goals — re-verify they now pass
- (b) delta changes — small surface, review only touched files + sibling regression

```bash
if [ "$REVIEW_MODE" != "delta" ]; then
  echo "↷ Skipping phaseP_delta (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Find parent phase dir from SPECS
  PARENT_REF=$(grep -E '^\*\*Parent phase:\*\*|^parent_phase:' "$PHASE_DIR/SPECS.md" 2>/dev/null | \
               sed -E 's/.*(Parent phase:\*\*|parent_phase:)\s*//' | awk '{print $1}' | head -1)
  if [ -z "$PARENT_REF" ]; then
    echo "⛔ Hotfix profile but no parent_phase in SPECS.md — cannot derive delta context" >&2
    exit 1
  fi
  PARENT_DIR=$(ls -d "${PHASES_DIR}/${PARENT_REF}"* 2>/dev/null | head -1)
  echo "▸ Delta review: parent=${PARENT_REF} → ${PARENT_DIR}"

  # 2. If parent has GOAL-COVERAGE-MATRIX, extract failed/blocked goals
  PARENT_MATRIX="${PARENT_DIR}/GOAL-COVERAGE-MATRIX.md"
  if [ -f "$PARENT_MATRIX" ]; then
    FAILED_GOALS=$(grep -E '\| (BLOCKED|FAILED|INFRA_PENDING|UNREACHABLE) \|' "$PARENT_MATRIX" | \
                   grep -oE 'G-[0-9]+|S-[0-9]+' | sort -u | head -100)
    echo "▸ Parent failed goals: $(echo $FAILED_GOALS | tr '\n' ' ')"
  else
    echo "⚠ Parent has no GOAL-COVERAGE-MATRIX — delta review will focus on delta changes only"
  fi

  # 3. Write a compact GOAL-COVERAGE-MATRIX for hotfix showing:
  #    - Parent failed goals re-checked status (best-effort — requires re-run of test)
  #    - Delta change summary from git
  DELTA_FILES=$(git diff --name-only HEAD~10 HEAD -- apps/ infra/ packages/ 2>/dev/null | head -20 || echo "")
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PARENT_REF" "$DELTA_FILES" <<'PY'
import sys
from datetime import datetime
out_path = sys.argv[1]
phase = sys.argv[2]
parent = sys.argv[3]
delta_files = sys.argv[4].splitlines() if sys.argv[4] else []
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (hotfix delta)",
    "",
    f"**Profile:** hotfix  ",
    f"**Parent phase:** {parent}  ",
    f"**Source:** parent_phase.TEST-GOALS (regression re-verify) + delta changes  ",
    f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    "",
    "## Delta changes",
    "",
]
if delta_files:
    for f in delta_files:
        lines.append(f"- `{f}`")
else:
    lines.append("_no delta files detected_")
lines += ["", "## Regression scope", "",
          f"Re-verify parent phase ({parent}) failed/blocked goals in /vg:test step.",
          "Delta review passes automatically if no delta is detected as breaking.",
          "",
          "## Gate", "",
          "**Verdict:** PASS (delta review — regression verification deferred to /vg:test)", ""]
open(out_path,'w',encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (hotfix delta)")
PY

  touch "${PHASE_DIR}/.step-markers/phaseP_delta.done"
  exit 0
fi
```
</step>

<step name="phaseP_regression">
## Review mode: regression (P5, v1.9.2 — bugfix profile)

**Runs when `REVIEW_MODE=regression`.**

```bash
if [ "$REVIEW_MODE" != "regression" ]; then
  echo "↷ Skipping phaseP_regression (REVIEW_MODE=$REVIEW_MODE)"
else
  BUG_REF=$(grep -E '^\*\*issue_id\*\*:|^issue_id:|^\*\*bug_ref\*\*:|^bug_ref:|^\*\*Fixes bug\*\*:' "$PHASE_DIR/SPECS.md" 2>/dev/null | sed -E 's/.*://; s/^\s*//' | head -1)
  echo "▸ Regression review (bugfix): issue_ref=${BUG_REF:-<unspecified>}"
  echo "  Deferring actual regression tests to /vg:test (issue-specific suite)."
  # Write stub matrix
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$BUG_REF" <<'PY'
import sys
from datetime import datetime
out, phase, bug = sys.argv[1], sys.argv[2], sys.argv[3]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (bugfix regression)",
    "",
    f"**Profile:** bugfix  ",
    f"**Bug reference:** {bug or '_unspecified_'}  ",
    f"**Source:** SPECS.fixes_bug  ",
    f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "## Regression gate",
    "",
    "Bugfix regression is verified by /vg:test `issue-specific` runner — this review step",
    "passes automatically. Full regression sweep via /vg:regression after accept.",
    "",
    "**Verdict:** PASS (regression handled at /vg:test)",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (bugfix regression stub)")
PY
  touch "${PHASE_DIR}/.step-markers/phaseP_regression.done"
  exit 0
fi
```
</step>

<step name="phaseP_schema_verify">
## Review mode: schema-verify (P5, v1.9.2 — migration profile)

```bash
if [ "$REVIEW_MODE" != "schema-verify" ]; then
  echo "↷ Skipping phaseP_schema_verify (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Schema-verify review (migration): checking ROLLBACK.md + migration files"
  # Minimum verification: ROLLBACK.md present (already checked in prereq),
  # migration files referenced in PLAN exist.
  MISSING_MIG=""
  for f in $(grep -oE '<file-path>[^<]*migrations[^<]*\.sql[^<]*</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
             sed -E 's/<\/?file-path>//g'); do
    [ -f "$f" ] || MISSING_MIG="${MISSING_MIG} $f"
  done
  if [ -n "$MISSING_MIG" ]; then
    echo "⛔ Migration files referenced in PLAN but missing:$MISSING_MIG"
    exit 1
  fi

  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (migration schema-verify)",
    "",
    "**Profile:** migration  ",
    "**Source:** SPECS.migration_plan + ROLLBACK.md  ",
    f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "## Schema verification",
    "",
    "- ROLLBACK.md present",
    "- Migration files referenced in PLAN exist on disk",
    "- Schema round-trip validation deferred to /vg:test schema-roundtrip runner",
    "",
    "**Verdict:** PASS",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (migration schema-verify)")
PY
  touch "${PHASE_DIR}/.step-markers/phaseP_schema_verify.done"
  exit 0
fi
```
</step>

<step name="phaseP_link_check">
## Review mode: link-check (P5, v1.9.2 — docs profile)

```bash
if [ "$REVIEW_MODE" != "link-check" ]; then
  echo "↷ Skipping phaseP_link_check (REVIEW_MODE=$REVIEW_MODE)"
else
  echo "▸ Link-check review (docs): scanning markdown files for broken relative links"
  DOC_FILES=$(grep -oE '<file-path>[^<]+\.md</file-path>' "${PHASE_DIR}/PLAN.md" 2>/dev/null | \
              sed -E 's/<\/?file-path>//g')
  BROKEN=""
  for f in $DOC_FILES; do
    [ -f "$f" ] || continue
    for link in $(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/\]\(//; s/\)$//' | grep -vE '^https?://|^#'); do
      target=$(dirname "$f")/"$link"
      [ -e "$target" ] || BROKEN="${BROKEN}\n$f → $link"
    done
  done
  if [ -n "$BROKEN" ]; then
    echo -e "⚠ Broken relative links:$BROKEN"
  fi
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" <<'PY'
import sys
from datetime import datetime
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (docs link-check)",
    "",
    "**Profile:** docs  ",
    f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "Docs-only phase — link-check performed; content fidelity deferred to /vg:test markdown-lint.",
    "",
    "**Verdict:** PASS",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (docs link-check)")
PY
  touch "${PHASE_DIR}/.step-markers/phaseP_link_check.done"
  exit 0
fi
```
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
  echo "RIPPLE_SKIPPED=true" > "${PHASE_DIR}/uat-ripples.txt"
  echo "RIPPLE_SKIP_REASON=graphify-inactive" >> "${PHASE_DIR}/uat-ripples.txt"
  touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"
  # skip to Phase 2
fi
```

**⛔ BUG #3 fix (2026-04-18): Stale graphify check + auto-rebuild before ripple analysis.**

Without this, ripple analysis runs against stale graph → reports "0 callers affected"
because graph doesn't know about new callers added since last build. Falsely safe verdict.

```bash
if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
  GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
  COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')
  STALE_THRESHOLD="${GRAPHIFY_STALE_WARN:-50}"

  echo "Review Phase 1.5: graphify ${COMMITS_SINCE} commits since last build"

  # Always rebuild before ripple — review is the SAFETY NET, must be accurate
  if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
    vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "review-phase1_5-${PHASE_NUMBER}" || {
      echo "⛔ Review cannot trust ripple analysis with stale graph"
      echo "   Fix manually: ${PYTHON_BIN} -m graphify update ."
    }
  fi
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

# Filter to source files only (exclude ${PLANNING_DIR}/, .claude/, node_modules, etc)
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
    fail)    echo "       ❌ Scan lỗi — xem ${PHASE_DIR}/scan-*.json (per-view atomic artifacts)" ;;
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
4. (v1.14.0+) Infra auto-start — nếu review.try_infra_start=true AND config có infra_start declared → chạy
5. DB seed (if configured): run_on_target "${config.environments[ENV].seed_command}"
   (skip if seed_command not in config — portable)
6. Auth bootstrap (if configured):
   For each role in config.credentials[ENV]:
     Run config.environments[ENV].auth_command with role credentials
     Save response token for API checks below
   (skip if auth_command not in config — MCP login handles auth instead)
```

Read `.claude/commands/vg/_shared/env-commands.md` — deploy(env) + preflight(env).

### 2a-infra: Tự động khởi động hạ tầng (v1.14.0+)

**Triết lý:** Review hiện skip `INFRA_PENDING` goals (ClickHouse/Kafka/Pixel không chạy). Cổng 100% không cho phép skip — review phải tự khởi động hạ tầng để goals verify được.

```bash
# Gate 1: config knob enabled?
TRY_INFRA_START=$(yq '.review.try_infra_start // true' .claude/vg.config.md 2>/dev/null)
if [ "$TRY_INFRA_START" != "true" ]; then
  echo "ℹ review.try_infra_start=false — bỏ qua bước khởi động hạ tầng"
else
  # Gate 2: env có declare infra_start không?
  INFRA_START=$(yq ".environments.${ENV}.infra_start // \"\"" .claude/vg.config.md 2>/dev/null)
  INFRA_STOP=$(yq  ".environments.${ENV}.infra_stop  // \"\"" .claude/vg.config.md 2>/dev/null)
  INFRA_STATUS=$(yq ".environments.${ENV}.infra_status // \"\"" .claude/vg.config.md 2>/dev/null)

  if [ -z "$INFRA_START" ]; then
    echo "ℹ Env '${ENV}' không declare infra_start — bỏ qua (infra không do review quản lý)"
  else
    # Gate 3: hạ tầng đã chạy sẵn chưa? (idempotent check)
    ALREADY_RUNNING=false
    if [ -n "$INFRA_STATUS" ]; then
      if eval "$INFRA_STATUS" 2>/dev/null | grep -qiE "running|up|ok|online"; then
        ALREADY_RUNNING=true
        echo "✓ Hạ tầng đã chạy sẵn (infra_status detect)"
      fi
    fi

    if [ "$ALREADY_RUNNING" = "false" ]; then
      # Gate 4: khởi động hạ tầng + trap EXIT để dọn
      narrate_phase "Phase 2a-infra — Khởi động hạ tầng" "Chạy infra_start + trap cleanup"
      echo "  Command: $INFRA_START"

      # Chạy, capture exit code
      eval "$INFRA_START"
      INFRA_START_RC=$?

      if [ $INFRA_START_RC -ne 0 ]; then
        # Hard block — không skip theo cổng 100%
        echo "⛔ infra_start THẤT BẠI (exit $INFRA_START_RC) — review không tiếp tục."
        echo "   Nguyên nhân khả dĩ: port conflict, resource thiếu, config sai."
        echo "   Debug: chạy '${INFRA_START}' thủ công xem stderr."
        echo "   Override: /vg:review ${PHASE_NUMBER} --legacy-mode (DEPRECATED, expire 2 milestones)"
        exit 1
      fi

      echo "  ✓ infra_start OK — trap infra_stop đã cài"

      # Trap: auto dọn khi review thoát (normal/error/interrupt)
      if [ -n "$INFRA_STOP" ]; then
        trap "echo '  ♻ Dọn hạ tầng (infra_stop)...'; eval \"$INFRA_STOP\" 2>/dev/null || true" EXIT INT TERM
      fi

      # Chờ hạ tầng ready (retry health 30s)
      for i in {1..30}; do
        if eval "$INFRA_STATUS" 2>/dev/null | grep -qiE "running|up|ok|online"; then
          echo "  ✓ Hạ tầng ready sau ${i}s"
          break
        fi
        sleep 1
      done

      # Emit telemetry
      if type -t telemetry_emit >/dev/null 2>&1; then
        telemetry_emit "review_infra_start_success" "{\"env\":\"${ENV}\",\"duration_s\":${i}}"
      fi
    fi
  fi
fi
```

**Tại sao không có AskUserQuestion:**  
Đây là autonomous action — config đã khai `try_infra_start: true` nghĩa là user OK. Nếu user không muốn auto-start → set `false` trong config. Giữa đêm chạy review mà lại hỏi user = anti-pattern.

**Cleanup guarantee:**  
Trap `EXIT INT TERM` bắt mọi đường thoát (normal / error / Ctrl+C). Hạ tầng sẽ stop khi review kết thúc dù success hay fail. Ngoại lệ: SIGKILL (process killed) → trap không chạy → user phải thủ công `infra_stop`.

**Cổng cứng:**  
infra_start fail → BLOCK. Không có "try again later" hay "skip INFRA_PENDING". Đây là điểm khác biệt cốt lõi với v1.13 — không cho phép defer hạ tầng.

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
  `cat ${PLANNING_DIR}/phases/{phase}/deploy-review.json`

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
  │   ⚠ ANTI-PATTERN WARNING (v1.9.1 R2 + v1.9.2 P4):                      │
  │   Do NOT fall back to "list 3 options (A/B/C) and wait".               │
  │   Use `block_resolve` helper — L1 auto-try `--skip`, L2 architect      │
  │   proposal for cross-env retry, L3 AskUserQuestion only if L2 fails.   │
  │                                                                        │
  │   Block-resolver handler:                                              │
  └─────────────────────────────────────────────────────────────────────────┘

```bash
# v1.9.2 P4 — Scenario F resolver (replaces legacy A/B/C prompt)
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
if type -t block_resolve >/dev/null 2>&1; then
  export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.infra-unavailable"
  BR_GATE_CONTEXT="External infra (${UNAVAILABLE_SERVICES:-unknown}) not reachable on env='${ENV}'. ${INFRA_PENDING_GOALS:-?} goals blocked. User must choose: continue local with skip, switch to sandbox, or partial (local + sandbox retry)."
  BR_EVIDENCE=$(printf '{"env":"%s","unavailable":"%s","pending_goals":"%s"}' "$ENV" "${UNAVAILABLE_SERVICES:-unknown}" "${INFRA_PENDING_GOALS:-0}")
  BR_CANDIDATES='[
    {"id":"skip-infra-goals","cmd":"echo \"Setting infra_deps.unmet_behavior=skip for this run\" && export CONFIG_INFRA_DEPS_UNMET_BEHAVIOR=skip","confidence":0.75,"rationale":"Skip infra-dependent goals = valid strategy for code-only review passes"}
  ]'
  BR_RESULT=$(block_resolve "infra-unavailable" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
  BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
  case "$BR_LEVEL" in
    L1) echo "✓ L1 resolved — continuing local review with infra goals skipped" >&2 ;;
    L2) block_resolve_l2_handoff "infra-unavailable" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
    *)  block_resolve_l4_stuck "infra-unavailable" "All candidates failed + no architect proposal"; exit 1 ;;
  esac
fi
```

  **Semantic fallback (if resolver unavailable — raw AskUserQuestion):**
  - If A → set config.infra_deps.unmet_behavior="skip", continue
  - If B → switch ENV=sandbox, re-run deploy + preflight
  - If C → continue local with skip, save INFRA_PENDING goals list for sandbox retry

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

#### 2b-2: Spawn Haiku Scanners (parallel OR sequential per view — v1.9.4 R3.3)

<MANDATORY_GATE>
**You MUST spawn Haiku agents in step 2b-2** (unless spawn_mode=none for cli-tool/library profiles). This is NOT optional.
- Do NOT skip this step because "phase is small" or "I already covered everything in 2b-1"
- Do NOT replace spawning with "I'll click through views myself"
- MINIMUM: spawn at least 1 Haiku agent per view discovered in 2b-1
- The Agent tool with model="haiku" MUST be called. If it's not called, 2b-2 is incomplete.
</MANDATORY_GATE>

<SPAWN_MODE_RESOLUTION>
**v1.9.4 R3.3 — Scanner spawn mode (mobile sequential constraint):**

Mobile apps (iOS simulator, Android emulator, physical device) can typically run only ONE instance at a time. Spawning 5 parallel Haiku agents on a single emulator causes conflicts / crashes / app state corruption. CLI/library projects have no UI to scan at all.

```bash
# Resolve scanner spawn mode BEFORE entering spawn loop
resolve_scanner_spawn_mode() {
  local mode="${CONFIG_REVIEW_SCANNER_SPAWN_MODE:-auto}"
  if [ "$mode" != "auto" ]; then
    echo "$mode"
    return
  fi
  # Auto-derive from config.profile
  case "${CONFIG_PROFILE:-web-fullstack}" in
    mobile-rn|mobile-flutter|mobile-native-ios|mobile-native-android|mobile-hybrid)
      echo "sequential"  # Single emulator/simulator/device
      ;;
    cli-tool|library)
      echo "none"        # No UI to scan
      ;;
    web-fullstack|web-frontend-only|web-backend-only|*)
      echo "parallel"    # Default — multiple browser contexts supported
      ;;
  esac
}

SPAWN_MODE=$(resolve_scanner_spawn_mode)
echo ""
echo "▸ Scanner spawn mode: ${SPAWN_MODE} (profile: ${CONFIG_PROFILE:-web-fullstack})"
case "$SPAWN_MODE" in
  sequential)
    echo "📱 Sequential mode — 1 Haiku agent at a time (mobile/single-window constraint)"
    echo "   Tổng ${TOTAL} view sẽ scan tuần tự; thời gian ~${TOTAL}×5min (1 agent/view)"
    ;;
  parallel)
    echo "🌐 Parallel mode — up to 5 Haiku agents concurrent (Playwright lock caps)"
    echo "   Tổng ${TOTAL} view; thời gian ~${TOTAL}/5 × 5min"
    ;;
  none)
    echo "⏭  Spawn mode=none — skipping Phase 2b-2 entirely (profile has no UI scan)"
    echo "   Backend goals resolved via surface probes in Phase 4a instead."
    ;;
  *)
    echo "⚠ Unknown spawn_mode=${SPAWN_MODE} — falling back to parallel" >&2
    SPAWN_MODE="parallel"
    ;;
esac
```

**Behavior branch by mode:**

- **`parallel`** (web default): All Agent(model="haiku", ...) calls in ONE tool_use block → Claude Code harness runs them concurrently. Playwright lock manager caps effective concurrency at 5 slots.

- **`sequential`** (mobile default): Each Agent(model="haiku", ...) call in SEPARATE messages, awaiting completion before spawning next. Guarantees single emulator/device state. User sees 1/N → 2/N → ... progression serially.

- **`none`** (cli-tool/library): Skip 2b-2 entirely. Jump to 2b-3 collect phase (will merge 0 scans). Phase 4 goal coverage relies 100% on surface probes (api/data/integration/time-driven) from Phase 4a.

**Override via config:** Set `review.scanner_spawn_mode: "sequential"` in vg.config.md to force sequential even for web projects (e.g., if CI has constrained browser resources).
</SPAWN_MODE_RESOLUTION>

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

Then spawn with **structured description** (thay vì freeform).

**⚠ SPAWN_MODE enforcement (v1.9.4 R3.3) — orchestrator branching:**

| SPAWN_MODE  | Tool-use pattern                                           | Use case                               |
|-------------|------------------------------------------------------------|----------------------------------------|
| `none`      | Skip spawn loop entirely, write empty scan-manifest, jump to 2b-3 | cli-tool, library (no UI to scan)      |
| `sequential`| Each Agent() call in **SEPARATE** message, await each complete before next | mobile-* (single emulator/device)      |
| `parallel`  | All Agent() calls in **ONE** tool_use block, harness runs concurrent ≤5 | web-* (default, multi-browser contexts)|

**When SPAWN_MODE=none:** orchestrator writes empty scan-manifest.json then skips to 2b-3:
```bash
${PYTHON_BIN} -c "
import json; from pathlib import Path
Path('${PHASE_DIR}/scans').mkdir(exist_ok=True)
Path('${PHASE_DIR}/scan-manifest.json').write_text(json.dumps({
  'mode': 'skipped_no_ui',
  'profile': '${CONFIG_PROFILE}',
  'scans': []
}, indent=2))"
# → proceed to 2b-3 collect (which handles empty scans gracefully)
```

**When SPAWN_MODE=sequential (mobile):** iterate view_assignments ONE AT A TIME. Each Agent() call in a separate message — DO NOT batch them into one tool_use block. Narrate `[idx/total] spawning <view>@<role>...` before each, `[idx/total] done (<N goals, <M regressions>)` after. User sees serial progression.

**When SPAWN_MODE=parallel (web):** batch ALL Agent() calls in ONE tool_use block so Claude harness dispatches them concurrently (Playwright lock manager caps at 5 slots).

**Common spawn pattern (applies to both sequential and parallel):**

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
- **Concurrency (v1.9.4 R3.3 SPAWN_MODE aware):**
  - `parallel` mode: up to 5 Haiku agents concurrent (Playwright slot cap)
  - `sequential` mode: exactly 1 Haiku agent at a time (mobile safety)
  - `none` mode: no Haiku agents spawned (cli-tool/library)

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
**Atomic artifact per major step — no separate state file (v1.14.4+):**
- Step 2b-1 → writes `${PHASE_DIR}/nav-discovery.json` (atomic)
- Step 2b-2 → writes `${PHASE_DIR}/scan-{view-slug}.json` per Haiku agent (atomic per view)
- Step 2b-3 → writes `${PHASE_DIR}/RUNTIME-MAP.json` + `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`
- Steps 8/9/10 → extend RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md

If session dies mid-2b-2: re-run `/vg:review {phase}` — nav-discovery.json + partial scan-*.json stay, orchestrator redoes only missing views. Per-view scan is cheap (~30s Haiku call), no need for global state file. Step-level idempotency handled by `.step-markers/*.done`.
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

<step name="phase2_exploration_limits" profile="web-fullstack,web-frontend-only">
## Phase 2-limit: EXPLORATION LIMIT CHECK (R8 enforcement — v1.14.4+)

Counts actions + views + wall-time sau Phase 2 để phát hiện runaway discovery (phát hiện quét vô kiểm soát). WARN (cảnh báo) only — không block (không chặn) vì discovery đã xong. Kết quả ghi vào PIPELINE-STATE.json metrics để test/accept biết RUNTIME-MAP có thể noisy (nhiễu).

**Thresholds (ngưỡng):**
- `config.review.max_actions_per_view` — default 50
- `config.review.max_actions_total` — default 200
- `config.review.max_wall_minutes` — default 30

```bash
RUNTIME_MAP="${PHASE_DIR}/RUNTIME-MAP.json"
if [ ! -f "$RUNTIME_MAP" ]; then
  echo "⚠ RUNTIME-MAP.json chưa tồn tại — bỏ qua limit check (Phase 2 có thể skipped hoặc failed)."
  touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"
else
  MAX_VIEW="${CONFIG_REVIEW_MAX_ACTIONS_PER_VIEW:-50}"
  MAX_TOTAL="${CONFIG_REVIEW_MAX_ACTIONS_TOTAL:-200}"
  MAX_WALL="${CONFIG_REVIEW_MAX_WALL_MINUTES:-30}"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$RUNTIME_MAP" "$MAX_VIEW" "$MAX_TOTAL" "$MAX_WALL" "${PHASE_DIR}" <<'PY'
import json, sys, time
from pathlib import Path
from datetime import datetime

rm_path = Path(sys.argv[1])
max_view = int(sys.argv[2])
max_total = int(sys.argv[3])
max_wall_min = int(sys.argv[4])
phase_dir = Path(sys.argv[5])

rm = json.loads(rm_path.read_text(encoding="utf-8"))
views = rm.get("views", {}) or {}
seqs = rm.get("goal_sequences", {}) or {}

per_view_actions = {}
total_actions = 0

# Count goal_sequences steps grouped by start_view
for gid, seq in seqs.items():
    start = seq.get("start_view") or "<unknown>"
    n = len(seq.get("steps", []) or [])
    per_view_actions[start] = per_view_actions.get(start, 0) + n
    total_actions += n

# Add free_exploration actions if tracked per view
for v_url, v in views.items():
    fe = (v.get("free_exploration") or {}).get("actions_count", 0) or 0
    per_view_actions[v_url] = per_view_actions.get(v_url, 0) + fe
    total_actions += fe

# Wall time — use session-start marker mtime as proxy for discovery start
marker = phase_dir / ".step-markers" / "00_session_lifecycle.done"
wall_min = None
if marker.exists():
    wall_min = (time.time() - marker.stat().st_mtime) / 60.0

# Evaluate
warnings = []
for v, n in per_view_actions.items():
    if n > max_view:
        warnings.append({"type": "view_overflow", "view": v, "count": n, "limit": max_view})
if total_actions > max_total:
    warnings.append({"type": "total_overflow", "count": total_actions, "limit": max_total})
if wall_min is not None and wall_min > max_wall_min:
    warnings.append({"type": "wall_overflow", "minutes": round(wall_min, 1), "limit": max_wall_min})

# Report
if warnings:
    print(f"⚠ R8 exploration limits exceeded ({len(warnings)} signal):")
    for w in warnings:
        if w["type"] == "view_overflow":
            print(f"   - view '{w['view']}' → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "total_overflow":
            print(f"   - total → {w['count']} actions vượt limit {w['limit']}")
        elif w["type"] == "wall_overflow":
            print(f"   - wall time (thời gian) → {w['minutes']} min vượt limit {w['limit']}")
    print("")
    print("Khuyến nghị (recommendation):")
    print("  - Review RUNTIME-MAP.json: có action lặp/vô ích không")
    print("  - Giảm views scanned hoặc tắt --full-scan (sidebar suppression giúp giảm action)")
    print("  - Nếu phase lớn thật, tăng config.review.max_actions_total")
else:
    wall_txt = f", {wall_min:.1f} min" if wall_min else ""
    print(f"✓ Exploration within limits: {total_actions} actions, {len(per_view_actions)} views{wall_txt}")

# Log to PIPELINE-STATE.json regardless
state_path = phase_dir / "PIPELINE-STATE.json"
state = {}
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
state.setdefault("metrics", {})["review_exploration"] = {
    "total_actions": total_actions,
    "views_scanned": len(per_view_actions),
    "wall_minutes": round(wall_min, 1) if wall_min is not None else None,
    "thresholds": {"per_view": max_view, "total": max_total, "wall_min": max_wall_min},
    "warnings": warnings,
    "recorded_at": datetime.utcnow().isoformat() + "Z",
}
state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
PY

  touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"
fi
```

**Hành vi downstream:** nếu có warnings, step `crossai_review` cuối pipeline sẽ include "exploration noisy" flag vào context để CrossAI xem xét kỹ goals liên quan views overflow.
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
   - Log current build SHA in PIPELINE-STATE.json `steps.review.last_fix_sha`
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

**Surface classification (v1.9.1 R1 — lazy migration, runs BEFORE browser discover decisions):**

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
# rc=2 → Haiku tie-break (spawn Task per row in .goal-classifier-pending.tsv, then classify_goals_apply)
# rc=3 → AskUserQuestion (surface list from config), then classify_goals_apply
```

Parse `**Surface:** <name>` per goal.

**Surface-aware routing (tightened v1.9.1 R1):**

For each goal:
- `surface == "ui"` / `"ui-mobile"` → proceed with existing browser RUNTIME-MAP lookup below.
- `surface ∈ { api, data, time-driven, integration, custom }` → skip browser discover for this goal; instead run lightweight **surface probe**:
  * `api`        → grep `apps/**/src/**` for route handler matching contract path → READY if present.
  * `data`       → grep migrations + `config.infra_deps` for table/collection → READY if present; INFRA_PENDING if service unavailable.
  * `time-driven`→ grep cron/scheduler registration in `apps/workers/**`/`apps/api/**` → READY if handler wired.
  * `integration`→ check `${PHASE_DIR}/test-runners/fixtures/${gid}.integration.sh` exists AND downstream caller found → READY.

Result feeds GOAL-COVERAGE-MATRIX with `(status, surface, probe_evidence)`.

**Pure-backend fast-path:**
```bash
UI_GOAL_COUNT=$(grep -c '^\*\*Surface:\*\* ui' "${PHASE_DIR}/TEST-GOALS.md" || echo 0)
if [ "$UI_GOAL_COUNT" -eq 0 ]; then
  echo "🧭 Pure-backend phase (không có goal UI) — bỏ qua browser discovery (khám phá trình duyệt), dùng surface probes." >&2
  # Emit empty RUNTIME-MAP if not written yet, skip to 4b
  [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || echo '{"views":{},"goal_sequences":{}}' > "${PHASE_DIR}/RUNTIME-MAP.json"
fi
```

**Mixed-phase surface probe execution (v1.9.2.3 P3):**

For phases có CẢ UI goals (cần browser) VÀ backend goals (api/data/integration/time-driven), browser phase chỉ cover UI goals. Backend goals PHẢI được probe SEPARATELY để avoid rơi vào NOT_SCANNED branch.

```bash
# Run surface probes cho goals có surface ≠ ui
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-probe.sh" 2>/dev/null || true
if type -t run_surface_probe >/dev/null 2>&1; then
  PROBE_RESULTS_JSON="${PHASE_DIR}/.surface-probe-results.json"
  echo '{"probed_at":"'"$(date -u +%FT%TZ)"'","results":{' > "$PROBE_RESULTS_JSON"
  FIRST=true

  # Extract goal_id + surface pairs from TEST-GOALS.md
  ${PYTHON_BIN} -c "
import re
tg = open('${PHASE_DIR}/TEST-GOALS.md', encoding='utf-8').read()
for gid, surface in re.findall(r'^## Goal (G-[\w]+):.*?^\*\*Surface:\*\* (\w[\w-]*)', tg, re.M|re.S):
    print(f'{gid} {surface}')
" | while read -r gid surface; do
    surface="${surface%$'\r'}"
    # Skip UI — browser phase handles them
    [ "$surface" = "ui" ] || [ "$surface" = "ui-mobile" ] && continue

    PROBE=$(run_surface_probe "$gid" "$surface" "$PHASE_DIR" 2>/dev/null)
    STATUS=$(echo "$PROBE" | cut -d'|' -f1)
    EVIDENCE=$(echo "$PROBE" | cut -d'|' -f2- | sed 's/"/\\"/g')

    [ "$FIRST" = "true" ] && FIRST=false || echo "," >> "$PROBE_RESULTS_JSON"
    printf '"%s":{"surface":"%s","status":"%s","evidence":"%s"}' \
           "$gid" "$surface" "$STATUS" "$EVIDENCE" >> "$PROBE_RESULTS_JSON"
  done

  echo '}}' >> "$PROBE_RESULTS_JSON"

  # Summary narration
  PROBED=$(${PYTHON_BIN} -c "
import json
d = json.load(open('$PROBE_RESULTS_JSON'))['results']
from collections import Counter
c = Counter(r['status'] for r in d.values())
print(f'Phase 4a surface probes: {len(d)} backend goals probed → {dict(c)}')")
  echo "▸ $PROBED"
fi
```

**Phase 4b integration:** Khi check goal_sequences cho backend goals (surface ≠ ui), trước khi mark NOT_SCANNED hãy check `.surface-probe-results.json`:
- Nếu probe READY → map → STATUS: READY với evidence từ probe (handler path, migration file, caller reference).
- Nếu probe BLOCKED → map → STATUS: BLOCKED với evidence là probe reason.
- Nếu probe INFRA_PENDING → map → STATUS: INFRA_PENDING.
- Nếu probe SKIPPED (can't parse criteria) → fallthrough to NOT_SCANNED branch → buộc user cải thiện TEST-GOALS hoặc override.

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
    # v1.9.1 R2+R4: block-resolver — try L1 auto-fix (re-scan failed goals) before demanding user override.
    # If L1 fails, L2 architect proposal is presented to user via AskUserQuestion (L3).
    # L4 only when L2 proposal rejected AND no user direction.
    # See _shared/lib/block-resolver.sh
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.4c-pre"
      BR_GATE_CONTEXT="NOT_SCANNED/FAILED goals block review exit. ${INTERMEDIATE} intermediate goals need conclusion (READY/BLOCKED/UNREACHABLE/INFRA_PENDING)."
      BR_EVIDENCE=$(printf '{"not_scanned":%d,"failed":%d,"total_intermediate":%d}' "$NOT_SCANNED_COUNT" "$FAILED_COUNT" "$INTERMEDIATE")
      BR_CANDIDATES='[{"id":"retry-failed-scan","cmd":"echo retry-failed auto-fix would re-trigger scanner for FAILED goals only; skipping in safe mode","confidence":0.5,"rationale":"retry-failed probe may reclassify goals without human override"}]'
      BR_RESULT=$(block_resolve "not-scanned-defer" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LEVEL" = "L1" ]; then
        echo "✓ Block resolver L1 self-resolved — intermediate goals auto-fixed"
      elif [ "$BR_LEVEL" = "L2" ]; then
        block_resolve_l2_handoff "not-scanned-defer" "$BR_RESULT" "$PHASE_DIR"
        echo "  Để proceed sau khi user chấp nhận proposal: re-run /vg:review ${PHASE_NUMBER} --allow-intermediate --reason='<applied proposal>'" >&2
        exit 2
      else
        # L4 truly stuck — print human-direction message
        block_resolve_l4_stuck "not-scanned-defer" "L1 failed + L2 produced no actionable proposal"
        exit 1
      fi
    else
      exit 1
    fi
  else
    # v1.9.0 T1: rationalization guard — NOT_SCANNED defer is a classic rationalization surface.
    RATGUARD_RESULT=$(rationalization_guard_check "not-scanned-defer" \
      "NOT_SCANNED = review didn't replay the goal sequence. Deferring = test codegen has no input. Auto-UNREACHABLE hides coverage debt." \
      "intermediate_goals=${INTERMEDIATE_GOALS} not_scanned=${NOT_SCANNED_COUNT} failed=${FAILED_COUNT}")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "not-scanned-defer" "--allow-intermediate" "$PHASE_NUMBER" "review.4c-pre" "${INTERMEDIATE} intermediate goals"; then
      exit 1
    fi
    # Auto-convert intermediate → UNREACHABLE với audit trail
    for gid in $INTERMEDIATE_GOALS; do
      update_goal_status $gid "UNREACHABLE" --reason "review-skip-${original_status}"
    done
    echo "intermediate-override: ${INTERMEDIATE} goals auto-converted UNREACHABLE ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/build-state.log"
  fi
fi
```

### 4c: Write GOAL-COVERAGE-MATRIX.md (v1.9.2.4 runnable merger)

```bash
# Call matrix-merger.sh helper — reads RUNTIME-MAP + probe-results + TEST-GOALS,
# computes per-goal status with priority precedence (browser > probe > code_exists),
# writes canonical GOAL-COVERAGE-MATRIX.md with summary + by-priority + details + gate.
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/matrix-merger.sh" 2>/dev/null || true
if type -t merge_and_write_matrix >/dev/null 2>&1; then
  MERGE_OUTPUT=$(merge_and_write_matrix "$PHASE_DIR" \
    "${PHASE_DIR}/TEST-GOALS.md" \
    "${PHASE_DIR}/RUNTIME-MAP.json" \
    "${PHASE_DIR}/.surface-probe-results.json" \
    "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>&1)

  # Extract machine-readable counts + verdict
  VERDICT=$(echo "$MERGE_OUTPUT" | grep '^VERDICT=' | cut -d= -f2)
  READY=$(echo "$MERGE_OUTPUT" | grep '^READY=' | cut -d= -f2)
  BLOCKED=$(echo "$MERGE_OUTPUT" | grep '^BLOCKED=' | cut -d= -f2)
  NOT_SCANNED=$(echo "$MERGE_OUTPUT" | grep '^NOT_SCANNED=' | cut -d= -f2)
  INTERMEDIATE=$(echo "$MERGE_OUTPUT" | grep '^INTERMEDIATE=' | cut -d= -f2)
  export VERDICT READY BLOCKED NOT_SCANNED INTERMEDIATE

  echo "✓ GOAL-COVERAGE-MATRIX.md: VERDICT=$VERDICT (ready=$READY blocked=$BLOCKED not_scanned=$NOT_SCANNED)"
else
  echo "⚠ matrix-merger.sh missing — falling back to manual matrix write (legacy path)"
  # Legacy path: orchestrator writes matrix directly using template below
fi
```

**Generated matrix format (canonical, from matrix-merger):**

```markdown
# Goal Coverage Matrix — Phase {phase}
**Generated:** {ISO-timestamp}
**Source:** RUNTIME-MAP.json + .surface-probe-results.json
**Merger:** _shared/lib/matrix-merger.sh v1.9.2.4

## Summary
- Total goals: {N}
- READY: {N}
- BLOCKED: {N}
- NOT_SCANNED: {N} (intermediate)
- UNREACHABLE: {N}
- INFRA_PENDING: {N}
- FAILED: {N} (intermediate)

## By Priority
| Priority | Ready | Blocked | Other | Total | Threshold | Pass % | Status |
|----------|-------|---------|-------|-------|-----------|--------|--------|
| critical | {N} | {N} | {N} | {N} | 100% | {X%} | ✅ PASS/⛔ BLOCK |
| important | {N} | {N} | {N} | {N} | 80% | {X%} | ... |
| nice-to-have | {N} | {N} | {N} | {N} | 50% | {X%} | ... |

## Goal Details
| Goal | Priority | Surface | Status | Evidence |
|------|----------|---------|--------|----------|
| G-01 | critical | api | READY | handler=apps/api/src/... |

## Gate: ✅/⛔/⚠️ {VERDICT}
{PASS|BLOCK|INTERMEDIATE message with next-action hints}
```

### 4d: Inline triage + apply scope-tag actions (v1.14.0+ A.2)

Triage chạy **inline** ngay sau matrix ghi, TRƯỚC 100% gate. Mục đích: đọc scope tag (`depends_on_phase`, `verification_strategy`) từ CONTEXT.md, phân loại mỗi UNREACHABLE thành verdict + action_required, rồi áp dụng action nào autonomous được (mark_deferred/mark_manual). Các action cần người quyết định (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) sẽ ghi vào hàng đợi nhưng vẫn BLOCK gate — **không có đường thoát ngụỵ trang**.

```bash
session_mark_step "4d-inline-triage"
echo ""
echo "🔍 Triage + áp dụng action cho UNREACHABLE goals (v1.14.0+)..."

# v1.14.3 H3 — pre-scan test source for @deferred markers so triage sees them
# alongside scope tags. Fixes gap where executor-written it.skip('@deferred X')
# was ignored (tests were skipped but matrix still BLOCKED).
DEFER_SCANNER=".claude/scripts/scan-deferred-tests.py"
if [ -f "$DEFER_SCANNER" ]; then
  echo "▸ Pre-scan: @deferred markers in test source..."
  ${PYTHON_BIN:-python3} "$DEFER_SCANNER" \
    --phase-dir "${PHASE_DIR}" --repo-root "${REPO_ROOT:-.}" 2>&1 | tail -12 || true
  # Writes .deferred-tests.json — consumed by unreachable-triage below
fi

# Chạy triage (sinh .unreachable-triage.json + UNREACHABLE-TRIAGE.md)
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
if type -t triage_unreachable_goals >/dev/null 2>&1; then
  triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
else
  echo "⚠ unreachable-triage.sh missing — triage bị bỏ qua, 100% gate sẽ hard-block mọi UNREACHABLE." >&2
fi

TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

if [ -f "$TRIAGE_JSON" ] && [ -f "$MATRIX" ]; then
  # Áp dụng action_required autonomous: mark_deferred, mark_manual
  # Những action còn lại (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) ghi log + để BLOCK.
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$TRIAGE_JSON" "$MATRIX" "$PHASE_DIR" "$PHASE_NUMBER" <<'PY'
import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

triage_path = Path(sys.argv[1])
matrix_path = Path(sys.argv[2])
phase_dir   = Path(sys.argv[3])
phase_num   = sys.argv[4]

try:
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
except Exception as e:
    print(f"⚠ Không đọc được triage JSON: {e}")
    sys.exit(0)

verdicts = triage.get("verdicts", {})

# v1.14.3 H3 — merge .deferred-tests.json as additional deferral source
# (test files with it.skip('@deferred X') markers that aren't in CONTEXT.md scope tags).
deferred_tests_path = phase_dir / ".deferred-tests.json"
test_deferrals = {}  # ts_id → {reason, kind}
if deferred_tests_path.exists():
    try:
        dt = json.loads(deferred_tests_path.read_text(encoding="utf-8"))
        for entry in dt.get("deferred_tests", []):
            ts = entry.get("ts_id")
            if ts:
                test_deferrals[ts] = entry
    except Exception as e:
        print(f"⚠ Không đọc được .deferred-tests.json: {e}")

if not verdicts and not test_deferrals:
    print("ℹ Không có UNREACHABLE cần triage — skip.")
    sys.exit(0)

matrix_text = matrix_path.read_text(encoding="utf-8")
pending_queue = []   # cho các action chờ user / destructive
applied       = {"mark_deferred": [], "mark_manual": [], "pending": []}

def update_status_in_matrix(text, gid, new_status, note=""):
    # Tìm dòng trong ## Goal Details có `| G-XX | ... | UNREACHABLE | ... |`
    # Thay UNREACHABLE → new_status; append note vào evidence nếu có.
    pat = re.compile(r'^(\| *' + re.escape(gid) + r' *\|[^|]*\|[^|]*\|) *UNREACHABLE *(\|[^\n]*)', re.M)
    def _repl(m):
        prefix = m.group(1)
        suffix = m.group(2)
        if note:
            suffix = suffix.rstrip("|").rstrip() + f" ({note})|"
        return f"{prefix} {new_status} {suffix}"
    return pat.sub(_repl, text, count=1)

for gid, v in verdicts.items():
    action   = v.get("action_required")
    params   = v.get("action_params", {})
    verdict  = v.get("verdict", "")

    if action == "mark_deferred":
        target = params.get("target_phase", "?")
        matrix_text = update_status_in_matrix(matrix_text, gid, "DEFERRED", f"depends_on_phase: {target}")
        applied["mark_deferred"].append((gid, target))
    elif action == "mark_manual":
        strat = params.get("strategy", "manual")
        matrix_text = update_status_in_matrix(matrix_text, gid, "MANUAL", f"verification: {strat}")
        applied["mark_manual"].append((gid, strat))
    elif action in ("spawn_fix_agent", "draft_amendment_ask", "prompt_scope_tag"):
        # Giữ UNREACHABLE — gate sẽ block; ghi vào pending queue
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": verdict,
            "action":  action,
            "params":  params,
            "title":   v.get("title", "(no title)"),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, action))

# v1.14.3 H3 — apply test-level deferrals (fills gap where scope tags missing
# but test source has it.skip('@deferred X')). Status depends on defer_kind:
#   depends_on_phase + test-codegen → DEFERRED
#   manual + faketime               → MANUAL
#   unknown                         → log as pending, leave as UNREACHABLE
for ts_id, entry in test_deferrals.items():
    # ts_id is "TS-XX"; matrix may have goal_ids like "TS-16" or "G-XX" — try TS- first
    gid = ts_id
    kind = entry.get("defer_kind", "unknown")
    reason = entry.get("defer_reason", "")
    if kind in ("depends_on_phase", "test-codegen"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "DEFERRED",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_deferred"].append((gid, f"test-marker:{kind}"))
    elif kind in ("manual", "faketime"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "MANUAL",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_manual"].append((gid, kind))
    else:
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": "test-level @deferred with unknown kind",
            "action":  "review_test_defer_reason",
            "params":  {"reason": reason, "source": entry.get("source_file", "")},
            "title":   entry.get("test_title", ""),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, "test-defer-unknown"))

# Re-sync header counts trong "## Summary" block nếu có thay đổi
def recount_summary(text):
    details = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
    if not details:
        return text
    body = details.group(1)
    counts = {"READY":0, "BLOCKED":0, "UNREACHABLE":0, "INFRA_PENDING":0,
              "DEFERRED":0, "MANUAL":0, "NOT_SCANNED":0, "FAILED":0}
    for line in body.splitlines():
        for k in counts:
            # Status cell đứng giữa 2 dấu | — tránh match keyword trong evidence
            if re.search(r'\|\s*' + k + r'\s*\|', line):
                counts[k] += 1
                break
    def _rewrite_summary(m):
        total = sum(counts.values())
        new = [
            "## Summary",
            f"- Total goals: {total}",
            f"- READY: {counts['READY']}",
            f"- DEFERRED: {counts['DEFERRED']} (tagged depends_on_phase)",
            f"- MANUAL: {counts['MANUAL']} (tagged verification_strategy)",
            f"- BLOCKED: {counts['BLOCKED']}",
            f"- UNREACHABLE: {counts['UNREACHABLE']}",
            f"- INFRA_PENDING: {counts['INFRA_PENDING']}",
            f"- NOT_SCANNED: {counts['NOT_SCANNED']} (intermediate)",
            f"- FAILED: {counts['FAILED']} (intermediate)",
            ""
        ]
        return "\n".join(new)
    new_text = re.sub(r'^## Summary\n(?:[-*].*\n)+', _rewrite_summary, text, count=1, flags=re.M)
    return new_text

matrix_text = recount_summary(matrix_text)
matrix_path.write_text(matrix_text, encoding="utf-8")

# Ghi pending queue vào .vg/PENDING-USER-REVIEW.md (append-only)
if pending_queue:
    pending_file = Path(".vg/PENDING-USER-REVIEW.md")
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not pending_file.exists()
    with pending_file.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("# Pending user review — hàng đợi quyết định đang chờ\n\n")
            f.write("Mỗi mục là một goal cần quyết định (scope tag / fix / amendment). ")
            f.write("User review xong → duyệt queue thay vì bị hỏi từng cái.\n\n")
            f.write("| Phase | Goal | Verdict | Action cần | Tiêu đề | Queued at |\n")
            f.write("|---|---|---|---|---|---|\n")
        for p in pending_queue:
            f.write(f"| {p['phase']} | {p['goal_id']} | {p['verdict']} | {p['action']} | "
                    f"{p['title'][:60]} | {p['queued_at']} |\n")

# Narration
print(f"▸ Triage applied: "
      f"{len(applied['mark_deferred'])} → DEFERRED, "
      f"{len(applied['mark_manual'])} → MANUAL, "
      f"{len(applied['pending'])} → chờ người duyệt")
for gid, tgt in applied["mark_deferred"]:
    print(f"  🔁 {gid} → DEFERRED (depends_on_phase: {tgt})")
for gid, strat in applied["mark_manual"]:
    print(f"  ✋ {gid} → MANUAL ({strat})")
for gid, act in applied["pending"]:
    print(f"  ⏳ {gid} → {act} (giữ UNREACHABLE, gate sẽ BLOCK đến khi giải quyết)")
PY
else
  [ -f "$TRIAGE_JSON" ] || echo "ℹ Không có triage JSON (không UNREACHABLE goal nào) — skip apply."
fi
```

### 4e: Cổng 100% (hard, v1.14.0+ A.3)

Thay gate trọng số (critical/important/nice-to-have) cũ bằng quy tắc đơn giản:

- **ĐẠT (PASS)** khi `BLOCKED == 0` VÀ `UNREACHABLE == 0` (goals ở trạng thái kết thúc: READY + DEFERRED + MANUAL + INFRA_PENDING).
- **BỊ CHẶN (BLOCK)** khi còn bất kỳ goal `BLOCKED` hoặc `UNREACHABLE`.

Không còn grey zone — DEFERRED và MANUAL là hai đường thoát hợp lệ nhưng phải declare ở `/vg:scope`, không phải review tự gắn.

```bash
session_mark_step "4e-100pct-gate"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

# Đọc config gate threshold (default 100, legacy-mode fallback 80)
GATE_THRESHOLD=$(${PYTHON_BIN} -c "
import re, sys
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold\s*:\s*(\d+)', c)
    print(m.group(1) if m else '100')
except Exception:
    print('100')
")

# Legacy-mode override: --legacy-mode flag hoặc config review.gate_threshold_legacy
if [[ "$ARGUMENTS" =~ --legacy-mode ]]; then
  GATE_THRESHOLD_LEGACY=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold_legacy\s*:\s*(\d+)', c)
    print(m.group(1) if m else '80')
except Exception:
    print('80')
")
  echo "⚠ --legacy-mode: dùng ngưỡng ${GATE_THRESHOLD_LEGACY}% (pre-v1.14). Flag này sẽ hết hạn sau 2 milestones."
  GATE_THRESHOLD="$GATE_THRESHOLD_LEGACY"
fi

# Count statuses từ matrix
if [ -f "$MATRIX" ]; then
  GATE_COUNTS=$(PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$MATRIX" <<'PY'
import re, sys, json
text = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
body = m.group(1) if m else ""
buckets = ["READY","DEFERRED","MANUAL","BLOCKED","UNREACHABLE","INFRA_PENDING","NOT_SCANNED","FAILED"]
counts = {b:0 for b in buckets}
for line in body.splitlines():
    for b in buckets:
        if re.search(r'\|\s*' + b + r'\s*\|', line):
            counts[b] += 1
            break
print(json.dumps(counts))
PY
)
  READY=$(echo "$GATE_COUNTS"        | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['READY'])")
  DEFERRED=$(echo "$GATE_COUNTS"     | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['DEFERRED'])")
  MANUAL=$(echo "$GATE_COUNTS"       | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['MANUAL'])")
  BLOCKED=$(echo "$GATE_COUNTS"      | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['BLOCKED'])")
  UNREACHABLE=$(echo "$GATE_COUNTS"  | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['UNREACHABLE'])")
  INFRA_PENDING=$(echo "$GATE_COUNTS"| ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['INFRA_PENDING'])")

  TOTAL=$((READY + DEFERRED + MANUAL + BLOCKED + UNREACHABLE + INFRA_PENDING))
  # Goals được tính là "kết thúc": READY + DEFERRED + MANUAL + INFRA_PENDING
  PASS_COUNT=$((READY + DEFERRED + MANUAL + INFRA_PENDING))
  FAIL_COUNT=$((BLOCKED + UNREACHABLE))

  if [ "$TOTAL" -gt 0 ]; then
    PASS_PCT=$(( PASS_COUNT * 100 / TOTAL ))
  else
    PASS_PCT=0
  fi

  echo ""
  echo "━━━ Cổng kiểm tra (${GATE_THRESHOLD}%) ━━━"
  echo "  Tổng goals:    $TOTAL"
  echo "  ✅ READY:      $READY"
  echo "  🔁 DEFERRED:   $DEFERRED (tagged depends_on_phase)"
  echo "  ✋ MANUAL:     $MANUAL (tagged verification_strategy)"
  echo "  ♻ INFRA:      $INFRA_PENDING (ngoài ENV hiện tại)"
  echo "  ⛔ BLOCKED:    $BLOCKED"
  echo "  ❓ UNREACHABLE:$UNREACHABLE"
  echo "  Tỉ lệ đạt:    ${PASS_PCT}% (yêu cầu ≥${GATE_THRESHOLD}%)"
  echo ""

  export GATE_THRESHOLD PASS_COUNT FAIL_COUNT PASS_PCT TOTAL
  export READY DEFERRED MANUAL BLOCKED UNREACHABLE INFRA_PENDING
else
  echo "⚠ GOAL-COVERAGE-MATRIX.md không tồn tại — không tính được gate."
  export FAIL_COUNT=999 PASS_PCT=0 GATE_THRESHOLD=100
fi
```

### 4f: Quyết định cổng (100% hard)

```bash
session_mark_step "4f-gate-decision"

# Quy tắc:
#   GATE_THRESHOLD == 100 (default)  → PASS iff FAIL_COUNT == 0
#   GATE_THRESHOLD <  100 (legacy)   → PASS iff PASS_PCT >= threshold
if [ "$GATE_THRESHOLD" = "100" ]; then
  GATE_PASS=$([ "$FAIL_COUNT" -eq 0 ] && echo "true" || echo "false")
else
  GATE_PASS=$([ "$PASS_PCT" -ge "$GATE_THRESHOLD" ] && echo "true" || echo "false")
fi

if [ "$GATE_PASS" = "true" ]; then
  echo "✅ Cổng ĐẠT — phase sẵn sàng cho /vg:test ${PHASE_NUMBER}"
  echo ""

  # v1.14.0+ A.4 — write trigger cho CROSS-PHASE-DEPS aggregator
  # Nếu có goal DEFERRED → append vào .vg/CROSS-PHASE-DEPS.md (idempotent)
  if [ "$DEFERRED" -gt 0 ]; then
    CPD_SCRIPT="${REPO_ROOT}/.claude/scripts/vg_cross_phase_deps.py"
    if [ -f "$CPD_SCRIPT" ]; then
      PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$CPD_SCRIPT" append "$PHASE_NUMBER" 2>&1 | sed 's/^/  /'
    else
      echo "⚠ vg_cross_phase_deps.py missing — DEFERRED entries không được aggregate." >&2
    fi
    echo "ℹ Có $DEFERRED goal DEFERRED (chờ phase phụ thuộc). Xem .vg/CROSS-PHASE-DEPS.md"
  fi
  if [ "$MANUAL" -gt 0 ]; then
    echo "ℹ Có $MANUAL goal MANUAL. /vg:accept sẽ prompt checklist người dùng."
  fi
  if [ "$INFRA_PENDING" -gt 0 ]; then
    echo "ℹ Có $INFRA_PENDING goal chờ infra (ngoài ENV). Re-run với --sandbox nếu cần."
  fi
else
  echo "⛔ Cổng BỊ CHẶN — còn $FAIL_COUNT goal chưa kết thúc."
  echo ""

  # Gợi ý hành động theo loại fail
  if [ "$BLOCKED" -gt 0 ]; then
    echo "  🛠 $BLOCKED goal BLOCKED (scan chạy nhưng criteria fail):"
    echo "     → Sửa code → re-run /vg:review ${PHASE_NUMBER} --fix-only"
  fi
  if [ "$UNREACHABLE" -gt 0 ]; then
    echo "  ❓ $UNREACHABLE goal UNREACHABLE (không reach được UI hoặc chưa build):"
    echo "     → Đọc ${PHASE_DIR}/UNREACHABLE-TRIAGE.md — mỗi goal có verdict + action gợi ý"
    echo "     → cross-phase-pending    → /vg:amend ${PHASE_NUMBER} thêm depends_on_phase tag"
    echo "     → bug-this-phase         → /vg:build ${PHASE_NUMBER} --gaps-only"
    echo "     → scope-amend destructive→ user confirm amendment rồi re-run review"

    # Nếu có pending queue, nhắc
    if [ -f ".vg/PENDING-USER-REVIEW.md" ]; then
      PENDING_CNT=$(grep -c "^| ${PHASE_NUMBER} " ".vg/PENDING-USER-REVIEW.md" 2>/dev/null || echo 0)
      [ "$PENDING_CNT" -gt 0 ] && echo "     → $PENDING_CNT mục đang chờ người duyệt (.vg/PENDING-USER-REVIEW.md)"
    fi
  fi

  echo ""
  echo "Không còn đường thoát tự động — scope tag phải declare ở /vg:scope (không phải review tự gán)."

  # Exit với mã lỗi để caller biết gate fail
  exit 1
fi
```
</step>

<step name="unreachable_triage">
## UNREACHABLE Triage — legacy guard (v1.14.0+)

**Từ v1.14.0, triage chạy INLINE trong Phase 4d (ngay trước cổng 100%).** Step này chỉ còn là **guard** cho trường hợp legacy flow đi vòng (ví dụ `--skip-discovery` + `--fix-only` nhảy qua 4d). Nếu `.unreachable-triage.json` đã tồn tại từ 4d → skip; nếu chưa → chạy fallback.

```bash
TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
if [ -f "$TRIAGE_JSON" ]; then
  echo "ℹ Triage đã chạy inline ở Phase 4d — skip legacy guard."
else
  session_mark_step "4f-unreachable-triage-legacy"
  echo ""
  echo "🔍 Legacy path: UNREACHABLE triage fallback (4d bị bỏ qua)..."
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
  if type -t triage_unreachable_goals >/dev/null 2>&1; then
    triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
  else
    echo "⚠ unreachable-triage.sh missing — triage skipped" >&2
  fi
fi
```

**Lưu ý v1.14.0+:** Triage không còn là "report-only cho accept gate". Triage SINH action_required, review 4d ÁP DỤNG autonomous action (mark_deferred/mark_manual) và BLOCK gate cho action cần người duyệt (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag). Xem spec section A.2.
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
# UNREACHABLE-TRIAGE artifacts (only exist if triage ran — i.e., any UNREACHABLE goal)
[ -f "${PHASE_DIR}/UNREACHABLE-TRIAGE.md" ]   && git add "${PHASE_DIR}/UNREACHABLE-TRIAGE.md"
[ -f "${PHASE_DIR}/.unreachable-triage.json" ] && git add "${PHASE_DIR}/.unreachable-triage.json"
git commit -m "review({phase}): RUNTIME-MAP — {views} views, {actions} actions, gate {PASS|BLOCK}"
```
</step>

<step name="bootstrap_reflection">
## End-of-Step Reflection (v1.15.0 Bootstrap Overlay)

Before closing review, spawn the **reflector** subagent to analyze this step's
artifacts + user messages + telemetry and draft learning candidates for user
review. Primary path for project self-adaptation.

**Skip conditions** (reflection does nothing, exit 0):
- `.vg/bootstrap/` directory absent (project hasn't opted in)
- `config.bootstrap.reflection_enabled == false` (user disabled)
- Review verdict = `FAIL` with fatal errors (reflect when next review succeeds)

### Run

```bash
BOOTSTRAP_DIR=".vg/bootstrap"
if [ ! -d "$BOOTSTRAP_DIR" ]; then
  # Bootstrap not opted in — skip silently
  :
else
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-review-${REFLECT_TS}.yaml"
  USER_MSG_FILE="${VG_TMP}/reflect-user-msgs-${REFLECT_TS}.txt"

  # Extract user messages sent during this step from Claude transcript (if accessible).
  # If no transcript API, reflector uses artifacts + telemetry + git log only.
  # Orchestrator may populate USER_MSG_FILE from session context.
  : > "$USER_MSG_FILE"

  # Filter telemetry entries to this phase+step within last 4 hours
  TELEMETRY_SLICE="${VG_TMP}/reflect-telemetry-${REFLECT_TS}.jsonl"
  grep -E "\"phase\":\"${PHASE}\".*\"command\":\"vg:review\"" "${PLANNING_DIR}/telemetry.jsonl" 2>/dev/null \
    | tail -200 > "$TELEMETRY_SLICE" || true

  # Collect override-debt entries created in this step
  OVERRIDE_SLICE="${VG_TMP}/reflect-overrides-${REFLECT_TS}.md"
  grep -E "\"step\":\"review\"" "${PLANNING_DIR}/OVERRIDE-DEBT.md" 2>/dev/null > "$OVERRIDE_SLICE" || true

  echo "📝 Running end-of-step reflection (Haiku, isolated context)..."
fi
```

### Spawn reflector agent (isolated Haiku)

Use Agent tool with skill `vg-reflector`, model `haiku`, fresh context:

```
Agent(
  description="End-of-step reflection for review phase {PHASE}",
  subagent_type="general-purpose",
  prompt="""
Use skill: vg-reflector

Arguments:
  STEP           = "review"
  PHASE          = "{PHASE}"
  PHASE_DIR      = "{PHASE_DIR absolute path}"
  USER_MSG_FILE  = "{USER_MSG_FILE}"
  TELEMETRY_FILE = "{TELEMETRY_SLICE}"
  OVERRIDE_FILE  = "{OVERRIDE_SLICE}"
  ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
  REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
  OUT_FILE       = "{REFLECT_OUT}"

Read .claude/skills/vg-reflector/SKILL.md and follow workflow exactly.
Do NOT read parent conversation transcript — echo chamber forbidden.
Output max 3 candidates with evidence to OUT_FILE.
"""
)
```

### Interactive promote flow (user gates)

After reflector exits, parse OUT_FILE. If candidates found, show to user:

```
📝 Reflection — review phase {PHASE} found {N} learning(s):

[1] {title}
    Type: {type}
    Scope: {scope}
    Evidence: {count} items — {sample}
    Confidence: {confidence}

    → Proposed: {target summary}

    [y] ghi sổ tay  [n] reject  [e] edit inline  [s] skip lần này

[2] ...

User gõ: y/n/e/s cho từng item, hoặc "all-defer" để bỏ qua toàn bộ.
```

For `y` → delegate to `/vg:learn --promote L-{id}` internally (validates schema,
dry-run preview, git commit).

For `n` → append to REJECTED.md with user reason.

For `e` → interactive field-by-field edit loop (not external editor):
```
Editing [1]:
  (1) title: "{current}"
  (2) scope: {current}
  (3) prose: "{current}"
  (4) target_step: {current}
  Field to edit? [1-4/done]: _
```

For `s` → leave candidate in `.vg/bootstrap/CANDIDATES.md`, user reviews later via `/vg:learn --review`.

### Emit telemetry

```bash
emit_telemetry "bootstrap.reflection_ran" PASS \
  "{\"step\":\"review\",\"phase\":\"${PHASE}\",\"candidates\":${CANDIDATE_COUNT:-0}}"
```

### Failure mode

Reflector crash or timeout → log warning, continue to `complete` step. Never block review completion.

```
⚠ Reflection failed — review completes normally. Check .vg/bootstrap/logs/
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

**Display — VERDICT-AWARE next steps (MANDATORY format).**

The closing message MUST follow this structure regardless of orchestrator (Claude / Codex / Gemini).
Every finding section MUST end with a concrete actionable command, not just a description.

### When verdict = PASS
```
Review complete for Phase {N} — PASS.
  Goals: {ready}/{total} READY ({pct}%)
  Gate: PASS (critical {C}/{C} 100%, important {I}/{I_total} ≥80%)
  Artifacts: RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md{REVIEW_FEEDBACK_SUFFIX}

Next:
  /vg:test {phase}            # codegen + run regression suite
```

### When verdict = FLAG (passed but with improvements)
```
Review complete for Phase {N} — FLAG ({N} non-blocking findings).
  Goals: {ready}/{total} READY
  Gate: PASS-WITH-FLAGS

Findings (improvements — non-blocking):
  - [Med] {one-line summary} → fix at {file:line}, then commit
  - [Low] {one-line summary} → defer or fix at {file:line}
  ... (full detail in REVIEW-FEEDBACK.md)

Next (pick one):
  /vg:test {phase}                          # proceed — flags are advisory
  edit {file:line}; git commit; /vg:next    # fix flags first, then continue
```

### When verdict = BLOCK (cannot proceed)
```
Review complete for Phase {N} — BLOCK.
  Goals: {ready}/{total} READY ({blocked} BLOCKED, {failed} FAILED, {unreach} UNREACHABLE)
  Gate: BLOCK ({reason — e.g., "critical goal G-03 FAILED" or "infra success_criteria 1/8 READY"})

Findings (severity-grouped — full detail in REVIEW-FEEDBACK.md):
  ⛔ Critical/Nghiêm trọng ({N}):
     1. {one-line summary}
        ↳ Fix: {concrete action — file:line, command, or workflow}
        ↳ Verify: {how to confirm — curl, test, diff}
     2. ...
  ⚠ High/Cao ({N}):
     ... (same format)
  ⓘ Medium/Trung bình ({N}):
     ... (same format)

Next steps (pick the matching path — DO NOT just re-run /vg:review blindly):

  A. Fix code bugs found → re-review:
     # Edit affected files (paths above), then:
     git add -A && git commit -m "fix({phase}-XX): {summary}"
     /vg:review {phase} --retry-failed      # only re-scan failed goals (faster)
     # OR /vg:review {phase}                # full re-scan if many fixes

  B. If findings need scope discussion (architectural, decision change):
     /vg:amend {phase}                       # mid-phase change request workflow
     # then re-blueprint + re-build before re-review

  C. If findings are infra/env (services down, config missing):
     /vg:doctor                              # diagnose env + service health
     # fix infra → /vg:review {phase}

  D. If finding is BUG in /vg:review tooling itself (not phase code):
     /vg:bug-report                          # surface to vietdev99/vgflow

  E. If you DISAGREE with verdict (false positive):
     # Open REVIEW-FEEDBACK.md, dispute specific finding with evidence
     /vg:review {phase} --override-reason "..." --allow-failed=G-XX
     # Will register in OVERRIDE-DEBT — re-evaluated at /vg:accept
```

### Hard rules for AI orchestrator (Claude/Codex/Gemini)
1. **Never end a BLOCK review without listing per-finding fixes + verify steps.** Bare list of issues = user has to re-derive next action — anti-pattern.
2. **Use RELATIVE paths** in narration (`apps/api/src/plugins/health.ts:23`), NOT absolute (`/D/Workspace/...`). Absolute paths waste 60% of terminal width on repeated prefixes.
3. **Per-finding format MUST be:**
   ```
   {N}. [Severity] {ONE LINE root-cause}
        ↳ Fix:    {file:line edit OR shell command OR workflow}
        ↳ Verify: {1-line check command OR test ID}
        ↳ Refs:   {file:line, file:line}  (only if 2+ refs needed)
   ```
4. **Closing MUST contain "Next:" block** with at least 2 labeled options (A/B/C...) when verdict ≠ PASS.
5. **If executor cannot run something** (bash broken, no internet, missing creds), say so EXPLICITLY and tell user the manual command to run instead. Don't bury it in middle of output.

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
