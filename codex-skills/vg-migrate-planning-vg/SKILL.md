---
name: "vg-migrate-planning-vg"
description: "Migrate .planning/ → .vg/ (VG canonical path). Idempotent — re-run scans + updates. Skips GSD-owned files."
metadata:
  short-description: "Migrate .planning/ → .vg/ (VG canonical path). Idempotent — re-run scans + updates. Skips GSD-owned files."
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

Invoke this skill as `$vg-migrate-planning-vg`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Idempotent** — safe to re-run. Compares hashes, only updates changed files.
2. **Comprehensive** — walks ALL files in .planning/. Doesn't silently skip unknowns.
3. **GSD-aware** — auto-classifies and SKIPS GSD-owned files (debug/, quick/, research/, codebase/, *.gsd, gsd-* paths).
4. **User-edit safe** — if target file in .vg/ has been user-edited since last migration, creates `.user-edit.<ts>` backup before overwriting.
5. **Default keep-original** — `.planning/` preserved by default. Use `--no-keep` to delete after successful migration.
6. **Dry-run first** — always preview before applying when in doubt.
</rules>

<objective>
Migrate VG-owned artifacts từ legacy `.planning/` → canonical `.vg/`. GSD continues using `.planning/`. After migration, all VG commands read/write `.vg/` (per `paths.planning_dir` config).

Modes:
- `--dry-run` — preview classification + actions, no files written
- `--no-keep` — delete `.planning/` after successful migration (default: keep)
- `--source=<path>` — override source (default `.planning`)
- `--target=<path>` — override target (default `.vg`)
- `--auto-promote` (v1.14.2+) — promote `.vg/_legacy/_extractions/*.extracted.md` → `.vg/` proper slot using deterministic name-based rules. Never overwrites existing `.vg/` content. Adds banner for review.
- `--full-auto` (v1.14.2+) — run migrate + auto-promote + verify-convergence in one pass. Short-circuit end-to-end.
- `--archive-planning` (v1.14.2+) — after successful migrate+promote+verify, tar.gz `.planning/` → `.vg/_archives/planning-{ts}.tar.gz` then remove `.planning/`. Safer than `--no-keep` (preserves evidence). Compose with `--full-auto`.

Idempotent — running multiple times is SAFE and EXPECTED:
- New files in source → copied to target
- Changed files in source → updated in target (with backup if user edited)
- Already-synced files → no-op
- GSD files → skipped consistently

Convergence guarantee (`--full-auto` only):
- After migrate + promote, dry-run re-check MUST produce 0 NEW + 0 UPDATED
- If not converged, command exits non-zero (signals drift somewhere)
</objective>

<process>

**Source:**
```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/planning-migrator.sh"
```

<step name="0_parse">
Parse flags from `$ARGUMENTS`:
```bash
ARGS=""
FULL_AUTO=false
AUTO_PROMOTE=false
for arg in $ARGUMENTS; do
  case "$arg" in
    --dry-run|--no-keep|--source=*|--target=*) ARGS="$ARGS $arg" ;;
    --full-auto) FULL_AUTO=true ;;
    --auto-promote) AUTO_PROMOTE=true ;;
  esac
done
```
</step>

<step name="1_run">
Three modes:

**(A) Full-auto (v1.14.2+ NEW):** migrate → promote → verify in one pass.
```bash
if [ "$FULL_AUTO" = "true" ]; then
  planning_migrator_full_auto $ARGS
  # Exit here — full_auto handles everything including commit suggestion
  exit $?
fi
```

**(B) Migrate + promote (without full verify):**
```bash
if [ "$AUTO_PROMOTE" = "true" ]; then
  planning_migrator_run $ARGS
  # Run promote AFTER migrate completes
  DRY_RUN_FLAG=false
  [[ "$ARGS" =~ --dry-run ]] && DRY_RUN_FLAG=true
  planning_migrator_promote_extractions $DRY_RUN_FLAG
fi
```

**(C) Classic (migrate only):**
```bash
if [ "$FULL_AUTO" != "true" ] && [ "$AUTO_PROMOTE" != "true" ]; then
  planning_migrator_run $ARGS
fi
```

Output shows per-file classification + final summary table.
</step>

<step name="2_post_migration_config">
After successful migration, update vg.config.md to point at `.vg`:

```bash
if [ ! -f ".claude/vg.config.md" ]; then
  echo "⚠ No vg.config.md — skipping config update"
  exit 0
fi

if grep -qE "^\s*planning_dir:\s*\".vg\"" .claude/vg.config.md; then
  echo "✓ Config already points at .vg"
else
  ${PYTHON_BIN:-python3} -c "
import re
p = '.claude/vg.config.md'
txt = open(p, encoding='utf-8').read()
# Update or insert paths.planning_dir
if re.search(r'^paths:\s*\n', txt, re.M):
    if re.search(r'planning_dir:', txt):
        txt = re.sub(r'(planning_dir:)\s*\"[^\"]*\"', r'\1 \".vg\"', txt)
    else:
        txt = re.sub(r'(^paths:\s*\n)', r'\\1  planning_dir: \".vg\"\\n', txt, flags=re.M)
else:
    txt += '\\n# v1.12.0 — paths.planning_dir set via /vg:migrate-planning-vg\\npaths:\\n  planning_dir: \".vg\"\\n'
open(p, 'w', encoding='utf-8').write(txt)
print('✓ vg.config.md updated: paths.planning_dir = .vg')
"
fi
```
</step>

<step name="3_summary">
Display next-steps:
```
Migration complete. .vg/ is now canonical for VG workflow.

Next:
- All VG commands now read .vg/ (auto-detected via config)
- .planning/ preserved (used by GSD if installed)
- Re-run /vg:migrate-planning-vg anytime to sync new .planning/ → .vg/
- After confirming .vg/ is correct, optionally delete .planning/:
    /vg:migrate-planning-vg --no-keep
```
</step>

</process>

<success_criteria>
- All non-GSD files in .planning/ present in .vg/
- GSD files (*.gsd, debug/, quick/, research/, codebase/) skipped
- Hash equality between corresponding source/target files
- Re-run produces 0 NEW + 0 UPDATED (idempotent)
- vg.config.md `paths.planning_dir: ".vg"` set
- User edits in .vg/ preserved via .user-edit.<ts> backup
</success_criteria>
