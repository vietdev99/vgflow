"""deploy.md frontmatter MUST retain phase.deploy_started + phase.deploy_completed.

These events are consumed by downstream env-recommendation gates (review/test/roam
via enrich-env-question.py). Any rename or removal breaks the contract.
"""

REQUIRED_EVENT_TYPES = {"phase.deploy_started", "phase.deploy_completed"}


def test_deploy_telemetry_events_preserved(skill_loader):
    skill = skill_loader("deploy")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    # Each entry is a dict with `event_type` key (per real frontmatter shape).
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
