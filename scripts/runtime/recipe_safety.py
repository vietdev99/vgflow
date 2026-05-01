"""Sandbox safety gate (RFC v9 D9).

Hard rule: when env=sandbox, fixture execution must:
1. Send `X-VGFlow-Sandbox: true` header (handled by recipe_auth).
2. Use sentinel values that backend can recognize as test data:
   - Email pattern: `*@fixture.vgflow.test`
   - Env-prefixed identifiers: `VG_FIXTURE_*`
   - Money amounts ≤ 0.01 (configurable per project)
3. Reject `side_effect_risk` ∈ {money_like, external_call, volume_change}
   when env != sandbox.

Failure mode this closes: project's fixture goes ROGUE because backend
doesn't filter by header — money or external API is hit in main. Sentinels
make the breach detectable in postmortem (DB query for VG_FIXTURE_* and
fixture.vgflow.test emails surfaces stray data).
"""
from __future__ import annotations

import re
from typing import Any


class SandboxSafetyError(Exception):
    """Sandbox safety gate refused to execute step."""


SENTINEL_EMAIL_RE = re.compile(r"@fixture\.vgflow\.test\b", re.IGNORECASE)
SENTINEL_PREFIX_RE = re.compile(r"\bVG_FIXTURE_[A-Z0-9_]+\b")
DEFAULT_MAX_MONEY_AMOUNT = 0.01

RISKY_SIDE_EFFECTS = {"money_like", "external_call", "volume_change"}


def is_sentinel_value(value: Any) -> bool:
    """True if value carries an obvious VG fixture sentinel."""
    if isinstance(value, str):
        return bool(SENTINEL_EMAIL_RE.search(value)) or bool(SENTINEL_PREFIX_RE.search(value))
    if isinstance(value, (int, float)):
        try:
            return float(value) <= DEFAULT_MAX_MONEY_AMOUNT
        except (TypeError, ValueError):
            return False
    return False


def assert_step_safe(
    step: dict,
    env: str,
    *,
    money_keys: tuple[str, ...] = ("amount", "total", "value", "price"),
    max_money: float = DEFAULT_MAX_MONEY_AMOUNT,
) -> None:
    """Raise if step would be unsafe in this env.

    Rules:
    - side_effect_risk ∈ RISKY_SIDE_EFFECTS → only sandbox allowed.
    - In sandbox: money fields > max_money → must carry sentinel marker
      elsewhere in body (email, prefix). Unprovable safety → reject.
    - Outside sandbox: side_effect_risk='none' or absent OR explicit
      `assert_step_safe(env='main', side_effect_risk='read')` accepted.
    """
    risk = step.get("side_effect_risk", "none")
    if risk in RISKY_SIDE_EFFECTS and env != "sandbox":
        raise SandboxSafetyError(
            f"step '{step.get('id', '?')}' has side_effect_risk='{risk}' but "
            f"env='{env}' — risky steps require env=sandbox (D9). Switch env "
            f"or set side_effect_risk=none if step is safely read-only."
        )

    if env == "sandbox":
        body = step.get("body") or {}
        if not isinstance(body, dict):
            return  # nothing to check
        # Collect all string + numeric leaves
        body_text = _stringify_leaves(body)
        body_amounts = _collect_money_values(body, money_keys)
        # Any money field > threshold → require any sentinel anywhere in body
        suspicious = [v for v in body_amounts if v > max_money]
        if suspicious:
            has_sentinel = (
                SENTINEL_EMAIL_RE.search(body_text)
                or SENTINEL_PREFIX_RE.search(body_text)
            )
            if not has_sentinel:
                raise SandboxSafetyError(
                    f"step '{step.get('id', '?')}' body has money-like "
                    f"value(s) {suspicious} > {max_money} in sandbox but no "
                    f"sentinel marker (VG_FIXTURE_* or @fixture.vgflow.test). "
                    f"D9 demands traceable test data."
                )


def _stringify_leaves(value: Any, parts: list[str] | None = None) -> str:
    if parts is None:
        parts = []
    if isinstance(value, dict):
        for v in value.values():
            _stringify_leaves(v, parts)
    elif isinstance(value, list):
        for v in value:
            _stringify_leaves(v, parts)
    elif isinstance(value, str):
        parts.append(value)
    return "\n".join(parts)


def _collect_money_values(value: Any, money_keys: tuple[str, ...]) -> list[float]:
    out: list[float] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in money_keys and isinstance(v, (int, float)):
                out.append(float(v))
            else:
                out.extend(_collect_money_values(v, money_keys))
    elif isinstance(value, list):
        for v in value:
            out.extend(_collect_money_values(v, money_keys))
    return out
