"""R3.5 Roam Pilot — mega-gate decomposition (audit FAIL #10 fix)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROAM = REPO / "commands/vg/roam.md"


def test_5_sub_step_markers_replace_single_0a():
    """The mega-gate decomposition must produce 5 markers (audit FAIL #10)."""
    text = ROAM.read_text()
    expected = [
        "0a_backfill_env_pref",
        "0a_detect_platform_tools",
        "0a_enrich_env_options",
        "0a_confirm_env_model_mode",
        "0a_persist_config",
    ]
    for m in expected:
        assert m in text, f"Missing decomposed marker: {m}"
    # Original mega-gate marker should NOT appear in the slim entry's
    # runtime_contract markers list — it's been replaced by the 5 sub-steps.
    # Note: it may still be referenced in narrative comments, so check the
    # frontmatter region only (between `must_touch_markers:` and the next top-level key).
    body = text
    fm_marker_start = body.find("must_touch_markers:")
    assert fm_marker_start > 0
    # End of must_touch_markers section is `must_emit_telemetry:` (next key)
    fm_marker_end = body.find("must_emit_telemetry:", fm_marker_start)
    assert fm_marker_end > fm_marker_start
    marker_section = body[fm_marker_start:fm_marker_end]
    assert "0a_env_model_mode_gate" not in marker_section, (
        "Mega-gate marker still in must_touch_markers — decomposition not complete"
    )


def test_each_sub_step_ref_under_150_lines():
    refs = [
        "commands/vg/_shared/roam/config-gate/backfill-env.md",
        "commands/vg/_shared/roam/config-gate/detect-platform.md",
        "commands/vg/_shared/roam/config-gate/enrich-env.md",
        "commands/vg/_shared/roam/config-gate/confirm-env-model-mode.md",
        "commands/vg/_shared/roam/config-gate/persist-config.md",
    ]
    for ref in refs:
        p = REPO / ref
        assert p.exists(), f"missing config-gate sub-ref: {ref}"
        n = len(p.read_text().splitlines())
        assert n <= 150, f"{ref} exceeds 150 lines (got {n})"


def test_each_sub_step_marks_its_own_step():
    """Each sub-step ref must contain its own mark_step call for its marker."""
    pairs = [
        ("backfill-env.md",          "0a_backfill_env_pref"),
        ("detect-platform.md",       "0a_detect_platform_tools"),
        ("enrich-env.md",            "0a_enrich_env_options"),
        ("confirm-env-model-mode.md", "0a_confirm_env_model_mode"),
        ("persist-config.md",        "0a_persist_config"),
    ]
    base = REPO / "commands/vg/_shared/roam/config-gate"
    for fname, marker in pairs:
        text = (base / fname).read_text()
        assert f'mark_step "${{PHASE_NUMBER}}" "{marker}"' in text, (
            f"{fname} must call mark_step for {marker}"
        )
