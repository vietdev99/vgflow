"""tests/test_batch24_audit_wiring.py — Batch 24 audit wiring."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_release_workflow_runs_detector():
    wf = REPO / ".github" / "workflows" / "release.yml"
    if not wf.is_file():
        # CI workflow not in repo — skip
        return
    body = wf.read_text(encoding="utf-8")
    assert "scaffold-detector" in body, (
        "Batch 24: release.yml must run scripts/audit/scaffold-detector.py "
        "as pre-tag gate"
    )


def test_audit_scaffold_command_exists():
    cmd = REPO / "commands" / "vg" / "audit-scaffold.md"
    assert cmd.is_file(), (
        "Batch 24: /vg:audit-scaffold command must ship — operator-facing "
        "invocation of scaffold-detector"
    )
    body = cmd.read_text(encoding="utf-8")
    assert "scaffold-detector" in body, "command must invoke the script"
