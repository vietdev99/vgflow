"""B90 v4.66.1 — Issue #197 partial fix: F-CAI-05 + F-CAI-08.

Issue #197 (vietnhprintway, 2026-05-20) surfaced 10 structural gaps in
generate-deep-test-specs.py + generate-lifecycle-specs.py + related
codegen surface. Plus build-gate proposal (live FE-BE coherence) and
Gemini CLI auth TLS issue.

B90 ships fixes for 2 of 10 findings (bug-level — no architectural
redesign needed):

  F-CAI-05 (major): execution-plan entrypoint pollution. 58 goals on
    PrintwayV3 Phase 8.2 carried literal "derive browser route from built
    implementation and TEST-GOALS" placeholder strings because the AI
    expander's no-route-hint fallback emitted natural-language text that
    downstream codegen never substituted. Fix: emit unambiguous
    `__TBD__:` marker + new `has_unresolved_tbd()` helper for downstream
    detection.

  F-CAI-08 (major): goal coverage shortfall — silent skip. TEST-GOALS.md
    had 206 headings; LIFECYCLE-SPECS emitted only 200. G-221..G-226
    dropped silently because `_parse_goal_block` returned None on heading
    regex mismatch + caller had no diagnostic path. Fix: add
    `_count_goal_headings()` + drop log into `_parse_goals()`. Summary
    now carries `heading_counts`, `goals_dropped`, `goals_dropped_count`.
    main() emits stderr warning when drift detected.

Deferred to future batches (architectural):
  F-CAI-01 (RCRURDR semantic anchoring) — needs goal-surface→endpoint
    matcher rewrite.
  F-CAI-02 (multi-actor RBAC) — needs actor/permission registry.
  F-CAI-03 (empty source assertions) — needs goal frontmatter linter
    upstream + generator validation gate.
  F-CAI-04 (stale endpoint declarations) — needs API-CONTRACTS.md→spec
    sync at generator entrypoint.
  F-CAI-06 (disconnected fixture DAG for multi-actor) — needs DAG
    builder rewrite to span multiple resource owners.
  F-CAI-07 (decision coverage below gate) — needs decision_refs
    propagation through generator.
  F-CAI-09 (read-only goal misclassification) — needs goal_type
    auto-detection from text vs explicit frontmatter.
  F-CAI-10 (endpoint=null pass-through) — needs binding propagation
    audit between generate-lifecycle-specs and downstream codegen.

Plus deferred non-generator items:
  Build-gate proposal — live FE-BE coherence check.
  Gemini CLI TLS — docs-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPANDER = REPO_ROOT / "scripts" / "test_spec_ai_expander.py"
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


# ---------------------------------------------------------------------------
# F-CAI-05: __TBD__ marker + has_unresolved_tbd helper
# ---------------------------------------------------------------------------

def test_b90_fcai05_tbd_marker_in_expander_source() -> None:
    body = EXPANDER.read_text(encoding="utf-8")
    assert "__TBD__:" in body, "expander must emit __TBD__: marker on fallback"
    # Old literal placeholder must be gone
    assert "derive {strategy['entrypoint_kind']} from built implementation" not in body, (
        "literal natural-language fallback must be replaced with __TBD__: marker"
    )


def test_b90_fcai05_has_unresolved_tbd_helper_added() -> None:
    body = EXPANDER.read_text(encoding="utf-8")
    assert "def has_unresolved_tbd" in body, "helper missing"


def test_b90_fcai05_helper_detects_tbd_marker() -> None:
    """Import + invoke the helper to verify behavior."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("expander", EXPANDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.has_unresolved_tbd(["__TBD__: resolve browser route from ..."]) is True
    assert mod.has_unresolved_tbd(["/admin/topups"]) is False
    assert mod.has_unresolved_tbd([]) is False
    assert mod.has_unresolved_tbd(None) is False  # type: ignore[arg-type]
    # Mixed: any TBD marker counts as unresolved
    assert mod.has_unresolved_tbd([
        "/admin/topups",
        "__TBD__: resolve API endpoint from ...",
    ]) is True


def test_b90_fcai05_expander_emits_tbd_when_no_routes(tmp_path: Path) -> None:
    """Behavioral: spec with no primary_endpoints + empty surfaces.routes →
    fallback emits __TBD__ marker (not literal natural-language string).
    """
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location("expander", EXPANDER)
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)

    goal_spec = {
        "title": "List approved topups",
        "primary_endpoints": [],
        "mutation_evidence": "",
        "persistence_check": "",
        "dependencies": "",
        "steps": [],
    }
    surfaces = {"routes": []}
    hints = mod._entrypoint_hints(goal_spec, surfaces, profile="web-fullstack")
    assert any(h.startswith("__TBD__:") for h in hints), (
        f"expected __TBD__ marker; got hints: {hints}"
    )
    # The literal old-fallback must NOT appear
    assert not any("derive" in h and "from built implementation" in h
                   for h in hints), f"old literal placeholder leaked: {hints}"


# ---------------------------------------------------------------------------
# F-CAI-08: heading_counts + goals_dropped diagnostics
# ---------------------------------------------------------------------------

def test_b90_fcai08_count_helper_added() -> None:
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "def _count_goal_headings" in body, "heading counter helper missing"
    assert "heading_counts" in body, "summary key heading_counts missing"
    assert "goals_dropped" in body, "summary key goals_dropped missing"
    assert "goals_dropped_count" in body, "summary key goals_dropped_count missing"


def test_b90_fcai08_dropped_log_optional_param() -> None:
    """_parse_goals must accept optional dropped_log list parameter."""
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "dropped_log: list[dict[str, str]] | None = None" in body, (
        "_parse_goals signature must accept dropped_log param"
    )


def test_b90_fcai08_main_emits_drift_warning() -> None:
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "goal parse drift detected" in body, "main() must surface drift"


def test_b90_fcai08_behavioral_count_headings_via_module(tmp_path: Path) -> None:
    """End-to-end: phase dir with 5 headings in TEST-GOALS.md, 3 split files
    → _count_goal_headings returns {split_files: 3, flat_headings: 5, ...}.
    """
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    # Split dir with 3 G-*.md files
    split = pdir / "TEST-GOALS"
    split.mkdir()
    for i in range(3):
        (split / f"G-00{i+1}.md").write_text(
            f"# G-00{i+1}: example\n\ngoal_type: mutation\n",
            encoding="utf-8",
        )
    # Flat file with 5 ## headings
    flat = pdir / "TEST-GOALS.md"
    flat.write_text("\n".join(
        f"## Goal G-1{i:02d}: example title\n\ngoal_type: mutation\n"
        for i in range(5)
    ), encoding="utf-8")

    import importlib.util
    spec_mod = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)
    counts = mod._count_goal_headings(pdir)
    assert counts["split_files"] == 3
    assert counts["flat_headings"] == 5
    assert counts["flat_files_exists"] == 1


def test_b90_fcai08_dropped_log_captures_malformed_split(tmp_path: Path) -> None:
    """Split file with no parseable G- heading → dropped_log gets entry."""
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    split = pdir / "TEST-GOALS"
    split.mkdir()
    # Malformed: no `# G-NNN` heading
    (split / "G-bogus.md").write_text("not a real goal block\n", encoding="utf-8")

    import importlib.util
    spec_mod = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)

    dropped: list[dict[str, str]] = []
    goals = mod._parse_goals(pdir, dropped_log=dropped)
    assert len(goals) == 0
    assert len(dropped) == 1
    assert "G-bogus.md" in dropped[0]["source"]


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b90_expander_mirror_byte_identical() -> None:
    a = EXPANDER.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "test_spec_ai_expander.py").read_bytes()
    assert a == b, "expander mirror drift"


def test_b90_lifecycle_mirror_byte_identical() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b, "lifecycle mirror drift"
