---
name: "vg-design-system"
description: "Design system lifecycle — browse/import/create/view/edit DESIGN.md (58 brand variants from getdesign.md ecosystem)"
metadata:
  short-description: "Design system lifecycle — browse/import/create/view/edit DESIGN.md (58 brand variants from getdesign.md ecosystem)"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
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

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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

Invoke this skill as `$vg-design-system`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Multi-design support** — project may have multiple design systems per role (SSP admin, DSP admin, Publisher, Advertiser). Use `--role=<name>` to target role-specific design.
2. **Pre-paywall source** — fetches from `Meliwat/awesome-design-md-pre-paywall` (free). Official `VoltAgent/awesome-design-md` moved content behind getdesign.md paywall.
3. **File convention** — project-level: `${PLANNING_DIR}/design/DESIGN.md`. Role-level: `${PLANNING_DIR}/design/{role}/DESIGN.md`. Phase-override: `${PLANNING_DIR}/phases/XX/DESIGN.md`.
4. **Resolution priority (highest first)** — phase > role > project > none.
5. **Idempotent** — running `--import` twice downloads again (brand files may be updated upstream).
</rules>

<objective>
Manage DESIGN.md files for UI standardization. Integrates with scope Round 4 (UI discussion), build (inject into UI task prompts), review (token validation).

Modes:
- `--browse` — list available 58 brand design systems grouped by category
- `--import <brand>` — download brand DESIGN.md to project/role location
- `--create` — guided discussion to build custom DESIGN.md
- `--view [--role=<name>]` — print current DESIGN.md content
- `--edit [--role=<name>]` — open editor to modify (delegates to $EDITOR)
- `--validate [--scan=<path>]` — check code tokens vs DESIGN.md palette
</objective>

<process>

**Config:** Source `.claude/commands/vg/_shared/lib/design-system.sh` first.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh"
```

<step name="0_parse_args">
## Step 0: Parse arguments

Parse flags from `$ARGUMENTS`:

```bash
MODE=""
BRAND=""
ROLE=""
SCAN_PATH="apps/web/src"

for arg in $ARGUMENTS; do
  case "$arg" in
    --browse)         MODE="browse" ;;
    --import=*|-i=*)  MODE="import"; BRAND="${arg#*=}" ;;
    --import|-i)      MODE="import" ;;  # followed by positional brand
    --create)         MODE="create" ;;
    --view)           MODE="view" ;;
    --edit)           MODE="edit" ;;
    --validate)       MODE="validate" ;;
    --role=*)         ROLE="${arg#*=}" ;;
    --scan=*)         SCAN_PATH="${arg#*=}" ;;
    *)
      # Positional: brand name after --import
      if [ "$MODE" = "import" ] && [ -z "$BRAND" ]; then
        BRAND="$arg"
      fi
      ;;
  esac
done

# Default mode if none specified
[ -z "$MODE" ] && MODE="browse"
```

**If mode unknown → BLOCK:**
```
Usage: /vg:design-system [--browse | --import <brand> | --create | --view | --edit | --validate] [--role=<name>]
```
</step>

<step name="1_dispatch">
## Step 1: Dispatch mode

### Mode: `browse`

List all 58 available brands, grouped by category. User can pick one to import next.

```bash
design_system_browse_grouped
echo ""
echo "To import a brand:"
echo "  /vg:design-system --import stripe              # → ${PLANNING_DIR}/design/DESIGN.md (project-level)"
echo "  /vg:design-system --import linear --role=ssp   # → ${PLANNING_DIR}/design/ssp/DESIGN.md (role-level)"
```

### Mode: `import`

Download brand DESIGN.md to target path.

```bash
if [ -z "$BRAND" ]; then
  echo "⛔ Brand not specified. Usage: /vg:design-system --import <brand>"
  echo "   Run /vg:design-system --browse to see available brands."
  exit 1
fi

# Determine target path
if [ -n "$ROLE" ]; then
  TARGET="${CONFIG_DESIGN_SYSTEM_ROLE_DIR:-${PLANNING_DIR}/design}/${ROLE}/DESIGN.md"
else
  TARGET="${CONFIG_DESIGN_SYSTEM_PROJECT_LEVEL:-${PLANNING_DIR}/design/DESIGN.md}"
fi

# Confirm if target exists
if [ -f "$TARGET" ]; then
  echo "⚠ Target exists: $TARGET"
  # Orchestrator should AskUserQuestion: overwrite / backup+replace / cancel
fi

design_system_fetch "$BRAND" "$TARGET"
echo ""
echo "✓ Imported $BRAND design system."
echo "  Next: /vg:design-system --view${ROLE:+ --role=$ROLE}"
echo "  Or:   /vg:scope {phase}  (Round 4 will auto-detect this DESIGN.md)"
```

### Mode: `create`

Guided discussion to build custom DESIGN.md. Orchestrator asks user 8 questions covering:

1. **Brand personality** — adjectives (modern/classic/playful/technical/luxurious/...) + 2-3 brand references
2. **Primary color** — hex code OR description ("deep purple like Stripe")
3. **Typography** — serif/sans/mono primary, optional secondary
4. **Border radius style** — sharp (0-2px) / subtle (4-6px) / rounded (8-12px) / pill (full)
5. **Shadow style** — flat / layered / colored / none
6. **Spacing scale** — compact (4/8/12/16) / standard (4/8/16/24/32) / generous (8/16/32/48/64)
7. **Motion** — instant / subtle (150ms) / smooth (300ms) / theatrical (500ms+)
8. **Component style** — minimal / standard / decorated

After Q&A, orchestrator generates DESIGN.md via template with 5 sections (Visual Theme, Color Palette, Typography, Spacing, Components) populated from user answers. Writes to target path based on `$ROLE`.

### Mode: `view`

Print current DESIGN.md content. Resolve via priority order.

```bash
# Phase not specified → resolve project/role level only
DESIGN_PATH=$(design_system_resolve "" "$ROLE")

if [ -z "$DESIGN_PATH" ]; then
  echo "⚠ No DESIGN.md found for role='${ROLE:-<project>}'"
  echo "  Import one: /vg:design-system --import <brand>${ROLE:+ --role=$ROLE}"
  echo "  Or browse:  /vg:design-system --browse"
  exit 0
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  DESIGN.md at: $DESIGN_PATH"
echo "═══════════════════════════════════════════════════════════════"
cat "$DESIGN_PATH"
```

### Mode: `edit`

Open file in editor. Fallback: print path for user to edit manually.

```bash
DESIGN_PATH=$(design_system_resolve "" "$ROLE")
if [ -z "$DESIGN_PATH" ]; then
  echo "⛔ No DESIGN.md to edit. Import first: /vg:design-system --import <brand>${ROLE:+ --role=$ROLE}"
  exit 1
fi

if [ -n "$EDITOR" ]; then
  "$EDITOR" "$DESIGN_PATH"
else
  echo "Edit manually: $DESIGN_PATH"
  echo "After edit, run: /vg:design-system --validate  (to check tokens match code)"
fi
```

### Mode: `validate`

Scan code for hex codes, compare against DESIGN.md palette. Report drift.

```bash
design_system_validate_tokens "" "$SCAN_PATH" "$ROLE"
```

Non-blocking — warns but doesn't exit 1. Invoked during `/vg:review` Phase 2.5.
</step>

<step name="2_config_loader">
## Step 2: Auto-populate config on first run

If `.claude/vg.config.md` lacks `design_system:` section, emit hint:

```bash
if ! grep -qE "^design_system:" .claude/vg.config.md; then
  echo ""
  echo "⚠ design_system: section missing from vg.config.md"
  echo "  Add this block to enable full integration:"
  cat <<'EOF'

design_system:
  enabled: true
  source_repo: "Meliwat/awesome-design-md-pre-paywall"
  project_level: "${PLANNING_DIR}/design/DESIGN.md"
  role_dir: "${PLANNING_DIR}/design"
  phase_override_pattern: "{phase_dir}/DESIGN.md"
  inject_on_build: true
  validate_on_review: true

EOF
fi
```
</step>

</process>

<success_criteria>
- `--browse` lists 58 brands grouped into 9 categories
- `--import <brand>` downloads to correct path (phase/role/project)
- `--view` resolves correctly by priority (phase > role > project)
- `--validate` scans CSS/TSX, reports hex drift vs DESIGN.md
- Config section auto-hinted if missing
- All operations idempotent (re-running safe)
</success_criteria>
