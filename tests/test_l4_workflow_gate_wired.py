"""F5 v2.64.0: L4_workflow gate wired into post-execution."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_post_execution_delegation_has_l4_workflow_step():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-delegation.md").read_text(encoding="utf-8")
    assert "L4_workflow" in body, (
        "post-execution-delegation.md must declare L4_workflow gate (v2.64.0 F5)"
    )
    assert "verify-workflow-evidence" in body, (
        "delegation must invoke verify-workflow-evidence.py"
    )


def test_post_execution_delegation_handles_missing_workflow_specs():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-delegation.md").read_text(encoding="utf-8")
    assert "WORKFLOW-SPECS" in body, "delegation must reference WORKFLOW-SPECS"
    assert "build.l4_workflow_skipped" in body, (
        "delegation must emit skip telemetry when WORKFLOW-SPECS absent"
    )


def test_post_execution_delegation_warn_default_block_strict():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-delegation.md").read_text(encoding="utf-8")
    assert "VG_BUILD_L4_WORKFLOW_STRICT" in body or "--strict" in body, (
        "delegation must support strict-mode opt-in"
    )


def test_post_execution_overview_documents_l4_workflow():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md").read_text(encoding="utf-8")
    assert "L4_workflow" in body, (
        "post-execution-overview.md must document L4_workflow gate"
    )


def test_build_md_telemetry_l4_workflow():
    body = (REPO_ROOT / "commands" / "vg" / "build.md").read_text(encoding="utf-8")
    assert "build.l4_workflow_completed" in body, (
        "build.md must declare must_emit_telemetry for build.l4_workflow_completed"
    )
    assert "build.l4_workflow_skipped" in body


def test_post_execution_delegation_mirror():
    canonical = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-delegation.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "post-execution-delegation.md"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_post_execution_overview_mirror():
    canonical = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_build_md_mirror():
    canonical = REPO_ROOT / "commands" / "vg" / "build.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "build.md"
    if not mirror.exists(): return
    assert canonical.read_bytes() == mirror.read_bytes()
