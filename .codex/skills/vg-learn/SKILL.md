---
name: "vg-learn"
description: "Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings"
metadata:
  short-description: "Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings"
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

Invoke this skill as `$vg-learn`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



---
description: Review, promote, reject, or retract bootstrap candidates — user-gate for AI-proposed learnings
argument-hint: "[--auto-surface|--review [id]|--review --all|--promote <id> --reason '...'|--reject <id> --reason '...'|--retract <id> --reason '...']"
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "learn.started"
    - event_type: "learn.completed"
    - event_type: "learn.promoted"  # on successful promote
    - event_type: "learn.rejected"  # on successful reject
    - event_type: "learn.promote_attempt_unauthenticated"  # blocked attempt
---

# /vg:learn

User gate for bootstrap overlay changes. Primary entry point: **end-of-step reflection** auto-drafts candidates into `.vg/bootstrap/CANDIDATES.md`. This command reviews them.

## Authentication (harness v2.6 Phase G, 2026-04-26)

Mutating actions (`--promote`, `--reject`) write to the bootstrap rule
set, which is injected into every subsequent executor prompt. A
fabricated candidate self-promoted by an AI subagent would silently
alter platform behaviour across phases. Same authentication surface as
`/vg:override-resolve` and `/vg:calibrate apply`:

| Action | Auth required | --reason required |
|---|---|---|
| `--auto-surface` | no | per-prompt y/n |
| `--review [id]` | no | no |
| `--review --all` | no | no |
| `--promote <id>` | **TTY OR HMAC token** | **min 50 chars** |
| `--reject <id>` | **TTY OR HMAC token** | **min 50 chars** |
| `--retract <id>` | **TTY OR HMAC token** | **min 50 chars** |

The orchestrator subcommand `learn promote/reject` enforces the gate via
`verify_human_operator()`. Two valid auth paths:

1. **TTY (interactive shell)** — auto-approved when run from a real
   terminal. Approver recorded as `$USER` / `$USERNAME`.
2. **HMAC-signed token (CI / automation escape hatch)** — mint via
   `python3 .claude/scripts/vg-auth.py approve --flag learn-promote`,
   then `export VG_HUMAN_OPERATOR=<token>`. Token is HMAC-signed against
   `~/.vg/.approver-key` (mode 0600 on POSIX).

Failed authentication paths emit
`learn.{promote,reject}_attempt_unauthenticated` events for the forensic
trail. Successful applies emit `learn.{promoted,rejected}` with
`{candidate_id, tier, reason, operator_token, auth_method}` payload —
auditors can reconstruct who/when/why for every rule-set mutation.

**The `--reason` flag is mandatory for promote/reject/retract and must
be ≥50 characters.** Audit text must justify the decision concretely:
evidence count, phases observed, conflict assessment. Placeholder reasons
(`"approved"`, `"obvious"`, `"per Claude"`) are filtered by the same
length gate as `--override-reason`.

## v2.5 Phase H: tiered auto-surface (fixes UX fatigue)

Problem before v2.5: user had to remember `/vg:learn --review` + sort through 10+ candidates → fatigue → "all-defer" → promotion loop never closed. Fix: automatic tier classification + silent auto-promote for high-confidence + hard cap on Tier B per phase.

**Tier A** (confidence ≥ 0.85 + impact=critical): auto-promote after N=3 phase confirms (configured via `bootstrap.tier_a_auto_promote_after_confirms`). User sees 1-line notification only.

**Tier B** (confidence 0.6-0.85 OR impact=important): surfaced at end of `/vg:accept` via `--auto-surface` mode, MAX 2 per phase (config `bootstrap.tier_b_max_per_phase`). 3 lines per candidate: rule + evidence count + target. Prompt: `y/n/e/s`.

**Tier C** (confidence < 0.6 or impact=nice): silent parking. Access via `/vg:learn --review --all` (user initiates when willing).

**Retirement**: candidate rejected ≥ 2 times → marked RETIRED, never surfaced again.

**Dedupe**: before surfacing, candidates with title similarity ≥ 0.8 are merged (evidence combined, one ID kept).

## Load config

Read `.claude/commands/vg/_shared/config-loader.md` first. Sets `${PLANNING_DIR}`, `${PYTHON_BIN}`, etc.

## Subcommands

### `/vg:learn --auto-surface` (v2.5 Phase H)

Invoked automatically at end of `/vg:accept` (unless `bootstrap.auto_surface_at_accept: false`).

**Flow:**
1. Run `learn-dedupe.py` — merge title-similar candidates (threshold 0.8) in-place into CANDIDATES.md
2. Run `learn-tier-classify.py --all` to tier every pending candidate
3. Auto-promote Tier A candidates with ≥ N confirms (config `tier_a_auto_promote_after_confirms`, default 3) — silent 1-line log
4. Surface first `tier_b_max_per_phase` (default 2) Tier B candidates interactively, 3 lines each:
   ```
   L-042 — "Playwright required for UI phases when surfaces contains 'web'" (tier B, 8 evidence)
     Target: review.step-2 (discovery)
     Action: must_run before skip
   Promote? [y]es / [n]o / [e]dit / [s]kip-rest → _
   ```
5. If user hits 's' → defer remaining Tier B candidates this phase (resurfaced next phase)
6. Tier C is silent (not mentioned) — access via `/vg:learn --review --all`

**Telemetry per candidate:**
- `bootstrap.candidate_surfaced` when shown to user
- `bootstrap.rule_promoted` when user approves
- `bootstrap.rule_retired` when reject count hits threshold

**Transparency after promote:** show 1-line "injected into next phase executor prompt at section R{N}" — so user knows rule is live, not just "y but did anything happen?"

### `/vg:learn --review [id]`

List pending candidates (legacy interface, still supported). With `<id>`, show full evidence + dry-run preview.

**Without `<id>`** — list all:
```bash
# Candidates are fenced ```yaml blocks starting with `id: L-XXX` at column 0
# (top-level mapping, not list-style — list-style would collide with YAML
# sequence semantics inside the fence).
grep -nE '^id: L-' .vg/bootstrap/CANDIDATES.md | head -20
```

For each candidate, show: id, title, type, scope, confidence, created_at.

**With `<id>`** — show full detail:
1. Parse candidate block from `.vg/bootstrap/CANDIDATES.md`
2. Show all evidence entries (file:line, user message, telemetry event_id)
3. **Dry-run preview:**
   - For `config_override`: diff current vanilla config vs proposed
   - For `rule`: evaluate scope against last 10 phases, report which would have matched
   - Impact: "rule would fire in N future phases with current metadata"
   - Conflict check: list any active ACCEPTED rules with overlapping scope + opposite action

Display with mandatory confirm prompt:
```
Promote? [y/n/edit]
```

### `/vg:learn --promote <id> --reason "..."`

Apply candidate to bootstrap zone.

**MANDATORY auth gate (harness v2.6 Phase G):** Before any pre-check
runs, the orchestrator subcommand `learn promote` requires:
- TTY OR HMAC-signed `VG_HUMAN_OPERATOR` token (see Authentication
  section above), AND
- `--reason "..."` ≥ 50 characters citing concrete evidence

Failed auth → BLOCK with rc=2 + `learn.promote_attempt_unauthenticated`
audit event. AI subagents cannot self-promote.

**MANDATORY pre-check (after auth passes):**
1. Schema validate (for `config_override`): target key must be in `schema/overlay.schema.yml` allowlist
   - If not in allowlist → offer fallback: "convert to prose rule?"
2. Scope syntax validate via `scope-evaluator.py --context-json <empty> --scope-json <scope>` → exit 2 = malformed
3. **Conflict detect** vs active ACCEPTED rules (same target key, opposite value/action) — MUST call `bootstrap-conflict.py`:
   ```bash
   # Write candidate block to tempfile then call conflict detector
   CAND_YAML=$(mktemp -t vg-candidate-XXXXXX.yml)
   # AI extracts candidate YAML block from CANDIDATES.md for L-XXX into $CAND_YAML
   RESULT=$("${PYTHON_BIN:-python3}" .claude/scripts/bootstrap-conflict.py \
     --candidate "$CAND_YAML" --emit json)
   CONFLICT_RC=$?
   rm -f "$CAND_YAML"
   if [ "$CONFLICT_RC" -ne 0 ]; then
     echo "⛔ Conflict detected — cannot promote L-XXX:" >&2
     echo "$RESULT" | ${PYTHON_BIN:-python3} -c "import json,sys; [print(f'  - {c}') for c in json.load(sys.stdin).get('conflicts', [])]"
     echo "   Resolve: retract conflicting rule OR adjust candidate scope." >&2
     exit 1
   fi
   ```
4. Dedupe check vs ACCEPTED (semantic equivalence) → block if duplicate
5. Dry-run REQUIRED (shows impact preview)

**If all pass:**
1. For `config_override` → update `.vg/bootstrap/overlay.yml` (deep-merge)
2. For `rule` → write `.vg/bootstrap/rules/{slug-from-title}.md` with full frontmatter
3. For `patch` → write `.vg/bootstrap/patches/{command}.{anchor}.md`, validate anchor in `anchors.yml`
4. Remove candidate from `CANDIDATES.md`
5. Append to `ACCEPTED.md` with git_sha placeholder
6. **Git commit atomic:**
   ```
   chore(bootstrap): promote L-XXX — {reason}

   Type: {type}
   Target: {target}
   Origin: {origin_incident or user.lesson}
   Confidence: {confidence}
   ```
7. Update ACCEPTED.md entry with real SHA
8. Emit telemetry:
   ```
   emit_telemetry "bootstrap.candidate_promoted" PASS \
     "{\"id\":\"L-XXX\",\"type\":\"...\",\"target\":\"...\"}"
   ```

### `/vg:learn --reject <id> --reason "..."`

Decline candidate. Reason is REQUIRED — same auth gate as promote
(harness v2.6 Phase G):
- TTY OR HMAC-signed token, AND
- `--reason "..."` ≥ 50 characters

Why same gate as promote? An AI subagent rejecting a candidate that
flags its own corner-cutting pattern is just as much a self-mutation —
the rule never gets reconsidered. Symmetric defense: both directions
require human accountability.

1. Move candidate block from `CANDIDATES.md` to `REJECTED.md`
2. Append rejection metadata: user, timestamp, reason, dedupe_key
3. Emit telemetry `learn.rejected` (success) or
   `learn.reject_attempt_unauthenticated` (auth fail)

Reflector checks `REJECTED.md` dedupe_key before future drafts — 2+ rejects of same key → silent skip forever.

### `/vg:learn --retract <id> --reason "..."`

**Emergency rollback** — remove an ACCEPTED rule immediately. Reason REQUIRED.

Use when:
- Rule caused regression discovered after promote
- Rule obsolete after refactor
- Manual cleanup

1. Locate rule in bootstrap zone (overlay.yml key / rules/*.md / patches/*.md)
2. Remove / set status=retracted
3. Append to `RETRACTED.md` with stats snapshot (hits, success/fail counts)
4. Git commit atomic:
   ```
   chore(bootstrap): retract L-XXX — {reason}
   ```
5. Emit `bootstrap.rule_retracted` telemetry

## Interactive inline-edit (`e` option during --review)

Not an external editor — prompt loop:
```
Editing L-042:
  [1] title:    "Playwright required for UI phases"
  [2] scope:    any_of: [...]
  [3] action:   must_run
  [4] prose:    "..."
  [5] target_step: review
  [done] finish editing

Field to edit? [1/2/3/4/5/done]: _
```

User picks field, inline-prompt shows current value, user types new value, save.
When `done` → re-validate schema + scope syntax, then proceed to promote.

## Output

- `--review` → terminal listing + optional full-detail block
- `--promote/--reject/--retract` → confirmation message + git SHA

## Safety

- Every promote = 1 git commit (atomic, revertable)
- Every reject has reason (REJECTED.md audit)
- Every retract has reason + stats snapshot (RETRACTED.md audit)
- Schema validation blocks AI invent fake keys
- Conflict detection blocks incompatible rules
- Dedupe blocks redundant rules
- Dry-run mandatory — no way to promote without seeing impact preview first
