"""deploy.md frontmatter MUST retain all 5 step markers.

Refactor must not drop or rename any marker — the orchestrator relies on
each marker to drive state-machine validation.
"""

REQUIRED_MARKERS = {
    "0_parse_and_validate",
    "0a_env_select_and_confirm",
    "1_deploy_per_env",
    "2_persist_summary",
    "complete",
}


def test_deploy_step_markers_preserved(skill_loader):
    skill = skill_loader("deploy")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    markers = set(rc.get("must_touch_markers", []))
    missing = REQUIRED_MARKERS - markers
    assert not missing, (
        f"frontmatter must_touch_markers missing: {missing}\n"
        f"current markers: {sorted(markers)}"
    )
