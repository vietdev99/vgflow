---
name: "vg-design-scaffold"
description: "Scaffold UI mockups for greenfield projects — multi-tool selector (Pencil MCP / PenBoard MCP / AI HTML / Claude design / Stitch / v0 / Figma / manual). Output drops into the phase-local design directory for /vg:design-extract."
metadata:
  short-description: "Scaffold UI mockups for greenfield projects — multi-tool selector (Pencil MCP / PenBoard MCP / AI HTML / Claude design / Stitch / v0 / Figma / manual). Output drops into the phase-local design directory for /vg:design-extract."
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

Invoke this skill as `$vg-design-scaffold`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Greenfield on-ramp** — closes the upstream gap exposed by Phase 19. Without scaffold, projects with zero mockups bypass every L1-L6 gate via Form B.
2. **Tool selector** — user-driven via AskUserQuestion or `--tool=<name>` flag. Default recommendation: `pencil-mcp` (free + automated + binary output ideal for downstream gates).
3. **Files converge** — every tool produces files at `$(vg_resolve_design_dir "$PHASE_DIR" phase)/<slug>.{ext}` so `/vg:design-extract` and `/vg:build` resolve the same phase-local assets.
4. **Bulk by default** — multi-page generation in one call; `--interactive` flag opts into per-page review pause.
5. **Auto-regen on DESIGN.md change** — scaffold caches by DESIGN.md SHA256; mockups regenerated when tokens drift.
6. **Idempotent** — re-running with same args + same DESIGN.md = no-op. `--refresh` forces re-scaffold.
7. **No replacement of /vg:design-system** — orthogonal: design-system manages tokens (DESIGN.md), scaffold consumes them.
</rules>

<objective>
Generate UI mockup files for every page in ROADMAP.md so `/vg:design-extract` has assets to normalize. Output:
  ${PHASE_DIR}/design/<slug>.{pen|html|png|fig}           ← per tool
  ${PHASE_DIR}/.scaffold-evidence/{slug}.json            ← per-page provenance (tool, hash, generated_at)
</objective>

<available_agent_types>
- general-purpose — Opus for Pencil MCP (D-02) + AI HTML (D-03) generation
</available_agent_types>

<process>

**Config:** Source `.claude/commands/vg/_shared/lib/design-system.sh` first to read design_assets paths + DESIGN.md location.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh" 2>/dev/null || true
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-path-resolver.sh" 2>/dev/null || true
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/scaffold-discovery.sh" 2>/dev/null || true
```

<step name="0_validate_prereqs">
## Step 0: Validate prerequisites

```bash
if type -t vg_resolve_design_dir >/dev/null 2>&1; then
  DESIGN_ASSETS_DIR=$(vg_resolve_design_dir "$PHASE_DIR" phase)
else
  DESIGN_ASSETS_DIR="${PHASE_DIR}/design"
fi
DESIGN_MD_PATH="${PLANNING_DIR}/design/DESIGN.md"

# Need at least one of: ROADMAP page list (preferred) OR current PHASE PLAN
ROADMAP="${PLANNING_DIR}/ROADMAP.md"
PLAN_GLOB="${PHASE_DIR}/PLAN*.md"

# Check DESIGN.md presence (not blocking — scaffold can run without tokens
# but quality drops; prompt user to run /vg:design-system first when missing)
if [ ! -f "$DESIGN_MD_PATH" ] && [ ! -f "${PHASE_DIR}/DESIGN.md" ]; then
  echo "⚠ Không thấy DESIGN.md (tokens). Mockups sẽ generic hơn — cân nhắc:"
  echo "    /vg:design-system --browse   (chọn brand từ 58 variants)"
  echo "    /vg:design-system --create   (tạo custom)"
  AskUserQuestion: "Continue scaffold without DESIGN.md? [y/N]"
fi

mkdir -p "$DESIGN_ASSETS_DIR" "${PHASE_DIR}/.scaffold-evidence"
```

If neither ROADMAP nor PLAN exists → BLOCK: "Run /vg:roadmap or /vg:specs first to define page list."
</step>

<step name="1_extract_page_list">
## Step 1: Extract page list

Build the list of pages to scaffold:

1. **Priority order:**
   - `--pages=slug1,slug2,...` flag → use as-is
   - PHASE_DIR PLAN tasks with `<design-ref>SLUG</design-ref>` (Form A only)
   - ROADMAP.md `<page>` declarations
   - Fallback: prompt user to type page list

2. **For each page**, derive metadata from PLAN/ROADMAP:
   - `slug` (kebab-case)
   - `description` (1-line, from task body or page section)
   - `type` (list / form / dashboard / wizard / detail / landing — auto-classify by description regex; user override via interactive prompt)

Write to `${PHASE_DIR}/.tmp/scaffold-pages.json`:

```json
{"pages": [{"slug": "home-dashboard", "description": "...", "type": "dashboard"}, ...]}
```
</step>

<step name="2_check_existing_assets">
## Step 2: Check existing assets

```bash
EXISTING=$(find "$DESIGN_ASSETS_DIR" -maxdepth 2 -type f \
  \( -name "*.pen" -o -name "*.html" -o -name "*.png" -o -name "*.fig" -o -name "*.penboard" \) 2>/dev/null | wc -l)
```

If $EXISTING > 0:
- Match each existing file basename against page list slugs.
- Pages with matching file → SKIP (already have mockup).
- Pages without → continue to scaffold.
- If `--refresh` flag → ignore existing, scaffold all.

**Auto-regen check (Q3 = A):** for each existing mockup file, compare its scaffold-evidence entry's `design_md_sha256` field against current DESIGN.md SHA256.
- Mismatch → mark page as "stale", scaffold again.
- Match → skip.
- No evidence file (manually-added mockup) → leave alone (not scaffold-managed).

Display:
```
Pages to scaffold: <N>
Pages skipped (exists, fresh): <M>
Pages stale (DESIGN.md changed): <K>
Pages new: <P>
```
</step>

<step name="3_tool_selector">
## Step 3: Tool selector

If `--tool=<name>` flag → validate name in {pencil-mcp, penboard-mcp, ai-html, claude-design, stitch, v0, figma, manual-html, sketch} and skip prompt.

Else AskUserQuestion with decision matrix:

```
Pages to scaffold: <N>. DESIGN.md: <yes|no>. Recommended: pencil-mcp (auto, free).

Pick a tool:
  [a] pencil-mcp     — Pencil MCP automated (DEFAULT). Output .pen via mcp__pencil__batch_design.
  [b] penboard-mcp   — PenBoard MCP automated (Wave B). Multi-page workspace.
  [c] ai-html        — Claude writes HTML+Tailwind from DESIGN.md tokens. Cheap, inspectable.
  [d] claude-design  — gstack:design-shotgun variants → comparison board → user picks (Wave B).
  [e] stitch         — Google Stitch (manual export). Best aesthetic, no API.
  [f] v0             — Vercel v0 (manual export, paid). React-first.
  [g] figma          — Figma (manual export). Industry standard for designer teams.
  [h] manual-html    — You write HTML mockups by hand. Trivial integration.
  [i] sketch         — Sketch.app (macOS only). Mobile-friendly artboard presets (Wave C D-13).
  [help]             — print full decision matrix + trade-offs.
```

Save choice as `$TOOL` env var.

`--interactive` flag (Q2 = C) is forwarded to tool sub-flow as `INTERACTIVE_MODE=1` env var.
</step>

<step name="4_per_tool_dispatch">
## Step 4: Per-tool dispatch

```bash
case "$TOOL" in
  pencil-mcp)    SCAFFOLD_LIB="scaffold-pencil.sh" ;;
  penboard-mcp)  SCAFFOLD_LIB="scaffold-penboard.sh" ;;     # Wave B stub
  ai-html)       SCAFFOLD_LIB="scaffold-ai-html.sh" ;;
  claude-design) SCAFFOLD_LIB="scaffold-claude-design.sh" ;;# Wave B stub
  stitch)        SCAFFOLD_LIB="scaffold-stitch.sh" ;;
  v0)            SCAFFOLD_LIB="scaffold-v0.sh" ;;
  figma)         SCAFFOLD_LIB="scaffold-figma.sh" ;;
  manual-html)   SCAFFOLD_LIB="scaffold-manual.sh" ;;
  sketch)        SCAFFOLD_LIB="scaffold-sketch.sh" ;;        # Wave C D-13
  *) echo "⛔ Unknown tool: $TOOL"; exit 1 ;;
esac

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/${SCAFFOLD_LIB}"
scaffold_run \
  --pages-json "${PHASE_DIR}/.tmp/scaffold-pages.json" \
  --output-dir "${DESIGN_ASSETS_DIR}" \
  --design-md "${DESIGN_MD_PATH}" \
  --evidence-dir "${PHASE_DIR}/.scaffold-evidence"
```

Each `scaffold-*.sh` lib exposes `scaffold_run` with the same args. See per-tool sub-flow specs in the Phase 20 SPECS.md (D-02 through D-04).
</step>

<step name="5_validate_output">
## Step 5: Validate output

```bash
MISSING=()
for slug in "${PAGE_SLUGS[@]}"; do
  found=0
  for ext in pen html png fig penboard; do
    if [ -f "${DESIGN_ASSETS_DIR}/${slug}.${ext}" ]; then
      found=1
      break
    fi
  done
  [ $found -eq 0 ] && MISSING+=("$slug")
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "⛔ Scaffold incomplete — missing files for: ${MISSING[*]}"
  echo "   Tool: $TOOL. Re-run /vg:design-scaffold --tool=$TOOL --pages=${MISSING[*]}"
  exit 1
fi
```

Write per-page evidence:

```json
{
  "slug": "home-dashboard",
  "tool": "pencil-mcp",
  "file": "${PHASE_DIR}/design/home-dashboard.pen",
  "design_md_sha256": "<sha256 of DESIGN.md at scaffold time>",
  "generated_at": "2026-04-28T12:34:56Z",
  "interactive_mode": false
}
```
</step>

<step name="6_auto_extract">
## Step 6: Auto-fire /vg:design-extract

```
SlashCommand: /vg:design-extract --auto
```

Verify `manifest.json` updated with all expected slugs. If any missing → fail loud with diagnostic.
</step>

<step name="7_resume_pipeline">
## Step 7: Resume pipeline

```
Scaffold complete.
  Tool used:        $TOOL
  Pages generated:  <N>
  Pages skipped:    <M>
  Output dir:       $DESIGN_ASSETS_DIR
  Evidence:         ${PHASE_DIR}/.scaffold-evidence/

Next: /vg:blueprint ${PHASE_NUMBER}  (or /vg:phase to continue full pipeline)
```

Mark step + emit telemetry `design_scaffold.completed`.
</step>

</process>

<help_tools_matrix>
# Decision matrix (--help-tools)

| Tool | Auto | Cost/page | Output | Best for |
|---|---|---|---|---|
| **pencil-mcp** (DEFAULT) | ✅ | ~$0.15 Opus | `.pen` binary | Solo dev, in-pipeline, token-faithful |
| penboard-mcp | ✅ Wave B | ~$0.20 Opus | `.penboard` workspace | Multi-page nav-aware (Wave B) |
| **ai-html** | ✅ | ~$0.05 Opus | `.html` Tailwind | DESIGN.md + cheap; hand-editable |
| claude-design | 🟡 Wave B | ~$0.30 (variants) | `.html` | Visual exploration, design-shotgun pattern |
| stitch | 🔴 manual | free 350/mo | `.html` (export) | Best aesthetic; willing to manual export |
| v0 | 🔴 manual | paid Vercel | `.html` React | React shop, has v0 sub |
| figma | 🔴 manual | varies | `.png` (export) | Designer-team, Figma-native |
| manual-html | trivial | $0 | `.html` | Existing hand-written mockups |
| **sketch** | 🔴 manual | $9/mo Sketch sub | `.png` (export 2x) | Mobile-friendly (iOS/Android artboards), macOS only |

</help_tools_matrix>

<success_criteria>
- Page list resolved from PLAN/ROADMAP/--pages
- Tool picked (interactive or flag)
- Per-tool sub-flow produced files at $DESIGN_ASSETS_DIR
- Validation passes (every requested page has a file)
- Evidence written per page
- /vg:design-extract auto-fired and manifest.json populated
- Telemetry events emitted (started + completed)
</success_criteria>
</process>
