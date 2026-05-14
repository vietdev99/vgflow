"""tests/test_batch30_goal_verification_default.py — Audit gap #4.

5c_goal_verification default = trust-review (skip_ready_reverify=true).
READY goals become PASSED from review evidence — not actually re-played
in Playwright runs. Audit recommends per-goal replay by default;
trust-review opt-in only.

Fix: flip default to 'false' (per-goal replay) when config absent.
Preserve --trust-review flag escape hatch for legacy projects.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OVERVIEW = REPO / "commands" / "vg" / "_shared" / "test" / "goal-verification" / "overview.md"
OVERVIEW_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "goal-verification" / "overview.md"


def test_trust_review_default_false():
    """Default TRUST_REVIEW must be 'false' (per-goal replay), not 'true'.
    Projects opt into trust-review explicitly via config or --trust-review."""
    body = OVERVIEW.read_text(encoding="utf-8")
    skip_idx = body.find("SKIP_REVERIFY")
    assert skip_idx > 0
    block = body[skip_idx:skip_idx + 800]
    # The fallback when config absent must default to 'false' now
    assert "'false'" in block or "\"false\"" in block, (
        "Batch 30: default TRUST_REVIEW must be 'false' (per-goal replay) "
        "when config absent. Currently defaults to 'true' → READY goals "
        "trust review evidence without actual Playwright replay."
    )


def test_trust_review_arg_escape():
    """--trust-review arg must opt into trust-review mode (legacy)."""
    body = OVERVIEW.read_text(encoding="utf-8")
    assert "--trust-review" in body, (
        "Batch 30: --trust-review escape hatch must be honored so legacy "
        "projects can preserve old behavior"
    )


def test_default_change_warning():
    """When TRUST_REVIEW default flipped to false, emit migration warning
    so users know about the behavior change."""
    body = OVERVIEW.read_text(encoding="utf-8")
    assert (
        "per-goal replay" in body
        or "Batch 30" in body
        or "replay mode" in body
    ), "Batch 30: must include narration explaining per-goal replay default"


def test_mirror_in_sync():
    assert OVERVIEW.read_text(encoding="utf-8") == OVERVIEW_MIRROR.read_text(encoding="utf-8")
