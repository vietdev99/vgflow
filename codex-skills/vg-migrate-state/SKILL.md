---
name: "vg-migrate-state"
description: "Detect + backfill phase state drift (missing step markers) after VG harness upgrades"
metadata:
  short-description: "Detect + backfill phase state drift (missing step markers) after VG harness upgrades"
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

Invoke this skill as `$vg-migrate-state`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Repair phase state drift introduced by VG harness upgrades. When a skill
adds new `<step>` blocks (or wires `mark-step` where it wasn't wired
before), phases that already ran the OLD skill miss the new markers.
`/vg:accept` then BLOCKs even though the pipeline actually ran end-to-end.

This command detects + backfills missing markers based on artifact
evidence (PLAN.md, REVIEW-FEEDBACK.md, SANDBOX-TEST.md, etc.). Idempotent.
Companion to Tier B (`.contract-pins.json` written at `/vg:scope`) which
prevents future drift; this command repairs legacy phases that pre-date
the pin mechanism.

Drift is detected per (phase, command) pair:
- Read step list from `.claude/commands/vg/{cmd}.md`
- Check artifact evidence (e.g. PLAN.md proves `/vg:blueprint` ran)
- If evidence present + markers missing → drift candidate
- If no evidence → skip (don't fabricate markers for commands that never ran)

**Auto-invocation by Stop hook (v2.8.3 hybrid recovery):**
This script is also invoked automatically by `vg-verify-claim.py` (Stop
hook) when run-complete BLOCKs purely on `must_touch_markers` AND the
same run_id has hit drift ≥ 2 times in the session. The hook calls
`migrate-state.py {phase} --apply` and retries run-complete; on retry
PASS, the session approves with telemetry event `hook.marker_drift_recovered`.
Manual invocation remains the canonical path — auto-invoke is a safety
net for skill-cache restart cycles, not a substitute for AI discipline.
</objective>

<process>

<step name="0_session_lifecycle">
Standard session banner + EXIT trap. No state mutation.

```bash
PHASE_NUMBER="${PHASE_NUMBER:-migrate-state}"
mkdir -p ".vg/.tmp"
```
</step>

<step name="1_parse_args">
Parse positional + flag arguments.

```bash
PHASE_ARG=""
SCAN=0
APPLY_ALL=0
DRY_RUN=0
JSON=0
for arg in $ARGUMENTS; do
  case "$arg" in
    --scan)        SCAN=1 ;;
    --apply-all)   APPLY_ALL=1 ;;
    --dry-run)     DRY_RUN=1 ;;
    --json)        JSON=1 ;;
    --*)           echo "⛔ Unknown flag: $arg" >&2; exit 2 ;;
    *)             PHASE_ARG="$arg" ;;
  esac
done

# Default: --scan if no positional + no apply-all
if [ -z "$PHASE_ARG" ] && [ $APPLY_ALL -eq 0 ] && [ $SCAN -eq 0 ]; then
  SCAN=1
fi
```
</step>

<step name="2_run_migrate">
Delegate to `migrate-state.py`. Script handles scan/apply/dry-run logic.

```bash
ARGS=()
[ -n "$PHASE_ARG" ] && ARGS+=("$PHASE_ARG")
[ $SCAN -eq 1 ]      && ARGS+=("--scan")
[ $APPLY_ALL -eq 1 ] && ARGS+=("--apply-all")
[ $DRY_RUN -eq 1 ]   && ARGS+=("--dry-run")
[ $JSON -eq 1 ]      && ARGS+=("--json")

"${PYTHON_BIN:-python3}" .claude/scripts/migrate-state.py "${ARGS[@]}"
RC=$?

# Emit telemetry
EVENT_TYPE="migrate_state.scanned"
[ $APPLY_ALL -eq 1 ] || ([ -n "$PHASE_ARG" ] && [ $DRY_RUN -eq 0 ]) && \
  EVENT_TYPE="migrate_state.applied"

PAYLOAD=$(printf '{"phase":"%s","mode":"%s","exit":%d}' \
  "${PHASE_ARG:-all}" \
  "$([ $DRY_RUN -eq 1 ] && echo dry-run || echo apply)" \
  "$RC")
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "$EVENT_TYPE" --payload "$PAYLOAD" >/dev/null 2>&1 || true
```

Exit codes:
- 0 → no drift OR migration applied successfully
- 1 → drift detected (--scan/--dry-run only)
- 2 → invalid args / phase not found / IO error
</step>

<step name="3_complete">
Self-mark final step.

```bash
mkdir -p ".vg/.step-markers/migrate-state" 2>/dev/null
touch ".vg/.step-markers/migrate-state/3_complete.done"
```
</step>

</process>

<success_criteria>
- `--scan` produces a project-wide drift table without writing anything
- `--apply` (or `{phase}` shorthand) backfills missing markers based on artifact evidence
- Single OD entry per applied phase (not per marker — prevents register bloat)
- Idempotent: re-running on a sync'd phase prints "no drift" + zero new OD entries
- `--dry-run` reports what would be backfilled without writing
- Phases without artifact evidence for a command are skipped (no fabricated markers)
</success_criteria>

<usage_examples>

**See project-wide drift before deciding what to fix:**
```
/vg:migrate-state --scan
```
Output: phase × (ran-commands, skipped, missing-markers) table.

**Preview what one phase would change:**
```
/vg:migrate-state 7.14.3 --dry-run
```

**Fix one phase + log audit trail:**
```
/vg:migrate-state 7.14.3
```

**Batch fix every phase with drift:**
```
/vg:migrate-state --apply-all
```

**Pipe machine-readable scan into other tooling:**
```
/vg:migrate-state --scan --json | jq '.scan[] | select(.totals.missing_markers > 0).phase'
```

</usage_examples>

<related>
- `marker-migrate.py` — one-time legacy fix for empty marker files (different drift class)
- `verify-step-markers.py` — gate that detects drift at `/vg:accept` time
- `.vg/OVERRIDE-DEBT.md` — schema-versioned audit trail
- Tier B (`/vg:scope` writes `.contract-pins.json`) — prevents future drift
</related>
