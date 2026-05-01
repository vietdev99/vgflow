"""Tests for scripts/runtime/recipe_safety.py — RFC v9 D9 sandbox safety gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.recipe_safety import (  # noqa: E402
    assert_step_safe,
    is_sentinel_value,
    SandboxSafetyError,
)


def test_sentinel_email_recognized():
    assert is_sentinel_value("alice@fixture.vgflow.test")
    assert is_sentinel_value("VG_FIXTURE_TENANT_ID")
    assert not is_sentinel_value("alice@example.com")


def test_sentinel_amount_under_threshold():
    assert is_sentinel_value(0.01)
    assert is_sentinel_value(0)
    assert not is_sentinel_value(1.0)
    assert not is_sentinel_value(1000)


def test_risky_side_effect_blocked_outside_sandbox():
    step = {
        "id": "send_email",
        "side_effect_risk": "external_call",
        "method": "POST",
        "endpoint": "/api/send",
    }
    with pytest.raises(SandboxSafetyError, match="env='main'"):
        assert_step_safe(step, env="main")


def test_risky_side_effect_allowed_in_sandbox():
    step = {
        "id": "send_email",
        "side_effect_risk": "external_call",
        "method": "POST",
        "endpoint": "/api/send",
        "body": {"to": "user@fixture.vgflow.test"},
    }
    # Should not raise
    assert_step_safe(step, env="sandbox")


def test_money_value_in_sandbox_with_sentinel_passes():
    step = {
        "id": "topup",
        "method": "POST",
        "endpoint": "/api/topup",
        "body": {"amount": 1000, "merchant": "VG_FIXTURE_M1"},
    }
    assert_step_safe(step, env="sandbox")  # sentinel marker present


def test_money_value_in_sandbox_without_sentinel_fails():
    step = {
        "id": "topup",
        "method": "POST",
        "endpoint": "/api/topup",
        "body": {"amount": 1000, "merchant": "real-merchant-xyz"},
    }
    with pytest.raises(SandboxSafetyError, match="sentinel marker"):
        assert_step_safe(step, env="sandbox")


def test_money_value_under_threshold_passes_without_sentinel():
    step = {
        "id": "topup",
        "method": "POST",
        "endpoint": "/api/topup",
        "body": {"amount": 0.01, "merchant": "any"},
    }
    assert_step_safe(step, env="sandbox")


def test_no_money_field_passes():
    step = {
        "id": "fetch",
        "method": "GET",
        "endpoint": "/api/me",
    }
    assert_step_safe(step, env="sandbox")
    assert_step_safe(step, env="main")


def test_volume_change_blocked_outside_sandbox():
    step = {
        "id": "bulk",
        "side_effect_risk": "volume_change",
        "method": "DELETE",
        "endpoint": "/api/users",
    }
    with pytest.raises(SandboxSafetyError, match="volume_change"):
        assert_step_safe(step, env="staging")


def test_money_like_blocked_outside_sandbox():
    step = {
        "id": "withdraw",
        "side_effect_risk": "money_like",
        "method": "POST",
        "endpoint": "/api/withdraw",
    }
    with pytest.raises(SandboxSafetyError, match="money_like"):
        assert_step_safe(step, env="prod")


def test_email_sentinel_in_nested_body_passes():
    step = {
        "id": "create_user",
        "method": "POST",
        "endpoint": "/api/users",
        "body": {
            "user": {
                "email": "tester@fixture.vgflow.test",
                "balance": 100,  # money-like
            },
        },
    }
    assert_step_safe(step, env="sandbox")


def test_custom_money_keys_respected():
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {"limit": 1000, "name": "real-name"},
    }
    # `limit` is the money key; no sentinel → fail
    with pytest.raises(SandboxSafetyError):
        assert_step_safe(step, env="sandbox", money_keys=("limit",))


# ─── Codex-HIGH-7: identity-field sentinel requirement ─────────────


def test_sentinel_anywhere_alone_now_fails_default():
    """RFC v9 D9 v2: sentinel must be on identity-bearing field, not just
    anywhere. This was the Codex-HIGH-7 finding — `note: 'VG_FIXTURE_X1'`
    used to satisfy the gate without proving the mutation targeted a
    fixture row."""
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "topup",
        "method": "POST",
        "endpoint": "/api/topup",
        "body": {
            "amount": 1000,
            "merchant_id": "real-merchant-xyz",  # NOT sentinel
            "note": "VG_FIXTURE_FROM_SOMEWHERE",  # sentinel on FREE-TEXT field
        },
    }
    # Default require_identity_sentinel=True → fail (sentinel not on identity)
    with pytest.raises(SandboxSafetyError, match="identity-bearing field"):
        assert_step_safe(step, env="sandbox")


def test_sentinel_on_identity_field_passes():
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "topup",
        "method": "POST",
        "endpoint": "/api/topup",
        "body": {"amount": 1000, "merchant_id": "VG_FIXTURE_M1"},
    }
    assert_step_safe(step, env="sandbox")  # sentinel on merchant_id


def test_sentinel_email_on_email_field_passes():
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {
            "amount": 1000,
            "email": "alice@fixture.vgflow.test",
        },
    }
    assert_step_safe(step, env="sandbox")


def test_legacy_anywhere_mode_opt_in():
    """Caller can opt back into D9 v1 'sentinel anywhere' for migration."""
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {"amount": 1000, "note": "VG_FIXTURE_NOTE"},
    }
    # require_identity_sentinel=False reverts to legacy "anywhere works"
    assert_step_safe(step, env="sandbox", require_identity_sentinel=False)


def test_custom_identity_fields_respected():
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {"amount": 1000, "vendor_ref": "VG_FIXTURE_V1"},
    }
    assert_step_safe(
        step, env="sandbox",
        identity_fields=("vendor_ref",),
    )


# ─── Codex-HIGH-7: URL allowlist ─────────────────────────────────────


def test_url_allowlist_exact_host_passes():
    from runtime.recipe_safety import assert_url_in_allowlist
    assert_url_in_allowlist(
        "https://sandbox.example.com/api",
        allowlist=["sandbox.example.com"],
    )


def test_url_allowlist_wildcard_subdomain_passes():
    from runtime.recipe_safety import assert_url_in_allowlist
    assert_url_in_allowlist(
        "https://eu.sandbox.example.com/api",
        allowlist=["*.sandbox.example.com"],
    )


def test_url_allowlist_unknown_host_fails():
    from runtime.recipe_safety import assert_url_in_allowlist
    with pytest.raises(SandboxSafetyError, match="NOT in sandbox_url_allowlist"):
        assert_url_in_allowlist(
            "https://prod.example.com/api",
            allowlist=["sandbox.example.com", "*.staging.example.com"],
        )


def test_url_allowlist_empty_disables_check():
    from runtime.recipe_safety import assert_url_in_allowlist
    # Empty/None disables — legacy projects without allowlist config
    assert_url_in_allowlist("https://anything.com", allowlist=[])
    assert_url_in_allowlist("https://anything.com", allowlist=None)


def test_url_allowlist_no_host_fails():
    from runtime.recipe_safety import assert_url_in_allowlist
    with pytest.raises(SandboxSafetyError, match="no parseable host"):
        assert_url_in_allowlist("not-a-url", allowlist=["sandbox.x.com"])


# ─── Codex-HIGH-7: response echo handshake ──────────────────────────


def test_response_echo_passes_when_header_present():
    from runtime.recipe_safety import assert_response_echo
    headers = {"X-VGFlow-Sandbox-Echo": "true"}
    assert_response_echo(headers)


def test_response_echo_fails_when_header_missing():
    from runtime.recipe_safety import (
        SandboxEchoMissingError, assert_response_echo,
    )
    with pytest.raises(SandboxEchoMissingError, match="missing"):
        assert_response_echo({"X-Other": "value"})


def test_response_echo_fails_when_value_wrong():
    from runtime.recipe_safety import (
        SandboxEchoMissingError, assert_response_echo,
    )
    with pytest.raises(SandboxEchoMissingError, match="rejected"):
        assert_response_echo({"X-VGFlow-Sandbox-Echo": "false"})


def test_response_echo_case_insensitive():
    from runtime.recipe_safety import assert_response_echo
    # requests.CaseInsensitiveDict-style lookup → both casings work
    assert_response_echo({"x-vgflow-sandbox-echo": "TRUE"})


def test_response_echo_custom_header_name():
    from runtime.recipe_safety import assert_response_echo
    assert_response_echo(
        {"X-Custom-Echo": "yes"},
        expected_header="X-Custom-Echo",
        expected_value="yes",
    )


# ─── Codex-HIGH-7-bis: numeric sentinel hole regression ──────────────


def test_numeric_zero_account_id_no_longer_passes_as_identity_sentinel():
    """Codex review caught: {account_id: 0, amount: 1000} used to pass
    because 0 ≤ DEFAULT_MAX_MONEY_AMOUNT made it a 'sentinel'.
    Now identity sentinel requires string pattern only."""
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {"amount": 1000, "account_id": 0},  # 0 not a sentinel anymore
    }
    with pytest.raises(SandboxSafetyError, match="identity-bearing field"):
        assert_step_safe(step, env="sandbox")


def test_is_sentinel_value_identity_mode_rejects_numeric():
    from runtime.recipe_safety import is_sentinel_value
    # Identity sentinel: string-only
    assert is_sentinel_value("VG_FIXTURE_M1", identity=True)
    assert is_sentinel_value("alice@fixture.vgflow.test", identity=True)
    assert not is_sentinel_value(0, identity=True)
    assert not is_sentinel_value(0.01, identity=True)
    assert not is_sentinel_value("real-merchant-x", identity=True)


def test_is_sentinel_value_money_mode_keeps_numeric():
    """Legacy money-amount detection: under-threshold int passes."""
    from runtime.recipe_safety import is_sentinel_value
    assert is_sentinel_value(0.01)
    assert is_sentinel_value(0)
    assert not is_sentinel_value(1000)


def test_numeric_sentinel_in_non_identity_field_does_not_auto_satisfy():
    """Even with sentinel string in a non-identity field, the gate fails
    because identity-fields walk needs identity field to carry sentinel."""
    from runtime.recipe_safety import assert_step_safe
    step = {
        "id": "x",
        "method": "POST",
        "endpoint": "/api/x",
        "body": {
            "amount": 1000,
            "merchant_id": 42,  # numeric — NOT sentinel
            "note": "VG_FIXTURE_NOTE",  # string sentinel but in note, not identity
        },
    }
    with pytest.raises(SandboxSafetyError):
        assert_step_safe(step, env="sandbox")
