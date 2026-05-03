#!/bin/bash
# crossai-skip-guard.sh — CrossAI skip enforcement (v2.5.2.9+)
#
# Purpose: prevent AI from silently skipping CrossAI review at the end of
# scope / blueprint / build flows. Problem observed in phase 7.14/7.15/7.16:
#   - scope CrossAI: entirely silent, 0 events, 0 debt entries across 3 phases
#   - blueprint CrossAI: logged 12/15/3 contract waives but reason rubber-stamp
#     ("7.14-pattern: UI-only no API change" copy-pasted verbatim 7.14→7.15→7.16)
#   - build CrossAI: loop aborts via skip-crossai-build-loop with Windows infra
#     rationale, no enforcement
#
# This helper is the single source of truth for skip enforcement. Each flow
# (scope/blueprint/build) calls crossai_skip_enforce when its skip condition
# hits. Guard fires only for user_flag skips (mechanical causes like empty
# config or infra error get audit-only treatment).
#
# Usage:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-skip-guard.sh"
#   crossai_skip_enforce "$COMMAND" "$PHASE_NUMBER" "$STEP" "$CAUSE" "$REASON"
#
#   $COMMAND: vg:scope | vg:blueprint | vg:build
#   $CAUSE:   user_flag | config_empty | infra_error
#   $STEP:    free text (e.g. "scope.4_crossai_review", "build.crossai-loop")
#   $REASON:  free text rationale (shown to guard + logged to debt)
#
# Returns:
#   0 if skip allowed (event emitted, debt logged if user_flag, caller may
#     proceed to mark marker + exit step)
#   1 if guard blocks skip — caller should exit 1

crossai_skip_enforce() {
  local command="$1"
  local phase="$2"
  local step="$3"
  local cause="$4"
  local reason="${5:-}"

  # Only guard user_flag skips — config_empty + infra_error are mechanical
  # (no CLI to call, or CLI crashed) and get audit-only treatment.
  if [ "$cause" = "user_flag" ]; then
    # Try sourcing rationalization guard from either .md or .sh location
    if [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/rationalization-guard.sh" ]; then
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/rationalization-guard.sh" 2>/dev/null || true
    elif [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/rationalization-guard.md" ]; then
      # rationalization-guard.md has bash helpers inline — load them
      # (skip the YAML frontmatter via sed to avoid parse errors)
      local tmp_guard="${VG_TMP:-/tmp}/rat-guard-$$.sh"
      sed -n '/^rationalization_guard_check/,$p' \
        "${REPO_ROOT}/.claude/commands/vg/_shared/rationalization-guard.md" \
        > "$tmp_guard" 2>/dev/null && source "$tmp_guard" 2>/dev/null
      rm -f "$tmp_guard"
    fi

    if type -t rationalization_guard_check >/dev/null 2>&1; then
      local gate_id="${step//./-}-skip"
      local RAT
      RAT=$(rationalization_guard_check "$gate_id" \
        "CrossAI review là tầng AI-thứ-2 verify cho ${command}. Skip = chỉ 1 AI quyết định (echo chamber risk + decision drift không bắt được). Rubber-stamp (cùng reason xuất hiện ≥2 phase liên tiếp) là red flag — chặn ngay." \
        "$reason") 2>/dev/null

      if [ -n "$RAT" ] && type -t rationalization_guard_dispatch >/dev/null 2>&1; then
        if ! rationalization_guard_dispatch "$RAT" "$gate_id" "--skip-crossai" \
             "$phase" "$step" "$reason"; then
          echo "" >&2
          echo "⛔ Guard chống rubber-stamp chặn skip CrossAI cho ${command} phase ${phase}" >&2
          echo "" >&2
          echo "   Nguyên nhân chặn:" >&2
          echo "     Lý do skip của bạn trùng pattern đã dùng ở phase trước." >&2
          echo "     Đây là dấu hiệu AI tự copy-paste rationale không suy nghĩ mới." >&2
          echo "" >&2
          echo "   Cách sửa:" >&2
          echo "     1. Bỏ cờ --skip-crossai → CrossAI sẽ chạy đầy đủ (khuyến nghị)" >&2
          echo "     2. Đưa reason khác hẳn với phase trước (phải chứng minh CrossAI thực sự không cần ở phase này)" >&2
          echo "" >&2
          return 1
        fi
      fi
    fi

    # Log override-debt for user_flag skips — audit trail
    if [ -f "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" ]; then
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
    fi
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "--skip-crossai" "$phase" "$step" "$reason" \
        "crossai-skip-${phase}-${command//:/}" 2>/dev/null || true
    fi

    # Bug S3 fix — also emit canonical override.used event so the
    # orchestrator's `forbidden_without_override` gate at run-complete
    # finds an exact flag match. log_override_debt only writes legacy
    # `override_used` (snake_case) telemetry + a register row; the gate
    # at __main__.py:4031 requires `override.used` (dotted). Both fire:
    # register tracking + canonical event emission. Use `--flag=` and
    # `--reason=` (equals form) because argparse otherwise treats
    # values starting with `--` as a separate option.
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/vg-orchestrator" override \
      "--flag=--skip-crossai" \
      "--reason=${reason:-no_reason_provided}" \
      >/dev/null 2>&1 || true
  fi

  # ALWAYS emit event — no silent skip ever. Replaces the old pattern where
  # scope.md just said "Skip if ..." in prose and AI could quietly fall through
  # without any trace in events.db.
  "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
    "crossai.skipped" \
    --payload "{\"phase\":\"${phase}\",\"command\":\"${command}\",\"step\":\"${step}\",\"cause\":\"${cause}\"}" \
    >/dev/null 2>&1 || true

  # User-facing summary (Vietnamese prose — no jargon dump)
  echo ""
  echo "ℹ CrossAI ĐÃ BỎ QUA — ${command} phase ${phase}"
  case "$cause" in
    user_flag)
      echo "  Nguyên nhân: user truyền cờ --skip-crossai"
      ;;
    config_empty)
      echo "  Nguyên nhân: config.crossai_clis trong .claude/vg.config.md đang rỗng"
      echo "  Hệ quả: project này chưa cấu hình CLI nào để gọi (vd Codex, Gemini)"
      ;;
    infra_error)
      echo "  Nguyên nhân: CrossAI CLI crashed hoặc timeout (infra error)"
      ;;
    *)
      echo "  Nguyên nhân: ${cause}"
      ;;
  esac
  [ -n "$reason" ] && echo "  Lý do cụ thể: ${reason}"
  echo ""
  echo "  Hệ quả phase:"
  echo "    - Decisions/plan/contracts của phase KHÔNG được AI thứ 2 review"
  echo "    - Rủi ro: drift, hallucination, decision contradiction không được catch"
  echo ""
  echo "  Audit trail:"
  echo "    - Event 'crossai.skipped' đã ghi vào events.db (không còn silent)"
  [ "$cause" = "user_flag" ] && echo "    - Override-debt entry đã thêm vào .vg/OVERRIDE-DEBT.md"
  echo ""
  return 0
}

# Convenience: auto-detect skip cause from context + env
# Returns cause string to stdout, empty if no skip needed.
crossai_detect_skip_cause() {
  local arguments="${1:-}"
  local config_path="${2:-.claude/vg.config.md}"

  # Check --skip-crossai flag
  if [[ "$arguments" =~ --skip-crossai ]]; then
    echo "user_flag"
    return 0
  fi

  # Check config.crossai_clis empty
  if [ -f "$config_path" ]; then
    if grep -qE "^\s*crossai_clis:\s*\[\s*\]" "$config_path" 2>/dev/null || \
       ! grep -qE "^\s*crossai_clis:" "$config_path" 2>/dev/null; then
      echo "config_empty"
      return 0
    fi
  fi

  # No skip
  echo ""
  return 0
}
