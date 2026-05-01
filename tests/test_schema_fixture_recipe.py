"""Golden tests for schemas/fixture-recipe.v1.json.

RFC v9 D2 — recipe schema for FIXTURES/{G-XX}.yaml. Authored at
/vg:build by executor; consumed by /vg:review preflight + /vg:test
codegen. Schema version 1.0 mandatory; runner rejects unknown major.

Validates positive + negative cases. Uses jsonschema if available;
otherwise structural sanity check on the schema itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "fixture-recipe.v1.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_file_present_and_parses():
    schema = _load_schema()
    assert schema["$id"].endswith("fixture-recipe.v1.json")
    assert schema["title"] == "VGFlow Fixture Recipe v1.0"


def test_schema_required_top_level_fields():
    schema = _load_schema()
    required = set(schema["required"])
    assert required == {"schema_version", "goal", "description", "fixture_intent", "steps"}


def test_schema_version_is_const_1_0():
    schema = _load_schema()
    sv = schema["properties"]["schema_version"]
    assert sv["const"] == "1.0"


def test_step_kind_enum_includes_loop_and_api_call():
    schema = _load_schema()
    step = schema["$defs"]["step"]
    assert set(step["properties"]["kind"]["enum"]) == {"api_call", "loop"}


def test_capture_path_must_start_with_dollar():
    schema = _load_schema()
    cap = schema["$defs"]["capture"]
    assert cap["properties"]["path"]["pattern"] == r"^\$"


def test_lifecycle_block_has_pre_action_post():
    schema = _load_schema()
    lifecycle = schema["$defs"]["lifecycle"]
    assert set(lifecycle["required"]) == {"pre_state", "action", "post_state"}


def test_lifecycle_action_has_expected_network():
    schema = _load_schema()
    action = schema["$defs"]["lifecycle"]["properties"]["action"]
    required = set(action["required"])
    assert "expected_network" in required
    assert "surface" in required
    surfaces = action["properties"]["surface"]["enum"]
    assert set(surfaces) == {"ui_click", "ui_form_submit", "api_direct"}


def test_idempotency_required_for_post_put():
    schema = _load_schema()
    step = schema["$defs"]["step"]
    # The conditional rule lives in step.allOf[1] — find it
    rules = step["allOf"]
    idem_rule = None
    for r in rules:
        if "idempotency_key" in str(r.get("then", {}).get("required", [])):
            idem_rule = r
            break
    assert idem_rule is not None, "POST/PUT idempotency rule missing"
    methods = idem_rule["if"]["allOf"][1]["properties"]["method"]["enum"]
    assert set(methods) == {"POST", "PUT"}


def test_side_effect_risk_enum():
    schema = _load_schema()
    risk = schema["$defs"]["step"]["properties"]["side_effect_risk"]
    assert set(risk["enum"]) == {"none", "money_like", "external_call", "volume_change"}


def test_validate_after_method_is_get():
    schema = _load_schema()
    va = schema["$defs"]["validate_after"]
    assert va["properties"]["method"]["enum"] == ["GET"]


# ─── jsonschema runtime validation (if available) ─────────────────────


def _has_jsonschema():
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark_jsonschema = pytest.mark.skipif(
    not _has_jsonschema(), reason="jsonschema not installed"
)


def _valid_minimal_recipe() -> dict:
    return {
        "schema_version": "1.0",
        "goal": "G-01",
        "description": "Create a tier2 topup pending entity for /api/topup approval flow",
        "fixture_intent": {
            "declared_in": "TEST-GOALS.md#G-01",
            "validates": "approval mutation lifecycle end-to-end",
        },
        "steps": [{
            "id": "create_topup",
            "kind": "api_call",
            "role": "user_alice",
            "method": "POST",
            "endpoint": "/api/topup",
            "idempotency_key": "k-001",
            "body": {"amount": 0.01},
        }],
    }


@pytestmark_jsonschema
def test_minimal_valid_recipe_passes():
    import jsonschema
    schema = _load_schema()
    jsonschema.validate(_valid_minimal_recipe(), schema)


@pytestmark_jsonschema
def test_missing_idempotency_on_post_fails():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    del recipe["steps"][0]["idempotency_key"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_get_step_does_not_need_idempotency():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["steps"][0] = {
        "id": "fetch_topup",
        "kind": "api_call",
        "role": "user_alice",
        "method": "GET",
        "endpoint": "/api/topup/123",
    }
    jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_loop_step_requires_over_and_each():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["steps"][0] = {
        "id": "loop_step",
        "kind": "loop",
        # missing over + each
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_short_description_fails_d27():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["description"] = "TBD"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_wrong_schema_version_fails():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["schema_version"] = "2.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_invalid_goal_pattern_fails():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["goal"] = "goal_one"  # not G-XX format
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(recipe, schema)


@pytestmark_jsonschema
def test_lifecycle_block_validates():
    import jsonschema
    schema = _load_schema()
    recipe = _valid_minimal_recipe()
    recipe["lifecycle"] = {
        "pre_state": {
            "role": "user_alice",
            "method": "GET",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 0}],
        },
        "action": {
            "surface": "ui_click",
            "target": "Submit topup",
            "expected_network": {
                "method": "POST",
                "endpoint": "/api/topup",
                "status_range": [200, 299],
                "target_selector_must_include": "G-01-fixture",
            },
        },
        "post_state": {
            "role": "user_alice",
            "method": "GET",
            "endpoint": "/api/topup/pending",
            "retry": {"max_attempts": 5, "delay_ms": 200, "until_assertion_pass": True},
            "assert_jsonpath": [{"path": "$.count", "increased_by_at_least": 1}],
        },
    }
    jsonschema.validate(recipe, schema)
