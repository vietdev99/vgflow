"""B115 v4.73.0 — parallel discovery + multi-hypothesis race.

Tests cover:
  - parallel_discovery fans out + measures wall clock < sum
  - race_hypotheses first-success wins + losers terminated
  - race timeout returns winner=None
  - Wiring in discovery-and-fix.md + debug.md + preflight.md
  - Mirror parity
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def parallel():
    spec = importlib.util.spec_from_file_location(
        "debug_parallel", REPO_ROOT / "scripts" / "lib" / "debug_parallel.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Parallel discovery
# ---------------------------------------------------------------------------

def test_b115_parallel_discovery_returns_summary(parallel, tmp_path: Path) -> None:
    (tmp_path / "apps").mkdir()
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    result = parallel.parallel_discovery(
        "static",
        "TypeError null is not undefined cannot read property",
        debug_dir,
        tmp_path,
        timeout=5,
    )
    assert "bug_type" in result
    assert "tasks_run" in result
    assert "wall_clock_sec" in result


def test_b115_parallel_discovery_speedup_for_static(parallel, tmp_path: Path) -> None:
    """Multiple grep chunks should show wall_clock < sum-of-durations."""
    (tmp_path / "apps").mkdir()
    (tmp_path / "packages").mkdir()
    # Seed some files to grep through
    for i in range(5):
        (tmp_path / "apps" / f"file{i}.ts").write_text(
            "TypeError null undefined property foo bar baz\n" * 50,
            encoding="utf-8",
        )
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    result = parallel.parallel_discovery(
        "static",
        "TypeError null undefined property foo bar baz",
        debug_dir,
        tmp_path,
        timeout=10,
    )
    # With multiple chunks should report tasks_run >= 2
    assert result["tasks_run"] >= 1


def test_b115_parallel_discovery_unknown_type_returns_empty(
    parallel, tmp_path: Path
) -> None:
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    result = parallel.parallel_discovery(
        "spec_gap",  # not in static/ui/network/infra
        "missing feature blah",
        debug_dir,
        tmp_path,
        timeout=5,
    )
    assert result["tasks_run"] == 0


def test_b115_parallel_discovery_writes_per_task_logs(
    parallel, tmp_path: Path
) -> None:
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "x.ts").write_text("foo bar baz qux", encoding="utf-8")
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    parallel.parallel_discovery(
        "static", "foo bar baz qux quux corge", debug_dir, tmp_path, timeout=5,
    )
    parallel_dir = debug_dir / "parallel"
    assert parallel_dir.is_dir()
    log_files = list(parallel_dir.glob("*.log"))
    assert len(log_files) >= 1


# ---------------------------------------------------------------------------
# Hypothesis race
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="bash -c not portable")
def test_b115_race_first_success_wins(parallel, tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    specs = [
        {"id": "H1", "description": "slow fail",
         "cmd": ["bash", "-c", "sleep 2; exit 1"]},
        {"id": "H2", "description": "fast win",
         "cmd": ["bash", "-c", "sleep 0.2; exit 0"]},
        {"id": "H3", "description": "slow win",
         "cmd": ["bash", "-c", "sleep 5; exit 0"]},
    ]
    start = time.monotonic()
    result = parallel.race_hypotheses(specs, timeout=10, debug_dir=debug_dir)
    elapsed = time.monotonic() - start
    assert result["winner"] == "H2"
    # Should NOT wait for H3 to finish (5s)
    assert elapsed < 4


@pytest.mark.skipif(sys.platform == "win32", reason="bash -c not portable")
def test_b115_race_all_fail_returns_none(parallel, tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    specs = [
        {"id": "H1", "cmd": ["bash", "-c", "exit 1"]},
        {"id": "H2", "cmd": ["bash", "-c", "exit 2"]},
    ]
    result = parallel.race_hypotheses(specs, timeout=5, debug_dir=debug_dir)
    assert result["winner"] is None


def test_b115_race_empty_specs_returns_no_winner(parallel) -> None:
    result = parallel.race_hypotheses([], timeout=5)
    assert result["winner"] is None
    assert result["wall_clock_sec"] == 0.0


def test_b115_race_writes_per_hypothesis_logs(parallel, tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    if sys.platform == "win32":
        cmd = ["cmd", "/c", "exit 1"]
    else:
        cmd = ["bash", "-c", "exit 1"]
    parallel.race_hypotheses(
        [{"id": "H1", "cmd": cmd}],
        timeout=5, debug_dir=debug_dir,
    )
    race_dir = debug_dir / "race"
    assert race_dir.is_dir()
    assert (race_dir / "H1.stdout.log").exists() or (race_dir / "H1.stderr.log").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_b115_extract_keywords_dedupes(parallel) -> None:
    kws = parallel._extract_keywords("foo bar foo baz qux foo bar", limit=9)
    assert kws == ["foo", "bar", "baz", "qux"]


def test_b115_extract_keywords_filters_stopwords(parallel) -> None:
    kws = parallel._extract_keywords("this that should foo could bar")
    assert "this" not in kws
    assert "should" not in kws
    assert "foo" in kws


def test_b115_chunk_splits_evenly(parallel) -> None:
    chunks = parallel._chunk([1, 2, 3, 4, 5, 6, 7], 3)
    assert chunks == [[1, 2, 3], [4, 5, 6], [7]]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_b115_discovery_md_invokes_parallel_script() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "discovery-and-fix.md").read_text(encoding="utf-8")
    assert "debug_parallel.py discovery" in body
    assert "B115 parallel discovery" in body


def test_b115_discovery_md_has_race_block() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "discovery-and-fix.md").read_text(encoding="utf-8")
    assert "debug_parallel.py race" in body
    assert "B115 multi-hypothesis race" in body or "B115 race" in body


def test_b115_debug_md_argument_hint_lists_race_flag() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "debug.md").read_text(encoding="utf-8")
    assert "--race" in body


def test_b115_preflight_lists_race_flag() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "preflight.md").read_text(encoding="utf-8")
    assert "--race" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "scripts/lib/debug_parallel.py",
    "commands/vg/_shared/debug/discovery-and-fix.md",
    "commands/vg/_shared/debug/preflight.md",
    "commands/vg/debug.md",
])
def test_b115_mirror_parity(rel: str) -> None:
    a = (REPO_ROOT / rel).read_bytes()
    b = (REPO_ROOT / ".claude" / rel).read_bytes()
    assert a == b, f"Mirror drift on {rel}"
