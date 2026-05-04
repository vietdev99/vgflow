---
name: "vg-accept"
description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
metadata:
  short-description: "Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)"
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

Invoke this skill as `$vg-accept`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>




---
name: vg:accept
description: Human UAT acceptance — structured checklist driven by VG artifacts (SPECS, CONTEXT, TEST-GOALS, RIPPLE-ANALYSIS)
argument-hint: "<phase> [--allow-uat-skips] [--allow-empty-uat] [--allow-unreachable] [--override-reason=<text>]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
  - TodoWrite
runtime_contract:
  # OHOK Batch 3 (2026-04-22): full-coverage contract + UAT quorum gate.
  # R4 Accept Pilot (2026-05-03): refactor to slim entry + 10 refs + 2 subagents.
  # Step IDs unchanged — markers + telemetry preserved verbatim.
  must_write:
    # v2.5.1 anti-forge: UAT.md must have Verdict: line — prevents
    # empty/stub UAT without human decision recorded.
    - path: "${PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
      content_min_bytes: 200
      content_required_sections: ["Verdict:"]
    - "${PHASE_DIR}/.uat-responses.json"
  must_touch_markers:
    # Hard gates — foundational + verdict enforcement
    - "0_gate_integrity_precheck"
    - "0_load_config"
    - "create_task_tracker"
    - "0c_telemetry_suggestions"
    - "1_artifact_precheck"
    - "2_marker_precheck"
    - "3_sandbox_verdict_gate"
    - "3b_unreachable_triage_gate"
    - "3c_override_resolution_gate"
    - "4_build_uat_checklist"
    - "4b_uat_narrative_autofire"
    - "5_interactive_uat"
    - "5_uat_quorum_gate"
    - "6b_security_baseline"
    - "6c_learn_auto_surface"
    - "6_write_uat_md"
    # Advisory / post-accept
    - "7_post_accept_actions"
  must_emit_telemetry:
    # v2.5.1 anti-forge: tasklist visibility at flow start
    - event_type: "accept.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    # AUDIT FAIL #9 (R4 fix inherited from R1a blueprint pilot): baseline 0 events.
    # Slim entry's STEP 1 IMPERATIVE TodoWrite + PostToolUse hook auto-projects.
    - event_type: "accept.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "accept.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "accept.completed"
      phase: "${PHASE_NUMBER}"
  # forbidden flags (each MUST be paired with --override-reason="<text>" — the
  # override mechanism itself, NOT listed because it IS what makes the others
  # acceptable). Each accepted bypass MUST also call:
  #   vg-orchestrator override --flag <flag> --reason "<text>"
  # so override.used fires for run-complete contract + OVERRIDE-DEBT.md entry.
  # --allow-uat-skips:    Batch 3 B4 — log when UAT quorum breached
  # --allow-empty-uat:    Batch 3 B4 — log when .uat-responses.json absent
  # --allow-unreachable:  existing (3b gate)
  # --allow-deferred:     belongs to /vg:next (DEFERRED bypass), NOT accept —
  #                        removed from this contract (was undeclared bypass surface).
  forbidden_without_override:
    - "--allow-uat-skips"
    - "--allow-empty-uat"
    - "--allow-unreachable"
---


<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

Ví dụ:
- ❌ "Validator failed with 225 evidence count"
- ✅ "Validator báo 225 trường thiếu — chi tiết ở `[path]`. Mình sẽ sửa rồi chạy lại."

File paths, code identifiers (G-04, Wave 9, getUserById), commit messages,
CLI commands stay English. AskUserQuestion title + options + question prose:
ngôn ngữ config.
</LANGUAGE_POLICY>


<HARD-GATE>
You MUST follow STEP 1 through STEP 8 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 (`create_task_tracker`)
runs `emit-tasklist.py` — DO NOT continue without it. The PreToolUse Bash
hook will block all subsequent step-active calls until signed evidence
exists at `.vg/runs/<run_id>/.tasklist-projected.evidence.json`. The
PostToolUse TodoWrite hook auto-writes that signed evidence. This fixes
audit FAIL #9 (`accept.native_tasklist_projected` baseline 0 events).

For HEAVY steps (STEP 3 UAT checklist build, STEP 8 cleanup), you MUST
spawn the named subagent via the `Agent` tool (NOT `Task` — Codex
confirmed correct tool name per Claude Code docs). DO NOT build the
checklist or run cleanup inline.

STEP 5 (interactive UAT) MUST execute INLINE in the main agent — DO NOT
spawn a subagent for it. AskUserQuestion is a UI-presentation tool;
subagent context handoff breaks UX continuity. `.uat-responses.json`
MUST be written after EACH of the 6 sections (anti-theatre, OHOK Batch 3
B4). Quorum gate (STEP 6) blocks if the file is missing or any required
section is empty. Override-resolution gate (STEP 2) blocks unresolved
blocking-severity entries from the override-debt register.
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "User trust me, skip interactive UAT" | Quorum gate blocks if `.uat-responses.json` missing/empty (Batch 3 B4) |
| "Override-debt is just warning, accept anyway" | Gate 3c hard-blocks unresolved critical-severity entries |
| "Greenfield design overrides are nominal" | Form B block treats `no-asset:greenfield-*` as critical |
| "UAT-NARRATIVE.md skip, ask user directly" | Narrative autofire deterministic; skip = miss anti-theatre check |
| "Cleanup defer to next phase" | `7_post_accept_actions` has bootstrap hygiene; skip = drift to next phase |
| "Final verdict = accept by default" | Quorum gate verifies actual responses; default-accept = theatre |
| "Subagent overkill for STEP 3 / STEP 8" | Heavy step empirical 96.5% skip rate without subagent (Codex review confirmed) |
| "Step 5 cũng nên là subagent cho gọn" | UX requirement (spec §1.2): AskUserQuestion needs main-agent presence |
| "Spawn `Task()` như cũ" | Tool name is `Agent`, not `Task` (Codex fix #3) |
| "TodoWrite gọi sau cũng được" | Layer 2 diagnostic: PreToolUse blocks subsequent tool calls |
| "Block message bỏ qua, retry là xong" | §4.5 Layer 2: `vg.block.fired` must pair with `vg.block.handled` or Stop blocks |

## Tasklist policy (summary)

`emit-tasklist.py` writes the profile-filtered
`.vg/runs/<run_id>/tasklist-contract.json` (schema `native-tasklist.v2`).
The slim entry STEP 1 calls it; this skill IMPERATIVELY calls TodoWrite
right after with one todo per `projection_items[]` entry (5 group headers
+ sub-steps with `↳` prefix). Then calls
`vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>` so
`accept.native_tasklist_projected` event fires.

Lifecycle: `replace-on-start` (first projection replaces stale list) +
`close-on-complete` (final clear or completed sentinel).

## Steps (5 checklist groups → 8 STEP sections)

### STEP 1 — preflight (4 light steps)

Read `_shared/accept/preflight.md` and follow it exactly.

This step covers:
- `0_gate_integrity_precheck` — T8 gate (xung đột) precheck
- `0_load_config` — config-loader + phase resolution
- `create_task_tracker` — IMPERATIVE TodoWrite + tasklist projection
- `0c_telemetry_suggestions` — pull weekly telemetry summary

After STEP 1.create_task_tracker bash runs, you MUST call TodoWrite
IMMEDIATELY with the projection items from
`.vg/runs/<run_id>/tasklist-contract.json`.

### STEP 2 — gates (3-tier preflight gates)

Read `_shared/accept/gates.md` and follow it exactly.

This step covers:
- `1_artifact_precheck` — pipeline artifacts present
- `2_marker_precheck` — every profile-applicable step has `.done`
- `3_sandbox_verdict_gate` — SANDBOX-TEST.md verdict ∈ {PASSED, GAPS_FOUND}
- `3b_unreachable_triage_gate` — UNREACHABLE goals classified
- `3c_override_resolution_gate` — override-debt register clean

Each gate is fail-fast. Override only with `--override-reason="<text>"`
(logs to override-debt register).

### STEP 3 — UAT checklist build (HEAVY, subagent)

Read `_shared/accept/uat/checklist-build/overview.md` AND
`_shared/accept/uat/checklist-build/delegation.md`.

Wrap the spawn with narration (overview.md spells out the same lifecycle).
Pre-spawn:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder spawning "phase ${PHASE_NUMBER} UAT checklist"
```

Then call:
```
Agent(subagent_type="vg-accept-uat-builder", prompt=<built from delegation>)
```

Post-return (success):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder returned "<count> items across 6 sections"
```

DO NOT build the checklist inline. The subagent uses `vg-load --list` for
goals (Section B) + design-refs (Section D); other artifacts are KEEP-FLAT
(small single-doc files: CONTEXT.md, FOUNDATION.md, CRUD-SURFACES.md,
RIPPLE-ANALYSIS.md, SUMMARY*.md, build-state.log).

After return, validate output JSON contract + present section counts to
user (proceed/abort prompt).

### STEP 4 — UAT narrative autofire

Read `_shared/accept/uat/narrative.md` and follow it exactly.

This step covers `4b_uat_narrative_autofire` — deterministic
(Sonnet-free) generation of `${PHASE_DIR}/UAT-NARRATIVE.md` from
TEST-GOALS frontmatter (`entry_url`, `navigation_steps`, `precondition`,
`expected_behavior`) + design-ref blocks. Strings come ONLY from
`narration-strings.yaml` (D-18 strict enforcement).

### STEP 5 — interactive UAT (INLINE, NOT subagent)

Read `_shared/accept/uat/interactive.md` and follow it exactly.

<HARD-GATE>
This step MUST execute INLINE in the main agent. DO NOT spawn a subagent.
AskUserQuestion is a UI-presentation tool; subagent context handoff
breaks UX continuity (spec §1.2). Write `.uat-responses.json` after EACH
of the 6 sections (anti-theatre, OHOK Batch 3 B4).
</HARD-GATE>

This step covers `5_interactive_uat` — 50+ AskUserQuestion items across
6 sections (Decisions, Goals, Ripple HIGH callers, Design refs,
Deliverables, Mobile gates). User decisions persisted per-section.

### STEP 6 — UAT quorum gate

Read `_shared/accept/uat/quorum.md` and follow it exactly.

This step covers `5_uat_quorum_gate` — quorum math + rationalization
guard. Counts SKIPs on critical items (Section A decisions, Section B
READY goals); blocks unless `--allow-uat-skips` AND rationalization-guard
passes.

### STEP 7 — audit (security + learn + UAT.md write)

Read `_shared/accept/audit.md` and follow it exactly.

This step covers 3 sub-steps:
- `6b_security_baseline` — `verify-security-baseline.py` subprocess
- `6c_learn_auto_surface` — `/vg:learn --auto-surface` y/n/e/s gate
- `6_write_uat_md` — write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with
  Verdict line. content_min_bytes=200 + content_required_sections enforced
  by must_write contract (anti-forge).

Use `vg-load --priority` (NOT flat TEST-GOALS.md) when enumerating goals
for UAT.md (Phase F Task 30 absorption).

### STEP 8 — cleanup (HEAVY, subagent + post-spawn gates)

Read `_shared/accept/cleanup/overview.md` AND
`_shared/accept/cleanup/delegation.md`.

Wrap the spawn with narration (overview.md spells out the same lifecycle).
Pre-spawn:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup spawning "post-accept ${PHASE_NUMBER}"
```

Then call:
```
Agent(subagent_type="vg-accept-cleanup", prompt=<built from delegation>)
```

Post-return (success):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-cleanup returned "<count> actions"
```

DO NOT cleanup inline. The subagent runs 8 subroutines (scan-cleanup,
screenshot cleanup, worktree prune, bootstrap outcome attribution,
PIPELINE-STATE update, ROADMAP flip, CROSS-PHASE-DEPS flip,
DEPLOY-RUNBOOK lifecycle). It branches on `UAT_VERDICT` — short-circuits
for non-ACCEPTED verdicts.

After return, the MAIN AGENT runs 3 hard-exit gates (in `overview.md`):
- Gate A: traceability chain (`verify-acceptance-traceability.py`)
- Gate B: profile marker contract (filter-steps + .step-markers check)
- Gate C: marker write + emit `accept.completed` + `run-complete`

The Stop hook then verifies all 17 markers, must_write paths, and
must_emit_telemetry events.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message
   (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3
escalation). After context compaction, SessionStart hook re-injects open
diagnostics (Layer 4).

## Architectural rationale (R4 pilot)

This slim entry replaces a 2,429-line monolithic accept.md. The 17 step
markers + must_emit_telemetry events are unchanged — only the on-disk
layout changed. Heavy steps (4: 291 lines, 7: 306 lines) are extracted
to subagents to fight the empirical 96.5% inline-skip rate. Light steps
move to flat refs in `_shared/accept/`. Interactive UAT (213 lines) stays
INLINE — UX requirement (spec §1.2). Companion artifacts:

- Spec: `docs/superpowers/specs/2026-05-03-vg-accept-design.md`
- Plan: `docs/superpowers/plans/2026-05-03-vg-r4-accept-pilot.md`
- Backup: `commands/vg/.accept.md.r4-backup` (full pre-refactor)
- Tests: `scripts/tests/test_accept_*.py` (5 static tests)
