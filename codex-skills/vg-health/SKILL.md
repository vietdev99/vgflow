---
name: "vg-health"
description: "Project health check — per-phase manifest status, last command, override pressure, drift register. Pass {phase} for deep inspection."
metadata:
  short-description: "Project health check — per-phase manifest status, last command, override pressure, drift register. Pass {phase} for deep inspection."
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

Invoke this skill as `$vg-health`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Use markdown headers in text output (e.g. `## ━━━ Scanning phases ━━━`). Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Tham khảo `_shared/term-glossary.md`. Ví dụ: `manifest (kê khai)`, `override (bỏ qua)`, `debt (nợ kỹ thuật)`, `drift (lệch hướng)`, `pipeline (đường ống)`, `telemetry (đo đạc)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Read-only** — never writes, never deletes, no git ops. Pure state inspection.
2. **Summary vs deep** — no arg = project-wide summary table. `{phase}` arg = deep inspection of that phase.
3. **Delegate to shared helpers** — reuse `artifact_manifest_validate`, `telemetry_warn_overrides`, `telemetry_query`.
4. **Graceful degradation** — missing manifest/telemetry/register → WARN line + continue. Exit 1 only on bad args.
5. **No telemetry pollution** — at most one `health_run` event emitted per invocation.
</rules>

<objective>
Answer two questions without raw-log parsing:
1. **Is the project healthy overall?** (summary mode — all phases)
2. **Why is phase X stuck?** (deep mode — one phase)

Pretty-printer on top of shared helpers. No corruption repair — that lives in `/vg:recover`.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse + load helpers

```bash
PLANNING_DIR=".vg"
PHASES_DIR="${PLANNING_DIR}/phases"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
DEBT_REGISTER="${PLANNING_DIR}/OVERRIDE-DEBT.md"
DRIFT_REGISTER="${PLANNING_DIR}/DRIFT-REGISTER.md"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || \
  echo "⚠ artifact-manifest.sh missing — integrity checks will degrade" >&2
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || \
  echo "⚠ telemetry.sh missing — event logging disabled" >&2

PHASE_ARG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --*) echo "⚠ Unknown flag: $arg (use /vg:gate-stats, /vg:integrity, /vg:recover instead)" ;;
    *)   PHASE_ARG="$arg" ;;
  esac
done

MODE="summary"
[ -n "$PHASE_ARG" ] && MODE="deep"

export VG_CURRENT_COMMAND="vg:health"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "🩺 ━━━ /vg:health — ${MODE} ━━━"
echo ""
```
</step>

<step name="1_summary">
## Step 1 (mode=summary): Project overview table

```bash
if [ "$MODE" = "summary" ]; then
  echo "## Project health overview"
  echo ""

  PHASE_DIRS=()
  if [ -d "$PHASES_DIR" ]; then
    while IFS= read -r d; do
      [ -d "$d" ] && PHASE_DIRS+=("$d")
    done < <(find "$PHASES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
  fi

  if [ ${#PHASE_DIRS[@]} -eq 0 ]; then
    echo "⚠ No phases found. Run /vg:roadmap hoặc /vg:add-phase."
  else
    echo "| Phase | Manifest | Last command | Unresolved overrides | Recommended action |"
    echo "|-------|----------|--------------|----------------------|--------------------|"

    for phase_dir in "${PHASE_DIRS[@]}"; do
      phase_name=$(basename "$phase_dir")
      phase_num=$(echo "$phase_name" | grep -oE '^[0-9.]+')

      manifest_status="?"
      if type artifact_manifest_validate >/dev/null 2>&1; then
        artifact_manifest_validate "$phase_dir" >/dev/null 2>&1
        case $? in
          0) manifest_status="✓ valid" ;;
          1) manifest_status="⚠ legacy" ;;
          2) manifest_status="⛔ corruption" ;;
        esac
      fi

      last_cmd="—"
      if [ -f "$TELEMETRY_PATH" ]; then
        last_cmd=$(${PYTHON_BIN} - "$TELEMETRY_PATH" "$phase_num" <<'PY' 2>/dev/null
import json, sys
path, phs = sys.argv[1], sys.argv[2]
last = None
try:
  for line in open(path, encoding='utf-8'):
    try:
      ev = json.loads(line)
      if ev.get("phase") == phs: last = ev
    except: pass
except: pass
print(last.get("command", "—") if last else "—")
PY
)
      fi

      unresolved=0
      if [ -f "$DEBT_REGISTER" ]; then
        unresolved=$(grep -cE "\| .*\| ${phase_num} \|.*\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
      fi

      action="—"
      case "$manifest_status" in
        *corruption*) action="/vg:recover ${phase_num}" ;;
        *legacy*)     action="next read auto-backfills" ;;
        *valid*)      [ "$unresolved" -gt 0 ] && action="review OVERRIDE-DEBT.md" ;;
      esac

      printf "| %s | %s | %s | %s | %s |\n" "$phase_num" "$manifest_status" "$last_cmd" "$unresolved" "$action"
    done
  fi
  echo ""

  echo "## Gate override pressure (áp lực bỏ qua cổng)"
  echo ""
  if type telemetry_warn_overrides >/dev/null 2>&1; then
    telemetry_warn_overrides 2 || echo "   (no gates exceed threshold)"
  else
    echo "   (telemetry helper unavailable)"
  fi
  echo ""

  echo "## Override debt register (sổ nợ bỏ qua)"
  if [ -f "$DEBT_REGISTER" ]; then
    open_count=$(grep -cE "\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    escalated=$(grep -cE "\| ESCALATED \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    echo "   Open: ${open_count}   Escalated: ${escalated}"
    [ "$escalated" -gt 0 ] && echo "   ⚠ Escalated entries block /vg:accept."
  else
    echo "   (no debt register — clean state)"
  fi
  echo ""

  echo "## Drift register (sổ lệch hướng)"
  if [ -f "$DRIFT_REGISTER" ]; then
    unfixed=$(grep -cE "^\| .* \| (info|warn) \| .* \| (?!resolved)" "$DRIFT_REGISTER" 2>/dev/null || echo 0)
    echo "   Unfixed: ${unfixed}"
    [ "$unfixed" -gt 0 ] && echo "   Run /vg:project --update để re-lock foundation."
  else
    echo "   (no drift register — clean state)"
  fi
  echo ""

  echo "## Semantic enrichment (v1.14.0+ migrate gates)"
  VERIFY_SCRIPT=""
  [ -f "${REPO_ROOT}/.claude/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
  [ -n "$VERIFY_SCRIPT" ] || { [ -f "${REPO_ROOT}/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"; }

  if [ -z "$VERIFY_SCRIPT" ]; then
    echo "   (validator not installed — skip semantic check)"
  else
    needs_enrich=0
    fully_enriched=0
    no_test_goals=0
    for phase_dir in "${PHASE_DIRS[@]}"; do
      [ -f "$phase_dir/TEST-GOALS.md" ] || { no_test_goals=$((no_test_goals + 1)); continue; }
      fail_count=$(${PYTHON_BIN} "$VERIFY_SCRIPT" --json "$phase_dir" 2>/dev/null \
        | ${PYTHON_BIN} -c "import sys,json; print(json.loads(sys.stdin.read()).get('fail',0))" 2>/dev/null)
      if [ "${fail_count:-0}" -gt 0 ]; then
        needs_enrich=$((needs_enrich + 1))
      else
        fully_enriched=$((fully_enriched + 1))
      fi
    done
    echo "   Fully enriched (all gates pass): ${fully_enriched}"
    echo "   Needs enrichment (≥1 gate fails): ${needs_enrich}"
    echo "   No TEST-GOALS yet:                 ${no_test_goals}"
    [ "$needs_enrich" -gt 0 ] && echo "   Detail per phase: /vg:health {phase}"
    [ "$needs_enrich" -gt 0 ] && echo "   Bulk re-enrich:  /vg:migrate {phase} --force (per phase)"
  fi
  echo ""

  echo "## Next actions"
  echo "   • Deep inspect:    /vg:health {phase}"
  echo "   • Integrity sweep: /vg:integrity"
  echo "   • Gate statistics: /vg:gate-stats"
  echo "   • Recover phase:   /vg:recover {phase}"
  echo ""
fi
```
</step>

<step name="2_deep">
## Step 2 (mode=deep): Single-phase deep inspection

```bash
if [ "$MODE" = "deep" ]; then
  phase_dir=""
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      phase_dir="$d"; break
    fi
  done

  if [ -z "$phase_dir" ]; then
    echo "⛔ Phase ${PHASE_ARG} not found under ${PHASES_DIR}"
    exit 1
  fi

  echo "## Phase ${PHASE_ARG} — deep inspection"
  echo "  Directory: ${phase_dir}"
  echo ""

  echo "### Artifacts + manifest (kê khai)"
  manifest_path="${phase_dir}/.artifact-manifest.json"
  if [ -f "$manifest_path" ]; then
    ${PYTHON_BIN} - "$phase_dir" "$manifest_path" <<'PY'
import json, sys, hashlib
from pathlib import Path
phase_dir = Path(sys.argv[1])
m = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
print(f"  Manifest version: {m.get('manifest_version', '?')}")
print(f"  Generated by:     {m.get('generated_by', '?')}")
print(f"  Artifact count:   {len(m.get('artifacts', []))}")
print()
print("  | Artifact | Size | Integrity |")
print("  |----------|------|-----------|")
for art in m.get("artifacts", []):
    abs_path = phase_dir / art["path"]
    if not abs_path.exists():
        status = "⛔ missing"
    else:
        actual = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        status = "✓" if actual == art["sha256"] else "⛔ mismatch"
    print(f"  | {art['path']} | {art.get('bytes', '?')}B | {status} |")
PY
  else
    echo "  ⚠ No manifest (legacy). Next read auto-backfills."
    find "$phase_dir" -maxdepth 1 -type f \( -name '*.md' -o -name '*.json' \) | sort | sed 's|^|    |'
  fi
  echo ""

  echo "### Recent telemetry events (last 10)"
  if type telemetry_query >/dev/null 2>&1 && [ -f "$TELEMETRY_PATH" ]; then
    telemetry_query --phase="${PHASE_ARG}" | tail -10 | ${PYTHON_BIN} - <<'PY' 2>/dev/null
import json, sys
print("  | Timestamp | Command | Step | Gate | Outcome |")
print("  |-----------|---------|------|------|---------|")
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      ts = ev.get("ts", "?")[:19]; cmd = ev.get("command", "?"); step = ev.get("step", "?")
      gate = ev.get("gate_id") or "—"; outc = ev.get("outcome") or ev.get("event_type", "?")
      print(f"  | {ts} | {cmd} | {step} | {gate} | {outc} |")
    except: pass
PY
  else
    echo "  (no telemetry for this phase)"
  fi
  echo ""

  echo "### Pipeline state"
  pipeline_state="${phase_dir}/PIPELINE-STATE.json"
  if [ -f "$pipeline_state" ]; then
    ${PYTHON_BIN} - "$pipeline_state" <<'PY'
import json, sys
s = json.loads(open(sys.argv[1], encoding='utf-8').read())
for k, v in s.items():
    if isinstance(v, (dict, list)): v = json.dumps(v)[:80]
    print(f"  • {k}: {v}")
PY
  else
    echo "  (no PIPELINE-STATE.json — phase may be new or pre-v1.8.0)"
  fi
  echo ""

  echo "### Recommended next action"
  if [ -f "${phase_dir}/UAT.md" ]; then
    echo "  ✓ Phase complete. /vg:next"
  elif [ -f "${phase_dir}/SANDBOX-TEST.md" ]; then
    echo "  → /vg:accept ${PHASE_ARG}"
  elif [ -f "${phase_dir}/RUNTIME-MAP.json" ]; then
    echo "  → /vg:test ${PHASE_ARG}"
  elif ls "${phase_dir}"/SUMMARY*.md >/dev/null 2>&1; then
    echo "  → /vg:review ${PHASE_ARG}"
  elif ls "${phase_dir}"/PLAN*.md >/dev/null 2>&1; then
    echo "  → /vg:build ${PHASE_ARG}"
  elif [ -f "${phase_dir}/CONTEXT.md" ]; then
    echo "  → /vg:blueprint ${PHASE_ARG}"
  elif [ -f "${phase_dir}/SPECS.md" ]; then
    echo "  → /vg:scope ${PHASE_ARG}"
  else
    echo "  → /vg:specs ${PHASE_ARG}"
  fi
  echo ""
fi
```
</step>

<step name="3_telemetry">
## Step 3: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "health_run" "${PHASE_ARG:-project}" "health.${MODE}" \
    "" "PASS" "{\"mode\":\"${MODE}\"}" >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Read-only; never writes/deletes.
- Summary mode = full-project table. Deep mode = one phase detailed view.
- All corruption/validation delegated to `artifact_manifest_validate`.
- Graceful degradation on missing files/helpers.
- Single `health_run` telemetry event per invocation.
</success_criteria>
</content>
</invoke>
