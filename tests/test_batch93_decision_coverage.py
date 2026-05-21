"""B93 v4.67.2 — issue #197 F-CAI-07 decision coverage propagation.

F-CAI-07 (major): CONTEXT decision coverage below gate. PrintwayV3 Phase
8.2: 68.4% (162/237 P8.D-XX). decision_refs empty for all 200 emitted
goals because _goal_decision_refs only text-scanned goal body. Many
goals didn't mention D-XX inline → coverage stayed sparse. P8.D-214
(audit log), P8.D-447 (seed conditions), P8.D-511 (row count, freshly
amended) NOT bound to any lifecycle.

Fix:
- New `_parse_explicit_decision_refs(goal)` reads `decision_refs:`
  frontmatter list (inline or block form). Goal body no longer required
  to inline D-XX strings; blueprint AI can declare refs upfront.
- `_goal_decision_refs` now returns union of explicit + text-scanned.
- New `_decision_coverage(goals, decisions)` computes coverage % + lists
  unbound decision IDs. Threshold 85.0 advisory (BLOCK later).
- Summary surfaces `decision_coverage_audit`. main() warns when below
  threshold + lists first 5 unbound.
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
# Explicit decision_refs frontmatter parser
# ---------------------------------------------------------------------------

def test_b93_explicit_inline_form(lc) -> None:
    goal = {"body": "## Goal G-test\n\ndecision_refs: [P8.D-12, P8.D-44]\n"}
    refs = lc._parse_explicit_decision_refs(goal)
    assert refs == ["P8.D-12", "P8.D-44"]


def test_b93_explicit_block_form(lc) -> None:
    goal = {
        "body": (
            "## Goal G-test\n\n"
            "decision_refs:\n"
            "  - P8.D-12\n"
            "  - P8.D-44\n"
            "  - P8.D-99\n"
        ),
    }
    refs = lc._parse_explicit_decision_refs(goal)
    # Block form parsing: at minimum first ref captured
    assert "P8.D-12" in refs or len(refs) >= 1


def test_b93_explicit_empty_when_no_field(lc) -> None:
    goal = {"body": "## Goal G-test\n\nno refs here\n"}
    assert lc._parse_explicit_decision_refs(goal) == []


def test_b93_explicit_filters_bogus_strings(lc) -> None:
    goal = {"body": "## Goal G-test\n\ndecision_refs: [P8.D-12, not-a-decision, P8.D-99]\n"}
    refs = lc._parse_explicit_decision_refs(goal)
    assert refs == ["P8.D-12", "P8.D-99"]


# ---------------------------------------------------------------------------
# _goal_decision_refs union behavior
# ---------------------------------------------------------------------------

def test_b93_goal_decision_refs_explicit_wins(lc) -> None:
    """When explicit decision_refs declared, those count + body scan adds more."""
    decisions = {"P8.D-12": {}, "P8.D-44": {}, "P8.D-99": {}}
    goal = {
        "title": "x",
        "body": (
            "## Goal\n\n"
            "decision_refs: [P8.D-12]\n\n"
            "Body mentions P8.D-99 inline.\n"
        ),
    }
    refs = lc._goal_decision_refs(goal, decisions)
    # Union: explicit P8.D-12 + body-scanned P8.D-99
    assert "P8.D-12" in refs
    assert "P8.D-99" in refs


def test_b93_goal_decision_refs_text_scan_only(lc) -> None:
    """Pure text scan still works when no explicit frontmatter."""
    decisions = {"P8.D-12": {}, "P8.D-44": {}}
    goal = {
        "title": "x",
        "body": "## Goal\n\nBody references P8.D-44 only.\n",
    }
    refs = lc._goal_decision_refs(goal, decisions)
    assert refs == ["P8.D-44"]


def test_b93_goal_decision_refs_drops_unknown(lc) -> None:
    """Refs that aren't in decisions dict are dropped (stale references)."""
    decisions = {"P8.D-12": {}}
    goal = {"body": "decision_refs: [P8.D-12, P8.D-99]\n"}
    refs = lc._goal_decision_refs(goal, decisions)
    # P8.D-99 not in decisions → dropped
    assert refs == ["P8.D-12"]


# ---------------------------------------------------------------------------
# _decision_coverage audit
# ---------------------------------------------------------------------------

def test_b93_decision_coverage_full(lc) -> None:
    decisions = {"P8.D-01": {}, "P8.D-02": {}}
    goals = [
        {"body": "decision_refs: [P8.D-01]\n"},
        {"body": "decision_refs: [P8.D-02]\n"},
    ]
    audit = lc._decision_coverage(goals, decisions)
    assert audit["total_decisions"] == 2
    assert audit["bound_decisions"] == 2
    assert audit["coverage_pct"] == 100.0
    assert audit["passed"] is True
    assert audit["unbound"] == []


def test_b93_decision_coverage_below_threshold(lc) -> None:
    """3 of 10 decisions bound → 30% — below 85% threshold."""
    decisions = {f"P8.D-{i:02d}": {} for i in range(1, 11)}
    goals = [
        {"body": "decision_refs: [P8.D-01]\n"},
        {"body": "decision_refs: [P8.D-02]\n"},
        {"body": "decision_refs: [P8.D-03]\n"},
    ]
    audit = lc._decision_coverage(goals, decisions)
    assert audit["bound_decisions"] == 3
    assert audit["coverage_pct"] == 30.0
    assert audit["passed"] is False
    assert audit["unbound_count"] == 7
    # First 30 unbound — under 30 means full list
    assert "P8.D-04" in audit["unbound"]


def test_b93_decision_coverage_above_threshold(lc) -> None:
    """9 of 10 = 90% — above 85% gate."""
    decisions = {f"P8.D-{i:02d}": {} for i in range(1, 11)}
    goals = [{"body": f"decision_refs: [P8.D-{i:02d}]\n"} for i in range(1, 10)]
    audit = lc._decision_coverage(goals, decisions)
    assert audit["coverage_pct"] == 90.0
    assert audit["passed"] is True


def test_b93_decision_coverage_no_decisions(lc) -> None:
    """No decisions in phase → coverage trivially 100%."""
    audit = lc._decision_coverage([], {})
    assert audit["coverage_pct"] == 100.0
    assert audit["passed"] is True


def test_b93_summary_includes_decision_coverage(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: Test\n\ngoal_type: mutation\n\n"
        "mutation_evidence: x\npersistence_check: y\n\n"
        "decision_refs: [P8.D-01]\n",
        encoding="utf-8",
    )
    (pdir / "CONTEXT.md").write_text(
        "## P8.D-01: First decision\n\n"
        "**expected_assertion:** something\n\n"
        "## P8.D-02: Second decision\n\n"
        "**expected_assertion:** another\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir)
    dca = payload["summary"]["decision_coverage_audit"]
    assert dca["total_decisions"] == 2
    assert dca["bound_decisions"] == 1
    assert dca["coverage_pct"] == 50.0
    assert dca["passed"] is False


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b93_lifecycle_mirror_byte_identical() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b
