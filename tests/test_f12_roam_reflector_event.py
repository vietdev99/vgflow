"""tests/test_f12_roam_reflector_event.py — F12 roam reflector event match."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
ROAM_CLOSE = REPO / "commands" / "vg" / "_shared" / "roam" / "close.md"
ROAM_MD = REPO / "commands" / "vg" / "roam.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_roam_close_emits_phase_roam_completed():
    body = _read(ROAM_CLOSE)
    assert "phase.roam_completed" in body, (
        "F12: roam/close.md must emit phase.roam_completed event so the "
        "reflector trigger in roam.md actually fires"
    )


def test_reflector_trigger_event_name_matches():
    """Either both files agree on phase.roam_completed, OR roam.md checks
    roam.session.completed instead."""
    close_body = _read(ROAM_CLOSE)
    md_body = _read(ROAM_MD)
    # roam.md trigger condition references some event name
    if "phase.roam_completed" in md_body:
        # close.md must emit phase.roam_completed
        assert "phase.roam_completed" in close_body, (
            "F12: roam.md reflector checks phase.roam_completed but "
            "roam/close.md doesn't emit it — meta-memory feedback loop dead"
        )
    elif "roam.session.completed" in md_body:
        assert "roam.session.completed" in close_body
