---
name: "vg-prioritize"
description: "Analyze ROADMAP.md + phase artifacts — rank phases by impact, readiness, and recommend next action"
metadata:
  short-description: "Analyze ROADMAP.md + phase artifacts — rank phases by impact, readiness, and recommend next action"
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

Invoke this skill as `$vg-prioritize`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths.
3. **Read-only** — this command does NOT modify any files. Pure analysis and display.
4. **Artifact-based classification** — phase status derived from actual file presence, not metadata.
5. **Score transparency** — every score component shown so user understands the ranking.
6. **Legacy detection** — identify phases built outside VG pipeline (missing VG artifacts despite having code).
</rules>

<objective>
Analyze ROADMAP.md and scan all phase directories to classify each phase by status, score by impact, and recommend the highest-value next action. Read-only command — outputs a ranked priority table.

Output: terminal display only (no files written)

Pipeline: project → roadmap → map → **prioritize** → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
## Step 0: Load Config

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

```bash
ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
```

**Validate:**
- If `${ROADMAP_FILE}` does not exist:
  → "ROADMAP.md not found. Run `/vg:roadmap` to derive phases from requirements."
  → STOP.
</step>

<step name="1_parse_roadmap">
## Step 1: Parse ROADMAP.md

Extract all phases:

```
For each "## Phase {NN}: {Name}" section:
  phase_number = NN
  phase_name = Name
  goal = text after "**Goal:**"
  requirements = REQ-IDs after "**Requirements:**"
  depends_on = phase numbers after "**Depends on:**" (or empty if "None")
  success_criteria = list after "**Success criteria:**"
  plans_count = parse "**Plans:** X/Y" → (completed, total)
  status_declared = text after "**Status:**" (planned, in-progress, accepted, etc.)
```

Build:
- `phases[]` — array of all phase objects
- `dependency_graph{}` — { phase_number: [depends_on_numbers] }
- `downstream_map{}` — { phase_number: [phases that depend on this one] }
</step>

<step name="2_scan_artifacts">
## Step 2: Scan Phase Directories for Artifacts

For each phase, determine its directory and check artifact presence:

```bash
# For each phase directory in ${PHASES_DIR}/
for phase_dir in ${PHASES_DIR}/*/; do
  phase_num = extract from dir name
  
  # VG pipeline artifacts
  HAS_SPECS=$(test -f "${phase_dir}/SPECS.md" && echo "true" || echo "false")
  HAS_CONTEXT=$(test -f "${phase_dir}/CONTEXT.md" && echo "true" || echo "false")
  HAS_PLAN=$(ls ${phase_dir}/*PLAN*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_API_CONTRACTS=$(test -f "${phase_dir}/API-CONTRACTS.md" && echo "true" || echo "false")
  HAS_TEST_GOALS=$(test -f "${phase_dir}/TEST-GOALS.md" && echo "true" || echo "false")
  HAS_SUMMARY=$(ls ${phase_dir}/*SUMMARY*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_RUNTIME_MAP=$(test -f "${phase_dir}/RUNTIME-MAP.json" && echo "true" || echo "false")
  HAS_GOAL_MATRIX=$(test -f "${phase_dir}/GOAL-COVERAGE-MATRIX.md" && echo "true" || echo "false")
  HAS_SANDBOX_TEST=$(ls ${phase_dir}/*SANDBOX-TEST*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_UAT=$(ls ${phase_dir}/*UAT*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  
  # Pipeline state (if exists)
  HAS_PIPELINE_STATE=$(test -f "${phase_dir}/PIPELINE-STATE.json" && echo "true" || echo "false")
done
```

**Also check for GOAL-COVERAGE-MATRIX gate status (if file exists):**

```bash
if [ "$HAS_GOAL_MATRIX" = "true" ]; then
  # Read gate status from GOAL-COVERAGE-MATRIX.md
  # Look for "Gate: PASS" or "Gate: BLOCK" or percentage
  GOAL_GATE=$(grep -i "gate:" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" | head -1)
  # Count READY vs total goals
  GOALS_READY=$(grep -c "READY" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo "0")
  GOALS_TOTAL=$(grep -cE "^\|.*\|.*(READY|BLOCKED|FAILED|UNREACHABLE|NOT_SCANNED)" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo "0")
fi
```

**Check for UAT verdict (if file exists):**

```bash
if [ "$HAS_UAT" = "true" ]; then
  UAT_VERDICT=$(grep -i "verdict:" ${phase_dir}/*UAT*.md | head -1)
  # ACCEPTED, REJECTED, PARTIAL
fi
```
</step>

<step name="3_classify_phases">
## Step 3: Classify Each Phase

Apply classification rules IN THIS ORDER (first match wins):

```
DONE:
  - HAS_UAT=true AND UAT_VERDICT contains "ACCEPTED"
  - OR status_declared == "accepted"

NEEDS_FIX:
  - HAS_GOAL_MATRIX=true AND gate != PASS (goals < 100% READY)
  - OR HAS_SANDBOX_TEST=true AND verdict contains "FAILED" or "GAPS"
  - OR HAS_RUNTIME_MAP=true AND GOALS_READY < GOALS_TOTAL

READY:
  - All dependency phases are DONE
  - AND HAS_CONTEXT=true (scope is done)
  - AND NOT HAS_PLAN (blueprint not started yet — ready to plan)

IN_PROGRESS:
  - Has some VG artifacts but not complete
  - Not blocked by dependencies
  - (Catch-all for phases mid-pipeline)

BLOCKED:
  - At least one dependency phase is NOT DONE
  - AND phase itself is not DONE

STALE:
  - HAS_SUMMARY=true (was built)
  - BUT missing VG-specific artifacts: no RUNTIME-MAP.json AND no GOAL-COVERAGE-MATRIX.md
  - (Built outside VG pipeline — legacy GSD build)

PLANNED:
  - In ROADMAP but no artifacts at all (or only SPECS.md)
  - Dependencies may or may not be met
```

Store: `phase.classification` for each phase.
</step>

<step name="4_score_phases">
## Step 4: Score Each Phase

For phases that are NOT DONE, compute a priority score:

```
score = 0

# Unblocks others: +3 per downstream phase
score += len(downstream_map[phase_number]) * 3

# NEEDS_FIX: +2 (quick win — partially done, fix and close)
if classification == NEEDS_FIX:
  score += 2

# IN_PROGRESS: +1 (momentum — continue what's started)
if classification == IN_PROGRESS:
  score += 1

# READY with full scope: +1 (low friction to start)
if classification == READY:
  score += 1

# Has critical requirements: +2 if any REQ is must-have
if any(req.priority == "must-have" for req in phase.requirements):
  score += 2

# STALE: -1 (needs migration overhead)
if classification == STALE:
  score -= 1

# BLOCKED: -5 (can't start anyway)
if classification == BLOCKED:
  score -= 5
```

**Score breakdown stored per phase** for transparency in output.
</step>

<step name="5_sort_and_display">
## Step 5: Sort and Display Ranked Table

Sort phases by score descending. Display:

```
Phase Priority — {PROJECT_NAME}
Generated: {ISO date}

#1  Phase {NN}: {Name} ({CLASSIFICATION})
    Score: {score} = {breakdown}
    Goal: {goal}
    {status detail}
    Action: {recommended VG command}

#2  Phase {NN}: {Name} ({CLASSIFICATION})
    Score: {score} = {breakdown}
    Goal: {goal}
    {status detail}
    Action: {recommended VG command}

...

--- Completed Phases ---
  Phase {NN}: {Name} (DONE) — accepted {date if available}
  ...

Legend: DONE | NEEDS_FIX | IN_PROGRESS | READY | BLOCKED | STALE | PLANNED
```

**Status detail per classification:**

| Classification | Status detail | Recommended action |
|---|---|---|
| NEEDS_FIX | "{X}/{Y} goals ready, gate BLOCK" or "sandbox test failed" | `/vg:review {phase} --retry-failed` or `/vg:test {phase}` |
| IN_PROGRESS | "Currently at: {current pipeline step}" | `/vg:next` or `/vg:{current_step} {phase}` |
| READY | "All deps done, scope complete, ready to plan" | `/vg:blueprint {phase}` |
| BLOCKED | "Blocked by: Phase {deps not done}" | (show which deps to finish first) |
| STALE | "Built via legacy pipeline, missing VG artifacts" | `/vg:review {phase}` (to generate RUNTIME-MAP + goals) |
| PLANNED | "No artifacts yet" | `/vg:specs {phase}` |

**Recommended action mapping (MANDATORY — always use /vg:* commands):**

| Phase state | Command |
|---|---|
| No SPECS.md | `/vg:specs {phase}` |
| SPECS but no CONTEXT | `/vg:scope {phase}` |
| CONTEXT but no PLAN | `/vg:blueprint {phase}` |
| PLAN but no SUMMARY | `/vg:build {phase}` |
| SUMMARY but no RUNTIME-MAP | `/vg:review {phase}` |
| RUNTIME-MAP but goals failing | `/vg:review {phase} --retry-failed` |
| Goals passing but no SANDBOX-TEST | `/vg:test {phase}` |
| SANDBOX-TEST but no UAT | `/vg:accept {phase}` |
| UAT accepted | (DONE — no action) |

**Forbidden suggestions:**
- NEVER suggest `/gsd-*` or `/gsd:*` commands
- NEVER suggest manually editing artifacts
</step>

<step name="6_legacy_detection">
## Step 6: Legacy Phase Detection

If any phases classified as STALE:

```
--- Legacy Phases Needing VG Migration ---

These phases were built outside the VG pipeline (e.g., legacy GSD).
They have build artifacts (SUMMARY) but are missing VG review/test artifacts.

  Phase {NN}: {Name}
    Has: CONTEXT, PLAN, SUMMARY
    Missing: RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md
    Migration: /vg:review {phase} → /vg:test {phase} → /vg:accept {phase}

  Phase {NN}: {Name}
    Has: SUMMARY
    Missing: SPECS, CONTEXT (scope never done in VG)
    Migration: /vg:specs {phase} → /vg:scope {phase} → /vg:review {phase}
```

This helps the user understand which phases need VG pipeline retrofit vs which are truly new.
</step>

<step name="7_summary">
## Step 7: Summary

```
Summary:
  Total phases: {N}
  DONE: {count}
  NEEDS_FIX: {count} (quick wins)
  IN_PROGRESS: {count}
  READY: {count}
  BLOCKED: {count}
  STALE: {count} (legacy migration needed)
  PLANNED: {count}

Top recommendation: /vg:{command} {phase} — {reason}
```
</step>

</process>

<success_criteria>
- All phases from ROADMAP.md scanned and classified
- Artifact detection accurate (file existence checked, not assumed)
- Dependency graph correctly identifies BLOCKED phases
- Scoring transparent — breakdown shown per phase
- Ranked output with actionable /vg:* command per phase
- Legacy/STALE phases identified with migration path
- No files written (read-only command)
- No /gsd:* commands suggested
</success_criteria>
</output>
