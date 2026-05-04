---
name: "vg-gate-stats"
description: "Gate telemetry query surface — counts by gate_id/outcome, filter by --gate-id/--since/--outcome, flags high-override gates"
metadata:
  short-description: "Gate telemetry query surface — counts by gate_id/outcome, filter by --gate-id/--since/--outcome, flags high-override gates"
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

Invoke this skill as `$vg-gate-stats`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `gate (cổng)`, `override (bỏ qua)`, `outcome (kết quả)`, `telemetry (đo đạc)`, `milestone (mốc)`, `threshold (ngưỡng)`, `event (sự kiện)`. Không áp dụng: file path, code ID, outcome ID (PASS/FAIL/OVERRIDE).
</NARRATION_POLICY>

<rules>
1. **Read-only** — queries telemetry JSONL only. No writes.
2. **Delegate to `telemetry_query` + `telemetry_warn_overrides`** — no reimplementation of event parsing.
3. **Filters** — `--gate-id=X`, `--since=ISO8601`, `--outcome=PASS|FAIL|OVERRIDE|SKIP|BLOCK|WARN`. Unfiltered = all events.
4. **Flag high-override gates** — threshold from `CONFIG_OVERRIDE_WARN_THRESHOLD` (default 2).
5. **Single `gate_stats_run` event** per invocation.
</rules>

<objective>
Answer: "Which gates fire most often? Which are being overridden too much?"

Produces a sorted table by total event volume, with per-outcome breakdown. Surfaces gates exceeding override threshold as remediation targets.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse filters + load helpers

```bash
PLANNING_DIR=".vg"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || {
  echo "⛔ telemetry.sh missing — cannot query" >&2
  exit 1
}

FILTER_GATE=""
FILTER_SINCE=""
FILTER_OUTCOME=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --gate-id=*) FILTER_GATE="${arg#--gate-id=}" ;;
    --since=*)   FILTER_SINCE="${arg#--since=}" ;;
    --outcome=*) FILTER_OUTCOME="${arg#--outcome=}" ;;
    --*)         echo "⚠ Unknown flag: $arg" ;;
    *)           echo "⚠ Positional arg ignored: $arg (use --gate-id=)" ;;
  esac
done

export VG_CURRENT_COMMAND="vg:gate-stats"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "📊 ━━━ /vg:gate-stats ━━━"
[ -n "$FILTER_GATE" ]    && echo "  Filter gate-id: ${FILTER_GATE}"
[ -n "$FILTER_SINCE" ]   && echo "  Filter since:   ${FILTER_SINCE}"
[ -n "$FILTER_OUTCOME" ] && echo "  Filter outcome: ${FILTER_OUTCOME}"
echo ""

if [ ! -f "$TELEMETRY_PATH" ]; then
  echo "  (no telemetry yet — run some VG commands first)"
  exit 0
fi
```
</step>

<step name="1_aggregate">
## Step 1: Aggregate events into per-gate × per-outcome counts

```bash
# Use telemetry_query when filters apply (it handles them); else stream raw file.
if type telemetry_query >/dev/null 2>&1 && { [ -n "$FILTER_GATE" ] || [ -n "$FILTER_SINCE" ] || [ -n "$FILTER_OUTCOME" ]; }; then
  QUERY_ARGS=()
  [ -n "$FILTER_GATE" ]    && QUERY_ARGS+=("--gate-id=${FILTER_GATE}")
  [ -n "$FILTER_SINCE" ]   && QUERY_ARGS+=("--since=${FILTER_SINCE}")
  [ -n "$FILTER_OUTCOME" ] && QUERY_ARGS+=("--outcome=${FILTER_OUTCOME}")
  STREAM_CMD=("telemetry_query" "${QUERY_ARGS[@]}")
  "${STREAM_CMD[@]}" > /tmp/vg-gate-stats.jsonl
  INPUT="/tmp/vg-gate-stats.jsonl"
else
  INPUT="$TELEMETRY_PATH"
fi

${PYTHON_BIN} - "$INPUT" <<'PY'
import json, sys
from collections import defaultdict
path = sys.argv[1]
counts = defaultdict(lambda: defaultdict(int))
try:
  for line in open(path, encoding='utf-8'):
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      gid = ev.get("gate_id")
      outc = ev.get("outcome")
      if gid and outc in ("PASS", "FAIL", "SKIP", "OVERRIDE", "BLOCK", "WARN"):
          counts[gid][outc] += 1
    except: pass
except FileNotFoundError:
  pass

if not counts:
  print("  (no gate events match filter)")
  sys.exit(0)

totals = {g: sum(oc.values()) for g, oc in counts.items()}
sorted_gates = sorted(counts.keys(), key=lambda g: -totals[g])

print("## Gate event counts")
print()
print("  | Gate | PASS | FAIL | BLOCK | OVERRIDE | SKIP | WARN | Total |")
print("  |------|------|------|-------|----------|------|------|-------|")
for g in sorted_gates:
    oc = counts[g]
    print(f"  | {g} | {oc.get('PASS',0)} | {oc.get('FAIL',0)} | {oc.get('BLOCK',0)} | {oc.get('OVERRIDE',0)} | {oc.get('SKIP',0)} | {oc.get('WARN',0)} | {totals[g]} |")
print()
PY
```
</step>

<step name="2_override_warn">
## Step 2: Surface high-override gates

```bash
echo "## High-override gates (bỏ qua nhiều)"
echo ""
THRESHOLD="${CONFIG_OVERRIDE_WARN_THRESHOLD:-2}"
if type telemetry_warn_overrides >/dev/null 2>&1; then
  telemetry_warn_overrides "$THRESHOLD" || echo "   (no gates exceed threshold ${THRESHOLD})"
else
  echo "   (telemetry_warn_overrides unavailable)"
fi
echo ""

echo "## Recommendations"
echo "   • If a gate is being overridden too often → investigate:"
echo "     - Is the gate threshold too strict?"
echo "     - Is the agent rationalizing past valid concerns?"
echo "     - Review ${PLANNING_DIR}/OVERRIDE-DEBT.md entries for that gate."
echo "   • Drill into a specific gate:  /vg:gate-stats --gate-id=X"
echo "   • Scope to recent window:      /vg:gate-stats --since=2026-04-01"
echo ""
```
</step>

<step name="3_telemetry">
## Step 3: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  payload="{\"filter_gate\":\"${FILTER_GATE}\",\"filter_since\":\"${FILTER_SINCE}\",\"filter_outcome\":\"${FILTER_OUTCOME}\"}"
  emit_telemetry_v2 "gate_stats_run" "project" "gate-stats" "" "PASS" "$payload" >/dev/null 2>&1 || true
fi
rm -f /tmp/vg-gate-stats.jsonl 2>/dev/null || true
```
</step>

</process>

<success_criteria>
- Pure read — no writes to telemetry or registers.
- Filters pass through to `telemetry_query` helper.
- Output = sorted table + override-pressure section + actionable drill-down hints.
- Single `gate_stats_run` telemetry event.
</success_criteria>
</content>
</invoke>
