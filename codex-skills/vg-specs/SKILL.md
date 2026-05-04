---
name: "vg-specs"
description: "Create SPECS.md for a phase — AI-draft or user-guided mode"
metadata:
  short-description: "Create SPECS.md for a phase — AI-draft or user-guided mode"
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

Invoke this skill as `$vg-specs`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Generate a concise SPECS.md defining phase goal, scope, constraints, and success criteria. This is the FIRST step of the VG pipeline — specs must be locked before scope, blueprint, or build can proceed.

Output: `${PLANNING_DIR}/phases/{phase_dir}/SPECS.md`
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

**Context loading (was a separate step, now process preamble — OHOK Batch 1 A1).**

Before any step below, read these files once to build context for the entire run:
1. **ROADMAP.md** — Phase goal, success criteria, dependencies
2. **PROJECT.md** — Project constraints, stack, architecture decisions
3. **STATE.md** — Current progress, what's already done
4. **Prior SPECS.md files** — `${PHASES_DIR}/*/SPECS.md` (1-2 most recent for style reference)

Store: `phase_goal`, `phase_success_criteria`, `project_constraints`, `prior_phases_done`, `spec_style`.

```bash
# Register run with orchestrator
[ -z "${PHASE_NUMBER:-}" ] && PHASE_NUMBER=$(echo "${ARGUMENTS}" | awk '{print $1}')
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:specs "${PHASE_NUMBER}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.started" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

# v2.5.1 anti-forge: show task list at flow start so user sees planned steps
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:specs" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true
```

<step name="parse_args">
## Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- **phase_number** — Required. e.g., "7.4", "8", "3.1"
- **--auto flag** — Optional. If present, skip interactive questions and AI-draft directly.

**Validate:**

```bash
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-specs" "parse_args" 2>&1 || true

# OHOK Batch 1 B2: phase existence gate (previously prose "fail fast", no enforcement).
# Accepts both "Phase X" and bare "X" at line start in ROADMAP.md.
if [ -z "${PHASE_NUMBER:-}" ]; then
  echo "⛔ PHASE_NUMBER not set — argument required" >&2
  exit 1
fi

ROADMAP="${PLANNING_DIR:-.vg}/ROADMAP.md"
if [ ! -f "$ROADMAP" ]; then
  echo "⛔ ROADMAP.md not found at ${ROADMAP}" >&2
  echo "   Run /vg:roadmap first to derive phases from PROJECT.md." >&2
  exit 1
fi

if ! grep -qE "(^##?\s+(Phase\s+)?${PHASE_NUMBER}[\s:|.-])|(^\|\s*${PHASE_NUMBER}[\s:|.-])|(^- \[.\]\s+\*\*Phase\s+${PHASE_NUMBER}[\s:.-])" "$ROADMAP" 2>/dev/null; then
  echo "⛔ Phase ${PHASE_NUMBER} not found in ${ROADMAP}" >&2
  echo "   Check phase number or add via /vg:add-phase." >&2
  echo "   Accepted ROADMAP formats:" >&2
  echo "     '## Phase N: ...'  |  '| N | ... |'  |  '- [x] **Phase N: ...**'" >&2
  exit 1
fi

# Resolve phase dir (create if missing)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/phase-resolver.sh" 2>/dev/null || true
if type -t resolve_phase_dir >/dev/null 2>&1; then
  PHASE_DIR=$(resolve_phase_dir "$PHASE_NUMBER" 2>/dev/null || echo "")
fi
if [ -z "${PHASE_DIR:-}" ]; then
  # Bootstrap phase dir if totally new (extract slug from ROADMAP heading if possible)
  PHASE_SLUG=$(grep -E "^##?\s+(Phase\s+)?${PHASE_NUMBER}\b" "$ROADMAP" \
               | head -1 | sed -E 's/^##?\s+(Phase\s+)?[0-9.]+[\s:.-]+//; s/[[:space:]]+/-/g; s/[^a-zA-Z0-9-]//g' \
               | tr '[:upper:]' '[:lower:]' | head -c 60)
  [ -z "$PHASE_SLUG" ] && PHASE_SLUG="phase-${PHASE_NUMBER}"
  PHASE_DIR="${PLANNING_DIR:-.vg}/phases/${PHASE_NUMBER}-${PHASE_SLUG}"
  mkdir -p "$PHASE_DIR"
fi

export PHASE_DIR
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "parse_args" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/parse_args.done"
```
</step>

<step name="check_existing">
## Step 2: Check Existing SPECS.md

If `${PHASE_DIR}/SPECS.md` already exists:

Ask user via `AskUserQuestion`:
- header: "SPECS.md exists — what next?"
- question: "SPECS.md đã tồn tại cho Phase ${PHASE_NUMBER}. Chọn: View (xem), Edit (giữ + sửa từng section), Overwrite (ghi đè từ đầu)."
- options:
  - "View — hiển thị nội dung rồi hỏi lại"
  - "Edit — giữ nguyên, sửa section cụ thể"
  - "Overwrite — start fresh"

Act on the response. If "View", show contents then re-ask. If "Edit", proceed to guided editing of specific sections. If "Overwrite", continue to next step.

If SPECS.md does not exist, continue.

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "check_existing" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/check_existing.done"
```
</step>

<step name="choose_mode">
## Step 3: Choose Mode

```bash
AUTO_MODE=false
if [[ "${ARGUMENTS:-}" =~ --auto ]]; then
  AUTO_MODE=true
fi
```

If `$AUTO_MODE=true`, skip to step 5 (generate_draft).

Otherwise, invoke `AskUserQuestion`:
- header: "SPECS mode"
- question: "Phase ${PHASE_NUMBER}: ${phase_goal}. Bạn muốn tạo SPECS theo cách nào?"
- options:
  - "AI Draft — tôi tự draft dựa trên ROADMAP + PROJECT"
  - "Guided — tôi hỏi 4-5 câu để bạn mô tả"

- If "AI Draft" → go to step 5 (generate_draft)
- If "Guided" → go to step 4 (guided_questions)

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "choose_mode" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/choose_mode.done"
```
</step>

<step name="guided_questions">
## Step 4: Guided Questions (User-Guided Mode only — skipped in --auto)

Ask questions ONE AT A TIME via `AskUserQuestion`. After each answer, save it immediately to avoid context loss.

**Q1: Goal** — "Mục tiêu chính của phase này là gì? (1-2 câu). ROADMAP nói: ${phase_goal}"

**Q2: Scope IN** — "Những gì NẰM TRONG scope? (liệt kê features/tasks)"

**Q3: Scope OUT** — "Những gì KHÔNG làm trong phase này? (exclusions rõ ràng)"

**Q4: Constraints** — "Ràng buộc kỹ thuật hoặc business nào cần lưu ý? (VD: latency, compatibility, dependencies)"

**Q5: Success Criteria** — "Làm sao biết phase này DONE? (tiêu chí đo lường được)"

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "guided_questions" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/guided_questions.done"
```
</step>

<step name="generate_draft">
## Step 5: Generate Draft + Approval Gate

**If AI Draft mode (`$AUTO_MODE=true` or user chose option 1):**
- Generate SPECS.md content from ROADMAP phase goal + PROJECT.md constraints
- Infer scope, constraints, success criteria from available context
- Match style of prior SPECS.md files if present

**If Guided mode:**
- Use user's answers from step 4 as primary content
- Supplement with ROADMAP + PROJECT where answers sparse
- Do NOT override explicit user answers with AI inference

**⛔ BLOCKING APPROVAL GATE — user MUST approve before write (OHOK Batch 1 B3).**

Render preview to user, then invoke `AskUserQuestion`:
- header: "Approve SPECS.md draft?"
- question: "Preview bên trên. Chọn Approve để ghi file, Edit để yêu cầu sửa, Discard để huỷ."
- options:
  - "Approve — write SPECS.md và tiếp tục"
  - "Edit — nói cần sửa gì, tôi regenerate rồi hỏi lại"
  - "Discard — dừng command, không tạo SPECS.md"

```bash
# OHOK Batch 1 B3: enforce explicit approval via $USER_APPROVAL env.
# AI MUST set USER_APPROVAL based on AskUserQuestion response:
#   "approve" → proceed to step 6
#   "edit" → loop back (regenerate + re-gate)
#   "discard" → exit 2 (clean halt, telemetry records decision)
# Silence / ambiguous / empty = treat as unapproved.

case "${USER_APPROVAL:-}" in
  approve)
    MODE_STR=$([ "${AUTO_MODE:-false}" = "true" ] && echo "auto" || echo "guided")
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.approved" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mode\":\"${MODE_STR}\"}" >/dev/null 2>&1 || true
    ;;
  edit)
    echo "User requested edit — regenerate draft + re-gate" >&2
    # AI loops back to regenerate; marker NOT touched until approve/discard terminal
    exit 2
    ;;
  discard)
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "specs.rejected" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"user_discarded\"}" >/dev/null 2>&1 || true
    echo "⛔ User discarded SPECS draft — halting /vg:specs (no file written)" >&2
    # Log to override-debt so audit trail captures the reject
    source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "specs-user-discard" "${PHASE_NUMBER}" "user discarded draft at approval gate" "${PHASE_DIR}"
    fi
    exit 2
    ;;
  *)
    echo "⛔ Approval gate not passed — USER_APPROVAL='${USER_APPROVAL:-<unset>}'" >&2
    echo "   AI must invoke AskUserQuestion and set USER_APPROVAL ∈ {approve, edit, discard}." >&2
    echo "   Silence / ambiguous answer = unapproved. No SPECS.md written." >&2
    exit 2
    ;;
esac

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "generate_draft" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/generate_draft.done"
```

**Rationale:** previous wording "AI MUST stop, render preview, wait" was prose-only — AI could silent-skip and proceed to write. Now gate is bash-enforced: no write without `USER_APPROVAL=approve` env set by AI based on AskUserQuestion result.
</step>

<step name="write_specs">
## Step 6: Write SPECS.md

Write to `${PHASE_DIR}/SPECS.md` with this format:

```markdown
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
phase: {X}
status: approved
created: {YYYY-MM-DD}
source: ai-draft|user-guided
---

## Goal

{1-2 sentence phase objective}

## Scope

### In Scope
- {feature/task 1}
- {feature/task 2}

### Out of Scope
- {exclusion 1}
- {exclusion 2}

## Constraints
- {constraint 1}

## Success Criteria
- [ ] {measurable criterion 1}
- [ ] {measurable criterion 2}

## Dependencies
- {dependency on prior phase or external system}
```

- **source**: `ai-draft` if --auto or user chose option 1, else `user-guided`
- **created**: today's date YYYY-MM-DD

```bash
# Verify file actually written (catches silent write fail)
if [ ! -s "${PHASE_DIR}/SPECS.md" ]; then
  echo "⛔ SPECS.md write failed — file missing or empty at ${PHASE_DIR}/SPECS.md" >&2
  exit 1
fi

# v2.7 Phase E — schema validation post-write (BLOCK on frontmatter drift).
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
PYTHON_BIN="${PYTHON_BIN:-python3}"
"${PYTHON_BIN}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact specs \
  > "${PHASE_DIR}/.tmp/artifact-schema-specs.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ SPECS.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-specs.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-specs.json"
  exit 2
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "write_specs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/write_specs.done"
```
</step>

<step name="write_interface_standards">
## Step 7: Write Interface Standards

After SPECS.md exists, generate the phase-local API/FE/CLI/mobile interface
contract. This artifact is mandatory context for blueprint, build, review,
and test. It standardizes API response envelopes, FE toast/form error
priority, CLI stdout/stderr/JSON output, and harness enforcement.

```bash
INTERFACE_GEN="${REPO_ROOT:-.}/.claude/scripts/generate-interface-standards.py"
INTERFACE_VAL="${REPO_ROOT:-.}/.claude/scripts/validators/verify-interface-standards.py"
[ -f "$INTERFACE_GEN" ] || INTERFACE_GEN="${REPO_ROOT:-.}/scripts/generate-interface-standards.py"
[ -f "$INTERFACE_VAL" ] || INTERFACE_VAL="${REPO_ROOT:-.}/scripts/validators/verify-interface-standards.py"

if [ ! -f "$INTERFACE_GEN" ] || [ ! -f "$INTERFACE_VAL" ]; then
  echo "⛔ Interface standards helpers missing — cannot continue specs." >&2
  exit 1
fi

"${PYTHON_BIN:-python3}" "$INTERFACE_GEN" \
  --phase-dir "$PHASE_DIR" \
  --profile "${PROFILE:-web-fullstack}" \
  --force

mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
"${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
  --phase-dir "$PHASE_DIR" \
  --profile "${PROFILE:-web-fullstack}" \
  --no-scan-source \
  > "${PHASE_DIR}/.tmp/interface-standards-specs.json" 2>&1
INTERFACE_RC=$?
if [ "$INTERFACE_RC" -ne 0 ]; then
  echo "⛔ INTERFACE-STANDARDS validation failed — see ${PHASE_DIR}/.tmp/interface-standards-specs.json" >&2
  cat "${PHASE_DIR}/.tmp/interface-standards-specs.json"
  exit 1
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "write_interface_standards" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/write_interface_standards.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step specs write_interface_standards 2>/dev/null || true
```
</step>

<step name="commit_and_next">
## Step 8: Commit and Next Step

```bash
git add "${PHASE_DIR}/SPECS.md" \
        "${PHASE_DIR}/INTERFACE-STANDARDS.md" \
        "${PHASE_DIR}/INTERFACE-STANDARDS.json" || {
  echo "⛔ git add failed — check permissions" >&2
  exit 1
}
git commit -m "specs(${PHASE_NUMBER}): create SPECS and interface standards for phase ${PHASE_NUMBER}" || {
  echo "⛔ git commit failed — check pre-commit hooks" >&2
  exit 1
}

# ─── P20 D-05: greenfield design discovery suggestion ──────────────────────
# After SPECS committed, surface design state proactively. Soft suggestion
# (doesn't block). Hard gate fires later in /vg:blueprint D-12.
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/scaffold-discovery.sh" 2>/dev/null || true
if type -t scaffold_detect_fe_work >/dev/null 2>&1 && scaffold_detect_fe_work "$PHASE_DIR"; then
  DESIGN_DIR=$(vg_config_get design_assets.paths "" 2>/dev/null | head -1)
  DESIGN_DIR="${DESIGN_DIR:-designs}"
  if ! scaffold_design_md_present "$PHASE_DIR"; then
    echo ""
    echo "ℹ Phase ${PHASE_NUMBER} có FE work nhưng chưa có DESIGN.md (tokens). Khuyến nghị:"
    echo "    /vg:design-system --browse   (chọn brand từ 58 variants)"
    echo "    /vg:design-system --create   (tạo custom)"
  fi
  MOCKUP_COUNT=$(scaffold_count_existing_mockups "$DESIGN_DIR")
  if [ "$MOCKUP_COUNT" = "0" ]; then
    echo ""
    echo "ℹ Chưa có mockup nào ở ${DESIGN_DIR}/. Khuyến nghị trước /vg:blueprint:"
    echo "    /vg:design-scaffold       (interactive tool selector)"
    echo "    /vg:design-scaffold --tool=pencil-mcp   (auto-generate)"
    echo ""
    echo "  /vg:blueprint D-12 sẽ HARD-BLOCK nếu vẫn thiếu mockup."
  fi
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "commit_and_next" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/commit_and_next.done"

# Orchestrator run-complete — validates runtime_contract + emits specs.completed
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ "$RUN_RC" -ne 0 ]; then
  echo "⛔ specs run-complete BLOCK (rc=$RUN_RC) — see orchestrator output" >&2
  exit $RUN_RC
fi

echo ""
echo "✓ SPECS.md + INTERFACE-STANDARDS created for Phase ${PHASE_NUMBER}."
echo "  Next: /vg:scope ${PHASE_NUMBER}"
```
</step>

</process>

<success_criteria>
- SPECS.md written to `${PHASE_DIR}/SPECS.md`
- INTERFACE-STANDARDS.md/json written to `${PHASE_DIR}/INTERFACE-STANDARDS.*`
- Contains ALL sections: Goal, Scope (In/Out), Constraints, Success Criteria, Dependencies
- Frontmatter includes phase, status, created, source fields
- User explicitly approved (`USER_APPROVAL=approve`) before writing — silent / unset = BLOCK
- All 8 step markers present under `.step-markers/` (guided_questions waived in --auto mode)
- `specs.started` + `specs.approved` telemetry events emitted
- Git committed + `run-complete` returned 0
</success_criteria>
