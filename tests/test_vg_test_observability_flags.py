"""Batch 5 task 4: /vg:test must document + propagate observability flags."""
from __future__ import annotations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / "commands" / "vg" / "test.md"


def test_test_skill_documents_headed_flag():
    body = CANONICAL.read_text(encoding="utf-8")
    assert "--headed" in body
    assert "--headless" in body


def test_test_skill_documents_ui_flag():
    body = CANONICAL.read_text(encoding="utf-8")
    assert "--ui" in body
    # --ui spawns full Playwright inspector
    assert "playwright" in body.lower()


def test_test_skill_documents_slow_mo():
    body = CANONICAL.read_text(encoding="utf-8")
    assert "--slow-mo" in body
