"""Load + validate FIXTURES/{G-XX}.yaml against fixture-recipe.v1.json.

RFC v9 D2 — recipe authoring at /vg:build, consumed by /vg:review preflight
and /vg:test codegen. schema_version: "1.0" mandatory; runner rejects
unknown major (D14 versioning policy).

Usage:
    from scripts.runtime import load_recipe
    recipe = load_recipe(Path("FIXTURES/G-10.yaml"))

Returns the parsed dict (validated). Raises ValidationError on:
- missing schema_version / unknown major
- schema validation failure (jsonschema) — deferred to import-time
- malformed YAML
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as e:
    raise ImportError(
        "PyYAML required for recipe loading — install with `pip install pyyaml>=6.0`"
    ) from e


class ValidationError(Exception):
    """Recipe failed schema validation or version check."""


def _schema_path() -> Path:
    """Resolve schemas/fixture-recipe.v1.json relative to repo root."""
    # __file__ = scripts/runtime/recipe_loader.py
    return Path(__file__).resolve().parents[2] / "schemas" / "fixture-recipe.v1.json"


_SCHEMA: dict[str, Any] | None = None


def _load_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(_schema_path().read_text(encoding="utf-8"))
    return _SCHEMA


def load_recipe(path: Path | str) -> dict[str, Any]:
    """Load + validate a recipe YAML.

    Args:
      path: path to FIXTURES/{G-XX}.yaml

    Returns:
      Validated recipe dict.

    Raises:
      ValidationError: schema_version major bump unsupported, or jsonschema
                       validation error (with path + actual fragment).
      FileNotFoundError: path does not exist.
      yaml.YAMLError: malformed YAML.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        recipe = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValidationError(f"YAML parse error in {p}: {e}") from e

    if not isinstance(recipe, dict):
        raise ValidationError(f"Recipe at {p} did not parse as object: got {type(recipe).__name__}")

    sv = recipe.get("schema_version")
    if sv is None:
        raise ValidationError(
            f"Recipe at {p} missing required field `schema_version` (D14)"
        )
    if not isinstance(sv, str) or not sv.startswith("1."):
        raise ValidationError(
            f"Recipe at {p} schema_version='{sv}' — runner only supports 1.x. "
            f"D14: major bump means breaking change, requires runtime upgrade."
        )

    # jsonschema validation (best-effort — schemas/ has the canonical version)
    try:
        import jsonschema
    except ImportError:
        # Allow import-time degraded mode for environments without jsonschema.
        # Runtime callers (PR-A2 executor) will refuse to execute without
        # validation. For consumers that only need the parsed dict (e.g.,
        # static analysis), this fall-through is acceptable.
        return recipe

    schema = _load_schema()
    try:
        jsonschema.validate(recipe, schema)
    except jsonschema.ValidationError as e:
        path_str = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValidationError(
            f"Recipe at {p} failed schema validation at `{path_str}`: {e.message}"
        ) from e

    return recipe
