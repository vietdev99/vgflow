---
name: "vg-roam"
description: "Exploratory CRUD-lifecycle pass with state-coherence assertion. Lens-driven, post-confirmation. Catches silent state-mismatches that /vg:review and /vg:test miss. Generates new .spec.ts proposals from findings."
metadata:
  short-description: "Exploratory CRUD-lifecycle pass with state-coherence assertion. Lens-driven, post-confirmation. Catches silent state-mismatches that /vg:review and /vg:test miss. Generates new .spec.ts proposals from findings."
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

Invoke this skill as `$vg-roam`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Run AFTER /vg:test confirmed PASS.** Roam is a janitor, not a primary verifier. Failed-review or failed-test phases skip roam (no point exploring broken app).
2. **Executor CLI logs only — never judges.** All bug classification happens in step 5 (commander analysis). HARD rule embedded in every CLI brief. **Conformance contract:** every brief MUST inject `vg:_shared:scanner-report-contract` (banned vocab + report schema). Briefs without the contract block REJECTED at compose time.
3. **Lens auto-pick by phase profile + entity types** (Q9 default). Manual override via `--lens=`.
4. **Spec auto-merge is staged** (Q10): roam writes proposed-specs/ but does NOT merge into test suite without `--merge-specs` confirmation.
5. **Cost guards**: hard cap 50 surfaces × 1 CLI default. Soft cap $10/session via `roam.max_cost_usd` config. Pre-spawn estimator warns + asks confirm if soft cap exceeded.
6. **Council mode default OFF** (Q8). Enable via `--council` for ship-critical phases.
7. **Security lens skipped by default** (Q13). `/vg:review` Phase 2.5 owns security probes. Enable via `--include-security` for double-coverage.
8. **Vocabulary validator** (v2.42.7+): post-aggregate step (4_aggregate_logs) runs grep on observe-*.jsonl for banned tokens (`bug`, `broken`, `critical`, `should fix`, etc — full list in scanner-report-contract.md). Hits → tag report `vocabulary_violation: true`, commander deprioritizes during step 5 analysis but still consumes (partial signal > no signal).
</rules>

<step name="0_parse_and_validate">
## Step 0 — Parse args, validate prerequisites

Read phase, validate `/vg:review` + `/vg:test` both completed with PASS (otherwise refuse to run). Parse flags. Initialize output dir.

```bash
PHASE_DIR=".vg/phases/${PHASE_NUMBER}"
ROAM_DIR="${PHASE_DIR}/roam"
mkdir -p "${ROAM_DIR}/proposed-specs"

# Refuse if review/test didn't pass
REVIEW_VERDICT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${PHASE_DIR}/PIPELINE-STATE.json')); print(d.get('steps',{}).get('review',{}).get('verdict','UNKNOWN'))" 2>/dev/null)
TEST_VERDICT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${PHASE_DIR}/PIPELINE-STATE.json')); print(d.get('steps',{}).get('test',{}).get('verdict','UNKNOWN'))" 2>/dev/null)

if [[ "$REVIEW_VERDICT" != "PASS" ]] || [[ "$TEST_VERDICT" != "PASS" ]]; then
  echo "⛔ Roam requires /vg:review and /vg:test both PASS before running."
  echo "   review verdict: $REVIEW_VERDICT"
  echo "   test verdict:   $TEST_VERDICT"
  echo "   Roam is post-confirmation janitor; no point exploring an unfinished phase."
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0_parse_and_validate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0_parse_and_validate.done"

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.session.started" \
  --actor "orchestrator" --outcome "INFO" --payload "{\"args\":\"${ARGUMENTS}\"}" 2>/dev/null || true
```
</step>

<step name="0aa_resume_check">
## Step 0aa — resume / force / aggregate-only detection (v2.42.6+)

If `${ROAM_DIR}/ROAM-CONFIG.json` exists, this phase had a roam run before.
Without resume logic, every re-run wastes work — re-discovers surfaces,
re-composes briefs, re-spawns executors. Detect existing state and route:

| Mode | What happens | When to use |
|------|--------------|-------------|
| `fresh` | normal flow — all steps run | first-time run, no prior state |
| `force` | wipe ROAM_DIR/* then proceed fresh | env/scope changed, want clean slate |
| `resume` | reuse config; per-step skip if artifact exists | partial run (e.g. 5/20 briefs done) |
| `aggregate-only` | skip steps 1-3 entirely, run 4-6 only | manual mode finalization (user pasted prompt to other CLI, dropped JSONL, now wants commander to aggregate + analyze) |

### Detection + branching

```bash
EXISTING_CONFIG="${ROAM_DIR}/ROAM-CONFIG.json"
HAS_RUN_BEFORE=false
[ -f "$EXISTING_CONFIG" ] && HAS_RUN_BEFORE=true

# v2.42.9 — LEGACY state detection. Pre-v2.42.6 runs didn't write
# ROAM-CONFIG.json, but artifacts (RAW-LOG.jsonl, SURFACES.md, INSTRUCTION-*,
# observe-*) still exist. Without this, the resume prompt silently skips
# and a re-invocation overwrites prior work or treats stale state as fresh.
if [ "$HAS_RUN_BEFORE" = false ]; then
  for legacy in "${ROAM_DIR}/RAW-LOG.jsonl" "${ROAM_DIR}/SURFACES.md" "${ROAM_DIR}/ROAM-BUGS.md"; do
    [ -f "$legacy" ] && HAS_RUN_BEFORE=true && break
  done
  if [ "$HAS_RUN_BEFORE" = false ]; then
    [ -n "$(find "$ROAM_DIR" -maxdepth 3 -name 'INSTRUCTION-*.md' -print -quit 2>/dev/null)" ] && HAS_RUN_BEFORE=true
    [ -n "$(find "$ROAM_DIR" -maxdepth 3 -name 'observe-*.jsonl' -print -quit 2>/dev/null)" ] && HAS_RUN_BEFORE=true
  fi
  if [ "$HAS_RUN_BEFORE" = true ] && [ ! -f "$EXISTING_CONFIG" ]; then
    echo "▸ LEGACY roam state detected (no ROAM-CONFIG.json, artifacts present)"
    echo "   Treating as prior run — resume prompt will fire. AI must NOT silently"
    echo "   overwrite or backfill config without user confirmation."
  fi
fi

# CLI flag overrides — skip AskUserQuestion when explicit
ROAM_RESUME_MODE="fresh"
if [[ "$ARGUMENTS" =~ --force ]]; then
  ROAM_RESUME_MODE="force"
elif [[ "$ARGUMENTS" =~ --resume ]]; then
  ROAM_RESUME_MODE="resume"
elif [[ "$ARGUMENTS" =~ --aggregate-only ]]; then
  ROAM_RESUME_MODE="aggregate-only"
elif [ "$HAS_RUN_BEFORE" = true ] && [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  # Interactive: AI MUST AskUserQuestion before proceeding.
  # Read existing config snapshot for a useful summary in the question.
  PREV_ENV=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('env','?'))" 2>/dev/null)
  PREV_MODEL=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('model','?'))" 2>/dev/null)
  PREV_MODE=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('mode','?'))" 2>/dev/null)
  PREV_STARTED=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('started_at','?'))" 2>/dev/null)
  EXISTING_INSTR=$(find "$ROAM_DIR" -maxdepth 2 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  EXISTING_OBSERVE=$(find "$ROAM_DIR" -maxdepth 2 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')

  echo "▸ Prior roam run detected:"
  echo "    env=${PREV_ENV} model=${PREV_MODEL} mode=${PREV_MODE} started=${PREV_STARTED}"
  echo "    INSTRUCTION-*.md: ${EXISTING_INSTR} | observe-*.jsonl: ${EXISTING_OBSERVE}"
  echo ""
  echo "AI: AskUserQuestion now with the 4-option block below before proceeding."
fi
```

### AskUserQuestion (interactive only — fires when `HAS_RUN_BEFORE=true` AND no `--force`/`--resume`/`--aggregate-only`/`--non-interactive` flag)

```
question: "Phase này đã chạy roam trước (env=$PREV_ENV, model=$PREV_MODEL, mode=$PREV_MODE, $PREV_STARTED). $EXISTING_INSTR briefs / $EXISTING_OBSERVE observed. Làm gì?"
header: "Resume?"
multiSelect: false
options:
  - label: "resume — tiếp tục từ điểm dừng (Recommended)"
    description: "Tái dùng config cũ; skip discover/compose/spawn cho artifacts đã có. Chỉ chạy bù phần thiếu + aggregate + analyze. Phù hợp khi spawn run partial (5/20 briefs xong) hoặc manual paste vẫn còn dở."
  - label: "aggregate-only — gom JSONL hiện có + analyze"
    description: "Skip discover/compose/spawn hoàn toàn. Đi thẳng vào aggregate (step 4) + analyze (step 5) + emit (step 6). Phù hợp khi manual mode đã paste xong, JSONL đã drop về model dir, chỉ cần commander gom + chấm điểm."
  - label: "force — wipe ROAM_DIR + chạy lại từ đầu"
    description: "Xóa hết SURFACES.md + INSTRUCTION-*.md + observe-*.jsonl + ROAM-BUGS.md. Phù hợp khi env/scope/lens đổi → muốn slate sạch. Sẽ hỏi lại env/model/mode."
  - label: "fresh — keep cũ + run mới (parallel)"
    description: "Giữ nguyên config + artifacts cũ; mở session mới với env/model/mode khác. Output đè lên cùng dir. CHỈ dùng khi muốn re-test cùng phase với scanner khác (vd codex → gemini)."
```

### After answer

```bash
# Apply ROAM_RESUME_MODE
case "$ROAM_RESUME_MODE" in
  force)
    echo "▸ Force mode — wiping ${ROAM_DIR}/* (preserving .step-markers)"
    find "$ROAM_DIR" -mindepth 1 -maxdepth 1 ! -name '.step-markers' -exec rm -rf {} +
    ROAM_RESUME_MODE="fresh"  # downstream treats as fresh after wipe
    ;;
  resume|aggregate-only)
    # v2.42.10 — load prior config as PRE-FILL ONLY. Step 0a will STILL fire
    # its 3-question batch and use these as Recommended defaults. Silent
    # load was a footgun: user often wanted to switch env/model/mode mid-run
    # but resume mode locked them in. Now: prior config informs pre-fill,
    # user always confirms.
    echo "▸ Resume mode: ${ROAM_RESUME_MODE} — loading PRIOR config as pre-fill (step 0a will still ask)"
    ROAM_PRIOR_ENV=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('env',''))" 2>/dev/null)
    ROAM_PRIOR_MODEL=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('model',''))" 2>/dev/null)
    ROAM_PRIOR_MODE=$(${PYTHON_BIN:-python3} -c "import json; print(json.load(open('$EXISTING_CONFIG')).get('mode',''))" 2>/dev/null)
    export ROAM_PRIOR_ENV ROAM_PRIOR_MODEL ROAM_PRIOR_MODE
    export ROAM_RESUME_MODE
    echo "  prior: env=${ROAM_PRIOR_ENV} model=${ROAM_PRIOR_MODEL} mode=${ROAM_PRIOR_MODE}"
    echo "  → step 0a will fire 3-question batch with these as Recommended defaults"
    ;;
  fresh)
    : # default — proceed to 0a AskUserQuestion normally
    ;;
esac

export ROAM_RESUME_MODE

# v2.42.9 HARD GATE: write resume-mode marker + emit telemetry. Step 1 entry
# refuses to proceed unless this marker exists (or --non-interactive set).
# Prevents AI from silently skipping the 4-option AskUserQuestion above.
mkdir -p "${ROAM_DIR}/.tmp"
echo "$(date +%s)|${ROAM_RESUME_MODE}" > "${ROAM_DIR}/.tmp/0aa-confirmed.marker"

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.resume_mode_chosen" \
  --actor "user" --outcome "INFO" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mode\":\"${ROAM_RESUME_MODE}\",\"had_prior_state\":${HAS_RUN_BEFORE}}" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0aa_resume_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0aa_resume_check.done"
```

**Step 0a behavior under resume (v2.42.10):** Step 0a ALWAYS fires its 3-question batch, regardless of `$ROAM_RESUME_MODE`. Under resume, prior values are loaded as `ROAM_PRIOR_ENV/MODEL/MODE` and used as pre-fill (Recommended option in each question), but user must confirm. Silent skip was the v2.42.6-9 footgun: users wanted to change env mid-run but resume locked them in.

**Subsequent steps under resume:** each step checks `$ROAM_RESUME_MODE`:

- Step 1 (discover surfaces): SKIP if `$ROAM_RESUME_MODE = resume` AND `SURFACES.md` exists. SKIP unconditionally if `aggregate-only`.
- Step 2 (compose briefs): SKIP if `$ROAM_RESUME_MODE = resume` AND `INSTRUCTION-*.md` count ≥ surface count for current model. SKIP unconditionally if `aggregate-only`.
- Step 3 (spawn/manual): per-brief skip — if `observe-${brief}.jsonl` exists with ≥1 event, skip that brief. SKIP unconditionally if `aggregate-only`.
- Steps 4 (aggregate), 5 (analyze), 6 (emit): always run regardless of mode (cheap; idempotent).
</step>

<step name="0a_env_model_mode_gate">
## Step 0a — env + model + mode gate (interactive, HARD gate)

**v2.42.10 — ALWAYS fires regardless of resume mode.** Prior runs (resume / aggregate-only) populate `ROAM_PRIOR_ENV/MODEL/MODE` which are surfaced as Recommended pre-fills in each question, but the user must still confirm. Removing this prompt under resume was the v2.42.6-9 footgun: users wanted to switch env/model/mode mid-stream but resume locked them in to the prior choice silently.

**MANDATORY FIRST ACTION** of this step (before ANY other tool call) — invoke `AskUserQuestion` with the 3-question payload below to lock down where roam runs, which CLI executes, and whether to spawn or generate paste prompts.

**Skip AskUserQuestion ONLY when:**
- `${ARGUMENTS}` contains `--non-interactive`, OR
- `VG_NON_INTERACTIVE=1`, OR
- `${ARGUMENTS}` contains ALL THREE: `--target-env=<v>` (or `--local`/`--sandbox`/`--staging`/`--prod`), `--model=<v>`, AND `--mode=<v>`

When pre-fills exist (resume mode), the AI MUST tag the matching option's label with " (Recommended — prior run)" so the user sees what was chosen last time. Order options so the prior choice appears first.

### Pre-prompt 1 — backfill `preferred_env_for` if scope ran before step 1b existed (v2.42.7+)

Phases scoped before /vg:scope step 1b landed have `CONTEXT.md` but no
`DEPLOY-STATE.json` `preferred_env_for` block. Without backfill, the
runtime env gate falls back to profile heuristic forever — user never gets
to set the preference. This pre-prompt closes that gap by asking the same
5-option preset (one-time, persists into DEPLOY-STATE.json so it never
re-fires).

**Skip conditions:**
- `${ARGUMENTS}` contains `--skip-env-preference` OR `--non-interactive`
- `${PHASE_DIR}/DEPLOY-STATE.json` already has `preferred_env_for` set
- `${PHASE_DIR}/DEPLOY-STATE.json` has `preferred_env_for_skipped: true`
  (user previously chose "auto" — don't re-ask)

```bash
DEPLOY_STATE="${PHASE_DIR}/DEPLOY-STATE.json"
NEED_PREF_PROMPT="false"
if [[ ! "$ARGUMENTS" =~ --skip-env-preference ]] && [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  if [ ! -f "$DEPLOY_STATE" ]; then
    NEED_PREF_PROMPT="true"
  else
    HAS_PREF=$(${PYTHON_BIN:-python3} -c "
import json
try:
  d = json.load(open('$DEPLOY_STATE'))
  print('1' if d.get('preferred_env_for') or d.get('preferred_env_for_skipped') else '0')
except Exception:
  print('0')" 2>/dev/null)
    [ "$HAS_PREF" = "0" ] && NEED_PREF_PROMPT="true"
  fi
fi

if [ "$NEED_PREF_PROMPT" = "true" ]; then
  echo "▸ DEPLOY-STATE.json chưa có preferred_env_for — fire one-time backfill prompt"
  echo "  AI: AskUserQuestion với 5-option preset trước khi vào env+model+mode gate."
fi
```

**AskUserQuestion (fires only when `$NEED_PREF_PROMPT=true`):**

```
question: |
  Phase này khi review/test/roam/accept chạy nên ưu tiên env nào?
  GỢI Ý THÔI — runtime AskUserQuestion vẫn fire, đây chỉ là pre-fill recommendation.
  Hỏi 1 lần thôi, lưu vào DEPLOY-STATE.json. Re-set bằng /vg:scope <phase> --reset-env-preference.
header: "Env pref"
multiSelect: false
options:
  - label: "auto — không lưu preference (Recommended cho phase mới)"
    description: "Lưu cờ skipped để không hỏi lại. Helper enrich-env-question.py dùng profile heuristic mỗi lần."
  - label: "all sandbox — review/test/roam/accept đều prefer sandbox"
    description: "Phase chưa ship lên prod; dogfood sâu trên sandbox."
  - label: "review+test+roam=sandbox, accept=prod — phổ biến nhất"
    description: "Production-ready phase. UAT trên prod thật, mọi check khác trên sandbox."
  - label: "review+test=sandbox, roam=staging, accept=prod — paranoid"
    description: "Tách roam riêng sang staging để soi env gần prod hơn. Phù hợp ship-critical."
  - label: "all local — phase nội bộ / dogfood"
    description: "Pure-backend hoặc internal tooling, không cần deploy."
```

**After answer, persist + continue:**

```bash
if [ "$NEED_PREF_PROMPT" = "true" ]; then
  ${PYTHON_BIN:-python3} -c "
import json, os, sys
from pathlib import Path
choice = os.environ.get('ENV_PREF_BACKFILL_CHOICE', 'auto').lower()
mapping = None
if 'all sandbox' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'sandbox'}
elif 'review+test+roam=sandbox' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'sandbox', 'accept': 'prod'}
elif 'roam=staging' in choice and 'accept=prod' in choice:
  mapping = {'review': 'sandbox', 'test': 'sandbox', 'roam': 'staging', 'accept': 'prod'}
elif 'all local' in choice:
  mapping = {'review': 'local', 'test': 'local', 'roam': 'local', 'accept': 'local'}

p = Path('$DEPLOY_STATE')
state = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'phase': '${PHASE_NUMBER}'}
if mapping is None:
  state['preferred_env_for_skipped'] = True
  print('[roam-backfill] auto — skipped flag saved (won\\'t re-ask)')
else:
  state['preferred_env_for'] = mapping
  print(f'[roam-backfill] saved: {json.dumps(mapping)}')
p.write_text(json.dumps(state, indent=2, ensure_ascii=False))
"
fi
```

### Pre-prompt 1.5 — platform + tool availability check (v2.42.11)

Roam shouldn't blindly assume web + codex CLI. Detect what platform the
phase targets (web / mobile-native / desktop / api-only) from CONTEXT.md
+ surfaces. Check which executor tools are present. Filter the mode
options below by availability — don't offer modes that will fail.

```bash
# Platform detection — heuristic from phase artifacts
ROAM_PLATFORM="web"
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  CONTEXT_LOWER=$(tr '[:upper:]' '[:lower:]' < "${PHASE_DIR}/CONTEXT.md" 2>/dev/null)
  echo "$CONTEXT_LOWER" | grep -qE 'react native|flutter|android sdk|ios simulator|maestro' && ROAM_PLATFORM="mobile-native"
  echo "$CONTEXT_LOWER" | grep -qE 'electron|tauri|desktop app' && ROAM_PLATFORM="desktop"
  if echo "$CONTEXT_LOWER" | grep -qE 'api[ -]only|backend[ -]only|no ui|server[ -]only|webhook'; then
    if ! echo "$CONTEXT_LOWER" | grep -qE 'admin (ui|panel|dashboard)|merchant (ui|app)|vendor (ui|app)'; then
      ROAM_PLATFORM="api-only"
    fi
  fi
fi
export ROAM_PLATFORM

# Tool availability
TOOL_PLAYWRIGHT_MCP="missing"
grep -qE '"mcp__playwright[1-5]?__' .claude/settings.json .claude/settings.local.json 2>/dev/null && TOOL_PLAYWRIGHT_MCP="present"
[ -f ~/.claude/settings.json ] && grep -q 'playwright' ~/.claude/settings.json 2>/dev/null && TOOL_PLAYWRIGHT_MCP="present"
TOOL_MAESTRO=$(command -v maestro >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_ADB=$(command -v adb >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_CODEX=$(command -v codex >/dev/null 2>&1 && echo "present" || echo "missing")
TOOL_GEMINI=$(command -v gemini >/dev/null 2>&1 && echo "present" || echo "missing")
export TOOL_PLAYWRIGHT_MCP TOOL_MAESTRO TOOL_ADB TOOL_CODEX TOOL_GEMINI

# Mode availability matrix per platform + tools
declare -a MODES_AVAIL
case "$ROAM_PLATFORM" in
  web)
    [ "$TOOL_PLAYWRIGHT_MCP" = "present" ] && MODES_AVAIL+=("self")
    { [ "$TOOL_CODEX" = "present" ] || [ "$TOOL_GEMINI" = "present" ]; } && MODES_AVAIL+=("spawn")
    MODES_AVAIL+=("manual")  # always available — user pastes elsewhere
    ;;
  mobile-native)
    if [ "$TOOL_MAESTRO" = "present" ] && [ "$TOOL_ADB" = "present" ]; then
      MODES_AVAIL+=("spawn-mobile")
    fi
    MODES_AVAIL+=("manual")
    ;;
  desktop|api-only)
    [ "$TOOL_PLAYWRIGHT_MCP" = "present" ] && MODES_AVAIL+=("self")
    MODES_AVAIL+=("manual")
    ;;
esac

echo "▸ Platform: ${ROAM_PLATFORM}"
echo "  Tools: playwright_mcp=${TOOL_PLAYWRIGHT_MCP} codex=${TOOL_CODEX} gemini=${TOOL_GEMINI} maestro=${TOOL_MAESTRO} adb=${TOOL_ADB}"
echo "  Available modes: ${MODES_AVAIL[*]:-NONE}"

if [ ${#MODES_AVAIL[@]} -eq 0 ]; then
  echo ""
  echo "⛔ No executor mode available for platform=${ROAM_PLATFORM} with current tools."
  case "$ROAM_PLATFORM" in
    mobile-native)
      echo "   Run /vg:setup-mobile to install adb + Maestro + Android SDK + AVD."
      ;;
    *)
      echo "   Install at least one of: codex CLI, gemini CLI, or enable Playwright MCP servers."
      ;;
  esac
  exit 1
fi

# Persist for downstream use (mode question filtering, brief composer)
echo "$ROAM_PLATFORM" > "${ROAM_DIR}/.tmp/platform.txt"
printf '%s\n' "${MODES_AVAIL[@]}" > "${ROAM_DIR}/.tmp/modes-avail.txt"
```

When building the **mode question** (Q3 below), AI MUST read `.tmp/modes-avail.txt` and ONLY include the modes listed there. Do not present "self" if Playwright MCP is missing; do not present "spawn" if codex/gemini missing. If `manual` is the only available mode, still present the question (for user awareness) but mark it Recommended.

When platform = `mobile-native` and Maestro/adb missing, AI MUST surface the `/vg:setup-mobile` install suggestion via AskUserQuestion BEFORE the env+model+mode batch (give user choice: install now / abort / fall back to manual).

### Pre-prompt 2 — enrich env options from DEPLOY-STATE (B2 wiring, v2.42.5+)

After backfill (or if skipped), run the helper to read DEPLOY-STATE +
emit decorated labels/descriptions. **Suggestion-only** — user still picks;
AI decorates options with evidence ("deployed 2min ago, sha abc1234",
"phase prefers this env", "chưa deploy phase này", etc.).

```bash
mkdir -p "${PHASE_DIR}/.tmp"
${PYTHON_BIN:-python3} .claude/scripts/enrich-env-question.py \
  --phase-dir "${PHASE_DIR}" --command roam \
  > "${PHASE_DIR}/.tmp/env-options.roam.json" 2>/dev/null || true
```

After this runs, `.tmp/env-options.roam.json` contains:
```
{
  "deploy_state_present": bool,
  "preferred_env": "sandbox" | null,
  "recommended_env": "sandbox",
  "envs": {
    "local":   {"decorated_label": "...", "decorated_description": "...", "is_recommended": false},
    "sandbox": {"decorated_label": "... (Recommended)", "decorated_description": "... [phase prefers this env]"},
    "staging": {...},
    "prod":    {...}
  }
}
```

When building the env question's `options` array (Q1 below), AI MUST read this
JSON and use `envs.{key}.decorated_label` + `envs.{key}.decorated_description`
verbatim instead of the hardcoded labels. If the JSON is missing or malformed,
fall back to the hardcoded options and proceed (graceful degrade).

**3-question batch (single AskUserQuestion call):**

```
questions:
  - question: "Roam env — chạy trên môi trường nào?"
    header: "Env"
    multiSelect: false
    options:
      # ⚠ Use envs.{local|sandbox|staging|prod}.decorated_label / .decorated_description
      # from .tmp/env-options.roam.json. Below is the FALLBACK shape only.
      - label: "local — máy của bạn"
        description: "Browser MCP local, port 3001-3010. Mặc định cho dogfood + nhanh."
      - label: "sandbox — VPS Hetzner (printway.work)"
        description: "Production-like, ssh deploy. Phù hợp khi muốn roam soi env gần production."
      - label: "staging — staging server"
        description: "Chỉ chọn nếu config có. Hiện chưa cấu hình → sẽ fail ở deploy."
      - label: "prod — production (CẢNH BÁO read-only)"
        description: "Workflow sẽ block mọi mutation lens (form-lifecycle, business-coherence)."
  - question: "Model — CLI nào sẽ chạy executor?"
    header: "Model"
    multiSelect: false
    options:
      - label: "Codex (gpt-5.3-codex, effort=high)"
        description: "Cheap + capable, default executor. Output dir: roam/codex/."
      - label: "Gemini 2.5 Pro"
        description: "UI consistency + a11y mạnh, cùng giá. Output dir: roam/gemini/."
      - label: "Council (cả Codex + Gemini song song)"
        description: "Ship-critical phase only — 2× cost, 2 perspectives. Output dirs: roam/codex/ + roam/gemini/."
  - question: "Mode — ai chạy executor?"
    header: "Mode"
    multiSelect: false
    options:
      # ⚠ AI MUST filter by .tmp/modes-avail.txt — only show options for which
      # tooling exists. Order: self first if available (cheapest, no subprocess),
      # then spawn, then manual.
      - label: "self — current Claude session là executor (Recommended cho web + MCP Playwright)"
        description: "AI session hiện tại điều khiển Playwright MCP trực tiếp. Không subprocess, không Chromium permission. Login + protocol thực hiện trong session. Output JSONL drop vào model dir. Phù hợp web platform khi MCP Playwright sẵn."
      - label: "spawn — VG tự subprocess CLI executor"
        description: "Cần codex hoặc gemini CLI authenticated. AI bị chặn nếu CLI không có. Risk macOS XPC permission cho Chromium binary. Output dir: roam/{model}/."
      - label: "manual — VG sinh INSTRUCTION.md + PASTE-PROMPT.md"
        description: "Copy đoạn paste-prompt sang CLI khác (Codex desktop, Cursor, web ChatGPT). User tự chạy, drop JSONL về dir đã chỉ, VG verify khi user signal continue."
```

### After answers (or CLI overrides), persist + branch

```bash
# Resolve from AskUserQuestion answers OR CLI flags OR defaults
ROAM_ENV="${ROAM_ENV:-${CONFIG_STEP_ENV_VERIFY:-local}}"
ROAM_MODEL="${ROAM_MODEL:-codex}"
ROAM_MODE="${ROAM_MODE:-spawn}"

# CLI override path
if [[ "$ARGUMENTS" =~ --target-env=([a-z]+) ]]; then ROAM_ENV="${BASH_REMATCH[1]}"; fi
[[ "$ARGUMENTS" =~ --local ]] && ROAM_ENV="local"
[[ "$ARGUMENTS" =~ --sandbox ]] && ROAM_ENV="sandbox"
[[ "$ARGUMENTS" =~ --staging ]] && ROAM_ENV="staging"
[[ "$ARGUMENTS" =~ --prod ]] && ROAM_ENV="prod"
if [[ "$ARGUMENTS" =~ --model=([a-z-]+) ]]; then ROAM_MODEL="${BASH_REMATCH[1]}"; fi
if [[ "$ARGUMENTS" =~ --mode=([a-z]+) ]]; then ROAM_MODE="${BASH_REMATCH[1]}"; fi

# Validate
case "$ROAM_ENV" in local|sandbox|staging|prod) ;; *) echo "⛔ invalid env '$ROAM_ENV'"; exit 1 ;; esac
case "$ROAM_MODEL" in codex|gemini|council) ;; *) echo "⛔ invalid model '$ROAM_MODEL'"; exit 1 ;; esac
case "$ROAM_MODE" in self|spawn|manual) ;; *) echo "⛔ invalid mode '$ROAM_MODE' (allowed: self|spawn|manual)"; exit 1 ;; esac

export ROAM_ENV ROAM_MODEL ROAM_MODE

# Resolve env-specific config: target URL prefix + credentials
ROAM_TARGET_DOMAIN=$(${PYTHON_BIN:-python3} - <<PY
import re, sys
text = open('.claude/vg.config.md', encoding='utf-8').read()
# credentials.${ROAM_ENV}: first role's domain
m = re.search(r'^\s*${ROAM_ENV}:\s*$', text, re.M)
if not m: print(''); sys.exit(0)
section = text[m.end():m.end()+2000]
dm = re.search(r'domain:\s*"([^"]+)"', section)
print(dm.group(1) if dm else '')
PY
)
ROAM_TARGET_PROTOCOL="https"
[[ "$ROAM_TARGET_DOMAIN" =~ localhost|127\. ]] && ROAM_TARGET_PROTOCOL="http"
ROAM_TARGET_URL="${ROAM_TARGET_PROTOCOL}://${ROAM_TARGET_DOMAIN}"
export ROAM_TARGET_URL

# Per-model output directory(ies)
if [ "$ROAM_MODEL" = "council" ]; then
  ROAM_MODEL_DIRS=("${ROAM_DIR}/codex" "${ROAM_DIR}/gemini")
else
  ROAM_MODEL_DIRS=("${ROAM_DIR}/${ROAM_MODEL}")
fi
for d in "${ROAM_MODEL_DIRS[@]}"; do mkdir -p "$d"; done

# Banner
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  /vg:roam configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase:       ${PHASE_NUMBER}"
echo "  Env:         ${ROAM_ENV} (target: ${ROAM_TARGET_URL})"
echo "  Model:       ${ROAM_MODEL}"
echo "  Mode:        ${ROAM_MODE}"
echo "  Output dirs: ${ROAM_MODEL_DIRS[*]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Persist + telemetry
${PYTHON_BIN:-python3} -c "
import json, datetime
from pathlib import Path
p = Path('${ROAM_DIR}/ROAM-CONFIG.json')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
  'phase': '${PHASE_NUMBER}',
  'env': '${ROAM_ENV}',
  'model': '${ROAM_MODEL}',
  'mode': '${ROAM_MODE}',
  'target_url': '${ROAM_TARGET_URL}',
  'output_dirs': '${ROAM_MODEL_DIRS[*]}'.split(),
  'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, indent=2))
"

${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
  "roam.config_confirmed" \
  --actor "orchestrator" --outcome "INFO" \
  --payload "{\"env\":\"${ROAM_ENV}\",\"model\":\"${ROAM_MODEL}\",\"mode\":\"${ROAM_MODE}\"}" 2>/dev/null || true

# v2.42.9 HARD GATE: write env/model/mode marker. Step 1 entry refuses to
# proceed unless this marker exists (or --non-interactive set). Marker
# value embeds env+model+mode so downstream gates can verify non-empty.
mkdir -p "${ROAM_DIR}/.tmp"
echo "$(date +%s)|${ROAM_ENV}|${ROAM_MODEL}|${ROAM_MODE}" > "${ROAM_DIR}/.tmp/0a-confirmed.marker"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_env_model_mode_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_env_model_mode_gate.done"
```
</step>

<step name="1_discover_surfaces">
## Step 1 — Discover surfaces (commander)

Read PLAN.md + CONTEXT.md + RUNTIME-MAP.md (from /vg:review). Identify CRUD-bearing surfaces. Annotate each with URL, role, entity, expected operations.

```bash
# v2.42.9 HARD GATE — refuse step 1 entry unless prior interactive prompts
# fired this run. Closes silent-skip path: AI cannot bypass 0aa+0a question
# batches and proceed to discover/compose/spawn. Bypass requires explicit
# --non-interactive (logged as override-debt by harness via runtime_contract).
RUN_MARK_DIR="${ROAM_DIR}/.tmp"
if [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  for marker in 0aa-confirmed.marker 0a-confirmed.marker; do
    f="${RUN_MARK_DIR}/${marker}"
    if [ ! -f "$f" ]; then
      # 0aa marker may legitimately be missing on first run (no prior state →
      # 0aa skipped its 4-option prompt). Allow only if EXISTING_CONFIG was
      # absent at 0aa entry AND no legacy artifacts triggered HAS_RUN_BEFORE.
      if [ "$marker" = "0aa-confirmed.marker" ] && [ "${HAS_RUN_BEFORE:-false}" = "false" ]; then
        continue
      fi
      echo "⛔ HARD GATE BREACH (v2.42.9): step 1 entered without ${marker}"
      echo "   Prior interactive gate (0aa or 0a) did NOT fire its AskUserQuestion this run."
      echo "   AI must invoke AskUserQuestion per skill spec — silent skip not permitted."
      echo "   Override (NOT recommended, debt-logged): re-run with --non-interactive + explicit"
      echo "   flags (--target-env=X --model=Y --mode=Z) to skip prompts intentionally."
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "roam.gate_breach" --actor "orchestrator" --outcome "FAIL" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing_marker\":\"${marker}\"}" 2>/dev/null || true
      exit 1
    fi
    # Stale marker — must be from THIS run (< 30 min old)
    AGE=$(( $(date +%s) - $(awk -F'|' '{print $1}' "$f" 2>/dev/null || echo 0) ))
    if [ "$AGE" -gt 1800 ]; then
      echo "⛔ HARD GATE BREACH: ${marker} stale (${AGE}s old)"
      echo "   Marker must be written THIS run, not reused from prior session."
      echo "   Delete ${RUN_MARK_DIR}/ and re-invoke /vg:roam to refire prompts."
      exit 1
    fi
  done
  # Sanity: env/model/mode resolved to non-empty values (catches AI writing
  # marker but leaving vars empty)
  if [ -z "${ROAM_ENV:-}" ] || [ -z "${ROAM_MODEL:-}" ] || [ -z "${ROAM_MODE:-}" ]; then
    echo "⛔ HARD GATE BREACH: marker present but ROAM_ENV/MODEL/MODE empty"
    echo "   env='${ROAM_ENV:-}' model='${ROAM_MODEL:-}' mode='${ROAM_MODE:-}'"
    echo "   Step 0a did not actually resolve the 3-question batch."
    exit 1
  fi
fi

# Resume guard (v2.42.6+): skip when aggregate-only mode, OR when resuming + SURFACES.md already exists
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  echo "▸ aggregate-only mode — skipping step 1 (discover_surfaces)"
  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
elif [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [ -f "${ROAM_DIR}/SURFACES.md" ] && [[ ! "$ARGUMENTS" =~ --refresh-surfaces ]]; then
  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
  echo "▸ resume mode — reusing existing SURFACES.md (${SURFACE_COUNT} surfaces). Pass --refresh-surfaces to re-discover."
else
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-discover-surfaces.py \
    --phase-dir "${PHASE_DIR}" \
    --output "${ROAM_DIR}/SURFACES.md"

  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
  echo "▸ Discovered ${SURFACE_COUNT} surface(s)"
fi

# Cost cap check
MAX_SURFACES=${VG_MAX_SURFACES:-50}
if [[ "$ARGUMENTS" =~ --max-surfaces=([0-9]+) ]]; then MAX_SURFACES="${BASH_REMATCH[1]}"; fi
if [ "$SURFACE_COUNT" -gt "$MAX_SURFACES" ]; then
  echo "⚠ Surface count ${SURFACE_COUNT} exceeds cap ${MAX_SURFACES}. Trimming to top ${MAX_SURFACES} by entity priority."
  # roam-discover-surfaces.py respects --max-surfaces; this branch is defensive
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "1_discover_surfaces" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_discover_surfaces.done"
```
</step>

<step name="2_compose_briefs">
## Step 2 — Compose per-surface task briefs (commander)

For each surface × selected lens × per-model dir, generate INSTRUCTION-{surface}-{lens}.md with verbatim HARD RULES + RCRURD sequence + env-injected URL/credentials + cwd convention.

```bash
# Resume guard (v2.42.6+): skip when aggregate-only, OR resume + briefs already exist
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  echo "▸ aggregate-only mode — skipping step 2 (compose_briefs)"
  BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2_compose_briefs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_compose_briefs.done"
elif [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [[ ! "$ARGUMENTS" =~ --refresh-briefs ]]; then
  EXISTING_BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  EXPECTED_BRIEF_COUNT=$((SURFACE_COUNT * ${#ROAM_MODEL_DIRS[@]}))
  if [ "$EXISTING_BRIEF_COUNT" -ge "$SURFACE_COUNT" ]; then
    echo "▸ resume mode — reusing existing INSTRUCTION-*.md (${EXISTING_BRIEF_COUNT} briefs across ${#ROAM_MODEL_DIRS[@]} model dir(s)). Pass --refresh-briefs to regenerate."
    BRIEF_COUNT=$EXISTING_BRIEF_COUNT
    SKIP_COMPOSE=1
  fi
fi

if [ "${SKIP_COMPOSE:-0}" != "1" ] && [ "${ROAM_RESUME_MODE:-fresh}" != "aggregate-only" ]; then

LENS_LIST="${VG_LENS:-auto}"
if [[ "$ARGUMENTS" =~ --lens=([a-z,-]+) ]]; then LENS_LIST="${BASH_REMATCH[1]}"; fi

# Resolve env-specific creds via Python helper (one source of truth for URL+creds injection)
# Anchor on `credentials:` block first — vg.config.md has multiple `local:` sections
# (environments.local, services.local, credentials.local) that must not be confused.
${PYTHON_BIN:-python3} -c "
import json, re, sys, pathlib
text = open('.claude/vg.config.md', encoding='utf-8').read()
env = '${ROAM_ENV}'
roles = []
cm = re.search(r'^credentials:\s*\$', text, re.M)
if cm:
    after = text[cm.end():cm.end()+10000]
    lm = re.search(rf'^\s+{re.escape(env)}:\s*\$', after, re.M)
    if lm:
        section = after[lm.end():lm.end()+5000]
        for rm in re.finditer(r'-\s*role:\s*\"([^\"]+)\"\s*\n\s*domain:\s*\"([^\"]+)\"\s*\n\s*email:\s*\"([^\"]+)\"\s*\n\s*password:\s*\"([^\"]+)\"', section):
            roles.append({'role': rm.group(1), 'domain': rm.group(2), 'email': rm.group(3), 'password': rm.group(4)})
            if len(roles) >= 5: break
pathlib.Path('${ROAM_DIR}/.env-creds.json').write_text(json.dumps({'env': env, 'roles': roles}, indent=2))
print(f'[roam] extracted {len(roles)} role(s) for env={env}', file=sys.stderr)
"

# Compose briefs into EACH per-model dir (council = 2 dirs, single = 1)
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  MODEL_NAME=$(basename "$MODEL_DIR")
  ${PYTHON_BIN:-python3} .claude/scripts/roam-compose-brief.py \
    --phase-dir "${PHASE_DIR}" \
    --surfaces "${ROAM_DIR}/SURFACES.md" \
    --lenses "${LENS_LIST}" \
    --output-dir "${MODEL_DIR}" \
    --env "${ROAM_ENV}" \
    --target-url "${ROAM_TARGET_URL}" \
    --creds-json "${ROAM_DIR}/.env-creds.json" \
    --model "${MODEL_NAME}" \
    --cwd-convention "\${PHASE_DIR}/roam/${MODEL_NAME}" \
    --include-security "$([[ "$ARGUMENTS" =~ --include-security ]] && echo true || echo false)"
done

BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
echo "▸ Composed ${BRIEF_COUNT} brief(s) across ${#ROAM_MODEL_DIRS[@]} model dir(s)"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2_compose_briefs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_compose_briefs.done"

fi  # end SKIP_COMPOSE guard
```
</step>

<step name="3_spawn_executors">
## Step 3 — Run executors (branched by `$ROAM_MODE`)

**Branch A — `$ROAM_MODE=spawn`:** subprocess each CLI per brief, parallel-bounded, capture stdout JSONL.
**Branch B — `$ROAM_MODE=manual`:** generate PASTE-PROMPT.md per model dir + display the paste prompt to user. User runs in their preferred CLI (Claude Code / Codex / Cursor / web ChatGPT), drops JSONL in the model dir, then signals continue.

CWD contract for executors (both branches): `${PHASE_DIR}/roam/${MODEL}/` so all artifacts land beside the brief.

```bash
# Resume guard (v2.42.6+): aggregate-only mode skips step 3 entirely;
# resume mode triggers per-brief skip in spawn loop (observe-X.jsonl
# with ≥1 event = brief already done).
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  EXISTING_OBSERVE=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
  echo "▸ aggregate-only mode — skipping step 3. Found ${EXISTING_OBSERVE} observe-*.jsonl ready for aggregate."
  if [ "$EXISTING_OBSERVE" -eq 0 ]; then
    echo "  ⚠ No observe-*.jsonl found in ${ROAM_MODEL_DIRS[*]}. Did you drop manual-mode JSONL files there?"
  fi
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "3_spawn_executors" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_spawn_executors.done"
else  # not aggregate-only — run executors

# Pre-spawn cost estimator (spawn mode only)
EST_USD=$(${PYTHON_BIN:-python3} -c "
brief_count = ${BRIEF_COUNT:-0}
print(f'{brief_count * 0.08:.2f}')
")
SOFT_CAP=${VG_MAX_COST_USD:-10}
if [[ "$ARGUMENTS" =~ --max-cost-usd=([0-9.]+) ]]; then SOFT_CAP="${BASH_REMATCH[1]}"; fi

if [ "$ROAM_MODE" = "self" ]; then
  # v2.42.11 — current Claude session is the executor via MCP Playwright.
  # No subprocess, no Chromium permission issue, login works because the
  # current model is authed via the MCP servers. Sequential per-brief.
  echo "▸ Self mode — current Claude session executes ${BRIEF_COUNT} brief(s) via MCP Playwright"
  echo ""
  echo "AI INSTRUCTIONS (verbatim — follow exactly):"
  echo "  1. For each INSTRUCTION-*.md in ${ROAM_MODEL_DIRS[*]} (lexical order):"
  echo "     a. Skip if observe-{surface}-{lens}.jsonl already exists with ≥1 line."
  echo "     b. Read the brief's Pre-flight section. Login FIRST via mcp__playwright1__browser_navigate"
  echo "        to login URL, mcp__playwright1__browser_fill_form with creds, submit, wait."
  echo "     c. Emit login confirmation event (JSON, single line) into observe file."
  echo "     d. Run lens protocol steps verbatim using mcp__playwright[1-5]__browser_* tools."
  echo "     e. Emit one JSON line per step. Each line MUST be valid JSON (no markdown)."
  echo "     f. Final event: {\"surface\":\"S##\",\"step\":\"complete\",\"total_events\":N}"
  echo "  2. After all briefs done, fall through to step 4 aggregate."
  echo ""
  echo "  Bound: ~3-5 min per brief × 19 briefs / parallel cap 1 (Playwright lock) = ~60-90 min."
  echo "  Per-brief skip handled by AI checking observe-*.jsonl existence before login."

  # Sanity ping: verify Playwright MCP responds
  if ! grep -q 'mcp__playwright' .claude/settings.json .claude/settings.local.json 2>/dev/null; then
    echo "  ⚠ Could not detect Playwright MCP in settings.json — AI may need to fall back to manual."
  fi

elif [ "$ROAM_MODE" = "spawn" ]; then
  echo "▸ Spawn mode — estimated cost: \$${EST_USD} (soft cap: \$${SOFT_CAP})"
  if (( $(echo "$EST_USD > $SOFT_CAP" | bc -l 2>/dev/null) )); then
    [[ ! "$ARGUMENTS" =~ --non-interactive ]] && echo "⚠ Cost > soft cap — confirm via AskUserQuestion before proceeding."
  fi

  # Resolve CLI command per model
  declare -A CLI_CMD_FOR_MODEL
  CLI_CMD_FOR_MODEL[codex]='cat "{brief}" | codex exec --full-auto'        # use config default model (gpt-5.3-codex effort=high)
  CLI_CMD_FOR_MODEL[gemini]='cat "{brief}" | gemini -m gemini-2.5-pro -p "follow brief verbatim, output JSONL only" --yolo'

  declare -a PIDS
  for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
    MODEL_NAME=$(basename "$MODEL_DIR")
    CLI_TEMPLATE="${CLI_CMD_FOR_MODEL[$MODEL_NAME]}"

    for brief in "$MODEL_DIR"/INSTRUCTION-*.md; do
      [ -f "$brief" ] || continue
      surface_lens=$(basename "$brief" .md | sed 's/^INSTRUCTION-//')
      out="${MODEL_DIR}/observe-${surface_lens}.jsonl"
      err="${MODEL_DIR}/observe-${surface_lens}.err"

      # Per-brief resume skip (v2.42.6+): if observe file exists + has any
      # non-empty line, skip this brief. We don't validate JSON here — any
      # content means the brief was attempted; commander will catch malformed
      # JSON during step 4 aggregate.
      if [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [ -s "$out" ] && [[ ! "$ARGUMENTS" =~ --refresh-spawn ]]; then
        EVENT_COUNT=$(grep -c . "$out" 2>/dev/null | head -1)
        EVENT_COUNT=${EVENT_COUNT:-0}
        if [ "$EVENT_COUNT" -gt 0 ]; then
          echo "  ↷ skip ${surface_lens} (${EVENT_COUNT} lines already)"
          continue
        fi
      fi

      RENDERED=$(echo "$CLI_TEMPLATE" | sed "s|{brief}|${brief}|g")

      (
        cd "$MODEL_DIR"   # CWD convention: executor runs from per-model dir
        timeout 600 bash -c "$RENDERED" > "$out" 2>"$err"
        echo "exit_code=$?" >> "$err"
      ) &
      PIDS+=($!)

      # Throttle: max 5 parallel (Playwright lock cap)
      if [ ${#PIDS[@]} -ge 5 ]; then
        wait "${PIDS[0]}"
        PIDS=("${PIDS[@]:1}")
      fi
    done
  done
  [ ${#PIDS[@]} -gt 0 ] && wait "${PIDS[@]}"
  echo "✓ All spawn executors completed"

elif [ "$ROAM_MODE" = "manual" ]; then
  echo "▸ Manual mode — generating PASTE-PROMPT.md per model dir"

  for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
    MODEL_NAME=$(basename "$MODEL_DIR")
    PASTE="${MODEL_DIR}/PASTE-PROMPT.md"
    BRIEF_LIST=$(ls "$MODEL_DIR"/INSTRUCTION-*.md 2>/dev/null | xargs -n1 basename)
    BRIEF_COUNT_MODEL=$(echo "$BRIEF_LIST" | wc -l | tr -d ' ')
    ABS_MODEL_DIR=$(cd "$MODEL_DIR" && pwd)

    cat > "$PASTE" <<EOF
# PASTE PROMPT — /vg:roam executor (model: ${MODEL_NAME}, env: ${ROAM_ENV})

Copy the block below + paste into your CLI of choice (Claude Code, Codex,
Cursor, web ChatGPT). The CLI must have Playwright MCP available.

\`\`\`
You are running roam executor for phase ${PHASE_NUMBER} on env=${ROAM_ENV}.
Working directory (cwd): ${ABS_MODEL_DIR}

There are ${BRIEF_COUNT_MODEL} INSTRUCTION-*.md files in cwd. Process them one
by one in lexical order. For each:

1. Read the file (it has full lens protocol + URL + creds inlined).
2. Follow steps verbatim using Playwright MCP (browser_navigate, browser_fill_form,
   browser_click, browser_snapshot, browser_network_requests, browser_console_messages).
3. Login FIRST per the brief's "Pre-flight" section before running protocol steps.
4. Write JSONL events ONE PER LINE to: observe-<surface>-<lens>.jsonl in cwd.
   The filename must match the INSTRUCTION-<surface>-<lens>.md basename
   (replace INSTRUCTION- prefix with observe-, .md → .jsonl).
5. Each line MUST be valid JSON. NO markdown. NO commentary outside JSON.
6. Do NOT redact PII (commander redacts).
7. After each brief, print a single line to STDERR: "DONE <surface>-<lens> events=N"
8. When all ${BRIEF_COUNT_MODEL} briefs done, print "ALL DONE" to STDERR.

Files (in lexical order):
${BRIEF_LIST}

START NOW. Read first INSTRUCTION file, login, run protocol, emit JSONL.
\`\`\`

After ALL briefs complete, the JSONL files in this dir get aggregated by
\`/vg:roam ${PHASE_NUMBER} --resume-aggregate\` (or by re-invoking roam — it'll
detect existing observe-*.jsonl and skip step 3 for that model).
EOF

    echo ""
    echo "━━━ PASTE PROMPT for model=${MODEL_NAME} ━━━"
    echo "  File: ${PASTE}"
    echo "  Briefs: ${BRIEF_COUNT_MODEL} INSTRUCTION-*.md in ${ABS_MODEL_DIR}"
    echo ""
    echo "  Copy from line below, paste into your CLI:"
    echo ""
    sed -n '/^```$/,/^```$/p' "$PASTE" | grep -v '^```$'
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  done

  # Manual mode resume awareness (v2.42.6+):
  # If $ROAM_RESUME_MODE=resume AND PASTE-PROMPT.md already exists in all model dirs,
  # AND some observe-*.jsonl files have been dropped, prefer pointing user to
  # /vg:roam --aggregate-only instead of regenerating paste prompts.
  if [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ]; then
    EXIST_PASTE=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "PASTE-PROMPT.md" 2>/dev/null | wc -l | tr -d ' ')
    EXIST_OBS=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$EXIST_PASTE" -gt 0 ] && [ "$EXIST_OBS" -gt 0 ]; then
      echo ""
      echo "▸ Manual mode resume — found ${EXIST_PASTE} PASTE-PROMPT.md + ${EXIST_OBS} observe-*.jsonl already."
      echo "  If executor runs are done, re-invoke: /vg:roam ${PHASE_NUMBER} --aggregate-only"
      echo "  If still pasting/running, leave them — re-run later."
    fi
  fi

  # Pause: ask user if all manual runs finished + JSONL ready in dirs
  if [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
    echo ""
    echo "→ When all CLI runs finished, re-invoke /vg:roam ${PHASE_NUMBER} --aggregate-only"
    echo "  (or set VG_ROAM_RESUME=1 + signal continue to this session)"
    echo ""
    # AI: invoke AskUserQuestion "Manual roam runs complete? (yes / abort)"
    # If abort → exit 1
    # If yes → fall through to step 4 aggregate
  fi
fi  # end if spawn/elif manual

fi  # end aggregate-only guard

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "3_spawn_executors" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/3_spawn_executors.done"
```

**Recursion (commander loop):** scan emitted observe-*.jsonl for `spawn-child` events. For each, compose new brief + spawn/manual-paste executor. Bound: max recursion depth 3, max children per parent 5.
</step>

<step name="4_aggregate_logs">
## Step 4 — Aggregate raw logs (commander)

```bash
# Merge observe-*.jsonl from EVERY model dir into single RAW-LOG.jsonl
> "${ROAM_DIR}/RAW-LOG.jsonl"
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  cat "$MODEL_DIR"/observe-*.jsonl >> "${ROAM_DIR}/RAW-LOG.jsonl" 2>/dev/null || true
done
EVENT_COUNT=$(wc -l < "${ROAM_DIR}/RAW-LOG.jsonl" 2>/dev/null | tr -d ' ' || echo 0)
EXEC_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "observe-*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
echo "▸ Aggregated ${EVENT_COUNT} events from ${EXEC_COUNT} executor output(s) across ${#ROAM_MODEL_DIRS[@]} model dir(s)"

# v2.42.9+ — Evidence completeness validator (HARD gate per scanner-report-contract)
# Rejects observations missing required tier fields. Output tagged for commander.
echo ""
echo "▸ Evidence completeness check (rule: REQUIRED fields per tier — empty/null OK, missing = reject)"
COMPLIANCE_OUT="${ROAM_DIR}/evidence-compliance.json"
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  "${PYTHON_BIN:-python3}" .claude/scripts/verify-scanner-evidence-completeness.py \
    --jsonl-glob "${MODEL_DIR}/observe-*.jsonl" \
    --lens-from-filename \
    --threshold "${ROAM_EVIDENCE_THRESHOLD:-80}" \
    --output "${COMPLIANCE_OUT}" 2>&1 | tail -10
  COMPL_RC=$?
  if [ $COMPL_RC -eq 1 ]; then
    echo "⛔ Evidence completeness BLOCK — see ${COMPLIANCE_OUT}"
    if [[ ! "${ARGUMENTS}" =~ --skip-evidence-completeness ]]; then
      echo "   Override (NOT recommended): /vg:roam ${PHASE_NUMBER} --skip-evidence-completeness"
      echo "   Recommended: re-run scanner — it produced too many incomplete observations."
      exit 1
    fi
    echo "⚠ --skip-evidence-completeness set — proceeding with partial evidence"
  elif [ $COMPL_RC -eq 2 ]; then
    echo "⚠ Evidence completeness WARN — partial coverage, commander will deprioritize"
  fi
done

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "4_aggregate_logs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_aggregate_logs.done"
```
</step>

<step name="5_analyze_findings">
## Step 5 — Commander analysis (THE judgment step)

Run deterministic Python rules R1-R8 over RAW-LOG.jsonl. Classify findings into severity buckets. Output ROAM-BUGS.md + proposed .spec.ts files.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/roam-analyze.py \
  --raw-log "${ROAM_DIR}/RAW-LOG.jsonl" \
  --phase-dir "${PHASE_DIR}" \
  --output-md "${ROAM_DIR}/ROAM-BUGS.md" \
  --output-specs-dir "${ROAM_DIR}/proposed-specs" \
  --output-summary "${ROAM_DIR}/RUN-SUMMARY.json"

BUGS_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${ROAM_DIR}/RUN-SUMMARY.json')); print(d.get('total_bugs',0))" 2>/dev/null || echo 0)
CRIT_COUNT=$("${PYTHON_BIN:-python3}" -c "import json; d=json.load(open('${ROAM_DIR}/RUN-SUMMARY.json')); print(d.get('by_severity',{}).get('critical',0))" 2>/dev/null || echo 0)
echo "▸ Found ${BUGS_COUNT} bugs (${CRIT_COUNT} critical)"

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.analysis.completed" \
  --actor "orchestrator" --outcome "INFO" --payload "{\"bugs\":${BUGS_COUNT},\"critical\":${CRIT_COUNT}}" 2>/dev/null || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "5_analyze_findings" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_analyze_findings.done"
```
</step>

<step name="6_emit_artifacts">
## Step 6 — Emit artifacts + update PIPELINE-STATE

ROAM-BUGS.md, RUN-SUMMARY.json already written by step 5. Update PIPELINE-STATE.json with roam verdict.

```bash
${PYTHON_BIN:-python3} -c "
import json, datetime
from pathlib import Path
p = Path('${PHASE_DIR}/PIPELINE-STATE.json')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
steps = s.setdefault('steps', {})
roam = steps.setdefault('roam', {})
roam['status'] = 'done'
roam['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
roam['bugs_total'] = ${BUGS_COUNT:-0}
roam['bugs_critical'] = ${CRIT_COUNT:-0}
roam['verdict'] = 'BLOCK_ACCEPT' if ${CRIT_COUNT:-0} > 0 else 'PASS'
p.write_text(json.dumps(s, indent=2))
"

if [ "${CRIT_COUNT:-0}" -gt 0 ]; then
  echo "⛔ ${CRIT_COUNT} critical bug(s) — blocks /vg:accept until resolved or override-debt logged"
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "6_emit_artifacts" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_emit_artifacts.done"
```
</step>

<step name="7_optional_fix_loop">
## Step 7 — Optional fix loop (gated by `--auto-fix`)

If `--auto-fix` flag set, for each top-N bug: spawn fix subagent (Sonnet/Opus), apply fix → atomic commit → re-roam affected surface only → verify resolved. Max 5 fixes per session. Default: report only (per Q1).

```bash
if [[ ! "$ARGUMENTS" =~ --auto-fix ]]; then
  echo "ℹ Skipping fix loop (default). Pass --auto-fix to enable."
else
  echo "▸ Running auto-fix loop on top 5 bugs..."
  # Implementation: read ROAM-BUGS.md, dispatch fix tasks via Task tool with Sonnet
  # subagent, after each fix re-run roam on affected surface, max 5 fixes
  # See ROAM-RFC-v1.md section 6.
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "7_optional_fix_loop" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_optional_fix_loop.done"
```
</step>

<step name="complete">
## Final — emit completion event + summary

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "roam.session.completed" \
  --actor "orchestrator" --outcome "INFO" \
  --payload "{\"surfaces\":${SURFACE_COUNT:-0},\"events\":${EVENT_COUNT:-0},\"bugs\":${BUGS_COUNT:-0}}" 2>/dev/null || true

echo ""
echo "━━━ Roam complete — Phase ${PHASE_NUMBER} ━━━"
echo "  Surfaces:    ${SURFACE_COUNT:-0}"
echo "  Events:      ${EVENT_COUNT:-0}"
echo "  Bugs total:  ${BUGS_COUNT:-0}"
echo "  Critical:    ${CRIT_COUNT:-0}"
echo "  Output:      ${ROAM_DIR}/ROAM-BUGS.md"
echo "  New specs:   ${ROAM_DIR}/proposed-specs/ (use /vg:roam --merge-specs to merge into test suite)"

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "complete" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/complete.done"
```
</step>

## Special invocation modes

### `--merge-specs`

Skip phases 0-7 entirely. Read existing `${PHASE_DIR}/roam/proposed-specs/*.spec.ts`, validate each via vg-codegen-interactive validator, merge into project test suite path (per `paths.tests` in vg.config.md). Manual gate (Q10).

```bash
if [[ "$ARGUMENTS" =~ --merge-specs ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-merge-specs.py \
    --phase-dir "${PHASE_DIR}" \
    --proposed-dir "${PHASE_DIR}/roam/proposed-specs" \
    --target-dir "$(grep -oP 'tests:\s*\K\S+' .claude/vg.config.md)"
  exit 0
fi
```

## Open

Implementation pending — see `.vg/research/ROAM-RFC-v1.md` section 8 for resolved defaults (Q1-Q18) + section 10 for v1.0 → v2.0 roadmap. Scripts referenced in this skill (`roam-discover-surfaces.py`, `roam-compose-brief.py`, `roam-analyze.py`, `roam-merge-specs.py`) are stubs to be filled in next session.
