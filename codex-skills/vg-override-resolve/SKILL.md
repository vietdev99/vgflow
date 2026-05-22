---
name: "vg-override-resolve"
description: "Manually resolve a single override-debt entry — clean RESOLVED or permanent WONT_FIX — for overrides without a natural re-run trigger (e.g. --skip-design-check on a scaffolding phase)"
metadata:
  short-description: "Manually resolve a single override-debt entry — clean RESOLVED or permanent WONT_FIX — for overrides without a natural re-run trigger (e.g. --skip-design-check on a scaffolding phase)"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
`VG_RUNTIME=codex`, use Codex `update_plan` for the compact visible task
window, and bind it with `vg-orchestrator tasklist-projected --adapter codex`.

VGFlow source paths are resolved through global `VG_HOME` (default:
`~/.vgflow`). Project-local Claude workflow files may be absent in
global-only installs; Codex must use
`${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}` and
`${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}` for workflow
helpers. References below to "Claude CLI", `TodoWrite`, or Haiku describe
the Claude adapter only. Codex must map them through this adapter contract
instead of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use `tasklist-contract.json` as source of truth. Do not paste the full hierarchy into Codex `update_plan`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and `+N pending`. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`. |
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
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh --tier planner` |
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
bash "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh" \
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

Invoke this skill as `$vg-override-resolve`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# /vg:override-resolve — Manual Override Resolution (v1.9.0+)

Resolves ONE entry in `${PLANNING_DIR}/OVERRIDE-DEBT.md` by DEBT-ID. Two modes:

- **Default (no flag):** status → `RESOLVED` (clean manual resolution — user confirms gate intent is satisfied without a telemetry-linked re-run)
- **`--wont-fix`:** status → `WONT_FIX` (permanent decline — override is intentionally kept, e.g. scaffolding phase where no tests were ever planned)

Both paths:
1. Emit `override_resolved` telemetry event with `{status, reason, debt_id, manual:true}` (audit trail).
2. Clear the accept-gate block for that entry (accept's `override_list_unresolved` filter skips non-OPEN rows).

Prefer the clean re-run path (`/vg:build --gaps-only`, `/vg:review`, `/vg:test`) whenever a natural retry exists — that auto-resolves via event correlation without needing this command.

## Inputs

- `<DEBT-ID>` (required, positional) — e.g. `DEBT-20260417142033-12345`
- `--reason='<text>'` (required) — non-empty justification, written into register + telemetry
- `--wont-fix` (optional) — mark permanent decline; triggers AskUserQuestion confirmation

## Step 1: Parse arguments + validate

```bash
set -euo pipefail
source .claude/commands/vg/_shared/config-loader.md 2>/dev/null || true
source .claude/commands/vg/_shared/telemetry.md 2>/dev/null || true
# B101 v4.69.4 (issue #198): source the runnable .sh, NOT the markdown .md.
# Pre-B101 sourced .md → bash silently ignored markdown headers (via
# `|| true`) → override_resolve_by_id was NEVER defined → command not found
# silently swallowed → row stayed status=active. The .md is doc-only per
# its own line-8 warning. The runnable bash lives in lib/override-debt.sh.
source .claude/commands/vg/_shared/lib/override-debt.sh 2>/dev/null || true
export VG_CURRENT_COMMAND="vg:override-resolve"
telemetry_init 2>/dev/null || true

ARGS="$ARGUMENTS"
# Issue #19/#21: register holds three ID flavors that all need resolution:
#   DEBT-YYYYMMDDHHMMSS-PID  — legacy markdown-table format
#   OD-NNN                    — orchestrator CLI YAML format
#   BF-YYYYMMDDHHMMSS-PID    — run-backfill YAML format (issue #21)
#
# B101 v4.69.4 (issue #198 batch mode): accept MULTIPLE DEBT-IDs. Real
# resolve sessions batch IDs like `OD-30179 OD-30180`. Pre-B101 took only
# the first match → second ID silently dropped.
DEBT_IDS=$(echo "$ARGS" | grep -oE '(DEBT-[0-9]+-[0-9]+|OD-[0-9]+|BF-[0-9]+-[0-9]+)')
REASON=$(echo "$ARGS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
WONT_FIX=false
[[ "$ARGS" =~ --wont-fix ]] && WONT_FIX=true

# Validate inputs
if [ -z "$DEBT_IDS" ]; then
  echo "⛔ Thiếu DEBT-ID. Usage: /vg:override-resolve <DEBT-...|OD-NNN|BF-...> [<id-2> ...] --reason='...' [--wont-fix]"
  exit 1
fi
if [ -z "$REASON" ]; then
  echo "⛔ Thiếu --reason='...'. Lý do (reason) là bắt buộc để audit trail."
  exit 1
fi

REGISTER="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
if [ ! -f "$REGISTER" ]; then
  echo "⛔ Register không tồn tại: ${REGISTER}"
  exit 1
fi

# B101: status check now accepts both "OPEN" (markdown table) AND "active"
# (YAML block). Pre-B101 awk-on-pipe only worked for table format; YAML
# rows produce empty CURRENT_STATUS → false negative "đã ở trạng thái ()".
# New check: per ID, grep for status line inside the row's block, normalize.
SKIPPED=()
PROCESS=()
for DEBT_ID in $DEBT_IDS; do
  if ! grep -qF "$DEBT_ID" "$REGISTER"; then
    echo "⛔ Không tìm thấy DEBT-ID '${DEBT_ID}' trong ${REGISTER}."
    SKIPPED+=("$DEBT_ID:not_found")
    continue
  fi
  # Detect format + extract current status case-insensitively
  if [[ "$DEBT_ID" =~ ^(OD-|BF-) ]]; then
    # YAML block — grep `status:` line between `- id: <id>` and next `- ` or EOF
    CURRENT_STATUS=$(awk -v id="- id: $DEBT_ID" '
      $0 == id {found=1; next}
      found && /^- / {exit}
      found && /^[[:space:]]*status:/ {sub(/^[[:space:]]*status:[[:space:]]*/, ""); print; exit}
    ' "$REGISTER")
  else
    # Markdown table — pipe column 9 is status
    CURRENT_STATUS=$(grep -F "$DEBT_ID" "$REGISTER" | head -n1 | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$9); print $9}')
  fi
  # Normalize to compare canonically
  CURRENT_LC=$(echo "$CURRENT_STATUS" | tr '[:upper:]' '[:lower:]' | xargs)
  if [ "$CURRENT_LC" != "open" ] && [ "$CURRENT_LC" != "active" ]; then
    echo "ℹ ${DEBT_ID} đã ở trạng thái ${CURRENT_STATUS:-<empty>} — không cần resolve lại."
    SKIPPED+=("$DEBT_ID:already_${CURRENT_LC}")
    continue
  fi
  PROCESS+=("$DEBT_ID")
done

if [ ${#PROCESS[@]} -eq 0 ]; then
  echo "ℹ No DEBT-IDs to process (all already resolved or not found)."
  exit 0
fi
```

## Step 2: `--wont-fix` confirmation gate

If `--wont-fix`, halt and use **AskUserQuestion** to force deliberate human confirmation — WONT_FIX is permanent; it means "we never plan to fix this." The audit trail depends on this prompt being honest.

```
question: "Đánh dấu ${PROCESS[*]} là WONT_FIX (từ chối sửa vĩnh viễn)?

  Lý do: ${REASON}

  WONT_FIX nghĩa là override (bỏ qua) này KHÔNG bao giờ được giải quyết (resolve) —
  ví dụ phase scaffolding cố ý không viết test. Chọn 'Cancel' nếu muốn dùng clean re-run path.

  B101: nếu đa-ID, cùng một status được áp dụng cho tất cả."
options:
  - "Yes, mark wont-fix"  → proceed
  - "Cancel"              → abort with exit 0
```

Skip this step if `--wont-fix` not set (default RESOLVED path proceeds without prompt — clean resolution is lower risk).

## Step 3: Call override_resolve_by_id (B101: batch loop)

```bash
STATUS="RESOLVED"
[ "$WONT_FIX" = "true" ] && STATUS="WONT_FIX"

RESOLVED_COUNT=0
FAILED=()
for DEBT_ID in "${PROCESS[@]}"; do
  EVENT_ID=$(override_resolve_by_id "$DEBT_ID" "$STATUS" "$REASON") || {
    echo "⛔ override_resolve_by_id thất bại cho ${DEBT_ID}. Kiểm tra stderr ở trên."
    FAILED+=("$DEBT_ID")
    continue
  }
  RESOLVED_COUNT=$((RESOLVED_COUNT + 1))
  echo "✓ ${DEBT_ID} → ${STATUS} (event ${EVENT_ID})"
done

echo ""
echo "Lý do (reason): ${REASON}"
echo "Register: ${REGISTER}"
echo "Resolved: ${RESOLVED_COUNT}/${#PROCESS[@]}"
if [ ${#SKIPPED[@]} -gt 0 ]; then
  echo "Skipped: ${SKIPPED[*]}"
fi
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "Failed: ${FAILED[*]}"
  exit 1
fi
echo ""
if [ "$STATUS" = "WONT_FIX" ]; then
  echo "→ /vg:accept sẽ không còn block entry này. Audit trail đã ghi nhận quyết định permanent."
else
  echo "→ /vg:accept sẽ không còn block entry này."
fi
```

## Edge cases

| Case | Handling |
|------|----------|
| DEBT-ID không tồn tại | grep guard → exit 1 với hướng dẫn tra register |
| --reason rỗng hoặc thiếu | exit 1 ngay — audit không được phép không có lý do |
| Entry đã RESOLVED/WONT_FIX | no-op, exit 0, báo trạng thái hiện tại |
| Register file thiếu | exit 1 — không tạo file trống tránh mask bug |
| AskUserQuestion → Cancel (wont-fix) | exit 0 không ghi gì, telemetry không emit |
| Concurrent edit của register | Python rewrite là atomic trên single row; nhiều DEBT-IDs khác nhau safe song song |

## --deploy-method Extension (Batch 20)

Use `--deploy-method=<new_method> --reason='<text>'` to change the locked deploy method
in `.vg/DEPLOY-CONTRACT.json`. Required when project genuinely migrates deploy
infrastructure (e.g. ansible → kubectl, pm2 → docker compose).

This is a **separate flow** from DEBT-ID resolution — no DEBT-ID needed, but `--reason` is mandatory.

```bash
if [[ "${ARGUMENTS}" =~ --deploy-method=([a-zA-Z0-9_-]+) ]]; then
  NEW_METHOD="${BASH_REMATCH[1]}"
  REASON_DEPLOY=$(echo "${ARGUMENTS}" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
  if [ -z "$REASON_DEPLOY" ]; then
    echo "⛔ --deploy-method requires --reason='<why changing deploy method>'" >&2
    exit 1
  fi

  CONTRACT_PATH="${PROJECT_VG_DIR:-.vg}/DEPLOY-CONTRACT.json"
  echo "▸ Changing locked deploy method to: ${NEW_METHOD}"
  echo "  Current contract: ${CONTRACT_PATH}"
  echo "  Reason: ${REASON_DEPLOY}"
  echo ""
  echo "  AI controller: gather new build/restart/health commands via AskUserQuestion,"
  echo "  then run:"
  echo "    python scripts/deploy-contract-init.py \\"
  echo "      --method ${NEW_METHOD} --build '...' --restart '...' --health '...' \\"
  echo "      --force --phase ${PHASE_NUMBER:-?} --run-id ${VG_RUN_ID:-?}"

  # Emit telemetry event
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "deploy.contract_override" \
    --actor "orchestrator" --outcome "INFO" \
    --payload "{\"new_method\":\"${NEW_METHOD}\",\"reason\":\"${REASON_DEPLOY}\"}" \
    2>/dev/null || true

  # Log override-debt entry for audit trail
  # B101 v4.69.4: source the .sh (runnable), not the .md (doc-only)
  source .claude/commands/vg/_shared/lib/override-debt.sh 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "deploy-method-change" "${PHASE_NUMBER:-global}" \
      "${NEW_METHOD}: ${REASON_DEPLOY}" "${PHASE_DIR:-.}" || true

  exit 0
fi
```

After AI gathers new commands and runs `deploy-contract-init.py --force`, the
PreToolUse hook will be updated to the new fingerprint_pattern on next deploy.

## Success criteria

- Một lệnh duy nhất xử lý một DEBT-ID → register update + telemetry event.
- WONT_FIX luôn qua AskUserQuestion confirmation (không bypass được qua CLI flag-only).
- Accept gate tự động bỏ qua WONT_FIX entries (implicit — `override_list_unresolved` chỉ trả OPEN).
- Reason preserved trong cả register (`reason_old || status: reason`) và telemetry payload.
