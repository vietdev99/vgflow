"""JSONPath capture with cardinality enforcement (RFC v9 D2 capture spec).

Capture spec entries:
    capture:
      pending_id:
        path: $.data.id
        cardinality: scalar          # default
        on_empty: fail               # default
      list_ids:
        path: $.data.items[*].id
        cardinality: array
        on_empty: skip
      optional_token:
        path: $.token
        cardinality: optional_scalar
        on_empty: null

Behavior:
- scalar     → exactly 1 match. >1 → CaptureError.
- array      → 0+ matches as list.
- optional_scalar → 0 or 1 match. on_empty='null' returns None.
- on_empty='fail' raises CaptureError on 0 matches (default for scalar).
- on_empty='skip' returns key omitted from result.
- on_empty='null' returns key with value None.

Uses jsonpath-ng (RFC 9535-aligned). Falls back to a simple in-house parser
if jsonpath-ng is unavailable, supporting only `$.dotted.path[index]` —
sufficient for ~90% of recipes.
"""
from __future__ import annotations

import re
from typing import Any


class CaptureError(Exception):
    """Capture failed validation (cardinality mismatch, on_empty=fail)."""


def _have_jsonpath_ng() -> bool:
    try:
        import jsonpath_ng  # noqa: F401
        return True
    except ImportError:
        return False


def _evaluate_jsonpath(path: str, payload: Any) -> list[Any]:
    """Return list of matches for `path` in `payload`.

    Prefers jsonpath-ng. Falls back to a stdlib `$.a.b[0].c[*]` evaluator.
    """
    if _have_jsonpath_ng():
        from jsonpath_ng.ext import parse  # ext supports filter expressions
        try:
            expr = parse(path)
        except Exception as e:
            raise CaptureError(f"Invalid JSONPath '{path}': {e}") from e
        return [m.value for m in expr.find(payload)]
    return _fallback_evaluate(path, payload)


_FALLBACK_RE = re.compile(r"\$(?:\.[a-zA-Z_][\w]*|\[(?:\*|\d+)\])+")


def _fallback_evaluate(path: str, payload: Any) -> list[Any]:
    if not _FALLBACK_RE.fullmatch(path):
        raise CaptureError(
            f"Fallback JSONPath only supports $.a.b[0].c[*] form. Got '{path}'. "
            f"Install jsonpath-ng for full RFC 9535 support."
        )
    # Tokenize: drop leading $ then split on `.` and `[` boundaries.
    tokens: list[str | int | object] = []
    STAR = object()
    cursor = 1  # skip $
    while cursor < len(path):
        ch = path[cursor]
        if ch == ".":
            cursor += 1
            m = re.match(r"[a-zA-Z_][\w]*", path[cursor:])
            assert m is not None, f"unreachable — regex pre-validated {path}"
            tokens.append(m.group(0))
            cursor += len(m.group(0))
        elif ch == "[":
            close = path.index("]", cursor)
            inner = path[cursor + 1 : close]
            tokens.append(STAR if inner == "*" else int(inner))
            cursor = close + 1
        else:
            raise CaptureError(f"Unexpected char '{ch}' at position {cursor} in {path}")

    current: list[Any] = [payload]
    for tok in tokens:
        next_layer: list[Any] = []
        for item in current:
            if tok is STAR:
                if isinstance(item, list):
                    next_layer.extend(item)
            elif isinstance(tok, int):
                if isinstance(item, list) and -len(item) <= tok < len(item):
                    next_layer.append(item[tok])
            else:  # str key
                if isinstance(item, dict) and tok in item:
                    next_layer.append(item[tok])
        current = next_layer
    return current


def capture_paths(payload: Any, capture_spec: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Apply a capture spec to a response payload.

    Args:
      payload: parsed JSON response body (dict/list).
      capture_spec: { name: { path, cardinality, on_empty } }

    Returns:
      Captured values keyed by name. Missing-with-skip keys omitted entirely.

    Raises:
      CaptureError: on_empty=fail with 0 matches; cardinality=scalar with
                    multiple matches; bad path.
    """
    out: dict[str, Any] = {}
    if not isinstance(capture_spec, dict):
        raise CaptureError(f"capture spec must be dict, got {type(capture_spec).__name__}")
    for name, spec in capture_spec.items():
        if not isinstance(spec, dict):
            raise CaptureError(f"capture[{name}] must be object, got {type(spec).__name__}")
        path = spec.get("path")
        if not path:
            raise CaptureError(f"capture[{name}] missing required 'path'")
        cardinality = spec.get("cardinality", "scalar")
        on_empty = spec.get("on_empty", "fail")

        matches = _evaluate_jsonpath(path, payload)

        if not matches:
            if on_empty == "fail":
                raise CaptureError(
                    f"capture[{name}] path '{path}' returned no matches "
                    f"(cardinality={cardinality}, on_empty=fail)"
                )
            if on_empty == "skip":
                continue
            if on_empty == "null":
                out[name] = None
                continue
            raise CaptureError(
                f"capture[{name}] unknown on_empty='{on_empty}' "
                f"(must be fail|skip|null)"
            )

        if cardinality == "scalar":
            if len(matches) > 1:
                raise CaptureError(
                    f"capture[{name}] path '{path}' expected scalar, got "
                    f"{len(matches)} matches"
                )
            out[name] = matches[0]
        elif cardinality == "optional_scalar":
            if len(matches) > 1:
                raise CaptureError(
                    f"capture[{name}] path '{path}' expected optional_scalar, "
                    f"got {len(matches)} matches"
                )
            out[name] = matches[0]
        elif cardinality == "array":
            out[name] = matches
        else:
            raise CaptureError(
                f"capture[{name}] unknown cardinality='{cardinality}' "
                f"(must be scalar|optional_scalar|array)"
            )

    return out
