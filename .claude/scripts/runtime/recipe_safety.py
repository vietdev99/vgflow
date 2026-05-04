"""Sandbox safety gate (RFC v9 D9 + Codex-HIGH-7 hardening).

Hard rules when env=sandbox:
1. Send `X-VGFlow-Sandbox: true` header (handled by recipe_auth).
2. base_url MUST match a sandbox URL allowlist (Codex-HIGH-7).
3. Money-like values > threshold MUST carry sentinel ON identity-bearing
   fields (merchant_id, user_id, account_id, …) — not just anywhere in
   body (Codex-HIGH-7: closes "anywhere passes" gap).
4. Risky `side_effect_risk` ∈ {money_like, external_call, volume_change}
   → reject when env != sandbox.

Recommended (not enforced by default — opt-in via response_check):
5. Backend echo handshake — first response in sandbox must carry
   `X-VGFlow-Sandbox-Echo: true` header. Confirms backend honored the
   sandbox flag rather than silently routing to prod.

Failure mode this closes: project's fixture goes ROGUE because backend
doesn't filter by header — money or external API hits prod. Sentinels
on identity fields make a breach detectable AND prevent it: a sentinel
on the merchant_id field forces the request to target a fixture row,
not just have a sentinel buried in a free-text field.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


class SandboxSafetyError(Exception):
    """Sandbox safety gate refused to execute step."""


class SandboxEchoMissingError(SandboxSafetyError):
    """Backend response did not echo X-VGFlow-Sandbox-Echo header."""


SENTINEL_EMAIL_RE = re.compile(r"@fixture\.vgflow\.test\b", re.IGNORECASE)
SENTINEL_PREFIX_RE = re.compile(r"\bVG_FIXTURE_[A-Z0-9_]+\b")
DEFAULT_MAX_MONEY_AMOUNT = 0.01

RISKY_SIDE_EFFECTS = {"money_like", "external_call", "volume_change"}

# Identity-bearing fields that carry "this row matters" semantics. A
# sentinel here proves the mutation targets a fixture row; sentinel
# anywhere else (e.g., free-text note field) does NOT.
DEFAULT_IDENTITY_FIELDS = (
    "merchant_id", "merchant", "user_id", "user", "account_id",
    "account", "customer_id", "customer", "tenant_id", "tenant",
    "owner_id", "owner", "target_id", "target", "recipient_id",
    "recipient", "source_id", "source", "wallet_id", "wallet",
    "subject_id", "subject", "id", "uid",
    "email",  # email field with sentinel domain proves identity
)


def is_sentinel_value(value: Any, *, identity: bool = False) -> bool:
    """True if value carries an obvious VG fixture sentinel.

    Codex-HIGH-7-bis fix: identity=True restricts to string patterns only
    (VG_FIXTURE_*, @fixture.vgflow.test). Without this, an `account_id: 0`
    field passes the gate because 0 ≤ DEFAULT_MAX_MONEY_AMOUNT, which is
    a false positive — numeric values cannot prove the row is disposable
    without a fixture-ID registry.

    identity=False (legacy/money path) keeps the under-threshold-numeric
    rule for amount fields, where ≤0.01 IS meaningful.
    """
    if isinstance(value, str):
        return bool(SENTINEL_EMAIL_RE.search(value)) \
            or bool(SENTINEL_PREFIX_RE.search(value))
    if identity:
        # Identity sentinel must be a string pattern. Numeric IDs (e.g.,
        # account_id: 0) do NOT qualify — they prove nothing about fixture-ness.
        return False
    if isinstance(value, bool):
        return False  # bool subclasses int — reject early
    if isinstance(value, (int, float)):
        try:
            return float(value) <= DEFAULT_MAX_MONEY_AMOUNT
        except (TypeError, ValueError):
            return False
    return False


def assert_url_in_allowlist(
    base_url: str,
    allowlist: list[str] | tuple[str, ...] | None,
) -> None:
    """Raise if `base_url` host isn't in `allowlist`.

    `allowlist` entries match by exact host OR by '*.' wildcard suffix
    (e.g., '*.sandbox.example.com' matches 'foo.sandbox.example.com').
    None or empty list disables the check (legacy behavior).
    """
    if not allowlist:
        return
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise SandboxSafetyError(
            f"base_url '{base_url}' has no parseable host — sandbox "
            f"allowlist cannot be enforced. Use scheme://host[:port]/path."
        )
    for entry in allowlist:
        entry = entry.lower().strip()
        if not entry:
            continue
        if entry == host:
            return
        if entry.startswith("*.") and (
            host == entry[2:] or host.endswith("." + entry[2:])
        ):
            return
    raise SandboxSafetyError(
        f"base_url host '{host}' NOT in sandbox_url_allowlist={list(allowlist)}. "
        f"Refusing to send sandbox traffic to a non-sandbox URL (RFC v9 D9 / "
        f"Codex-HIGH-7). Add the host to vg.config.md sandbox_url_allowlist "
        f"if intentional."
    )


def _has_sentinel_on_identity_field(
    body: Any,
    identity_fields: tuple[str, ...],
) -> tuple[bool, list[str]]:
    """Walk `body` checking if any identity-bearing field carries a sentinel.

    Returns (found, identity_fields_inspected). identity_fields_inspected
    is the list of identity field NAMES seen in the body (for error msgs).
    """
    seen_fields: list[str] = []

    def walk(value: Any, parent_key: str | None = None) -> bool:
        if isinstance(value, dict):
            for k, v in value.items():
                if k in identity_fields:
                    seen_fields.append(k)
                    # Codex-HIGH-7-bis: identity=True forbids numeric "sentinels"
                    if is_sentinel_value(v, identity=True):
                        return True
                if walk(v, k):
                    return True
        elif isinstance(value, list):
            for v in value:
                if walk(v, parent_key):
                    return True
        return False

    found = walk(body)
    return found, seen_fields


def assert_step_safe(
    step: dict,
    env: str,
    *,
    money_keys: tuple[str, ...] = ("amount", "total", "value", "price"),
    max_money: float = DEFAULT_MAX_MONEY_AMOUNT,
    identity_fields: tuple[str, ...] = DEFAULT_IDENTITY_FIELDS,
    require_identity_sentinel: bool = True,
) -> None:
    """Raise if step would be unsafe in this env.

    Rules:
    - side_effect_risk ∈ RISKY_SIDE_EFFECTS → only sandbox allowed.
    - In sandbox: money fields > max_money MUST have a sentinel on at least
      one identity-bearing field (require_identity_sentinel=True default).
      Older callers can opt out with require_identity_sentinel=False, which
      reverts to "any sentinel anywhere in body" (D9 v1).
    - Outside sandbox: side_effect_risk='none' or absent are accepted.
    """
    risk = step.get("side_effect_risk", "none")
    if risk in RISKY_SIDE_EFFECTS and env != "sandbox":
        raise SandboxSafetyError(
            f"step '{step.get('id', '?')}' has side_effect_risk='{risk}' but "
            f"env='{env}' — risky steps require env=sandbox (D9). Switch env "
            f"or set side_effect_risk=none if step is safely read-only."
        )

    if env != "sandbox":
        return

    body = step.get("body") or {}
    if not isinstance(body, dict):
        return  # nothing to check

    body_amounts = _collect_money_values(body, money_keys)
    suspicious = [v for v in body_amounts if v > max_money]
    if not suspicious:
        return

    if require_identity_sentinel:
        found, seen_fields = _has_sentinel_on_identity_field(body, identity_fields)
        if not found:
            raise SandboxSafetyError(
                f"step '{step.get('id', '?')}' body has money-like "
                f"value(s) {suspicious} > {max_money} in sandbox but no "
                f"sentinel marker on any identity-bearing field. "
                f"Identity fields seen in body: {seen_fields or '[none]'}. "
                f"Required: at least one of {list(identity_fields)} must "
                f"carry @fixture.vgflow.test or VG_FIXTURE_* (Codex-HIGH-7). "
                f"D9 demands the mutation provably target a fixture row."
            )
        return

    # Legacy behavior: any sentinel anywhere in body
    body_text = _stringify_leaves(body)
    has_sentinel = (
        SENTINEL_EMAIL_RE.search(body_text)
        or SENTINEL_PREFIX_RE.search(body_text)
    )
    if not has_sentinel:
        raise SandboxSafetyError(
            f"step '{step.get('id', '?')}' body has money-like "
            f"value(s) {suspicious} > {max_money} in sandbox but no "
            f"sentinel marker (VG_FIXTURE_* or @fixture.vgflow.test) "
            f"anywhere in body. D9 demands traceable test data."
        )


def assert_response_echo(
    headers: Any,
    *,
    expected_header: str = "X-VGFlow-Sandbox-Echo",
    expected_value: str = "true",
) -> None:
    """Raise if backend response didn't carry the sandbox-echo header.

    Opt-in (callers explicitly invoke). When backend supports the echo
    handshake, this proves it honored X-VGFlow-Sandbox: true. Without
    backend support, callers should NOT call this — fall back to URL
    allowlist + identity sentinel.
    """
    # requests.structures.CaseInsensitiveDict + plain dict both expose .get
    if not hasattr(headers, "get"):
        raise SandboxEchoMissingError(
            f"headers object lacks .get() — cannot verify {expected_header}"
        )
    actual = headers.get(expected_header) or headers.get(expected_header.lower())
    if not actual:
        raise SandboxEchoMissingError(
            f"backend response missing {expected_header} header. "
            f"Sandbox mode may not have been honored. Either configure "
            f"backend to echo, or disable response_check in vg.config.md."
        )
    if str(actual).lower() != str(expected_value).lower():
        raise SandboxEchoMissingError(
            f"{expected_header}='{actual}' != expected '{expected_value}' — "
            f"backend rejected sandbox mode."
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
            if k in money_keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
            else:
                out.extend(_collect_money_values(v, money_keys))
    elif isinstance(value, list):
        for v in value:
            out.extend(_collect_money_values(v, money_keys))
    return out
