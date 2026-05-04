"""L2 skill-split regression — assert runtime-checks.md split into 3 sub-refs.

Anthropic Skill progressive disclosure baseline: keep skill body < 200 lines,
push detail into refs on demand. The pre-split runtime-checks.md was 1033
lines (top context offender for /vg:review STEP 4.5).

This test pins:
- 3 sub-refs exist (overview slim, static, dynamic)
- Slim overview < 250 lines
- Step IDs preserved across split (Stop hook + tasklist read these)
- HARD-GATE block preserved
- review.md STEP 4.5 routing intact
- Mark_step lifecycle calls preserved
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REVIEW_REFS = REPO / "commands" / "vg" / "_shared" / "review"
OVERVIEW = REVIEW_REFS / "runtime-checks.md"
STATIC = REVIEW_REFS / "runtime-checks-static.md"
DYNAMIC = REVIEW_REFS / "runtime-checks-dynamic.md"
REVIEW_MD = REPO / "commands" / "vg" / "review.md"


def test_three_sub_refs_exist() -> None:
    """Both new sub-refs + slim overview exist on disk."""
    for path in (OVERVIEW, STATIC, DYNAMIC):
        assert path.exists(), f"missing sub-ref: {path}"
        assert path.stat().st_size > 100, f"{path} suspiciously short"


def test_overview_is_slim() -> None:
    """Slim overview <= 250 lines per Anthropic Skill body baseline."""
    lines = OVERVIEW.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 250, (
        f"runtime-checks.md = {len(lines)} lines, exceeds 250-line slim cap. "
        "Pre-split file was 1033 lines (R3 audit top context offender)."
    )


def test_overview_has_hard_gate_block() -> None:
    """HARD-GATE preserved verbatim in slim overview."""
    text = OVERVIEW.read_text(encoding="utf-8")
    assert "<HARD-GATE>" in text and "</HARD-GATE>" in text, (
        "HARD-GATE block dropped from runtime-checks.md slim overview"
    )
    assert "You MUST execute every applicable sub-step" in text, (
        "HARD-GATE imperative dropped"
    )


def test_overview_references_both_sub_refs() -> None:
    """Slim overview MUST reference both sub-refs by name so AI can route."""
    text = OVERVIEW.read_text(encoding="utf-8")
    assert "runtime-checks-static.md" in text, "overview missing route to static sub-ref"
    assert "runtime-checks-dynamic.md" in text, "overview missing route to dynamic sub-ref"


def test_all_step_ids_preserved_across_split() -> None:
    """All 7 step IDs from pre-split file MUST exist somewhere in the split.

    Stop hook validates must_touch_markers against this set; silently dropping
    any of them means AI may skip a step that the runtime contract required.
    """
    expected_step_ids = {
        "phase2_exploration_limits",
        "phase2_mobile_discovery",
        "phase2_5_visual_checks",
        "phase2_5_mobile_visual_checks",
        "phase2_7_url_state_sync",
        "phase2_8_url_state_runtime",
        "phase2_9_error_message_runtime",
    }
    combined = (
        STATIC.read_text(encoding="utf-8")
        + DYNAMIC.read_text(encoding="utf-8")
        + OVERVIEW.read_text(encoding="utf-8")
    )
    missing = {sid for sid in expected_step_ids if sid not in combined}
    assert not missing, (
        f"Step IDs missing from split: {sorted(missing)}. Each ID must appear "
        "either as a <step name=...> block or as a routing reference."
    )


def test_static_sub_ref_contains_static_step_blocks() -> None:
    """Static sub-ref carries the file-scan/declaration sub-steps verbatim."""
    text = STATIC.read_text(encoding="utf-8")
    assert '<step name="phase2_exploration_limits"' in text, (
        "phase2_exploration_limits step block missing from runtime-checks-static.md"
    )
    assert '<step name="phase2_7_url_state_sync"' in text, (
        "phase2_7_url_state_sync step block missing from runtime-checks-static.md"
    )
    # R8 enforcement language preserved
    assert "R8 enforcement" in text, "R8 exploration-limit narration dropped"


def test_dynamic_sub_ref_contains_dynamic_step_blocks() -> None:
    """Dynamic sub-ref carries browser/Maestro probe sub-steps verbatim."""
    text = DYNAMIC.read_text(encoding="utf-8")
    for sid in (
        "phase2_mobile_discovery",
        "phase2_5_visual_checks",
        "phase2_5_mobile_visual_checks",
        "phase2_8_url_state_runtime",
        "phase2_9_error_message_runtime",
    ):
        assert f'<step name="{sid}"' in text, (
            f"{sid} step block missing from runtime-checks-dynamic.md"
        )


def test_mark_step_lifecycle_preserved() -> None:
    """Each step writes its marker via mark_step OR touch fallback. Pin that
    lifecycle is preserved across split."""
    combined = STATIC.read_text(encoding="utf-8") + DYNAMIC.read_text(encoding="utf-8")
    # Sample a few step markers from the canonical mark_step pattern
    for sid in (
        "phase2_exploration_limits",
        "phase2_5_visual_checks",
        "phase2_8_url_state_runtime",
    ):
        assert f"{sid}.done" in combined, (
            f"mark_step lifecycle dropped for {sid} (Stop hook needs this)"
        )


def test_review_md_step45_routing_intact() -> None:
    """commands/vg/review.md STEP 4.5 must still route to runtime-checks.md
    (the slim entry, which then routes to sub-refs)."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    assert "_shared/review/runtime-checks.md" in text, (
        "review.md no longer references _shared/review/runtime-checks.md — "
        "STEP 4.5 routing broken"
    )
    assert "STEP 4.5" in text, "STEP 4.5 heading dropped from review.md"
