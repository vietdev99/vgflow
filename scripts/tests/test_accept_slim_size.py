"""R4 Accept Pilot — slim entry size + imperative language + ref listing."""
from pathlib import Path

ACCEPT = Path(__file__).resolve().parents[1].parent / "commands/vg/accept.md"


def test_accept_slim():
    lines = ACCEPT.read_text().splitlines()
    assert len(lines) <= 600, f"accept.md exceeds 600 lines (got {len(lines)})"


def test_accept_imperative_language():
    body = ACCEPT.read_text()
    assert "<HARD-GATE>" in body
    assert "Red Flags" in body
    assert "MUST" in body
    assert "STEP 1" in body
    assert "STEP 8" in body, "all 8 STEP sections must be present"
    forbidden_in_imperative = [" should call ", " may call ", " will call "]
    lower_body = body.lower()
    for phrase in forbidden_in_imperative:
        assert phrase not in lower_body, f"forbidden descriptive phrase: '{phrase}'"


def test_accept_refs_listed_directly():
    body = ACCEPT.read_text()
    expected_refs = [
        "_shared/accept/preflight.md",
        "_shared/accept/gates.md",
        "_shared/accept/uat/checklist-build/overview.md",
        "_shared/accept/uat/checklist-build/delegation.md",
        "_shared/accept/uat/narrative.md",
        "_shared/accept/uat/interactive.md",
        "_shared/accept/uat/quorum.md",
        "_shared/accept/audit.md",
        "_shared/accept/cleanup/overview.md",
        "_shared/accept/cleanup/delegation.md",
    ]
    for ref in expected_refs:
        assert ref in body, f"entry must directly list leaf ref: {ref}"


def test_accept_uses_agent_not_task():
    body = ACCEPT.read_text()
    assert "Agent" in body, "must use Agent tool name (Codex fix #3)"
    # allowed-tools list MUST NOT have a `- Task` entry
    assert "\n  - Task\n" not in body, "allowed-tools should use Agent, not Task"


def test_accept_runtime_contract_preserved():
    """17 step markers + 4 telemetry events must appear in frontmatter."""
    body = ACCEPT.read_text()
    expected_markers = [
        "0_gate_integrity_precheck",
        "0_load_config",
        "create_task_tracker",
        "0c_telemetry_suggestions",
        "1_artifact_precheck",
        "2_marker_precheck",
        "3_sandbox_verdict_gate",
        "3b_unreachable_triage_gate",
        "3c_override_resolution_gate",
        "4_build_uat_checklist",
        "4b_uat_narrative_autofire",
        "5_interactive_uat",
        "5_uat_quorum_gate",
        "6b_security_baseline",
        "6c_learn_auto_surface",
        "6_write_uat_md",
        "7_post_accept_actions",
    ]
    for marker in expected_markers:
        assert marker in body, f"runtime_contract must keep marker: {marker}"
    # Audit FAIL #9 fix
    assert "accept.native_tasklist_projected" in body, (
        "must_emit_telemetry must keep accept.native_tasklist_projected (audit FAIL #9 fix)"
    )
