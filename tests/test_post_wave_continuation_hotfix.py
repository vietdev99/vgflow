"""Regression test for v4.21.0 hotfix — post-wave continuation enforcement.

Real-world dogfood feedback (PrintwayV3 Phase 7 Wave 14):
- Build waves completed but AI ended turn before running STEP 5 post-execution.
- vg-build-post-executor never spawned → L2/L3/L5/L6 fidelity gates skipped.
- truthcheck never ran → no truthcheck.json artifact.
- User re-ran /vg:build → preflight blocked with stale markers error,
  suggested --reset-queue (DESTRUCTIVE — wipes wave commits) instead of
  --resume (correct).

Two fixes ship in v4.21.0:

1. **scripts/hooks/vg-stop.sh** — new check #4: when build command + waves
   done + 9_post_execution missing + is_final_wave=true → BLOCK Stop hook
   with POST-WAVE CONTINUATION failure. AI cannot end turn without
   completing STEP 5.

2. **commands/vg/_shared/build/preflight.md** — Step 2 marker sanity check
   now detects partial-build-state. When waves done + 9_post_execution
   missing, suggests --resume (continue) NOT --reset-queue (destroy).
"""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
STOP_HOOK = REPO / "scripts" / "hooks" / "vg-stop.sh"
STOP_MIRROR = REPO / ".claude" / "scripts" / "hooks" / "vg-stop.sh"
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "build" / "preflight.md"
PREFLIGHT_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "build" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_stop_hook_post_wave_continuation_check_present():
    body = _read(STOP_HOOK)
    assert "POST-WAVE CONTINUATION" in body, (
        "v4.21.0 hotfix: vg-stop.sh must contain POST-WAVE CONTINUATION failure "
        "block that fires when build waves done but STEP 5 not run"
    )
    # Must check 9_post_execution marker
    assert "9_post_execution" in body, (
        "Post-wave check must inspect 9_post_execution.done marker"
    )
    # Must check is_final_wave
    assert "is_final_wave" in body or "is-final-wave" in body, (
        "Must guard on is_final_wave to avoid blocking partial-wave runs"
    )


def test_stop_hook_post_wave_only_triggers_on_build_command():
    body = _read(STOP_HOOK)
    # The new block must be gated on command = vg:build (else triggers on every Stop)
    post_wave_idx = body.find("POST-WAVE CONTINUATION")
    assert post_wave_idx > 0
    # B68 widened window: cascade checks added 4b + 4c → comment block grew.
    # B82 widened again: wave-done marker filename fix added ~700 chars of
    # B82 explanatory comment between the $command guard and the
    # POST-WAVE CONTINUATION block. Search 2500 chars backward.
    block = body[max(0, post_wave_idx - 2500):post_wave_idx]
    assert ("\"$command\" = \"vg:build\"" in block or '"$command" = "build"' in block), (
        "POST-WAVE CONTINUATION check must gate on $command being vg:build"
    )


def test_preflight_distinguishes_resume_from_reset_queue():
    body = _read(PREFLIGHT)
    # Find the partial-build-state branch
    assert "partial state" in body.lower() or "wave(s) completed but STEP 5" in body, (
        "v4.21.0 hotfix: preflight Step 2 must detect partial-build state and "
        "suggest --resume (not --reset-queue) for waves-done + post-exec-missing"
    )
    # Must mention --resume in the new error path
    partial_idx = body.find("post-execution NOT done")
    if partial_idx < 0:
        partial_idx = body.find("partial state")
    assert partial_idx > 0
    block = body[partial_idx:partial_idx + 1000]
    assert "--resume" in block, (
        "partial-build-state error must instruct user to run --resume"
    )
    assert "--reset-queue" in block and "destructive" in block.lower() or "RESTART" in block.upper(), (
        "must mention --reset-queue is destructive alternative, not default"
    )


def test_mirrors_byte_identical():
    if STOP_MIRROR.is_file():
        assert _read(STOP_HOOK) == _read(STOP_MIRROR)
    if PREFLIGHT_MIRROR.is_file():
        assert _read(PREFLIGHT) == _read(PREFLIGHT_MIRROR)
