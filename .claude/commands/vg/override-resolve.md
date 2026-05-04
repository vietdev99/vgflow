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
source .claude/commands/vg/_shared/override-debt.md 2>/dev/null || true
export VG_CURRENT_COMMAND="vg:override-resolve"
telemetry_init 2>/dev/null || true

ARGS="$ARGUMENTS"
# Issue #19/#21: register holds three ID flavors that all need resolution:
#   DEBT-YYYYMMDDHHMMSS-PID  — legacy markdown-table format
#   OD-NNN                    — orchestrator CLI YAML format
#   BF-YYYYMMDDHHMMSS-PID    — run-backfill YAML format (issue #21)
# Slash command accepts all three. The downstream override_resolve_by_id
# helper detects format from the ID prefix and mutates the right rows.
DEBT_ID=$(echo "$ARGS" | grep -oE '(DEBT-[0-9]+-[0-9]+|OD-[0-9]+|BF-[0-9]+-[0-9]+)' | head -n1)
REASON=$(echo "$ARGS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
WONT_FIX=false
[[ "$ARGS" =~ --wont-fix ]] && WONT_FIX=true

# Validate inputs
if [ -z "$DEBT_ID" ]; then
  echo "⛔ Thiếu DEBT-ID. Usage: /vg:override-resolve <DEBT-...|OD-NNN|BF-...> --reason='...' [--wont-fix]"
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

# Validate DEBT-ID exists in register
if ! grep -qF "$DEBT_ID" "$REGISTER"; then
  echo "⛔ Không tìm thấy DEBT-ID '${DEBT_ID}' trong ${REGISTER}."
  echo "   Chạy /vg:progress hoặc xem trực tiếp register để tra DEBT-ID hợp lệ."
  exit 1
fi

# Check current status — WONT_FIX/RESOLVED is a no-op
CURRENT_STATUS=$(grep -F "$DEBT_ID" "$REGISTER" | head -n1 | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$9); print $9}')
if [ "$CURRENT_STATUS" != "OPEN" ]; then
  echo "ℹ ${DEBT_ID} đã ở trạng thái ${CURRENT_STATUS} (không phải OPEN) — không cần giải quyết (resolve) lại."
  exit 0
fi
```

## Step 2: `--wont-fix` confirmation gate

If `--wont-fix`, halt and use **AskUserQuestion** to force deliberate human confirmation — WONT_FIX is permanent; it means "we never plan to fix this." The audit trail depends on this prompt being honest.

```
question: "Đánh dấu ${DEBT_ID} là WONT_FIX (từ chối sửa vĩnh viễn)?

  Lý do: ${REASON}

  WONT_FIX nghĩa là override (bỏ qua) này KHÔNG bao giờ được giải quyết (resolve) —
  ví dụ phase scaffolding cố ý không viết test. Chọn 'Cancel' nếu muốn dùng clean re-run path."
options:
  - "Yes, mark wont-fix"  → proceed
  - "Cancel"              → abort with exit 0
```

Skip this step if `--wont-fix` not set (default RESOLVED path proceeds without prompt — clean resolution is lower risk).

## Step 3: Call override_resolve_by_id

```bash
STATUS="RESOLVED"
[ "$WONT_FIX" = "true" ] && STATUS="WONT_FIX"

EVENT_ID=$(override_resolve_by_id "$DEBT_ID" "$STATUS" "$REASON") || {
  echo "⛔ override_resolve_by_id thất bại. Kiểm tra stderr ở trên."
  exit 1
}

echo ""
echo "✓ ${DEBT_ID} → ${STATUS}"
echo "   Lý do (reason): ${REASON}"
echo "   Telemetry event: ${EVENT_ID}"
echo "   Register: ${REGISTER}"
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

## Success criteria

- Một lệnh duy nhất xử lý một DEBT-ID → register update + telemetry event.
- WONT_FIX luôn qua AskUserQuestion confirmation (không bypass được qua CLI flag-only).
- Accept gate tự động bỏ qua WONT_FIX entries (implicit — `override_list_unresolved` chỉ trả OPEN).
- Reason preserved trong cả register (`reason_old || status: reason`) và telemetry payload.
