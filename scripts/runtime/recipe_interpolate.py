"""${var} interpolation for recipe step bodies/endpoints/headers.

RFC v9 D2: recipe steps reference earlier captured values via `${name}`.
Names are dotted paths into the capture store (e.g., `${pending_id}`,
`${created.user.id}`).

Behavior:
- Whole-string match `"${name}"` → returns the captured value preserving
  type (int stays int, list stays list).
- Substring match `"User ${name} confirmed"` → returns formatted string.
- Missing variable → InterpolationError.
- Recurses into dicts and lists.
- Leaves non-string scalars (int, float, bool, None) untouched.

The whole-string vs substring distinction matters: API bodies often need
typed values (`{"amount": "${amount}"}` should yield `{"amount": 100}`,
not `{"amount": "100"}`).
"""
from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"\$\{([a-zA-Z_][\w.]*)\}")
_WHOLE_VAR_RE = re.compile(r"^\$\{([a-zA-Z_][\w.]*)\}$")


class InterpolationError(Exception):
    """Variable referenced is not in store."""


def _resolve_dotted(store: dict[str, Any], dotted: str) -> Any:
    """Walk dotted path. Raises InterpolationError if any segment missing."""
    parts = dotted.split(".")
    current: Any = store
    for i, part in enumerate(parts):
        if isinstance(current, dict):
            if part not in current:
                raise InterpolationError(
                    f"Variable '{dotted}' missing — '{part}' not found at "
                    f"depth {i} (have keys: {sorted(current)[:8]})"
                )
            current = current[part]
        else:
            raise InterpolationError(
                f"Variable '{dotted}' resolution hit non-dict at depth {i} "
                f"(type={type(current).__name__})"
            )
    return current


def interpolate(value: Any, store: dict[str, Any]) -> Any:
    """Recursively replace ${var} occurrences in `value`.

    Whole-string `"${var}"` preserves the captured value type.
    Substring matches stringify all interpolated parts.
    """
    if isinstance(value, str):
        whole = _WHOLE_VAR_RE.match(value)
        if whole:
            return _resolve_dotted(store, whole.group(1))
        return _VAR_RE.sub(
            lambda m: str(_resolve_dotted(store, m.group(1))),
            value,
        )
    if isinstance(value, list):
        return [interpolate(v, store) for v in value]
    if isinstance(value, dict):
        return {k: interpolate(v, store) for k, v in value.items()}
    return value
