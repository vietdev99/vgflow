---
name: "vg-next"
description: "Auto-detect current V5 pipeline step and advance to the next"
metadata:
  short-description: "Auto-detect current V5 pipeline step and advance to the next"
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

Invoke this skill as `$vg-next`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Detect current position in the 7-step phase pipeline and immediately invoke the next command.

Pipeline order: specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="load_config">
**Config:** Read .claude/commands/vg/_shared/config-loader.md first.
</step>

<step name="detect_state">
Read `${PLANNING_DIR}/STATE.md` and `${PLANNING_DIR}/ROADMAP.md`.

Extract `current_phase` and `phase_dir`.

If `${PLANNING_DIR}/` does not exist or STATE.md is missing:
  - Output: "No VG project detected. Run /vg:project to initialize."
  - STOP.
</step>

<step name="detect_pipeline_position">
**Phase reconnaissance — recon-driven routing (replaces binary file-exists checks).**

Follow `.claude/commands/vg/_shared/phase-recon.md`.

```bash
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet

PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
NEXT_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
HAS_PRE_ACTION=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print('yes' if s['recommended_action'].get('pre_action') else 'no')
")
```

**Route 0 (priority):** `STATE.md` shows `paused_at` field
→ Read PIPELINE-STATE.json. Resume logic (tightened 2026-04-17 — field-specific):

```bash
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
if [ -f "$PIPELINE_STATE" ]; then
  # Priority 1: find first step with status == "in_progress" (explicit pause)
  RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
for st in order:
    if steps.get(st, {}).get('status') == 'in_progress':
        print(st); break
")
  # Priority 2: if no in_progress, find last step with status == "done", resume from next
  if [ -z "$RESUME_STEP" ]; then
    RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
last_done = -1
for i, st in enumerate(order):
    if steps.get(st, {}).get('status') == 'done':
        last_done = i
next_step = order[last_done + 1] if last_done + 1 < len(order) else 'complete'
print(next_step)
")
  fi
else
  RESUME_STEP="scope"  # no state, start from beginning
fi

echo "Resume from: /vg:${RESUME_STEP} {phase}"
```

→ Next: `/vg:${RESUME_STEP} {phase}`

**⛔ Deferred-incomplete gate (tightened 2026-04-17):**

Before advancing to a NEW phase, check current phase for `.deferred-incomplete` marker:

```bash
CURRENT_PHASE_DIR="${PHASE_DIR}"  # from recon
if [ -f "${CURRENT_PHASE_DIR}/.deferred-incomplete" ]; then
  if [[ ! "$ARGUMENTS" =~ --allow-deferred ]]; then
    echo "⛔ Phase ${PHASE_NUMBER} is DEFERRED-INCOMPLETE — cannot advance."
    echo "   Open items in ${CURRENT_PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
    echo "   Resolve with: /vg:accept ${PHASE_NUMBER} --resume"
    echo "   Force advance (creates tech debt): /vg:next --allow-deferred"
    exit 1
  else
    echo "⚠ --allow-deferred set — advancing with ${PHASE_NUMBER} still deferred. Tech debt recorded."
    echo "next-advance-with-deferred: ${PHASE_NUMBER} ts=$(date -u +%FT%TZ)" >> ${PLANNING_DIR}/deferred-debt.log
  fi
fi
```

**Route 0b (legacy/hybrid):** `HAS_PRE_ACTION == "yes"` (recon found legacy artifacts)
→ Display: "Phase {N} has legacy GSD artifacts — run `/vg:migrate {N}` to convert to VG format."
→ Show what's missing: API-CONTRACTS.md, TEST-GOALS.md, enriched CONTEXT.md
→ Do NOT auto-invoke migration. `/vg:next` is fast — migrations require interactive approval via `/vg:migrate`.

**Route 0c (semantic enrichment gap, v1.14.0+):** Phase already migrated (no GSD legacy files) BUT TEST-GOALS missing v1.14.0 semantic fields (Persistence check, Surface classification, Plan-Goal linkage).

```bash
VERIFY_SCRIPT=""
[ -f "${REPO_ROOT}/.claude/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
[ -n "$VERIFY_SCRIPT" ] || { [ -f "${REPO_ROOT}/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"; }

if [ -n "$VERIFY_SCRIPT" ] && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  SEMANTIC_JSON=$(${PYTHON_BIN:-python3} "$VERIFY_SCRIPT" --json "$PHASE_DIR" 2>/dev/null)
  FAIL_GATES=$(echo "$SEMANTIC_JSON" | ${PYTHON_BIN:-python3} -c "import sys,json; d=json.loads(sys.stdin.read()); print(','.join(r['name'] for r in d.get('results',[]) if r.get('status')=='FAIL'))" 2>/dev/null)
  if [ -n "$FAIL_GATES" ]; then
    echo "⚠ Phase ${PHASE_NUMBER}: v1.14.0 semantic gaps detected — ${FAIL_GATES}"
    echo "  Re-run /vg:migrate ${PHASE_NUMBER} --force để enrich (preserves existing decisions/goals)."
    echo "  Skip để continue pipeline với debt — but blueprint/build sẽ block khi gặp Rule 3b/Surface gates."
  fi
fi
```

Display only — không block. User decision: re-migrate (recommended) hay skip.

**Recon routes** (derived from `NEXT_STEP`):
- `NEXT_STEP == "scope"` → Next: `/vg:scope {phase}`
- `NEXT_STEP == "blueprint"` → Next: `/vg:blueprint {phase}`
- `NEXT_STEP == "build"` → Next: `/vg:build {phase}`
- `NEXT_STEP == "review"` → Next: `/vg:review {phase}` (see Cross-CLI option below)
- `NEXT_STEP == "test"` → Next: `/vg:test {phase}` (UNLESS prior review verdict ∈ FAIL/BLOCK — see verdict gate)
- `NEXT_STEP == "accept"` → Next: `/vg:accept {phase}` (UNLESS prior test verdict ∈ GAPS_FOUND/FAILED — see verdict gate)
- `NEXT_STEP == "complete"` → Phase done (check Route 8/9)

**Verdict gate (v2.43.2 — fixes "loop tới /vg:accept dù test có gap" bug):**

Before routing to `/vg:test` or `/vg:accept`, read PIPELINE-STATE.json verdict
of the prior step. If non-PASS verdict, do NOT auto-advance — show the same
verdict-aware guidance the prior skill printed at exit:

```bash
PRIOR_REVIEW_VERDICT=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('${PHASE_DIR}/PIPELINE-STATE.json'))
  print(d.get('steps',{}).get('review',{}).get('verdict','?'))
except Exception: print('?')
" 2>/dev/null)

PRIOR_TEST_VERDICT=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('${PHASE_DIR}/PIPELINE-STATE.json'))
  print(d.get('steps',{}).get('test',{}).get('verdict','?'))
except Exception: print('?')
" 2>/dev/null)

# Gate before /vg:test
if [ "$NEXT_STEP" = "test" ] && [[ "$PRIOR_REVIEW_VERDICT" =~ ^(BLOCK|FAIL)$ ]]; then
  echo "⛔ /vg:next refuses auto-advance to /vg:test — review verdict=${PRIOR_REVIEW_VERDICT}."
  echo "   Read REVIEW-FEEDBACK.md + ROAM-MAP.md.  Pick A/B/C/D/E from /vg:review's exit guidance."
  echo "   Then re-run /vg:next or invoke the chosen path directly."
  exit 1
fi

# Gate before /vg:accept
if [ "$NEXT_STEP" = "accept" ] && [[ "$PRIOR_TEST_VERDICT" =~ ^(GAPS_FOUND|FAILED)$ ]]; then
  echo ""
  echo "⛔ /vg:next refuses auto-advance to /vg:accept — test verdict=${PRIOR_TEST_VERDICT}."
  echo ""
  if [ "$PRIOR_TEST_VERDICT" = "FAILED" ]; then
    echo "   /vg:accept WILL BLOCK with hard-gate redirect for FAILED verdict."
  else
    echo "   /vg:accept will register OVERRIDE-DEBT for non-critical gaps OR BLOCK on critical."
  fi
  echo ""
  echo "   First: cat ${PHASE_DIR}/REVIEW-FEEDBACK.md   ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
  echo "   Then pick A-G from /vg:test's exit guidance (re-print: tail -100 ${PHASE_DIR}/.test-exit-output.log)"
  echo ""
  echo "   Common paths:"
  echo "     A) Code bug fixed manually  → /vg:test ${PHASE_NUMBER} --regression-only"
  echo "     B) Test spec wrong          → /vg:test ${PHASE_NUMBER} --skip-deploy"
  echo "     C) Runtime bug              → /vg:review ${PHASE_NUMBER} --retry-failed"
  echo "     D) Goal needs redesign      → /vg:amend ${PHASE_NUMBER}"
  echo "     E) Accept with debt (NON-critical only) → /vg:accept ${PHASE_NUMBER}"
  echo ""
  exit 1
fi
```

The gate intentionally exits 1 (not auto-route) so user MUST consciously pick
the next step. Auto-routing on a non-PASS verdict was the v2.43.1 bug —
sent users to /vg:accept which blocks, no clear way out.

**Review cross-CLI option** (only when NEXT_STEP == "review"):
Display cross-CLI option:
→ Display cross-CLI option:
```
  **Review options:**
  A) Standard:  `/vg:review {phase}` — Claude does full review (discovery + evaluate + fix)
  B) Cross-CLI: Split work across AI CLIs for lower cost:
     1. Codex:  `$vg-review {phase} --discovery-only`  — Codex does discovery (cheap, has MCP browser)
     2. Claude: `/vg:review {phase} --evaluate-only`   — Claude reads scan results, evaluates + fixes
     
     Or Gemini: `/vg-review {phase} --discovery-only`  — same flow, Gemini does discovery
  
  Option B saves ~60-70% tokens on Claude (no browser interaction).
  
  Flag: add `--full-scan` to disable snapshot pruning (default: pruning ON, saves 50-70% tokens).
  Use --full-scan only when app has non-standard layout or no <main> selector.
```

**Route 5b:** `RUNTIME-MAP.json` exists + `GOAL-COVERAGE-MATRIX.md` exists + gate = BLOCK (goals < 100%)
→ Review ran but goals not met. Auto-detect cause from artifacts:

```
Read discovery-state.json → completed_phase field
Read GOAL-COVERAGE-MATRIX.md → goal statuses (READY / BLOCKED / UNREACHABLE / FAILED)
Read RUNTIME-MAP.json → goal_sequences[goal_id].start_view for each failed goal

SIGNAL 1 — discovery-state.json.completed_phase ≠ "investigate":
  → Review was INTERRUPTED (token exhaustion / session died mid-scan)
  → Auto-invoke: /vg:review {phase} --resume
  → No user choice needed.

SIGNAL 2 — completed_phase == "investigate" (review fully completed):
  Classify failed goals (4 distinct statuses — verify code presence before assuming):
    UNREACHABLE = goal has no start_view AND code for page/route NOT found in repo
                  (feature genuinely not built — grep config.code_patterns returns nothing)
    NOT_SCANNED = goal has no start_view BUT code for page/route DOES exist
                  (review didn't replay — multi-step wizard, orphan route, timeout, retry-scope miss)
    BLOCKED/FAILED = goal has start_view but result=failed
                     (view found, scan ran, criteria not met → code bug)
```

**Display to user (explain, then action):**

```
⚠ Phase {N} gate BLOCKED — {X}/{total} goals failed.

┌─ What the failure types mean ─────────────────────────────────┐
│ UNREACHABLE ({N})  Code for page/route NOT in repo (verified) │
│                    → Feature not built yet                    │
│                    → Fix: /vg:build {phase} --gaps-only       │
│                                                               │
│ NOT_SCANNED ({N})  Code EXISTS but review didn't replay       │
│                    (multi-step wizard/mutation, orphan route, │
│                     Haiku timeout, retry scope missed goal)   │
│                    → Fix: /vg:test {phase} (codegen walks)    │
│                         or --retry-failed (re-scan only)      │
│                                                               │
│ BLOCKED ({N})      View found, but goal criteria not met      │
│                    (form didn't submit, API error, etc.)      │
│                    → Code has a bug — fix and re-scan         │
│                                                               │
│ INTERRUPTED        Review died mid-scan (token/timeout)       │
│                    → Just resume where it left off            │
└───────────────────────────────────────────────────────────────┘

Failed goals:
  [UNREACHABLE] {goal_id}: {goal_desc}
  [NOT_SCANNED] {goal_id}: {goal_desc} (code: {path/to/page.tsx})
  [BLOCKED]     {goal_id}: {goal_desc} (view: {start_view})
  ...
```

**Then route by classification:**

```
IF all UNREACHABLE (code confirmed missing):
  → Auto-invoke: /vg:build {phase} --gaps-only
  Print: "All failures UNREACHABLE — feature missing. Auto-building gaps..."
  After build completes → re-run /vg:review {phase}

IF all NOT_SCANNED (code exists, review skipped):
  Print: "All failures NOT_SCANNED — code built but review didn't replay."
  Display (do NOT auto-invoke — user picks based on root cause):
    Common cause 1: Multi-step wizard/mutation needs dedicated browser session
      → /vg:test {phase}
        (codegen + Playwright auto-walks wizard, fills all steps, verifies goal)
    Common cause 2: Timeout or retry-scope missed the goal
      → /vg:review {phase} --retry-failed
        (fresh re-scan of only failed views)
    DO NOT run /vg:build --gaps-only — code already exists.

IF all BLOCKED (code bugs — user fix required first):
  Print: "All failures BLOCKED — code bugs in {N} views. Workflow:"
  Display (do NOT auto-invoke):
    Step 1: Fix the code (inspect logs/network errors in GOAL-COVERAGE-MATRIX.md)
    Step 2: Re-scan ONLY failed views: /vg:review {phase} --retry-failed
            (~5-10x faster than full review — skips passed views)
    Cross-CLI option: $vg-review {phase} --retry-failed --discovery-only
                    → /vg:review {phase} --evaluate-only

IF mix (any combination):
  Print: "Mixed failures — handle in order:"
  Display (do NOT auto-invoke):
    Step 1: /vg:build {phase} --gaps-only       ← if UNREACHABLE exists, build first
    Step 2: Fix code for BLOCKED goals (list shown above)
    Step 3: /vg:test {phase}                     ← if NOT_SCANNED exists (codegen for complex flows)
    Step 4: /vg:review {phase} --retry-failed   ← re-verify everything
```

**Route 6:** `RUNTIME-MAP.json` + `RUNTIME-MAP.md` exist + GOAL-COVERAGE-MATRIX gate = PASS + no `*-SANDBOX-TEST.md`
→ Next: `/vg:test {phase}`
Note: RUNTIME-MAP.json is the canonical artifact — .md alone is NOT sufficient for /vg:test.

**Route 7:** `*-SANDBOX-TEST.md` exists but no `*-UAT.md` OR UAT status != "complete"
→ Next: `/vg:accept {phase}`

**Route 8:** UAT complete AND next phase exists in ROADMAP.md AND next phase has NO `SPECS.md`
→ Next: `/vg:specs {next_phase}`

**Route 8b:** UAT complete AND next phase has `SPECS.md` but NO `CONTEXT.md`
→ Next: `/vg:scope {next_phase}`

**Route 9:** All phases complete
→ Next: `/vg:complete-milestone {M}` (close + audit + summary + archive — v2.33.0+)
   Then: `/vg:project --milestone` to scope the next milestone
</step>

<step name="show_and_execute">
Display current status with artifact checklist, then IMMEDIATELY invoke.

```
## VG Next (V6)

**Current:** Phase {N} — {name}
**Phase type:** {PHASE_TYPE} (from recon)
**Pipeline position (from .recon-state.json):**
  scope:     {status} {v6_artifacts}
  blueprint: {status} {v6_artifacts}
  build:     {status} {v6_artifacts}
  review:    {status} {v6_artifacts}
  test:      {status} {v6_artifacts}
  accept:    {status} {v6_artifacts}

▶ **Next step:** `/vg:{NEXT_STEP} {phase}`
  {recommended_action.reason from recon}
```

Pipeline position is read from `.recon-state.json` (per-step status: done|partial|missing|legacy_only).
IMMEDIATELY invoke the next command. No confirmation prompt (except legacy migration which redirects to /vg:phase).
</step>

</process>

<success_criteria>
- Config loaded
- State detected from files
- Pipeline position determined
- Status displayed with V5 artifact checklist
- Next command invoked immediately
</success_criteria>
