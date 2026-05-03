---
name: "vg-scope"
description: "Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md"
metadata:
  short-description: "Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md"
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

Invoke this skill as `$vg-scope`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<HARD-GATE>
You MUST follow STEP 1 through STEP 7 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 runs emit-tasklist.py.
The PreToolUse Bash hook will block all subsequent step-active calls
until signed evidence (HMAC) exists at `.vg/runs/<run>/tasklist-evidence.json`.

For each of the 5 discussion rounds (inside STEP 2), you MUST invoke:
  (a) per-answer adversarial challenger via the Agent tool
      (subagent_type=general-purpose, model=Opus default), AND
  (b) per-round dimension expander via the Agent tool
      (subagent_type=general-purpose, model=Opus default).
The wrappers `vg-challenge-answer-wrapper.sh` + `vg-expand-round-wrapper.sh`
build the prompts. DO NOT skip rounds, DO NOT skip challenger/expander —
hooks will not catch this, but Codex consensus blocked omission as
adversarial-suppression risk.

Tool name is `Agent`, NOT `Task` (Codex correction #1).
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "User answered clearly, skip challenger this round" | Challenger is per-answer trigger; skipping = miss adversarial check |
| "All 5 rounds done, skip expander on R5" | Expander runs once per round end; missing = miss critical_missing detection |
| "R4 UI seems irrelevant for backend phase" | R4 has profile-aware skip — let the profile branch decide, don't manually skip |
| "Fast mode: write CONTEXT.md after R1 only" | Steps 2-5 build incremental decisions; partial = downstream phases ungrounded |
| "CrossAI review takes time, --skip-crossai" | --skip-crossai requires --override-reason; gate enforces override-debt entry |
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Tôi đã hiểu, không cần đọc reference" | Reference contains step-specific bash commands not in entry |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex correction #1) |
| "Per-decision split overkill" | UX baseline R1 — blueprint already consumes via vg-load.sh; missing = build context overflow |
| "Sẵn ngữ cảnh, sinh luôn API-CONTRACTS / TEST-GOALS / PLAN cho nhanh" | Rule 4: scope = DISCUSSION only. Sinh artifact đó là job của /vg:blueprint — write từ scope = lệch contract, blueprint sẽ overwrite gây mất công |

## Steps (7 checklist groups — wired into native tasklist via emit-tasklist.py CHECKLIST_DEFS["vg:scope"])

### STEP 1 — preflight
Read `_shared/scope/preflight.md` and follow it exactly.
This step parses args, validates SPECS.md exists, runs emit-tasklist.py,
and includes the IMPERATIVE TodoWrite call after evidence is signed.

### STEP 2 — deep discussion (HEAVY, INLINE — interactive UX)
Read `_shared/scope/discussion-overview.md` first (sources wrappers,
loads bug-detection-guide). Then loop through 5 rounds:
- R1: Read `_shared/scope/discussion-round-1-domain.md`
- R2: Read `_shared/scope/discussion-round-2-technical.md` (multi-surface gate)
- R3: Read `_shared/scope/discussion-round-3-api.md`
- R4: Read `_shared/scope/discussion-round-4-ui.md` (profile-aware skip)
- R5: Read `_shared/scope/discussion-round-5-tests.md`
- After R5: Read `_shared/scope/discussion-deep-probe.md` (mandatory min 5 probes)

For EACH user answer in EACH round:
1. Build challenger prompt:
   ```bash
   PROMPT=$(bash commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
            "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft")
   ```
2. Spawn challenger:
   ```bash
   bash scripts/vg-narrate-spawn.sh scope-challenger spawning "round-$ROUND answer #$N"
   ```
   Then `Agent(subagent_type="general-purpose", prompt=<PROMPT>)`.
   On return: `bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"`.

For EACH round end (after all answers + challengers):
1. Build expander prompt via `vg-expand-round-wrapper.sh`.
2. Spawn expander (same Agent + narrate pattern).

DO NOT skip rounds. DO NOT skip challenger or expander.

### STEP 3 — env preference
Read `_shared/scope/env-preference.md` and follow it exactly.
Captures sandbox/staging/prod target for downstream commands.

### STEP 4 — artifact generation
Read `_shared/scope/artifact-write.md` and follow it exactly.
Atomic group commit: writes CONTEXT.md (Layer 3 flat) + CONTEXT/D-NN.md
per decision (Layer 1) + CONTEXT/index.md (Layer 2) + DISCUSSION-LOG.md
(append-only). MUST emit `2_artifact_generation` step marker.

### STEP 5 — completeness validation
Read `_shared/scope/completeness-validation.md` and follow it exactly.
Runs 4 checks (decision count, endpoint coverage, UI components,
test scenarios) and surfaces warnings.

### STEP 6 — CrossAI review (skippable with --skip-crossai + --override-reason)
Read `_shared/scope/crossai.md` and follow it exactly.
Async dispatch via crossai-invoke.sh + bootstrap reflection (4_5) +
TEST-STRATEGY draft (4_6). Skipping requires override-debt entry.

### STEP 7 — close
Read `_shared/scope/close.md` and follow it exactly.
Writes contract pin, runs decisions-trace gate, marks `5_commit_and_next`,
emits `scope.completed`, calls run-complete.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).

## UX baseline (R1a inheritance — mandatory cross-flow)

This flow honors the 3 UX requirements baked into R1a blueprint pilot:
- **Per-decision artifact split** — STEP 4 writes CONTEXT/D-NN.md
  (Layer 1) + CONTEXT/index.md (Layer 2) + CONTEXT.md flat concat
  (Layer 3). Blueprint consumes via `scripts/vg-load.sh --phase N --artifact context --decision D-NN`.
- **Subagent spawn narration** — every Agent() call (challenger, expander,
  reflector, vg-crossai inside crossai.md) wrapped with
  `bash scripts/vg-narrate-spawn.sh <name> {spawning|returned|failed}`.
- **Compact hook stderr** — success silent, block 3 lines + file pointer.
  Full diagnostic in `.vg/blocks/{run_id}/{gate_id}.md`.
