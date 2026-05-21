"""B94 v4.67.3 — issue #197 F-CAI-09 read-only goal auto-detect.

F-CAI-09 (minor): PrintwayV3 Phase 8.2: 52 goals classified default
RCRURDR but actually read-only subset (list/display/dashboard/filter
with no mutation HTTP verb in evidence). Validator emitted 52 warnings.

Fix: new `_looks_read_only(goal)` heuristic auto-detect. Triggers
read-only stage set (`GOAL_TYPE_STAGES["read-only"]`) when:
  - goal_type empty AND goal_class empty (not explicit)
  - title matches read-only verb cue (list/display/dashboard/etc.)
  - AND title has NO mutation verb cue
  - AND mutation_evidence has no HTTP mutation verb

Marker `_b94_readonly_autodetected: True` set on goal for diagnostic
aggregation. Summary surfaces count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _looks_read_only heuristic
# ---------------------------------------------------------------------------

def test_b94_list_title_detected(lc) -> None:
    assert lc._looks_read_only({"title": "List approved topups"})


def test_b94_display_title_detected(lc) -> None:
    assert lc._looks_read_only({"title": "Display merchant dashboard"})


def test_b94_filter_title_detected(lc) -> None:
    assert lc._looks_read_only({"title": "Filter pending requests"})


def test_b94_dashboard_summary_detected(lc) -> None:
    assert lc._looks_read_only({"title": "Summary of last 30 days"})


def test_b94_mutation_title_not_detected(lc) -> None:
    """Mutation verb in title → not read-only."""
    assert not lc._looks_read_only({"title": "Create new topup"})
    assert not lc._looks_read_only({"title": "Delete bank account"})
    assert not lc._looks_read_only({"title": "Update credit limit"})


def test_b94_mixed_title_mutation_wins(lc) -> None:
    """List + Delete in same title → mutation cue wins, not read-only."""
    assert not lc._looks_read_only(
        {"title": "List and delete archived topups"}
    )


def test_b94_explicit_goal_class_skips_autodetect(lc) -> None:
    """If goal_class declared, auto-detect skips (don't override declarations)."""
    goal = {"title": "List topups", "goal_class": "feature_chain"}
    assert not lc._looks_read_only(goal)


def test_b94_post_verb_in_evidence_blocks_autodetect(lc) -> None:
    """Title says 'List' but evidence has POST → not read-only."""
    goal = {
        "title": "List endpoint with side effects",
        "mutation_evidence": "POST /api/v1/admin/topups/track-view 200",
    }
    assert not lc._looks_read_only(goal)


def test_b94_no_title_cue_no_autodetect(lc) -> None:
    """Neutral title without read or mutation cue → no autodetect."""
    assert not lc._looks_read_only({"title": "Goal G-001"})


# ---------------------------------------------------------------------------
# _stages_for_goal dispatch
# ---------------------------------------------------------------------------

def test_b94_stages_for_goal_uses_readonly_set(lc) -> None:
    """Goal without explicit goal_type but read-only title → read-only stages."""
    goal = {"title": "List approved topups for review"}
    stages = lc._stages_for_goal(goal)
    expected = lc.GOAL_TYPE_STAGES.get("read-only", ())
    # The stages should match read-only set, NOT REQUIRED_STAGES default
    assert stages == expected
    assert stages != lc.REQUIRED_STAGES


def test_b94_explicit_goal_type_wins_over_autodetect(lc) -> None:
    """If `goal_type: mutation` declared, autodetect doesn't override."""
    goal = {"title": "List topups", "goal_type": "mutation"}
    stages = lc._stages_for_goal(goal)
    expected = lc.GOAL_TYPE_STAGES.get("mutation", lc.REQUIRED_STAGES)
    assert stages == expected


def test_b94_autodetect_tagged_on_goal(lc) -> None:
    goal = {"title": "List items"}
    lc._stages_for_goal(goal)
    assert goal.get("_b94_readonly_autodetected") is True


# ---------------------------------------------------------------------------
# Summary aggregate
# ---------------------------------------------------------------------------

def test_b94_summary_aggregates_autodetect_count(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    # 2 read-only goals + 1 explicit mutation
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: List approved topups\n\n"
        "(no goal_type — should be autodetected)\n\n"
        "## Goal G-002: Display dashboard counters\n\n"
        "(no goal_type — should be autodetected)\n\n"
        "## Goal G-003: Create topup\n\ngoal_type: mutation\n"
        "mutation_evidence: POST /api/v1/admin/topups\n"
        "persistence_check: GET returns row\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir, include_readonly=True)
    assert payload["summary"]["readonly_autodetected_count"] >= 2


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b94_lifecycle_mirror_byte_identical() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b
