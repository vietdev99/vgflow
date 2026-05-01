"""Tests for scripts/runtime/tester_pro.py — RFC v9 D17–D23."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.tester_pro import (  # noqa: E402
    Defect,
    TestSummary,
    TraceabilityRow,
    assert_required_coverage,
    coverage_by_test_type,
    detect_orphan_goals,
    detect_orphan_requirements,
    new_defect_id,
    parse_test_type_from_goal_body,
    render_defect_log,
    render_rtm,
    render_summary_report,
    reverse_index,
)


# ─── D18 test_type ────────────────────────────────────────────────


def test_parse_test_type_recognized():
    body = "...some prose...\n**Test type:** smoke\n..."
    assert parse_test_type_from_goal_body(body) == "smoke"


def test_parse_test_type_case_insensitive_keyword():
    body = "**TEST TYPE:** Negative"
    assert parse_test_type_from_goal_body(body) == "negative"


def test_parse_test_type_unknown_returns_none():
    body = "**Test type:** sanity"  # not in TEST_TYPES
    assert parse_test_type_from_goal_body(body) is None


def test_parse_test_type_missing_returns_none():
    assert parse_test_type_from_goal_body("no directive here") is None


def test_coverage_by_test_type():
    goals = [
        {"id": "G-1", "test_type": "smoke"},
        {"id": "G-2", "test_type": "smoke"},
        {"id": "G-3", "test_type": "happy"},
        {"id": "G-4", "test_type": "edge"},
        {"id": "G-5"},  # untyped
    ]
    counts = coverage_by_test_type(goals)
    assert counts["smoke"] == 2
    assert counts["happy"] == 1
    assert counts["edge"] == 1
    assert counts["negative"] == 0


def test_assert_required_coverage_passes():
    counts = {"smoke": 2, "happy": 3, "edge": 4}
    missing = assert_required_coverage(counts, requirements={"smoke": 1, "happy": 1})
    assert missing == []


def test_assert_required_coverage_misses():
    counts = {"smoke": 0, "happy": 1, "edge": 0}
    missing = assert_required_coverage(
        counts, requirements={"smoke": 1, "edge": 2},
    )
    assert any("smoke" in m for m in missing)
    assert any("edge" in m for m in missing)


# ─── D21 DEFECT-LOG ───────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def test_new_defect_id_increments():
    existing = []
    assert new_defect_id(existing) == "D-001"
    existing.append(Defect(
        id="D-001", title="x", severity="high", discovered_at=_now(),
        discovered_in="review",
    ))
    assert new_defect_id(existing) == "D-002"


def test_new_defect_id_handles_gaps():
    existing = [Defect(
        id="D-005", title="x", severity="high", discovered_at=_now(),
        discovered_in="review",
    )]
    assert new_defect_id(existing) == "D-006"


def test_render_defect_log_includes_table_and_details():
    defects = [
        Defect(
            id="D-001",
            title="Idempotency missing on POST /topup",
            severity="high",
            discovered_at=_now(),
            discovered_in="review",
            repro_steps=["click submit twice", "observe two receipts"],
            root_cause="No backend dedup",
            fix_ref="commit-abc123",
            related_goals=["G-10", "G-11"],
        ),
    ]
    out = render_defect_log(defects)
    assert "D-001" in out
    assert "Idempotency" in out
    assert "Repro" in out
    assert "commit-abc123" in out
    assert "G-10" in out


def test_render_defect_log_open_marker():
    defects = [Defect(
        id="D-001", title="Open defect", severity="medium",
        discovered_at=_now(), discovered_in="review",
    )]
    out = render_defect_log(defects)
    assert "open" in out  # closed_at None → "open" in table


# ─── D22 TEST-SUMMARY ─────────────────────────────────────────────


def test_render_summary_report():
    summary = TestSummary(
        phase="3.2",
        generated_at=_now(),
        goals_total=50,
        goals_passed=42,
        goals_failed=3,
        goals_blocked=5,
        coverage_by_type={"smoke": 10, "happy": 25, "edge": 8, "negative": 5,
                            "security": 2, "perf": 0, "integration": 0},
        defects_opened=4,
        defects_closed=2,
        defects_open=2,
        notes="Phase 3.2 dogfood validated wave-3.2.3 fixes",
    )
    out = render_summary_report(summary)
    assert "3.2" in out
    assert "Passed: 42" in out
    assert "smoke: 10" in out
    assert "Notes" in out


# ─── D23 RTM ──────────────────────────────────────────────────────


def test_reverse_index_maps_leaves_to_requirements():
    rows = [
        TraceabilityRow(
            requirement_id="REQ-01",
            goal_ids=["G-10", "G-11"],
            test_case_ids=["TC-1"],
            fix_commits=["abc"],
        ),
        TraceabilityRow(
            requirement_id="REQ-02",
            goal_ids=["G-11", "G-12"],
            defect_ids=["D-005"],
        ),
    ]
    rev = reverse_index(rows)
    assert sorted(rev["G-11"]) == ["REQ-01", "REQ-02"]
    assert rev["G-10"] == ["REQ-01"]
    assert rev["abc"] == ["REQ-01"]
    assert rev["D-005"] == ["REQ-02"]


def test_detect_orphan_goals():
    rows = [TraceabilityRow(requirement_id="REQ-1", goal_ids=["G-1", "G-2"])]
    declared = {"G-1", "G-2", "G-3", "G-4"}
    assert detect_orphan_goals(rows, declared_goals=declared) == ["G-3", "G-4"]


def test_detect_orphan_requirements():
    rows = [TraceabilityRow(requirement_id="REQ-1")]
    declared = {"REQ-1", "REQ-2", "REQ-3"}
    assert detect_orphan_requirements(
        rows, declared_requirements=declared,
    ) == ["REQ-2", "REQ-3"]


def test_render_rtm():
    rows = [
        TraceabilityRow(
            requirement_id="REQ-01",
            goal_ids=["G-10"],
            test_case_ids=["TC-100"],
            fix_commits=["abc1234"],
        ),
    ]
    out = render_rtm(rows)
    assert "REQ-01" in out
    assert "G-10" in out
    assert "TC-100" in out
    assert "abc1234" in out
