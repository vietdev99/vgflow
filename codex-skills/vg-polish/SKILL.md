---
name: "vg-polish"
description: "Optional code-cleanup pass — strip console.log, trailing whitespace, empty blocks. Atomic commit per fix. NOT a pipeline gate; user invokes when ready."
metadata:
  short-description: "Optional code-cleanup pass — strip console.log, trailing whitespace, empty blocks. Atomic commit per fix. NOT a pipeline gate; user invokes when ready."
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

For tasklist projection, Codex must write evidence before any step marker call:
after `emit-tasklist.py`, run `vg-orchestrator tasklist-projected --adapter codex`
as its own tool call. Do not group `tasklist-projected` and `step-active` in
one shell command; PreToolUse evaluates the entire command before the evidence
file exists and will block the grouped command.

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

Invoke this skill as `$vg-polish`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Optional, not a gate** — pipeline (specs → scope → blueprint → build → review → test → accept) does NOT depend on `/vg:polish` running. User invokes when satisfied with feature work and wants a tidy-up pass.
2. **Atomic per fix** — each fix is ONE commit. Failure reverts that fix only; other fixes survive.
3. **Light is safe** — light mode only touches code that can never affect runtime (console.log, trailing whitespace, empty blocks). No typecheck loop needed.
4. **Deep is gated** — deep mode requires test re-run after each fix; revert on regression.
5. **Read-only by default** — `--scan` (default) shows candidates without writing. `--apply` is the only mode that commits.
6. **Telemetry over judgement** — every applied / reverted fix emits an event. Decide ROI from `/vg:telemetry --command=vg:polish` after a few months of dogfood, then promote (or kill) features.
</rules>

<objective>
Surface and (optionally) auto-fix low-risk code-cleanliness issues that pile up across build / fix loops:
- `console.log` / `console.debug` / `console.info` / `console.warn` left over from debugging
- trailing whitespace
- empty `if {}` / `else {}` / `catch {}` / function bodies (refactor leftovers)

Modes:
- `--scan` (default) — print ranked candidates, write nothing
- `--apply` — apply fixes one-by-one, atomic commit per fix
- `--level=light` (default) — only the 3 categories above. Safe on production code (TS/JS/Python).
- `--level=deep` — light + warn on long functions (>80 lines). v1: warn-only, no auto-refactor.

Pipeline position: anytime after a code-touching step (`/vg:build`, `/vg:review`, `/vg:test`). NOT wired into accept gate.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

<step name="0_validate_prereqs">
## Step 0: Validate

```bash
set -euo pipefail
source .claude/commands/vg/_shared/config-loader.md 2>/dev/null || true
source .claude/commands/vg/_shared/telemetry.md 2>/dev/null || true
export VG_CURRENT_COMMAND="vg:polish"

# Engine script must exist
POLISH_PY="${REPO_ROOT:-.}/.claude/scripts/vg_polish.py"
[ -f "$POLISH_PY" ] || POLISH_PY="${REPO_ROOT:-.}/scripts/vg_polish.py"
if [ ! -f "$POLISH_PY" ]; then
  echo "⛔ vg_polish.py engine not found. Reinstall vgflow."
  exit 1
fi

# Inside a git repo
git rev-parse --show-toplevel >/dev/null 2>&1 || {
  echo "⛔ Not in a git repository. /vg:polish needs git for atomic commits."
  exit 1
}

# Working tree must be clean — atomic-commit semantics break with dirty tree
if [ -n "$(git status --porcelain)" ]; then
  echo "⚠ Working tree dirty. Either commit/stash first, or run with explicit --allow-dirty."
  echo "  (--allow-dirty makes commits include your in-flight changes — usually not what you want.)"
  case " ${ARGUMENTS:-} " in
    *" --allow-dirty "*) echo "  Continuing with --allow-dirty …" ;;
    *) exit 1 ;;
  esac
fi
```
</step>

<step name="1_parse_args">
## Step 1: Parse args

```bash
MODE="scan"
LEVEL="light"
SCOPE=""
DRY_RUN=""
ALLOW_DIRTY=""

for arg in ${ARGUMENTS}; do
  case "$arg" in
    --scan)         MODE="scan" ;;
    --apply)        MODE="apply" ;;
    --level=*)      LEVEL="${arg#--level=}" ;;
    --scope=*)      SCOPE="${arg#--scope=}" ;;
    --since=*)      SCOPE="since:${arg#--since=}" ;;
    --file=*)       SCOPE="file:${arg#--file=}" ;;
    --dry-run)      DRY_RUN="--dry-run" ;;
    --allow-dirty)  ALLOW_DIRTY="--allow-dirty" ;;
    *) ;;
  esac
done

case "$LEVEL" in
  light|deep) ;;
  *)
    echo "⛔ Invalid --level=${LEVEL}. Expected: light | deep"
    exit 1
    ;;
esac

echo "Mode: $MODE | Level: $LEVEL | Scope: ${SCOPE:-<repo>}"
```
</step>

<step name="2_emit_started">
## Step 2: Emit polish.started telemetry

```bash
if type -t emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "polish.started" "" "" "" "INFO" \
    "{\"mode\":\"$MODE\",\"level\":\"$LEVEL\",\"scope\":\"${SCOPE:-repo}\"}" \
    >/dev/null 2>&1 || true
fi
```
</step>

<step name="3_run_engine">
## Step 3: Run engine

`vg_polish.py` does the actual scan + apply. Slash command is a thin wrapper that adds telemetry + arg parsing + git-state guards. Engine handles per-fix atomic commit, typecheck (deep mode), and revert.

```bash
SCAN_OUT=$(mktemp)

${PYTHON_BIN:-python3} "$POLISH_PY" \
  --mode "$MODE" \
  --level "$LEVEL" \
  ${SCOPE:+--scope "$SCOPE"} \
  ${DRY_RUN} \
  ${ALLOW_DIRTY} \
  --report "$SCAN_OUT"

ENGINE_EXIT=$?
```

The engine prints human-readable progress to stdout and writes a structured JSON report to `$SCAN_OUT` for telemetry consumption.
</step>

<step name="4_emit_completed">
## Step 4: Emit polish.completed telemetry

Read engine report and emit summary event.

```bash
if [ -s "$SCAN_OUT" ]; then
  PAYLOAD=$(${PYTHON_BIN:-python3} -c "
import json, sys
with open('$SCAN_OUT', 'r', encoding='utf-8') as f:
  r = json.load(f)
summary = {
  'candidates': r.get('candidates_count', 0),
  'applied': r.get('applied_count', 0),
  'reverted': r.get('reverted_count', 0),
  'mode': r.get('mode', 'scan'),
  'level': r.get('level', 'light'),
  'exit_code': $ENGINE_EXIT,
}
print(json.dumps(summary))
")

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    OUTCOME="PASS"
    [ "$ENGINE_EXIT" -ne 0 ] && OUTCOME="FAIL"
    emit_telemetry_v2 "polish.completed" "" "" "" "$OUTCOME" "$PAYLOAD" \
      >/dev/null 2>&1 || true
  fi
fi

rm -f "$SCAN_OUT" 2>/dev/null
exit $ENGINE_EXIT
```
</step>

<step name="5_resume">
```
Polish complete.

  Mode:        $MODE
  Level:       $LEVEL
  Scope:       ${SCOPE:-<repo>}

Next:
  - Review commits:  git log --oneline -<applied_count>
  - Re-run scan:     /vg:polish --scope=$SCOPE
  - View telemetry:  /vg:telemetry --command=vg:polish
```
</step>

</process>

<example_use_cases>
1. **After /vg:build wave finishes**: `/vg:polish --scope=phase-7` to strip debug logs accumulated during build.
2. **Pre-PR cleanup**: `/vg:polish --since=main --apply` to clean up the branch before merge.
3. **Single-file targeted clean**: `/vg:polish --file=apps/web/src/components/Foo.tsx --apply`.
4. **Dry-run inspection**: `/vg:polish --apply --dry-run` to preview applies without committing.
5. **Deep pass after major fix loop**: `/vg:polish --level=deep --scope=phase-7` to surface long-function warnings (no auto-refactor in v1).
</example_use_cases>

<success_criteria>
- `--scan` mode lists ranked candidates per file, writes nothing.
- `--apply` produces N atomic commits, one per fix. Commits have the same author as user's git config.
- Each commit message: `polish: {fix_type} in {file}` with body citing scope.
- Engine emits `polish.fix_applied` per success and `polish.fix_reverted` per revert.
- Working tree clean after run (no leftover staging).
- Telemetry: `/vg:telemetry --command=vg:polish` shows aggregated counts.
- Skip-if-empty-tree guard rejects dirty working tree unless `--allow-dirty`.
</success_criteria>
