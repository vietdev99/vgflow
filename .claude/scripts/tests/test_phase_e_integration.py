"""
Phase E v2.5 (2026-04-23) — Reactive telemetry suggestions skill wiring.

Validates that review.md + test.md + accept.md all read telemetry
suggestions at start-of-step and surface them (advisory only).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT  = Path(__file__).resolve().parents[3]
REVIEW_MD  = REPO_ROOT / ".claude" / "commands" / "vg" / "review.md"
TEST_MD    = REPO_ROOT / ".claude" / "commands" / "vg" / "test.md"
ACCEPT_MD  = REPO_ROOT / ".claude" / "commands" / "vg" / "accept.md"
SUGGEST_PY = REPO_ROOT / ".claude" / "scripts" / "telemetry-suggest.py"


def _extract_step(text: str, step_name: str) -> str:
    m = re.search(
        rf'<step name="{step_name}"[^>]*>(.*?)</step>',
        text, re.DOTALL,
    )
    return m.group(1) if m else ""


# ─── review.md 0c_telemetry_suggestions ─────────────────────────────────

class TestReviewTelemetry:
    def test_step_exists(self):
        body = _extract_step(REVIEW_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert len(body) > 50

    def test_invokes_telemetry_suggest(self):
        body = _extract_step(REVIEW_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "telemetry-suggest.py" in body

    def test_command_filter_vg_review(self):
        body = _extract_step(REVIEW_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "--command vg:review" in body

    def test_mentions_unquarantinable_safety(self):
        body = _extract_step(REVIEW_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "security" in body.lower() or "NEVER" in body

    def test_step_marker_written(self):
        body = _extract_step(REVIEW_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "0c_telemetry_suggestions.done" in body


# ─── test.md 0c_telemetry_suggestions ───────────────────────────────────

class TestTestMdTelemetry:
    def test_step_exists(self):
        body = _extract_step(TEST_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert len(body) > 50

    def test_invokes_telemetry_suggest(self):
        body = _extract_step(TEST_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "telemetry-suggest.py" in body

    def test_command_filter_vg_test(self):
        body = _extract_step(TEST_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "--command vg:test" in body

    def test_step_marker_written(self):
        body = _extract_step(TEST_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "0c_telemetry_suggestions.done" in body


# ─── accept.md 0c_telemetry_suggestions ─────────────────────────────────

class TestAcceptTelemetry:
    def test_step_exists(self):
        body = _extract_step(ACCEPT_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert len(body) > 50

    def test_invokes_telemetry_suggest(self):
        body = _extract_step(ACCEPT_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "telemetry-suggest.py" in body

    def test_command_filter_vg_accept(self):
        body = _extract_step(ACCEPT_MD.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "--command vg:accept" in body

    def test_positioned_before_artifact_precheck(self):
        text = ACCEPT_MD.read_text(encoding="utf-8")
        pos_tel = text.find('name="0c_telemetry_suggestions"')
        pos_art = text.find('name="1_artifact_precheck"')
        assert pos_tel != -1 and pos_art != -1
        assert pos_tel < pos_art


def test_telemetry_suggest_script_exists():
    assert SUGGEST_PY.exists(), f"telemetry-suggest.py not found: {SUGGEST_PY}"


def test_all_three_commands_have_advisory_markers():
    """All 3 commands must note suggestions are ADVISORY (not auto-applied)."""
    for path in (REVIEW_MD, TEST_MD, ACCEPT_MD):
        body = _extract_step(path.read_text(encoding="utf-8"),
                             "0c_telemetry_suggestions")
        assert "advisory" in body.lower() or "ADVISORY" in body or \
               "never" in body.lower(), (
            f"{path.name} telemetry step missing advisory/never note — "
            "users must know suggestions are not auto-applied"
        )
