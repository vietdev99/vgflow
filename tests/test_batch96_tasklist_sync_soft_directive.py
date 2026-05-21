"""B96 v4.68.1 — soft-directive mode for tasklist sync gate.

User report (2026-05-21):
"Run-complete bị block ở latest_marked_step=5_complete status=pending không
refresh. Recover bằng /vg:doctor recovery hoặc vg-orchestrator run-abort
--reason 'tasklist gate loop' rồi re-emit run-start nếu cần."

Previously: any tasklist sync drift (sync_stale OR sync_status_invalid)
fired immediate hard block via emit_block → exit 2. AI had no chance to
self-correct in the same bash flow → loop trap requiring manual
run-abort.

B96 fix: first N detections emit AI directive on stderr + telemetry
event but exit 0. AI sees instruction and issues corrective TodoWrite
on the next call. After threshold N (default 2, configurable via env
`VG_TASKLIST_SYNC_SOFT_LIMIT`), falls back to current hard block.
Counter persists at `.vg/runs/<run_id>/.tasklist-sync-retry-count` +
resets to 0 when `sync_check_result=ok` next iteration.

Soft directive format:
- Yellow warn color (\\033[33m) — softer than orange error
- 3-line compact stderr
- Includes "soft directive N/M" attempt count
- Includes specific corrective action (TodoWrite syntax + which step)
- Mentions hard-block threshold so AI knows budget

Telemetry: `<cmd>.tasklist_sync_directive_emitted` event per attempt
with payload {run_id, kind, attempt, threshold}.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

def test_b96_soft_directive_helper_defined() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert "_emit_sync_directive" in body, "soft-directive helper missing"
    assert "B96 v4.68.1" in body, "B96 marker missing"


def test_b96_retry_counter_file_path() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert ".tasklist-sync-retry-count" in body, "retry counter file missing"
    # Lives under .vg/runs/<run_id>/ per existing convention
    assert ".vg/runs/${run_id}/.tasklist-sync-retry-count" in body


def test_b96_soft_threshold_env_override() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert "VG_TASKLIST_SYNC_SOFT_LIMIT" in body, "env override missing"
    # Default 2
    assert ":-2}" in body or ':-2}"' in body


def test_b96_sync_stale_uses_soft_directive_first() -> None:
    body = HOOK.read_text(encoding="utf-8")
    # sync_stale branch wrapped in soft-threshold check
    stale_idx = body.index("sync_stale*)")
    block_idx = body.index("emit_block", stale_idx)
    # Soft check appears between case match and emit_block
    region = body[stale_idx:block_idx]
    assert "_sync_retry_count" in region
    assert "_emit_sync_directive" in region
    assert "exit 0" in region


def test_b96_sync_status_invalid_uses_soft_directive_first() -> None:
    body = HOOK.read_text(encoding="utf-8")
    inv_idx = body.index("sync_status_invalid*)")
    block_idx = body.index("emit_block", inv_idx)
    region = body[inv_idx:block_idx]
    assert "_sync_retry_count" in region
    assert "_emit_sync_directive" in region
    assert "exit 0" in region


def test_b96_ok_branch_resets_counter() -> None:
    body = HOOK.read_text(encoding="utf-8")
    case_start = body.index('case "$tasklist_sync_check_result" in')
    case_end = body.index('esac', case_start)
    region = body[case_start:case_end]
    assert "_sync_retry_file" in region and "rm -f" in region


def test_b96_hard_block_escalation_message() -> None:
    body = HOOK.read_text(encoding="utf-8")
    # Hard block path mentions "escalating" so AI sees it's the final step
    assert "escalating to hard block" in body


def test_b96_directive_uses_warn_color_not_orange() -> None:
    body = HOOK.read_text(encoding="utf-8")
    # Color 33 = yellow (warn); 38;5;208 = orange (error). Soft uses 33.
    helper_idx = body.index("_emit_sync_directive()")
    case_idx = body.index('case "$tasklist_sync_check_result" in', helper_idx)
    region = body[helper_idx:case_idx]
    assert "\\033[33m" in region, "soft directive must use yellow warn color"


def test_b96_telemetry_event_emitted() -> None:
    body = HOOK.read_text(encoding="utf-8")
    helper_idx = body.index("_emit_sync_directive()")
    helper_end = body.index("\ncase \"$tasklist_sync_check_result\"", helper_idx)
    region = body[helper_idx:helper_end]
    assert "tasklist_sync_directive_emitted" in region


def test_b96_directive_explains_corrective_action() -> None:
    body = HOOK.read_text(encoding="utf-8")
    # Directive must mention TodoWrite + tasklist-projected refresh
    assert "AI MUST call TodoWrite" in body
    # And give specific instruction not to skip ahead
    assert "Do NOT call run-complete" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b96_hook_mirror_byte_identical() -> None:
    assert HOOK.read_bytes() == MIRROR.read_bytes(), (
        "vg-pre-tool-use-bash.sh mirror drift"
    )
