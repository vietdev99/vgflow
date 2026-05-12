"""tests/test_c9_marker_strict_run_id.py — Batch 9 C9 gap."""
from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
SCHEMA_SH = REPO / "commands" / "vg" / "_shared" / "lib" / "marker-schema.sh"
CLOSE = REPO / "commands" / "vg" / "_shared" / "test" / "close.md"


def test_close_gate_calls_verify_marker_strict():
    body = CLOSE.read_text(encoding="utf-8")
    # Must call verify_marker or verify_all_markers with strict mode
    assert "verify_marker" in body or "verify_all_markers" in body, (
        "C9: test/close.md terminal gate must invoke verify_marker/"
        "verify_all_markers (not bare [ -f marker.done ])"
    )
    # Must use VG_MARKER_STRICT=1 or pass strict flag
    assert "VG_MARKER_STRICT" in body or "--strict" in body or "strict" in body, (
        "C9: marker verification must run in strict mode (refuse legacy "
        "empty markers and forged markers)"
    )


def test_close_gate_checks_run_id():
    body = CLOSE.read_text(encoding="utf-8")
    # Must check run_id matches active run
    assert "VG_RUN_ID" in body or "run_id" in body, (
        "C9: close gate must require marker's run_id field to match "
        "active VG_RUN_ID — otherwise forged/stale markers pass"
    )


def test_schema_sh_has_run_id_match_helper():
    body = SCHEMA_SH.read_text(encoding="utf-8")
    # verify_marker should support run_id check
    assert "run_id" in body
    # New helper for full marker-set verify with run_id
    assert ("verify_marker_runid" in body or
            "verify_all_markers_strict_runid" in body or
            "expected_run_id" in body), (
        "C9: marker-schema.sh must export a helper that verifies marker "
        "run_id field matches the active VG_RUN_ID. Existing verify_marker "
        "supports the schema but doesn't enforce run_id match."
    )


def test_forged_empty_marker_rejected_in_strict_mode(tmp_path, monkeypatch):
    """Functional: forge empty marker, run verify in strict mode, expect non-zero."""
    phase_dir = tmp_path / "phase"
    marker_dir = phase_dir / ".step-markers"
    marker_dir.mkdir(parents=True)
    forged = marker_dir / "test_step.done"
    forged.write_text("")  # empty — legacy forge pattern

    bash_cmd = f"""
    set -e
    source '{SCHEMA_SH}'
    export VG_MARKER_STRICT=1
    verify_marker '{forged}' 'phase99' 'test_step'
    """
    r = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True)
    assert r.returncode != 0, (
        f"C9: forged empty marker must be REJECTED in strict mode. "
        f"verify_marker exit={r.returncode} stderr={r.stderr}"
    )
