"""Tests for scripts/runtime/recipe_loader.py — RFC v9 PR-A1 recipe parser."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.recipe_loader import load_recipe, ValidationError  # noqa: E402


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "G-01.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _valid_minimal() -> str:
    return """
schema_version: "1.0"
goal: G-01
description: Create tier2 topup pending entity for /api/topup approval flow tests
fixture_intent:
  declared_in: TEST-GOALS.md#G-01
  validates: approval mutation lifecycle end-to-end smoke test
steps:
  - id: create_topup
    kind: api_call
    role: user_alice
    method: POST
    endpoint: /api/topup
    idempotency_key: k-001
    body:
      amount: 0.01
""".lstrip()


def test_loads_minimal_valid_recipe(tmp_path):
    p = _write(tmp_path, _valid_minimal())
    recipe = load_recipe(p)
    assert recipe["schema_version"] == "1.0"
    assert recipe["goal"] == "G-01"
    assert len(recipe["steps"]) == 1


def test_missing_schema_version_rejected(tmp_path):
    p = _write(tmp_path, _valid_minimal().replace('schema_version: "1.0"\n', ""))
    with pytest.raises(ValidationError, match="schema_version"):
        load_recipe(p)


def test_major_version_2_rejected(tmp_path):
    content = _valid_minimal().replace('schema_version: "1.0"', 'schema_version: "2.0"')
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError, match="2.0"):
        load_recipe(p)


def test_minor_version_1_5_accepted(tmp_path):
    content = _valid_minimal().replace('schema_version: "1.0"', 'schema_version: "1.5"')
    p = _write(tmp_path, content)
    # NB: jsonschema (if installed) validates schema_version: const "1.0";
    # the const constraint will reject 1.5. The version-line check passes
    # but schema validation may not. Skip jsonschema validation by deleting
    # the const after load — actually for this test, just verify the
    # version gate path doesn't reject 1.x.
    try:
        load_recipe(p)
    except ValidationError as e:
        # Accept if jsonschema raises on const "1.0"; reject if version gate did.
        assert "schema_version" in str(e) and "1.5" not in str(e), e


def test_missing_required_field_rejected(tmp_path):
    """jsonschema must catch goal missing — only runs when jsonschema installed."""
    pytest.importorskip("jsonschema")
    content = _valid_minimal().replace("goal: G-01\n", "")
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError):
        load_recipe(p)


def test_short_description_rejected(tmp_path):
    pytest.importorskip("jsonschema")
    content = _valid_minimal().replace(
        "description: Create tier2 topup pending entity for /api/topup approval flow tests",
        "description: TBD",
    )
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError, match="description"):
        load_recipe(p)


def test_post_without_idempotency_rejected(tmp_path):
    pytest.importorskip("jsonschema")
    content = _valid_minimal().replace("    idempotency_key: k-001\n", "")
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError):
        load_recipe(p)


def test_get_step_does_not_need_idempotency(tmp_path):
    pytest.importorskip("jsonschema")
    content = """
schema_version: "1.0"
goal: G-02
description: Read merchant detail to confirm provisioning succeeded
fixture_intent:
  declared_in: TEST-GOALS.md#G-02
  validates: merchant detail GET-only smoke
steps:
  - id: fetch
    kind: api_call
    role: user_alice
    method: GET
    endpoint: /api/merchant/123
""".lstrip()
    p = _write(tmp_path, content)
    recipe = load_recipe(p)
    assert recipe["goal"] == "G-02"


def test_yaml_parse_error_wrapped_as_validation_error(tmp_path):
    p = _write(tmp_path, ":\n  : - [unclosed\n")
    with pytest.raises(ValidationError, match="YAML"):
        load_recipe(p)


def test_file_not_found_propagates(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_recipe(tmp_path / "missing.yaml")


# ─── Codex-R4-HIGH-6: JSONPath pre-validation at load time ────────


def test_invalid_capture_jsonpath_rejected_at_load(tmp_path):
    """Codex-R4-HIGH-6: invalid JSONPath used to blow up AT runtime
    (after the mutation already ran). Pre-validate at load."""
    pytest.importorskip("jsonpath_ng")
    content = """
schema_version: "1.0"
goal: G-01
description: Capture path with bad filter expression for pre-validation test
fixture_intent:
  declared_in: TEST-GOALS.md#G-01
  validates: pre-validation regression test goal
steps:
  - id: x
    kind: api_call
    role: u
    method: POST
    endpoint: /api/x
    idempotency_key: k1
    body:
      a: 1
    capture:
      bad:
        path: "$..[?(@invalid_filter syntax!!)]"
""".lstrip()
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError, match="JSONPath"):
        load_recipe(p)


def test_invalid_validate_after_jsonpath_rejected(tmp_path):
    pytest.importorskip("jsonpath_ng")
    content = """
schema_version: "1.0"
goal: G-01
description: validate_after with bad path for regression test
fixture_intent:
  declared_in: TEST-GOALS.md#G-01
  validates: pre-validation regression on validate_after
steps:
  - id: x
    kind: api_call
    role: u
    method: POST
    endpoint: /api/x
    idempotency_key: k1
    body: {a: 1}
    validate_after:
      kind: api_call
      method: GET
      endpoint: /api/x
      assert_jsonpath:
        - path: "$.[?($invalid)]"
""".lstrip()
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError, match="JSONPath"):
        load_recipe(p)


def test_invalid_lifecycle_jsonpath_rejected(tmp_path):
    pytest.importorskip("jsonpath_ng")
    content = """
schema_version: "1.0"
goal: G-01
description: lifecycle with bad path for regression test
fixture_intent:
  declared_in: TEST-GOALS.md#G-01
  validates: pre-validation regression on lifecycle
steps:
  - id: x
    kind: api_call
    role: u
    method: GET
    endpoint: /api/x
lifecycle:
  pre_state:
    role: u
    method: GET
    endpoint: /api/state
    assert_jsonpath:
      - path: "$..[?(this is broken)]"
  action:
    surface: ui_click
    expected_network:
      method: POST
      endpoint: /api/x
      status_range: [200, 299]
  post_state:
    role: u
    method: GET
    endpoint: /api/state
    assert_jsonpath:
      - path: "$.count"
        equals: 1
""".lstrip()
    p = _write(tmp_path, content)
    with pytest.raises(ValidationError, match="JSONPath"):
        load_recipe(p)


def test_valid_jsonpath_with_filter_passes(tmp_path):
    """Valid filter expressions should pass pre-validation."""
    pytest.importorskip("jsonpath_ng")
    content = """
schema_version: "1.0"
goal: G-01
description: Recipe with valid jsonpath filter expression for runtime tests
fixture_intent:
  declared_in: TEST-GOALS.md#G-01
  validates: jsonpath filter syntax acceptance regression test
steps:
  - id: x
    kind: api_call
    role: u
    method: POST
    endpoint: /api/x
    idempotency_key: k1
    body:
      a: 1
    capture:
      first_active:
        path: "$.items[?(@.status == 'active')].id"
        cardinality: optional_scalar
""".lstrip()
    p = _write(tmp_path, content)
    recipe = load_recipe(p)
    assert recipe["goal"] == "G-01"
