---
name: "vg-recover"
description: "Guided recovery for stuck/corrupted phases — classifies corruption type + prints safe recovery commands. Add --apply for assisted execution."
metadata:
  short-description: "Guided recovery for stuck/corrupted phases — classifies corruption type + prints safe recovery commands. Add --apply for assisted execution."
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

Invoke this skill as `$vg-recover`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `recovery (khôi phục)`, `corruption (hư hỏng)`, `manifest (kê khai)`, `stuck (tắc nghẽn)`, `hash mismatch (lệch băm)`, `rollback (quay lui)`, `artifact (tạo phẩm)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Suggest-only by default** — prints recovery commands. Does NOT execute anything destructive unless `--apply` + second user confirm.
2. **--apply requires AskUserQuestion confirm** — even safe helpers get a "proceed? yes/no" prompt before running.
3. **Phase arg mandatory** — `/vg:recover` without phase → exit 1 with usage hint.
4. **Delegate classification to `artifact_manifest_validate`** — exit code + stderr pattern selects recovery template.
5. **Never call `git reset --hard`, `rm -rf`, `git push --force`** — always print those as user-run commands, never execute.
6. **Emit single `recover_run` event** per invocation.
</rules>

<objective>
Answer: "How do I un-break phase X?"

Classifies corruption into 6 types (clean / legacy-no-manifest / manifest-self-corruption / missing-artifacts / hash-mismatch / unknown-corruption), maps each to a safe recovery template, and prints it. `--apply` mode runs ONLY non-destructive helpers (re-read triggers, progress checks) after confirm.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse args + load helpers

```bash
PLANNING_DIR=".vg"
PHASES_DIR="${PLANNING_DIR}/phases"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || {
  echo "⛔ artifact-manifest.sh missing — cannot classify corruption" >&2
  exit 1
}
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || true

PHASE_ARG=""
APPLY_FLAG=false
for arg in $ARGUMENTS; do
  case "$arg" in
    --apply) APPLY_FLAG=true ;;
    --*)     echo "⚠ Unknown flag: $arg" ;;
    *)       PHASE_ARG="$arg" ;;
  esac
done

if [ -z "$PHASE_ARG" ]; then
  echo "⛔ /vg:recover requires {phase} argument"
  echo "   Usage: /vg:recover 07.12 [--apply]"
  echo "   Scan corrupted phases first: /vg:integrity"
  exit 1
fi

export VG_CURRENT_COMMAND="vg:recover"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "🔧 ━━━ /vg:recover — phase ${PHASE_ARG} ━━━"
[ "$APPLY_FLAG" = "true" ] && echo "   Mode: --apply (will prompt before safe helpers)"
[ "$APPLY_FLAG" = "false" ] && echo "   Mode: suggest-only (prints commands, runs nothing)"
echo ""

# Resolve phase dir
phase_dir=""
for d in "${PHASES_DIR}"/*; do
  [ -d "$d" ] || continue
  base=$(basename "$d")
  if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
    phase_dir="$d"; break
  fi
done

if [ -z "$phase_dir" ]; then
  echo "⛔ Phase ${PHASE_ARG} not found. Run /vg:health to list phases."
  exit 1
fi
```
</step>

<step name="1_classify">
## Step 1: Classify corruption type

```bash
echo "## Detecting corruption type"
echo ""

corruption_type="unknown"
corruption_detail=""

val_output=$(artifact_manifest_validate "$phase_dir" 2>&1)
val_rc=$?
case $val_rc in
  0)
    corruption_type="clean"
    corruption_detail="Manifest valid. No file-level corruption."
    ;;
  1)
    corruption_type="legacy-no-manifest"
    corruption_detail="Missing .artifact-manifest.json (legacy phase)."
    ;;
  2)
    if echo "$val_output" | grep -q "ARTIFACT MISSING"; then
      corruption_type="missing-artifacts"
    elif echo "$val_output" | grep -q "ARTIFACT CORRUPTION"; then
      corruption_type="hash-mismatch"
    elif echo "$val_output" | grep -q "MANIFEST CORRUPTION"; then
      corruption_type="manifest-self-corruption"
    else
      corruption_type="unknown-corruption"
    fi
    corruption_detail="$val_output"
    ;;
esac

# Pipeline staleness check
stuck="no"
pipeline_state="${phase_dir}/PIPELINE-STATE.json"
if [ -f "$pipeline_state" ]; then
  stuck=$(${PYTHON_BIN} - "$pipeline_state" <<'PY' 2>/dev/null
import json, sys, os, datetime
try:
  s = json.loads(open(sys.argv[1], encoding='utf-8').read())
  mtime = os.path.getmtime(sys.argv[1])
  age_hours = (datetime.datetime.now().timestamp() - mtime) / 3600
  last_step = s.get("last_step") or s.get("current_step") or "?"
  if age_hours > 24 and last_step not in ("accept", "done"):
    print(f"stuck@{last_step}(age {int(age_hours)}h)")
  else:
    print("no")
except:
  print("no")
PY
)
fi

echo "  Type:     **${corruption_type}**"
[ "$stuck" != "no" ] && echo "  Pipeline: ${stuck}"
echo ""
[ -n "$corruption_detail" ] && echo "$corruption_detail" | sed 's/^/  /'
echo ""
```
</step>

<step name="2_suggest">
## Step 2: Print recovery template for classified type

```bash
echo "## Suggested recovery commands"
echo ""
case "$corruption_type" in
  clean)
    echo "  ✓ No corruption. Nothing to recover."
    if [ "$stuck" != "no" ]; then
      echo "  Pipeline appears ${stuck}:"
      echo "    /vg:next ${PHASE_ARG}       # auto-advance to next step"
      echo "    /vg:progress ${PHASE_ARG}   # inspect current state"
    fi
    ;;
  legacy-no-manifest)
    echo "  Manifest auto-backfills on next read (no action required)."
    echo "  Force explicit backfill:"
    echo "    /vg:progress ${PHASE_ARG}"
    ;;
  manifest-self-corruption)
    echo "  Manifest file tampered/corrupted. Regenerate via the producer command:"
    echo "    /vg:blueprint ${PHASE_ARG}   # if PLAN/CONTRACTS/TEST-GOALS exist"
    echo "    /vg:review ${PHASE_ARG}      # if RUNTIME-MAP exists"
    ;;
  missing-artifacts)
    echo "  Files referenced by manifest are gone. Choose one:"
    echo "    /vg:blueprint ${PHASE_ARG}   # regenerate from scratch"
    echo "    git checkout HEAD -- ${phase_dir}/   # restore from last commit"
    ;;
  hash-mismatch)
    echo "  Artifact content changed after manifest write (manual edit suspected)."
    echo "  Option 1 — keep edits, refresh manifest:"
    echo "    /vg:blueprint ${PHASE_ARG}"
    echo "  Option 2 — revert to manifest version:"
    echo "    git checkout ${phase_dir}/"
    ;;
  unknown-corruption|unknown)
    echo "  Could not classify. Manual inspection:"
    echo "    cat ${phase_dir}/.artifact-manifest.json"
    echo "    /vg:health ${PHASE_ARG}   # deep phase inspection"
    ;;
esac
echo ""
```
</step>

<step name="3_apply">
## Step 3 (--apply only): Run SAFE helpers after confirm

Only non-destructive helpers are auto-runnable. Destructive ops (`git checkout`, regeneration that overwrites) always require user to run manually.

```bash
if [ "$APPLY_FLAG" = "true" ]; then
  echo "## --apply mode"
  echo ""

  case "$corruption_type" in
    legacy-no-manifest)
      echo "  Safe helper available: trigger manifest backfill via /vg:progress."
      echo "  This is a read-only command; it will not modify any artifacts."
      ;;
    clean)
      if [ "$stuck" != "no" ]; then
        echo "  Safe helper available: /vg:next ${PHASE_ARG} to auto-advance."
      else
        echo "  Nothing to apply — state is clean."
        exit 0
      fi
      ;;
    *)
      echo "  ⚠ --apply is NOT safe for corruption type '${corruption_type}'."
      echo "  Destructive ops (git checkout, regeneration) must be run manually."
      echo "  See suggested commands above."
      exit 0
      ;;
  esac

  echo ""
  echo "  Proceed with safe helper? (use AskUserQuestion to confirm)"
  echo "  [This block would invoke AskUserQuestion with yes/no options.]"
  # Actual AskUserQuestion invocation happens in the caller model, not shell.
  # Shell output signals the model to prompt the user.
fi
```

When `--apply` mode is engaged AND corruption type is `legacy-no-manifest` or `clean+stuck`, the outer model SHOULD:
1. Call `AskUserQuestion` with "Proceed with safe helper X?" question.
2. On "yes" → invoke the appropriate read-only command via Skill tool (`vg:progress` or `vg:next`).
3. On "no" → print "Aborted. No action taken." and exit.
</step>

<step name="4_telemetry">
## Step 4: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  payload="{\"type\":\"${corruption_type}\",\"stuck\":\"${stuck}\",\"apply\":${APPLY_FLAG}}"
  emit_telemetry_v2 "recover_run" "${PHASE_ARG}" "recover.${corruption_type}" \
    "" "PASS" "$payload" >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Suggest-only by default — no destructive ops execute without `--apply` + user confirm.
- 6 corruption types mapped to distinct recovery templates.
- Delegates classification to `artifact_manifest_validate`.
- `--apply` mode restricted to non-destructive helpers.
- Single `recover_run` telemetry event.
</success_criteria>
</content>
</invoke>
