"""Tests for ui_assert section in RCRURD invariant schema (Task 25)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "lib"


def test_ui_assert_array_ops_parse(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read:
            method: GET
            endpoint: /api/users/U
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - {path: $.roles, op: contains, value_from: action.new_role}
          ui_assert:
            settle: {timeout_ms: 5000, poll_ms: 100}
            ops:
              - op: count_matches_response_array
                dom_selector: '[data-testid="roles-list"] [data-role]'
                response_path: $.roles[*]
              - op: text_contains_all
                dom_selector: '[data-testid="roles-list"]'
                response_path: $.roles[*].name
              - op: each_exists_for_array_item
                response_path: $.roles[*]
                selector_template: '[data-testid="role-{key}"]'
                key_from: $.id
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert is not None
    assert inv.ui_assert.settle.timeout_ms == 5000
    assert len(inv.ui_assert.ops) == 3
    assert inv.ui_assert.ops[0].op == "count_matches_response_array"
    assert inv.ui_assert.ops[2].selector_template == '[data-testid="role-{key}"]'
    assert inv.ui_assert.ops[2].key_from == "$.id"
    sys.path.remove(str(LIB))


def test_ui_assert_scalar_conditional_attribute_ops_parse(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/users/U}
          read: {method: GET, endpoint: /api/users/U, cache_policy: no_store, settle: {mode: immediate}}
          assert:
            - {path: $.email, op: equals, value_from: action.email}
          ui_assert:
            settle: {timeout_ms: 3000, poll_ms: 100}
            ops:
              - op: text_equals_response_value
                dom_selector: '[data-testid="user-email"]'
                response_path: $.email
              - op: text_matches_response_value
                dom_selector: '[data-testid="user-updated-at"]'
                response_path: $.updated_at
                regex: '^\\d{4}-\\d{2}-\\d{2}'
              - op: visible_when_response_value
                dom_selector: '[data-testid="banner-verified"]'
                response_path: $.verified
                expected_value: true
              - op: hidden_when_response_value
                dom_selector: '[data-testid="banner-pending"]'
                response_path: $.verified
                expected_value: true
              - op: attribute_equals_response_value
                dom_selector: '[data-testid="role-toggle"]'
                attribute: aria-checked
                response_path: $.has_admin_role
              - op: aria_state_matches
                dom_selector: '[data-testid="user-row"]'
                aria_state: aria-selected
                response_path: $.selected
              - op: input_value_equals_response
                dom_selector: '[data-testid="username-input"]'
                response_path: $.username
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.ui_assert.ops) == 7
    assert inv.ui_assert.ops[1].regex == r'^\d{4}-\d{2}-\d{2}'
    assert inv.ui_assert.ops[2].expected_value is True
    assert inv.ui_assert.ops[4].attribute == "aria-checked"
    assert inv.ui_assert.ops[5].aria_state == "aria-selected"
    sys.path.remove(str(LIB))


def test_each_exists_requires_key_from(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.x, op: equals, value_from: action.x}]
          ui_assert:
            settle: {timeout_ms: 1000}
            ops:
              - op: each_exists_for_array_item
                response_path: $.items[*]
                selector_template: '[data-testid="item-{key}"]'
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="key_from"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_invalid_op_in_ui_assert_rejected(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.x, op: equals, value_from: action.x}]
          ui_assert:
            settle: {timeout_ms: 1000}
            ops:
              - op: cosmic_ray_detector
                dom_selector: '[data-testid="x"]'
                response_path: $.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="cosmic_ray_detector"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_ui_assert_optional_when_no_render_concern(tmp_path: Path) -> None:
    """ui_assert is optional — APIs without UI surface (worker, cron) skip it."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: POST, endpoint: /api/internal/jobs}
          read: {method: GET, endpoint: /api/internal/jobs/last, cache_policy: no_store, settle: {mode: immediate}}
          assert: [{path: $.status, op: equals, value_from: literal:queued}]
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert is None
    sys.path.remove(str(LIB))
