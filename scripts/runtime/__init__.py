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
from .fixture_cache import (
    CacheError,
    LeaseError,
    acquire_lease,
    find_orphans,
    get_captured,
    load as cache_load,
    reap_expired_leases,
    reap_orphans,
    recipe_hash,
    release_lease,
    save as cache_save,
    write_captured,
)
from .api_index import (
    ApiIndexError,
    ResourceCounter,
    count_fn_factory,
    parse_api_index,
)
from .preflight import (
    InvariantGap,
    PreflightError,
    fix_hint,
    parse_env_contract,
    required_count,
    verify_invariants,
)
from .recipe_loader import load_recipe, ValidationError
from .recipe_capture import capture_paths, CaptureError
from .recipe_interpolate import interpolate, InterpolationError
from .recipe_safety import (
    SandboxEchoMissingError,
    SandboxSafetyError,
    assert_response_echo,
    assert_step_safe,
    assert_url_in_allowlist,
    is_sentinel_value,
)
from .recipe_auth import authenticate, AuthContext, AuthError
from .recipe_executor import AuthDegradedError, RecipeRunner, RecipeExecutionError

__all__ = [
    "load_recipe",
    "ValidationError",
    "capture_paths",
    "CaptureError",
    "interpolate",
    "InterpolationError",
    "assert_step_safe",
    "assert_url_in_allowlist",
    "assert_response_echo",
    "SandboxSafetyError",
    "SandboxEchoMissingError",
    "is_sentinel_value",
    "AuthDegradedError",
    "authenticate",
    "AuthContext",
    "AuthError",
    "RecipeRunner",
    "RecipeExecutionError",
    "CacheError",
    "LeaseError",
    "acquire_lease",
    "release_lease",
    "write_captured",
    "get_captured",
    "find_orphans",
    "reap_orphans",
    "reap_expired_leases",
    "recipe_hash",
    "cache_load",
    "cache_save",
    "InvariantGap",
    "PreflightError",
    "parse_env_contract",
    "required_count",
    "verify_invariants",
    "fix_hint",
    "ApiIndexError",
    "ResourceCounter",
    "count_fn_factory",
    "parse_api_index",
]
