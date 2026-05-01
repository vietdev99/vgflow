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
