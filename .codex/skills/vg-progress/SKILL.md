---
name: "vg-progress"
description: "Show detailed pipeline progress across all phases — artifact status, current step, next action"
metadata:
  short-description: "Show detailed pipeline progress across all phases — artifact status, current step, next action"
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

Invoke this skill as `$vg-progress`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Show detailed progress dashboard for the VG pipeline. Without arguments, shows current phase + overview of all phases. With a phase argument, shows deep detail for that phase.

Pipeline steps: specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
Read .claude/commands/vg/_shared/config-loader.md first.
</step>

<step name="0a_dashboard_shortcut">
**Phase E (2026-04-26): `--dashboard` shortcut.**

If `$ARGUMENTS` contains `--dashboard`, generate the dogfood dashboard and
open it in the default browser, then exit early — skip the per-phase
artifact scan below. The dashboard is a separate read-only surface and
runs on a different cadence than the table view.

```bash
if echo "$ARGUMENTS" | grep -q -- "--dashboard"; then
  LOOKBACK=$(echo "$ARGUMENTS" | grep -oE -- "--lookback-phases [0-9]+" | awk '{print $2}')
  LOOKBACK=${LOOKBACK:-10}
  OUTPUT="${REPO_ROOT:-.}/.vg/dashboard.html"

  PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} \
    "${REPO_ROOT:-.}/.claude/scripts/dogfood-dashboard.py" \
    --lookback-phases "$LOOKBACK" \
    --output "$OUTPUT"

  # Cross-platform open: Python's webbrowser.open() handles win/mac/linux uniformly.
  # Quiet mode — never block the user if browser launch fails.
  ${PYTHON_BIN:-python3} -c "import webbrowser, sys; webbrowser.open('file://' + sys.argv[1])" "$OUTPUT" 2>/dev/null || true
  echo ""
  echo "✓ Dashboard at $OUTPUT"
  exit 0
fi
```

Flag synopsis:
- `/vg:progress --dashboard` — generate + open dashboard.html with default 10-phase lookback
- `/vg:progress --dashboard --lookback-phases 5` — narrower window
- Other flags (`[phase]`, `--all`) ignored when `--dashboard` is set.
</step>

<step name="0b_version_banner">
Show VG version + update availability. Daily cache to avoid hammering GitHub API (60/hr unauth quota).

```bash
VGFLOW_VERSION=$(cat .claude/VGFLOW-VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
CACHE_DIR=".cache"
CACHE_FILE="${CACHE_DIR}/vgflow-latest-check.json"
mkdir -p "$CACHE_DIR" 2>/dev/null || true

# Refresh cache if older than 1 day (or missing). Don't fail banner on network error.
if [ ! -f "$CACHE_FILE" ] || [ -n "$(find "$CACHE_FILE" -mtime +1 2>/dev/null)" ]; then
  if [ -f ".claude/scripts/vg_update.py" ]; then
    timeout 3 python3 .claude/scripts/vg_update.py check --repo "vietdev99/vgflow" > "$CACHE_FILE" 2>/dev/null || true
  fi
fi

LATEST=$(grep -oE 'latest=[^ ]+' "$CACHE_FILE" 2>/dev/null | cut -d= -f2)

if [ -n "$LATEST" ] && [ "$LATEST" != "unknown" ] && [ "$LATEST" != "$VGFLOW_VERSION" ]; then
  echo "VG v${VGFLOW_VERSION} (latest v${LATEST} available — run /vg:update)"
else
  echo "VG v${VGFLOW_VERSION}"
fi
echo ""
```

Gracefully degrades: no VGFLOW-VERSION → "VG vunknown"; offline → no update hint (cached or nothing).
</step>

<step name="1_scan_phases">
**Deterministic scan via script — DO NOT self-scan.**

LLM self-scanning across many phases is error-prone (hallucinated counts, missed
verdict formats). Progress uses a Python script as the single source of truth.

**UTF-8 safety (Windows fix, v1.13.0):** Python emits ✅ 🔄 ⬜ ❌ icons in JSON.
On Windows, default codepage is cp1252/cp1258 which crashes on emoji bytes.
Always export `PYTHONIOENCODING=utf-8` when invoking AND when reading back,
and write to a file instead of `$(…)` capture (bash var encoding inconsistent).

```bash
PROGRESS_JSON="${PLANNING_DIR}/.vg-progress.json"
mkdir -p "$(dirname "$PROGRESS_JSON")"

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-progress.py" \
  --planning "${PLANNING_DIR}" --output json > "$PROGRESS_JSON" 2>/dev/null

if [ ! -s "$PROGRESS_JSON" ]; then
  echo "⛔ vg-progress.py failed or produced empty output. Falling back to artifact check — results may be stale."
fi

# Read back with explicit UTF-8 (never rely on OS default encoding).
# When iterating from the orchestrator, always use this pattern:
#   PYTHONIOENCODING=utf-8 python -c "import json, io; \
#     data = json.load(io.open('$PROGRESS_JSON', encoding='utf-8')); \
#     ..."
```

The script returns JSON:
```json
{
  "current_phase_from_state": "07.8",
  "phase_count": 33,
  "phases": [
    {
      "phase": "07.7",
      "name": "07.7-inventory-floor-pricing-engine",
      "label": "DONE",
      "done_count": 7,
      "total_steps": 7,
      "current_step": null,
      "next_command": "—",
      "steps": {
        "specs": {"status": "done", "icon": "✅", "source": "artifact"},
        "scope": {"status": "done", "icon": "✅", "source": "artifact"},
        "blueprint": {"status": "done", "icon": "✅", "source": "artifact"},
        "build": {"status": "done", "icon": "✅", "source": "artifact"},
        "review": {"status": "done", "icon": "✅", "source": "artifact"},
        "test": {"status": "done", "icon": "✅", "source": "artifact"},
        "accept": {"status": "done", "icon": "✅", "source": "artifact"}
      },
      "content": {
        "sandbox": "PASSED",
        "uat": "ACCEPTED",
        "matrix": {"ready": 36, "blocked": 0, "unreachable": 0, "gate": "PASS"}
      },
      "artifacts": {...},
      "pipeline_state": null
    }
  ]
}
```

Key fields to render in Step 3:
- `label` — overall status (DONE | BLOCKED | IN_PROGRESS | NOT_STARTED)
- `done_count/total_steps` — "6/7" in header
- `steps[*].icon` — pipeline string
- `next_command` — exact command to suggest (already includes phase number)
- `content.sandbox`, `content.uat`, `content.matrix` — for detail view

**Detection rules the script enforces** (so renderer trusts them):
1. **PIPELINE-STATE.json** is authoritative — script reads it first, falls back to artifacts only if missing.
2. **UAT verdict** parsing handles all seen formats: `**Verdict:** ACCEPTED`,
   `## Verdict: PASSED`, `status: complete`, YAML frontmatter prioritized over
   per-test `status:` lines deeper in file.
3. **Monotonic invariant** — if step N is done, all steps < N are promoted to
   done with `source: "inferred"`. Prevents false BLOCKED when review matrix
   has an unusual format but UAT has already accepted the phase.
4. **Matrix gate** — `Ready: X | Blocked: Y | Unreachable: Z` parsed deterministically.
   FAIL only when Blocked+Unreachable > 0 AND UAT hasn't accepted downstream.
</step>

<step name="2_identify_current">
**Determine active phase:**

Read `${PLANNING_DIR}/STATE.md` (if exists) for `current_phase`.
If STATE.md missing → active phase = first phase with step < 7.
If all phases done → show milestone completion.
</step>

<step name="3_display_overview">
**Display multi-phase dashboard — one pipeline block per phase.**

For EACH phase in ${PHASES_DIR} (sorted numerically), render this block:

```
────────────────────────────────────────────────────────────────
Phase {N}: {name}   [{step}/7]   {status_label}

Pipeline: {s0} specs → {s1} scope → {s2} blueprint → {s3} build → {s4} review → {s5} test → {s6} accept

Next: {next_command_or_dash}
────────────────────────────────────────────────────────────────
```

**IMPORTANT — use the inline format above, NOT a separate "Status:" row.**

Why: status icons on their own line don't align with step names (different widths: "specs"=5 chars, "blueprint"=9 chars, "test"=4 chars). Inline format puts each icon directly next to its step name — no alignment issues.

Example rendered output:
```
Pipeline: ✅ specs → ✅ scope → ✅ blueprint → ✅ build → 🔄 review → ⬜ test → ⬜ accept
```

**Status icon per step (computed from artifacts):**

| Step | Icon logic |
|------|-----------|
| 0 (specs)     | ✅ if SPECS.md exists, else ⬜ |
| 1 (scope)     | ✅ if CONTEXT.md exists, else ⬜ (🔄 if SPECS exists but no CONTEXT = currently here) |
| 2 (blueprint) | ✅ if PLAN*.md + API-CONTRACTS.md exist, 🔄 if partial, ⬜ if none |
| 3 (build)     | ✅ if SUMMARY*.md exists, ⬜ otherwise |
| 4 (review)    | ✅ if RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX gate=PASS, 🔄 if RUNTIME exists but gate BLOCK, ❌ if gate=FAILED, ⬜ if no RUNTIME-MAP |
| 5 (test)      | ✅ if *-SANDBOX-TEST.md exists + verdict=PASSED, 🔄 if GAPS_FOUND, ❌ if FAILED, ⬜ if missing |
| 6 (accept)    | ✅ if *-UAT.md exists + verdict=ACCEPTED, ⬜ otherwise |

**In-progress detection (🔄):** the FIRST step that isn't ✅ and has partial work = currently active step for that phase. Exactly one step per phase can be 🔄.

**status_label:**
- `✅ DONE` if all 7 steps ✅
- `🔄 IN PROGRESS` if any 🔄
- `⏸ NOT STARTED` if step 0 is ⬜
- `❌ BLOCKED` if any ❌

**next_command:** use Step 5 mapping table (what command moves phase forward). `—` if DONE.

**Rendering rules:**
- Print blocks TOP-DOWN in phase-number order
- Do NOT collapse into a single table — each phase gets its own visual block so user can scan progress at a glance
- Include ALL phases from ROADMAP.md, even ones with step 0/7 (shows upcoming work)
</step>

<step name="4_display_detail">
**Show artifact detail — ONLY if `$ARGUMENTS` contains a specific phase number.**

Without a phase argument: Step 3's per-phase blocks are enough. Skip this step entirely.
With a phase argument: print this extra block AFTER the phase's overview block.

For the requested phase, show artifact detail:

```
### Phase {N}: {name}

Pipeline: ✅ specs → ✅ scope → ✅ blueprint → ✅ build → 🔄 review → ⬜ test → ⬜ accept

#### Artifacts
| Step | Artifact | Status | Detail |
|------|----------|--------|--------|
| 0 | SPECS.md | ✅ | Created |
| 1 | CONTEXT.md | ✅ | {N} decisions (D-01..D-{N}) |
| 2 | PLAN*.md | ✅ | {N} plans |
| 2 | API-CONTRACTS.md | ✅ | {N} endpoints |
| 2 | TEST-GOALS.md | ✅ | {N} goals ({critical}/{important}/{nice}) |
| 3 | SUMMARY*.md | ✅ | {N} summaries |
| 4 | RUNTIME-MAP.json | 🔄 | {N} views, {M} elements, {coverage}% |
| 4 | GOAL-COVERAGE-MATRIX.md | 🔄 | {ready}/{total} goals ready |
| 4 | scan-*.json | — | {N} Haiku scan results |
| 4 | probe-*.json | — | {N} probe results |
| 5 | SANDBOX-TEST.md | ⬜ | Not started |
| 6 | UAT.md | ⬜ | Not started |

#### CrossAI
- Results: {N} XML files in crossai/
- Latest: {filename} ({date})

#### Git Activity
- Recent commits: `git log --oneline -5 -- {phase_dir}`
- Files changed: `git diff --stat HEAD~10 -- apps/ packages/ | head -5`
```

**Status icons:**
- ✅ = complete (artifact exists and valid)
- 🔄 = in progress (artifact exists but phase not done)
- ⬜ = not started
- ❌ = failed/blocked
</step>

<step name="5_suggest_next">
**Suggest next action — ALWAYS use /vg:* commands. NEVER suggest /gsd-* or /gsd:* commands.**

**Step-to-command mapping (MANDATORY):**

| Current step (missing artifact) | Command to suggest |
|---|---|
| 0 (no SPECS.md) | `/vg:specs {phase}` |
| 1 (no CONTEXT.md) | `/vg:scope {phase}` |
| 2 (no PLAN*.md or API-CONTRACTS.md) | `/vg:blueprint {phase}` |
| 3 (no SUMMARY*.md) | `/vg:build {phase}` |
| 3b (SUMMARY exists, goals UNREACHABLE after review) | `/vg:build {phase} --gaps-only` |
| 4 (no RUNTIME-MAP.json) | `/vg:review {phase}` |
| 4b (gate BLOCK, goals failed) | `/vg:next {phase}` — auto-classifies UNREACHABLE vs BLOCKED |
| 5 (no SANDBOX-TEST.md) | `/vg:test {phase}` |
| 5b (test found gaps, need deeper UAT) | `/vg:test {phase}` or `/vg:accept {phase}` |
| 6 (no UAT.md or UAT incomplete) | `/vg:accept {phase}` |
| 7 (UAT complete, next phase exists) | `/vg:scope {next_phase}` after `/vg:specs {next_phase}` |
| 7 (all phases done) | `/vg:complete-milestone {M}` (close + archive); then `/vg:project --milestone` |

**Output format:**

```
#### What's Next

▶ `{command from table above}` — {one-line description tied to actual phase state}

Also available:
  - `/vg:phase {phase} --from={step}` — run remaining pipeline
  - `/vg:next` — auto-advance (runs immediately, handles BLOCK/UNREACHABLE routing)
  - `/vg:progress {phase}` — detail for specific phase
```

**Forbidden suggestions (common AI mistake — do NOT emit these):**
- ❌ `/gsd-plan-phase` → use `/vg:blueprint` instead
- ❌ `/gsd-verify-work` → use `/vg:test` or `/vg:accept` instead
- ❌ `/gsd-discuss-phase` → use `/vg:scope` instead
- ❌ `/gsd-execute-phase` → use `/vg:build` instead

If `$ARGUMENTS` contains a specific phase, show detail for that phase only.
If `$ARGUMENTS` contains `--all`, show detail for ALL phases (not just active).
</step>

</process>

<success_criteria>
- All phase directories scanned
- Artifact status accurately detected
- Progress bar visually clear
- Active phase identified
- Next action suggested (not auto-invoked)
- Works with both VG and cross-referenced RTB phases
</success_criteria>
