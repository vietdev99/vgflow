from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_partial_wave_writes_build_continuation_token() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
    ).read_text(encoding="utf-8")

    assert ".claude/scripts/build-continuation.py write" in text
    assert "--current-wave \"${WAVE_FILTER}\"" in text
    assert "--max-wave \"${MAX_WAVE}\"" in text
    assert "build.partial_wave_complete" in text
    assert "next_command" in text


def test_final_wave_clears_build_continuation_token() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
    ).read_text(encoding="utf-8")

    assert ".claude/scripts/build-continuation.py clear" in text
    assert "--phase-dir \"${PHASE_DIR}\"" in text


def test_build_entry_surfaces_natural_continue_instruction() -> None:
    text = (REPO_ROOT / "commands" / "vg" / "build.md").read_text(encoding="utf-8")

    assert ".claude/scripts/build-continuation.py show" in text
    assert "Type 'tiếp tục' to resume" in text
