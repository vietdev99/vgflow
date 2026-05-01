---
name: "vg-doctor"
description: "Thin dispatcher for VG state inspection — routes to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover. Use sub-commands directly for clarity."
metadata:
  short-description: "Thin dispatcher for VG state inspection — routes to /vg:health, /vg:integrity, /vg:gate-stats, /vg:recover. Use sub-commands directly for clarity."
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
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

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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

Invoke this skill as `$vg-doctor`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. This command is a thin router — actual work happens in sub-commands.

**Translate English terms (RULE)** — `dispatcher (điều phối)`, `sub-command (lệnh con)`, `legacy flag (cờ cũ)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Pure routing** — never does health/integrity/gate/recover work directly. Invokes sub-command via Skill tool.
2. **Positional verb** — first arg parsed as verb: `health | integrity | gate-stats | recover`. Unknown verb → print help.
3. **Legacy flag compat** — `--integrity`, `--gates`, `--recover` emit a DEPRECATED warn and route to new sub-command.
4. **No arg or `help`** — print the 4-sub-command menu and exit 0.
5. **Zero heavy work** — this file stays ≤80 LOC.
</rules>

<process>

<step name="0_parse_verb">
## Step 0: Parse verb + route

```bash
# Extract first positional token + capture remaining args for forwarding.
VERB=""
FWD_ARGS=""
for arg in $ARGUMENTS; do
  case "$arg" in
    health|integrity|gate-stats|recover|recovery|stack|wired|dist|ohok|help)
      [ -z "$VERB" ] && VERB="$arg" || FWD_ARGS="${FWD_ARGS} ${arg}"
      ;;
    --dist|--distribution)
      VERB="dist"
      ;;
    --wired)
      VERB="wired"
      ;;
    --integrity)
      echo "⚠ DEPRECATED: --integrity flag. Use /vg:integrity instead." >&2
      VERB="integrity"
      ;;
    --gates)
      echo "⚠ DEPRECATED: --gates flag. Use /vg:gate-stats instead." >&2
      VERB="gate-stats"
      ;;
    --recover)
      echo "⚠ DEPRECATED: --recover flag. Use /vg:recover {phase} instead." >&2
      VERB="recover"
      ;;
    *)
      FWD_ARGS="${FWD_ARGS} ${arg}"
      ;;
  esac
done

# Default to help when no verb resolved
if [ -z "$VERB" ]; then
  [ -n "$FWD_ARGS" ] && VERB="health"  # bare phase arg → health deep mode (back-compat)
fi
```
</step>

<step name="1_dispatch">
## Step 1: Dispatch (or print help)

The shell block above resolves `VERB` and `FWD_ARGS`. The outer model reads the resolved values and routes via the **Skill tool**:

| Resolved VERB | Skill invocation |
|---------------|------------------|
| `health`      | `Skill(skill="vg:health", args=FWD_ARGS)` |
| `integrity`   | `Skill(skill="vg:integrity", args=FWD_ARGS)` |
| `gate-stats`  | `Skill(skill="vg:gate-stats", args=FWD_ARGS)` |
| `recover`     | `Skill(skill="vg:recover", args=FWD_ARGS)` |
| `stack`       | run `python .claude/scripts/vg-stack-health.py` inline (no sub-skill) |
| `wired`       | run `python .claude/scripts/vg-wired-check.py ${FWD_ARGS}` inline — WIRED-OR-NOTHING 3-check for validators/hooks/commands (OHOK v2 Day 6) |
| `dist`        | run `python .claude/scripts/distribution-check.py --verify ${FWD_ARGS}` inline — compare script+validator hashes vs `.distribution-manifest.json` baseline (detects local drift / tampering). Use `--generate` to rewrite baseline after intentional edits. |
| `ohok`        | run `python .claude/scripts/vg-ohok-metrics.py ${FWD_ARGS}` inline — **behavioral truth measurement** (OHOK-4). Reads events.db, computes true OHOK rate (% runs finishing PASS with 0 overrides + 0 manual promotions), per-command breakdown, override pressure top-N, promote-manual quota usage, validator BLOCK distribution. Accepts `--since 30d`, `--command build`, `--json`. |
| `recovery`    | run `python .claude/scripts/vg-recovery.py ${FWD_ARGS}` inline — **recovery path picker** (v2.46-wave3). Reads latest run from events.db, detects validator BLOCKs, prints actionable recovery paths per violation. Closes UX dead-end where BLOCK gives generic options. Accepts `--phase 3.2` (filter), `--json` (machine-readable). |
| `help` / ""   | print menu below, exit 0 |

For `stack` verb: executes the v2.2 stack diagnostic — orchestrator reachable, events.db integrity, schemas valid, validators present, hooks wired, bootstrap consistent. Exit 0 healthy, 1 warnings, 2 blocking issues.

```bash
if [ -z "$VERB" ] || [ "$VERB" = "help" ]; then
  cat <<'HELP'

🩺 ━━━ /vg:doctor — VG state inspection router ━━━

This command is a thin dispatcher. Use the sub-commands directly for clarity:

  /vg:health [phase]              Project health summary, or phase deep inspect
  /vg:integrity [phase]           Hash-validate artifacts across all (or one) phase
  /vg:gate-stats [--gate-id=X]    Gate event counts + override pressure
  /vg:recover {phase} [--apply]   Classify corruption + print recovery commands
  /vg:doctor stack                v2.2 stack diagnostic (orch + DB + schemas)
  /vg:doctor wired                WIRED-OR-NOTHING validators/hooks/commands check
  /vg:doctor dist [--generate]    Distribution integrity (sha256 manifest drift)
  /vg:doctor ohok [--since 30d]   Behavioral OHOK rate from events.db
  /vg:doctor recovery [--phase X] Recovery path picker for current BLOCK

Legacy flags (DEPRECATED, still routed):
  /vg:doctor --integrity          → /vg:integrity
  /vg:doctor --gates              → /vg:gate-stats
  /vg:doctor --recover {phase}    → /vg:recover {phase}

HELP
  exit 0
fi

echo "→ Routing to /vg:${VERB}${FWD_ARGS}"

# Inline verbs (not Skill subroutes) — execute Python script directly
case "$VERB" in
  recovery)
    python3 .claude/scripts/vg-recovery.py ${FWD_ARGS}
    exit $?
    ;;
  stack|wired|dist|ohok)
    # Other inline verbs handled per matrix above (already in this file's older revisions)
    ;;
esac

# Model side: now invoke Skill(skill="vg:${VERB}", args="${FWD_ARGS}")
```
</step>

</process>

<success_criteria>
- ≤80 LOC, no direct health/integrity/gate/recover logic.
- Legacy `--integrity | --gates | --recover` flags emit DEPRECATED warn and still route correctly.
- Unknown verb or no verb → help menu, exit 0.
- Router prints chosen target; outer model invokes via Skill tool.
</success_criteria>
</content>
</invoke>
