"""v2.84.2 hotfix — review_batch.py ROADMAP.md dual-mode lookup.

Verifies _resolve_phases_milestone() prefers `.vg/ROADMAP.md` (post-migration)
and falls back to root `ROADMAP.md` (legacy v2.x layout).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def review_batch():
    import review_batch  # type: ignore[import-not-found]

    return review_batch


def _make_roadmap_body() -> str:
    return """# Roadmap

## Milestone M1

- Phase 1 — alpha
- Phase 2 — beta

## Milestone M2

- Phase 3 — gamma
"""


def test_prefers_new_layout(tmp_path, review_batch):
    """`.vg/ROADMAP.md` wins over root `ROADMAP.md`."""
    (tmp_path / ".vg").mkdir()
    (tmp_path / ".vg" / "ROADMAP.md").write_text(
        "## Milestone M1\n- Phase 99 — new layout\n## Milestone M2\n- Phase 100 — z\n",
        encoding="utf-8",
    )
    (tmp_path / "ROADMAP.md").write_text(
        "## Milestone M1\n- Phase 1 — legacy\n", encoding="utf-8"
    )
    phases = review_batch._resolve_phases_milestone(tmp_path, "M1")
    assert "99" in phases or any("99" in p for p in phases)


def test_falls_back_to_legacy(tmp_path, review_batch):
    """No `.vg/ROADMAP.md`, falls back to root."""
    (tmp_path / "ROADMAP.md").write_text(_make_roadmap_body(), encoding="utf-8")
    phases = review_batch._resolve_phases_milestone(tmp_path, "M1")
    assert any("1" in p for p in phases) or any("2" in p for p in phases)


def test_returns_empty_when_neither_exists(tmp_path, review_batch, capsys):
    """No roadmap anywhere — empty list + stderr message naming both paths."""
    phases = review_batch._resolve_phases_milestone(tmp_path, "M1")
    assert phases == []
    captured = capsys.readouterr()
    assert ".vg/ROADMAP.md" in captured.err
