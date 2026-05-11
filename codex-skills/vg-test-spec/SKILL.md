---
name: "vg-test-spec"
description: "Post-build deep test-spec authoring — derive lifecycle specs, fixture DAG, localizer prompt, and execution plan before review"
metadata:
  short-description: "Post-build deep test-spec authoring — derive lifecycle specs, fixture DAG, localizer prompt, and execution plan before review"
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

`.claude/scripts/*` and `.claude/commands/*` are canonical VGFlow source
paths shared by both adapters; those paths do not mean the runtime changed to
Claude. References below to "Claude CLI", `TodoWrite`, or Haiku describe the
Claude adapter only. Codex must map them through this adapter contract instead
of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
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

Invoke this skill as `$vg-test-spec`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<LANGUAGE_POLICY>
Follow `_shared/language-policy.md`. Default narration is Vietnamese; file
paths, command names, JSON keys, and code identifiers stay English.
</LANGUAGE_POLICY>

<objective>
Run the dedicated deep test-spec lane after `/vg:build` and before
`/vg:review`.

Why this exists:
- Blueprint is too early: implemented DOM, route files, API handlers, generated
  UI, and concrete form state may not exist yet.
- Build must not self-certify runtime coverage.
- Review should verify runtime against a pre-authored deep spec contract, not
  discover test depth late and route it ambiguously.

Pipeline:
`specs → scope → blueprint → build → test-spec → review → test → accept`
</objective>

<rules>
1. This command is post-build only. Missing `SUMMARY*.md`, `BUILD-LOG.md`, or
   `.build-progress.json` BLOCKs with guidance to run `/vg:build`.
2. It authors test-depth contracts, not executable test specs. Executable
   specs still belong to `/vg:test`.
3. Mutation and multi-actor goals must get closed-loop RCRURDR coverage:
   read_before → create → read_after_create → update → read_after_update →
   delete → read_after_delete.
4. Fixture dependencies must be explicit: actors, sessions, resource ownership,
   artifact sinks, cleanup order.
5. VG is profile-aware. Web may use Playwright, mobile may use Maestro/Appium/native,
   CLI may use command assertions, backend may use HTTP/RPC/job checks, library may
   use unit/property tests.
6. Review consumes these artifacts. If review finds runtime blockers, stay in
   review/debug. If runtime is clean but executable specs are missing, route to
   `/vg:test`.
</rules>

<process>

<step name="0_parse_and_validate">
```bash
set -euo pipefail

REPO_ROOT="$(pwd)"
PHASE_NUMBER="$(printf '%s\n' "${ARGUMENTS:-}" | awk '{print $1}')"
if [ -z "${PHASE_NUMBER:-}" ]; then
  echo "⛔ Missing phase. Usage: /vg:test-spec <phase>"
  exit 1
fi

VG_HOME="${VG_HOME:-${HOME}/.vgflow}"
ORCH="${REPO_ROOT}/.claude/scripts/vg-orchestrator"
[ -e "$ORCH" ] || ORCH="${VG_HOME}/scripts/vg-orchestrator"
if [ ! -e "$ORCH" ]; then
  echo "⛔ vg-orchestrator missing. Re-sync VGFlow global install."
  exit 1
fi

MAX_FILES="1200"
AI_RESPONSE=""
for tok in ${ARGUMENTS:-}; do
  case "$tok" in
    --max-files=*) MAX_FILES="${tok#--max-files=}" ;;
    --ai-response=*) AI_RESPONSE="${tok#--ai-response=}" ;;
    --regen) ;;
    *) ;;
  esac
done

PHASE_RESOLVER="${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-resolver.sh"
[ -f "$PHASE_RESOLVER" ] || PHASE_RESOLVER="${VG_HOME}/commands/vg/_shared/lib/phase-resolver.sh"
source "$PHASE_RESOLVER" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR="$(resolve_phase_dir "$PHASE_NUMBER")"
else
  PHASE_DIR="$(ls -d "${REPO_ROOT}/.vg/phases/${PHASE_NUMBER}"* "${REPO_ROOT}/.vg/phases/$(printf '%02d' "$PHASE_NUMBER" 2>/dev/null)"* 2>/dev/null | head -1)"
fi
if [ -z "${PHASE_DIR:-}" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "⛔ Phase dir not found for ${PHASE_NUMBER}"
  exit 1
fi

"${PYTHON_BIN:-python3}" "$ORCH" run-start vg:test-spec "${PHASE_NUMBER}" "${ARGUMENTS:-}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}
mkdir -p "${PHASE_DIR}/.step-markers/test-spec"
touch "${PHASE_DIR}/.step-markers/test-spec/0_parse_and_validate.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 0_parse_and_validate 2>/dev/null || true
"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.started" --step "0_parse_and_validate" --actor "llm-claimed" \
  --outcome "INFO" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
```
</step>

<step name="1_build_artifact_gate">
```bash
if ! ls "${PHASE_DIR}"/SUMMARY*.md >/dev/null 2>&1 && \
   [ ! -f "${PHASE_DIR}/BUILD-LOG.md" ] && \
   [ ! -d "${PHASE_DIR}/BUILD-LOG" ] && \
   [ ! -f "${PHASE_DIR}/.build-progress.json" ]; then
  echo "⛔ /vg:test-spec requires build evidence first."
  echo "   Run: /vg:build ${PHASE_NUMBER}"
  exit 1
fi

if [ ! -f "${PHASE_DIR}/TEST-GOALS.md" ] && [ ! -d "${PHASE_DIR}/TEST-GOALS" ]; then
  echo "⛔ /vg:test-spec requires TEST-GOALS from blueprint."
  echo "   Run: /vg:blueprint ${PHASE_NUMBER}"
  exit 1
fi

touch "${PHASE_DIR}/.step-markers/test-spec/1_build_artifact_gate.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 1_build_artifact_gate 2>/dev/null || true
```
</step>

<step name="2_generate_deep_specs">
```bash
SCRIPT="${REPO_ROOT}/.claude/scripts/generate-deep-test-specs.py"
[ -f "$SCRIPT" ] || SCRIPT="${REPO_ROOT}/scripts/generate-deep-test-specs.py"
[ -f "$SCRIPT" ] || SCRIPT="${VG_HOME}/scripts/generate-deep-test-specs.py"
if [ ! -f "$SCRIPT" ]; then
  echo "⛔ generate-deep-test-specs.py missing. Re-sync VGFlow."
  exit 1
fi

AI_ARGS=()
if [ -n "${AI_RESPONSE:-}" ]; then
  AI_ARGS=(--ai-response "${AI_RESPONSE}")
fi

"${PYTHON_BIN:-python3}" "$SCRIPT" \
  --phase "${PHASE_NUMBER}" \
  --phase-dir "${PHASE_DIR}" \
  --root "${REPO_ROOT}" \
  --max-files "${MAX_FILES}" \
  "${AI_ARGS[@]}" \
  --json > "${PHASE_DIR}/.deep-test-spec-summary.json"

"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.generated" --step "2_generate_deep_specs" --actor "llm-claimed" \
  --outcome "PASS" --payload "$(cat "${PHASE_DIR}/.deep-test-spec-summary.json")" >/dev/null 2>&1 || true

touch "${PHASE_DIR}/.step-markers/test-spec/2_generate_deep_specs.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 2_generate_deep_specs 2>/dev/null || true
```
</step>

<step name="3_validate_deep_specs">
```bash
VALIDATOR="${REPO_ROOT}/.claude/scripts/validators/verify-deep-test-specs.py"
[ -f "$VALIDATOR" ] || VALIDATOR="${REPO_ROOT}/scripts/validators/verify-deep-test-specs.py"
[ -f "$VALIDATOR" ] || VALIDATOR="${VG_HOME}/scripts/validators/verify-deep-test-specs.py"
if [ ! -f "$VALIDATOR" ]; then
  echo "⛔ verify-deep-test-specs.py missing. Re-sync VGFlow."
  exit 1
fi

"${PYTHON_BIN:-python3}" "$VALIDATOR" --phase "${PHASE_NUMBER}" \
  > "${PHASE_DIR}/.deep-test-spec-verify.json" 2>&1

touch "${PHASE_DIR}/.step-markers/test-spec/3_validate_deep_specs.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 3_validate_deep_specs 2>/dev/null || true
```
</step>

<step name="4_complete">
```bash
"${PYTHON_BIN:-python3}" - <<PY
import json
from datetime import datetime
from pathlib import Path
p = Path("${PHASE_DIR}") / "PIPELINE-STATE.json"
state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
state.setdefault("steps", {}).setdefault("test-spec", {})
state["steps"]["test-spec"].update({
    "status": "done",
    "verdict": "PASS",
    "updated_at": datetime.now().isoformat(),
})
state["pipeline_step"] = "test-spec-complete"
state["updated_at"] = datetime.now().isoformat()
p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
PY

touch "${PHASE_DIR}/.step-markers/test-spec/4_complete.done"
"${PYTHON_BIN:-python3}" "$ORCH" mark-step test-spec 4_complete 2>/dev/null || true
"${PYTHON_BIN:-python3}" "$ORCH" emit-event \
  "test_spec.completed" --step "4_complete" --actor "llm-claimed" \
  --outcome "PASS" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
"${PYTHON_BIN:-python3}" "$ORCH" run-complete --outcome PASS 2>/dev/null || true

echo "✓ /vg:test-spec complete"
echo "  Wrote: ${PHASE_DIR}/DEEP-TEST-SPECS.md"
echo "  Wrote: ${PHASE_DIR}/LIFECYCLE-SPECS.json"
echo "  Wrote: ${PHASE_DIR}/TEST-FIXTURE-DAG.json"
echo "  Wrote: ${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
echo "  Wrote: ${PHASE_DIR}/TEST-SPEC-LOCALIZER/PROMPT.md"
echo "  Wrote: ${PHASE_DIR}/PLAYWRIGHT-SPEC-PLAN.md"
echo "  Next:  /vg:review ${PHASE_NUMBER}"
```
</step>

</process>

<success_criteria>
- Build evidence existed before generation.
- Deep test-spec artifacts exist and pass `verify-deep-test-specs.py`.
- `TEST-EXECUTION-PLAN.json` selects runner family from phase profile.
- `TEST-SPEC-LOCALIZER/PROMPT.md` exists for optional project-local AI expansion.
- `PIPELINE-STATE.json` marks `steps.test-spec.status=done`.
- Next command is `/vg:review <phase>`.
</success_criteria>
