"""Recipe runtime public surface.

The package is intentionally lazy: many commands import one runtime submodule
for static checks, and they must not pull optional HTTP/YAML dependencies.
Runtime-only exports are imported when accessed.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


class _MissingRecipeValidationError(Exception):
    """Fallback when recipe_loader dependencies are not installed."""


def _missing_load_recipe(*_args: Any, **_kwargs: Any) -> Any:
    raise ImportError(
        "Recipe loading requires optional dependencies such as PyYAML. "
        "Install workflow runtime extras before executing fixture recipes."
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "CacheError": ("fixture_cache", "CacheError"),
    "LeaseError": ("fixture_cache", "LeaseError"),
    "acquire_lease": ("fixture_cache", "acquire_lease"),
    "find_orphans": ("fixture_cache", "find_orphans"),
    "get_captured": ("fixture_cache", "get_captured"),
    "cache_load": ("fixture_cache", "load"),
    "reap_expired_leases": ("fixture_cache", "reap_expired_leases"),
    "reap_orphans": ("fixture_cache", "reap_orphans"),
    "recipe_hash": ("fixture_cache", "recipe_hash"),
    "release_lease": ("fixture_cache", "release_lease"),
    "cache_save": ("fixture_cache", "save"),
    "write_captured": ("fixture_cache", "write_captured"),
    "ApiIndexError": ("api_index", "ApiIndexError"),
    "ResourceCounter": ("api_index", "ResourceCounter"),
    "count_fn_factory": ("api_index", "count_fn_factory"),
    "parse_api_index": ("api_index", "parse_api_index"),
    "InvariantGap": ("preflight", "InvariantGap"),
    "PreflightError": ("preflight", "PreflightError"),
    "fix_hint": ("preflight", "fix_hint"),
    "parse_env_contract": ("preflight", "parse_env_contract"),
    "required_count": ("preflight", "required_count"),
    "verify_invariants": ("preflight", "verify_invariants"),
    "load_recipe": ("recipe_loader", "load_recipe"),
    "ValidationError": ("recipe_loader", "ValidationError"),
    "capture_paths": ("recipe_capture", "capture_paths"),
    "CaptureError": ("recipe_capture", "CaptureError"),
    "interpolate": ("recipe_interpolate", "interpolate"),
    "InterpolationError": ("recipe_interpolate", "InterpolationError"),
    "SandboxEchoMissingError": ("recipe_safety", "SandboxEchoMissingError"),
    "SandboxSafetyError": ("recipe_safety", "SandboxSafetyError"),
    "assert_response_echo": ("recipe_safety", "assert_response_echo"),
    "assert_step_safe": ("recipe_safety", "assert_step_safe"),
    "assert_url_in_allowlist": ("recipe_safety", "assert_url_in_allowlist"),
    "is_sentinel_value": ("recipe_safety", "is_sentinel_value"),
    "authenticate": ("recipe_auth", "authenticate"),
    "AuthContext": ("recipe_auth", "AuthContext"),
    "AuthError": ("recipe_auth", "AuthError"),
    "AuthDegradedError": ("recipe_executor", "AuthDegradedError"),
    "RecipeRunner": ("recipe_executor", "RecipeRunner"),
    "RecipeExecutionError": ("recipe_executor", "RecipeExecutionError"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    try:
        module = import_module(f"{__name__}.{module_name}")
        value = getattr(module, attr_name)
    except ImportError:
        if name == "load_recipe":
            value = _missing_load_recipe
        elif name == "ValidationError":
            value = _MissingRecipeValidationError
        else:
            raise

    globals()[name] = value
    return value
