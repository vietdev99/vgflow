---
name: "vg-roam"
description: "Exploratory CRUD-lifecycle pass with state-coherence assertion (post-review/test janitor). Lens-driven, post-confirmation. Catches silent state-mismatches that /vg:review and /vg:test miss. Generates new .spec.ts proposals from findings."
metadata:
  short-description: "Exploratory CRUD-lifecycle pass with state-coherence assertion (post-review/test janitor). Lens-driven, post-confirmation. Catches silent state-mismatches that /vg:review and /vg:test miss. Generates new .spec.ts proposals from findings."
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



<HARD-GATE>
Roam is post-confirmation (runs AFTER /vg:review + /vg:test PASS).
You MUST verify both passes BEFORE any roam step.

Lens auto-pick by phase profile + entity types — DO NOT manually override
unless --lens flag explicit. Spec.ts proposals stage to proposed-specs/ —
DO NOT auto-merge (requires --merge-specs).

TodoWrite IMPERATIVE after `emit-tasklist.py` projects the 8-group checklist
for vg:roam. Skipping TodoWrite emission causes Stop hook to fail because
`roam.native_tasklist_projected` event will not fire.
</HARD-GATE>

## Red Flags (you have used these before — they will not work)

| Thought | Reality |
|---|---|
| "I can skip 0a sub-steps and write the marker directly" | Each of the 5 decomposed sub-steps emits its own `mark_step` — Stop hook checks all 5 markers (audit FAIL #10 fix). Single-marker skip is a HARD GATE BREACH. |
| "Resume mode means I don't need to ask env/model/mode" | v2.42.10 footgun fix: step 0a fires its 3-question batch ALWAYS. Prior values become Recommended pre-fills, but the user must confirm. |
| "Lens prompts are all the same — I can run one lens for everything" | Per-surface composition is Cartesian (surface × lens × per-model dir). Wrong lens for a surface produces low-signal observations and pollutes RAW-LOG.jsonl. |
| "I'll just cat PLAN.md to find surfaces" | PLAN.md is 8K+ lines on large phases. Use `vg-load --phase N --artifact plan --index` instead — discovery ref enforces this and the static test rejects flat reads. |
| "Auto-merge proposed specs to save a step" | Manual gate is intentional (Q10). Auto-merging untriaged specs floods the test suite with flaky tests. Always require explicit `--merge-specs`. |

## Special invocation — `--merge-specs`

Short-circuit before the main pipeline. Validates `proposed-specs/*.spec.ts`
via `vg-codegen-interactive` validator, merges into project test suite path
(per `paths.tests` in vg.config.md). Manual gate.

```bash
if [[ "$ARGUMENTS" =~ --merge-specs ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-merge-specs.py \
    --phase-dir "${PHASE_DIR}" \
    --proposed-dir "${PHASE_DIR}/roam/proposed-specs" \
    --target-dir "$(grep -oP 'tests:\s*\K\S+' .claude/vg.config.md)"
  exit 0
fi
```

If `--merge-specs` is set, exit before reading any pipeline ref below.

## Tasklist projection

Before any pipeline step runs, project the native task checklist via
`emit-tasklist.py`. The 8-group checklist (see Task 12 of plan +
`scripts/emit-tasklist.py` `CHECKLIST_DEFS["vg:roam"]`) drives the TodoWrite
imperative. AI MUST issue `TodoWrite` with the projected items as soon as
`emit-tasklist.py` returns — this fires `roam.native_tasklist_projected`
which the runtime contract requires.

```bash
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command vg:roam \
  --phase "${PHASE_NUMBER}"
# AI: now invoke TodoWrite with the items printed above.
```

## Steps

Read each ref in order. Each ref contains its own `<step>` block with
`mark_step` calls and (where applicable) a `vg-orchestrator emit-event`
invocation. Do NOT inline content from refs into this entry — the slim
entry only sequences and gates.

### STEP 1 — preflight (parse + resume check)

Read `_shared/roam/preflight.md`.

Two markers: `0_parse_and_validate`, `0aa_resume_check`. Emits
`roam.session.started` (always) and `roam.resume_mode_chosen`
(unless `--non-interactive`).

### STEP 2 — config gate (decomposed: overview + 5 sub-steps)

Read `_shared/roam/config-gate/overview.md` first. Then sequence through
the 5 sub-step refs in order:

1. `_shared/roam/config-gate/backfill-env.md` (`0a_backfill_env_pref`)
2. `_shared/roam/config-gate/detect-platform.md` (`0a_detect_platform_tools`)
3. `_shared/roam/config-gate/enrich-env.md` (`0a_enrich_env_options`)
4. `_shared/roam/config-gate/confirm-env-model-mode.md` (`0a_confirm_env_model_mode`)
5. `_shared/roam/config-gate/persist-config.md` (`0a_persist_config`)

Each sub-step writes its own `mark_step`. Sub-step 5 emits
`roam.config_confirmed` and writes `.tmp/0a-confirmed.marker` (HARD GATE
token consumed by step 1 entry in `discovery.md`).

**Why decomposed:** original `0a_env_model_mode_gate` was 355 lines with
9 inline AskUserQuestion sub-prompts. Single marker for 9 prompts meant
silent-skip of any sub-prompt was undetectable. Decomposed: one marker
per sub-prompt, each ref ≤150 lines.

### STEP 3 — discovery + briefs

Read `_shared/roam/discovery.md`.

Two markers: `1_discover_surfaces`, `2_compose_briefs`. Discovery uses
`vg-load --index` for PLAN.md (closes Phase F Task 30 for vg:roam — single
L600 flat read replaced by index call).

CONTEXT.md and RUNTIME-MAP.md remain KEEP-FLAT (small docs / already
filtered JSON).

### STEP 4 — spawn executors (3 dispatch branches)

Read `_shared/roam/spawn-executors.md`.

Marker: `3_spawn_executors`. Branches by `$ROAM_MODE`:

- `self` → current Claude session executes via MCP Playwright
- `spawn` → subprocess CLI (codex / gemini), parallel cap 5
- `manual` → generate `PASTE-PROMPT.md`, user pastes elsewhere, drops JSONL back

Cost estimator + soft cap warning before spawn (default $10/session via
`VG_MAX_COST_USD`, override with `--max-cost-usd=N`).

### STEP 5 — aggregate + analyze

Read `_shared/roam/aggregate-analyze.md`.

Two markers: `4_aggregate_logs`, `5_analyze_findings`. Step 4 runs
evidence completeness validator (`verify-scanner-evidence-completeness.py`)
+ vocabulary validator (`grep` for banned tokens — tags
`vocabulary_violation: true`). Step 5 runs deterministic R1-R8 Python
rules in `roam-analyze.py` and emits `roam.analysis.completed`.

### STEP 6 — artifacts (PIPELINE-STATE update + spec.ts staging)

Read `_shared/roam/artifacts.md`.

Marker: `6_emit_artifacts`. Updates PIPELINE-STATE.json with verdict
(PASS or BLOCK_ACCEPT). Spec.ts proposals staged to `proposed-specs/` —
NOT auto-merged.

### STEP 7 — optional fix loop (gated by `--auto-fix`)

Read `_shared/roam/fix-loop.md`.

Marker: `7_optional_fix_loop` (severity `warn`,
`required_unless_flag: "--auto-fix"` in runtime_contract). Default path:
report only. With `--auto-fix`: spawn existing auto-fix subagent on top-N
bugs (max 5 per session). NO new subagent introduced in R3.5 — auto-fix
loop is preserved as-is.

### STEP 8 — close

Read `_shared/roam/close.md`.

Marker: `complete`. Emits `roam.session.completed` + final summary banner.

## Conformance contract for executors

Per `<rules>` 2: every brief MUST inject `vg:_shared:scanner-report-contract`
(banned vocab + report schema). Briefs without the contract block are
REJECTED at compose time by `roam-compose-brief.py`. Executors emit
**observations only, never verdicts** — the commander (Opus) is the sole
judge during step 5 analysis.

## Cost guards

- Hard cap: 50 surfaces × 1 CLI default (`--max-surfaces=N` to override)
- Soft cap: $10/session (`VG_MAX_COST_USD` env or `--max-cost-usd=N`)
- Pre-spawn estimator (in `spawn-executors.md`) warns + asks confirm if
  soft cap exceeded.
- Council mode default OFF (Q8); enable via `--council` for ship-critical
  phases (2× cost, 2 perspectives).
- Security lens skipped by default (Q13); enable via `--include-security`
  for double-coverage.

## Resume modes (recap)

| Mode | Trigger | Behavior |
|---|---|---|
| `fresh` | first run, no prior state | normal flow, all steps |
| `force` | `--force` or interactive choice | wipe `ROAM_DIR/*` then proceed fresh |
| `resume` | `--resume` or interactive choice | reuse config; per-step skip if artifact exists |
| `aggregate-only` | `--aggregate-only` or interactive choice | skip steps 1-3, run 4-6 only |

Detection logic in `preflight.md` (step 0aa). Step 0a (config gate)
ALWAYS fires regardless of mode (v2.42.10 footgun fix — prior values
become Recommended pre-fills, user must confirm).
