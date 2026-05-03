"""Tests for RCRURD invariant schema parser + serializer (Single Source of Truth)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "lib"


def test_minimal_invariant_parses(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariant  # type: ignore

    yaml_doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: PATCH
            endpoint: /api/users/{userId}/roles
          read:
            method: GET
            endpoint: /api/users/{userId}
            cache_policy: no_store
            settle:
              mode: immediate
          assert:
            - path: $.roles[*].name
              op: contains
              value_from: action.new_role
    """).strip()

    inv = parse_yaml(yaml_doc)
    assert isinstance(inv, RCRURDInvariant)
    assert inv.write.method == "PATCH"
    assert inv.write.endpoint == "/api/users/{userId}/roles"
    assert inv.read.cache_policy == "no_store"
    assert inv.read.settle.mode == "immediate"
    assert len(inv.assertions) == 1
    assert inv.assertions[0].path == "$.roles[*].name"
    assert inv.assertions[0].op == "contains"
    assert inv.assertions[0].value_from == "action.new_role"
    sys.path.remove(str(LIB))


def test_eventual_consistency_requires_explicit_timeout(tmp_path: Path) -> None:
    """Codex blind-spot: eventual consistency must declare settle.timeout_ms."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read:
            method: GET
            endpoint: /api/x
            cache_policy: no_store
            settle:
              mode: poll
          assert:
            - path: $.x
              op: equals
              value_from: action.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="timeout_ms"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_invalid_op_rejected(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError  # type: ignore

    bad = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read: {method: GET, endpoint: /api/x, cache_policy: no_store, settle: {mode: immediate}}
          assert:
            - path: $.x
              op: looks_like_maybe
              value_from: action.x
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="op"):
        parse_yaml(bad)
    sys.path.remove(str(LIB))


def test_side_effects_multi_assert_supported(tmp_path: Path) -> None:
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml  # type: ignore

    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: "/api/users/{id}/roles"}
          read:
            method: GET
            endpoint: "/api/users/{id}"
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - path: $.roles[*].name
              op: contains
              value_from: action.new_role
          side_effects:
            - layer: audit_log
              path: $.events[*].type
              op: contains
              value_from: literal:role_granted
            - layer: effective_permission
              path: $.can_access_admin
              op: equals
              value_from: literal:true
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.side_effects) == 2
    assert inv.side_effects[0].layer == "audit_log"
    assert inv.side_effects[1].layer == "effective_permission"
    sys.path.remove(str(LIB))


def test_round_trip_yaml_serialization(tmp_path: Path) -> None:
    """Parse → serialize → parse must produce identical structure."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, to_yaml  # type: ignore

    src = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write: {method: PATCH, endpoint: /api/x}
          read:
            method: GET
            endpoint: /api/x
            cache_policy: no_store
            settle: {mode: immediate}
          assert:
            - {path: $.x, op: equals, value_from: action.x}
    """).strip()
    inv1 = parse_yaml(src)
    out = to_yaml(inv1)
    inv2 = parse_yaml(out)
    assert inv1.write.method == inv2.write.method
    assert inv1.assertions[0].path == inv2.assertions[0].path
    sys.path.remove(str(LIB))
