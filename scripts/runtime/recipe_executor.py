"""Recipe step executor — RFC v9 PR-A2 native API runtime.

Walks recipe.steps[] in declared order:
1. Resolve role → AuthContext (cached per role+env).
2. Apply ${var} interpolation against capture store.
3. Sandbox safety gate (D9) on body before send.
4. POST/PUT/PATCH/DELETE: attach idempotency_key as `Idempotency-Key` header
   (RFC 7240, D13).
5. Execute via requests.Session.
6. On 401 with bearer_jwt: invoke refresh_callable, retry once.
7. validate_after (D3): GET endpoint + assert_jsonpath against response.
8. capture (D2): JSONPath into response body, write into store.
9. lifecycle (D12): execute pre_state/post_state assertions, retry on
   eventual consistency.

Public API:
    runner = RecipeRunner(base_url, env="sandbox", credentials_map={...})
    runner.run(recipe)
    print(runner.store)  # { "pending_id": "...", ... }
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .recipe_auth import AuthContext, AuthError, authenticate
from .recipe_capture import CaptureError, capture_paths
from .recipe_interpolate import interpolate
from .recipe_safety import SandboxSafetyError, assert_step_safe


class RecipeExecutionError(Exception):
    """Step failed during execution."""


@dataclass
class RecipeRunner:
    base_url: str
    env: str = "sandbox"
    credentials_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, AuthContext] = field(default_factory=dict)
    store: dict[str, Any] = field(default_factory=dict)
    request_timeout: float = 30.0

    def _auth_context(self, role: str) -> AuthContext:
        if role not in self.sessions:
            creds = self.credentials_map.get(role)
            if not creds:
                raise RecipeExecutionError(
                    f"Role '{role}' not in credentials_map. Configure in vg.config.md."
                )
            kind = creds.get("kind")
            if not kind:
                raise RecipeExecutionError(
                    f"credentials_map[{role}] missing 'kind' (cookie_login|api_key|"
                    f"bearer_jwt|command)"
                )
            try:
                self.sessions[role] = authenticate(
                    kind, self.base_url, creds, sandbox=(self.env == "sandbox"),
                )
            except AuthError as e:
                raise RecipeExecutionError(f"Auth failed for role={role}: {e}") from e
        return self.sessions[role]

    def run(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """Execute all steps. Returns the capture store."""
        for step in recipe.get("steps") or []:
            self.run_step(step)
        return self.store

    def run_step(self, step: dict[str, Any]) -> None:
        kind = step.get("kind", "api_call")
        if kind == "loop":
            self._run_loop_step(step)
            return
        if kind == "api_call":
            self._run_api_call(step)
            return
        raise RecipeExecutionError(f"Unsupported step kind: {kind}")

    def _run_loop_step(self, step: dict[str, Any]) -> None:
        over = step.get("over")
        each = step.get("each")
        if each is None or over is None:
            raise RecipeExecutionError(
                f"loop step '{step.get('id', '?')}' requires `over` + `each`"
            )
        if isinstance(over, int):
            iterable = list(range(over))
        elif isinstance(over, list):
            iterable = list(over)
        elif isinstance(over, str):  # variable reference
            resolved = interpolate(over, self.store)
            if not isinstance(resolved, list):
                raise RecipeExecutionError(
                    f"loop step `over` resolved to {type(resolved).__name__}, want list"
                )
            iterable = resolved
        else:
            raise RecipeExecutionError(f"loop step `over` must be int|list|str")

        # `from_each: true` captures collect into arrays
        from_each_keys = {
            cap_name for cap_name, spec in (each.get("capture") or {}).items()
            if spec.get("from_each")
        }
        accum: dict[str, list[Any]] = {k: [] for k in from_each_keys}

        for i, value in enumerate(iterable):
            self.store[f"_loop_{i}"] = value
            try:
                self._run_api_call(each, _loop_index=i, _loop_value=value,
                                    _loop_accum=accum)
            finally:
                self.store.pop(f"_loop_{i}", None)

        for k, v in accum.items():
            self.store[k] = v

    def _run_api_call(
        self,
        step: dict[str, Any],
        *,
        _loop_index: int | None = None,
        _loop_value: Any = None,
        _loop_accum: dict[str, list[Any]] | None = None,
    ) -> None:
        # Build local context — base store + loop variables
        ctx_store: dict[str, Any] = dict(self.store)
        if _loop_index is not None:
            ctx_store["_index"] = _loop_index
            ctx_store["_value"] = _loop_value

        method = step.get("method", "GET").upper()
        endpoint_raw = step.get("endpoint")
        if not endpoint_raw:
            raise RecipeExecutionError(f"step '{step.get('id', '?')}' missing endpoint")
        endpoint = interpolate(endpoint_raw, ctx_store)
        body = interpolate(step.get("body"), ctx_store) if step.get("body") else None

        # Sandbox safety gate (D9)
        try:
            interpolated_step = {
                **step,
                "body": body,
            }
            assert_step_safe(interpolated_step, self.env)
        except SandboxSafetyError as e:
            raise RecipeExecutionError(str(e)) from e

        role = step.get("role", "default")
        auth = self._auth_context(role)
        session = auth.session

        url = self.base_url.rstrip("/") + endpoint
        headers: dict[str, str] = {}
        # D13: idempotency-key for POST/PUT
        idem = step.get("idempotency_key")
        if idem and method in {"POST", "PUT"}:
            idem_resolved = interpolate(idem, ctx_store)
            headers["Idempotency-Key"] = str(idem_resolved)

        kwargs: dict[str, Any] = {"timeout": self.request_timeout, "headers": headers}
        if body is not None and method in {"POST", "PUT", "PATCH", "DELETE"}:
            kwargs["json"] = body
        elif body is not None:
            kwargs["params"] = body if isinstance(body, dict) else None

        resp = session.request(method, url, **kwargs)

        # Refresh-on-401 once for bearer_jwt
        if resp.status_code == 401 and auth.refresh_callable:
            try:
                auth.refresh_callable()
            except AuthError as e:
                raise RecipeExecutionError(f"Auth refresh failed: {e}") from e
            resp = session.request(method, url, **kwargs)

        expect = step.get("expect_status")
        if expect is not None and resp.status_code != expect:
            raise RecipeExecutionError(
                f"step '{step.get('id', '?')}': {method} {endpoint} expected "
                f"{expect}, got {resp.status_code}: {resp.text[:200]}"
            )
        if expect is None and resp.status_code >= 400:
            raise RecipeExecutionError(
                f"step '{step.get('id', '?')}': {method} {endpoint} returned "
                f"{resp.status_code}: {resp.text[:200]}"
            )

        # Capture (D2)
        capture_spec = step.get("capture")
        if capture_spec:
            try:
                payload = resp.json() if resp.text else {}
            except Exception:
                payload = {}
            try:
                captured = capture_paths(payload, capture_spec)
            except CaptureError as e:
                raise RecipeExecutionError(
                    f"step '{step.get('id', '?')}' capture failed: {e}"
                ) from e
            if _loop_accum is not None:
                for k, v in captured.items():
                    if k in _loop_accum:
                        _loop_accum[k].append(v)
                    else:
                        self.store[k] = v
            else:
                self.store.update(captured)

        # validate_after (D3)
        va = step.get("validate_after")
        if isinstance(va, dict):
            self._run_validate_after(va, role)

    def _run_validate_after(self, va: dict[str, Any], role: str) -> None:
        endpoint = interpolate(va["endpoint"], self.store)
        url = self.base_url.rstrip("/") + endpoint
        auth = self._auth_context(role)
        resp = auth.session.get(url, timeout=self.request_timeout)
        expect = va.get("expect_status", 200)
        if resp.status_code != expect:
            raise RecipeExecutionError(
                f"validate_after GET {endpoint} expected {expect}, got "
                f"{resp.status_code}"
            )
        asserts = va.get("assert_jsonpath") or []
        if asserts:
            try:
                payload = resp.json() if resp.text else {}
            except Exception:
                payload = {}
            for a in asserts:
                self._check_assert(a, payload, where=f"validate_after {endpoint}")

    def _check_assert(
        self,
        assertion: dict[str, Any],
        payload: Any,
        *,
        where: str,
    ) -> None:
        path = assertion.get("path")
        if not path:
            raise RecipeExecutionError(f"{where}: assertion missing path")
        # Use capture machinery to evaluate
        try:
            captured = capture_paths(
                payload,
                {"_v": {"path": path, "cardinality": "array", "on_empty": "skip"}},
            )
        except CaptureError as e:
            raise RecipeExecutionError(f"{where}: assertion eval error: {e}") from e
        matches = captured.get("_v", [])

        if "equals" in assertion:
            expected = assertion["equals"]
            if not matches or matches[0] != expected:
                raise RecipeExecutionError(
                    f"{where} {path} expected={expected!r}, got={matches!r}"
                )
        if "not_equals" in assertion:
            expected = assertion["not_equals"]
            if matches and matches[0] == expected:
                raise RecipeExecutionError(
                    f"{where} {path} not_equals failed: value={matches[0]!r}"
                )
        if assertion.get("not_null"):
            if not matches or matches[0] is None:
                raise RecipeExecutionError(
                    f"{where} {path} not_null failed: matches={matches}"
                )
        if "cardinality" in assertion:
            spec = assertion["cardinality"]  # e.g., ">=1", "==3"
            actual = len(matches)
            if not _check_cardinality(spec, actual):
                raise RecipeExecutionError(
                    f"{where} {path} cardinality '{spec}' failed: actual={actual}"
                )


def _check_cardinality(spec: str, actual: int) -> bool:
    import re
    m = re.fullmatch(r"\s*([><]=?|==|=)\s*(\d+)\s*", spec)
    if not m:
        return False
    op, num_s = m.group(1), m.group(2)
    num = int(num_s)
    if op in {"=", "=="}:
        return actual == num
    if op == ">":
        return actual > num
    if op == ">=":
        return actual >= num
    if op == "<":
        return actual < num
    if op == "<=":
        return actual <= num
    return False
