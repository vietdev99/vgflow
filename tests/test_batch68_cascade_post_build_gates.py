"""tests/test_batch68_cascade_post_build_gates.py — B68 (v4.56.0).

User report: "vẫn còn tình trạng bỏ quên các bước sau khi build trong
flow build, không cross ai check, không làm các step sau mà chỉ thông
báo là đã build xong".

Diagnosis:
- v4.21.0 hotfix d19403d added Stop hook check #4 that catches STEP 5
  (9_post_execution) missing after waves.
- BUT: check #4 only catches STEP 5. After STEP 5 done, AI can still
  end turn before STEP 6 (CrossAI verify-loop) or STEP 7 (close →
  run_complete). No cascade enforcement.
- User pain: AI marks STEP 5 done → ends turn → CrossAI never runs →
  run_complete marker never written → "build done" announcement is
  premature.

Fix (B68):
Extend vg-stop.sh post-wave block with 2 new cascade checks:
- 4b: STEP 5 done + STEP 6 (11_crossai_build_verify_loop) missing +
      is_final_wave=true → BLOCK with CrossAI continuation message
- 4c: STEP 6 done + STEP 7 (12_run_complete) missing +
      is_final_wave=true → BLOCK with close.md continuation message

Coverage:
  1. Check 4a (STEP 5 missing) still present (B62 regression guard)
  2. Check 4b (STEP 6 CrossAI missing) present + references crossai-loop.md
  3. Check 4c (STEP 7 run_complete missing) present + references close.md
  4. CrossAI hard-gate reference in message
  5. run_complete canonical marker reference
  6. Reads 11_crossai_build_verify_loop marker
  7. Reads 12_run_complete marker
  8. Mirror parity (.claude/scripts/hooks/vg-stop.sh)
  9. Check order: 4a → 4b → 4c (cascade fires sequentially as steps
     complete)
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STOP_HOOK = REPO / "scripts" / "hooks" / "vg-stop.sh"
STOP_MIRROR = REPO / ".claude" / "scripts" / "hooks" / "vg-stop.sh"


def _read(p): return p.read_text(encoding="utf-8")


def test_check_4a_step5_missing_present():
    body = _read(STOP_HOOK)
    # B62 regression guard: original check still in place
    assert "POST-WAVE CONTINUATION (4a)" in body, "check 4a (STEP 5) must remain"
    assert "9_post_execution" in body
    assert "STEP 5 post-execution not run" in body


def test_check_4b_crossai_missing_present():
    body = _read(STOP_HOOK)
    assert "POST-WAVE CONTINUATION (4b)" in body, "B68: check 4b (CrossAI) required"
    assert "11_crossai_build_verify_loop" in body
    assert "CrossAI" in body
    # Must reference crossai-loop.md doc
    assert "crossai-loop.md" in body


def test_check_4c_postmortem_missing_present():
    """B68 codex BLOCKER #1 fix: 4c gates postmortem_sanity (was: run_complete)."""
    body = _read(STOP_HOOK)
    assert "POST-WAVE CONTINUATION (4c)" in body, "B68: check 4c (postmortem) required"
    assert "10_postmortem_sanity" in body
    assert "postmortem" in body.lower()


def test_check_4d_run_complete_missing_present():
    """B68: 4d gates 12_run_complete marker write."""
    body = _read(STOP_HOOK)
    assert "POST-WAVE CONTINUATION (4d)" in body
    assert "12_run_complete" in body
    assert "CANONICAL" in body or "canonical" in body.lower()


def test_check_4e_run_state_active_despite_marker():
    """B68 codex BLOCKER #2 fix: 4e gates state-based, not marker-based.
    12_run_complete marker written before real vg-orchestrator run-complete."""
    body = _read(STOP_HOOK)
    assert "POST-WAVE CONTINUATION (4e)" in body
    assert "run-status" in body
    assert "state" in body.lower()
    assert "preliminary" in body.lower() or "preliminary" in body.lower()


def test_crossai_hard_gate_referenced_in_message():
    body = _read(STOP_HOOK)
    # Locate 4b block + verify hard-gate language
    idx_4b = body.find("POST-WAVE CONTINUATION (4b)")
    assert idx_4b > 0
    block_4b = body[idx_4b:idx_4b + 1000]
    assert "HARD-GATE" in block_4b or "hard-gate" in block_4b.lower()


def test_run_complete_canonical_referenced_in_message():
    body = _read(STOP_HOOK)
    # 4d (not 4c per codex fix) gates the run_complete marker
    idx_4d = body.find("POST-WAVE CONTINUATION (4d)")
    assert idx_4d > 0
    block_4d = body[idx_4d:idx_4d + 1000]
    assert "CANONICAL" in block_4d or "canonical" in block_4d.lower()


def test_crossai_event_name_corrected():
    """codex MAJOR #1 fix: 4b references real event name
    build.crossai_loop_complete, not the incorrect crossai.verdict."""
    body = _read(STOP_HOOK)
    idx_4b = body.find("POST-WAVE CONTINUATION (4b)")
    block_4b = body[idx_4b:idx_4b + 1000]
    assert "build.crossai_loop_complete" in block_4b or "build-crossai-required.py" in block_4b
    # Old incorrect name should NOT be in the failure message body
    assert "crossai.verdict" not in block_4b


def test_crossai_marker_var_read():
    body = _read(STOP_HOOK)
    assert "crossai_done=" in body
    assert "11_crossai_build_verify_loop.done" in body


def test_run_complete_marker_var_read():
    body = _read(STOP_HOOK)
    assert "run_complete_done=" in body
    assert "12_run_complete.done" in body


def test_mirror_in_sync():
    assert _read(STOP_HOOK) == _read(STOP_MIRROR), "stop hook mirror drift"


def test_cascade_order_4a_through_4e():
    """Cascade order: 4a → 4b → 4c → 4d → 4e (post codex fixes)."""
    body = _read(STOP_HOOK)
    idx = {k: body.find(f"POST-WAVE CONTINUATION ({k})") for k in ("4a", "4b", "4c", "4d", "4e")}
    for k, v in idx.items():
        assert v > 0, f"{k} not found"
    ordered = [idx["4a"], idx["4b"], idx["4c"], idx["4d"], idx["4e"]]
    assert ordered == sorted(ordered), f"cascade order broken: {idx}"


def test_postmortem_done_variable_actually_used():
    """codex BLOCKER #1 fix: postmortem_done must be USED, not just declared."""
    body = _read(STOP_HOOK)
    # Variable declared
    assert "postmortem_done=" in body
    # Variable used in a condition check (after declaration, not just declared)
    decl_idx = body.find('postmortem_done="0"')
    assert decl_idx > 0
    body_after_decl = body[decl_idx:]
    assert '"$postmortem_done"' in body_after_decl, "postmortem_done declared but never checked"


def test_is_final_wave_default_true_when_file_missing():
    """File missing → default true (full-build assumption). User pain when
    is_final_wave defaulted false on full run made post-build skipped."""
    body = _read(STOP_HOOK)
    # Default assignment before file read
    assert 'is_final_wave="true"' in body
    # File read with || true to preserve default
    assert ".is-final-wave" in body
