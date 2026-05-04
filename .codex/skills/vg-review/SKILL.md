---
name: "vg-review"
description: "Post-build review — code scan + browser discovery + fix loop + goal comparison → RUNTIME-MAP"
metadata:
  short-description: "Post-build review — code scan + browser discovery + fix loop + goal comparison → RUNTIME-MAP"
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

Invoke this skill as `$vg-review`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>




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
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-review" "00_gate_integrity_precheck" 2>&1 || true

# v2.2 — T8 gate now routes through block_resolve. L1 auto-clears stale
# file when all entries carry resolution markers. Only genuine conflicts BLOCK.
if [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh" ]; then
  [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" ] && \
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh"
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh"
  t8_gate_check "${PLANNING_DIR}" "review"
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
# OHOK-8 round-4 Codex fix: parse PHASE_NUMBER BEFORE run-start so the run
# doesn't register against an empty phase (telemetry + runtime-contract
# evidence attaches to "" instead of the actual phase).
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:review "${PHASE_NUMBER}" "${ARGUMENTS}" || { echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2; exit 1; }
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 00_gate_integrity_precheck 2>/dev/null || true
```

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

TASKLIST_PROFILE="${PROFILE:-web-fullstack}"
TASKLIST_MODE=""
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if [ -n "$PHASE_DIR_CANDIDATE" ] && type -t detect_phase_profile >/dev/null 2>&1; then
  TASKLIST_PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR_CANDIDATE" 2>/dev/null || echo "feature")
  TASKLIST_MODE=$(phase_profile_review_mode "$TASKLIST_PHASE_PROFILE" 2>/dev/null || echo "full")
fi
if [[ "$ARGUMENTS" =~ --mode=([a-z-]+) ]]; then
  TASKLIST_MODE="${BASH_REMATCH[1]}"
fi
: "${TASKLIST_MODE:=full}"

# Emit session-start banner → distinct separator for Claude Code tail UI
session_start "review" "${PHASE_NUMBER:-unknown}"
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:review" \
  --profile "${TASKLIST_PROFILE}" \
  --mode "${TASKLIST_MODE}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true
# Register EXIT trap emitting "━━━ review Phase X EXITED at step=Y ━━━" on any exit path
# Sweep stale state from previous interrupted runs (>config.session.stale_hours old)
[ -n "$PHASE_DIR_CANDIDATE" ] && stale_state_sweep "review" "$PHASE_DIR_CANDIDATE"
# Kill orphan dev servers on declared ports before pre-flight
[ "${CONFIG_SESSION_PORT_SWEEP_ON_START:-true}" = "true" ] && session_port_sweep "pre-flight"

session_mark_step "0-parse-args"
```

Immediately after this block returns, execute the TASKLIST_POLICY binding:
project `.vg/runs/{run_id}/tasklist-contract.json` to the native task UI and
call `vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`.
</step>

<step name="0_parse_and_validate">
Parse `$ARGUMENTS`: phase_number, flags.

Flags:
- `--skip-scan` — skip Phase 1 (code scan), go directly to browser discovery. **Gated**: must pair with `--override-reason="<text>"` (logged to override-debt).
- `--skip-discovery` — skip Phase 2 (browser discovery), use existing RUNTIME-MAP for Phase 4. **Gated**: must pair with `--override-reason="<text>"` (logged to override-debt).
- `--fix-only` — skip to Phase 3 (requires RUNTIME-MAP with errors). **Gated**: listed in `forbidden_without_override` (line 34) — must combine with `--override-reason="<text>"` to run, otherwise hard BLOCK. Entry logged to override-debt register.
- `--skip-crossai` — skip CrossAI review at end
- `--evaluate-only` — skip Phase 1 + 2 (discovery already done by Codex/Gemini), read existing scan JSONs from ${PHASE_DIR}, go directly to Phase 2b-3 (collect + merge) → Phase 3 (fix) → Phase 4 (goal comparison). Requires: nav-discovery.json + scan-*.json already exist.
- `--retry-failed` — skip Phase 1 + Phase 2 navigator, re-scan ONLY views mapped to failed/blocked/SUSPECTED goals in GOAL-COVERAGE-MATRIX.md. Requires: GOAL-COVERAGE-MATRIX.md + RUNTIME-MAP.json already exist. Use when: review already ran but goals < 100%, code was fixed, need targeted re-scan without full re-discovery. **v2.46-wave3.2:** SUSPECTED status (matrix=READY but no submit evidence) is now included in retry set automatically — closes Phase 3.2 staleness gap where matrix lied.
- `--re-scan-goals=G-XX,G-YY,G-ZZ` — bypass matrix entirely; re-scan only the listed goal IDs. Resolves to start_views via RUNTIME-MAP.json goal_sequences. Use when: matrix-staleness validator surfaced specific suspected goals, OR you know exactly which goals need re-evidence. Mutually exclusive with `--retry-failed` (more precise overrides broader).
- `--dogfood` — re-scan ALL mutation goals (any goal with non-empty `mutation_evidence` in TEST-GOALS.md) regardless of matrix status. Use when: you suspect systemic submit-evidence gaps. Slower than `--retry-failed` but catches the full surface.
- `--force` — full rerun from scratch for an already-reviewed phase. Clears prior review markers/artifacts before any staleness/reuse logic runs, so API precheck + discovery + matrix must be regenerated in the current run. Use when: you explicitly want fresh evidence, not re-validation on existing artifacts.
- `--full-scan` — disable sidebar suppression. Haiku agents see full page (sidebar/header/footer) in every snapshot. Use when: app has non-standard layout, geometry detection fails, or debugging suppression issues.
- `--with-probes` — enable mutation probe variations (edit/boundary/repeat) in step 2b-3 step 9. Adds 1 Haiku per mutation goal. Default OFF — let /vg:test handle variations via Playwright codegen (deterministic, cheaper).
- `--allow-no-crud-surface` — last-resort waiver for legacy phases missing CRUD-SURFACES.md. Logs debt via validator output; do not use for new CRUD work.

**Flag parsing (v2.46-wave3.2 — explicit env vars used downstream):**
```bash
# Parse boolean + value flags from $ARGUMENTS into env vars consumed by later steps.
# (Pre-wave3.2 the skill relied on AI interpretation; making it explicit closes
# the gap where staleness check + retry-failed referenced unset variables.)
ARGS_RAW="${ARGUMENTS:-}"
RETRY_FAILED=""
RE_SCAN_GOALS=""
DOGFOOD=""
SKIP_SCAN=""
SKIP_DISCOVERY=""
FIX_ONLY=""
EVALUATE_ONLY=""
FULL_SCAN=""
WITH_PROBES=""
SKIP_CROSSAI=""
ALLOW_NO_CRUD_SURFACE=""
NON_INTERACTIVE=""
FORCE_RERUN=""

for tok in $ARGS_RAW; do
  case "$tok" in
    --retry-failed)            RETRY_FAILED=1 ;;
    --re-scan-goals=*)         RE_SCAN_GOALS="${tok#--re-scan-goals=}" ;;
    --dogfood)                 DOGFOOD=1 ;;
    --force)                   FORCE_RERUN=1 ;;
    --skip-scan)               SKIP_SCAN=1 ;;
    --skip-discovery)          SKIP_DISCOVERY=1 ;;
    --fix-only)                FIX_ONLY=1 ;;
    --evaluate-only)           EVALUATE_ONLY=1 ;;
    --full-scan)               FULL_SCAN=1 ;;
    --with-probes)             WITH_PROBES=1 ;;
    --skip-crossai)            SKIP_CROSSAI=1 ;;
    --allow-no-crud-surface)   ALLOW_NO_CRUD_SURFACE=1 ;;
    --non-interactive)         NON_INTERACTIVE=1 ;;
  esac
done

export RETRY_FAILED RE_SCAN_GOALS DOGFOOD SKIP_SCAN SKIP_DISCOVERY FIX_ONLY \
       EVALUATE_ONLY FULL_SCAN WITH_PROBES SKIP_CROSSAI ALLOW_NO_CRUD_SURFACE \
       NON_INTERACTIVE FORCE_RERUN
```

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
  REQUIRED_ARTIFACTS="SPECS.md CONTEXT.md PLAN.md API-CONTRACTS.md API-DOCS.md TEST-GOALS.md SUMMARY.md"
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

**Force rerun reset (`--force`) — clear prior review state before any reuse/staleness branch can fire.**

This is the explicit escape hatch for "phase already reviewed" situations.
`--force` means: do a real full rerun, not matrix-only re-validation.

```bash
if [ -n "$FORCE_RERUN" ]; then
  if [ -n "$RETRY_FAILED" ] || [ -n "$RE_SCAN_GOALS" ] || [ -n "$EVALUATE_ONLY" ] || \
     [ -n "$DOGFOOD" ] || [ -n "$SKIP_DISCOVERY" ] || [ -n "$FIX_ONLY" ]; then
    echo "⛔ --force is incompatible with --retry-failed, --re-scan-goals, --evaluate-only, --dogfood, --skip-discovery, and --fix-only." >&2
    echo "   Use plain full review + --force when you need fresh API/browser evidence." >&2
    exit 1
  fi

  # If operator explicitly pinned a non-full mode on CLI, reject. Force is
  # for full rerun semantics, not profile-short-circuit modes.
  if [[ "${ARGS_RAW}" =~ --mode=([a-z-]+) ]] && [ "${BASH_REMATCH[1]}" != "full" ]; then
    echo "⛔ --force currently supports only --mode=full. Got --mode=${BASH_REMATCH[1]}." >&2
    exit 1
  fi

  VG_SCRIPT_ROOT="${REPO_ROOT:-.}/.claude/scripts"
  [ -d "$VG_SCRIPT_ROOT" ] || VG_SCRIPT_ROOT="${REPO_ROOT:-.}/scripts"
  FORCE_RESET_SCRIPT="${VG_SCRIPT_ROOT}/reset-review-state.py"
  if [ ! -f "$FORCE_RESET_SCRIPT" ]; then
    echo "⛔ --force requested but reset helper missing: $FORCE_RESET_SCRIPT" >&2
    exit 1
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "↻ Force rerun requested"
  echo "   Clearing prior review markers/artifacts"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  FORCE_RESET_JSON=$("${PYTHON_BIN:-python3}" "$FORCE_RESET_SCRIPT" --phase-dir "${PHASE_DIR}")
  FORCE_RESET_RC=$?
  if [ "$FORCE_RESET_RC" -ne 0 ]; then
    echo "⛔ reset-review-state failed — cannot guarantee a fresh rerun." >&2
    exit 1
  fi

  echo "$FORCE_RESET_JSON" | "${PYTHON_BIN:-python3}" -c "
import json, sys
data = json.load(sys.stdin)
print(f\"   removed artifacts: {data.get('removed_count', 0)}\")
for path in data.get('removed', [])[:12]:
    print(f\"   - {path}\")
extra = max(0, len(data.get('removed', [])) - 12)
if extra:
    print(f\"   ... +{extra} more\")
"

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.force_rerun_requested" \
    --step "0_parse_and_validate" \
    --actor "llm-claimed" \
    --outcome "INFO" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mode\":\"full\"}" >/dev/null 2>&1 || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.force_rerun_workspace_reset" \
    --step "0_parse_and_validate" \
    --actor "llm-claimed" \
    --outcome "INFO" \
    --payload "$FORCE_RESET_JSON" >/dev/null 2>&1 || true
fi
```

**Matrix staleness check (v2.46-wave3.2) — closes "matrix says READY but button still errors" gap.**

Runs BEFORE `--retry-failed` short-circuit so SUSPECTED goals get folded into the retry set automatically. Cross-checks `goal_sequences[].steps[]` against each goal's `mutation_evidence` declaration:

- `mutation_evidence` non-empty → goal expects submit click + 2xx mutation network
- `goal_sequences[gid].result == 'passed'` AND no submit step → SUSPECTED
- `goal_sequences[gid].result == 'passed'` AND no 2xx POST/PUT/PATCH/DELETE → SUSPECTED
- `goal_sequences[gid].result == 'passed'` AND only cancel-only steps → SUSPECTED

```bash
# Only run if both artifacts exist (skip on first review where matrix not yet built)
if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ] && [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
  STALENESS_VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-matrix-staleness.py"
  if [ -f "$STALENESS_VALIDATOR" ]; then
    echo "━━ Checking matrix staleness (matrix-vs-runtime evidence) ━━"
    # --apply-status-update: rewrite matrix in place so retry-failed picks up SUSPECTED goals
    STALENESS_OUT=$("${PYTHON_BIN:-python3}" "$STALENESS_VALIDATOR" \
      --phase "$PHASE_NUMBER" \
      --severity block \
      --apply-status-update 2>&1)
    STALENESS_RC=$?

    SUSPECTED_COUNT=0
    if [ -f "${PHASE_DIR}/.matrix-staleness.json" ]; then
      SUSPECTED_COUNT=$("${PYTHON_BIN:-python3}" -c "
import json
try: print(json.load(open('${PHASE_DIR}/.matrix-staleness.json'))['suspected_count'])
except: print(0)
")
    fi

    if [ "$STALENESS_RC" -ne 0 ] && [ "$SUSPECTED_COUNT" -gt 0 ]; then
      echo "⚠ ${SUSPECTED_COUNT} goal(s) marked SUSPECTED — matrix=READY but no submit evidence." >&2
      # Auto-promote to --retry-failed if not already in a retry/scan-goals mode
      if [ -z "$RETRY_FAILED" ] && [ -z "$RE_SCAN_GOALS" ] && [ -z "$DOGFOOD" ]; then
        echo "   Auto-promoting to --retry-failed (SUSPECTED goals folded into retry set)." >&2
        RETRY_FAILED=1
        export RETRY_FAILED
      fi
    elif [ "$SUSPECTED_COUNT" -eq 0 ]; then
      echo "✓ Matrix staleness OK — all READY goals have submit + 2xx mutation evidence."
    fi
  else
    echo "⚠ verify-matrix-staleness.py not found — skipping staleness check (re-sync vgflow)." >&2
  fi
fi
```

**Validate `--re-scan-goals` flag (mutually exclusive with `--retry-failed`):**
```bash
if [ -n "$RE_SCAN_GOALS" ] && [ -n "$RETRY_FAILED" ]; then
  echo "⛔ --re-scan-goals and --retry-failed are mutually exclusive (--re-scan-goals is more precise)." >&2
  exit 1
fi
if [ -n "$RE_SCAN_GOALS" ]; then
  # Validate each goal ID exists in RUNTIME-MAP.json goal_sequences
  if [ ! -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
    echo "⛔ --re-scan-goals requires RUNTIME-MAP.json (run /vg:review {phase} first)." >&2
    exit 1
  fi
  INVALID_GOALS=$("${PYTHON_BIN:-python3}" -c "
import json
rt = json.load(open('${PHASE_DIR}/RUNTIME-MAP.json'))
seqs = rt.get('goal_sequences') or {}
asked = '${RE_SCAN_GOALS}'.split(',')
missing = [g.strip() for g in asked if g.strip() and g.strip() not in seqs]
print(','.join(missing))
" 2>/dev/null)
  if [ -n "$INVALID_GOALS" ]; then
    echo "⛔ --re-scan-goals: unknown goal IDs: ${INVALID_GOALS}" >&2
    echo "   Valid IDs are keys of goal_sequences in RUNTIME-MAP.json." >&2
    exit 1
  fi
fi
```
</step>

<step name="0a_env_mode_gate">
## Step 0a — Confirm review env + mode + scanner (v2.42.1+ — HARD gate)

**Background:** Pre-v2.42, review used `config.step_env.verify` silently. User had no visibility. Phases 3.3/3.4a/3.4b needed re-runs because env wasn't pinned. v2.42 added prompt with `severity: warn` — AI skipped it. v2.42.1 makes this a HARD block (severity: block default + telemetry required).

**This step makes env+mode+scanner user-visible + recorded BEFORE any other work happens.**

### ⛔ MANDATORY FIRST ACTION (before ANY other tool call in this step)

**STOP. The very first thing you do in step `0a_env_mode_gate` is run the provider-native user prompt** with the payload below — no exceptions other than the documented waivers.

Provider-native prompt means:
- **Claude Code:** invoke `AskUserQuestion` with the structured payload below.
- **Codex:** ask the same concise questions in the main Codex thread, or use the closest available Codex user-input UI. Do not literally ask for `AskUserQuestion`; Codex does not expose that Claude primitive inside generated skills.

Runtime rule: Claude remains the canonical source path. If runtime is Claude
or unknown, keep `AskUserQuestion` + `haiku-only`. Only when
`VG_RUNTIME=codex` (set by the Codex adapter) or Codex runtime is detected
does this step map to main-thread prompt + `codex-inline`.

**Skip the provider-native prompt ONLY when:**
- `$ARGUMENTS` contains `--non-interactive` flag, OR
- `VG_NON_INTERACTIVE=1` env var is set, OR
- `$ARGUMENTS` contains ALL THREE: `--target-env=<v>` (or `--sandbox`/`--local`/`--staging`/`--prod`), `--mode=<v>`, and `--scanner=<v>`

If ANY of the 3 axes is missing on CLI and not waived → provider-native prompt is REQUIRED. Do NOT silently default. Do NOT run the bash block below before the prompt returns.

**Why HARD gate (v2.42.1):** AI agents have a strong pull to silent-default in `warn` severity contracts. Phases 3.3/3.4a/3.4b confirmed this. Block severity + telemetry-required closes the gap.

### Provider prompt payload (3 questions, single batched call on Claude; concise main-thread questions on Codex)

```
questions:
  - question: "Review environment — chạy review trên môi trường nào? (môi trường = environment, môi trường thử nghiệm)"
    header: "Env"
    multiSelect: false
    options:
      - label: "local — máy của bạn (port 3001-3010, fastest)"
        description: "Browser MCP local, DB seed local, không cần SSH. Tốt khi iterate nhanh."
      - label: "sandbox — VPS Hetzner (printway.work subdomain)"
        description: "Production-like, ssh deploy. Mặc định cho phase ship-ready."
      - label: "staging — staging server (CHỈ nếu config có)"
        description: "Hiện chưa cấu hình ở project này — chọn sẽ fail."
      - label: "prod — production (CẢNH BÁO: read-only debug)"
        description: "CHỈ dùng debug khẩn cấp. Workflow sẽ block mutations."
  - question: "Review mode — chạy theo profile (hồ sơ phase) nào?"
    header: "Mode"
    multiSelect: false
    options:
      - label: "full — discovery đầy đủ (feature profile)"
        description: "Phase 1 code scan + Phase 2 browser scan + fix loop. Mặc định cho feature mới."
      - label: "delta — chỉ scan vùng đã sửa (hotfix profile)"
        description: "Diff-aware. Tốt cho hotfix nhỏ, không cần full sweep."
      - label: "regression — sweep sau bugfix (bugfix profile)"
        description: "Re-verify parent goals + new bug fix area."
      - label: "schema-verify — round-trip migration (migration profile)"
        description: "Up/down migration check, không discovery UI."
      - label: "link-check — markdown links (docs profile)"
        description: "Validate links + cross-refs only. Skip UI."
      - label: "infra-smoke — chạy success_criteria bash (infra profile)"
        description: "Parse SPECS bash bullets, run từng cái, ghi kết quả."
  - question: "Scanner — model/runtime nào chạy code-scan + view-scan (deepscan = quét sâu)"
    header: "Scanner"
    multiSelect: false
    options:
      - label: "codex-inline — Codex main-orchestrator scan (Codex Recommended)"
        description: "Codex giữ MCP/browser trong main orchestrator, chạy scanner protocol inline/sequential và vẫn ghi cùng scan artifacts/events. Không spawn Haiku."
      - label: "haiku-only — Claude Haiku scanner (Claude Code fastest)"
        description: "Claude Code path: Phase 1 + Phase 2b-2 dùng Haiku agents qua Task tool. Chỉ chọn trên Codex nếu child MCP/subagent path đã smoke-test."
      - label: "codex-supplement — Haiku + Codex CLI deepscan trên surfaces trọng yếu"
        description: "Claude: Haiku + Codex CLI supplement. Codex: inline scan + optional codex exec read-only classifier over captured snapshots if smoke-tested."
      - label: "gemini-supplement — Haiku + Gemini CLI deepscan"
        description: "Gemini Pro 3.1 cross-scan, focus on UI consistency + a11y. +cost +time."
      - label: "council-all — Haiku + Codex + Gemini + Claude (full council deepscan)"
        description: "Triple cross-AI review. CHỈ dùng khi phase ship-critical (e.g., payment, auth)."
  - question: "Method — cách chạy scanner: spawn auto subprocess hay manual paste prompt? (chỉ áp dụng khi scanner cần external CLI)"
    header: "Method"
    multiSelect: false
    options:
      - label: "spawn — VG tự subprocess CLI scanner (Recommended)"
        description: "Hands-off, tự chạy + tự gom log. Cần CLI authenticated trên máy này (codex / gemini). Với codex-inline thì main orchestrator sở hữu MCP/browser."
      - label: "manual — VG sinh prompt files cho user paste"
        description: "Generates per-tool prompts vào `.vg/phases/{phase}/review/prompts/{codex,gemini}/` cho user paste sang CLI desktop / Cursor / web ChatGPT. User tự chạy, drop scan results vào `runs/{tool}/`, VG verify khi user signal continue."
      - label: "hybrid — auto cho high-confidence lenses, manual cho human-judgment"
        description: "Routing per `vg.config review.scanner.hybrid_routing`. Phù hợp khi muốn tốc độ + control selective."
```

### After provider prompt returns

**Export BEFORE running bash:**
```bash
export VG_ENV="<chosen env>"            # e.g., "local"
export VG_REVIEW_MODE="<chosen>"        # e.g., "full"
export VG_SCANNER="<chosen scanner>"    # e.g., "haiku-only" on Claude, "codex-inline" on Codex
export VG_METHOD="<chosen method>"      # e.g., "spawn" / "manual" / "hybrid"
```

If non-interactive path: echo chosen values to user (`Auto-pinned: env=X, mode=Y, scanner=Z, method=W`) but do NOT prompt.

### Bash (resolve final values + persist + emit telemetry)

```bash
# 1. Defaults (if AI did not export — non-interactive or skipped paths)
detect_vg_runtime() {
  case "${VG_RUNTIME:-${VG_PROVIDER:-}}" in
    claude|claude-*) echo "claude"; return ;;
    codex|codex-*) echo "codex"; return ;;
  esac
  if [ -n "${CLAUDE_SESSION_ID:-}" ] || [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] || [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    echo "claude"
    return
  fi
  if [ -n "${CODEX_SANDBOX:-}" ] || [ -n "${CODEX_CLI_SANDBOX:-}" ] || [ -n "${CODEX_HOME:-}" ]; then
    echo "codex"
    return
  fi
  echo "claude"  # Preserve Claude/Haiku path unless Codex is explicit.
}
VG_RUNTIME="$(detect_vg_runtime)"
export VG_RUNTIME

: "${VG_ENV:=${CONFIG_STEP_ENV_VERIFY:-local}}"
: "${VG_REVIEW_MODE:=${REVIEW_MODE:-full}}"
if [ -z "${VG_SCANNER+x}" ]; then
  case "$VG_RUNTIME" in
    codex|codex-*) VG_SCANNER="codex-inline" ;;
    *) VG_SCANNER="haiku-only" ;;
  esac
fi
: "${VG_METHOD:=spawn}"

# 2. CLI flag override (still applies even if AI exported — explicit beats prompt)
if [[ "$ARGUMENTS" =~ --target-env=([a-z]+) ]]; then VG_ENV="${BASH_REMATCH[1]}"; fi
if [[ "$ARGUMENTS" =~ --sandbox ]]; then VG_ENV="sandbox"; fi
if [[ "$ARGUMENTS" =~ --local ]]; then VG_ENV="local"; fi
if [[ "$ARGUMENTS" =~ --staging ]]; then VG_ENV="staging"; fi
if [[ "$ARGUMENTS" =~ --prod ]]; then VG_ENV="prod"; fi
if [[ "$ARGUMENTS" =~ --mode=([a-z-]+) ]]; then VG_REVIEW_MODE="${BASH_REMATCH[1]}"; fi
if [[ "$ARGUMENTS" =~ --scanner=([a-z-]+) ]]; then VG_SCANNER="${BASH_REMATCH[1]}"; fi
if [[ "$ARGUMENTS" =~ --method=([a-z]+) ]]; then VG_METHOD="${BASH_REMATCH[1]}"; fi

# 2b. v2.43.4 — coerce method when scanner=haiku-only (Haiku spawns via Task,
# manual/hybrid don't apply). Echo correction so user sees what happened.
if [ "$VG_SCANNER" = "haiku-only" ] && [ "$VG_METHOD" != "spawn" ]; then
  echo "ℹ Method '${VG_METHOD}' không áp dụng cho scanner=haiku-only (Haiku qua Task tool internal). Coerce method=spawn."
  VG_METHOD="spawn"
fi
if [ "$VG_SCANNER" = "codex-inline" ] && [ "$VG_METHOD" != "spawn" ]; then
  echo "ℹ Method '${VG_METHOD}' không áp dụng cho scanner=codex-inline (Codex main orchestrator owns MCP/browser). Coerce method=spawn."
  VG_METHOD="spawn"
fi

export VG_ENV VG_REVIEW_MODE VG_SCANNER VG_METHOD

# 3. Backward-compat: existing code reads ENV_NAME / REVIEW_MODE
ENV_NAME="$VG_ENV"
REVIEW_MODE="$VG_REVIEW_MODE"
export ENV_NAME REVIEW_MODE

# 4. Validate env exists in config (warn if not configured)
if ! grep -qE "^[[:space:]]*${VG_ENV}:" .claude/vg.config.md 2>/dev/null; then
  echo "⚠ Env '${VG_ENV}' không có trong vg.config.md — có thể fail ở deploy/auth steps." >&2
  echo "   Available envs (môi trường khả dụng): $(grep -oE '^  (local|sandbox|staging|prod):' .claude/vg.config.md | tr -d ' :' | tr '\n' ' ')" >&2
fi

# 5. Validate mode is recognized
case "$VG_REVIEW_MODE" in
  full|delta|regression|schema-verify|link-check|infra-smoke) ;;
  *)
    echo "⚠ Mode '${VG_REVIEW_MODE}' không hợp lệ — fall back về 'full'." >&2
    VG_REVIEW_MODE="full"
    REVIEW_MODE="full"
    export VG_REVIEW_MODE REVIEW_MODE
    ;;
esac

# 5b. Validate scanner is recognized
case "$VG_SCANNER" in
  haiku-only|codex-inline|codex-supplement|gemini-supplement|council-all) ;;
  *)
    echo "⚠ Scanner '${VG_SCANNER}' không hợp lệ — fall back theo runtime." >&2
    case "$VG_RUNTIME" in
      codex|codex-*) VG_SCANNER="codex-inline" ;;
      *) VG_SCANNER="haiku-only" ;;
    esac
    export VG_SCANNER
    ;;
esac

# 5c. v2.43.4 — validate method
case "$VG_METHOD" in
  spawn|manual|hybrid) ;;
  *)
    echo "⚠ Method '${VG_METHOD}' không hợp lệ — fall back về 'spawn'." >&2
    VG_METHOD="spawn"
    export VG_METHOD
    ;;
esac

if [ -n "${FORCE_RERUN:-}" ] && [ "$VG_REVIEW_MODE" != "full" ]; then
  echo "⛔ --force requires full review mode after env gate. Current mode=${VG_REVIEW_MODE}." >&2
  echo "   Re-run với --mode=full --force nếu muốn ép scan lại từ đầu." >&2
  exit 1
fi

# 6. Display banner — user-visible confirmation of what's about to run
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  /vg:review configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase:    ${PHASE_NUMBER} (profile=${PHASE_PROFILE})"
echo "  Env:      ${VG_ENV}"
echo "  Mode:     ${VG_REVIEW_MODE}"
echo "  Scanner:  ${VG_SCANNER}"
echo "  Method:   ${VG_METHOD}    # spawn=auto subprocess / manual=paste prompt / hybrid"
echo "  Runtime:  ${VG_RUNTIME}"
echo "  Args:     ${ARGUMENTS}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 7. Persist to PIPELINE-STATE.json — audit trail
${PYTHON_BIN} -c "
import json
from pathlib import Path
import datetime
p = Path('${PHASE_DIR}/PIPELINE-STATE.json')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
steps = s.setdefault('steps', {})
review = steps.setdefault('review', {})
review['env'] = '${VG_ENV}'
review['mode'] = '${VG_REVIEW_MODE}'
review['scanner'] = '${VG_SCANNER}'
review['method'] = '${VG_METHOD}'
review['runtime'] = '${VG_RUNTIME}'
review['profile'] = '${PHASE_PROFILE}'
review['last_invoked_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
review['last_args'] = '''${ARGUMENTS}'''[:500]
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

# 8. Emit telemetry — orchestrator gates on this event.
# v2.47.1 (Issue #83) — emit-event signature: event_type is positional;
# --phase/--command are NOT valid args (orchestrator infers phase from
# active run; command is recorded by run-start). Valid --actor enum:
# orchestrator | hook | validator | llm-claimed | user. The literal
# "skill" is rejected by argparse, silently failing the call when stderr
# is redirected via 2>&1 || true. Pre-fix: review.env_mode_confirmed
# events never recorded. Phase + command moved into payload JSON.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.env_mode_confirmed" \
  --step "0a_env_mode_gate" \
  --actor "llm-claimed" \
  --outcome "INFO" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"command\":\"vg:review\",\"env\":\"${VG_ENV}\",\"mode\":\"${VG_REVIEW_MODE}\",\"scanner\":\"${VG_SCANNER}\",\"method\":\"${VG_METHOD}\",\"runtime\":\"${VG_RUNTIME}\",\"profile\":\"${PHASE_PROFILE}\",\"interactive\":$([[ \"$ARGUMENTS\" =~ --non-interactive ]] && echo false || echo true)}" \
  2>/dev/null || true

# 9. Mark step
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "0a_env_mode_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_env_mode_gate.done" 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0a_env_mode_gate 2>/dev/null || true
```

**Downstream impact:**
- Phase 1 / Phase 2 / Phase 2.5 / Phase 3 / Phase 4 all read `$ENV_NAME` and `$REVIEW_MODE` — no further changes needed; they pick up user choice automatically.
- `phaseP_*` profile branches (line 528+) gate on `$REVIEW_MODE` — user can override auto-detected profile mode here.
- `$VG_SCANNER` is recorded into PIPELINE-STATE.json + telemetry. **Banner echoes the choice at start of phase1_code_scan** so user sees the value was honored. `codex-inline` is the Codex-native path: main orchestrator keeps MCP/browser control and writes the same scan artifacts/events without Haiku. **Supplemental CrossAI CLI scan (codex-supplement / gemini-supplement / council-all) is wired in v2.42.2** — a follow-up patch lands the actual `codex exec` / `gemini` / Claude CLI dispatch after primary scan completes, plus merge into RUNTIME-MAP under `crossai_scanner_findings`. v2.42.1 captures the user choice so the data path is in place.
- Re-running `/vg:review <phase>` re-prompts (audit trail accumulates `last_invoked_at` history).
</step>

<step name="0b_goal_coverage_gate">
**ADVISORY GATE (v2.2+) — warn on unbound automated goals, but don't BLOCK at review stage.**

Rationale: tests land in /vg:test (creates .spec.ts with TS-XX markers). Review runs BEFORE /vg:test → first-pass review always fails goal coverage → pipeline deadlock on backend-only phases.

Fix (v2.2+): at review stage = WARN only. At /vg:test + /vg:accept stages = BLOCK (those are the right enforcement points).

```bash
echo ""
echo "━━━ Goal coverage gate (advisory at review) ━━━"
${PYTHON_BIN} .claude/scripts/verify-goal-coverage-phase.py \
  --phase-dir "${PHASE_DIR}" \
  --repo-root "${REPO_ROOT}"
GOAL_RC=$?

if [ "$GOAL_RC" -eq 2 ]; then
  echo ""
  echo "⚠ Goal coverage gap (advisory at review stage — will enforce at /vg:test):"
  echo "   Some automated goals have no TS-XX binding. This is expected if /vg:test"
  echo "   hasn't run yet. Tests will be added there."
  echo ""
  echo "To hard-enforce at review: /vg:review ${PHASE_NUMBER} --strict-goal-coverage"
  if [[ "${ARGUMENTS}" =~ --strict-goal-coverage ]]; then
    echo "⛔ --strict-goal-coverage set — BLOCK at review (legacy v1.14.4 behavior)."
    exit 1
  fi
  # Log advisory to debt register for /vg:test + /vg:accept to enforce
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "review-goal-coverage-advisory" "${PHASE_NUMBER}" "unbound goals expected before /vg:test" "${PHASE_DIR}"
  fi
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "0b_goal_coverage_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0b_goal_coverage_gate.done" 2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0b_goal_coverage_gate 2>/dev/null || true
```
</step>

<step name="0c_telemetry_suggestions">
## Step 0c — Reactive Telemetry Suggestions (v2.5 Phase E)

Read telemetry-generated suggestions (always-pass skip candidates / expensive reorder / override abuse) so orchestrator can surface to user BEFORE running full review pipeline. Purely advisory; never auto-applied. UNQUARANTINABLE validators (security/wave-verify/etc.) are never suggested for skip — closes AI-gaming surface.

```bash
TELEMETRY_ENABLED=$(${PYTHON_BIN:-python3} -c "
import re
in_t=False
for line in open('.claude/vg.config.md', encoding='utf-8'):
    s=line.strip()
    if s.startswith('telemetry:'): in_t=True; continue
    if in_t:
        m=re.match(r'^\s*enabled:\s*(true|false)', line, re.IGNORECASE)
        if m: print(m.group(1).lower()); break
        if line and not line[0].isspace() and ':' in s: break
print('true')
" 2>/dev/null | head -1)

if [ "$TELEMETRY_ENABLED" = "true" ]; then
  SUGGESTIONS=$(${PYTHON_BIN:-python3} .claude/scripts/telemetry-suggest.py \
    --command vg:review 2>/dev/null || echo "")
  if [ -n "$SUGGESTIONS" ]; then
    COUNT=$(echo "$SUGGESTIONS" | grep -c '^{' || echo 0)
    if [ "${COUNT:-0}" -gt 0 ]; then
      echo "▸ Telemetry suggestions (${COUNT}, advisory only — skip-security NEVER suggested):"
      echo "$SUGGESTIONS" | head -5 | ${PYTHON_BIN:-python3} -c "
import json, sys
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        d=json.loads(line)
        t=d.get('type','?')
        if t=='skip':
            print(f\"  [skip] {d.get('validator','?')} — {d.get('pass_rate',0):.0%} pass ({d.get('samples',0)} samples)\")
        elif t=='reorder':
            print(f\"  [reorder-late] {d.get('validator','?')} — p95={d.get('p95_ms',0)}ms\")
        elif t=='override_abuse':
            print(f\"  [override-abuse] {d.get('flag','?')} used {d.get('count_30d',0)}x/30d — gate may need tuning\")
    except Exception: pass
" 2>/dev/null
      echo "  (apply: /vg:telemetry --apply <id>; full list: /vg:telemetry --suggest)"
    fi
  fi
fi
touch "${PHASE_DIR}/.step-markers/0c_telemetry_suggestions.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0c_telemetry_suggestions 2>/dev/null || true
```
</step>

<step name="create_task_tracker">
**Project the harness tasklist contract into native task UI.**

Per TASKLIST_POLICY, the tasklist shown by `emit-tasklist.py` is a binding contract, not advisory text. Before running Phase 1, do all of this:

1. Read `.vg/runs/{run_id}/tasklist-contract.json` from the current run.
2. Project every contract item to native task UI:
   - Claude CLI: `TodoWrite` replaces the whole tasklist with one item per
     checklist group, then updates the
     same list as steps move active/completed. `TaskCreate`/`TaskUpdate` is
     acceptable only when that runtime exposes those native task tools.
   - Codex CLI: use Codex native tasklist/plan UI with the same item ids, then update items as steps move active/completed.
3. Bind the projection to orchestrator telemetry:
   ```bash
   "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator tasklist-projected --adapter claude
   # Codex runtime uses: --adapter codex
   # Runtime with no native task UI uses: --adapter fallback
   ```
4. Also write this compact step plan in your text output before starting phase 1 so the message stream is readable:
   ```
   ## ━━━ /vg:review step plan ━━━
   1a:   Contract verify (grep BE routes vs contracts)
   1b:   Element inventory (count UI elements per file)
   1.5:  Graphify ripple analysis (cross-module callers)
   2a:   Deploy + preflight (to {ENV}, health check)
   2a.5: API Docs + API contract precheck (BE -> FE reference + live route probe)
   2b-1: Navigator discovers views (Haiku scanning sidebar)
   2b-2: Haiku scanners per view (N parallel agents)
   2b-3: Merge + evaluate scan results
   2c:   Runtime lens dispatch (plugins: enrich, CRUD/RCRURD, filter, paging, sort, search, URL-state, visual)
   2d:   API error-message runtime lens (API body message -> visible toast/form error)
   2e:   Findings pipeline (merge, adversarial challenge, auto-fix routing)
   3:    Fix loop (max 3 iterations)
   4a:   Load goals + filter infra deps
   4b:   Map goals to RUNTIME-MAP
   4c:   Weighted gate evaluation
   4d:   Write GOAL-COVERAGE-MATRIX
   post: Unreachable triage → CrossAI review → artifacts → reflection
   ```
5. Before each major step/sub-step runs, update the native task item to active, call `vg-orchestrator step-active <step_name>`, then narrate: `## ━━━ Running 2b-2: Scanning /conversions as advertiser (3/7 views) ━━━`.
6. After each sub-step: write its marker, call `vg-orchestrator mark-step review <step_name>`, then update the native task item to completed.

**Dynamic header examples** (concrete values in headers, not in stale task items):
- `## ━━━ 2b-2: Scanning /conversions as advertiser (3/7 views) ━━━`
- `## ━━━ 3: Fixing Bug #2: S2SSecretSection crash (iter 1/3) ━━━`
- `## ━━━ 4a: 38 goals loaded, 16 INFRA_PENDING (ClickHouse, pixel_server) ━━━`
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

# Materialize the profile-aware checklist/plugin contract early. Full web runs
# refresh it after RUNTIME-MAP discovery, but backend-only/CLI/library and
# non-full modes still need a REVIEW-LENS-PLAN artifact and task contract.
LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --write >/dev/null 2>&1 || {
      echo "⛔ Review checklist/lens plan generation failed for profile=${PROFILE:-${CONFIG_PROFILE:-web-fullstack}} mode=${REVIEW_MODE:-full}" >&2
      exit 1
    }
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_plan_generated" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"platform\":\"${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}\",\"phase_profile\":\"${PHASE_PROFILE:-unknown}\",\"mode\":\"${REVIEW_MODE:-full}\",\"artifact\":\"REVIEW-LENS-PLAN.json\"}" \
    >/dev/null 2>&1 || true
else
  echo "⛔ Missing review lens planner: $LENS_PLAN_SCRIPT" >&2
  exit 1
fi
```

**Dispatcher rule:** Orchestrator runs EXACTLY ONE of: `phaseP_infra_smoke` | `phaseP_delta` | `phaseP_regression` | `phaseP_schema_verify` | `phaseP_link_check` | classic `phase1_code_scan → phase4_goal_comparison`. Infra-smoke etc. write `GOAL-COVERAGE-MATRIX.md` directly (implicit goals from SPECS), skip browser + RUNTIME-MAP entirely.
</step>

<step name="phaseP_infra_smoke" profile="web-fullstack,web-backend-only,cli-tool,library" mode="infra-smoke">
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
from datetime import datetime, timezone
results = json.load(open(sys.argv[1], encoding='utf-8'))['results']
out_path = sys.argv[2]
phase = sys.argv[3]
profile = sys.argv[4]
lines = [
    f"# Goal Coverage Matrix — Phase {phase}",
    "",
    f"**Profile:** {profile}  ",
    f"**Source:** SPECS.success_criteria (implicit goals)  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
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
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_infra_smoke" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_infra_smoke.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_infra_smoke 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Infra-smoke checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_infra_smoke_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  # Exit review early — subsequent steps (browser, goal comparison) N/A for infra profile.
  exit 0
fi
```
</step>

<step name="phaseP_delta" mode="delta">
## Review mode: delta (P5, v1.9.2 — OHOK Batch 2 B5: real verification)

**Runs when `REVIEW_MODE=delta` (hotfix profile).**

**Previous behavior (performative):** wrote "Verdict: PASS" stub without actually verifying hotfix touches parent failures. Hotfix could ship completely untested. OHOK Batch 2 B5 replaces stub with per-goal verification loop.

Logic: hotfix patches a parent phase. Review MUST:
- (a) Find parent's failed/blocked goals in GOAL-COVERAGE-MATRIX
- (b) For each failed goal, check if hotfix commits touch files that were implicated in the failure (via commit paths ∩ parent phase commits for that goal)
- (c) Fail build if any critical failed goal is NOT covered by hotfix delta — ship would regress

```bash
if [ "$REVIEW_MODE" != "delta" ]; then
  echo "↷ Skipping phaseP_delta (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Resolve parent phase
  PARENT_REF=$(grep -E '^\*\*Parent phase:\*\*|^parent_phase:' "$PHASE_DIR/SPECS.md" 2>/dev/null | \
               sed -E 's/.*(Parent phase:\*\*|parent_phase:)\s*//' | awk '{print $1}' | head -1)
  if [ -z "$PARENT_REF" ]; then
    echo "⛔ Hotfix profile but no parent_phase in SPECS.md — cannot derive delta context" >&2
    exit 1
  fi
  PARENT_DIR=$(ls -d "${PHASES_DIR}/${PARENT_REF}"* 2>/dev/null | head -1)
  if [ -z "$PARENT_DIR" ]; then
    echo "⛔ Parent phase dir not found for ref '${PARENT_REF}'" >&2
    exit 1
  fi
  PARENT_MATRIX="${PARENT_DIR}/GOAL-COVERAGE-MATRIX.md"
  echo "▸ Delta review: parent=${PARENT_REF} → ${PARENT_DIR}"

  # 2. Extract parent failed/blocked goals (actionable subset — UNREACHABLE/INFRA_PENDING
  #    are parent-domain issues hotfix can't resolve, exclude from coverage gate)
  FAILED_GOALS=""
  if [ -f "$PARENT_MATRIX" ]; then
    FAILED_GOALS=$(grep -E '\|[[:space:]]*(BLOCKED|FAILED)[[:space:]]*\|' "$PARENT_MATRIX" | \
                   grep -oE 'G-[0-9]+' | sort -u)
    FAILED_COUNT=$([ -z "$FAILED_GOALS" ] && echo 0 || echo "$FAILED_GOALS" | wc -l | tr -d ' ')
    echo "▸ Parent BLOCKED/FAILED goals (${FAILED_COUNT}): $(echo $FAILED_GOALS | tr '\n' ' ')"
  else
    echo "⚠ Parent has no GOAL-COVERAGE-MATRIX — cannot verify delta coverage"
    FAILED_COUNT=0
  fi

  # 3. Extract delta files (changes made in THIS phase — current commits only)
  PHASE_COMMITS=$(git log --format=%H -- "${PHASE_DIR}" 2>/dev/null | head -1)
  BASELINE_SHA=$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD 2>/dev/null)
  DELTA_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
                'apps/**/src/**' 'packages/**/src/**' 'infra/**' 2>/dev/null | sort -u)
  DELTA_COUNT=$([ -z "$DELTA_FILES" ] && echo 0 || echo "$DELTA_FILES" | wc -l | tr -d ' ')

  if [ "$DELTA_COUNT" -eq 0 ]; then
    echo "⛔ Hotfix phase has 0 code files changed (apps/**/src|packages/**/src|infra/**)" >&2
    echo "   Hotfix must modify at least 1 code file to be meaningful." >&2
    echo "   Override: --allow-empty-hotfix (log to override-debt)" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-empty-hotfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "phaseP-delta-empty-hotfix" "${PHASE_NUMBER}" "hotfix has no code delta" "${PHASE_DIR}"
  fi

  # 4. For each failed goal, check if delta files overlap with files parent modified
  #    when the goal was recorded as failing. Proxy: grep parent commits mentioning G-XX
  #    for file paths, check intersection with DELTA_FILES.
  COVERAGE_JSON="${PHASE_DIR}/.delta-coverage.json"
  ${PYTHON_BIN} - "$PARENT_DIR" "$PHASE_DIR" "$COVERAGE_JSON" "$PARENT_REF" <<'PY' || true
import json, re, subprocess, sys
from pathlib import Path

parent_dir, phase_dir, out_path, parent_ref = sys.argv[1:5]
matrix = Path(parent_dir) / "GOAL-COVERAGE-MATRIX.md"

failed = []
if matrix.exists():
    for line in matrix.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r'\|\s*(G-\d+)\s*\|.*\|\s*(BLOCKED|FAILED)\s*\|', line)
        if m:
            failed.append(m.group(1))

# Delta files (current hotfix phase)
try:
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD",
         "--", "apps/**/src/**", "packages/**/src/**", "infra/**"],
        capture_output=True, text=True, timeout=10,
    )
    delta_files = set(f.strip() for f in r.stdout.splitlines() if f.strip())
except Exception:
    delta_files = set()

# Per-goal overlap (CrossAI R6 fix).
# Previously: one global parent file set → any touched parent file false-PASSes
# every failed goal. Now: for each failed goal, find files in parent commits
# that cite that goal_id, compute overlap per-goal.
def _files_for_goal(goal_id: str) -> set[str]:
    """Files changed in parent commits whose message cites `goal_id`.

    Proxy for "files involved in this goal's implementation/failure". Limits
    by default to code paths. Falls back to empty set if grep yields nothing
    (goal may have no associated commit — e.g., goal added but never worked on).
    """
    try:
        r = subprocess.run(
            ["git", "log", f"--grep={goal_id}", "--name-only", "--format=",
             "--", str(parent_dir), "apps", "packages", "infra"],
            capture_output=True, text=True, timeout=10,
        )
        return {
            ln.strip() for ln in r.stdout.splitlines()
            if ln.strip() and any(
                ln.startswith(p) for p in ("apps/", "packages/", "infra/")
            )
        }
    except Exception:
        return set()

per_goal: dict[str, dict] = {}
parent_files: set[str] = set()
goals_covered = 0
goals_orthogonal = 0

for g in failed:
    gf = _files_for_goal(g)
    parent_files |= gf
    ovl = sorted(gf & delta_files)
    covered = bool(ovl)
    if covered:
        goals_covered += 1
    elif gf:
        # Goal has known files but none overlap with delta — orthogonal
        goals_orthogonal += 1
    per_goal[g] = {
        "parent_files": sorted(gf),
        "parent_files_count": len(gf),
        "overlap_files": ovl,
        "overlap_count": len(ovl),
        "covered": covered,
        "has_goal_commits": bool(gf),
    }

overlap = sorted(parent_files & delta_files)
coverage_pct = (len(overlap) / len(parent_files) * 100) if parent_files else 0

out = {
    "parent_ref": parent_ref,
    "failed_goals": failed,
    "parent_files_count": len(parent_files),
    "delta_files_count": len(delta_files),
    "overlap_files": overlap,
    "overlap_count": len(overlap),
    "coverage_pct_of_parent": round(coverage_pct, 1),
    "per_goal": per_goal,
    "goals_covered": goals_covered,
    "goals_orthogonal": goals_orthogonal,
    "goals_no_commits": sum(1 for d in per_goal.values() if not d["has_goal_commits"]),
}
Path(out_path).write_text(json.dumps(out, indent=2))
print(f"✓ delta coverage: {goals_covered}/{len(failed)} failed goals have file overlap "
      f"({goals_orthogonal} orthogonal, {out['goals_no_commits']} unmapped); "
      f"total overlap {len(overlap)}/{len(parent_files)} files")
PY

  # 5. Gate: per-goal coverage (CrossAI R6 fix).
  # Previously: one global overlap → any touched parent file false-PASSed every
  # goal. Now: each failed goal evaluated independently. Block if ANY failed
  # goal with known commits has zero overlap with delta.
  GOALS_COVERED=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_covered',0))" 2>/dev/null || echo 0)
  GOALS_ORTHOGONAL=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_orthogonal',0))" 2>/dev/null || echo 0)
  GOALS_UNMAPPED=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}')).get('goals_no_commits',0))" 2>/dev/null || echo 0)

  if [ "${FAILED_COUNT:-0}" -gt 0 ] && [ "${GOALS_ORTHOGONAL:-0}" -gt 0 ]; then
    echo "⛔ ${GOALS_ORTHOGONAL} of ${FAILED_COUNT} failed parent goal(s) have known commits but delta touches NONE of their files." >&2
    echo "   Covered:   ${GOALS_COVERED}/${FAILED_COUNT}" >&2
    echo "   Orthogonal: ${GOALS_ORTHOGONAL}/${FAILED_COUNT} ← hotfix does not address these" >&2
    echo "   Unmapped:  ${GOALS_UNMAPPED}/${FAILED_COUNT} (no parent commits cite these goals)" >&2
    echo "   Delta files: ${DELTA_COUNT}" >&2
    echo "   Options:" >&2
    echo "     (a) Ensure hotfix edits files involved in each failed goal" >&2
    echo "     (b) /vg:scope ${PHASE_NUMBER} — re-scope if truly unrelated" >&2
    echo "     (c) --allow-orthogonal-hotfix override (debt logged, hotfix ships without per-goal coverage)" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    # v2.6.1 (2026-04-26): fix arg-ordering bug — was passing flag-as-step,
    # phase-dir-as-reason, missing gate_id. Function signature is:
    # log_override_debt FLAG PHASE STEP REASON [GATE_ID]
    # gate_id="review-goal-coverage" enables auto-resolve when next phase
    # review goal-coverage validator passes clean.
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-orthogonal-hotfix" "${PHASE_NUMBER}" "review.goal-coverage" \
        "${GOALS_ORTHOGONAL}/${FAILED_COUNT} failed goals uncovered per-goal — hotfix delta orthogonal to failed goals" \
        "review-goal-coverage"
  fi

  # Preserve legacy OVERLAP_COUNT var for downstream consumers
  OVERLAP_COUNT=$("${PYTHON_BIN}" -c "import json; print(json.load(open('${COVERAGE_JSON}'))['overlap_count'])" 2>/dev/null || echo 0)

  # 6. Write matrix with actual per-goal delta-overlap status
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$PARENT_REF" "$COVERAGE_JSON" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

out_path, phase, parent_ref, cov_json = sys.argv[1:5]
cov = json.loads(Path(cov_json).read_text(encoding="utf-8")) if Path(cov_json).exists() else {}

failed = cov.get("failed_goals", [])
overlap = cov.get("overlap_files", [])
delta_count = cov.get("delta_files_count", 0)
parent_files_count = cov.get("parent_files_count", 0)
coverage_pct = cov.get("coverage_pct_of_parent", 0)
per_goal = cov.get("per_goal", {})
goals_covered = cov.get("goals_covered", 0)
goals_orthogonal = cov.get("goals_orthogonal", 0)
goals_no_commits = cov.get("goals_no_commits", 0)

# Decide verdict using PER-GOAL coverage (CrossAI R6 fix).
# Previously: any global overlap = PASS for all goals. Now: goals tracked
# individually. BLOCK if any failed goal with known commits has no per-goal
# overlap with delta.
if failed and goals_orthogonal > 0:
    verdict = (f"BLOCK ({goals_orthogonal}/{len(failed)} failed goals orthogonal — "
               f"hotfix doesn't touch their files)")
elif failed and goals_covered == 0 and goals_no_commits == len(failed):
    verdict = (f"FLAG (all {len(failed)} failed goals have no parent commits — "
               f"cannot verify per-goal coverage; /vg:test must re-verify each)")
elif failed and goals_covered > 0:
    verdict = (f"PASS ({goals_covered}/{len(failed)} failed goals have file overlap; "
               f"{goals_no_commits} unmapped deferred to /vg:test)")
elif not failed:
    verdict = "PASS (parent had no failed goals; delta review defers full goal re-check to /vg:test)"
else:
    verdict = "PASS (no parent matrix found; /vg:test will handle regression)"

lines = [
    f"# Goal Coverage Matrix — Phase {phase} (hotfix delta)",
    "",
    f"**Profile:** hotfix  ",
    f"**Parent phase:** {parent_ref}  ",
    f"**Source:** parent GOAL-COVERAGE-MATRIX + git delta vs HEAD~1  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
    "",
    "## Parent failed goals (per-goal overlap)",
    "",
]
if failed:
    lines.append("| Goal | Status | Parent files | Overlap | Verdict |")
    lines.append("|------|--------|--------------|---------|---------|")
    for g in failed:
        pg = per_goal.get(g, {})
        pf_count = pg.get("parent_files_count", 0)
        ov_count = pg.get("overlap_count", 0)
        if pg.get("covered"):
            mark = f"COVERED ({ov_count}/{pf_count})"
        elif pg.get("has_goal_commits"):
            mark = f"ORTHOGONAL (0/{pf_count})"
        else:
            mark = "UNMAPPED (no parent commits cite goal)"
        lines.append(f"| {g} | BLOCKED/FAILED (parent) | {pf_count} | {ov_count} | {mark} |")
else:
    lines.append("_no parent failed/blocked goals found_")
lines += [
    "",
    "## Delta changes",
    "",
    f"**Files changed (code paths):** {delta_count}",
    f"**Overlap with parent files:** {len(overlap)}/{parent_files_count} ({coverage_pct:.1f}%)",
    "",
]
if overlap:
    lines.append("Sample overlapping files:")
    for f in overlap[:10]:
        lines.append(f"- `{f}`")
lines += [
    "",
    "## Gate",
    "",
    f"**Verdict:** {verdict}",
    "",
]
Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f"✓ GOAL-COVERAGE-MATRIX.md written — verdict: {verdict.split(' (')[0]}")
PY

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_delta" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_delta.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_delta 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.phaseP_delta_verified" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"parent\":\"${PARENT_REF}\",\"overlap_count\":${OVERLAP_COUNT:-0},\"failed_count\":${FAILED_COUNT:-0}}" >/dev/null 2>&1 || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Delta checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_delta_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  exit 0
fi
```
</step>

<step name="phaseP_regression" mode="regression">
## Review mode: regression (P5, v1.9.2 — bugfix profile, OHOK Batch 2 B5: real verification)

**Runs when `REVIEW_MODE=regression`.**

**Previous behavior (performative):** wrote "Verdict: PASS (regression handled at /vg:test)" stub without verifying (a) issue is referenced, (b) code was actually changed, or (c) regression test exists. Bugfix could ship with empty changeset.

OHOK Batch 2 B5 enforces 3 real checks:
1. Bug reference exists in SPECS (else BLOCK — bugfix must cite issue)
2. Phase has ≥1 code commit (else BLOCK — fix must touch code)
3. Phase introduces ≥1 test file or extends existing test with bug ID reference (else WARN — logged but doesn't block; /vg:test will discover gap if test truly missing)

```bash
if [ "$REVIEW_MODE" != "regression" ]; then
  echo "↷ Skipping phaseP_regression (REVIEW_MODE=$REVIEW_MODE)"
else
  # 1. Extract bug reference — MUST exist
  BUG_REF=$(grep -E '^\*\*issue_id\*\*:|^issue_id:|^\*\*bug_ref\*\*:|^bug_ref:|^\*\*Fixes bug\*\*:' \
            "$PHASE_DIR/SPECS.md" 2>/dev/null | sed -E 's/.*://; s/^\s*//' | head -1)
  if [ -z "$BUG_REF" ]; then
    echo "⛔ Bugfix profile requires issue_id/bug_ref in SPECS.md — no reference found" >&2
    echo "   Add to SPECS frontmatter: issue_id: JIRA-123" >&2
    echo "   or body: **Fixes bug**: GH#456" >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    # v2.6.1 (2026-04-26): correct API call (FLAG PHASE STEP REASON GATE_ID)
    # gate_id="bugfix-bugref-required" enables auto-resolve when next review
    # finds the bugref later added.
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-no-bugref" "${PHASE_NUMBER}" "review.bugref-check" \
        "bugfix without issue_id — SPECS frontmatter missing issue_id/bug_ref/Fixes bug" \
        "bugfix-bugref-required"
    BUG_REF="<unspecified>"
  fi
  echo "▸ Regression review (bugfix): issue_ref=${BUG_REF}"

  # 2. Phase must have ≥1 code commit — empty bugfix is meaningless
  BASELINE_SHA=$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD 2>/dev/null)
  CODE_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               'apps/**/src/**' 'packages/**/src/**' 'infra/**' 2>/dev/null | sort -u)
  CODE_COUNT=$([ -z "$CODE_FILES" ] && echo 0 || echo "$CODE_FILES" | wc -l | tr -d ' ')

  if [ "$CODE_COUNT" -eq 0 ]; then
    echo "⛔ Bugfix phase has 0 code files changed in apps|packages|infra" >&2
    echo "   Bugfix must modify at least 1 production file." >&2
    if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
      exit 1
    fi
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    # v2.6.1 (2026-04-26): correct API call (FLAG PHASE STEP REASON GATE_ID)
    # gate_id="bugfix-code-delta-required" enables auto-resolve when next
    # review finds non-empty code delta in apps|packages|infra.
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "--allow-empty-bugfix" "${PHASE_NUMBER}" "review.code-delta-check" \
        "bugfix has 0 code files changed in apps|packages|infra — no production delta" \
        "bugfix-code-delta-required"
  fi

  # 3. Scan for regression test — WARN if missing (don't block; /vg:test catches real gaps)
  TEST_FILES=$(git diff --name-only "${BASELINE_SHA}" HEAD -- \
               '**/e2e/**/*.spec.ts' '**/__tests__/**' '**/*.test.ts' '**/*.test.js' \
               '**/tests/**/*.py' 2>/dev/null | sort -u)
  TEST_COUNT=$([ -z "$TEST_FILES" ] && echo 0 || echo "$TEST_FILES" | wc -l | tr -d ' ')
  BUG_ID_SAFE=$(echo "$BUG_REF" | grep -oE '[A-Za-z0-9_-]+' | head -1)

  # Look for test file mentioning the bug ID (by name or content)
  TEST_MENTIONS_BUG=0
  if [ -n "$BUG_ID_SAFE" ] && [ "$TEST_COUNT" -gt 0 ]; then
    for f in $TEST_FILES; do
      if [ -f "$f" ]; then
        if grep -qiE "(${BUG_ID_SAFE}|regression|bugfix)" "$f" 2>/dev/null; then
          TEST_MENTIONS_BUG=1
          break
        fi
      fi
    done
  fi

  if [ "$TEST_COUNT" -eq 0 ]; then
    echo "⚠ Bugfix introduces no test files — /vg:test will attempt to generate regression coverage" >&2
    REGRESSION_NOTE="no-test-added (WARN — /vg:test to generate)"
  elif [ "$TEST_MENTIONS_BUG" -eq 0 ]; then
    echo "⚠ Bugfix has ${TEST_COUNT} test files but none reference bug ID '${BUG_ID_SAFE}'" >&2
    REGRESSION_NOTE="test-files-unlinked (WARN — consider adding bug ID comment to test)"
  else
    echo "✓ Bugfix has ${TEST_COUNT} test files, at least one references bug ID" >&2
    REGRESSION_NOTE="test-linked (OK)"
  fi

  # 4. Write matrix with actual verification results
  ${PYTHON_BIN} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "$PHASE_NUMBER" "$BUG_REF" \
    "$CODE_COUNT" "$TEST_COUNT" "$TEST_MENTIONS_BUG" "$REGRESSION_NOTE" <<'PY'
import sys
from datetime import datetime, timezone
out, phase, bug, code_count, test_count, test_mentions, note = sys.argv[1:8]
code_count = int(code_count); test_count = int(test_count); test_mentions = int(test_mentions)

if code_count == 0:
    verdict = "BLOCK (empty bugfix — no code changes)"
elif test_count > 0 and test_mentions:
    verdict = f"PASS (bugfix has {code_count} code files + linked test; /vg:test re-verifies)"
elif test_count > 0:
    verdict = f"PASS-WARN (bugfix has {code_count} code files + {test_count} tests unlinked to bug)"
else:
    verdict = f"PASS-WARN (bugfix has {code_count} code files but 0 tests; /vg:test must generate)"

lines = [
    f"# Goal Coverage Matrix — Phase {phase} (bugfix regression)",
    "",
    f"**Profile:** bugfix  ",
    f"**Bug reference:** {bug}  ",
    f"**Source:** SPECS.md issue_id + git delta vs HEAD~1  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "## Verification checks",
    "",
    "| Check | Status |",
    "|-------|--------|",
    f"| Bug reference present | {'✓' if bug != '<unspecified>' else '⛔ missing'} |",
    f"| Code files changed | {code_count} |",
    f"| Test files changed | {test_count} |",
    f"| Tests reference bug ID | {'✓' if test_mentions else 'no'} |",
    f"| Regression note | {note} |",
    "",
    "## Gate",
    "",
    f"**Verdict:** {verdict}",
    "",
    "**Next:** /vg:test runs issue-specific runner to re-verify bug is actually fixed.",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print(f"✓ GOAL-COVERAGE-MATRIX.md written — {verdict.split(' (')[0]}")
PY

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_regression" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_regression.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_regression 2>/dev/null || true
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.phaseP_regression_verified" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"bug_ref\":\"${BUG_REF}\",\"code_count\":${CODE_COUNT},\"test_count\":${TEST_COUNT},\"test_linked\":${TEST_MENTIONS_BUG}}" >/dev/null 2>&1 || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Regression checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_regression_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  exit 0
fi
```
</step>

<step name="phaseP_schema_verify" mode="schema-verify">
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
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (migration schema-verify)",
    "",
    "**Profile:** migration  ",
    "**Source:** SPECS.migration_plan + ROLLBACK.md  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
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
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_schema_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_schema_verify.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_schema_verify 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Schema-verify checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_schema_verify_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  exit 0
fi
```
</step>

<step name="phaseP_link_check" mode="link-check">
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
from datetime import datetime, timezone
out, phase = sys.argv[1], sys.argv[2]
lines = [
    f"# Goal Coverage Matrix — Phase {phase} (docs link-check)",
    "",
    "**Profile:** docs  ",
    f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    "",
    "Docs-only phase — link-check performed; content fidelity deferred to /vg:test markdown-lint.",
    "",
    "**Verdict:** PASS",
    "",
]
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print("✓ GOAL-COVERAGE-MATRIX.md written (docs link-check)")
PY
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phaseP_link_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phaseP_link_check.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phaseP_link_check 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  if [ -f "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/review-lens-plan.py" \
      --phase-dir "$PHASE_DIR" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" --mode "$REVIEW_MODE" \
      --write --validate-only --json > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1 || {
        echo "⛔ Link-check checklist evidence missing — see ${PHASE_DIR}/.tmp/review-lens-plan-validation.json" >&2
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.phaseP_link_check_lens_plan" \
            --phase-dir "$PHASE_DIR" \
            --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
            --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
        fi
        exit 1
      }
  fi
  exit 0
fi
```
</step>

<step name="phase1_code_scan" mode="full">
## Phase 0.5: RFC v9 preflight (data invariants + RCRURD + cache hygiene)

**RFC v9 PR-D1/D2/F integration.** Runs deterministic gates BEFORE the
scanner so we fail fast on broken sandbox state instead of burning Haiku
tokens on a doomed scan.

```bash
# RFC v9 preflight — Codex-HIGH-5-ter fix: outer guard checks scripts/runtime
# only. The inner gates check their own artifacts (ENV-CONTRACT.md for
# invariants, FIXTURES/ for RCRURD). Previously the outer guard required
# BOTH scripts/runtime AND ENV-CONTRACT, so a phase with FIXTURES+lifecycle
# but no ENV-CONTRACT skipped RCRURD entirely.
PRE_OK=1
VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
[ -d "${VG_SCRIPT_ROOT}/runtime" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
if [ -d "${VG_SCRIPT_ROOT}/runtime" ]; then
  RFC_V9_GATE_RAN=0
  # Only echo the banner once when at least one gate has work to do
  HAS_INVARIANTS_FILE=0
  HAS_FIXTURES_DIR=0
  [ -f "${PHASE_DIR}/ENV-CONTRACT.md" ] && HAS_INVARIANTS_FILE=1
  [ -d "${PHASE_DIR}/FIXTURES" ] && HAS_FIXTURES_DIR=1
  if [ "$HAS_INVARIANTS_FILE" = "1" ] || [ "$HAS_FIXTURES_DIR" = "1" ]; then
    echo ""
    echo "━━━ Phase 0.5 — RFC v9 preflight ━━━"

    # 1. Reap expired leases + orphans (PR-F) — only if FIXTURES exist
    if [ "$HAS_FIXTURES_DIR" = "1" ] && [ -f "${VG_SCRIPT_ROOT}/fixture-prune.py" ]; then
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/fixture-prune.py" \
        --phase "$PHASE_NUMBER" --apply --skip-orphans 2>&1 | sed 's/^/  prune: /'
    fi

    # Codex-HIGH-1-ter fix: delete stale snapshot at entry. Otherwise post
    # mode at run-complete may load a snapshot from a PRIOR run.
    rm -f "${PHASE_DIR}/.rcrurd-pre-snapshot.json" 2>/dev/null || true
  fi  # end OR guard (banner + prune + snapshot reset)

  # 2. data_invariants N-consumer check (PR-C, live HTTP wiring stub-1 fix)
  # Codex-HIGH-5-ter: guarded by ENV-CONTRACT.md only — independent of FIXTURES.
  if [ -f "${VG_SCRIPT_ROOT}/preflight-invariants.py" ] && \
     [ -f "${PHASE_DIR}/ENV-CONTRACT.md" ]; then
    # Codex-R4-HIGH-2 fix: PREVIOUSLY parsed step_env.sandbox_test from
    # vg.config.md, but that's an ENV NAME like "local", not a URL. The
    # actual URL lives in ENV-CONTRACT.md under `target.base_url`. Use
    # that as canonical source; fall back to VG_BASE_URL env override.
    PRE_BASE=$("${PYTHON_BIN:-python3}" -c "
import re, sys
text = open('${PHASE_DIR}/ENV-CONTRACT.md', encoding='utf-8').read()
# Match \`target:\n  base_url: \"...\"\` block (handles single+double quotes)
m = re.search(r'^target:\s*\n((?:[ \t].*\n)+)', text, re.MULTILINE)
if m:
    body = m.group(1)
    bm = re.search(r'^\s*base_url:\s*[\"\\']?([^\"\\'\s#]+)', body, re.MULTILINE)
    if bm: print(bm.group(1))
" 2>/dev/null)
    [ -z "$PRE_BASE" ] && PRE_BASE="${VG_BASE_URL:-}"
    if [ -n "$PRE_BASE" ]; then
      PRE_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/preflight-invariants.py" \
        --phase "$PHASE_NUMBER" --base-url "$PRE_BASE" \
        --severity "${VG_PREFLIGHT_SEVERITY:-block}" 2>&1)
      PRE_RC=$?
      echo "  preflight invariants: $(echo "$PRE_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({len(d.get(\"gaps\",[]))} gap(s))")
    elif v == "WARN":
        print(f"WARN ({len(d.get(\"gaps\",[]))} gap(s) — VG_PREFLIGHT_SEVERITY=warn override active)")
    elif v == "PASS":
        print(f"PASS (checked {d.get(\"invariants_checked\",\"?\")} invariants)")
    elif v == "DRY_RUN":
        print("DRY_RUN")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
      # Codex-HIGH-5 fix: setup errors (RC=2) ALWAYS block, regardless of
      # severity gate. Missing api_index, bad creds, or missing base_url
      # mean we cannot proceed safely — silent skip would let scan run on
      # broken sandbox state.
      if [ "$PRE_RC" -eq 2 ]; then
        echo "⛔ Phase 0.5 preflight setup error — cannot proceed (RFC v9 PR-C):"
        echo "$PRE_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown setup error\")[:300]}")
except: print("   (could not parse error)")
'
        echo "   Fix path: ENV-CONTRACT.md must declare api_index for every"
        echo "   resource referenced in data_invariants. Verify vg.config.md"
        echo "   credentials_map covers all count_role values."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      if [ "$PRE_RC" -eq 1 ] && [ "${VG_PREFLIGHT_SEVERITY:-block}" = "block" ]; then
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_invariants_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

        source scripts/lib/blocking-gate-prompt.sh
        EVIDENCE_PATH="${PHASE_DIR}/.vg/preflight-invariants-evidence.json"
        mkdir -p "$(dirname "$EVIDENCE_PATH")"
        cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "preflight_invariants",
  "summary": "Phase 0.5 preflight invariants gate BLOCK",
  "fix_hint": "Fix the data invariant gaps reported by the preflight validator. Check fix_hint in each gap entry."
}
JSON
        blocking_gate_prompt_emit "preflight_invariants" "$EVIDENCE_PATH" "error"
        # AI controller calls AskUserQuestion → resolve via Leg 2.
        # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
      fi
    else
      # Codex-HIGH-5-bis fix: missing base_url WAS silent skip — that's
      # the original "RFC v9 silently bypassed" failure mode. If
      # ENV-CONTRACT.md declares data_invariants, missing base_url IS a
      # setup error → block. If no invariants declared, this is a no-op
      # phase and skip is fine.
      HAS_INVARIANTS=$(grep -cE '^\s*data_invariants:' "${PHASE_DIR}/ENV-CONTRACT.md" 2>/dev/null || echo 0)
      if [ "$HAS_INVARIANTS" -gt 0 ] && [ "${VG_PREFLIGHT_SEVERITY:-block}" = "block" ]; then
        echo "⛔ Phase 0.5 preflight setup error — ENV-CONTRACT.md declares"
        echo "   data_invariants but no sandbox base_url found."
        echo "   Fix path: set step_env.sandbox_test in vg.config.md OR"
        echo "             export VG_BASE_URL=https://your-sandbox/."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.preflight_no_base_url" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      echo "  preflight invariants: SKIPPED (no base_url + no data_invariants — no-op)"
    fi
  fi

  # 3. RCRURD pre_state gate (PR-D2, live wiring stub-2 fix)
  # Calls scripts/rcrurd-preflight.py: walks FIXTURES/*.yaml, runs pre_state
  # GET + assert_jsonpath for each lifecycle block. Fail-fast before scan.
  if [ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] && \
     [ -d "${PHASE_DIR}/FIXTURES" ]; then
    PRE_BASE_RC="${PRE_BASE:-${VG_BASE_URL:-}}"
    if [ -n "$PRE_BASE_RC" ]; then
      # Codex-HIGH-1-ter fix: capture snapshot in the SAME pre-mode call
      # (not a follow-up). The snapshot is read by post-mode at run-complete
      # to compute increased_by_at_least deltas against real pre-action state.
      RCRURD_SNAP="${PHASE_DIR}/.rcrurd-pre-snapshot.json"
      RCRURD_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" \
        --phase "$PHASE_NUMBER" --base-url "$PRE_BASE_RC" \
        --severity "${VG_RCRURD_SEVERITY:-block}" \
        --capture-snapshot "$RCRURD_SNAP" 2>&1)
      RCRURD_RC=$?
      echo "  RCRURD pre_state: $(echo "$RCRURD_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed)")
    elif v == "WARN":
        print(f"WARN ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed — VG_RCRURD_SEVERITY=warn override active)")
    elif v == "PASS":
        print(f"PASS (checked {d.get(\"checked\",0)} fixtures)")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
      # Codex-HIGH-5 fix: RCRURD setup errors (RC=2) ALWAYS block.
      if [ "$RCRURD_RC" -eq 2 ]; then
        echo "⛔ Phase 0.5 RCRURD setup error — cannot proceed:"
        echo "$RCRURD_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown setup error\")[:300]}")
except: print("   (could not parse error)")
'
        echo "   Fix path: vg.config.md credentials_map must cover every role"
        echo "   referenced in FIXTURES/{G-XX}.yaml lifecycle.pre_state."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      if [ "$RCRURD_RC" -eq 1 ] && [ "${VG_RCRURD_SEVERITY:-block}" = "block" ]; then
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_preflight_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

        source scripts/lib/blocking-gate-prompt.sh
        EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-preflight-evidence.json"
        mkdir -p "$(dirname "$EVIDENCE_PATH")"
        cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_preflight",
  "summary": "Phase 0.5 RCRURD gate BLOCK — fixture pre_state assertions failed",
  "fix_hint": "Ensure sandbox seed data matches each fixture's lifecycle.pre_state assertions"
}
JSON
        blocking_gate_prompt_emit "rcrurd_preflight" "$EVIDENCE_PATH" "error"
        # AI controller calls AskUserQuestion → resolve via Leg 2.
        # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
      fi

      # Codex-HIGH-1-ter fix: validate snapshot was captured. If pre-mode
      # passed assertions but snapshot file missing, post-mode delta
      # assertions will be wrong. Block if any fixture declares an
      # increased_by_at_least assertion (those NEED snapshot).
      if [ "$RCRURD_RC" -eq 0 ] && [ -d "${PHASE_DIR}/FIXTURES" ]; then
        NEEDS_SNAPSHOT=$(grep -lE 'increased_by_at_least|decreased_by_at_least' \
          "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
        if [ "$NEEDS_SNAPSHOT" -gt 0 ] && [ ! -f "$RCRURD_SNAP" ]; then
          echo "⛔ Phase 0.5 RCRURD setup error — pre-state snapshot not"
          echo "   captured but ${NEEDS_SNAPSHOT} fixture(s) declare delta"
          echo "   assertions (increased_by_at_least / decreased_by_at_least)."
          echo "   Without snapshot, post-mode would compare post-action to"
          echo "   post-action → delta=0 false-fail."
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_snapshot_missing" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
          exit 1
        fi
      fi
    else
      # Codex-HIGH-5-bis: missing base_url + FIXTURES with lifecycle = setup error
      HAS_LIFECYCLE=$(grep -lE '^lifecycle:' "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
      if [ "$HAS_LIFECYCLE" -gt 0 ] && [ "${VG_RCRURD_SEVERITY:-block}" = "block" ]; then
        echo "⛔ Phase 0.5 RCRURD setup error — FIXTURES declare ${HAS_LIFECYCLE}"
        echo "   lifecycle blocks but no sandbox base_url found."
        echo "   Fix path: set step_env.sandbox_test in vg.config.md OR"
        echo "             export VG_BASE_URL=https://your-sandbox/."
        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_no_base_url" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
        exit 1
      fi
      echo "  RCRURD pre_state: SKIPPED (no base_url + no lifecycle — no-op)"
    fi
  fi
fi
```

## Phase 1: CODE SCAN (automated, <10 sec)

**If --skip-scan, skip this phase.**

```bash
# Echo scanner choice from step 0a so user sees their --scanner choice was honored
echo ""
echo "━━━ Phase 1 — Code scan (scanner=${VG_SCANNER:-haiku-only}) ━━━"
case "${VG_SCANNER:-haiku-only}" in
  haiku-only)
    echo "  Mode: Haiku-only — fastest path, default depth."
    ;;
  codex-inline)
    echo "  Mode: Codex inline scanner — main orchestrator owns MCP/browser; no Haiku spawn."
    ;;
  codex-supplement)
    echo "  Mode: Haiku + Codex CLI supplement (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; supplemental Codex scan invocation lands in next iter."
    ;;
  gemini-supplement)
    echo "  Mode: Haiku + Gemini CLI supplement (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; supplemental Gemini scan invocation lands in next iter."
    ;;
  council-all)
    echo "  Mode: Haiku + Codex + Gemini + Claude council (queued for v2.42.2 wiring)."
    echo "  Note: v2.42.1 records the choice; full council scan invocation lands in next iter."
    ;;
esac
echo ""
```

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

### 1d: Override Debt Auto-Resolve (v2.7 Phase M extension)

When phase1_code_scan completes with no scan-driven regression (contract verify
PASS or WARNING-only, i18n missing-keys treated as non-blocking), the 5
Phase-M gate_ids on the supported list can auto-resolve any matching prior
debt entries from earlier phases.

The skip-when-current-phase-also-uses-flag guard mirrors the v2.6.1 accept.md
pattern: never resolve a gate_id whose flag is being used right now.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
if type -t override_auto_resolve_clean_run >/dev/null 2>&1; then
  RESOLUTION_EVENT_ID="review-clean-${PHASE_NUMBER}-$(date -u +%s)"
  if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
    override_auto_resolve_clean_run "allow-orthogonal-hotfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
    override_auto_resolve_clean_run "allow-no-bugref" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-hotfix ]]; then
    override_auto_resolve_clean_run "allow-empty-hotfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
    override_auto_resolve_clean_run "allow-empty-bugfix" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-unresolved-overrides ]]; then
    override_auto_resolve_clean_run "allow-unresolved-overrides" "${PHASE_NUMBER}" \
      "${RESOLUTION_EVENT_ID}" 2>&1 | sed 's/^/  /'
  fi
fi
```

The helper emits one `override.auto_resolved` audit event per gate_id that
matched at least one OPEN debt entry from a prior phase (R9: gate_id +
timestamp + git_sha). No-op when there are no matching entries.
</step>

<step name="phase1_5_ripple_and_god_node" mode="full">
## Phase 1.5: GRAPHIFY IMPACT ANALYSIS (cross-module ripple + god node coupling)

**Purpose**: retroactive safety net for changes that affect callers outside the phase's changed-files list. Complement to /vg:build's proactive caller graph.

**Prereq**: `_shared/config-loader.md` already resolved `$GRAPHIFY_ACTIVE`, `$GRAPHIFY_GRAPH_PATH`, `$PYTHON_BIN`, `$REPO_ROOT`, `$VG_TMP` at command start.

```bash
if [ "$GRAPHIFY_ACTIVE" != "true" ]; then
  echo "ℹ Graphify not available — skipping Phase 1.5"
  echo "RIPPLE_SKIPPED=true" > "${PHASE_DIR}/uat-ripples.txt"
  echo "RIPPLE_SKIP_REASON=graphify-inactive" >> "${PHASE_DIR}/uat-ripples.txt"
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase1_5_ripple_and_god_node" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase1_5_ripple_and_god_node 2>/dev/null || true
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

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase1_5_ripple_and_god_node" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase1_5_ripple_and_god_node.done"`
</step>

<step name="phase2a_api_contract_probe" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2a.5: API CONTRACT PROBE (curl, no browser)

**Mandatory before browser discovery for web feature phases.**

Purpose:
- prove the current run touched the live API surface before any browser scan
- fail fast on broken/stale backend routes instead of hiding the problem behind discovery noise
- create a fresh artifact that runtime_contract can enforce even on older pinned phases
- verify API-DOCS.md fully covers API-CONTRACTS.md so discovery/test use the built API reference, not stale prose

**Scope:** low-cost readiness gate only. This is NOT the full `/vg:test` runtime contract verification and NOT a project-specific mutation batch. Mutating endpoints are probed safely (OPTIONS / existence check), not executed for side effects.

```bash
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔎 Phase 2a.5 — API contract probe"
echo "   Curl API contracts trước browser discovery"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2a_api_contract_probe >/dev/null 2>&1 || true

API_PROBE_OUT="${PHASE_DIR}/api-contract-precheck.txt"
API_DOCS_CHECK_OUT="${PHASE_DIR}/api-docs-check.txt"
VG_SCRIPT_ROOT="${REPO_ROOT:-.}/.claude/scripts"
[ -d "$VG_SCRIPT_ROOT" ] || VG_SCRIPT_ROOT="${REPO_ROOT:-.}/scripts"
PROBE_SCRIPT="${VG_SCRIPT_ROOT}/review-api-contract-probe.py"
INTERFACE_CHECK_OUT="${PHASE_DIR}/.tmp/interface-standards-review.json"

if [ ! -f "$PROBE_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_helper\"}" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — missing helper: $PROBE_SCRIPT",
  "fix_hint": "Ensure review-api-contract-probe.py exists in .claude/scripts/ or scripts/"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
INTERFACE_VAL="${VG_SCRIPT_ROOT}/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_VAL" ]; then
  "${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    > "$INTERFACE_CHECK_OUT" 2>&1
  INTERFACE_RC=$?
  cat "$INTERFACE_CHECK_OUT"
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ Interface standards gate failed — review cannot continue with undefined API/FE error semantics." >&2
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.interface_standards" \
        --phase-dir "$PHASE_DIR" \
        --input "$INTERFACE_CHECK_OUT" \
        --out-md "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/interface-standards-diagnostic.md" 2>/dev/null || true
    fi
    exit 1
  fi
else
  echo "⛔ Interface standards validator missing: $INTERFACE_VAL" >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-api-docs-coverage.py \
  --phase "${PHASE_NUMBER}" \
  > "${API_DOCS_CHECK_OUT}" 2>&1
API_DOCS_RC=$?
cat "${API_DOCS_CHECK_OUT}"
if [ "$API_DOCS_RC" -ne 0 ]; then
  echo "⛔ API docs coverage failed — browser discovery is not allowed to continue with incomplete API-DOCS.md." >&2
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.api_docs_contract_coverage" \
      --phase-dir "$PHASE_DIR" \
      --input "$API_DOCS_CHECK_OUT" \
      --out-md "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/api-docs-diagnostic.md" 2>/dev/null || true
  fi
  exit 1
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
  --path "${PHASE_DIR}/api-docs-check.txt" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,${PHASE_DIR}/API-DOCS.md,.claude/vg.config.md" \
  --producer "vg:review/phase2a_api_contract_probe"
API_DOCS_MANIFEST_RC=$?
if [ "$API_DOCS_MANIFEST_RC" -ne 0 ]; then
  echo "⛔ API docs check wrote report but failed to bind evidence to current run." >&2
  exit 1
fi

# Resolve base URL from the same canonical source used by Phase 0.5 preflight.
API_PROBE_BASE=$("${PYTHON_BIN:-python3}" -c "
import re, sys
path = '${PHASE_DIR}/ENV-CONTRACT.md'
try:
    text = open(path, encoding='utf-8').read()
except OSError:
    sys.exit(0)
m = re.search(r'^target:\\s*\\n((?:[ \\t].*\\n)+)', text, re.MULTILINE)
if m:
    body = m.group(1)
    bm = re.search(r'^\\s*base_url:\\s*[\"\\']?([^\"\\'\\s#]+)', body, re.MULTILINE)
    if bm:
        print(bm.group(1))
" 2>/dev/null)
[ -z "$API_PROBE_BASE" ] && API_PROBE_BASE="${VG_BASE_URL:-}"

if [ -z "$API_PROBE_BASE" ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"missing_base_url\"}" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe setup error — no base_url found in ENV-CONTRACT.md and VG_BASE_URL is empty",
  "fix_hint": "Set target.base_url in ENV-CONTRACT.md or export VG_BASE_URL"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_started" \
  --payload "$(printf '{"phase":"%s","base_url":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}")" >/dev/null 2>&1 || true

PROBE_CMD=("${PYTHON_BIN:-python3}" "$PROBE_SCRIPT"
  --contracts "${PHASE_DIR}/API-CONTRACTS.md"
  --base-url "$API_PROBE_BASE"
  --out "$API_PROBE_OUT")

# Optional auth token from deploy/auth bootstrap. If absent, 401/403 still count
# as route-exists evidence for auth-protected endpoints.
if [ -n "${AUTH_TOKEN:-}" ]; then
  PROBE_CMD+=(--header "Authorization: Bearer ${AUTH_TOKEN}")
fi

"${PROBE_CMD[@]}"
API_PROBE_RC=$?
cat "$API_PROBE_OUT"

if [ "$API_PROBE_RC" -ne 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_blocked" \
    --payload "$(printf '{"phase":"%s","base_url":"%s","rc":%s}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "${API_PROBE_RC}")" >/dev/null 2>&1 || true

  source scripts/lib/blocking-gate-prompt.sh
  EVIDENCE_PATH="${PHASE_DIR}/.vg/api-precheck-evidence.json"
  mkdir -p "$(dirname "$EVIDENCE_PATH")"
  cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "api_precheck",
  "summary": "API contract probe failed — browser discovery is not allowed to start on stale/broken API surface",
  "fix_hint": "Fix the API surface issues found in api-contract-precheck.txt before continuing review"
}
JSON
  blocking_gate_prompt_emit "api_precheck" "$EVIDENCE_PATH" "error"
  # AI controller calls AskUserQuestion → resolve via Leg 2.
  # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
fi

"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/emit-evidence-manifest.py" \
  --path "${PHASE_DIR}/api-contract-precheck.txt" \
  --source-inputs "${PHASE_DIR}/API-CONTRACTS.md,.claude/vg.config.md" \
  --producer "vg:review/phase2a_api_contract_probe"
MANIFEST_RC=$?
if [ "$MANIFEST_RC" -ne 0 ]; then
  echo "⛔ API contract probe wrote report but failed to bind evidence to current run." >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.api_precheck_completed" \
  --payload "$(printf '{"phase":"%s","base_url":"%s","artifact":"%s"}' "${PHASE_NUMBER}" "${API_PROBE_BASE}" "api-contract-precheck.txt")" >/dev/null 2>&1 || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2a_api_contract_probe" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2a_api_contract_probe.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2a_api_contract_probe 2>/dev/null || true
```

</step>

<step name="phase2_browser_discovery" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2: BROWSER DISCOVERY (MCP Playwright — organic)

**🎬 Live narration protocol (tightened 2026-04-17 — user theo dõi flow):**

Orchestrator PHẢI in dòng tiếng người BEFORE mỗi sub-phase + BEFORE mỗi view/goal đang xử lý. Khác test.md: review chạy parallel nhiều Haiku, narration ở orchestrator level không cần per-step.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2_browser_discovery >/dev/null 2>&1 || true
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

  Parse GOAL-COVERAGE-MATRIX.md → collect all goals where status NOT IN (READY, INFRA_PENDING, DEFERRED, MANUAL).
  This includes: BLOCKED, UNREACHABLE, FAILED, PARTIAL, NOT_SCANNED, **and SUSPECTED** (v2.46-wave3.2 — matrix=READY but no submit/2xx evidence; flagged by `verify-matrix-staleness.py` at step 0_parse_and_validate and folded in here).
  If none found → print "All goals already READY. Nothing to retry." → skip to Phase 4.

  Parse RUNTIME-MAP.json → for each failed goal_id:
    start_view = goal_sequences[goal_id].start_view
  RETRY_VIEWS[] = unique(all start_views), with roles from RUNTIME-MAP views[start_view].role

  Print: "Retry mode: {N} failed/suspected goals → {M} views to re-scan: {RETRY_VIEWS[]}"

  Skip Phase 1 (code scan). Skip 2b-0 (seed). Skip 2b-1 (navigator — reuse existing nav-discovery.json).
  Go directly to 2b-2 using RETRY_VIEWS[] as view_assignments (NOT view-assignments.json).

**If --re-scan-goals=G-XX,G-YY,G-ZZ (v2.46-wave3.2):**
  Validate: ${PHASE_DIR}/RUNTIME-MAP.json exists (matrix not required — bypasses status filter).
  Missing → BLOCK: "Run `/vg:review {phase}` first to generate RUNTIME-MAP.json."

  Each goal ID validated already at step 0_parse_and_validate (unknown IDs → exit 1 there).

  Parse RUNTIME-MAP.json → for each goal_id in $RE_SCAN_GOALS:
    start_view = goal_sequences[goal_id].start_view
  RETRY_VIEWS[] = unique(all start_views).

  Print: "Re-scan mode: {N} explicit goals → {M} views: {RETRY_VIEWS[]}"

  Skip Phase 1 + 2b-0 + 2b-1. Go directly to 2b-2 using RETRY_VIEWS[].
  Marker: write `${PHASE_DIR}/.re-scan-goals.txt` with the list (consumed by 2b-3 to scope sequence recording to just these goals).

**If --dogfood (v2.46-wave3.2):**
  Validate: ${PHASE_DIR}/TEST-GOALS.md AND ${PHASE_DIR}/RUNTIME-MAP.json exist.

  Parse TEST-GOALS.md → all goals with non-empty `**Mutation evidence:**` field (see verify-matrix-staleness.py `parse_goals` for parser).
  RE_SCAN_GOALS := comma-join(those goal_ids), then proceed exactly as `--re-scan-goals` branch above.

  Print: "Dogfood mode: re-scanning ALL {N} mutation goals (regardless of matrix status)."

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
  │   proposal for cross-env retry, L3 provider-native prompt if needed.   │
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

  **Semantic fallback (if resolver unavailable — provider-native prompt):**
  - Claude Code: AskUserQuestion.
  - Codex: ask the same options in the main Codex thread / closest input UI.
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
   MCP_PREFIX=$(bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" claim "$SESSION_ID")
   trap "bash '${HOME}/.claude/playwright-locks/playwright-lock.sh' release \"$SESSION_ID\" 2>/dev/null" EXIT INT TERM
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
   8. bash "${HOME}/.claude/playwright-locks/playwright-lock.sh" release "haiku-nav-{phase}-$$"

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

<DEEPSCAN_OPT_IN_GATE_v2.42.4>
**v2.42.4+ refactor — Phase 2b-2 default OFF.**

Per the 3-tier review/test/roam refactor (see `.vg/research/ROAM-RFC-v1.md`
and `PLAN-vgflow-2026-05-01.md` Part D), exhaustive UI exploration moves
to `/vg:roam`. /vg:review keeps light browser smoke (Phase 2b-1 navigator
+ Phase 2b-3 goal recording) for goal-binding verification, but skips
the per-view Haiku exhaustive scan unless explicitly opted in.

**Skip 2b-2 entirely UNLESS one of these holds:**
- `$ARGUMENTS` contains `--with-deepscan`, OR
- `$ARGUMENTS` contains `--full-scan` (legacy alias, kept for backward compat), OR
- Phase profile is mobile-* (mobile uses sequential haiku as primary scan path), OR
- `CONFIG_REVIEW_DEEPSCAN_DEFAULT` is set to `on` in vg.config.md (per-project opt-back-in)

Skip narration:
```
echo "▸ Phase 2b-2 (Haiku per-view exhaustive scan) skipped — v2.42.4 default off."
echo "  Lens-driven exhaustive exploration now lives in /vg:roam (post-test janitor)."
echo "  Pass --with-deepscan to opt back in for this run, or set"
echo "  config.review.deepscan_default=on in vg.config.md for project-wide opt-in."
```

After echoing skip narration, jump directly to phase2b-3 (goal sequence
recording). The MANDATORY_GATE block below applies ONLY when 2b-2 is
gated ON via the conditions above.
</DEEPSCAN_OPT_IN_GATE_v2.42.4>

<MANDATORY_GATE>
**Applies only when 2b-2 is gated ON (--with-deepscan, --full-scan, mobile-*, or config opt-in).**

**You MUST run the provider-native scanner protocol in step 2b-2** (unless spawn_mode=none for cli-tool/library profiles). This is NOT optional.
- Do NOT skip this step because "phase is small" or "I already covered everything in 2b-1"
- Claude Code path: spawn at least 1 Haiku agent per view discovered in 2b-1; the Agent tool with model="haiku" MUST be called.
- Codex path: keep MCP/browser actions in the main Codex orchestrator for `codex-inline`; optionally use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots. Do not ask to spawn Haiku on Codex.
- Required evidence is provider-neutral: `scan-*.json`, RUNTIME-MAP merge, GOAL-COVERAGE-MATRIX impact, and `review.haiku_scanner_spawned` telemetry semantics.
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

**Bootstrap rules injection (v1.15.0+):** Before spawning each Haiku scanner,
render + inject promoted project rules so scanners see project-specific checks
(e.g. "verify data persists after mutation" rule L-050 will fire here):
```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "review")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "review" "${PHASE_NUMBER}"
```
Then in each Haiku prompt body, include:
```
<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>
```
Position: after static `<scanner_workflow>` block, before `<view_assignment>`.
Scanner skill treats rules as additional per-element checks on top of fixed protocol.

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

    # ─── Phase 15 D-17 telemetry (BEFORE spawn, not after) ──────────────
    # Emit `review.haiku_scanner_spawned` IMMEDIATELY before Agent() so the
    # event survives Agent failure / run abort. Validator
    # verify-haiku-spawn-fired.py (Phase 15 T3.11) reads this in events.db
    # to confirm step 2b-2 actually fired for UI-profile phases. Without
    # this, a non-deterministic spawn failure could leave the validator
    # unable to distinguish "spawn never attempted" from "spawn attempted
    # but Agent crashed". Order matters: emit BEFORE Agent call.
    #
    # Parallel mode: emit per-spawn in a serial bash loop, THEN batch all
    # Agent() calls in one tool_use block. Sequential mode: emit
    # immediately before each Agent() call individually.
    Bash:
      ${PYTHON_BIN} .claude/scripts/vg-orchestrator emit-event \
        "review.haiku_scanner_spawned" \
        --step "2b-2" --actor "orchestrator" --outcome "INFO" \
        --payload "$(printf '{"view":"%s","role":"%s","idx":%d,"total":%d,"spawn_mode":"%s"}' \
          "{view.url}" "{role}" "$IDX" "$TOTAL" "$SPAWN_MODE")" \
        2>/dev/null || true

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

</step>

<step name="phase2_5_recursive_lens_probe" profile="web-fullstack,web-frontend-only" mode="full">

#### 2b-2.5: Recursive Lens Probe (v2.40, manager dispatcher)

**Purpose:** After parallel Haiku scanners (2b-2) complete, run the recursive lens probe layer to deep-dive each interesting clickable through bug-class lenses (authz-negative, csrf, idor, ssrf, ...). Manager dispatcher reads scan-*.json, classifies clickables into element classes, picks lenses per class, spawns workers in parallel (auto), generates prompt files (manual), or both (hybrid). Goals discovered by lens probes are merged single-writer into TEST-GOALS-DISCOVERED.md.

**Eligibility (6 rules — all must pass unless `--skip-recursive-probe` is set):**
1. `.phase-profile` declares `phase_profile ∈ {feature, feature-legacy, hotfix}`
2. `.phase-profile` declares `surface ∈ {ui, ui-mobile}` (NOT visual-only)
3. `CRUD-SURFACES.md` declares ≥1 resource
4. `SUMMARY.md` / `RIPPLE-ANALYSIS.md` lists ≥1 `touched_resources` intersecting CRUD
5. `surface != 'visual'`
6. `ENV-CONTRACT.md` present, `disposable_seed_data: true`, all `third_party_stubs` stubbed

If eligibility fails → write `.recursive-probe-skipped.yaml` and continue to 2b-3 (no error).

<MANDATORY_GATE>
**You MUST run the provider-native user prompt below BEFORE invoking the bash block** — unless `--non-interactive` / `VG_NON_INTERACTIVE=1` is set, OR all three axes (`--recursion`, `--probe-mode`, `--target-env`) were already passed on the `/vg:review` command line.
- Do NOT skip the pre-flight because "defaults look fine" — the operator must explicitly choose recursion depth, probe execution mode, and target environment per run.
- Do NOT delegate the prompt to `spawn_recursive_probe.py` stdin — Claude Code's bash sandbox makes `sys.stdin.isatty()` return False, so script-side prompts silently fall back to defaults.
- The bash block at the end of this section will refuse to launch (loud abort + telemetry) if it detects an interactive run with no env vars set, which means the pre-flight was skipped.
- Claude Code path: use `AskUserQuestion`. Codex path: ask the same concise questions in the main Codex thread or closest available Codex input UI.
- After the prompt answers, emit telemetry event `review.recursive_probe.preflight_asked` (logs the chosen axes for audit).
</MANDATORY_GATE>

**Pre-flight (v2.41.1) — operator config via provider-native prompt:**

> ⚠ Why this lives in the command layer (not script stdin):
> Claude Code wraps bash in a sandbox where `sys.stdin.isatty()` returns `False`,
> so the script-side `input()` prompts in `spawn_recursive_probe.py` silently fall
> back to defaults (`light` / `auto` / `sandbox`) without the operator ever
> seeing them. To deliver an actual interactive UX under Claude Code, the
> command layer asks **before** invoking bash, then exports the answers as
> env vars that bash forwards via flags.

Phase 2b-2.5 has three operator-controlled axes. The orchestrator MUST resolve
all three before invoking bash:

| Env var | Source priority | Default |
|---|---|---|
| `RECURSION_MODE` | (1) `--recursion` CLI flag → (2) provider-native prompt → (3) `light` | `light` |
| `PROBE_MODE`     | (1) `--probe-mode` CLI flag → (2) provider-native prompt → (3) `auto` | `auto` |
| `TARGET_ENV`     | (1) `--target-env` CLI flag → (2) `vg.config review.target_env` → (3) provider-native prompt → (4) `sandbox` | `sandbox` |

**Resolution procedure (the orchestrator runs these BEFORE the bash block):**

1. **Parse `/vg:review` CLI args.** For each of `--recursion`, `--probe-mode`,
   `--target-env` that the operator passed, set the matching env var
   (`RECURSION_MODE` / `PROBE_MODE` / `TARGET_ENV`) and skip its prompt.

2. **Skip prompts entirely if `VG_NON_INTERACTIVE=1`** (CI / piped runs) —
   downstream defaults apply.

3. **For each axis still unset, run the provider-native prompt** with the spec below.
   Ask in this order, ONE call per axis (so operator answers can short-circuit
   the next prompt — e.g. picking `skip` for probe-mode means we skip the
   target-env question because no probes will fire).

   **Question 1 — `RECURSION_MODE` (depth/coverage envelope):**
   - `light` *(recommended)* — ~15 workers, depth 2, goal cap 50. Quick coverage on touched resources only.
   - `deep` — ~40 workers, depth 3, goal cap 150. Typical dogfood pass.
   - `exhaustive` — ~100 workers, depth 4, goal cap 400. Pre-release sweep; expect ≥30min wall-clock.

   **Question 2 — `PROBE_MODE` (execution strategy):**
   - `auto` *(recommended)* — VG spawns Gemini Flash subprocess workers end-to-end.
   - `manual` — VG generates per-tool prompt files (`recursive-prompts/{codex,gemini}/`) for paste; operator runs CLI session, drops artifacts in `runs/<tool>/`, VG verifies. Pick when subprocess sandboxing isn't available.
   - `hybrid` — auto for high-confidence lenses (authz-negative, idor, csrf, ...), manual for human-judgment ones (business-logic, ssrf, auth-jwt). Routing comes from `vg.config review.recursive_probe.hybrid_routing`.
   - `skip` — emit `.recursive-probe-skipped.yaml` and continue to 2b-3. Logs OVERRIDE-DEBT critical with reason `"interactive: operator chose skip"`. Use when the recursive layer would be redundant (e.g. follow-up review of a phase that already passed 2b-2.5).

   **Question 3 — `TARGET_ENV` (deploy environment policy):** *only ask if probe-mode ≠ skip.*
   - `local` — full mutations OK, unlimited budget. Pick for local dev runs.
   - `sandbox` *(recommended)* — full mutations OK, 50-mutation/phase budget, disposable seed data assumed.
   - `staging` — mutations OK, `lens-input-injection` blocked, 25-mutation budget, shared-env hygiene.
   - `prod` — **READ-ONLY** (no POST/PUT/PATCH/DELETE), only safe lenses fire. Requires the operator to also pass `--i-know-this-is-prod=<reason>` on the next invocation (hard gate, logs OVERRIDE-DEBT critical).

4. **Export the resolved values** so the bash block sees them:

   ```bash
   export RECURSION_MODE PROBE_MODE TARGET_ENV
   ```

5. **If the operator chose `skip` for probe-mode**, also set
   `SKIP_RECURSIVE_PROBE="interactive: operator chose skip"` before bash.

**Bash invocation:**

```bash
# v2.41.1 — env vars resolved by the provider-native pre-flight above.
# Bash forwards each axis ONLY if set; the script's argparse defaults apply
# otherwise (matches CI / VG_NON_INTERACTIVE=1 contract).
SKIP_REASON="${SKIP_RECURSIVE_PROBE:-}"

# v2.41.2 — anti-forge guard: if the orchestrator skipped the provider-native prompt
# pre-flight (no env vars set + not in CI), refuse to launch with bare defaults.
# This catches the regression where Phase 2b-2.5 silently ran with light/auto/
# sandbox because the markdown narrative pre-flight was lazy-skipped by the LLM.
if [[ -z "${RECURSION_MODE:-}" && -z "${PROBE_MODE:-}" && -z "${TARGET_ENV:-}" \
      && "${VG_NON_INTERACTIVE:-0}" != "1" ]]; then
  echo "" >&2
  echo "⛔ Phase 2b-2.5 pre-flight skipped." >&2
  echo "   The MANDATORY_GATE above requires provider-native prompt to run BEFORE this bash block" >&2
  echo "   so the operator can choose recursion depth / probe-mode / target-env." >&2
  echo "   None of the three env vars (RECURSION_MODE / PROBE_MODE / TARGET_ENV) are set." >&2
  echo "" >&2
  echo "   Fix one of the following:" >&2
  echo "   1. Run the provider-native prompt to ask the operator (recommended for interactive runs)" >&2
  echo "   2. Pass --recursion / --probe-mode / --target-env on the /vg:review CLI" >&2
  echo "   3. Set VG_NON_INTERACTIVE=1 to accept defaults (CI / scripted runs only)" >&2
  echo "   4. Pass --skip-recursive-probe=<reason> to skip Phase 2b-2.5 entirely" >&2
  echo "" >&2
  emit_telemetry_v2 "review.recursive_probe.preflight_skipped" "${PHASE_NUMBER}" \
    --tag "severity=block" 2>/dev/null || true
  exit 2
fi

ARGS=( --phase-dir "$PHASE_DIR" )
if [[ -n "${RECURSION_MODE:-}" ]]; then
  ARGS+=( --mode "$RECURSION_MODE" )
fi
if [[ -n "${PROBE_MODE:-}" ]]; then
  ARGS+=( --probe-mode "$PROBE_MODE" )
fi
if [[ -n "${TARGET_ENV:-}" ]]; then
  ARGS+=( --target-env "$TARGET_ENV" )
fi
if [[ -n "$SKIP_REASON" ]]; then
  ARGS+=( --skip-recursive-probe "$SKIP_REASON" )
fi
if [[ "${VG_NON_INTERACTIVE:-0}" == "1" ]]; then
  ARGS+=( --non-interactive )
fi

# v2.41.2 — pre-flight succeeded; emit telemetry so audit can confirm prompts ran.
emit_telemetry_v2 "review.recursive_probe.preflight_asked" "${PHASE_NUMBER}" \
  --tag "recursion=${RECURSION_MODE:-default}" \
  --tag "probe_mode=${PROBE_MODE:-default}" \
  --tag "target_env=${TARGET_ENV:-default}" 2>/dev/null || true

python scripts/spawn_recursive_probe.py "${ARGS[@]}"
```

**Argparse forwarding (entry point of /vg:review):**

```bash
# /vg:review accepts these flags. The orchestrator parses them BEFORE the
# Provider-native pre-flight runs and exports the matching env var so the
# operator only gets prompted for axes they didn't pre-supply:
#   --recursion={light,deep,exhaustive}     → export RECURSION_MODE=$value
#   --probe-mode={auto,manual,hybrid}       → export PROBE_MODE=$value
#   --target-env={local,sandbox,staging,prod} → export TARGET_ENV=$value
#   --skip-recursive-probe="<reason>"       → export SKIP_RECURSIVE_PROBE=$value
#   --non-interactive                       → export VG_NON_INTERACTIVE=1 (suppress provider prompts + stdin prompts)
#   --i-know-this-is-prod="<reason>"        → forwarded as-is (prod-safety opt-in)
```

**Manual mode (`PROBE_MODE=manual`):**

The dispatcher writes prompt files to `${PHASE_DIR}/recursive-prompts/MANIFEST.md` and pauses. Operator runs each prompt against their preferred CLI agent (gemini/codex/claude), drops artifacts back into `${PHASE_DIR}/runs/<tool>/`, then resumes the pipeline. The verifier runs automatically when the user signals completion:

```bash
if [[ "$PROBE_MODE" == "manual" ]]; then
  echo "Manual prompts written. Follow ${PHASE_DIR}/recursive-prompts/MANIFEST.md, drop artifacts in runs/, then press Enter."
  if [[ "${VG_NON_INTERACTIVE:-0}" != "1" ]]; then
    read -r _
  fi
  python scripts/verify_manual_run_artifacts.py --phase-dir "$PHASE_DIR" || exit 1
fi
```

**Hybrid mode:** dispatcher routes per-lens to auto vs manual based on `vg.config.md → review.recursive_probe.hybrid_routing`. See [vg:_shared:config-loader] for resolution.

**Aggregation (single-writer, end of 2b-2.5):**

```bash
python scripts/aggregate_recursive_goals.py --phase-dir "$PHASE_DIR" --mode "$RECURSION_MODE"
# Writes TEST-GOALS-DISCOVERED.md (G-RECURSE-* level-3 entries) + recursive-goals-overflow.json.
```

**Idempotency:** Re-running 2b-2.5 reuses existing `runs/` artifacts; canonical-key dedup in aggregator prevents duplicate goal stubs.

**Failure semantics:** Eligibility fail → skip block (continue). Worker fail → recorded in `runs/INDEX.json`, does not abort pipeline. Manual mode timeout → operator re-runs; no automatic retry.

</step>

<step name="phase2b_collect_merge" profile="web-fullstack,web-frontend-only" mode="full">

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

**Phase 15 D-17 — phantom-aware Haiku spawn audit (NEW, 2026-04-27):**

Confirm the `review.haiku_scanner_spawned` event emitted by step 2b-2 is
actually present in events.db for every (view × role) we expected to scan.
The validator (`verify-haiku-spawn-fired.py`) is phantom-aware: it ignores
events from runs whose signature matches `args:""` + 0 step.marked + abort
within 60s (the D-17 hook-triggered noise pattern), so manual `/vg:learn`
invocations don't show up as false positives.

```bash
PHANTOM_VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-haiku-spawn-fired.py"
if [ -x "$PHANTOM_VALIDATOR" ] && [ -f "${REPO_ROOT}/.vg/events.db" ]; then
  ${PYTHON_BIN} "$PHANTOM_VALIDATOR" --phase "${PHASE_NUMBER}" \
      > "${VG_TMP}/haiku-spawn-audit.json" 2>&1 || true
  HSV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/haiku-spawn-audit.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$HSV" in
    PASS) echo "✓ D-17 Haiku-spawn audit: PASS — telemetry confirms scanner fired per view/role" ;;
    WARN) echo "⚠ D-17 Haiku-spawn audit: WARN — see ${VG_TMP}/haiku-spawn-audit.json (informational only)" ;;
    BLOCK)
      echo "⛔ D-17 Haiku-spawn audit: BLOCK — expected scanner spawns missing from events.db." >&2
      echo "   Inspect ${VG_TMP}/haiku-spawn-audit.json for the per-(view,role) breakdown." >&2
      echo "   Common cause: orchestrator ran briefing_for_view but Agent() spawn was skipped." >&2
      echo "   Override: --skip-haiku-audit (logs override-debt as kind=haiku-spawn-audit-skipped)." >&2
      if [[ ! "$ARGUMENTS" =~ --skip-haiku-audit ]]; then
        exit 1
      fi
      ;;
    SKIP|*) echo "ℹ D-17 Haiku-spawn audit: ${HSV} — likely no UI-profile views in this phase" ;;
  esac
fi
```

### 2b-4: Generate Review Lens Plan

After RUNTIME-MAP exists, materialize the plugin contract that the remaining
review steps must execute. This is the harness-level binding between the
visible step list and the smaller checks/lenses.

```bash
LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ]; then
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --write
  LENS_PLAN_RC=$?
  if [ "$LENS_PLAN_RC" -ne 0 ] || [ ! -f "${PHASE_DIR}/REVIEW-LENS-PLAN.json" ]; then
    echo "⛔ Review lens plan generation failed — cannot prove plugin checklist coverage." >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_plan_generated" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"artifact\":\"REVIEW-LENS-PLAN.json\"}" \
    >/dev/null 2>&1 || true
else
  echo "⛔ Missing review lens planner: $LENS_PLAN_SCRIPT" >&2
  exit 1
fi
```
</step>

<step name="phase2c_enrich_test_goals" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2c — Enrich TEST-GOALS from runtime discovery (v2.34.0+, closes #52)

Bridges the design gap between **Step 3 (click many components)** and **Step 4 (rich goals for test layer)** of the original 4-step review architecture. Without this step, every Haiku-discovered button/form/modal/tab/row-action sits dead in `views[X].elements[]` and the downstream test layer never tests it.

`enrich-test-goals.py` reads every `scan-*.json`, classifies elements (modal triggers, mutations, forms, table row actions, paging, tabs), dedupes against existing TEST-GOALS.md `interactive_controls`, and emits `${PHASE_DIR}/TEST-GOALS-DISCOVERED.md` with `G-AUTO-*` goal stubs. `/vg:test` codegen (step 5d) reads both files; auto-emitted specs land as `auto-{goal-id}.spec.ts` for visual distinction.

```bash
echo ""
echo "━━━ Phase 2c — Enrich TEST-GOALS from runtime discovery ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2c_enrich_test_goals >/dev/null 2>&1 || true

ENRICH_THRESHOLD=$(vg_config_get "review.enrich_min_elements" "3" 2>/dev/null || echo "3")

${PYTHON_BIN:-python3} .claude/scripts/enrich-test-goals.py \
  --phase-dir "$PHASE_DIR" \
  --threshold "$ENRICH_THRESHOLD"
ENRICH_RC=$?

case "$ENRICH_RC" in
  0)
    AUTO_COUNT=$(grep -c "^id: G-AUTO-" "$PHASE_DIR/TEST-GOALS-DISCOVERED.md" 2>/dev/null || echo 0)
    echo "  ✓ Phase 2c: ${AUTO_COUNT} auto-emitted goals → ${PHASE_DIR}/TEST-GOALS-DISCOVERED.md"
    emit_telemetry_v2 "review_phase2c_enriched" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment" "PASS" \
      "{\"auto_goals\":${AUTO_COUNT}}" 2>/dev/null || true
    ;;
  *)
    echo "  ⚠ Phase 2c enrichment failed (rc=${ENRICH_RC}) — TEST-GOALS-DISCOVERED.md not written."
    echo "    Test layer codegen will fall back to TEST-GOALS.md only (legacy behavior)."
    emit_telemetry_v2 "review_phase2c_failed" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment" "WARN" \
      "{\"rc\":${ENRICH_RC}}" 2>/dev/null || true
    ;;
esac

# Coverage validator: BLOCK if any view had elements scanned but no goals derived.
# This catches the failure mode where Haiku ran but classification missed everything
# (e.g. element schema drift, parser bug). Per-phase override via --skip-enrich-validate.
if [[ ! "$ARGUMENTS" =~ --skip-enrich-validate ]]; then
  ${PYTHON_BIN:-python3} .claude/scripts/enrich-test-goals.py \
    --phase-dir "$PHASE_DIR" \
    --threshold "$ENRICH_THRESHOLD" \
    --validate-only
  VALIDATE_RC=$?
  if [ "$VALIDATE_RC" -ne 0 ]; then
    echo "  ⛔ Phase 2c enrichment validation FAILED."
    echo "     Either re-run /vg:review {phase} so scanners visit those views,"
    echo "     or pass --skip-enrich-validate=\"<reason>\" to log OVERRIDE-DEBT."
    emit_telemetry_v2 "review_phase2c_coverage_gap" "${PHASE_NUMBER}" \
      "review.2c-enrich" "test_goals_enrichment_coverage" "FAIL" \
      "{\"rc\":${VALIDATE_RC}}" 2>/dev/null || true
    exit 1
  fi
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2c_enrich_test_goals 2>/dev/null || true
```
</step>

<step name="phase2c_pre_dispatch_gates" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2c-pre — Contract completeness + env preflight (v2.39.0+)

Two pre-dispatch gates close Codex critiques #1 (contract validity not gated) + #6 (env state implicit):

1. `verify-contract-completeness.py` diffs runtime/code inventory against CRUD-SURFACES.md declared resources. Flags hidden routes, undeclared resources, background jobs, webhooks.
2. `verify-env-contract.py` reads ENV-CONTRACT.md preflight_checks and verifies each (app reachable, seed data present, login works).

If contract incomplete OR env preflight fails → review aborts BEFORE spawning expensive workers (Gemini Flash workers can run $0.30-1.00 per phase; aborting pre-spawn saves token cost when env is broken).

```bash
echo ""
echo "━━━ Phase 2c-pre — Contract completeness + env preflight ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2c_pre_dispatch_gates >/dev/null 2>&1 || true

# Contract completeness gate (severity warn first release for dogfood)
COMPLETE_SEV=$(vg_config_get "review.contract_completeness.severity" "warn" 2>/dev/null || echo "warn")
${PYTHON_BIN:-python3} .claude/scripts/verify-contract-completeness.py \
  --phase-dir "$PHASE_DIR" \
  --code-root "${REPO_ROOT}" \
  --severity "$COMPLETE_SEV"
COMPLETE_RC=$?
if [ "$COMPLETE_RC" -ne 0 ] && [ "$COMPLETE_SEV" = "block" ]; then
  echo "⛔ Contract completeness BLOCK — see CONTRACT-COMPLETENESS.json"
  exit 1
fi

# Env contract preflight (mandatory if any kit:crud-roundtrip declared, optional for kit:static-sast)
if grep -q '"kit"\s*:\s*"crud-roundtrip"\|"kit"\s*:\s*"approval-flow"\|"kit"\s*:\s*"bulk-action"' "${PHASE_DIR}/CRUD-SURFACES.md" 2>/dev/null; then
  ENV_SEV=$(vg_config_get "review.env_contract.severity" "block" 2>/dev/null || echo "block")
  if [[ "$ARGUMENTS" =~ --skip-env-contract=\"([^\"]*)\" ]]; then
    ENV_REASON="${BASH_REMATCH[1]}"
    echo "  ⚠ ENV-CONTRACT skipped: $ENV_REASON (logged to OVERRIDE-DEBT)"
  else
    ${PYTHON_BIN:-python3} .claude/scripts/verify-env-contract.py \
      --phase-dir "$PHASE_DIR" \
      > "${PHASE_DIR}/.tmp/env-contract-review.txt" 2>&1
    ENV_RC=$?
    if [ "$ENV_RC" -ne 0 ] && [ "$ENV_SEV" = "block" ]; then
      echo "⛔ ENV-CONTRACT preflight FAIL — fix env or pass --skip-env-contract=\"<reason>\""
      cat "${PHASE_DIR}/.tmp/env-contract-review.txt" 2>/dev/null || true
      DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
      if [ -f "$DIAG_SCRIPT" ]; then
        "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
          --gate-id "review.env_contract" \
          --phase-dir "$PHASE_DIR" \
          --input "${PHASE_DIR}/.tmp/env-contract-review.txt" \
          --out-md "${PHASE_DIR}/.tmp/env-contract-diagnostic.md" \
          >/dev/null 2>&1 || true
        cat "${PHASE_DIR}/.tmp/env-contract-diagnostic.md" 2>/dev/null || true
      fi
      exit 1
    fi
  fi
fi

emit_telemetry_v2 "review_phase2c_pre_gates" "${PHASE_NUMBER}" \
  "review.2c-pre" "pre_dispatch_gates" "PASS" \
  "{\"contract_complete_rc\":${COMPLETE_RC:-0}}" 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2c_pre_dispatch_gates 2>/dev/null || true
```
</step>

<step name="phase2d_crud_roundtrip_dispatch" profile="web-fullstack,web-frontend-only,web-backend-only" mode="full">
## Phase 2d — CRUD round-trip lens dispatch (v2.35.0+, closes #51)

Dispatches Gemini Flash workers per `(resource × role)` declared with `kit: crud-roundtrip` in CRUD-SURFACES.md. Each worker runs the 8-step Read→Create→Read→Update→Read→Delete→Read round-trip per `commands/vg/_shared/transition-kits/crud-roundtrip.md`.

**Why Gemini Flash (not Claude Haiku):** $0.075/M input vs $1.00/M = 13× cheaper. Already MCP-configured (5 Playwright servers in `~/.gemini/settings.json`). Already in cross-CLI plumbing.

**Pre-flight:** auth fixture must exist. If not, run `scripts/review-fixture-bootstrap.py` first.

```bash
echo ""
echo "━━━ Phase 2d — CRUD round-trip lens dispatch ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2d_crud_roundtrip_dispatch >/dev/null 2>&1 || true

# Skip if no CRUD-SURFACES or no resources declare this kit
if [ ! -f "${PHASE_DIR}/CRUD-SURFACES.md" ]; then
  echo "  (no CRUD-SURFACES.md — skipping Phase 2d)"
elif ! grep -q '"kit"\s*:\s*"crud-roundtrip"' "${PHASE_DIR}/CRUD-SURFACES.md"; then
  echo "  (no resources with kit: crud-roundtrip — skipping Phase 2d)"
else
  # Bootstrap auth tokens if missing
  TOKENS_PATH="${PHASE_DIR}/.review-fixtures/tokens.local.yaml"
  REPO_TOKENS_PATH="${REPO_ROOT}/.review-fixtures/tokens.local.yaml"
  if [ ! -f "$TOKENS_PATH" ] && [ ! -f "$REPO_TOKENS_PATH" ]; then
    echo "  Bootstrapping auth tokens..."
    ${PYTHON_BIN:-python3} .claude/scripts/review-fixture-bootstrap.py \
      --phase-dir "$PHASE_DIR" || {
        echo "  ⚠ Auth fixture bootstrap failed — Phase 2d skipped (workers cannot authenticate)"
      }
  fi

  if [ -f "$TOKENS_PATH" ] || [ -f "$REPO_TOKENS_PATH" ]; then
    COST_CAP=$(vg_config_get "review.crud_roundtrip.cost_cap_usd" "1.50" 2>/dev/null || echo "1.50")
    CONCURRENCY=$(vg_config_get "review.crud_roundtrip.concurrency" "2" 2>/dev/null || echo "2")

    ${PYTHON_BIN:-python3} .claude/scripts/spawn-crud-roundtrip.py \
      --phase-dir "$PHASE_DIR" \
      --concurrency "$CONCURRENCY" \
      --cost-cap "$COST_CAP"
    DISPATCH_RC=$?

    if [ "$DISPATCH_RC" -eq 0 ]; then
      ARTIFACTS=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('${PHASE_DIR}/runs/INDEX.json')); print(d.get('artifacts_present', 0))" 2>/dev/null || echo "0")
      echo "  ✓ CRUD round-trip dispatch complete: ${ARTIFACTS} run artifact(s)"
      emit_telemetry_v2 "review_phase2d_dispatched" "${PHASE_NUMBER}" \
        "review.2d-crud-dispatch" "crud_roundtrip" "PASS" \
        "{\"artifacts\":${ARTIFACTS}}" 2>/dev/null || true
    else
      echo "  ⚠ CRUD round-trip dispatch failed (rc=${DISPATCH_RC})"
      emit_telemetry_v2 "review_phase2d_failed" "${PHASE_NUMBER}" \
        "review.2d-crud-dispatch" "crud_roundtrip" "FAIL" \
        "{\"rc\":${DISPATCH_RC}}" 2>/dev/null || true
    fi
  fi
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2d_crud_roundtrip_dispatch 2>/dev/null || true
```
</step>

<step name="phase2e_findings_merge" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2e — Findings derivation (v2.35.0+)

Reads run artifacts from Phase 2d and derives `REVIEW-FINDINGS.json` (machine-readable, deduped) + `REVIEW-BUGS.md` (Strix-style human-readable triage doc).

**No auto-route to /vg:build in v2.35.0** — manual triage during dogfood per Codex review feedback. Auto-route candidate for v2.37.0 after schema confidence/dedupe quality validated on real findings.

```bash
echo ""
echo "━━━ Phase 2e — Findings derivation ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2e_findings_merge >/dev/null 2>&1 || true

if [ -d "${PHASE_DIR}/runs" ] && [ -n "$(ls -A ${PHASE_DIR}/runs/*.json 2>/dev/null | grep -v INDEX.json)" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/derive-findings.py \
    --phase-dir "$PHASE_DIR"
  DERIVE_RC=$?

  if [ "$DERIVE_RC" -eq 0 ] && [ -f "${PHASE_DIR}/REVIEW-FINDINGS.json" ]; then
    FINDING_COUNT=$(${PYTHON_BIN:-python3} -c "import json; d=json.load(open('${PHASE_DIR}/REVIEW-FINDINGS.json')); print(d.get('findings_total', 0))" 2>/dev/null || echo "0")
    echo "  ✓ ${FINDING_COUNT} finding(s) derived → ${PHASE_DIR}/REVIEW-BUGS.md"
    emit_telemetry_v2 "review_phase2e_findings" "${PHASE_NUMBER}" \
      "review.2e-findings" "findings_derive" "PASS" \
      "{\"findings\":${FINDING_COUNT}}" 2>/dev/null || true
  fi
else
  echo "  (no run artifacts to derive — skipping)"
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2e_findings_merge 2>/dev/null || true
```
</step>

<step name="phase2e_post_challenge" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2e-post — Manager adversarial challenge (v2.39.0+, closes Codex critique #7)

Workers report `coverage.passed`. This step asks: "do these passes actually imply coverage?". Heuristic adversarial reducer samples N% of run artifacts and challenges each pass step:
- `pass` with empty `evidence_ref` → downgrade to `weak-pass`
- `pass` with empty `observed` block → downgrade to `weak-pass`
- `pass` with observed status mismatching expected → flagged `false-pass` (severity DEGRADED)

Output: `${PHASE_DIR}/COVERAGE-CHALLENGE.json` with downgrades + warnings. v2.40 may add LLM-driven challenge for ambiguous claims.

```bash
echo ""
echo "━━━ Phase 2e-post — Manager adversarial challenge ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2e_post_challenge >/dev/null 2>&1 || true

if [ -d "${PHASE_DIR}/runs" ] && [ -n "$(ls -A ${PHASE_DIR}/runs/*.json 2>/dev/null | grep -v INDEX.json)" ]; then
  CHALLENGE_RATE=$(vg_config_get "review.challenge.sample_rate" "25" 2>/dev/null || echo "25")
  CHALLENGE_SEV=$(vg_config_get "review.challenge.severity" "warn" 2>/dev/null || echo "warn")

  ${PYTHON_BIN:-python3} .claude/scripts/challenge-coverage.py \
    --phase-dir "$PHASE_DIR" \
    --sample-rate "$CHALLENGE_RATE" \
    --severity "$CHALLENGE_SEV"
  CHALLENGE_RC=$?

  if [ "$CHALLENGE_RC" -ne 0 ] && [ "$CHALLENGE_SEV" = "block" ]; then
    echo "⛔ Coverage challenge: false-pass steps detected. See COVERAGE-CHALLENGE.json"
    emit_telemetry_v2 "review_phase2e_post_challenge_failed" "${PHASE_NUMBER}" \
      "review.2e-post" "coverage_challenge" "BLOCK" "{}" 2>/dev/null || true
    exit 1
  fi
  emit_telemetry_v2 "review_phase2e_post_challenge" "${PHASE_NUMBER}" \
    "review.2e-post" "coverage_challenge" "PASS" \
    "{\"sample_rate\":${CHALLENGE_RATE}}" 2>/dev/null || true
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2e_post_challenge 2>/dev/null || true
```
</step>

<step name="phase2f_route_auto_fix" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2f — Route findings to /vg:build (v2.37.0+, opt-in)

Reads `REVIEW-FINDINGS.json` and emits `AUTO-FIX-TASKS.md` for findings meeting the conservative gate (severity ≥ high, confidence == high, cleanup_status == completed). `/vg:build` consumes via `--include-auto-fix` flag (opt-in v2.37, may default-on v2.38 after dogfood).

```bash
echo ""
echo "━━━ Phase 2f — Route findings to /vg:build (auto-fix loop) ━━━"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase2f_route_auto_fix >/dev/null 2>&1 || true

if [ -f "${PHASE_DIR}/REVIEW-FINDINGS.json" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/route-findings-to-build.py \
    --phase-dir "$PHASE_DIR"
  ROUTE_RC=$?

  if [ "$ROUTE_RC" -eq 0 ] && [ -f "${PHASE_DIR}/AUTO-FIX-TASKS.md" ]; then
    TASK_COUNT=$(grep -c "^### Task AF-" "${PHASE_DIR}/AUTO-FIX-TASKS.md" 2>/dev/null || echo 0)
    echo "  ✓ ${TASK_COUNT} auto-fix task group(s) → AUTO-FIX-TASKS.md"
    echo "    Run /vg:build ${PHASE_NUMBER} --include-auto-fix to consume"
    emit_telemetry_v2 "review_phase2f_routed" "${PHASE_NUMBER}" \
      "review.2f-route" "auto_fix_routing" "PASS" \
      "{\"task_groups\":${TASK_COUNT}}" 2>/dev/null || true
  else
    echo "  (no qualifying findings to route)"
  fi
else
  echo "  (no REVIEW-FINDINGS.json — skipping)"
fi
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2f_route_auto_fix 2>/dev/null || true
```
</step>

<step name="phase2_exploration_limits" profile="web-fullstack,web-frontend-only" mode="full">
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
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
else
  MAX_VIEW="${CONFIG_REVIEW_MAX_ACTIONS_PER_VIEW:-50}"
  MAX_TOTAL="${CONFIG_REVIEW_MAX_ACTIONS_TOTAL:-200}"
  MAX_WALL="${CONFIG_REVIEW_MAX_WALL_MINUTES:-30}"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$RUNTIME_MAP" "$MAX_VIEW" "$MAX_TOTAL" "$MAX_WALL" "${PHASE_DIR}" <<'PY'
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

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
    "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
PY

  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_exploration_limits" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_exploration_limits.done"

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_exploration_limits 2>/dev/null || true
fi
```

**Hành vi downstream:** nếu có warnings, step `crossai_review` cuối pipeline sẽ include "exploration noisy" flag vào context để CrossAI xem xét kỹ goals liên quan views overflow.
</step>

<step name="phase2_mobile_discovery" profile="mobile-*" mode="full">
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

<step name="phase2_5_visual_checks" profile="web-fullstack,web-frontend-only" mode="full">
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

### 6. Phase 15 D-12 — Wave-scoped + Holistic Drift Gates (NEW, 2026-04-27)

After the legacy visual checks (font/overflow/responsive/z-index), run the
Phase 15 visual-fidelity gates. Threshold comes from `.fidelity-profile.lock`
written by `/vg:blueprint` step 2_fidelity_profile_lock (D-08).

**6a. D-12c — UI flag presence (cheap precondition, runs first):**

```bash
if [ -x "${REPO_ROOT}/.claude/scripts/validators/verify-phase-ui-flag.py" ]; then
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/validators/verify-phase-ui-flag.py" \
      --phase "${PHASE_NUMBER}" > "${VG_TMP}/ui-flag.json" 2>&1
  UIF=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/ui-flag.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$UIF" in
    PASS|WARN) echo "✓ D-12c UI-flag check: $UIF" ;;
    BLOCK) echo "⛔ D-12c UI-flag check: BLOCK — phase declared UI work but UI-MAP.md/design assets missing" >&2; exit 1 ;;
    *) echo "ℹ D-12c UI-flag check: $UIF — phase has no UI declaration" ;;
  esac
fi
```

**6b. D-12b — Wave-scoped structural drift (per wave that has owned UI subtree):**

```bash
if [ -f "${PHASE_DIR}/UI-MAP.md" ] \
   && [ -x "${REPO_ROOT}/.claude/scripts/verify-ui-structure.py" ]; then
  THRESHOLD=$(${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/lib/threshold-resolver.py" \
      --phase "${PHASE_NUMBER}" 2>/dev/null || echo "0.85")

  # Discover waves with owned subtrees by inspecting planner UI-MAP for owner_wave_id values.
  WAVES=$(${PYTHON_BIN} -c "
import json, re
text = open('${PHASE_DIR}/UI-MAP.md', encoding='utf-8').read()
m = re.search(r'\`\`\`json\s*\n([\s\S]*?)\n\`\`\`', text)
if not m:
    raise SystemExit
data = json.loads(m.group(1))
seen = set()
def walk(n):
    if isinstance(n, dict):
        if n.get('owner_wave_id'):
            seen.add(n['owner_wave_id'])
        for c in n.get('children', []) or []:
            walk(c)
walk(data.get('root', data))
print(' '.join(sorted(seen)))
" 2>/dev/null)

  WAVE_BLOCK=0
  for WAVE_ID in $WAVES; do
    ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/verify-ui-structure.py" \
        --phase "${PHASE_NUMBER}" \
        --scope "owner-wave-id=${WAVE_ID}" \
        --threshold "${THRESHOLD}" \
        > "${VG_TMP}/drift-${WAVE_ID}.json" 2>&1 || true
    V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/drift-${WAVE_ID}.json')).get('verdict','SKIP'))" 2>/dev/null)
    case "$V" in
      PASS|WARN) echo "✓ D-12b drift ${WAVE_ID}: $V (threshold=${THRESHOLD})" ;;
      BLOCK)
        echo "⛔ D-12b drift ${WAVE_ID}: BLOCK — see ${VG_TMP}/drift-${WAVE_ID}.json" >&2
        WAVE_BLOCK=1
        ;;
      *) echo "ℹ D-12b drift ${WAVE_ID}: $V" ;;
    esac
  done
  if [ "$WAVE_BLOCK" = "1" ] && [[ ! "$ARGUMENTS" =~ --allow-wave-drift ]]; then
    echo "  Override: --allow-wave-drift (logs override-debt as kind=wave-drift-relaxed)" >&2
    exit 1
  fi
fi
```

**6c. D-12e — Holistic phase-wide drift (runs once at phase end):**

```bash
if [ -x "${REPO_ROOT}/.claude/scripts/verify-holistic-drift.py" ] \
   && [ -f "${PHASE_DIR}/UI-MAP.md" ]; then
  ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/verify-holistic-drift.py" \
      --phase "${PHASE_NUMBER}" \
      > "${VG_TMP}/holistic-drift.json" 2>&1 || true
  HV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open('${VG_TMP}/holistic-drift.json')).get('verdict','SKIP'))" 2>/dev/null)
  case "$HV" in
    PASS|WARN) echo "✓ D-12e holistic drift: $HV" ;;
    BLOCK)
      echo "⛔ D-12e holistic drift: BLOCK — see ${VG_TMP}/holistic-drift.json" >&2
      echo "  Wave gates passed but phase-wide composition drifted (e.g., layout fight between waves)." >&2
      echo "  Override: --allow-holistic-drift" >&2
      if [[ ! "$ARGUMENTS" =~ --allow-holistic-drift ]]; then exit 1; fi
      ;;
    *) echo "ℹ D-12e holistic drift: $HV" ;;
  esac
fi
```

**6e. L4 — Design-fidelity SSIM gate (NEW, 2026-04-28):**

Final safety net for the 4-layer pixel pipeline. L1 (executor reads PNG) +
L2 (LAYOUT-FINGERPRINT) + L3 (build-time render vs baseline) all run
during /vg:build. This gate runs during /vg:review using the live browser
session — if any of the upstream layers were skipped or overridden, this
catches the drift before it leaves the phase. **Severity = BLOCK** by
design; override `--allow-design-drift` consumes a rationalization-guard
slot and logs override-debt.

```bash
DF_THRESHOLD="$(vg_config_get visual_checks.design_fidelity_threshold_pct 5.0 2>/dev/null || echo 5.0)"

if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
  DF_PAIRS=$(PYTHONPATH="${REPO_ROOT}/.claude/scripts/lib:${REPO_ROOT}/scripts/lib:${PYTHONPATH:-}" ${PYTHON_BIN} - "${PHASE_DIR}/RUNTIME-MAP.json" "${PHASE_DIR}" "${REPO_ROOT}" "${REPO_ROOT}/.claude/vg.config.md" <<'PY'
import json, sys
from pathlib import Path
from design_ref_resolver import first_screenshot, parse_config_file, resolve_design_assets

rt = json.load(open(sys.argv[1], encoding="utf-8"))
phase_dir = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
config = parse_config_file(Path(sys.argv[4]))
views = rt.get("views") or rt.get("routes") or []
for v in views:
    slug = v.get("design_ref") or v.get("design_slug") or v.get("slug")
    if not slug:
        continue
    png = first_screenshot(resolve_design_assets(slug, repo_root=repo_root, phase_dir=phase_dir, config=config))
    if not png:
        continue
    label = v.get("label") or v.get("path") or v.get("url") or slug
    url = v.get("url") or v.get("path") or "/"
    print(f"{slug}\t{url}\t{png}\t{label}")
PY
  )

  DF_ISSUES=()
  DF_CHECKS=0
  if [ -n "$DF_PAIRS" ]; then
    mkdir -p "${PHASE_DIR}/visual-fidelity" 2>/dev/null
    while IFS=$'\t' read -r DF_SLUG DF_URL DF_BASELINE DF_LABEL; do
      [ -z "$DF_SLUG" ] && continue
      DF_CHECKS=$((DF_CHECKS + 1))
      DF_CURRENT="${PHASE_DIR}/visual-fidelity/${DF_SLUG}.current.png"
      DF_DIFF="${PHASE_DIR}/visual-fidelity/${DF_SLUG}.diff.png"

      # Reuse the Phase 2 browser session — already navigated + logged in.
      # MCP step (orchestrator runs in-context):
      #   browser_navigate { url: $DF_URL }
      #   browser_evaluate "await new Promise(r => setTimeout(r, 500))"
      #   browser_take_screenshot { path: $DF_CURRENT }
      # If an MCP step is unavailable, the diff falls back to SKIP and the
      # next phase 2.5 sweep will pick the slug up.

      if [ ! -f "$DF_CURRENT" ]; then
        echo "ℹ L4 fidelity ${DF_SLUG}: SKIP — current screenshot not produced (MCP browser step missing)"
        continue
      fi

      DF_PCT=$(${PYTHON_BIN} - "$DF_CURRENT" "$DF_BASELINE" "$DF_DIFF" <<'PY'
import sys
try:
    from PIL import Image
    from pixelmatch.contrib.PIL import pixelmatch
except ImportError:
    print("-1")
    sys.exit(0)
a = Image.open(sys.argv[1]).convert("RGBA")
b = Image.open(sys.argv[2]).convert("RGBA")
if a.size != b.size:
    b = b.resize(a.size)
diff = Image.new("RGBA", a.size)
mismatch = pixelmatch(a, b, diff, threshold=0.1)
total = a.size[0] * a.size[1]
pct = (mismatch / total) * 100 if total else 0
diff.save(sys.argv[3])
print(f"{pct:.3f}")
PY
      )

      if [ "$DF_PCT" = "-1" ]; then
        echo "ℹ L4 fidelity ${DF_SLUG}: SKIP — pixelmatch+PIL not installed"
        continue
      fi

      DF_VERDICT=$(${PYTHON_BIN} -c "import sys; print('PASS' if float(sys.argv[1]) <= float(sys.argv[2]) else 'BLOCK')" "$DF_PCT" "$DF_THRESHOLD")
      cat > "${PHASE_DIR}/visual-fidelity/${DF_SLUG}.json" <<JSON
{"slug":"${DF_SLUG}","url":"${DF_URL}","label":"${DF_LABEL}","diff_pct":${DF_PCT},"threshold_pct":${DF_THRESHOLD},"verdict":"${DF_VERDICT}","current":"${DF_CURRENT}","baseline":"${DF_BASELINE}","diff":"${DF_DIFF}"}
JSON
      if [ "$DF_VERDICT" = "BLOCK" ]; then
        DF_ISSUES+=("${DF_SLUG} (${DF_PCT}% > ${DF_THRESHOLD}%)")
        echo "⛔ L4 fidelity ${DF_SLUG}: ${DF_PCT}% drift > ${DF_THRESHOLD}% → see ${DF_DIFF}"
      else
        echo "✓ L4 fidelity ${DF_SLUG}: ${DF_PCT}% (≤ ${DF_THRESHOLD}%)"
      fi
    done <<< "$DF_PAIRS"
  fi

  if [ ${#DF_ISSUES[@]} -gt 0 ]; then
    echo "⛔ L4 design-fidelity gate: ${#DF_ISSUES[@]} view(s) drift past ${DF_THRESHOLD}%:"
    for i in "${DF_ISSUES[@]}"; do echo "    - $i"; done
    echo "   Diffs: ${PHASE_DIR}/visual-fidelity/*.diff.png"
    echo "   Override: --allow-design-drift (rationalization-guard + override-debt)"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "review_l4_fidelity" "${PHASE_NUMBER}" "review.phase2_5" \
        "design_fidelity" "BLOCK" "{\"count\":${#DF_ISSUES[@]},\"threshold\":${DF_THRESHOLD}}"
    fi
    if [[ ! "$ARGUMENTS" =~ --allow-design-drift ]]; then exit 1; fi
    echo "⚠ --allow-design-drift set — drift accepted; override-debt logged."
  elif [ "${DF_CHECKS:-0}" -gt 0 ]; then
    echo "✓ L4 design-fidelity gate: ${DF_CHECKS} view(s) within ${DF_THRESHOLD}% of baseline"
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_visual_checks" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_visual_checks.done"`
</step>

<step name="phase2_5_mobile_visual_checks" profile="mobile-*" mode="full">
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

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_5_mobile_visual_checks" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_5_mobile_visual_checks.done"`
</step>

<step name="phase2_7_url_state_sync" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.7: URL state sync declaration check (Phase J)

→ `narrate_phase "Phase 2.7 — URL state sync" "Kiểm tra interactive_controls trong TEST-GOALS"`

**Purpose:** validate every list/table/grid view goal in TEST-GOALS.md
declares `interactive_controls` block (filter/sort/pagination/search +
URL sync assertion). This is the static-side complement to runtime
browser probing — declaration must exist before runtime can verify.

**CRUD surface precheck (v2.12):** before URL-state checks, validate
`${PHASE_DIR}/CRUD-SURFACES.md`. Review compares runtime observations against
the resource/platform contract first, then uses `interactive_controls` as the
web-list extension pack. Missing CRUD contract means the reviewer has no
authoritative list of expected headings, filters, columns, states, row actions,
delete confirmations, or security/abuse expectations.

```bash
CRUD_FLAGS=""
[[ "${ARGUMENTS:-}" =~ --allow-no-crud-surface ]] && CRUD_FLAGS="--allow-missing"
CRUD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crud-surface-contract.py"
if [ -x "$CRUD_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_VAL" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" ${CRUD_FLAGS} \
    > "${PHASE_DIR}/.tmp/crud-surface-review.json" 2>&1
  CRUD_RC=$?
  if [ "$CRUD_RC" != "0" ]; then
    echo "⛔ CRUD surface contract missing/incomplete — see ${PHASE_DIR}/.tmp/crud-surface-review.json"
    echo "   Fix blueprint artifact CRUD-SURFACES.md or rerun /vg:blueprint."
    exit 2
  fi
fi
```

**Why:** modern dashboard UX baseline (executor R7) requires list view
state synced to URL search params. Without declaration, AI executors
build local-state-only filters and ship apps that lose state on refresh.
This validator catches the gap at /vg:review time, before user sees it.

**Severity:** config-driven via `vg.config.md → ui_state_conventions.severity_phase_cutover`
(default 14). Phase number < cutover → WARN (grandfather). Phase ≥ cutover
→ BLOCK (mandatory). Override with `--allow-no-url-sync` to log soft OD
debt entry.

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-sync.py \
  --phase "${PHASE_NUMBER}" \
  --enforce-required-lenses \
  > "${PHASE_DIR}/.tmp/url-state-sync.json" 2>&1
URL_SYNC_RC=$?

if [ "${URL_SYNC_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-no-url-sync"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-sync \
      --reason "URL state sync waived for ${PHASE_NUMBER} via --allow-no-url-sync (soft debt logged)"
    echo "⚠ URL state sync gate waived via --allow-no-url-sync"
  else
    echo "⛔ URL state sync declarations missing — see ${PHASE_DIR}/.tmp/url-state-sync.json"
    cat "${PHASE_DIR}/.tmp/url-state-sync.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_sync" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-sync.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-sync-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Add interactive_controls blocks to TEST-GOALS.md per goal."
    echo "     Schema: .claude/commands/vg/_shared/templates/TEST-GOAL-enriched-template.md (Phase J section)."
    echo "  2. If state is genuinely local-only, declare url_sync: false + url_sync_waive_reason."
    echo "  3. Override (last resort): re-run with --allow-no-url-sync (logs soft OD debt)."
    exit 2
  fi
fi
```

**Future runtime probe (deferred to v2.9):** once RUNTIME-MAP.json is
populated by phase 2 browser discovery, a follow-up validator can click
each declared control via MCP Playwright + snapshot URL pre/post +
assert reload-survives. Static declaration check is the foundation that
makes runtime probe meaningful.

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_7_url_state_sync" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_7_url_state_sync.done"`
</step>

<step name="phase2_8_url_state_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.8: URL state runtime probe (v2.7 Phase A)

→ `narrate_phase "Phase 2.8 — URL state runtime probe" "Click từng control + snapshot URL để verify declaration vs implementation"`

**Purpose:** verify that the static `interactive_controls` declarations
(checked at phase 2.7) match actual application behaviour. AI drives MCP
Playwright through every declared control, captures URL params before/after
each interaction, writes the result to
`${PHASE_DIR}/url-runtime-probe.json`. Validator reads that artifact and
flags coverage gaps (WARN) or declaration drift (BLOCK).

**Why:** static declarations close ~50% of URL-state bugs; runtime probe
catches the remaining drift class — declaration says `?status=...` but
the route handler ships `?state=...`, or the filter pretends to sync but
no `pushState` actually fires.

**Skip conditions:**
- No goal in TEST-GOALS.md has `interactive_controls.url_sync: true` → skip silently.
- `${RUN_ARGS}` contains `--skip-runtime` → run validator with the same flag (logs OD debt).
- Browser environment unavailable (no MCP Playwright) → invoke validator with `--skip-runtime`.

### 2.8a Drive the probe (AI agent task)

For every goal in `${PHASE_DIR}/TEST-GOALS.md` that declares
`interactive_controls.url_sync: true`:

1. Determine the goal's route from `${PHASE_DIR}/RUNTIME-MAP.json` (key
   matching the goal id) or, when the goal frontmatter carries an explicit
   `route:` field, prefer that.
2. Authenticate as `goal.actor` (default `admin`) using the standard
   review-phase auth helper.
3. Navigate to the route. Wait for the list/table/grid to be visible.
4. For every entry in the goal's `interactive_controls`:
   - **filter** — pick the first declared `values[0]`, click the filter
     control, snapshot URL, then prove visible rows and/or network response
     match the selected value. Example: `status=pending` must not show flagged,
     approved, rejected, or failed rows unless the contract explicitly says
     flagged is an orthogonal boolean.
   - **sort** — apply the first declared column, snapshot URL, then prove row
     order matches the declared direction.
   - **pagination** — click page 2 (or scroll once for `infinite-scroll`),
     snapshot URL, then prove the result window changed without duplicated
     first-page rows.
   - **search** — type a representative query, wait `debounce_ms + 100ms`,
     snapshot URL, then prove returned rows contain/match the query.
5. Also compare the observed route against `${PHASE_DIR}/CRUD-SURFACES.md`
   `platforms.web.list`: heading/description presence, declared table columns,
   row actions, empty/loading/error/unauthorized states where reachable, and
   delete confirmation if a delete action is declared.
6. Append one entry per goal to `url-runtime-probe.json`.

**Artifact schema** (`${PHASE_DIR}/url-runtime-probe.json`):

```json
{
  "generated_at": "2026-04-26T10:30:00Z",
  "goals": [
    {
      "goal_id": "G-01",
      "url": "/admin/campaigns",
      "controls": [
        {
          "kind": "filter",
          "name": "status",
          "value": "active",
          "url_before": "https://app.local:5173/admin/campaigns",
          "url_after": "https://app.local:5173/admin/campaigns?status=active",
          "url_params_after": {"status": "active"},
          "result_semantics": {
            "passed": true,
            "rows_checked": 20,
            "violations": []
          }
        }
      ]
    }
  ]
}
```

`kind` is one of `filter | sort | pagination | search`. `name` matches the
declared control name (or normalised — `page` for pagination, `search` for
search, `sort` for sort). `url_params_after` is the parsed search-param
dict. For filters, `result_semantics` is mandatory; URL-only success is not
enough because it misses the class where a Pending tab still renders Flagged
records.

### 2.8b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"

EXTRA_FLAGS=""
if [[ "${RUN_ARGS:-}" == *"--skip-runtime"* ]] || [[ -z "${VG_BROWSER_AVAILABLE:-1}" ]]; then
  EXTRA_FLAGS="--skip-runtime"
fi

"${PYTHON_BIN}" .claude/scripts/validators/verify-url-state-runtime.py \
  --phase "${PHASE_NUMBER}" ${EXTRA_FLAGS} \
  > "${PHASE_DIR}/.tmp/url-state-runtime.json" 2>&1
URL_RUNTIME_RC=$?

if [ "${URL_RUNTIME_RC}" != "0" ]; then
  if [[ "${RUN_ARGS:-}" == *"--allow-runtime-drift"* ]]; then
    "${PYTHON_BIN}" .claude/scripts/vg-orchestrator override \
      --flag skip-url-state-runtime \
      --reason "URL state runtime drift waived for ${PHASE_NUMBER} via --allow-runtime-drift (soft debt logged)"
    echo "⚠ URL state runtime drift waived via --allow-runtime-drift"
  else
    echo "⛔ URL state runtime drift detected — see ${PHASE_DIR}/.tmp/url-state-runtime.json"
    cat "${PHASE_DIR}/.tmp/url-state-runtime.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.url_state_runtime" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/url-state-runtime.json" \
        --out-md "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/url-state-runtime-diagnostic.md" 2>/dev/null || true
    fi
    echo ""
    echo "Fix options:"
    echo "  1. Implementation drift — fix the route handler / UI so declared url_param actually appears in URL after interaction."
    echo "  2. Declaration drift — declared url_param is wrong; update TEST-GOALS.md interactive_controls block."
    echo "  3. Override (last resort): re-run with --allow-runtime-drift (logs soft OD debt)."
    exit 2
  fi
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_8_url_state_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_8_url_state_runtime.done"`
</step>

<step name="phase2_9_error_message_runtime" profile="web-fullstack,web-frontend-only" mode="full">
## Phase 2.9: API error-message runtime lens

→ `narrate_phase "Phase 2.9 — API error-message runtime lens" "Trigger API error paths and prove toast/form errors show API body messages, not HTTP transport text"`

**Purpose:** catch the P3.2 class of bug where the backend returns a useful
domain/validation message but the frontend toast shows `Request failed with
status 403`, `statusText`, or another generic transport message.

This is a plugin/lens inside review, not a second full browser discovery pass.
Reuse the authenticated browser session and routes already discovered by
Phase 2. For each API+UI mutation or protected action that can safely fail,
drive one negative path and record API body + visible UI message.

### 2.9a Drive the probe

For API+UI phases:

1. Read `${PHASE_DIR}/INTERFACE-STANDARDS.md`, `${PHASE_DIR}/API-DOCS.md`,
   `${PHASE_DIR}/API-CONTRACTS.md`, and `${PHASE_DIR}/RUNTIME-MAP.json`.
2. Pick safe negative paths in this order:
   - validation error on create/update form
   - unauthorized/forbidden path for a role-gated action
   - domain rule error that does not mutate durable data
3. Capture the network response JSON for the failed request.
4. Capture visible toast/banner/form error text from the UI.
5. Compare using the standard message priority:
   `error.user_message -> error.message -> message -> network_fallback`.
6. Write `${PHASE_DIR}/error-message-probe.json`.

**Artifact schema**:

```json
{
  "generated_at": "2026-05-02T10:30:00Z",
  "checks": [
    {
      "goal_id": "G-01",
      "route": "/admin/billing/topup-queue",
      "action": "submit invalid filter or mutation",
      "request": {"method": "POST", "path": "/api/example"},
      "status": 400,
      "api_error": {
        "code": "VALIDATION_ERROR",
        "message": "Amount is required",
        "user_message": "Amount is required"
      },
      "api_user_message": "Amount is required",
      "visible_message": "Amount is required",
      "passed": true
    }
  ]
}
```

If a phase has API contracts and UI goals but no reachable negative path, write
the artifact with `checks: []` plus `blocked_reason`, then run the diagnostic.
Do not silently skip.

### 2.9b Run validator

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null

"${PYTHON_BIN}" .claude/scripts/validators/verify-error-message-runtime.py \
  --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.tmp/error-message-runtime.json" 2>&1
ERROR_MESSAGE_RC=$?

if [ "${ERROR_MESSAGE_RC}" != "0" ]; then
  echo "⛔ API error-message runtime lens failed — see ${PHASE_DIR}/.tmp/error-message-runtime.json"
  cat "${PHASE_DIR}/.tmp/error-message-runtime.json"
  DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
  if [ -f "$DIAG_SCRIPT" ]; then
    "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
      --gate-id "review.error_message_runtime" \
      --phase-dir "$PHASE_DIR" \
      --input "${PHASE_DIR}/.tmp/error-message-runtime.json" \
      --out-md "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" \
      >/dev/null 2>&1 || true
    cat "${PHASE_DIR}/.tmp/error-message-runtime-diagnostic.md" 2>/dev/null || true
  fi
  echo ""
  echo "Fix options:"
  echo "  1. Backend drift — return the standard API error envelope from INTERFACE-STANDARDS.md."
  echo "  2. Frontend drift — use shared error adapter: error.user_message || error.message, never statusText/AxiosError.message."
  echo "  3. Probe gap — rerun full review with a safe negative path and write error-message-probe.json."
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase2_9_error_message_runtime" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase2_9_error_message_runtime.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase2_9_error_message_runtime 2>/dev/null || true
```
</step>

<step name="phase3_fix_loop" mode="full">
## Phase 3: FIX LOOP (max 3 iterations)

→ `narrate_phase "Phase 3 — Fix loop (iteration ${I}/3)" "Sửa bug MINOR, escalate MODERATE/MAJOR"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase3_fix_loop >/dev/null 2>&1 || true
```

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

### 3e: Iter limit fallback — Diagnostic L2 (RFC v9 D11 + D26, PR-E)

When iter 3 exits with errors STILL remaining (loop hit cap without
self-resolving), do NOT silent-BLOCK. Spawn diagnostic_l2 single-advisory
fallback:

1. Capture residual evidence: list of unresolved error rows from
   RUNTIME-MAP + scan-*.json + recipe_executor logs.
2. Spawn isolated Haiku subagent (zero parent context — RFC v9 D11) to
   classify root cause `block_family` ∈ {schema_drift, validation_bug,
   auth_issue, db_constraint, business_logic, integration_failure,
   unknown}.
3. L2 generates `L2Proposal.json` with confidence + proposed_fix.
4. Present to user via single-advisory pattern (D26):
     - confidence ≥ 0.7  → "Đề xuất: <fix>. [Yes / chi tiết]"
     - confidence < 0.7  → 3-option block_resolve_l3_present (legacy)
5. **User gate is mandatory** — never auto-apply (per project policy).
6. User accept → apply fix → re-run iter 4 (one extra iteration grace).
7. User reject → BLOCK with full audit trail in
   `.l2-proposals/{proposal_id}.json` + DEFECT-LOG entry referencing
   the proposal.

```bash
if [ "${ITER:-1}" -eq 3 ] && [ -n "${REMAINING_ERRORS}" ] && \
   { [ -f "${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py" ] || [ -f "${REPO_ROOT}/scripts/spawn-diagnostic-l2.py" ]; }; then
  echo "━━━ Phase 3e — Diagnostic L2 fallback (iter 3 hit cap) ━━━"
  DIAGNOSTIC_L2="${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py"
  [ -f "$DIAGNOSTIC_L2" ] || DIAGNOSTIC_L2="${REPO_ROOT}/scripts/spawn-diagnostic-l2.py"
  L2_ARGS=(
    --phase "${PHASE_NUMBER}"
    --gate-id "review.fix_loop"
    --evidence-file "${PHASE_DIR}/.fix-loop-evidence.json"
  )
  L2_OUT=$("${PYTHON_BIN:-python3}" "$DIAGNOSTIC_L2" \
    "${L2_ARGS[@]}" 2>&1)
  L2_PROPOSAL_ID=$(echo "$L2_OUT" | ${PYTHON_BIN:-python3} -c "
import json, sys
try: print(json.loads(sys.stdin.read()).get('proposal_id',''))
except: print('')
")
  if [ -n "$L2_PROPOSAL_ID" ]; then
    echo "  L2 proposal generated: $L2_PROPOSAL_ID"
    # Open DEFECT-LOG entry referencing the proposal
    TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
    [ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
    if [ -f "$TESTER_PRO_CLI" ]; then
      "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" defect new \
        --phase "${PHASE_NUMBER}" \
        --title "[ITER-LIMIT] Fix loop hit max=3, L2 proposal $L2_PROPOSAL_ID" \
        --severity major --found-in review \
        --notes "L2 proposal at .l2-proposals/${L2_PROPOSAL_ID}.json — user decision pending" \
        2>&1 | sed 's/^/  /' || true
    fi
    # User gate is provider-native after spawn-diagnostic-l2.py:
    # Claude Code uses AskUserQuestion; Codex asks in the main thread/UI.
    # On accept → run-complete sees applied; on reject → BLOCK below.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.diagnostic_l2_spawned" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"proposal_id\":\"$L2_PROPOSAL_ID\"}" \
      >/dev/null 2>&1 || true
  fi
fi
```

> **Tại sao không tự apply L2 fix**: L2 đã sai trong dogfood 3.2
> (propose fix giả mà có vẻ hợp lý). User gate là single source of truth
> cho fix correctness. Audit trail (`.l2-proposals/`) cho phép trace
> sau-incident: proposal nào được accept/reject, fix tham chiếu commit nào.
</step>

<step name="phase4_goal_comparison" mode="full">
## Phase 4: GOAL COMPARISON

→ `narrate_phase "Phase 4 — Goal comparison" "So khớp ${N} goals từ TEST-GOALS với views đã khám phá"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase4_goal_comparison >/dev/null 2>&1 || true
```

### 4.0: RCRURD runtime verification (Task 23 — Codex GPT-5.5 review 2026-05-03)

For every TEST-GOALS/G-NN.md with `goal_type: mutation`, run the runtime
gate. BLOCK review on assertion fail (R8 update_did_not_apply, etc).
Action payload comes from per-phase fixture (`FIXTURES/G-NN.action.json`).

```bash
EVIDENCE_DIR="${PHASE_DIR}/.rcrurd-evidence"
mkdir -p "$EVIDENCE_DIR"
RCRURD_FAILED=0
RCRURD_RAN=0

if [ -d "${PHASE_DIR}/TEST-GOALS" ]; then
  for goal in "${PHASE_DIR}/TEST-GOALS"/G-*.md; do
    [ -f "$goal" ] || continue
    grep -qE "goal_type:[[:space:]]*mutation" "$goal" || continue
    RCRURD_RAN=$((RCRURD_RAN+1))
    ev_out="${EVIDENCE_DIR}/$(basename "$goal" .md).json"

    payload="{}"
    fixture="${PHASE_DIR}/FIXTURES/$(basename "$goal" .md).action.json"
    [ -f "$fixture" ] && payload=$(cat "$fixture")

    "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rcrurd-runtime.py \
      --goal-file "$goal" \
      --phase "${PHASE_NUMBER}" \
      --action-payload "$payload" \
      --auth-header "$(vg_config_get review.rcrurd_auth_header '')" \
      --evidence-out "$ev_out" || RCRURD_FAILED=1
  done
fi

if [ "$RCRURD_RAN" -gt 0 ]; then
  if [ "$RCRURD_FAILED" = "1" ]; then
    echo "⛔ Phase 4.0 RCRURD runtime — at least one mutation goal failed (of ${RCRURD_RAN} run)"
    echo "   Evidence: ${EVIDENCE_DIR}/*.json"
    echo "   Route through classifier (Task 7) — most are IN_SCOPE for current phase"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.rcrurd_runtime_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\",\"goals_run\":${RCRURD_RAN}}" \
      2>/dev/null || true
    exit 1
  fi

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.rcrurd_runtime_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_run\":${RCRURD_RAN}}" \
    2>/dev/null || true
fi
```

### 4a: Load Goals + edge cases

Read `${PHASE_DIR}/TEST-GOALS.md` (generated by /vg:blueprint).
If missing → generate from CONTEXT.md + API-CONTRACTS.md (fallback).

**P1 v2.49+ — Edge case variants:** also load `${PHASE_DIR}/EDGE-CASES/G-NN.md`
per goal. Status format extended:
- Old: `G-04: PASS` / `G-04: FAIL` / `G-04: NOT_TESTED`
- New: `G-04: PASS (5/6 variants — G-04-c1 NOT_TESTED [needs concurrency harness])`

For each variant in EDGE-CASES/G-NN.md:
- Replay `start_view` (per RUNTIME-MAP) with variant's input
- Verify expected_outcome matches actual UI/API response
- Mark per-variant: PASS | FAIL | NOT_TESTED (with reason)
- Aggregate to goal status (goal PASS only when all critical/high variants PASS)

Skip variants when:
- EDGE-CASES file missing (legacy phase pre-v2.49) → emit
  `review.edge_cases_unavailable` (severity=warn) + treat goal as 1-variant
- Variant priority=low + `--skip-low-edge-cases` flag set
- No-CRUD phase (CRUD-SURFACES.resources empty) → no variants expected

Emit per gate-blocked variant: `review.edge_case_variant_blocked` with
`{goal_id, variant_id, reason}` payload.

Parse goals: ID, description, success criteria, mutation evidence, dependencies, priority.

**Surface classification (v1.9.1 R1 — lazy migration, runs BEFORE browser discover decisions):**

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
# rc=2 → provider-native cheap classifier
#        Claude: Haiku Task per row; Codex: read-only scanner adapter over pending TSV
# rc=3 → provider-native prompt (surface list from config), then classify_goals_apply
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

  # v2.48.1 (Issue #85) — backfill synthetic goal_sequences[gid] for non-UI
  # goals from probe results so verify-matrix-evidence-link.py (which only
  # inspects RUNTIME-MAP goal_sequences[]) sees backend evidence. Closes the
  # surface-probe schema gap that BLOCKed Phase 3.2 dogfood with 32 non-UI
  # READY goals flagged matrix_status_without_runtime_sequence.
  # Idempotent: re-runs overwrite synthetic entries by gid, never overwrites
  # real browser-recorded sequences.
  if [ -f "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" ]; then
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/backfill-surface-probe-runtime.py" \
      --phase-dir "$PHASE_DIR" 2>&1 | sed 's/^/▸ /' || true
  fi
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
# OHOK-8 round-4 Codex fix: replace pseudocode with real bash grep.
# Previously `count goals where status == "NOT_SCANNED"` was not executable
# → gate couldn't run → NOT_SCANNED goals slipped through unresolved.
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
NOT_SCANNED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*NOT_SCANNED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
FAILED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*FAILED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
INTERMEDIATE=$((NOT_SCANNED_COUNT + FAILED_COUNT))
# Build the list of intermediate goal IDs (used later in override auto-convert)
INTERMEDIATE_GOALS=$(grep -oE '^\| (G-[0-9]+)[^|]*\|[^|]*\|[^|]*\|[[:space:]]*(NOT_SCANNED|FAILED)[[:space:]]*\|' "$MATRIX" 2>/dev/null \
  | grep -oE 'G-[0-9]+' | sort -u | tr '\n' ' ')

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
    # If L1 fails, L2 architect proposal is presented through provider-native L3 prompt.
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
    # OHOK-8 round-4 Codex fix: update_goal_status was undefined function.
    # Replaced with real bash sed that rewrites matrix row in-place.
    # Auto-convert intermediate → UNREACHABLE với audit trail.
    TS=$(date -u +%FT%TZ)
    for gid in $INTERMEDIATE_GOALS; do
      # Match row `| G-XX |...|...|...| (NOT_SCANNED|FAILED) |`, replace
      # status column only. Preserve other columns. Use | delimiter in sed
      # to avoid conflicts with pipe chars in evidence.
      sed -i -E "s|^(\| ${gid} \|[^|]+\|[^|]+\|[^|]+\|)[[:space:]]*(NOT_SCANNED\|FAILED)[[:space:]]*\|(.*)$|\1 UNREACHABLE |review-skip-\2 @${TS}\3|" \
        "$MATRIX" 2>/dev/null || true
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

# Defense-in-depth: matrix-merger now downgrades shallow mutation sequences, but
# keep an explicit validator so legacy/hand-written RUNTIME-MAP files cannot
# mark create/update/delete goals READY from list-only evidence.
CRUD_DEPTH_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-runtime-map-crud-depth.py"
if [ -f "$CRUD_DEPTH_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_DEPTH_VAL" --phase "${PHASE_NUMBER}" \
    > "${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json" 2>&1
  CRUD_DEPTH_RC=$?
  if [ "$CRUD_DEPTH_RC" != "0" ]; then
    echo "⛔ Runtime map CRUD depth gate failed — see ${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json"
    echo "   Mutation goals require observed POST/PUT/PATCH/DELETE + persistence proof."
    echo "   Re-run /vg:review ${PHASE_NUMBER} with deeper CRUD interaction before /vg:test."
    exit 1
  fi
fi

# v2.35.0 verdict gate hardening (closes #51) — 3 invariants replacing path-existence checks
# Override per-phase: --skip-content-invariants=<reason> logs OVERRIDE-DEBT
if [[ ! "$ARGUMENTS" =~ --skip-content-invariants ]]; then
  for VALIDATOR in verify-interface-standards verify-goal-security verify-goal-perf verify-security-baseline verify-haiku-scan-completeness verify-runtime-map-coverage verify-crud-runs-coverage verify-error-message-runtime; do
    VAL_PATH="${REPO_ROOT}/.claude/scripts/validators/${VALIDATOR}.py"
    if [ -f "$VAL_PATH" ]; then
      mkdir -p "${PHASE_DIR}/.tmp"
      VAL_OUT="${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic-input.txt"
      case "$VALIDATOR" in
        verify-interface-standards)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" > "$VAL_OUT" 2>&1
          ;;
        verify-error-message-runtime)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-goal-security|verify-goal-perf)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-security-baseline)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --scope all > "$VAL_OUT" 2>&1
          ;;
        *)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase-dir "$PHASE_DIR" > "$VAL_OUT" 2>&1
          ;;
      esac
      VAL_RC=$?
      cat "$VAL_OUT"
      if [ "$VAL_RC" -ne 0 ]; then
        echo ""
        echo "⛔ Verdict gate invariant FAILED: ${VALIDATOR}"
        echo "   v2.35.0 hardened gate: review cannot PASS with empty/incomplete artifacts."
        echo "   Either re-run /vg:review ${PHASE_NUMBER} with proper scanner/dispatch coverage,"
        echo "   or pass --skip-content-invariants=\"<reason>\" to log OVERRIDE-DEBT."
        DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.${VALIDATOR}" \
            --phase-dir "$PHASE_DIR" \
            --input "$VAL_OUT" \
            --out-md "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" 2>/dev/null || true
        fi
        emit_telemetry_v2 "review_verdict_invariant_failed" "${PHASE_NUMBER}" \
          "review.4-verdict" "${VALIDATOR}" "BLOCK" "{}" 2>/dev/null || true
        exit 1
      fi
    fi
  done
fi

LENS_PLAN_SCRIPT="${REPO_ROOT}/.claude/scripts/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ] && [[ ! "$ARGUMENTS" =~ --skip-lens-plan-gate ]]; then
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --validate-only \
    --json \
    > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1
  LENS_GATE_RC=$?
  if [ "$LENS_GATE_RC" -ne 0 ]; then
    echo ""
    echo "⛔ Review lens plan gate FAILED — required checklist plugins lack evidence."
    echo "   See ${PHASE_DIR}/.tmp/review-lens-plan-validation.json"
    DIAG_SCRIPT="${REPO_ROOT}/.claude/scripts/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.lens_plan_gate" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
        --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
    fi
    echo "   Re-run /vg:review ${PHASE_NUMBER} --mode=full --force so API docs, browser inventory, URL-state/filter/paging, error-message, visual, and findings lenses execute."
    exit 1
  fi
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

<step name="unreachable_triage" mode="full">
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

<step name="crossai_review" mode="full">
## CrossAI Review (mandatory when CLIs are configured)

**If config.crossai_clis is empty, emit an explicit skip note and continue.**
**If --skip-crossai is present, it must have override-debt evidence because
objective review is otherwise a silent quality downgrade.**

Prepare context with RUNTIME-MAP + GOAL-COVERAGE-MATRIX + TEST-GOALS.
Set `$LABEL="review-check"`. Follow crossai-invoke.md.

Required evidence when not skipped:
- `${PHASE_DIR}/crossai/review-check.xml`
- `crossai.verdict` telemetry event
</step>

<step name="write_artifacts" mode="full">
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

<step name="bootstrap_reflection" mode="full">
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

**v2.6.1 (2026-04-26): Auto-resolve hotfix debt entries from prior phases.**

If THIS phase's review ran clean (no `--allow-orthogonal-hotfix` /
`--allow-no-bugref` / `--allow-empty-bugfix` overrides hit), prior phases'
OPEN debt entries with matching gate_id auto-resolve. Closes AUDIT.md D2 H4
(hotfix overrides had no natural resolution path → debt piled up forever).

Each gate_id maps to a specific re-run condition that the current clean
review proves: if review passed without orthogonal-hotfix override, the
"goal-coverage" condition is satisfied for prior phases too.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
if type -t override_auto_resolve_clean_run >/dev/null 2>&1; then
  # Only resolve if THIS phase didn't fall back to the override itself
  if [[ ! "${ARGUMENTS}" =~ --allow-orthogonal-hotfix ]]; then
    override_auto_resolve_clean_run "review-goal-coverage" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-no-bugref ]]; then
    override_auto_resolve_clean_run "bugfix-bugref-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-bugfix ]]; then
    override_auto_resolve_clean_run "bugfix-code-delta-required" "${PHASE_NUMBER}" \
      "review-clean-${PHASE_NUMBER}-$(date -u +%s)" 2>&1 | sed 's/^/  /'
  fi
fi
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
     # Edit affected files (paths above), then stage + commit as SEPARATE
     # steps (v2.5.2.7: don't chain staging with commit — if commit-msg
     # hook BLOCKs on missing citation, prior `git add` success gets
     # masked by the red "Exit 1" UI label):
     git add path/to/fixed-file.ts              # stage intentional files
     git commit -m "fix({phase}-XX): {summary}

Per CONTEXT.md D-XX OR Per API-CONTRACTS.md"  # body must cite
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


```bash
# v2.2 — complete step marker + terminal emit + run-complete
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review 0_parse_and_validate 2>/dev/null || true
READY_COUNT=$(grep -c "READY" "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo 0)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_ready\":${READY_COUNT}}" >/dev/null

# v2.38.0 — Flow compliance audit
if [[ "$ARGUMENTS" =~ --skip-compliance=\"([^\"]*)\" ]]; then
  COMP_REASON="${BASH_REMATCH[1]}"
else
  COMP_REASON=""
fi
COMP_SEV=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
COMP_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "review" "--severity" "$COMP_SEV" )
[ -n "$COMP_REASON" ] && COMP_ARGS+=( "--skip-compliance=$COMP_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMP_ARGS[@]}"
COMP_RC=$?
if [ "$COMP_RC" -ne 0 ] && [ "$COMP_SEV" = "block" ]; then
  echo "⛔ Review flow compliance failed. See .flow-compliance-review.yaml or pass --skip-compliance=\"<reason>\"."
  exit 1
fi

# v2.45 fail-closed-validators PR: matrix↔runtime evidence cross-check.
# Phase 3.2 dogfood found GOAL-COVERAGE-MATRIX.md fabricating READY status
# even when goal_sequences[].result == "blocked" or sequence missing entirely.
# This validator catches the fabrication BEFORE review exits, so /vg:test
# never sees a lying matrix.
MATRIX_LINK_VAL=".claude/scripts/validators/verify-matrix-evidence-link.py"
if [ -f "$MATRIX_LINK_VAL" ]; then
  ${PYTHON_BIN:-python3} "$MATRIX_LINK_VAL" --phase-dir "$PHASE_DIR" --severity block
  MATRIX_LINK_RC=$?
  if [ "$MATRIX_LINK_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_evidence_link_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-evidence-link-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_evidence_link",
  "summary": "Review matrix-evidence-link gate failed — GOAL-COVERAGE-MATRIX.md asserts goal status that runtime evidence does not support",
  "fix_hint": "1. Re-run /vg:review ${PHASE_NUMBER} --retry-failed (record real sequences); 2. OR reclassify goals to UNREACHABLE/INFRA_PENDING/DEFERRED with justification"
}
JSON
    blocking_gate_prompt_emit "matrix_evidence_link" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# RFC v9 PR-D2 Codex-HIGH-1 fix: post_state lifecycle gate AFTER scanner ran.
# Pre_state checked at Phase 0.5 (pre-scanner); post_state must verify the
# action actually mutated state correctly. Without this leg, RCRURD is half-
# wired (Codex review found pre-only).
# Re-resolve base URL from config (PRE_BASE local to Phase 0.5; not in scope).
# Codex-R4-HIGH-2 fix: read base_url from ENV-CONTRACT.md (canonical),
# not from vg.config.md step_env (env NAME, not URL).
POST_BASE_RC=$("${PYTHON_BIN:-python3}" -c "
import re
try:
    text = open('${PHASE_DIR}/ENV-CONTRACT.md', encoding='utf-8').read()
    m = re.search(r'^target:\s*\n((?:[ \t].*\n)+)', text, re.MULTILINE)
    if m:
        bm = re.search(r'^\s*base_url:\s*[\"\\']?([^\"\\'\s#]+)', m.group(1), re.MULTILINE)
        if bm: print(bm.group(1))
except FileNotFoundError: pass
" 2>/dev/null)
[ -z "$POST_BASE_RC" ] && POST_BASE_RC="${VG_BASE_URL:-}"
HAS_POST_LIFECYCLE=$(grep -lE '^\s*post_state:' "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
# Codex-HIGH-5-bis fix: post_state setup error blocks even without runner exec
if [ "$HAS_POST_LIFECYCLE" -gt 0 ] && [ -z "$POST_BASE_RC" ] && \
   [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
  echo "⛔ RCRURD post_state setup error — FIXTURES declare post_state"
  echo "   blocks but no sandbox base_url available at run-complete."
  exit 1
fi
VG_SCRIPT_ROOT="${REPO_ROOT}/.claude/scripts"
[ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] || VG_SCRIPT_ROOT="${REPO_ROOT}/scripts"
if [ -f "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" ] && \
   [ -d "${PHASE_DIR}/FIXTURES" ] && [ -n "$POST_BASE_RC" ]; then
  # Codex-HIGH-1-ter fix: snapshot must exist when delta assertions present
  POST_NEEDS_SNAP=$(grep -lE 'increased_by_at_least|decreased_by_at_least' \
    "${PHASE_DIR}/FIXTURES"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
  if [ "$POST_NEEDS_SNAP" -gt 0 ] && [ ! -f "${PHASE_DIR}/.rcrurd-pre-snapshot.json" ] && \
     [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    echo "⛔ RCRURD post_state — pre-snapshot missing but ${POST_NEEDS_SNAP}"
    echo "   fixture(s) declare delta assertions. Pre-mode at Phase 0.5"
    echo "   should have captured it. Re-run /vg:review from scratch."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_snapshot_missing" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  POST_OUT=$("${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT}/rcrurd-preflight.py" \
    --phase "$PHASE_NUMBER" --base-url "$POST_BASE_RC" \
    --mode post --severity "${VG_RCRURD_POST_SEVERITY:-block}" \
    --pre-snapshot "${PHASE_DIR}/.rcrurd-pre-snapshot.json" 2>&1)
  POST_RC=$?
  echo "▸ RCRURD post_state: $(echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get("verdict","?")
    if v == "BLOCK":
        print(f"BLOCK ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} post-state assertions failed)")
    elif v == "WARN":
        print(f"WARN ({d.get(\"failed\",0)}/{d.get(\"checked\",0)} failed)")
    elif v == "PASS":
        print(f"PASS ({d.get(\"checked\",0)} fixtures)")
    else:
        print(f"ERROR: {d.get(\"error\",\"unknown\")[:200]}")
except: print("parse-error")
')"
  if [ "$POST_RC" -eq 2 ]; then
    echo "⛔ RCRURD post_state setup error — cannot proceed:"
    echo "$POST_OUT" | "${PYTHON_BIN:-python3}" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(f"   {d.get(\"error\",\"unknown\")[:300]}")
except: print("   (could not parse error)")
'
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_setup_error" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if [ "$POST_RC" -eq 1 ] && [ "${VG_RCRURD_POST_SEVERITY:-block}" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_post_state_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-post-state-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_post_state",
  "summary": "RCRURD post_state gate BLOCK — fixture lifecycle assertions failed after the scanner action. State did not transition as expected.",
  "fix_hint": "Re-run scanner if action genuinely succeeded; or fix the action's expected_network/post_state assertion drift."
}
JSON
    blocking_gate_prompt_emit "rcrurd_post_state" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2 matrix-staleness final gate: after matrix is BUILT (Phase 4),
# re-run staleness validator at review-complete time. Step 0 entry pass catches
# stale entries from PRIOR runs; this catches stale entries created by THIS run
# (e.g. scanner recorded sequence but skipped submit, then matrix wrote READY).
# Phase 3.2 dogfood found 36/39 mutation goals stale despite verdict=PASS.
MATRIX_STALE_VAL=".claude/scripts/validators/verify-matrix-staleness.py"
if [ -f "$MATRIX_STALE_VAL" ]; then
  STALE_SEV="block"
  [[ "${ARGUMENTS}" =~ --allow-stale-matrix ]] && STALE_SEV="warn"
  ${PYTHON_BIN:-python3} "$MATRIX_STALE_VAL" --phase "${PHASE_NUMBER}" --severity "$STALE_SEV"
  STALE_RC=$?
  if [ "$STALE_RC" -ne 0 ] && [ "$STALE_SEV" = "block" ]; then
    SUSPECTED_N=$(${PYTHON_BIN:-python3} -c "
import json
try: print(json.load(open('${PHASE_DIR}/.matrix-staleness.json'))['suspected_count'])
except: print('?')
")
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.matrix_staleness_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"suspected\":${SUSPECTED_N}}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/matrix-staleness-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "matrix_staleness",
  "summary": "Matrix-staleness gate failed — ${SUSPECTED_N} mutation goal(s) marked READY without submit/2xx evidence",
  "fix_hint": "1. /vg:review ${PHASE_NUMBER} --retry-failed; 2. /vg:review ${PHASE_NUMBER} --re-scan-goals=G-XX,G-YY; 3. /vg:review ${PHASE_NUMBER} --dogfood; 4. /vg:review ${PHASE_NUMBER} --allow-stale-matrix --override-reason=... (debt)"
}
JSON
    blocking_gate_prompt_emit "matrix_staleness" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46-wave3.2.3 (RFC v9 D10) — evidence provenance gate. Mutation steps
# claiming success (action + 2xx network) MUST carry structured evidence:
# {source, artifact_hash, captured_at, schema_version, scanner_run_id |
# layer2_proposal_id}. Closes the trust hole where executor agents could
# fabricate evidence to flip matrix-staleness bidirectional sync.
#
# Codex-HIGH-4 fix: default to BLOCK (was warn). Migration grace via
# explicit `review.provenance.enforcement: warn` in vg.config.md OR
# --allow-legacy-provenance flag for phases pre-dating RFC v9.
PROV_VAL=".claude/scripts/validators/verify-evidence-provenance.py"
if [ -f "$PROV_VAL" ]; then
  # Resolve enforcement from config — env var wins, then grep config, default block
  PROV_MODE="${VG_PROVENANCE_ENFORCEMENT:-}"
  if [ -z "$PROV_MODE" ] && [ -n "${CONFIG_RAW:-}" ]; then
    PROV_MODE=$(echo "$CONFIG_RAW" | grep -A2 '^review:' | grep -E '^\s*provenance:' -A2 | \
                grep -E '^\s*enforcement:' | head -1 | sed 's/.*enforcement:\s*//;s/[\"'\'']//g' | tr -d ' ')
  fi
  [ -z "$PROV_MODE" ] && PROV_MODE="block"
  PROV_FLAGS="--severity ${PROV_MODE}"
  # During migration window, allow legacy phases without provenance
  [[ "${ARGUMENTS}" =~ --allow-legacy-provenance ]] && PROV_FLAGS="$PROV_FLAGS --allow-legacy"
  ${PYTHON_BIN:-python3} "$PROV_VAL" --phase "${PHASE_NUMBER}" $PROV_FLAGS
  PROV_RC=$?
  if [ "$PROV_RC" -ne 0 ] && [ "$PROV_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.evidence_provenance_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/evidence-provenance-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "evidence_provenance",
  "summary": "Evidence provenance gate failed — mutation steps claim success without structured provenance object (RFC v9 D10). Possible fabricated evidence.",
  "fix_hint": "1. Re-run scanner: /vg:review ${PHASE_NUMBER} --retry-failed; 2. For legacy phases: --allow-legacy-provenance; 3. Set review.provenance.enforcement: warn in vg.config.md to defer enforcement"
}
JSON
    blocking_gate_prompt_emit "evidence_provenance" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 anti-performative-review: ép scanner phải submit mutation goals,
# không được Cancel modal rồi mark passed. Phase 3.2 dogfood (2026-05-01) tìm
# 5 false-pass goals (G-31/G-34/G-35/G-44/G-52) modal opened nhưng chưa bao giờ
# submit. Validator này check goal_sequences.steps[] có submit click + 2xx
# network entry trước khi cho phép run-complete.
MUT_SUBMIT_VAL=".claude/scripts/validators/verify-mutation-actually-submitted.py"
if [ -f "$MUT_SUBMIT_VAL" ]; then
  MUT_FLAGS="--severity block"
  if [[ "${ARGUMENTS}" =~ --allow-cancel-only-mutations ]]; then
    MUT_FLAGS="--severity block --allow-cancel-only-mutations"
  fi
  ${PYTHON_BIN:-python3} "$MUT_SUBMIT_VAL" --phase "${PHASE_NUMBER}" $MUT_FLAGS
  MUT_RC=$?
  if [ "$MUT_RC" -ne 0 ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.mutation_submit_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/mutation-submit-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "mutation_submit",
  "summary": "Review mutation-actually-submitted gate failed — mutation goals marked passed without actual submit click + 2xx network",
  "fix_hint": "Re-run /vg:review ${PHASE_NUMBER} with scanner prompt requiring SUBMIT, or use --allow-cancel-only-mutations override (logs OVERRIDE-DEBT)"
}
JSON
    blocking_gate_prompt_emit "mutation_submit" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 Phase 6 enrichment: traceability + RCRURD enforcement.
# Closes "AI bịa goal/decision/business-rule" + "scanner stops too early".
# Migration: VG_TRACEABILITY_MODE=warn for pre-2026-05-01 phases (set in
# vg.config.md). New phases default to block.
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"

# v2.46 L4 — RCRURD step depth (per goal_class threshold)
RCRURD_VAL=".claude/scripts/validators/verify-rcrurd-depth.py"
if [ -f "$RCRURD_VAL" ]; then
  RCRURD_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-shallow-scans ]] && RCRURD_FLAGS="$RCRURD_FLAGS --allow-shallow-scans"
  ${PYTHON_BIN:-python3} "$RCRURD_VAL" --phase "${PHASE_NUMBER}" $RCRURD_FLAGS
  RCRURD_RC=$?
  if [ "$RCRURD_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.rcrurd_depth_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/rcrurd-depth-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "rcrurd_depth",
  "summary": "RCRURD depth gate failed — scanner stopped too early on mutation goals",
  "fix_hint": "See scanner-report-contract.md 'RCRURD Lifecycle Protocol'. Goal class drives min steps."
}
JSON
    blocking_gate_prompt_emit "rcrurd_depth" "$EVIDENCE_PATH" "warn"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — asserted_quote vs business rule similarity
ASSERTED_VAL=".claude/scripts/validators/verify-asserted-rule-match.py"
if [ -f "$ASSERTED_VAL" ]; then
  ASSERTED_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-asserted-drift ]] && ASSERTED_FLAGS="$ASSERTED_FLAGS --allow-asserted-drift"
  ${PYTHON_BIN:-python3} "$ASSERTED_VAL" --phase "${PHASE_NUMBER}" $ASSERTED_FLAGS
  ASSERTED_RC=$?
  if [ "$ASSERTED_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.asserted_drift_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

    source scripts/lib/blocking-gate-prompt.sh
    EVIDENCE_PATH="${PHASE_DIR}/.vg/asserted-drift-evidence.json"
    mkdir -p "$(dirname "$EVIDENCE_PATH")"
    cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "asserted_drift",
  "summary": "Asserted-rule-match gate failed — scanner asserted_quote drifts from BR-NN text",
  "fix_hint": "Align scanner asserted_quote fields with the business rule text in BUSINESS-RULES.md or use --allow-asserted-drift override"
}
JSON
    blocking_gate_prompt_emit "asserted_drift" "$EVIDENCE_PATH" "error"
    # AI controller calls AskUserQuestion → resolve via Leg 2.
    # Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
  fi
fi

# v2.46 L4 — replay-evidence (structural + optional curl replay)
REPLAY_VAL=".claude/scripts/validators/verify-replay-evidence.py"
if [ -f "$REPLAY_VAL" ]; then
  REPLAY_FLAGS="--severity warn"  # default warn — auth fixture not always available
  [[ "${ARGUMENTS}" =~ --enable-replay ]] && REPLAY_FLAGS="--severity ${TRACE_MODE} --enable-replay"
  ${PYTHON_BIN:-python3} "$REPLAY_VAL" --phase "${PHASE_NUMBER}" $REPLAY_FLAGS
  REPLAY_RC=$?
  if [ "$REPLAY_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ] && [[ "${ARGUMENTS}" =~ --enable-replay ]]; then
    echo "⛔ Replay-evidence gate failed — scanner network claims can't be verified."
    exit 1
  fi
fi

# v2.46 L4 — cross-phase decision validity (D-XX from earlier phase still active)
CROSS_VAL=".claude/scripts/validators/verify-cross-phase-decision-validity.py"
if [ -f "$CROSS_VAL" ]; then
  CROSS_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-stale-decisions ]] && CROSS_FLAGS="$CROSS_FLAGS --allow-stale-decisions"
  ${PYTHON_BIN:-python3} "$CROSS_VAL" --phase "${PHASE_NUMBER}" $CROSS_FLAGS
  CROSS_RC=$?
  if [ "$CROSS_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Cross-phase decision validity failed — goal cites revoked/missing D-XX."
    exit 1
  fi
fi

# v2.46 L6 — adversarial scanner-business-alignment verifier
# Two-phase: emit prompts → orchestrator spawns Haiku verifier per prompt →
# re-run validator with --verifier-results to gate.
ALIGN_VAL=".claude/scripts/validators/verify-scanner-business-alignment.py"
if [ -f "$ALIGN_VAL" ]; then
  PROMPTS_FILE="${PHASE_DIR}/.tmp/business-alignment-prompts.jsonl"
  RESULTS_FILE="${PHASE_DIR}/.tmp/business-alignment-results.jsonl"
  mkdir -p "$(dirname "$PROMPTS_FILE")" 2>/dev/null
  ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" --prompts-out "$PROMPTS_FILE" 2>&1 | head -3
  PROMPT_COUNT=$(wc -l < "$PROMPTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

  if [ "$PROMPT_COUNT" -gt 0 ]; then
    echo ""
    echo "📋 Business alignment verifier needs ${PROMPT_COUNT} adversarial check(s)."
    echo "   Orchestrator should spawn isolated Haiku per prompt + write JSONL results to:"
    echo "     ${RESULTS_FILE}"
    echo "   Then re-run review with --verifier-results=${RESULTS_FILE}"
    echo ""
    # If results file exists from prior orchestrator pass, gate now
    if [ -f "$RESULTS_FILE" ]; then
      ALIGN_FLAGS="--severity ${TRACE_MODE} --verifier-results ${RESULTS_FILE}"
      [[ "${ARGUMENTS}" =~ --allow-business-drift ]] && ALIGN_FLAGS="$ALIGN_FLAGS --allow-business-drift"
      ${PYTHON_BIN:-python3} "$ALIGN_VAL" --phase "${PHASE_NUMBER}" $ALIGN_FLAGS
      ALIGN_RC=$?
      if [ "$ALIGN_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
        echo "⛔ Business alignment gate failed — adversarial verifier flagged drift."
        exit 1
      fi
    fi
  fi
fi

# RFC v9 D21 — DEFECT-LOG.md generation (tester pro).
# After GOAL-COVERAGE-MATRIX is final, parse the matrix and create one
# Defect entry per goal with status ∈ {BLOCKED, UNREACHABLE, FAILED, SUSPECTED}
# that does NOT already have an open defect in .tester-pro/defects.json.
# Severity inferred from priority + block_family heuristics.
TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ] && [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
  echo "━━━ D21 — Defect log generation ━━━"
  TESTER_PRO_CLI="$TESTER_PRO_CLI" ${PYTHON_BIN:-python3} - <<'PYDEFECT' 2>&1 | sed 's/^/  D21: /' || true
import json, os, re, subprocess, sys
phase_dir = os.environ['PHASE_DIR']
phase_no = os.environ['PHASE_NUMBER']
matrix = open(os.path.join(phase_dir, 'GOAL-COVERAGE-MATRIX.md'),
              encoding='utf-8').read()
cli = os.environ.get(
    'TESTER_PRO_CLI',
    os.path.join(os.environ['REPO_ROOT'], 'scripts', 'tester-pro-cli.py'),
)
# Parse rows `| G-XX | priority | surface | STATUS | evidence |`
row_re = re.compile(
    r"^\|\s*(G-[\w.-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
    r"\s*([A-Z_]+)\s*\|\s*(.+?)\s*\|", re.MULTILINE,
)
fail_states = {"BLOCKED", "UNREACHABLE", "FAILED", "SUSPECTED"}
# Load existing open defects to skip duplicates by (goal, title-prefix)
defects_path = os.path.join(phase_dir, '.tester-pro', 'defects.json')
existing = []
if os.path.exists(defects_path):
    try: existing = json.load(open(defects_path, encoding='utf-8'))
    except: pass
def is_open_for(gid, title_prefix):
    return any(
        d.get('related_goals') and gid in d['related_goals']
        and d.get('title','').startswith(title_prefix)
        and not d.get('closed_at')
        for d in existing
    )
opened = 0
for m in row_re.finditer(matrix):
    gid, prio, surf, status, ev = m.groups()
    if status not in fail_states:
        continue
    title_prefix = f"[{status}]"
    if is_open_for(gid, title_prefix):
        continue
    # Severity heuristic: critical priority → critical; backend mutation → major;
    # else minor.
    prio_l = prio.strip().lower()
    surf_l = surf.strip().lower()
    if prio_l == 'critical':
        sev = 'critical'
    elif any(s in surf_l for s in ('api', 'data', 'integration')):
        sev = 'major'
    else:
        sev = 'minor'
    title = f"[{status}] {gid} — {ev[:80]}"
    cmd = [
        sys.executable, cli, 'defect', 'new',
        '--phase', phase_no, '--title', title,
        '--severity', sev, '--found-in', 'review',
        '--goals', gid,
        '--notes', f"surface={surf} priority={prio} status={status}. Auto-opened from GOAL-COVERAGE-MATRIX.",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        opened += 1
print(f"opened {opened} new defect(s) from matrix")
PYDEFECT
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ review run-complete BLOCK — review orchestrator output + fix before /vg:test" >&2
  exit $RUN_RC
fi
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
