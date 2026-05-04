"""Parse api_index from ENV-CONTRACT.md (RFC v9 PR-C wiring).

`api_index` maps logical resource names to:
- count_endpoint: GET endpoint that returns a count or list-with-meta
- count_jsonpath: JSONPath into the response body to extract an integer
- count_role: which credentials_map role to authenticate as

ENV-CONTRACT.md fragment:
```yaml
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
    count_query_keys: [tier, status]   # which `where` keys map to query params
  withdraw:
    count_endpoint: /api/admin/withdraw
    count_jsonpath: $.data.length
    count_role: admin
```

Used by preflight.verify_invariants's count_fn — for every invariant
`{resource: topup, where: {tier:2, status:pending}}`, the count_fn:
1. Looks up api_index[topup].
2. Builds GET {count_endpoint}?tier=2&status=pending (only count_query_keys
   passed through; extras dropped to avoid backend confusion).
3. Authenticates as count_role.
4. Captures count_jsonpath into an integer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


class ApiIndexError(Exception):
    """api_index missing, malformed, or incomplete for a requested resource."""


@dataclass
class ResourceCounter:
    resource: str
    count_endpoint: str
    count_jsonpath: str
    count_role: str
    count_query_keys: list[str] = field(default_factory=list)


def parse_api_index(path: Path | str) -> dict[str, ResourceCounter]:
    """Extract `api_index:` block from ENV-CONTRACT.md.

    Same parsing strategy as preflight.parse_env_contract — accepts both
    fenced ```yaml block and pure-yaml file.
    """
    text = Path(path).read_text(encoding="utf-8")
    if yaml is None:
        raise ApiIndexError("PyYAML required for ENV-CONTRACT parsing")

    parsed: Any = None
    blocks = re.findall(r"```ya?ml\s*\n(.*?)\n```", text, re.DOTALL)
    for block in blocks:
        if "api_index:" in block:
            try:
                parsed = yaml.safe_load(block)
                if isinstance(parsed, dict) and "api_index" in parsed:
                    break
            except yaml.YAMLError as e:
                raise ApiIndexError(f"Malformed YAML block in ENV-CONTRACT: {e}") from e
            parsed = None
    if parsed is None:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            return {}
        if not isinstance(parsed, dict) or "api_index" not in parsed:
            return {}

    raw = parsed.get("api_index") or {}
    if not isinstance(raw, dict):
        raise ApiIndexError(f"api_index must be object, got {type(raw).__name__}")

    out: dict[str, ResourceCounter] = {}
    for resource, spec in raw.items():
        if not isinstance(spec, dict):
            raise ApiIndexError(f"api_index['{resource}'] must be object")
        for required in ("count_endpoint", "count_jsonpath", "count_role"):
            if required not in spec:
                raise ApiIndexError(
                    f"api_index['{resource}'] missing '{required}'"
                )
        out[str(resource)] = ResourceCounter(
            resource=str(resource),
            count_endpoint=str(spec["count_endpoint"]),
            count_jsonpath=str(spec["count_jsonpath"]),
            count_role=str(spec["count_role"]),
            count_query_keys=[str(k) for k in (spec.get("count_query_keys") or [])],
        )
    return out


def count_fn_factory(
    api_index: dict[str, ResourceCounter],
    runner: Any,  # RecipeRunner — duck-typed to avoid circular import
):
    """Return a count_fn(resource, where) → int closing over runner + index.

    Drops `where` keys not in count_query_keys (when configured) so the
    backend doesn't 400 on unknown query params. When count_query_keys is
    empty, all keys pass through.
    """
    from .recipe_capture import capture_paths

    def count_fn(resource: str, where: dict[str, Any]) -> int:
        spec = api_index.get(resource)
        if spec is None:
            raise ApiIndexError(
                f"api_index has no entry for resource '{resource}'. "
                f"Add it to ENV-CONTRACT.md api_index block, or remove the "
                f"invariant referencing it."
            )
        # Filter where → query params per count_query_keys allowlist
        if spec.count_query_keys:
            params = {
                k: v for k, v in where.items() if k in spec.count_query_keys
            }
        else:
            params = dict(where)

        auth = runner._auth_context(spec.count_role)
        url = runner.base_url.rstrip("/") + spec.count_endpoint
        resp = auth.session.get(url, params=params, timeout=runner.request_timeout)
        if resp.status_code >= 400:
            raise ApiIndexError(
                f"count GET {spec.count_endpoint} for resource '{resource}' "
                f"returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json() if resp.text else {}
        except Exception as e:
            raise ApiIndexError(f"count response not JSON: {e}") from e

        # Capture as array first; treat single-match as scalar, multi-match as len.
        captured = capture_paths(
            payload,
            {"_n": {"path": spec.count_jsonpath, "cardinality": "array",
                    "on_empty": "null"}},
        )
        matches = captured.get("_n")

        if matches is None or matches == []:
            return 0
        if len(matches) == 1:
            value = matches[0]
            if isinstance(value, bool):  # bool subclasses int — reject
                raise ApiIndexError(
                    f"count_jsonpath '{spec.count_jsonpath}' resolved to bool"
                )
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    raise ApiIndexError(
                        f"count_jsonpath '{spec.count_jsonpath}' resolved to "
                        f"non-numeric string {value!r}"
                    )
            if isinstance(value, list):
                return len(value)
            raise ApiIndexError(
                f"count_jsonpath '{spec.count_jsonpath}' resolved to "
                f"{type(value).__name__}={value!r}; expected int, str, or list"
            )
        # Multi-match: caller asked for an array path → count is the list size
        return len(matches)

    return count_fn
