"""tests/test_batch49_partial_marker_status.py — Batch 49.

PARTIAL markers in verify.md fire even when checker absent (silent skip).
Audit gap (Batch 33 deferred): 2c_verify_plan_paths, 2c_utility_reuse,
2c_compile_check.

Fix: each step emits SKIPPED event + sets STATUS var so step-status-ledger
captures the absence. Mark still fires (these are advisory), but observability
restored.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "commands" / "vg" / "_shared" / "blueprint" / "verify.md"
VERIFY_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "verify.md"


def test_2c_verify_plan_paths_emits_skipped_when_checker_absent():
    body = VERIFY.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2c_verify_plan_paths")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 2000]
    # Must have status var + emit event on missing checker
    assert "PATH_STATUS" in block or "PLAN_PATH_STATUS" in block, (
        "Batch 49: 2c_verify_plan_paths must set status var"
    )
    assert "path_checker_absent" in block or "verify_plan_paths_skipped" in block, (
        "Batch 49: 2c_verify_plan_paths must emit event when checker absent"
    )


def test_2c_utility_reuse_emits_skipped_when_missing():
    body = VERIFY.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2c_utility_reuse")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 2500]
    assert "UTIL_STATUS" in block or "UTILITY_STATUS" in block, (
        "Batch 49: 2c_utility_reuse must set status var"
    )
    assert "utility_checker_absent" in block or "utility_reuse_skipped" in block, (
        "Batch 49: must emit event on missing checker/PROJECT.md"
    )


def test_2c_compile_check_emits_when_compile_cmd_empty():
    body = VERIFY.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2c_compile_check")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 5000]
    assert "COMPILE_STATUS" in block or "COMPILE_CHECK_STATUS" in block, (
        "Batch 49: 2c_compile_check must set status var"
    )
    assert "compile_cmd_unset" in block or "compile_check_skipped" in block, (
        "Batch 49: must emit event when COMPILE_CMD empty (no compile run)"
    )


def test_mirror_in_sync():
    assert VERIFY.read_text(encoding="utf-8") == VERIFY_MIRROR.read_text(encoding="utf-8")
