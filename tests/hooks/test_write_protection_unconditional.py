"""Regression — write hook blocks protected paths regardless of session.

R5.5 design §3.3 explicit decision: write protection is filesystem-
scoped, not session-scoped. Any caller (VG or not) writing to
.vg/runs/*/evidence-* or .vg/events.db corrupts the signed evidence
pipeline. Hook MUST keep blocking even with no active VG run.
"""
import json

from .conftest import run_hook


def _write_input(file_path: str) -> str:
    return json.dumps({"tool_input": {"file_path": file_path}})


def test_write_blocks_evidence_path_without_active_run(tmp_workspace):
    """No .vg/active-runs/ — but still must block evidence-path writes."""
    result = run_hook(
        "write",
        stdin=_write_input(".vg/runs/run-x/evidence-foo.json"),
    )
    assert result.returncode == 2, (
        f"write hook should block protected path even without VG run; "
        f"got rc={result.returncode}, stderr={result.stderr!r}"
    )


def test_write_blocks_events_db_without_active_run(tmp_workspace):
    result = run_hook(
        "write",
        stdin=_write_input(".vg/events.db"),
    )
    assert result.returncode == 2


def test_write_allows_non_protected_path_without_active_run(tmp_workspace):
    """Non-protected path: hook silent (exit 0) regardless of VG state."""
    result = run_hook(
        "write",
        stdin=_write_input("src/feature/x.ts"),
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_write_allows_non_protected_path_with_active_run(vg_active_run):
    result = run_hook(
        "write",
        stdin=_write_input("src/feature/x.ts"),
    )
    assert result.returncode == 0
