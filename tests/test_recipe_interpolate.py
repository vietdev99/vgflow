"""Tests for scripts/runtime/recipe_interpolate.py — RFC v9 PR-A1 ${var} interpolation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.recipe_interpolate import interpolate, InterpolationError  # noqa: E402


STORE = {
    "pending_id": "pending-7e9",
    "amount": 100,
    "is_active": True,
    "tags": ["alpha", "beta"],
    "created": {"user": {"id": "user-42"}},
}


def test_whole_string_match_preserves_type():
    assert interpolate("${amount}", STORE) == 100
    assert interpolate("${is_active}", STORE) is True
    assert interpolate("${tags}", STORE) == ["alpha", "beta"]


def test_substring_match_stringifies():
    assert interpolate("ID: ${pending_id}", STORE) == "ID: pending-7e9"
    assert interpolate("amount=${amount}", STORE) == "amount=100"


def test_dotted_path_resolves():
    assert interpolate("${created.user.id}", STORE) == "user-42"


def test_missing_top_level_variable_raises():
    with pytest.raises(InterpolationError, match="absent"):
        interpolate("${absent}", STORE)


def test_missing_dotted_segment_raises():
    with pytest.raises(InterpolationError, match="missing"):
        interpolate("${created.user.absent}", STORE)


def test_dotted_into_non_dict_raises():
    with pytest.raises(InterpolationError, match="non-dict"):
        interpolate("${pending_id.foo}", STORE)


def test_dict_recursive_interpolation():
    template = {
        "id": "${pending_id}",
        "amount": "${amount}",
        "label": "User ${created.user.id} pending",
    }
    out = interpolate(template, STORE)
    assert out == {
        "id": "pending-7e9",
        "amount": 100,
        "label": "User user-42 pending",
    }


def test_list_recursive_interpolation():
    template = ["${pending_id}", "${amount}", "static"]
    out = interpolate(template, STORE)
    assert out == ["pending-7e9", 100, "static"]


def test_non_string_scalars_passthrough():
    assert interpolate(42, STORE) == 42
    assert interpolate(None, STORE) is None
    assert interpolate(True, STORE) is True


def test_no_variables_returns_unchanged():
    assert interpolate("plain string", STORE) == "plain string"
    assert interpolate({"k": "v"}, STORE) == {"k": "v"}


def test_multiple_substitutions_in_one_string():
    assert interpolate(
        "${pending_id}/${amount}/${is_active}", STORE,
    ) == "pending-7e9/100/True"


def test_nested_dict_in_list():
    template = [{"id": "${pending_id}"}, {"id": "${created.user.id}"}]
    out = interpolate(template, STORE)
    assert out == [{"id": "pending-7e9"}, {"id": "user-42"}]
