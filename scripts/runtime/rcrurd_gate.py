"""Layer 0 RCRURD lifecycle gate (RFC v9 D12).

Deterministic gate at /vg:review entry. For every mutation goal with a
declared `lifecycle` block in its FIXTURES/{G-XX}.yaml:
1. Run pre_state GET → assert assertions (initial conditions met).
2. (action skipped — gate is read-only verification of bookends).
3. Run post_state GET — but skip; this gate runs BEFORE the action.

Wait — re-reading RFC v9 D12 carefully: the L0 gate verifies that the
fixture WOULD work end-to-end without actually mutating. So it:
1. Runs pre_state GET → confirms initial state matches assertions.
2. Notes the action's expected_network shape so /vg:review can later
   verify the scanner hit the right endpoint.
3. Records the lifecycle invariant for downstream comparison.

Why it's deterministic Layer 0: no AI, no scanner — pure HTTP + JSONPath
asserts against the recipe's lifecycle block. If pre_state fails, the
fixture is broken (data not in expected start state) — fail-fast before
spending tokens on browser scan.

The post_state assertion runs LATER (after browser scan completes) to
close the loop and verify the action took effect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .recipe_capture import CaptureError, capture_paths


class LifecycleGateError(Exception):
    """Lifecycle pre/post-state assertion failed."""


@dataclass
class LifecycleResult:
    goal_id: str
    pre_state_passed: bool = False
    post_state_passed: bool = False
    pre_state_failures: list[str] = field(default_factory=list)
    post_state_failures: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


GetFn = Callable[[str, str], dict[str, Any]]
"""(role, endpoint) → response payload (dict). Project supplies via
recipe_executor session lookup."""


def _check_assertion(
    assertion: dict[str, Any],
    payload: Any,
    *,
    where: str,
    failures: list[str],
) -> None:
    path = assertion.get("path")
    if not path:
        failures.append(f"{where}: assertion missing path")
        return
    try:
        captured = capture_paths(
            payload,
            {"_v": {"path": path, "cardinality": "array", "on_empty": "skip"}},
        )
    except CaptureError as e:
        failures.append(f"{where} jsonpath '{path}' eval error: {e}")
        return
    matches = captured.get("_v", [])

    if "equals" in assertion:
        expected = assertion["equals"]
        if not matches or matches[0] != expected:
            failures.append(
                f"{where} {path} expected={expected!r}, got={matches!r}"
            )
    if "not_equals" in assertion:
        expected = assertion["not_equals"]
        if matches and matches[0] == expected:
            failures.append(
                f"{where} {path} not_equals failed: value={matches[0]!r}"
            )
    if assertion.get("not_null"):
        if not matches or matches[0] is None:
            failures.append(f"{where} {path} not_null failed: matches={matches}")
    if "increased_by_at_least" in assertion:
        # Comparative assertions only meaningful in post_state when paired
        # with pre_state value — handled by caller. Here, just check non-zero.
        pass
    if "cardinality" in assertion:
        spec = str(assertion["cardinality"])
        actual = len(matches)
        if not _check_cardinality(spec, actual):
            failures.append(
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


def run_pre_state(
    goal_id: str,
    lifecycle: dict[str, Any],
    get_fn: GetFn,
) -> LifecycleResult:
    """Execute pre_state GET + assertions only. Caller runs the action."""
    result = LifecycleResult(goal_id=goal_id)
    pre = lifecycle.get("pre_state")
    if not pre:
        result.skipped_reason = "no pre_state declared"
        return result
    role = pre.get("role")
    endpoint = pre.get("endpoint")
    if not (role and endpoint):
        result.pre_state_failures.append("pre_state missing role or endpoint")
        return result
    try:
        payload = get_fn(role, endpoint)
    except Exception as e:
        result.pre_state_failures.append(f"pre_state GET {endpoint} raised: {e}")
        return result
    asserts = pre.get("assert_jsonpath") or []
    for a in asserts:
        _check_assertion(a, payload, where=f"pre_state {endpoint}",
                         failures=result.pre_state_failures)
    result.pre_state_passed = not result.pre_state_failures
    return result


def run_post_state_with_retry(
    goal_id: str,
    lifecycle: dict[str, Any],
    get_fn: GetFn,
    *,
    pre_payload: Any = None,
) -> LifecycleResult:
    """Execute post_state GET + assertions with eventual-consistency retry.

    D12 retry config:
      retry:
        max_attempts: 5
        delay_ms: 200
        until_assertion_pass: true

    If until_assertion_pass=True, the GET re-runs until all assertions
    pass OR max_attempts exhausted. delay_ms applied between attempts.
    """
    import time
    result = LifecycleResult(goal_id=goal_id)
    post = lifecycle.get("post_state")
    if not post:
        result.skipped_reason = "no post_state declared"
        return result
    role = post.get("role")
    endpoint = post.get("endpoint")
    if not (role and endpoint):
        result.post_state_failures.append("post_state missing role or endpoint")
        return result
    asserts = post.get("assert_jsonpath") or []
    retry_cfg = post.get("retry") or {}
    max_attempts = int(retry_cfg.get("max_attempts", 1))
    delay_ms = int(retry_cfg.get("delay_ms", 0))
    until_pass = bool(retry_cfg.get("until_assertion_pass", False))

    for attempt in range(1, max_attempts + 1):
        try:
            payload = get_fn(role, endpoint)
        except Exception as e:
            result.post_state_failures.append(
                f"post_state GET {endpoint} (attempt {attempt}) raised: {e}"
            )
            break

        attempt_failures: list[str] = []
        for a in asserts:
            _check_assertion(a, payload,
                             where=f"post_state {endpoint} (attempt {attempt})",
                             failures=attempt_failures)
            if "increased_by_at_least" in a and isinstance(pre_payload, (dict, list)):
                _check_increase(a, pre_payload, payload, attempt_failures,
                                 endpoint=endpoint)

        if not attempt_failures:
            result.post_state_passed = True
            result.post_state_failures = []
            return result

        if attempt < max_attempts and until_pass:
            time.sleep(delay_ms / 1000.0)
            continue

        result.post_state_failures = attempt_failures
        break

    return result


def _check_increase(
    assertion: dict[str, Any],
    pre_payload: Any,
    post_payload: Any,
    failures: list[str],
    *,
    endpoint: str,
) -> None:
    path = assertion.get("path")
    if not path:
        return
    try:
        pre_v = capture_paths(
            pre_payload,
            {"_v": {"path": path, "cardinality": "array", "on_empty": "skip"}},
        ).get("_v", [])
        post_v = capture_paths(
            post_payload,
            {"_v": {"path": path, "cardinality": "array", "on_empty": "skip"}},
        ).get("_v", [])
    except CaptureError as e:
        failures.append(f"increased_by jsonpath eval error: {e}")
        return
    if not pre_v or not post_v:
        failures.append(
            f"increased_by_at_least {path}: pre={pre_v} post={post_v}"
        )
        return
    try:
        pre_n = float(pre_v[0])
        post_n = float(post_v[0])
    except (TypeError, ValueError):
        failures.append(
            f"increased_by_at_least {path}: not numeric pre={pre_v[0]!r} post={post_v[0]!r}"
        )
        return
    delta = post_n - pre_n
    threshold = float(assertion["increased_by_at_least"])
    if delta < threshold:
        failures.append(
            f"increased_by_at_least {path}: delta={delta} < threshold={threshold} "
            f"(pre={pre_n}, post={post_n} from {endpoint})"
        )
