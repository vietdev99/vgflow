from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _test_spec_missing_section(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("TEST_SPEC_MISSING_GOALS=")
    end = text.index("# v2.38.0", start)
    return text[start:end]


def test_review_routes_test_spec_missing_to_test_spec_regen() -> None:
    section = _test_spec_missing_section(
        REPO_ROOT / "commands/vg/_shared/review/close.md",
    )

    assert "/vg:test-spec ${PHASE_NUMBER} --regen" in section
    assert "/vg:review ${PHASE_NUMBER} --mode=full --force" in section
    assert "--codegen-from-goals" not in section
    assert "--filter=test-spec-missing" not in section


def test_review_taxonomy_says_not_test_or_build() -> None:
    text = (
        REPO_ROOT / "commands/vg/_shared/review/lens-and-findings.md"
    ).read_text(encoding="utf-8")

    assert "`TEST_SPEC_MISSING` *(v3.7.1)*" in text
    assert "do NOT route to /vg:test or /vg:build" in text
