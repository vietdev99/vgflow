---
name: vg:override-resolve
description: Manually resolve a single override-debt entry — clean RESOLVED or permanent WONT_FIX — for overrides without a natural re-run trigger (e.g. --skip-design-check on a scaffolding phase)
argument-hint: <DEBT-ID> --reason='<justification>' [--wont-fix]
allowed-tools: Read, Bash, Grep, AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "override_resolve.started"
    - event_type: "override_resolve.completed"
---

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
