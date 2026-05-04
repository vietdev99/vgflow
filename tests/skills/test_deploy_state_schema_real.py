"""DEPLOY-STATE.json schema invariant — preserved keys + per-env fields.

NO real fixture exists in repo (no phase has been deployed). This test
synthesizes an in-memory pre-deploy state matching the REAL schema and
asserts that a hypothetical Step 2 merge preserves all keys.
"""
from copy import deepcopy

# Real schema fields per spec §3.4 (verified against current deploy.md Step 2).
REAL_PER_ENV_FIELDS = {
    "sha", "deployed_at", "health", "deploy_log", "previous_sha", "dry_run"
}
HEALTH_ENUM = {"ok", "failed", "dry-run"}


def _synthesize_state() -> dict:
    """Build an in-memory pre-deploy state mirroring real schema."""
    return {
        "phase": "P1",
        "deployed": {
            "sandbox": {
                "sha": "f00ba12",
                "deployed_at": "2026-04-30T10:15:22Z",
                "health": "ok",
                "deploy_log": ".vg/phases/P1/.deploy-log.sandbox.txt",
                "previous_sha": None,
                "dry_run": False,
            },
            "staging": None,
            "prod": None,
        },
        "preferred_env_for": {"feature_x": "staging"},
        "preferred_env_for_skipped": False,
    }


def _merge_executor_result(state: dict, result: dict) -> dict:
    """Reference merge logic — MUST match commands/vg/deploy.md Step 2 behavior.

    Preserves all top-level non-deployed keys; updates only deployed.<env>.
    """
    new_state = deepcopy(state)
    env = result["env"]
    new_state["deployed"][env] = {
        "sha": result["sha"],
        "deployed_at": result["deployed_at"],
        "health": result["health"],
        "deploy_log": result["deploy_log"],
        "previous_sha": result["previous_sha"],
        "dry_run": result["dry_run"],
    }
    return new_state


def test_state_round_trip_preserves_preferred_env_for():
    state = _synthesize_state()
    result = {
        "env": "staging",
        "sha": "abcdef0",
        "deployed_at": "2026-05-03T14:32:11Z",
        "health": "ok",
        "deploy_log": ".vg/phases/P1/.deploy-log.staging.txt",
        "previous_sha": None,
        "dry_run": False,
        "error": None,
    }
    merged = _merge_executor_result(state, result)
    assert merged["preferred_env_for"] == {"feature_x": "staging"}, "must preserve preferred_env_for"
    assert merged["preferred_env_for_skipped"] is False, "must preserve preferred_env_for_skipped"
    assert merged["deployed"]["sandbox"]["sha"] == "f00ba12", "must not overwrite other env's block"
    assert merged["deployed"]["staging"]["sha"] == "abcdef0", "must update target env block"


def test_per_env_fields_complete():
    state = _synthesize_state()
    sandbox = state["deployed"]["sandbox"]
    missing = REAL_PER_ENV_FIELDS - set(sandbox)
    assert not missing, f"synthesized fixture missing real fields: {missing}"
    assert sandbox["health"] in HEALTH_ENUM


def test_executor_result_shape_compatible_with_merge():
    """The subagent return JSON shape must be sufficient to populate per-env block."""
    result = {
        "env": "sandbox", "sha": "abc", "deployed_at": "2026-05-03T00:00:00Z",
        "health": "ok", "deploy_log": "/tmp/log.txt",
        "previous_sha": None, "dry_run": False, "error": None,
    }
    state = _synthesize_state()
    merged = _merge_executor_result(state, result)
    block = merged["deployed"]["sandbox"]
    assert set(block) == REAL_PER_ENV_FIELDS, (
        f"merged block has wrong fields: {set(block)} vs {REAL_PER_ENV_FIELDS}"
    )
