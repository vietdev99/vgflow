"""v3.6.0 — #173 Stage 6 / #169: marker → lifecycle event auto-emission.

Coverage:
1. MARKER_TO_AUTO_EVENT mapping exists with required entries
2. mark-step CLI source references MARKER_TO_AUTO_EVENT
3. cmd_mark_step source has auto-emit code path (no double-emit)
4. canonical/mirror byte-identity for __main__.py + telemetry-repair.py
5. telemetry-repair script exists + has --check + --dry-run + --json args
6. telemetry-repair mapping matches __main__.py MARKER_TO_AUTO_EVENT
7. close.md still emits review.completed (defensive — proves auto-emit
   is idempotent, not a replacement)
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ORCH_MAIN = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
ORCH_MAIN_MIRROR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
REPAIR = REPO_ROOT / "scripts" / "vg-orchestrator-telemetry-repair.py"
REPAIR_MIRROR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator-telemetry-repair.py"
CLOSE_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "close.md"


REQUIRED_EVENTS = {
    "build.completed",
    "review.completed",
    "test.completed",
    "accept.completed",
    "blueprint.completed",
    "deploy.completed",
    "next.completed",
    "review.qa_check_completed",
    "review.recursive_probe_completed",
    "review.pre_dispatch_passed",
    "review.goal_comparison_completed",
}


def test_marker_to_auto_event_mapping_exists():
    body = ORCH_MAIN.read_text(encoding="utf-8")
    assert "MARKER_TO_AUTO_EVENT" in body, (
        "__main__.py must declare MARKER_TO_AUTO_EVENT mapping"
    )
    for ev in REQUIRED_EVENTS:
        assert ev in body, f"__main__.py must map a marker to {ev}"


def test_cmd_mark_step_auto_emits():
    body = ORCH_MAIN.read_text(encoding="utf-8")
    # Find cmd_mark_step body and verify auto-emit code path is there
    m = re.search(r"def cmd_mark_step\(args\)[\s\S]+?\n(?=def )", body)
    assert m, "cmd_mark_step function not found"
    fn_body = m.group(0)
    assert "MARKER_TO_AUTO_EVENT" in fn_body, (
        "cmd_mark_step must reference MARKER_TO_AUTO_EVENT mapping"
    )
    assert "_has_event_for_run" in fn_body, (
        "cmd_mark_step must use idempotency probe (_has_event_for_run)"
    )
    assert "auto_emitted" in fn_body, (
        "auto-emitted events must set auto_emitted=True in payload for audit"
    )


def test_idempotency_probe_exists():
    body = ORCH_MAIN.read_text(encoding="utf-8")
    assert "def _has_event_for_run" in body, (
        "__main__.py must define _has_event_for_run idempotency probe"
    )


def test_main_mirror_byte_identity():
    assert ORCH_MAIN.read_bytes() == ORCH_MAIN_MIRROR.read_bytes(), (
        "vg-orchestrator/__main__.py canonical and .claude/ mirror must match"
    )


def test_repair_script_exists():
    assert REPAIR.is_file()
    body = REPAIR.read_text(encoding="utf-8")
    assert "def main()" in body
    assert "find_missing_events" in body
    assert "repair_events" in body
    assert "--check" in body
    assert "--dry-run" in body
    assert "--json" in body


def test_repair_mapping_matches_orchestrator():
    """Repair script's MARKER_TO_EVENT must cover every event in
    orchestrator's MARKER_TO_AUTO_EVENT — otherwise repair leaves gaps."""
    repair_body = REPAIR.read_text(encoding="utf-8")
    for ev in REQUIRED_EVENTS:
        assert ev in repair_body, f"telemetry-repair must map a marker to {ev}"


def test_repair_mirror_byte_identity():
    assert REPAIR.read_bytes() == REPAIR_MIRROR.read_bytes()


def test_close_md_still_emits_review_completed():
    """Defensive: auto-emit is the safety net, not a replacement. close.md's
    bash block should continue emitting review.completed in the normal path
    so older harness installs and explicit emission both work."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert 'emit-event "review.completed"' in body, (
        "close.md must continue emitting review.completed (auto-emit is idempotent fallback)"
    )
