"""Recipe runtime — RFC v9 native Python orchestrator.

Modules:
- recipe_loader: parse YAML + jsonschema validate against fixture-recipe.v1.json
- recipe_capture: JSONPath capture with cardinality enforcement (RFC 9535)
- recipe_interpolate: ${var} interpolation from captured store
- recipe_executor (PR-A2): API execution + 4 auth handlers + sandbox safety
- fixture_cache (PR-A3): FIXTURES-CACHE.json + lease management

Public surface (PR-A1):
- load_recipe(path) → dict
- ValidationError on schema mismatch
- capture_paths(payload, capture_spec) → dict[str, Any]
- interpolate(template, store) → resolved string

Stability: schema_version: "1.0" pinned. Major bump rejected at load time.
"""
from .recipe_loader import load_recipe, ValidationError
from .recipe_capture import capture_paths, CaptureError
from .recipe_interpolate import interpolate, InterpolationError
from .recipe_safety import assert_step_safe, SandboxSafetyError, is_sentinel_value
from .recipe_auth import authenticate, AuthContext, AuthError
from .recipe_executor import RecipeRunner, RecipeExecutionError

__all__ = [
    "load_recipe",
    "ValidationError",
    "capture_paths",
    "CaptureError",
    "interpolate",
    "InterpolationError",
    "assert_step_safe",
    "SandboxSafetyError",
    "is_sentinel_value",
    "authenticate",
    "AuthContext",
    "AuthError",
    "RecipeRunner",
    "RecipeExecutionError",
]
