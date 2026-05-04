---
name: "vg-complete-milestone"
description: "Close out a milestone — verify all phases accepted, run security audit + summary, archive phase dirs, advance STATE.md to next milestone"
metadata:
  short-description: "Close out a milestone — verify all phases accepted, run security audit + summary, archive phase dirs, advance STATE.md to next milestone"
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

Invoke this skill as `$vg-complete-milestone`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Atomic milestone closeout. Orchestrates the existing milestone-level pieces into a single command:

1. **Gate check** — every phase resolved for the milestone has UAT.md (= accepted), no critical OPEN threats, no critical OVERRIDE-DEBT entries unresolved.
2. **Security audit** — invokes `/vg:security-audit-milestone --milestone-gate` so decay + composite + Strix-advisory steps run with the milestone gate active.
3. **Aggregate summary** — invokes `/vg:milestone-summary` to refresh the cross-phase report.
4. **Archive phase dirs** — moves `.vg/phases/{N}/` (for phases in this milestone) into `.vg/milestones/{M}/phases/{N}/` via `git mv` to preserve history. Skip with `--no-archive` if you want phases hot-readable for amendments.
5. **Advance STATE.md** — flips `current_milestone` to `M{N+1}` and appends `milestones_completed[]` entry.
6. **Atomic commit** — single commit with all milestone artifacts + state transition. Subject: `milestone(close): {M} — {phase-count} phases archived`.

Pass `--check` to dry-run the gate without mutations. Override blockers with `--allow-open-critical=<reason>` or `--allow-open-override-debt=<reason>` (logs to OVERRIDE-DEBT for next-milestone triage).
</objective>

<process>

<step name="0_args">
```bash
MILESTONE="${1:-}"
if [ -z "$MILESTONE" ]; then
  echo "⛔ Usage: /vg:complete-milestone <milestone-id> [--check] [--allow-open-critical=<reason>] [--no-archive]"
  exit 1
fi
shift

CHECK_ONLY=false
NO_ARCHIVE=false
ALLOW_CRITICAL=""
ALLOW_DEBT=""

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=true ;;
    --no-archive) NO_ARCHIVE=true ;;
    --allow-open-critical=*) ALLOW_CRITICAL="${arg#*=}" ;;
    --allow-open-override-debt=*) ALLOW_DEBT="${arg#*=}" ;;
    *) echo "⚠ Unknown arg: $arg (ignored)" ;;
  esac
done
```
</step>

<step name="1_telemetry_started">
```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/telemetry.sh" 2>/dev/null || true
emit_telemetry_v2 "complete_milestone.started" "" "complete-milestone" \
  "milestone_orchestrator" "INFO" "{\"milestone\":\"${MILESTONE}\",\"check_only\":${CHECK_ONLY}}" 2>/dev/null || true
```
</step>

<step name="2_gate_check">
```bash
echo "━━━ Step 1 — Milestone gate check ━━━"

GATE_ARGS=( "--milestone" "$MILESTONE" )
[ -n "$ALLOW_CRITICAL" ] && GATE_ARGS+=( "--allow-open-critical=$ALLOW_CRITICAL" )
[ -n "$ALLOW_DEBT" ] && GATE_ARGS+=( "--allow-open-override-debt=$ALLOW_DEBT" )

${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py "${GATE_ARGS[@]}" --check
GATE_RC=$?

if [ "$GATE_RC" -ne 0 ]; then
  echo ""
  echo "Gate failed. Resolve blockers above, or pass override flags:"
  echo "  --allow-open-critical=\"<reason>\""
  echo "  --allow-open-override-debt=\"<reason>\""
  exit 1
fi

if [ "$CHECK_ONLY" = "true" ]; then
  echo ""
  echo "✓ --check mode — no mutations performed. Re-run without --check to finalize."
  exit 0
fi
```
</step>

<step name="3_security_audit">
```bash
echo ""
echo "━━━ Step 2 — Security audit (milestone gate) ━━━"

if [ -f ".claude/commands/vg/security-audit-milestone.md" ]; then
  ${PYTHON_BIN:-python3} -c "
import subprocess, sys
# Invoke via the standard slash command surface so all hooks/telemetry fire
# Fall back to direct script call if a runner harness is missing
print('  (delegating to /vg:security-audit-milestone --milestone-gate)')
" || true
  AUDIT_ARGS="--milestone=$MILESTONE --milestone-gate"
  echo "  Run: /vg:security-audit-milestone $AUDIT_ARGS"
  echo "  (this command writes audit + Strix advisory if enabled)"
else
  echo "  ⚠ /vg:security-audit-milestone missing — skipping audit (review hand-off recommended)"
fi
```
</step>

<step name="4_milestone_summary">
```bash
echo ""
echo "━━━ Step 3 — Milestone summary ━━━"

${PYTHON_BIN:-python3} .claude/scripts/generate-milestone-summary.py --milestone "$MILESTONE"
SUM_RC=$?
if [ "$SUM_RC" -ne 0 ]; then
  echo "⚠ Milestone summary failed (rc=${SUM_RC}) — continuing closeout but inspect manually."
fi
```
</step>

<step name="5_archive_phases">
```bash
echo ""
echo "━━━ Step 4 — Archive phase directories ━━━"

if [ "$NO_ARCHIVE" = "true" ]; then
  echo "  (--no-archive — phases left in place at .vg/phases/{N}/)"
else
  PHASE_NUMS=$(${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py \
    --milestone "$MILESTONE" --check --json 2>/dev/null \
    | ${PYTHON_BIN:-python3} -c "import json,sys; d=json.load(sys.stdin); print(' '.join(p.split('-',1)[0] for p in d['phases_resolved']))")

  ARCHIVE_DIR=".vg/milestones/$MILESTONE/phases"
  mkdir -p "$ARCHIVE_DIR"

  ARCHIVED=0
  for phase_num in $PHASE_NUMS; do
    SRC=".vg/phases/${phase_num}"
    if [ ! -d "$SRC" ]; then
      # try suffixed name
      SRC=$(find .vg/phases -maxdepth 1 -type d -name "${phase_num}-*" | head -1)
    fi
    if [ -n "$SRC" ] && [ -d "$SRC" ]; then
      git mv "$SRC" "${ARCHIVE_DIR}/$(basename "$SRC")" 2>/dev/null || \
        mv "$SRC" "${ARCHIVE_DIR}/$(basename "$SRC")"
      echo "  ✓ Archived $SRC → ${ARCHIVE_DIR}/$(basename "$SRC")"
      ARCHIVED=$((ARCHIVED + 1))
    fi
  done
  echo "  → $ARCHIVED phase dirs archived"
fi
```
</step>

<step name="6_finalize_state">
```bash
echo ""
echo "━━━ Step 5 — Advance STATE.md + write completion marker ━━━"

FINAL_ARGS=( "--milestone" "$MILESTONE" "--finalize" )
[ -n "$ALLOW_CRITICAL" ] && FINAL_ARGS+=( "--allow-open-critical=$ALLOW_CRITICAL" )
[ -n "$ALLOW_DEBT" ] && FINAL_ARGS+=( "--allow-open-override-debt=$ALLOW_DEBT" )

${PYTHON_BIN:-python3} .claude/scripts/complete-milestone.py "${FINAL_ARGS[@]}"
FINAL_RC=$?

if [ "$FINAL_RC" -ne 0 ]; then
  echo "⛔ Finalize failed (rc=${FINAL_RC}) — STATE.md NOT advanced. Inspect logs."
  exit 1
fi
```
</step>

<step name="7_atomic_commit">
```bash
echo ""
echo "━━━ Step 6 — Atomic commit ━━━"

PHASE_COUNT=$(ls -1 .vg/milestones/${MILESTONE}/phases/ 2>/dev/null | wc -l | tr -d ' ')
COMMIT_MSG="milestone(close): ${MILESTONE} — ${PHASE_COUNT} phases archived"

git add .vg/STATE.md .vg/milestones/${MILESTONE}/ 2>/dev/null

if git diff --cached --quiet; then
  echo "  (nothing staged — skipping commit)"
else
  git commit -m "$COMMIT_MSG" 2>&1 | tail -5
fi

emit_telemetry_v2 "complete_milestone.completed" "" "complete-milestone" \
  "milestone_orchestrator" "PASS" \
  "{\"milestone\":\"${MILESTONE}\",\"phases\":${PHASE_COUNT}}" 2>/dev/null || true

echo ""
echo "✓ Milestone ${MILESTONE} closed."
echo "  Next: /vg:project --milestone   # define milestone scope for current_milestone (advanced)"
echo "  Then: /vg:roadmap               # add phases for the new milestone"
```
</step>

</process>

<success_criteria>
- All resolved phases were UAT-accepted before close (gate enforced)
- Critical OPEN security threats were either resolved or explicitly waived (override-debt logged)
- Critical OVERRIDE-DEBT entries were either resolved or explicitly deferred (logged)
- `.vg/milestones/{M}/MILESTONE-SUMMARY.md` regenerated
- `.vg/milestones/{M}/.completed` marker JSON written with vgflow version + timestamp
- `.vg/STATE.md` advanced (`current_milestone` incremented, `milestones_completed[]` appended)
- Phase dirs archived under `.vg/milestones/{M}/phases/{N}/` (unless `--no-archive`)
- Atomic commit created with `milestone(close):` subject prefix
- Telemetry events emitted (started + completed)
</success_criteria>

<dependencies>
- `scripts/complete-milestone.py` — gate + state engine
- `scripts/generate-milestone-summary.py` — summary aggregator
- `commands/vg/security-audit-milestone.md` — security gate (Step 4 already wires `--milestone-gate`)
- `git` (for archive via `git mv` to preserve history)
</dependencies>

<see_also>
- `/vg:security-audit-milestone` — runs decay + composite + Strix advisory
- `/vg:milestone-summary` — standalone summary view (re-runnable)
- `/vg:project --milestone` — append next milestone scope to PROJECT.md
- `/vg:roadmap` — derive phases for the next milestone
</see_also>
