"""
VG v2.6 Phase C — bootstrap-conflict-detector regression tests.

6 cases per PLAN-REVISED.md Phase C:
  1. No conflicts when rules disjoint → empty output
  2. Jaccard ≥ threshold + same verb → conflict pair detected
  3. Opposing verbs even with low Jaccard (e.g., "must X" vs "must not X" with
     ~0.55 Jaccard) → still flagged
  4. Winner determined by Phase A correctness when both have shadow telemetry
  5. Winner falls back to evidence_count when shadow data missing
  6. Tie → no winner declared, both surface to operator (winner = null)

All tests use VG_REPO_ROOT scoped to tmp_path; the script is invoked
in-process via importlib so no subprocess flakiness.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "bootstrap-conflict-detector.py"
)


@pytest.fixture
def detector(monkeypatch, tmp_path):
    """Import the script as a module with VG_REPO_ROOT scoped to tmp_path."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg" / "bootstrap").mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.write_text(
        "bootstrap:\n"
        "  conflict_similarity_threshold: 0.7\n",
        encoding="utf-8",
    )

    # Strip cached modules so REPO_ROOT picks up the env var fresh.
    sys.modules.pop("bootstrap_conflict_detector", None)

    spec = importlib.util.spec_from_file_location(
        "bootstrap_conflict_detector", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_conflict_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_rule(mod, cid, *, title="", prose="", evidence_count=0,
               correctness=None, status="pending"):
    rule = mod.CandidateRule(
        cid=cid,
        title=title,
        prose=prose,
        status=status,
        evidence_count=evidence_count,
        correctness=correctness,
    )
    return rule


# ---------------------------------------------------------------------------
# Case 1 — disjoint rules emit no conflicts.
# ---------------------------------------------------------------------------

def test_case_1_no_conflicts_when_disjoint(detector):
    rules = [
        _make_rule(
            detector, "L-001",
            title="API responses must include CORS headers in dev",
            prose="When the API runs in dev mode, every response must carry "
                  "Access-Control-Allow-Origin set to the configured origin.",
            evidence_count=3,
        ),
        _make_rule(
            detector, "L-002",
            title="Test specs require checkpoint files",
            prose="Multi-page Playwright flows always save a checkpoint JSON "
                  "after each page transition for resume support.",
            evidence_count=2,
        ),
    ]
    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert conflicts == []


# ---------------------------------------------------------------------------
# Case 2 — high Jaccard + same verb → flagged.
# ---------------------------------------------------------------------------

def test_case_2_high_similarity_same_verb(detector):
    rules = [
        _make_rule(
            detector, "L-010",
            title="Build wave parallelism must respect contract injection",
            prose="Build wave parallelism must respect contract injection so "
                  "downstream agents always see the resolved contract block.",
            evidence_count=5,
        ),
        _make_rule(
            detector, "L-011",
            title="Build wave parallelism must respect contract injection",
            prose="Build wave parallelism must respect contract injection. "
                  "Downstream agents must always see the resolved contract.",
            evidence_count=4,
        ),
    ]
    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert {c["id_a"], c["id_b"]} == {"L-010", "L-011"}
    assert c["similarity"] >= 0.7
    # Verbs matched but they agree — opposing_verb should be None.
    assert c["opposing_verb"] is None
    # Winner falls back to evidence_count (5 > 4 → L-010).
    assert c["winner"] == "L-010"


# ---------------------------------------------------------------------------
# Case 3 — opposing verbs with low Jaccard still flag.
# ---------------------------------------------------------------------------

def test_case_3_opposing_verb_low_similarity(detector):
    # Two rules talking about the same domain (CORS dev origins) but with
    # contradictory directives — must vs must not. Jaccard sits around 0.55,
    # which is below the conflict threshold of 0.7 but above the verb floor
    # (0.45) so the opposing-verb signal still trips.
    rules = [
        _make_rule(
            detector, "L-020",
            title="CORS dev origins must allow localhost",
            prose="CORS dev origins must allow localhost ports for the dev "
                  "stack. Without that the browser blocks requests.",
            evidence_count=3,
        ),
        _make_rule(
            detector, "L-021",
            title="CORS dev origins must not allow localhost",
            prose="CORS dev origins must not allow localhost ports outside "
                  "the configured allowlist. Drift breaks production.",
            evidence_count=2,
        ),
    ]
    sim = detector.prose_similarity(rules[0].prose, rules[1].prose)
    # Sanity check the test data — should be in the 0.45-0.7 band.
    assert detector.OPPOSING_VERB_FLOOR <= sim < 0.7, (
        f"test fixture drifted: sim={sim:.3f}, expected 0.45 ≤ sim < 0.7"
    )

    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["opposing_verb"] is not None
    assert "must" in c["opposing_verb"]


# ---------------------------------------------------------------------------
# Case 4 — winner via shadow correctness when both populated.
# ---------------------------------------------------------------------------

def test_case_4_winner_by_correctness(detector):
    rules = [
        _make_rule(
            detector, "L-030",
            title="Plan reviewer must always run typecheck",
            prose="Plan reviewer must always run typecheck before approving "
                  "any wave because incomplete typecheck masks real failures.",
            evidence_count=4,
            correctness=0.91,
        ),
        _make_rule(
            detector, "L-031",
            title="Plan reviewer must always run typecheck",
            prose="Plan reviewer must always run typecheck before approving "
                  "any wave to catch incomplete signatures.",
            evidence_count=10,   # higher count, but lower correctness
            correctness=0.62,
        ),
    ]
    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["winner"] == "L-030"
    assert c["correctness_a"] == 0.91
    assert c["correctness_b"] == 0.62


# ---------------------------------------------------------------------------
# Case 5 — winner via evidence_count when shadow data missing.
# ---------------------------------------------------------------------------

def test_case_5_winner_by_evidence_when_no_shadow(detector):
    rules = [
        _make_rule(
            detector, "L-040",
            title="Test runner must save checkpoint after each step",
            prose="Test runner must save checkpoint after each step. "
                  "Checkpoint enables resume support across long flow runs.",
            evidence_count=3,
            correctness=None,
        ),
        _make_rule(
            detector, "L-041",
            title="Test runner must save checkpoint after each step",
            prose="Test runner must save checkpoint after each step. "
                  "Checkpoint enables resume support across long flow runs.",
            evidence_count=8,
            correctness=None,
        ),
    ]
    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["winner"] == "L-041"
    assert c["correctness_a"] is None
    assert c["correctness_b"] is None
    assert c["evidence_count_b"] == 8


# ---------------------------------------------------------------------------
# Case 6 — tie produces no winner; operator surfaces both.
# ---------------------------------------------------------------------------

def test_case_6_tie_no_winner(detector):
    rules = [
        _make_rule(
            detector, "L-050",
            title="Reviewer must scan single-port viable tests before skip",
            prose="Reviewer must scan the spec for deferred annotations and "
                  "classify each test before invoking a wholesale skip.",
            evidence_count=2,
            correctness=None,
        ),
        _make_rule(
            detector, "L-051",
            title="Reviewer must scan single-port viable tests before skip",
            prose="Reviewer must scan the spec for deferred annotations and "
                  "classify each test before invoking a blanket skip path.",
            evidence_count=2,
            correctness=None,
        ),
    ]
    conflicts = detector.find_conflicts(rules, threshold=0.7)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["winner"] is None  # tie surfaces both to operator
    assert c["evidence_count_a"] == c["evidence_count_b"]
