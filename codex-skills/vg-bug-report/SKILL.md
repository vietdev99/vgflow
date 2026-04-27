---
name: "vg-bug-report"
description: "Auto-detect workflow bugs + push to GitHub issues on vietdev99/vgflow. Opt-out default, anonymous URL fallback if no gh auth."
metadata:
  short-description: "Auto-detect workflow bugs + push to GitHub issues on vietdev99/vgflow. Opt-out default, anonymous URL fallback if no gh auth."
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

Invoke this skill as `$vg-bug-report`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Opt-out default** — first install prompts consent. User can disable via `--disable-all`.
2. **Privacy-first** — redact project paths, names, emails, phase IDs before upload.
3. **Dedup** — local sent cache + GitHub issue search by signature.
4. **Rate limit** — max 5 events per session (configurable via `config.bug_reporting.max_per_session`).
5. **3-tier send** — gh CLI (authenticated) → URL fallback (anonymous) → silent queue (if auto_send_minor=false).
6. **Severity threshold** — only immediate-send if severity >= threshold. Lower severities queued for weekly flush.
</rules>

<objective>
Auto-report workflow bugs to vietdev99/vgflow. Users help improve VG by letting AI detect issues (schema violations, helper errors, user pushback, gate loops) and report them.

Modes:
- `--flush` — send queued events now
- `--queue` — show pending local queue
- `--disable=<signature>` — suppress future reports of a specific signature
- `--disable-all` — disable entire bug reporter
- `--enable` — re-enable after disable
- `--stats` — local statistics
- `--test` — send test bug to verify setup
- Without flags → prompt consent if not yet configured, else show status
</objective>

<process>

**Source:**
```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/bug-reporter.sh"
```

<step name="0_parse">
Parse flags:
```bash
MODE="status"
SIG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --flush)          MODE="flush" ;;
    --queue)          MODE="queue" ;;
    --disable=*)      MODE="disable"; SIG="${arg#*=}" ;;
    --disable-all)    MODE="disable-all" ;;
    --enable)         MODE="enable" ;;
    --stats)          MODE="stats" ;;
    --test)           MODE="test" ;;
  esac
done
```
</step>

<step name="1_dispatch">

### Mode: `status` (default)

```bash
bug_reporter_consent_prompt  # prompts if not yet configured
if bug_reporter_enabled; then
  echo "✓ Bug reporting enabled"
  count=$(bug_reporter_session_count)
  echo "  Session events: ${count}"
  local queue="${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}"
  if [ -f "$queue" ]; then
    echo "  Queued (pending flush): $(wc -l < "$queue")"
  fi
  local sent="${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}"
  if [ -f "$sent" ]; then
    echo "  Total sent: $(wc -l < "$sent")"
  fi
else
  echo "⚠ Bug reporting disabled. Enable: /vg:bug-report --enable"
fi
```

### Mode: `flush`

```bash
bug_reporter_queue_flush
```

### Mode: `queue`

```bash
bug_reporter_queue_show
```

### Mode: `disable=SIG`

```bash
local disabled="${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}"
mkdir -p "$(dirname "$disabled")"
echo "$SIG" >> "$disabled"
echo "✓ Signature $SIG suppressed. Future reports ignored."
```

### Mode: `disable-all`

```bash
${PYTHON_BIN} -c "
import re
cfg = '.claude/vg.config.md'
txt = open(cfg, encoding='utf-8').read()
txt = re.sub(r'(bug_reporting:\n  enabled:)\s*true', r'\1 false', txt)
open(cfg, 'w', encoding='utf-8').write(txt)
print('✓ Bug reporting disabled. Existing queue preserved but not sent.')
"
```

### Mode: `enable`

```bash
${PYTHON_BIN} -c "
import re
cfg = '.claude/vg.config.md'
txt = open(cfg, encoding='utf-8').read()
txt = re.sub(r'(bug_reporting:\n  enabled:)\s*false', r'\1 true', txt)
open(cfg, 'w', encoding='utf-8').write(txt)
print('✓ Bug reporting enabled. Run /vg:bug-report --flush to send queued events.')
"
```

### Mode: `stats`

```bash
echo "=== Bug Reporter Stats ==="
local queue_count=0 sent_count=0 disabled_count=0
[ -f "${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}" ] && queue_count=$(wc -l < "${CONFIG_BUG_REPORTING_QUEUE:-.claude/.bug-reports-queue.jsonl}")
[ -f "${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}" ] && sent_count=$(wc -l < "${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}")
[ -f "${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}" ] && disabled_count=$(wc -l < "${CONFIG_BUG_REPORTING_DISABLED:-.claude/.bug-reports-disabled.txt}")
echo "  Queued: $queue_count"
echo "  Sent: $sent_count"
echo "  Disabled signatures: $disabled_count"
echo ""
echo "Top 5 most-reported types (from sent cache):"
[ -f "${CONFIG_BUG_REPORTING_SENT_CACHE}" ] && ${PYTHON_BIN} -c "
import json, collections
from pathlib import Path
p = Path('${CONFIG_BUG_REPORTING_SENT_CACHE:-.claude/.bug-reports-sent.jsonl}')
if p.exists():
    types = [json.loads(l).get('signature','') for l in p.read_text().splitlines() if l]
    for t, c in collections.Counter(types).most_common(5):
        print(f'  - {t}: {c}')
"
```

### Mode: `test`

```bash
echo "=== Test bug report (dry run) ==="
report_bug "test-$(date +%s)" "test_event" "This is a test event from /vg:bug-report --test" "minor"
echo "Check: /vg:bug-report --queue"
echo "Send: /vg:bug-report --flush"
```
</step>

</process>

<success_criteria>
- `status` mode prompts consent if config missing, shows state otherwise
- `flush` sends queue via gh CLI or URL fallback
- `disable=SIG` adds signature to disabled list, suppresses future reports
- `disable-all` / `enable` toggle config.bug_reporting.enabled
- `stats` shows queued/sent/disabled counts + top types
- `test` creates sample event end-to-end
</success_criteria>
