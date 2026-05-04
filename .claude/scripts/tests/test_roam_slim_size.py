"""R3.5 Roam Pilot — slim entry size + imperative language + ref listing."""
from pathlib import Path

ROAM = Path(__file__).resolve().parents[1].parent / "commands/vg/roam.md"


def test_roam_md_under_600():
    lines = ROAM.read_text().splitlines()
    assert len(lines) <= 600, f"roam.md exceeds 600 lines (got {len(lines)})"


def test_roam_imperative_language():
    body = ROAM.read_text()
    assert "<HARD-GATE>" in body
    assert "Red Flags" in body
    assert "MUST" in body
    assert "STEP 1" in body
    assert "STEP 8" in body, "all 8 STEP sections must be present"


def test_roam_md_uses_agent_not_task():
    body = ROAM.read_text()
    assert "Agent" in body, "must use Agent tool name, not Task"
    # allowed-tools list MUST NOT have a `- Task` entry
    assert "\n  - Task\n" not in body, "allowed-tools should use Agent, not Task"


def test_roam_runtime_contract_preserved():
    """All step markers + telemetry events must appear in frontmatter."""
    body = ROAM.read_text()
    expected_markers = [
        "0_parse_and_validate",
        "0a_backfill_env_pref",
        "0a_detect_platform_tools",
        "0a_enrich_env_options",
        "0a_confirm_env_model_mode",
        "0a_persist_config",
        "0aa_resume_check",
        "1_discover_surfaces",
        "2_compose_briefs",
        "3_spawn_executors",
        "4_aggregate_logs",
        "5_analyze_findings",
        "6_emit_artifacts",
        "complete",
        "7_optional_fix_loop",
    ]
    for marker in expected_markers:
        assert marker in body, f"runtime_contract must keep marker: {marker}"

    # PARTIAL audit fix
    assert "roam.native_tasklist_projected" in body, (
        "must_emit_telemetry must keep roam.native_tasklist_projected (PARTIAL audit fix)"
    )
    # Other required telemetry
    for ev in [
        "roam.session.started",
        "roam.session.completed",
        "roam.analysis.completed",
        "roam.resume_mode_chosen",
        "roam.config_confirmed",
        "roam.tasklist_shown",
    ]:
        assert ev in body, f"telemetry event must be declared: {ev}"
