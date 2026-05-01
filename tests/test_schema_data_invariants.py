"""Golden tests for schemas/data-invariants.v1.json.

RFC v9 D5 — data_invariants block in ENV-CONTRACT.md. Per-consumer entity
creation closes preflight non-convergence ping-pong (multiple destructive
consumers all check "0 rows" → all create N rows → mutation collisions).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "data-invariants.v1.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_file_present_and_parses():
    schema = _load_schema()
    assert schema["$id"].endswith("data-invariants.v1.json")
    assert schema["title"] == "VGFlow Data Invariants v1.0"


def test_invariant_required_fields():
    schema = _load_schema()
    inv = schema["$defs"]["invariant"]
    assert set(inv["required"]) == {"id", "resource", "where", "consumers"}


def test_consumer_required_fields():
    schema = _load_schema()
    consumer = schema["$defs"]["consumer"]
    assert set(consumer["required"]) == {"goal", "recipe", "consume_semantics"}
    assert set(consumer["properties"]["consume_semantics"]["enum"]) == {
        "destructive", "read_only",
    }


def test_isolation_enum_includes_per_consumer_default():
    schema = _load_schema()
    inv = schema["$defs"]["invariant"]
    iso = inv["properties"]["isolation"]
    assert iso["default"] == "per_consumer"
    assert set(iso["enum"]) == {"per_consumer", "shared_when_read_only"}


def test_invariant_id_pattern_strict_lowercase_snake():
    schema = _load_schema()
    inv = schema["$defs"]["invariant"]
    assert inv["properties"]["id"]["pattern"] == r"^[a-z][a-z0-9_]*$"


def test_consumer_goal_must_match_g_pattern():
    schema = _load_schema()
    pat = schema["$defs"]["consumer"]["properties"]["goal"]["pattern"]
    assert pat == r"^G-[A-Za-z0-9._-]+$"


def test_where_must_have_at_least_one_filter():
    schema = _load_schema()
    where = schema["$defs"]["invariant"]["properties"]["where"]
    assert where["minProperties"] == 1


# ─── jsonschema runtime validation ───────────────────────────────────


def _has_jsonschema():
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark_jsonschema = pytest.mark.skipif(
    not _has_jsonschema(), reason="jsonschema not installed"
)


def _valid_minimal() -> dict:
    return {
        "data_invariants": [{
            "id": "tier2_topup_pending",
            "resource": "topup",
            "where": {"tier": 2, "status": "pending"},
            "consumers": [
                {"goal": "G-10", "recipe": "G-10", "consume_semantics": "destructive"},
                {"goal": "G-11", "recipe": "G-10", "consume_semantics": "destructive"},
                {"goal": "G-12", "recipe": "G-10", "consume_semantics": "read_only"},
            ],
            "isolation": "per_consumer",
        }],
    }


@pytestmark_jsonschema
def test_minimal_valid_invariants_pass():
    import jsonschema
    schema = _load_schema()
    jsonschema.validate(_valid_minimal(), schema)


@pytestmark_jsonschema
def test_invariant_id_uppercase_fails():
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    payload["data_invariants"][0]["id"] = "Tier2Topup"  # not snake_case
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytestmark_jsonschema
def test_consumer_invalid_goal_fails():
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    payload["data_invariants"][0]["consumers"][0]["goal"] = "goal-1"  # missing G- prefix
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytestmark_jsonschema
def test_consume_semantics_invalid_enum_fails():
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    payload["data_invariants"][0]["consumers"][0]["consume_semantics"] = "mutate"  # invalid
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytestmark_jsonschema
def test_empty_where_fails():
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    payload["data_invariants"][0]["where"] = {}  # minProperties=1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytestmark_jsonschema
def test_no_consumers_fails():
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    payload["data_invariants"][0]["consumers"] = []  # minItems=1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytestmark_jsonschema
def test_recipe_owning_can_differ_from_consumer_goal():
    """G-11 reuses G-10's recipe — explicitly allowed by RFC v9."""
    import jsonschema
    schema = _load_schema()
    payload = _valid_minimal()
    # already in fixture: G-11 consumer with recipe=G-10 — passes
    jsonschema.validate(payload, schema)
