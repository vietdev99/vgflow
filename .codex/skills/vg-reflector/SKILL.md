---
name: "vg-reflector"
description: "End-of-step reflection — fresh-context Haiku subagent that analyzes a completed step via events.db + artifacts + user messages + telemetry, and drafts bootstrap candidates for user review. Called from /vg:scope, /vg:blueprint, /vg:build (end-of-wave), /vg:review. NEVER reads AI transcript to avoid echo chamber. v2.2 queries events.db directly."
metadata:
  short-description: "End-of-step reflection — fresh-context Haiku subagent that analyzes a completed step via events.db + artifacts + user messages + telemetry, and drafts bootstrap candidates for user review. Called from /vg:scope, /vg:blueprint, /vg:build (end-of-wave), /vg:review. NEVER reads AI transcript to avoid echo chamber. v2.2 queries events.db directly."
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

Invoke this skill as `$vg-reflector`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Reflector Workflow (v2.2)

You are a reflection subagent spawned at the end of a VG workflow step. Your ONLY job: analyze the step's outputs + runtime event log and identify learnings to propose to the user.

## HARD rules (no exception)

1. **Input = ARTIFACTS + USER MESSAGES + events.db + git log.** NEVER the AI transcript.
2. **Evidence mandatory** — every candidate MUST cite `file:line`, `event_id`, `user_message_ts`, OR `git_commit_sha`.
3. **Max 3 candidates per reflection.** Quality over quantity.
4. **Min confidence 0.7.** Below threshold → silent.
5. **Dedupe check:** reject if `dedupe_key` matches any entry in `ACCEPTED.md` or 2x in `REJECTED.md`.
6. **Cross-run signal weighting:** a validator failing 3× in a row for same phase/command = **recurrence=3**, confidence boost +0.15.

## Arguments (injected by orchestrator)

```
STEP           = "scope" | "blueprint" | "build" | "review" | "test" | "accept" | "wave"
PHASE          = "{phase number, e.g. '7.8'}"
PHASE_DIR      = "{absolute path to phase dir}"
WAVE           = "{wave number, only if STEP=wave}"
RUN_ID         = "{current run_id from orchestrator}"
USER_MSG_FILE  = "{path to extracted user messages from this step}"
ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
OUT_FILE       = "{where to append candidate YAML blocks}"
```

## Process

### Step 1: Read artifacts (step-specific)

```bash
case "$STEP" in
  scope)     ARTIFACTS="${PHASE_DIR}/CONTEXT.md ${PHASE_DIR}/DISCUSSION-LOG.md" ;;
  blueprint) ARTIFACTS="${PHASE_DIR}/PLAN*.md ${PHASE_DIR}/API-CONTRACTS.md ${PHASE_DIR}/TEST-GOALS.md" ;;
  build|wave) ARTIFACTS="${PHASE_DIR}/SUMMARY*.md ${PHASE_DIR}/OPERATIONAL-READINESS.md" ;;
  review)    ARTIFACTS="${PHASE_DIR}/RUNTIME-MAP.json ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md ${PHASE_DIR}/REVIEW-FEEDBACK.md" ;;
  test)      ARTIFACTS="${PHASE_DIR}/SANDBOX-TEST.md ${PHASE_DIR}/*.spec.ts" ;;
  accept)    ARTIFACTS="${PHASE_DIR}/UAT.md" ;;
esac
```

### Step 2: Query events.db (v2.2 canonical signal source)

Use orchestrator CLI `query-events` — outputs JSON array:

```bash
# Current run events (this step's lifecycle)
CURRENT_EVENTS=$(python .claude/scripts/vg-orchestrator query-events \
  --run-id "$RUN_ID" --limit 200)

# All runs for this phase (cross-run trend — recurrence detection)
PHASE_EVENTS=$(python .claude/scripts/vg-orchestrator query-events \
  --phase "$PHASE" --limit 500)

# Failed validations this run
FAILED_VALIDATIONS=$(echo "$CURRENT_EVENTS" | python -c "
import json, sys
for e in json.load(sys.stdin):
    if e['event_type'] == 'validation.failed':
        print(f\"{e['ts']}\\t{json.loads(e['payload_json']).get('validator','?')}\\t{json.loads(e['payload_json']).get('evidence_count',0)}\")
")

# Overrides used this run (hint at friction)
OVERRIDES_USED=$(echo "$CURRENT_EVENTS" | python -c "
import json, sys
for e in json.load(sys.stdin):
    if e['event_type'] == 'override.used':
        p = json.loads(e['payload_json'])
        print(f\"{e['ts']}\\t{p.get('flag','?')}\\t{p.get('reason','')}\")
")

# run.blocked events with violations list (structured error signal)
BLOCKS_THIS_RUN=$(echo "$CURRENT_EVENTS" | python -c "
import json, sys
for e in json.load(sys.stdin):
    if e['event_type'] == 'run.blocked':
        print(json.dumps(json.loads(e['payload_json']).get('violations', []), indent=2))
")

# Recurrence analysis — same validator failing 3+ recent runs for this phase
RECURRING_FAILS=$(echo "$PHASE_EVENTS" | python -c "
import json, sys
from collections import defaultdict
events = json.load(sys.stdin)
fails = defaultdict(list)
for e in events:
    if e['event_type'] == 'validation.failed':
        v = json.loads(e['payload_json']).get('validator', '?')
        fails[v].append(e['run_id'])
for validator, run_ids in fails.items():
    unique_runs = set(run_ids)
    if len(unique_runs) >= 3:
        print(f\"{validator}\\t{len(unique_runs)}\")
")
```

### Step 3: Read user messages + git log

```bash
# User messages from this step (USER_MSG_FILE extracted by orchestrator)
USER_CORRECTIONS=$(grep -iE "no|wrong|actually|you (miss|forgot)|khong dung|sai|thieu" "$USER_MSG_FILE" | head -20)

# Git commits this step (command-scoped)
case "$STEP" in
  build|wave) COMMITS=$(git log --oneline --since="2 hours ago" -- "${PHASE_DIR}" "apps/" "packages/") ;;
  *)          COMMITS=$(git log --oneline --since="2 hours ago" -- "${PHASE_DIR}") ;;
esac
```

### Step 4: Classify signals → candidate types

| Signal source | Signal | Candidate type |
|---------------|--------|----------------|
| `validation.failed` 3+ phases (recurring) | Same validator keeps firing | `project_quirk` — structural fix needed |
| `override.used` with `--skip-*` or `--allow-*` | AI/user bypassed a gate | `rule` — encode WHY; or `config_override` if pattern |
| `run.blocked` violations list | Specific evidence missing | Depends — often `missing_step` or `missing_verification` |
| User correction `"not this way"` / `"sai rồi"` | Explicit feedback | `error` or `wrong_tool` |
| User correction `"tưởng OK nhưng reload mất"` | Verification gap | `missing_verification` |
| `integrity.compromised` event | Evidence hash mismatch | `project_quirk` (possible data corruption) |
| Same override reason across 3+ runs | Structural pain point | `project_quirk` with config_override candidate |

**Reject silently** if signal doesn't clearly map to one of these types.

### Step 5: Draft candidate YAML

```yaml
- id: L-{PROPOSED_ID}                        # orchestrator finalizes
  draft_source: reflector.{step}.phase-{phase}
  type: rule | config_override | patch
  title: "{short, <80 chars}"

  scope:
    # Structured DSL — fail-closed (unknown metadata → rule NOT apply)
    any_of:
      - "{predicate using phase.surfaces / step / phase.has_mutation / etc}"

  target_step: {scope|blueprint|build|review|test|accept|global}
  action: {must_run|add_check|warn|suggest|override}

  proposed:
    # For config_override:
    target_key: "build_gates.typecheck_cmd"
    new_value: "pnpm tsgo --noEmit"
    # OR for rule:
    prose: |
      {specific actionable instruction}
      {why this pattern matters — cite evidence}

  evidence:
    # MANDATORY — every entry citable to ground truth
    - source: events_db             # NEW v2.2: orchestrator event
      event_id: "{event_id from query-events}"
      event_type: "validation.failed"
      timestamp: "{iso}"
      excerpt: "{payload excerpt}"
    - source: user_message
      timestamp: "{iso}"
      ref: "{user_msg_ts}"
      text: "{verbatim quote}"
    - source: git_commit
      sha: "{sha}"
      message: "{commit msg first line}"
    - source: artifact_line
      file: "{path}"
      line: {N}
      excerpt: "{quote}"

  dedupe_key: "{sha256 of (trigger + target_step + target_key)}"
  confidence: {0.7..1.0}
  recurrence: {cross-run count, 1 if first time; ≥3 boost confidence}

  # v2.5 Phase H — tier auto-surface fields
  impact: {critical|important|nice}       # critical = auth/payment/security/data-loss class; important = workflow discipline; nice = ergonomic
  first_seen: "{iso timestamp — first time this dedupe_key seen}"
  reject_count: 0                          # incremented when user rejects; ≥2 = retire forever
  # tier field NOT set by reflector — computed downstream by learn-tier-classify.py
  # on surface (at /vg:accept step 6c) based on confidence + impact + reject_count

  # v2.6 Phase A — adaptive shadow evaluation telemetry (start in shadow mode)
  shadow_mode: true                        # candidate enters shadow mode by default — telemetry-only until threshold met
  shadow_since_phase: "{phase number}"     # phase in which shadow tracking began
  shadow_correct: null                     # populated by bootstrap-shadow-evaluator.py
  shadow_total: null                       # populated by bootstrap-shadow-evaluator.py
  adaptive_threshold: null                 # snapshot at last tier decision
  confirmed_by_telemetry: null             # {rate, n_samples} written on subsequent surface

  # v2.6 Phase D — phase-scoped injection (regex against current phase number)
  # Reflector MUST inspect evidence_shas commit subjects to extract phase
  # numbers and propose a narrow pattern when all evidence concentrates in
  # one milestone. Default ".*" when evidence spans 2+ disjoint milestones.
  phase_pattern: ".*"                      # POSIX ERE matched against phase.number — narrow when evidence is milestone-local

  origin_incident: "phase-{number}-{short-desc}"
```

**v2.6 Phase A note:** new candidates MUST set `shadow_mode: true` and
`shadow_since_phase: "{current phase}"`. The other shadow fields stay
`null` until `bootstrap-shadow-evaluator.py` computes them at
`/vg:accept` step 6c. Shadow mode prevents premature auto-promotion;
the candidate sits at Tier C until correctness ≥ threshold AND
`n_samples ≥ shadow_min_phases` (default 5).

**v2.6 Phase D — phase_pattern suggestion from evidence commits:** when
aggregating `evidence_shas` (or `evidence[].sha` entries) for a candidate,
the reflector MUST extract phase numbers from each commit subject using
the canonical pattern `^[a-z]+\(([0-9]+(?:\.[0-9]+)*)-[0-9]+\):` (matches
`feat(7.14-04): ...`, `fix(12.3-01): ...`, etc.). Aggregate the major
component of each phase number (e.g. `7.14.3` → `7`, `12` → `12`).

Decision rule:
- All evidence majors are identical (e.g. all `7`) → suggest
  `phase_pattern: "^7\\."` (narrow to that milestone).
- Two adjacent majors (e.g. `7` and `8`) → suggest `^(7|8)\\.`.
- Three or more disjoint majors, OR a single piece of evidence → suggest
  `.*` (insufficient signal to narrow).
- Evidence subject doesn't match commit pattern (e.g. user_message only) →
  suggest `.*` (grandfather default).

Example draft snippet (reflector pseudo-code):

```python
import re
phases = []
for sha_subject in evidence_subjects:
    m = re.match(r"^[a-z]+\(([0-9]+(?:\.[0-9]+)*)-[0-9]+\):", sha_subject)
    if m:
        phases.append(m.group(1).split(".")[0])  # major component
majors = set(phases)
if len(majors) == 1:
    pattern = f"^{majors.pop()}\\."
elif len(majors) == 2:
    pattern = f"^({'|'.join(sorted(majors))})\\."
else:
    pattern = ".*"
candidate["phase_pattern"] = pattern
```

Operator can widen the pattern in `e` (edit) mode at `/vg:accept` step 6c
surface — narrow suggestion is just the default. Goal: prevent silent
global drift from milestone-local lessons.

**Impact field guidance:**
- `critical` — security rule (auth bypass, rate limit, CSRF), data integrity (transaction safety, idempotency), deploy safety (rollback gate, migration verify). User rejection uncommon; auto-promote after N confirms appropriate.
- `important` — workflow discipline (commit format, citation, contract alignment), test coverage, perf budget. Surface for confirm but don't auto-promote.
- `nice` — ergonomic (narration style, doc tone, optional lint rule). Silent parking; user opts in via `--review --all`.

When in doubt: default `important`. Never mark a new-unfamiliar rule as `critical` without an incident reference (origin_incident must cite a real breakage).

### Step 6: Dedupe check

```bash
DKEY=$(echo -n "${trigger}|${target_step}|${target_key}" | sha256sum | cut -d' ' -f1)

# Drop if already accepted
grep -q "dedupe_key: ${DKEY}" "$ACCEPTED_MD" && DROP=true

# Drop if rejected 2+ times (user doesn't want this)
REJECT_COUNT=$(grep -c "dedupe_key: ${DKEY}" "$REJECTED_MD" 2>/dev/null || echo 0)
[ "$REJECT_COUNT" -ge 2 ] && DROP=true
```

### Step 7: Append to OUT_FILE + emit telemetry

```bash
# Append passing candidates (max 3 total) to OUT_FILE as YAML blocks
cat >> "$OUT_FILE" <<EOF

## Candidates from reflector.$STEP.phase-$PHASE @ $(date -Iseconds)

$YAML_BLOCKS
EOF

# Emit via orchestrator (v2.2 — tamper-evident)
python .claude/scripts/vg-orchestrator emit-event "bootstrap.candidate_drafted" \
  --payload "{\"reflector_step\":\"$STEP\",\"phase\":\"$PHASE\",\"count\":$N_CANDIDATES,\"recurrences\":[$RECURRENCE_SUMMARY]}"
```

### Step 8: Exit code

```
0  = analyzed successfully (may have 0 candidates)
1  = input files missing / malformed
2  = orchestrator query-events crashed (degraded — proceed without events)
```

## Anti-echo-chamber checklist

Before writing any candidate, verify:

- [ ] Read ONLY artifacts + USER messages + events.db + git log
- [ ] AVOIDED AI responses in transcript
- [ ] Each candidate cites concrete evidence (event_id / user_msg_ts / git SHA / file:line)
- [ ] Confidence ≥ 0.7 (≥0.85 if recurrence ≥3)
- [ ] dedupe_key fresh (not in ACCEPTED, not 2×-rejected)

Answer NO to any → drop candidate.

## Signal patterns → candidate examples

### Pattern: recurring validation.failed

```
events.db query shows validator=goal-coverage failed 4 times across runs
dc609a27, a8f2b391, c02109ab, 7ffcd31e for phase 14.
```

Draft:
```yaml
- id: L-AUTO
  type: rule
  title: "Phase 14-style backend phases skip goal-coverage gate at review"
  target_step: review
  action: add_check
  proposed:
    prose: |
      Backend-only phases (no UI surfaces) should NOT run goal-coverage
      gate at /vg:review stage. Tests land at /vg:test. Gate enforcement
      moved to /vg:test + /vg:accept only.
  evidence:
    - source: events_db
      event_type: validation.failed
      excerpt: "validator=goal-coverage for 4 runs on phase 14"
  recurrence: 4
  confidence: 0.9
```

### Pattern: user correction about missing verification

User message: `"tôi reload rồi, không thấy data save"`

Draft:
```yaml
- id: L-AUTO
  type: rule
  title: "Verify data persistence after mutation via reload"
  target_step: review
  action: must_run
  proposed:
    prose: |
      After every mutation (POST/PUT/DELETE), test MUST:
      1. Execute mutation
      2. Wait for success response + toast
      3. RELOAD page (Ctrl+R equivalent)
      4. Re-read data — assert persisted value matches expected
      5. Fail if reload shows stale/missing data
  evidence:
    - source: user_message
      timestamp: "{iso}"
      text: "tôi reload rồi, không thấy data save"
  confidence: 0.9
```

## Output file format

Appends YAML blocks to `OUT_FILE`:

```markdown
## Candidates from reflector.{step}.phase-{phase} @ {iso}

- id: L-XXXX
  ...

- id: L-XXXY
  ...
```

Orchestrator (`/vg:review`, `/vg:scope`, etc) reads OUT_FILE after reflector returns, presents interactive y/n/e/s flow to user. User's choice → promoted to ACCEPTED.md / REJECTED.md / CANDIDATES.md.

## What's new in v2.2 vs v1.x

| Dimension | v1.x | v2.2 |
|-----------|------|------|
| Event source | `telemetry.jsonl` flat file | `events.db` SQLite + hash chain |
| Cross-run analysis | None (per-step only) | Recurrence detection via SQL queries |
| Evidence integrity | File mtime (can forge) | event_id (tamper-evident hash chain) |
| Override debt correlation | Separate register | Queryable as event type `override.used` |
| Validation failure attribution | Log message parse | Typed `validation.failed` payload |
| Dedupe scope | This run's candidates | History via `query-events --phase` |

Queries via `vg-orchestrator query-events` are the canonical signal path. No shell parsing of log files.
