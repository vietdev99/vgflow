"""B116 v4.73.0 — cleaner /vg:debug handling.

Tests cover:
  - symptom_hash determinism + normalization
  - rank_resume_candidates scoring (recency × iter × similarity)
  - detect_duplicate_session matches by hash or similarity ≥ threshold
  - should_silent_continue gating logic
  - batch_checkpoints merges same-reason within window
  - Wiring in preflight.md + verify-and-close.md
  - Mirror parity
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def session():
    spec = importlib.util.spec_from_file_location(
        "debug_session", REPO_ROOT / "scripts" / "lib" / "debug_session.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# symptom_hash
# ---------------------------------------------------------------------------

def test_b116_symptom_hash_deterministic(session) -> None:
    h1 = session.symptom_hash("click button broken on /users page")
    h2 = session.symptom_hash("click button broken on /users page")
    assert h1 == h2 and len(h1) == 16


def test_b116_symptom_hash_normalizes_order(session) -> None:
    """Same tokens in different order → same hash."""
    h1 = session.symptom_hash("foo bar baz")
    h2 = session.symptom_hash("baz foo bar")
    assert h1 == h2


def test_b116_symptom_hash_filters_stopwords(session) -> None:
    h1 = session.symptom_hash("foo bar")
    h2 = session.symptom_hash("the foo and bar")
    assert h1 == h2


def test_b116_symptom_hash_empty_returns_sentinel(session) -> None:
    assert session.symptom_hash("") == "empty"
    assert session.symptom_hash("the the the") == "empty"


# ---------------------------------------------------------------------------
# rank_resume_candidates
# ---------------------------------------------------------------------------

def _seed_session(
    sessions_dir: Path,
    debug_id: str,
    description: str,
    iter_count: int = 0,
    status: str = "OPEN",
    age_seconds: float = 0,
) -> None:
    s = sessions_dir / debug_id
    s.mkdir(parents=True, exist_ok=True)
    log = s / "DEBUG-LOG.md"
    iters_md = "".join(
        f"### Iteration {i} — 2026-05-30T10:00:00Z\n"
        for i in range(1, iter_count + 1)
    )
    log.write_text(
        f"# Debug session {debug_id}\n\n"
        f"**Started:** 2026-05-30T10:00:00Z\n"
        f"**Description:** {description}\n"
        f"**Classification:** runtime_ui (85%)\n"
        f"**Status:** {status}\n\n"
        f"## Iterations\n{iters_md}\n",
        encoding="utf-8",
    )
    if age_seconds > 0:
        now = time.time()
        new_t = now - age_seconds
        import os
        os.utime(str(log), (new_t, new_t))


def test_b116_rank_returns_only_open(session, tmp_path: Path) -> None:
    """RESOLVED + ABANDONED + SPEC_GAP_ROUTED filtered out."""
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-001", "click users broken", status="OPEN")
    _seed_session(sessions_dir, "dbg-002", "click users broken", status="RESOLVED at iteration 3")
    _seed_session(sessions_dir, "dbg-003", "click users broken", status="ABANDONED")
    _seed_session(sessions_dir, "dbg-004", "click users broken", status="SPEC_GAP_ROUTED_TO_AMEND")
    result = session.rank_resume_candidates(sessions_dir, "click users broken")
    ids = [c["debug_id"] for c in result]
    assert "dbg-001" in ids
    assert "dbg-002" not in ids
    assert "dbg-003" not in ids
    assert "dbg-004" not in ids


def test_b116_rank_duplicate_gets_score_boost(session, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-dup", "form submit 500 broken", iter_count=2)
    _seed_session(sessions_dir, "dbg-other", "completely unrelated stuff", iter_count=2)
    result = session.rank_resume_candidates(sessions_dir, "form submit 500 broken")
    assert result[0]["debug_id"] == "dbg-dup"
    assert result[0]["is_duplicate_of_current"] is True


def test_b116_rank_recency_beats_old(session, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-fresh", "abc def ghi", iter_count=1, age_seconds=3600)
    _seed_session(sessions_dir, "dbg-stale", "abc def ghi", iter_count=1, age_seconds=5 * 86400)
    result = session.rank_resume_candidates(sessions_dir, "abc def ghi")
    # Fresh should appear above stale
    fresh_idx = next(i for i, c in enumerate(result) if c["debug_id"] == "dbg-fresh")
    stale_idx = next(i for i, c in enumerate(result) if c["debug_id"] == "dbg-stale")
    assert fresh_idx < stale_idx


def test_b116_rank_drops_too_old(session, tmp_path: Path) -> None:
    """> max_age_days → excluded."""
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-ancient", "abc", age_seconds=10 * 86400)
    result = session.rank_resume_candidates(sessions_dir, "abc", max_age_days=7)
    assert all(c["debug_id"] != "dbg-ancient" for c in result)


# ---------------------------------------------------------------------------
# detect_duplicate_session
# ---------------------------------------------------------------------------

def test_b116_detect_dup_returns_id_on_hash_match(session, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-x", "form submit 500 error")
    dup = session.detect_duplicate_session("form submit 500 error", sessions_dir)
    assert dup == "dbg-x"


def test_b116_detect_dup_returns_none_for_distinct(session, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "debug"
    _seed_session(sessions_dir, "dbg-y", "totally different problem here")
    dup = session.detect_duplicate_session("nothing alike whatsoever", sessions_dir)
    assert dup is None


def test_b116_detect_dup_empty_sessions_dir(session, tmp_path: Path) -> None:
    assert session.detect_duplicate_session("anything", tmp_path / "nonexistent") is None


# ---------------------------------------------------------------------------
# should_silent_continue
# ---------------------------------------------------------------------------

def test_b116_silent_continue_yes_high_conf_pass_early(session) -> None:
    assert session.should_silent_continue(95, True, 1) is True


def test_b116_silent_continue_no_low_conf(session) -> None:
    assert session.should_silent_continue(70, True, 1) is False


def test_b116_silent_continue_no_verify_failed(session) -> None:
    assert session.should_silent_continue(95, False, 1) is False


def test_b116_silent_continue_no_late_iteration(session) -> None:
    assert session.should_silent_continue(95, True, 5) is False


# ---------------------------------------------------------------------------
# batch_checkpoints
# ---------------------------------------------------------------------------

def test_b116_batch_checkpoints_merges_same_reason_in_window(session) -> None:
    base = 1000
    pending = [
        {"timestamp": base, "reason": "ui-verify", "iter": 1, "instructions": "test /users"},
        {"timestamp": base + 30, "reason": "ui-verify", "iter": 2, "instructions": "test /users"},
        {"timestamp": base + 50, "reason": "ui-verify", "iter": 3, "instructions": "test /campaigns"},
    ]
    batches = session.batch_checkpoints(pending, window_sec=60)
    assert len(batches) == 1
    assert batches[0]["iters"] == [1, 2, 3]
    assert "/users" in batches[0]["combined_instructions"]
    assert "/campaigns" in batches[0]["combined_instructions"]


def test_b116_batch_checkpoints_splits_outside_window(session) -> None:
    base = 1000
    pending = [
        {"timestamp": base, "reason": "ui-verify", "iter": 1, "instructions": "a"},
        {"timestamp": base + 200, "reason": "ui-verify", "iter": 2, "instructions": "b"},
    ]
    batches = session.batch_checkpoints(pending, window_sec=60)
    assert len(batches) == 2


def test_b116_batch_checkpoints_splits_on_different_reason(session) -> None:
    base = 1000
    pending = [
        {"timestamp": base, "reason": "ui-verify", "iter": 1},
        {"timestamp": base + 10, "reason": "network-verify", "iter": 2},
    ]
    batches = session.batch_checkpoints(pending, window_sec=60)
    assert len(batches) == 2


def test_b116_batch_checkpoints_empty(session) -> None:
    assert session.batch_checkpoints([]) == []


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_b116_preflight_invokes_rank_picker() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "preflight.md").read_text(encoding="utf-8")
    assert "debug_session.py rank" in body
    assert "B116 ranked" in body


def test_b116_preflight_invokes_dup_detector() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "preflight.md").read_text(encoding="utf-8")
    assert "debug_session.py dup" in body
    assert "B116 duplicate detected" in body


def test_b116_verify_close_invokes_silent_continue() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "verify-and-close.md").read_text(encoding="utf-8")
    assert "debug_session.py silent" in body
    assert "B116 silent" in body
    assert "SILENT_PASS" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "scripts/lib/debug_session.py",
    "commands/vg/_shared/debug/preflight.md",
    "commands/vg/_shared/debug/verify-and-close.md",
])
def test_b116_mirror_parity(rel: str) -> None:
    a = (REPO_ROOT / rel).read_bytes()
    b = (REPO_ROOT / ".claude" / rel).read_bytes()
    assert a == b, f"Mirror drift on {rel}"
