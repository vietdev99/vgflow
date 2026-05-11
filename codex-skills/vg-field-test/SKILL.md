---
name: "vg-field-test"
description: "User-driven field test capture — AI opens MCP Playwright browser with floating Start/Stop/Mark overlay; human roams manually; AI silently captures browser console + network + clicks + nav + per-Mark notes + correlated API server log tails. On Stop, analyzer subagent produces FIELD-REPORT.md + appends entries to .vg/KNOWN-ISSUES.json. Distinct from AI-driven /vg:roam."
metadata:
  short-description: "User-driven field test capture — AI opens MCP Playwright browser with floating Start/Stop/Mark overlay; human roams manually; AI silently captures browser console + network + clicks + nav + per-Mark notes + correlated API server log tails. On Stop, analyzer subagent produces FIELD-REPORT.md + appends entries to .vg/KNOWN-ISSUES.json. Distinct from AI-driven /vg:roam."
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
`VG_RUNTIME=codex`, use Codex `update_plan` for the compact visible task
window, and bind it with `vg-orchestrator tasklist-projected --adapter codex`.

VGFlow source paths are resolved through global `VG_HOME` (default:
`~/.vgflow`). Project-local Claude workflow files may be absent in
global-only installs; Codex must use
`${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}` and
`${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}` for workflow
helpers. References below to "Claude CLI", `TodoWrite`, or Haiku describe
the Claude adapter only. Codex must map them through this adapter contract
instead of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use `tasklist-contract.json` as source of truth. Do not paste the full hierarchy into Codex `update_plan`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and `+N pending`. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`. |
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
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh --tier planner` |
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
bash "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh" \
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

Invoke this skill as `$vg-field-test`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<HARD-GATE>
This skill captures live user behavior. Default redaction applies to
console, network, API log streams, and user notes. Screenshots are NOT redacted.

⚠ Do NOT navigate to password/payment/credentials views during this session
  unless that is the explicit test target. Screenshots embed pixel content as-is.

Atomic lock at `.vg/field-test/.active` prevents concurrent sessions.
On crash, manual cleanup: `rm -rf .vg/field-test/.active`
(or run `python scripts/field-test/release-lock.py --root .`).

v1 does NOT support `--resume`. A browser crash mid-session leaves raw
streams under `.vg/field-test/<sid>/` for manual triage; rerun
`build-bundle.py` + `analyze.py` manually if needed.
</HARD-GATE>

## Overview

`/vg:field-test` is a USER-driven exploratory capture skill. Distinct from `/vg:roam`:
- `/vg:roam` = AI-driven. Spawns executors that auto-replay lenses against discovered surfaces.
- `/vg:field-test` = USER-driven. Human roams manually; AI is a silent recorder.

On Stop, an analyzer subagent produces `FIELD-REPORT.md` and appends entries to `.vg/KNOWN-ISSUES.json`. Downstream consumers (`/vg:test-spec`, `/vg:review`) read those entries to enrich lifecycle context.

## Step 0: Preflight (`0_preflight`)

```bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# v2.1 §3: atomic lock via mkdir (NOT echo > file — TOCTOU race).
mkdir -p "${REPO_ROOT}/.vg/field-test" 2>/dev/null
if ! mkdir "${REPO_ROOT}/.vg/field-test/.active" 2>/dev/null; then
  ACTIVE_OWNER=$(cat "${REPO_ROOT}/.vg/field-test/.active/owner" 2>/dev/null || echo "unknown")
  echo "⛔ field-test session active (sid=${ACTIVE_OWNER})" >&2
  echo "   Run: python scripts/field-test/release-lock.py --root \"${REPO_ROOT}\"" >&2
  echo "   to clear a stuck lock (PID-aware)." >&2
  exit 1
fi

# Build session id: ft-<ts> (or ft-p<N>-<ts> when --phase=N supplied).
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
PHASE_TAG=""
case " $ARGUMENTS " in *" --phase="*)
  PHASE_NUMBER=$(echo "$ARGUMENTS" | sed -n 's/.*--phase=\([^ ]*\).*/\1/p')
  PHASE_TAG="-p${PHASE_NUMBER}"
  ;;
esac
SID="ft${PHASE_TAG}-${TS}"
SESSION_DIR="${REPO_ROOT}/.vg/field-test/${SID}"
mkdir -p "${SESSION_DIR}/marks"

# Record owner PID for release-lock.py liveness check.
printf '%s' "$SID" > "${REPO_ROOT}/.vg/field-test/.active/owner"
printf '%s' "$$" > "${REPO_ROOT}/.vg/field-test/.active/pid"
trap 'rm -rf "${REPO_ROOT}/.vg/field-test/.active"' EXIT
```

## Step 1: Resolve config (`1_resolve_config`)

Use `AskUserQuestion` to confirm:
- **Redaction regex** — precedence order:
  1. If `--redact=<regex>` was passed in `$ARGUMENTS`, use it directly (skip the question).
  2. Else if `vg.config.md` has `field_test.default_redaction`, prompt with it as default.
  3. Else prompt with hard-coded multi-form default (`password|token|secret|api[_-]?key|email|phone`).
- **API log sources** — precedence:
  1. If `vg.config.md` has `field_test.api_log_sources`, prompt to confirm/edit.
  2. Else prompt user for at least one source.
- **Base URL** — precedence:
  1. `--base-url=<url>` flag from `$ARGUMENTS`.
  2. `vg.config.md` `field_test.default_base_url`.
  3. Prompt user.

Write `${SESSION_DIR}/session.json` matching `schemas/field-test-session.v1.json`.

## Step 2: Launch browser (`2_launch_browser`)

```
mcp__playwright1__browser_navigate({ url: "<base_url>" })
```

## Step 3: Inject overlay (`3_inject_overlay`)

```bash
OVERLAY_PATH="${REPO_ROOT}/scripts/field-test/overlay.js"
OVERLAY_JS=$(cat "$OVERLAY_PATH")
```

Then call:
```
mcp__playwright1__browser_evaluate({
  function: "() => { ${OVERLAY_JS} }"
})
```

Verify injection:
```
mcp__playwright1__browser_evaluate({
  function: "() => typeof window.__VG_FT_INIT === 'function'"
})
```

## Step 4: Wait for Start (`4_wait_start`)

Poll `mcp__playwright1__browser_console_messages` with offset tracking for `[VG_FT] start` edge event.

On hit:
```bash
# Spawn per-source tails (each pipes through redact-stream.py at capture).
for src_label in $(${PYTHON_BIN} -c "import json,sys; [print(s['label']) for s in json.load(open(sys.argv[1]))['sources']]" "${SESSION_DIR}/session.json"); do
  SRC_TYPE=$(${PYTHON_BIN} -c "import json,sys; s=[x for x in json.load(open(sys.argv[1]))['sources'] if x['label']==sys.argv[2]][0]; print(s['type'])" "${SESSION_DIR}/session.json" "$src_label")
  SRC_TARGET=$(${PYTHON_BIN} -c "import json,sys; s=[x for x in json.load(open(sys.argv[1]))['sources'] if x['label']==sys.argv[2]][0]; print(s['target'])" "${SESSION_DIR}/session.json" "$src_label")
  REDACT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('redaction') or 'default')" "${SESSION_DIR}/session.json")
  bash "${REPO_ROOT}/scripts/field-test/tail-source.sh" \
    --type "$SRC_TYPE" --target "$SRC_TARGET" \
    --out "${SESSION_DIR}/api-${src_label}.log" \
    --redact "$REDACT" &
  echo "$!" >> "${SESSION_DIR}/.tail-pids"
done

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.session_started --payload "{\"sid\":\"$SID\"}"
```

## Step 5: Capture loop (`5_capture_loop`)

v2.1 §1 + MUST-4: poll overlay state directly (NOT console_messages — that is a snapshot reader that replays the buffer and would duplicate marks). On SPA full-reload, the browser wipes `window.__VG_FT_STATE` and the next re-inject restarts `reload_epoch=0` — detect via `epoch < last_epoch` (K→0 transition) and reset `last_consumed=0`.

```bash
last_consumed=0
last_epoch=0

while true; do
  # AI tool call:
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => window.__VG_FT_STATE ? ({ len: window.__VG_FT_STATE.marks.length, status: window.__VG_FT_STATE.status, epoch: window.__VG_FT_STATE.reload_epoch }) : null"
  #   })
  #
  # If null returned (full reload erased state): re-inject overlay.js, set last_consumed=0.
  # Else if returned.epoch < last_epoch: full reload — re-inject + last_consumed=0.
  # Else if returned.len > last_consumed:
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => window.__VG_FT_STATE.marks.slice(N, M)"  # N=last_consumed, M=returned.len
  #   })
  #   For each new mark <n,...>:
  #     mcp__playwright1__browser_take_screenshot({ filename: "${SESSION_DIR}/marks/<n>.png" })
  #     mcp__playwright1__browser_snapshot({ filename: "${SESSION_DIR}/marks/<n>.snapshot.yml" })
  #     append entry to ${SESSION_DIR}/marks.raw.jsonl
  #     emit field_test.mark_recorded with payload {"sid": "$SID", "n": <n>}
  #   last_consumed = returned.len
  #
  # If returned.status == "stopped": break and proceed to Step 6.

  # v2.1 MUST-2: enforce size + wall-clock caps each iter.
  if ! ${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/check-quota.py" --session-dir "${SESSION_DIR}"; then
    echo "⛔ quota exceeded — forcing Stop" >&2
    break
  fi

  sleep 2
done
```

## Step 6: Stop + bundle (`6_stop_finalize`)

```bash
# Kill tails: TERM → 5s grace → KILL.
if [ -f "${SESSION_DIR}/.tail-pids" ]; then
  while read -r tpid; do
    kill -TERM "$tpid" 2>/dev/null || true
  done < "${SESSION_DIR}/.tail-pids"
  sleep 5
  while read -r tpid; do
    kill -KILL "$tpid" 2>/dev/null || true
  done < "${SESSION_DIR}/.tail-pids"
fi

# Dump any remaining overlay buffers via browser_evaluate.
# (AI emits: mcp__playwright1__browser_evaluate({function: "() => JSON.stringify(window.__VG_FT_STATE.buffer)"})
#  and writes result to ${SESSION_DIR}/buffer.dump.json)

# Build bundle.
${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/build-bundle.py" \
  --session-dir "${SESSION_DIR}" \
  --mark-window-sec "${MARK_WINDOW_SEC:-30}"

# v2.1 / #175: emit evidence-manifest entries for the bundle artifacts.
EMIT_MANIFEST="${REPO_ROOT}/.claude/scripts/emit-evidence-manifest.py"
[ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
if [ -f "$EMIT_MANIFEST" ]; then
  ${PYTHON_BIN} "$EMIT_MANIFEST" \
    --path "${SESSION_DIR}/manifest.json" \
    --producer "vg:field-test 6_stop_finalize" \
    --source-inputs "${SESSION_DIR}/session.json,${SESSION_DIR}/marks.raw.jsonl" \
    --quiet || true
fi

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.session_stopped --payload "{\"sid\":\"$SID\"}"
```

## Step 7: Analyze (`7_analyze`)

Spawn the `vg-field-test-analyzer` subagent (see `agents/vg-field-test-analyzer/SKILL.md`). Subagent runs `analyze.py` deterministically, then optionally augments `FIELD-REPORT.md` with LLM narrative on HIGH/MEDIUM marks.

```bash
${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/analyze.py" \
  --session-dir "${SESSION_DIR}" \
  --known-issues "${REPO_ROOT}/.vg/KNOWN-ISSUES.json"

# v2.1 / #175: emit evidence-manifest for FIELD-REPORT.md.
# Re-resolve EMIT_MANIFEST in case Step 7 runs in a fresh subshell separated
# from Step 6 (Agent dispatch, etc.).
EMIT_MANIFEST="${REPO_ROOT}/.claude/scripts/emit-evidence-manifest.py"
[ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
if [ -f "$EMIT_MANIFEST" ] && [ -f "${SESSION_DIR}/FIELD-REPORT.md" ]; then
  ${PYTHON_BIN} "$EMIT_MANIFEST" \
    --path "${SESSION_DIR}/FIELD-REPORT.md" \
    --producer "vg:field-test 7_analyze" \
    --source-inputs "${SESSION_DIR}/manifest.json,${SESSION_DIR}/marks.jsonl" \
    --quiet || true
fi

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.analysis_completed --payload "{\"sid\":\"$SID\"}"
```

## Step 8: Complete (`complete`)

Auto-emit `field_test.session_completed` via MARKER_TO_AUTO_EVENT (Task 7d wiring). Remove lock directory (`trap EXIT` handles this).

```bash
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" mark-step field-test complete
```

## Outputs

- `.vg/field-test/<sid>/manifest.json` — bundle manifest (8 fields).
- `.vg/field-test/<sid>/marks.jsonl` — per-Mark bundle entries.
- `.vg/field-test/<sid>/FIELD-REPORT.md` — human-readable report with severity per Mark.
- `.vg/field-test/<sid>/errors.jsonl` — naive timestamps + truncated lines (NEVER silent drops).
- `.vg/KNOWN-ISSUES.json` — appended entries, deduped by (source=field-test, sid, n).

## Scope (v1 — deferred to v2)

- No `--resume` (implementation absent; plan v2 dropped it).
- No `quick`/`deep` presets (single `standard` profile only).
- No phase-snapshot mirror under versioned directories (committed-or-ignored policy unresolved).
- No `--non-interactive` (user-driven skill has no useful headless mode).
- No auto-recovered crash bundle (manual triage on browser crash).
