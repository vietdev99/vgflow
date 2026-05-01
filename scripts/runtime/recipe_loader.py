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

    # Codex-R4-HIGH-6 fix: pre-validate JSONPath expressions at load time.
    # Schema only enforces `^$` regex; an invalid filter expression would
    # blow up AT runtime AFTER the mutation already executed. Pre-compile
    # so authoring errors surface before any HTTP traffic.
    _validate_jsonpaths(recipe, p)

    return recipe


def _validate_jsonpaths(recipe: dict[str, Any], source: Path) -> None:
    """Walk recipe.steps[].capture and validate_after.assert_jsonpath plus
    lifecycle.{pre,post}_state.assert_jsonpath. Compile each path; raise
    ValidationError on any failure."""
    try:
        from jsonpath_ng.ext import parse as _jp_parse
    except ImportError:
        return  # jsonpath-ng absent; runtime fallback evaluator catches errors

    paths_to_check: list[tuple[str, str]] = []  # (location, path)

    def collect_step(step: Any, base: str) -> None:
        if not isinstance(step, dict):
            return
        cap = step.get("capture")
        if isinstance(cap, dict):
            for name, spec in cap.items():
                if isinstance(spec, dict) and isinstance(spec.get("path"), str):
                    paths_to_check.append((f"{base}.capture[{name}].path",
                                            spec["path"]))
        va = step.get("validate_after")
        if isinstance(va, dict):
            for a in va.get("assert_jsonpath") or []:
                if isinstance(a, dict) and isinstance(a.get("path"), str):
                    paths_to_check.append(
                        (f"{base}.validate_after.assert_jsonpath.path", a["path"])
                    )
        # Recurse into loop step `each`
        each = step.get("each")
        if isinstance(each, dict):
            collect_step(each, f"{base}.each")

    for i, step in enumerate(recipe.get("steps") or []):
        collect_step(step, f"steps[{i}]")

    lifecycle = recipe.get("lifecycle")
    if isinstance(lifecycle, dict):
        for leg in ("pre_state", "post_state"):
            block = lifecycle.get(leg)
            if isinstance(block, dict):
                for a in block.get("assert_jsonpath") or []:
                    if isinstance(a, dict) and isinstance(a.get("path"), str):
                        paths_to_check.append(
                            (f"lifecycle.{leg}.assert_jsonpath.path", a["path"])
                        )
        side = lifecycle.get("side_effects") or []
        if isinstance(side, list):
            for j, eff in enumerate(side):
                if isinstance(eff, dict):
                    for a in eff.get("assert_jsonpath") or []:
                        if isinstance(a, dict) and isinstance(a.get("path"), str):
                            paths_to_check.append(
                                (f"lifecycle.side_effects[{j}].assert_jsonpath.path",
                                 a["path"])
                            )

    for location, path in paths_to_check:
        try:
            _jp_parse(path)
        except Exception as e:
            raise ValidationError(
                f"Recipe at {source} has invalid JSONPath at `{location}`: "
                f"{path!r} — {e}"
            ) from e
