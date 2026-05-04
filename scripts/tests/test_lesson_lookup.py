"""
Failure-time lesson retrieval — R9-A.

Codex audit (2026-05-05) found the VG learn/lesson loop was PARTLY REAL,
NOT CLOSED: lessons captured + injected at spawn-time for scope/blueprint/
build/test, but failure recovery (block / override / retry) used a
STATIC violation→path mapping and never queried prior lessons. "fail →
learn → never fail again" was not guaranteed.

This module's tests cover the new `scripts/vg-orchestrator/lesson_lookup.py`
helper plus its three integration points:
  - `scripts/vg-recovery.py` (auto-pick + render menu + JSON output)
  - `scripts/vg-orchestrator/recovery_paths.py` (`render_recovery_block`)
  - `commands/vg/debug.md` (Step 0 lesson injection block)
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_DIR = REPO_ROOT / "scripts" / "vg-orchestrator"
LESSON_LOOKUP_PY = ORCH_DIR / "lesson_lookup.py"
RECOVERY_PATHS_PY = ORCH_DIR / "recovery_paths.py"
VG_RECOVERY_PY = REPO_ROOT / "scripts" / "vg-recovery.py"
DEBUG_MD = REPO_ROOT / "commands" / "vg" / "debug.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore
    return mod


@pytest.fixture
def lesson_lookup():
    """Load lesson_lookup as a module."""
    # Ensure repo orchestrator dir is on sys.path so the inner CLI can find it.
    sys.path.insert(0, str(ORCH_DIR))
    try:
        yield _load_module("lesson_lookup_test", LESSON_LOOKUP_PY)
    finally:
        if str(ORCH_DIR) in sys.path:
            sys.path.remove(str(ORCH_DIR))


def _write_accepted(tmp_path: Path, text: str) -> Path:
    bs = tmp_path / ".vg" / "bootstrap"
    bs.mkdir(parents=True, exist_ok=True)
    p = bs / "ACCEPTED.md"
    p.write_text(text, encoding="utf-8")
    return p


def _write_rule(tmp_path: Path, name: str, body: str) -> Path:
    rdir = tmp_path / ".vg" / "bootstrap" / "rules"
    rdir.mkdir(parents=True, exist_ok=True)
    p = rdir / name
    p.write_text(body, encoding="utf-8")
    return p


def _two_lesson_fixture() -> str:
    """Standard 2-lesson ACCEPTED.md content used by several tests."""
    return (
        "# Bootstrap Accepted\n\n"
        "- id: L-001\n"
        "  promoted_at: 2026-04-20T07:00:00Z\n"
        "  promoted_by: user\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/tdd-violation.md\n"
        "  reason: 'Always write test first; flags TDD-violation'\n"
        "  status: active\n"
        "  hits: 5\n"
        "  hit_outcomes:\n"
        "    success_count: 4\n"
        "    fail_count: 1\n"
        "\n"
        "- id: L-002\n"
        "  promoted_at: 2026-04-21T07:00:00Z\n"
        "  promoted_by: user\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/runtime-map-crud.md\n"
        "  reason: 'validator runtime-map-crud-depth needs goal_sequences'\n"
        "  status: active\n"
        "  hits: 3\n"
        "  hit_outcomes:\n"
        "    success_count: 3\n"
        "    fail_count: 0\n"
    )


def test_returns_empty_when_no_accepted_md(lesson_lookup, tmp_path, monkeypatch):
    """Graceful when bootstrap dir missing — must NOT raise."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    out = lesson_lookup.query_relevant_lessons(
        violation_type="anything", gate_id="any", limit=5
    )
    assert out == [], "Expected empty list when ACCEPTED.md absent"


def test_returns_empty_when_no_match(lesson_lookup, tmp_path, monkeypatch):
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(tmp_path, _two_lesson_fixture())
    out = lesson_lookup.query_relevant_lessons(
        violation_type="something-completely-unrelated-xyz",
        gate_id="zzz-no-match",
        limit=5,
    )
    assert out == []


def test_matches_by_violation_type(lesson_lookup, tmp_path, monkeypatch):
    """Lesson body / metadata mentioning violation_type → high confidence."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(tmp_path, _two_lesson_fixture())

    out = lesson_lookup.query_relevant_lessons(
        violation_type="TDD-violation", limit=5
    )
    ids = [l["lesson_id"] for l in out]
    assert "L-001" in ids, f"L-001 should match TDD-violation; got {ids}"
    matched = next(l for l in out if l["lesson_id"] == "L-001")
    assert matched["confidence"] == "high"
    assert matched["hits"] == 5
    assert matched["success_rate"] == 80.0


def test_matches_by_gate_id_in_body(lesson_lookup, tmp_path, monkeypatch):
    """gate_id substring match in metadata or rule body → returns lesson."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(tmp_path, _two_lesson_fixture())
    _write_rule(
        tmp_path, "runtime-map-crud.md",
        "---\nid: L-002\n---\nApplies when gate G-42-crud-depth fires.\n",
    )

    out = lesson_lookup.query_relevant_lessons(
        gate_id="g-42-crud-depth", limit=5
    )
    ids = [l["lesson_id"] for l in out]
    assert "L-002" in ids
    matched = next(l for l in out if l["lesson_id"] == "L-002")
    assert matched["confidence"] in ("medium", "high")


def test_sorts_by_confidence_then_efficacy(lesson_lookup, tmp_path, monkeypatch):
    """High-confidence (violation match) outranks medium (gate match);
    within same confidence, higher success_rate ranks first."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    text = (
        "# Bootstrap Accepted\n\n"
        "- id: L-100\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/r100.md\n"
        "  reason: 'Gate G-99 mention only'\n"
        "  status: active\n"
        "  hits: 10\n"
        "  hit_outcomes:\n"
        "    success_count: 10\n"
        "    fail_count: 0\n"
        "\n"
        "- id: L-200\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/r200.md\n"
        "  reason: 'TDD-violation root cause; gate G-99'\n"
        "  status: active\n"
        "  hits: 2\n"
        "  hit_outcomes:\n"
        "    success_count: 1\n"
        "    fail_count: 1\n"
        "\n"
        "- id: L-300\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/r300.md\n"
        "  reason: 'TDD-violation w/ perfect track record'\n"
        "  status: active\n"
        "  hits: 4\n"
        "  hit_outcomes:\n"
        "    success_count: 4\n"
        "    fail_count: 0\n"
    )
    _write_accepted(tmp_path, text)

    # First: violation+gate together (multi-signal rank). L-200 matches both.
    out = lesson_lookup.query_relevant_lessons(
        violation_type="TDD-violation", gate_id="G-99", limit=5
    )
    ids = [l["lesson_id"] for l in out]
    # L-200 matches violation (100) + gate (40) = highest combined signal score,
    # so it ranks first ahead of L-300 (violation-only) and L-100 (gate-only).
    assert ids[0] == "L-200", f"Expected L-200 first (multi-signal), got {ids}"
    # L-300 (violation-only, perfect efficacy) outranks L-100 (gate-only).
    assert ids.index("L-300") < ids.index("L-100"), (
        f"L-300 (high confidence) should outrank L-100 (medium); got {ids}"
    )

    # Second: with violation only, perfect-efficacy L-300 outranks L-200.
    out_v = lesson_lookup.query_relevant_lessons(
        violation_type="TDD-violation", limit=5
    )
    ids_v = [l["lesson_id"] for l in out_v]
    assert ids_v[0] == "L-300", (
        f"With same confidence, higher success_rate ranks first; got {ids_v}"
    )
    assert "L-100" not in ids_v, "L-100 only matches gate, must not appear"


def test_skips_retracted_status(lesson_lookup, tmp_path, monkeypatch):
    """Retracted/inactive rules must NOT influence recovery."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    text = (
        "# Bootstrap Accepted\n\n"
        "- id: L-001\n"
        "  reason: 'TDD-violation but retracted'\n"
        "  target:\n"
        "    file: rules/x.md\n"
        "  status: retracted\n"
        "  hits: 9\n"
        "\n"
        "- id: L-002\n"
        "  reason: 'TDD-violation active'\n"
        "  target:\n"
        "    file: rules/y.md\n"
        "  status: active\n"
        "  hits: 1\n"
    )
    _write_accepted(tmp_path, text)
    out = lesson_lookup.query_relevant_lessons(
        violation_type="TDD-violation", limit=5
    )
    ids = [l["lesson_id"] for l in out]
    assert "L-001" not in ids
    assert "L-002" in ids


def test_format_for_recovery_renders_block(lesson_lookup, tmp_path, monkeypatch):
    """Markdown rendering smoke — must contain header, IDs, efficacy line."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(tmp_path, _two_lesson_fixture())
    lessons = lesson_lookup.query_relevant_lessons(
        violation_type="TDD-violation", limit=5
    )
    md = lesson_lookup.format_lessons_for_recovery(lessons)

    assert "## Relevant prior lessons" in md
    assert "L-001" in md
    assert "Past efficacy" in md
    assert "5 hits" in md
    # Empty input → graceful fallback
    assert lesson_lookup.format_lessons_for_recovery([]) == "No relevant prior lessons found."


def test_recovery_paths_invokes_lookup(tmp_path, monkeypatch):
    """`render_recovery_block` from recovery_paths.py must surface lessons.

    We import recovery_paths as a module, point lesson_lookup at our tmp
    fixture via VG_REPO_ROOT + sys.path, then assert the rendered output
    contains a `📚 Prior lessons` line for a known violation_type.
    """
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(
        tmp_path,
        "# Bootstrap Accepted\n\n"
        "- id: L-077\n"
        "  type: rule\n"
        "  target:\n"
        "    file: rules/runtime-map.md\n"
        "  reason: 'validator:runtime-map-crud-depth root cause'\n"
        "  status: active\n"
        "  hits: 7\n"
        "  hit_outcomes:\n"
        "    success_count: 6\n"
        "    fail_count: 1\n",
    )

    sys.path.insert(0, str(ORCH_DIR))
    try:
        rp = _load_module("recovery_paths_test", RECOVERY_PATHS_PY)
        # Disable the real telemetry emitter so the test stays hermetic.
        rp._emit_lessons_consulted_event = lambda *a, **kw: None
        lines = rp.render_recovery_block(
            "validator:runtime-map-crud-depth",
            command="vg:review",
            phase="7.6",
        )
    finally:
        if str(ORCH_DIR) in sys.path:
            sys.path.remove(str(ORCH_DIR))

    rendered = "\n".join(lines)
    assert "Prior lessons" in rendered, (
        f"Expected lessons block in rendered output, got:\n{rendered}"
    )
    assert "L-077" in rendered
    # Original recovery paths must still be present
    assert "Recovery paths for [validator:runtime-map-crud-depth]" in rendered


def test_debug_md_documents_lesson_query():
    """commands/vg/debug.md must reference lesson_lookup so AI sees prior
    lessons before generating fix hypotheses (closes user-memory dependency).
    """
    text = DEBUG_MD.read_text(encoding="utf-8")
    assert "lesson_lookup" in text, "debug.md missing lesson_lookup reference"
    assert "query_relevant_lessons" in text, (
        "debug.md should call query_relevant_lessons in its bash snippet"
    )
    assert "format_lessons_for_recovery" in text
    # Telemetry emission requirement
    assert "recovery.lessons_consulted" in text


def test_vg_recovery_imports_lesson_lookup():
    """scripts/vg-recovery.py must import lesson_lookup and emit
    `recovery.lessons_consulted` telemetry on consultation."""
    text = VG_RECOVERY_PY.read_text(encoding="utf-8")
    assert "from lesson_lookup import" in text
    assert "query_relevant_lessons" in text
    assert "recovery.lessons_consulted" in text
    # Soft-fallback so missing helper doesn't break recovery — accept either
    # `def fallback(): return []` (one-liner) or split-line bodies.
    assert re.search(
        r"def query_relevant_lessons\([^)]*\):.*?return \[\]",
        text, re.DOTALL,
    ), "vg-recovery.py must define a no-op fallback for missing lesson_lookup"


def test_cli_smoke(lesson_lookup, tmp_path, monkeypatch, capsys):
    """`python lesson_lookup.py --violation X --json` returns JSON list."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    _write_accepted(tmp_path, _two_lesson_fixture())

    rc = lesson_lookup._main(["--violation", "TDD-violation", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    import json
    data = json.loads(out)
    assert isinstance(data, list)
    assert any(l["lesson_id"] == "L-001" for l in data)
