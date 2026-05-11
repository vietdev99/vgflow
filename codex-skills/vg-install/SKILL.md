---
name: "vg-install"
description: "Install or repair VGFlow global-only harness at ~/.vgflow and prune project-local .claude/.codex VG files."
metadata:
  short-description: "Install or repair VGFlow global-only harness at ~/.vgflow and prune project-local .claude/.codex VG files."
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

Invoke this skill as `$vg-install`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Install the VG harness globally for this project, then wire hooks via
`vg-cli-dispatcher.sh`.

Global-only contract:
- Workflow source lives in `~/.vgflow/`.
- Codex skills live in `~/.codex/skills`.
- Claude hooks live in `~/.claude/settings.json`.
- Project-local VG-owned `.claude/` and `.codex/` surfaces are pruned on every install/update.
- `.vg/.install-target` is written as `global`.

Architectural reference: docs/plans/2026-05-09-vg-global-install-design.md (Section 3 install + upgrade flow).
</objective>

<process>

<step name="0_parse_args">
```bash
set -u
ARGS="${ARGUMENTS:-}"

TARGET=""
REPAIR=0
for tok in $ARGS; do
  case "$tok" in
    --target=*) TARGET="${tok#--target=}" ;;
    --repair)   REPAIR=1 ;;
    *)          ;;
  esac
done

REPO_ROOT="$(pwd)"
MARKER="${REPO_ROOT}/.vg/.install-target"
LEGACY_VERSION="${REPO_ROOT}/.claude/VGFLOW-VERSION"
HOME_VGFLOW="${HOME}/.vgflow"

CURRENT=""
[ -f "$MARKER" ] && CURRENT="$(tr -d '[:space:]' < "$MARKER")"

echo "vg:install detect:"
echo "  cwd:           ${REPO_ROOT}"
echo "  marker:        ${CURRENT:-(absent)}"
echo "  ~/.vgflow/:    $([ -d "$HOME_VGFLOW" ] && echo present || echo absent)"
echo "  .claude/legacy: $([ -f "$LEGACY_VERSION" ] && echo "yes (v$(cat "$LEGACY_VERSION" 2>/dev/null))" || echo no)"
echo "  --target arg:  ${TARGET:-(unset; global-only)}"
echo "  --repair:      ${REPAIR}"
```
</step>

<step name="1_decide_target">
**Decision matrix:**

| Marker | Legacy | --target | --repair | Action |
|---|---|---|---|---|
| any | any | unset/global | any | Install global, prune project-local VG files, write marker=global |
| any | any | project/switch | any | Deprecated input; coerce to global and print warning |

```bash
if [ -n "$TARGET" ] && [ "$TARGET" != "global" ]; then
  echo "⚠ --target=${TARGET} is deprecated; VGFlow is global-only now. Coercing to global."
fi
RESOLVED="global"

echo "Resolved target: ${RESOLVED}"
```
</step>

<step name="2_apply">
**Backup legacy project harness before pruning.**

```bash
NEED_BACKUP=0
if [ -d "${REPO_ROOT}/.claude/commands/vg" ] || [ -d "${REPO_ROOT}/.codex/skills" ]; then
  NEED_BACKUP=1
fi

if [ "$NEED_BACKUP" = "1" ]; then
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_DIR="${REPO_ROOT}/.vg/.backup-${TS}"
  mkdir -p "$BACKUP_DIR"
  for d in .claude/commands .claude/skills .claude/scripts; do
    if [ -d "${REPO_ROOT}/${d}" ]; then
      cp -R "${REPO_ROOT}/${d}" "${BACKUP_DIR}/$(basename "$d")" 2>/dev/null || true
    fi
  done
  if [ -f "${REPO_ROOT}/.claude/settings.json" ]; then
    cp "${REPO_ROOT}/.claude/settings.json" "${BACKUP_DIR}/settings.json.bak" 2>/dev/null || true
  fi
  echo "vg:install backup: ${BACKUP_DIR}"
fi
```

**Apply target via dispatcher.** Resolve dispatcher path:

```bash
DISPATCHER=""
for candidate in \
  "${HOME_VGFLOW}/bin/vg-cli-dispatcher.sh" \
  "${VG_HOME:-}/bin/vg-cli-dispatcher.sh" \
  "${REPO_ROOT}/bin/vg-cli-dispatcher.sh"; do
  if [ -f "$candidate" ]; then
    DISPATCHER="$candidate"
    break
  fi
done

if [ -z "$DISPATCHER" ]; then
  echo "⛔ vg-cli-dispatcher.sh not found. Install vgflow first:"
  echo "  npm install -g vgflow"
  echo "  OR  git clone https://github.com/vietdev99/vgflow ~/.vgflow"
  exit 1
fi

VG_HOME="$(dirname "$(dirname "$DISPATCHER")")" \
  bash "$DISPATCHER" install "--${RESOLVED}"
```

The dispatcher writes the marker (Stage 4 wiring). Verify:

```bash
NEW_MARKER="$(tr -d '[:space:]' < "$MARKER" 2>/dev/null || true)"
if [ "$NEW_MARKER" != "$RESOLVED" ]; then
  echo "⚠ marker mismatch: expected ${RESOLVED}, got ${NEW_MARKER:-(absent)}"
  echo "  Re-running marker write directly..."
  mkdir -p "${REPO_ROOT}/.vg"
  printf '%s\n' "$RESOLVED" > "$MARKER"
fi

echo "vg:install applied: ${RESOLVED}"
```
</step>

<step name="3_complete">
Emit telemetry + summary:

```bash
${PYTHON_BIN:-python3} - <<EOF
import json, time, urllib.request, sys
ts = int(time.time() * 1000)
payload = {"target": "${RESOLVED}", "previous": "${CURRENT}", "repair": ${REPAIR}, "ts_ms": ts}
print(f"vg:install telemetry: {json.dumps(payload)}")
EOF

echo ""
echo "✓ vg:install complete"
echo "  target:    ${RESOLVED}"
echo "  marker:    ${MARKER}"
echo "  hooks at:  ${HOME}/.claude/settings.json"
[ "$NEED_BACKUP" = "1" ] && echo "  backup:    ${BACKUP_DIR}"
echo ""
echo "Restart Claude Code / Codex session to load updated hooks."
```
</step>

</process>

<success_criteria>
- `.vg/.install-target` written with `global`
- `~/.claude/settings.json` contains VG hook entries in global mode
- Project-local VG-owned `.claude/` and `.codex/` files are removed or backed up
- `install.started` + `install.completed` telemetry events emitted
- Restart hint printed to stdout
</success_criteria>
