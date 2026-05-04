"""Task 39 — RCRURDR 7-phase lifecycle schema + parser."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts/lib"


def test_legacy_single_cycle_still_parses(tmp_path: Path) -> None:
    """lifecycle: rcrurd (default) — backward compat."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: PATCH
            endpoint: "/api/users/U"
          read:
            method: GET
            endpoint: "/api/users/U"
            cache_policy: no_store
            settle:
              mode: immediate
          assert:
            - path: $.email
              op: equals
              value_from: action.email
    """).strip()
    inv = parse_yaml(doc)
    # Default lifecycle is "rcrurd" (single cycle)
    assert inv.lifecycle == "rcrurd"
    assert inv.lifecycle_phases == ()
    sys.path.remove(str(LIB))


def test_rcrurdr_lifecycle_with_7_phases(tmp_path: Path) -> None:
    """lifecycle: rcrurdr requires lifecycle_phases[] with 7 entries."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users
                op: equals
                value_from: "literal:[]"
          - phase: create
            write:
              method: POST
              endpoint: "/api/users"
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users[0].id
                op: matches
                value_from: "literal:^[a-f0-9-]{36}$"
          - phase: read_populated
            read:
              method: GET
              endpoint: "/api/users/{created_id}"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.id
                op: equals
                value_from: action.created_id
          - phase: update
            write:
              method: PATCH
              endpoint: "/api/users/{created_id}"
            read:
              method: GET
              endpoint: "/api/users/{created_id}"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.email
                op: equals
                value_from: action.new_email
          - phase: read_updated
            read:
              method: GET
              endpoint: "/api/users/{created_id}"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.email
                op: equals
                value_from: action.new_email
          - phase: delete
            write:
              method: DELETE
              endpoint: "/api/users/{created_id}"
            read:
              method: GET
              endpoint: "/api/users/{created_id}"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.error.code
                op: equals
                value_from: "literal:NOT_FOUND"
          - phase: read_after_delete
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users
                op: equals
                value_from: "literal:[]"
    """).strip()
    inv = parse_yaml(doc)
    assert inv.lifecycle == "rcrurdr"
    assert len(inv.lifecycle_phases) == 7
    phases = [p.phase for p in inv.lifecycle_phases]
    assert phases == [
        "read_empty", "create", "read_populated", "update",
        "read_updated", "delete", "read_after_delete",
    ]
    sys.path.remove(str(LIB))


def test_rcrurdr_missing_phases_rejected(tmp_path: Path) -> None:
    """RCRURDR with only 1 phase — rejected."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml, RCRURDInvariantError
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users
                op: equals
                value_from: "literal:[]"
    """).strip()
    with pytest.raises(RCRURDInvariantError, match="lifecycle.*rcrurdr.*requires.*7"):
        parse_yaml(doc)
    sys.path.remove(str(LIB))


def test_create_only_goal_type_partial_lifecycle(tmp_path: Path) -> None:
    """goal_type: create_only requires phases [read_empty, create, read_populated]."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: create_only
        lifecycle: partial
        lifecycle_phases:
          - phase: read_empty
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users
                op: equals
                value_from: "literal:[]"
          - phase: create
            write:
              method: POST
              endpoint: "/api/users"
            read:
              method: GET
              endpoint: "/api/users"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.users[0].id
                op: matches
                value_from: "literal:.+"
          - phase: read_populated
            read:
              method: GET
              endpoint: "/api/users/{created_id}"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.id
                op: equals
                value_from: action.created_id
    """).strip()
    inv = parse_yaml(doc)
    assert len(inv.lifecycle_phases) == 3
    sys.path.remove(str(LIB))


def test_ui_assert_apply_to_phase_keying(tmp_path: Path) -> None:
    """ui_assert ops must specify apply_to_phase when lifecycle: rcrurdr."""
    sys.path.insert(0, str(LIB))
    from rcrurd_invariant import parse_yaml
    doc = textwrap.dedent("""
        goal_type: mutation
        lifecycle: rcrurdr
        lifecycle_phases:
          - phase: read_empty
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: equals
                value_from: "literal:[]"
          - phase: create
            write:
              method: POST
              endpoint: "/api/x"
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: contains
                value_from: action.new
          - phase: read_populated
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: contains
                value_from: action.new
          - phase: update
            write:
              method: PATCH
              endpoint: "/api/x"
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: contains
                value_from: action.new
          - phase: read_updated
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: contains
                value_from: action.new
          - phase: delete
            write:
              method: DELETE
              endpoint: "/api/x"
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: equals
                value_from: "literal:[]"
          - phase: read_after_delete
            read:
              method: GET
              endpoint: "/api/x"
              cache_policy: no_store
              settle:
                mode: immediate
            assert:
              - path: $.x
                op: equals
                value_from: "literal:[]"
        ui_assert:
          apply_to_phase: read_populated
          settle:
            timeout_ms: 3000
          ops:
            - op: text_equals_response_value
              dom_selector: '[data-testid="x-display"]'
              response_path: $.x[0]
    """).strip()
    inv = parse_yaml(doc)
    assert inv.ui_assert.apply_to_phase == "read_populated"
    sys.path.remove(str(LIB))


def test_blueprint_md_registers_2b8_rcrurdr_step() -> None:
    text = (REPO / "commands/vg/blueprint.md").read_text(encoding="utf-8")
    assert "2b8_rcrurdr_invariants" in text, \
        "blueprint.md must register 2b8_rcrurdr_invariants step (Task 39 / Bug G)"
    assert "blueprint.rcrurdr_invariant_emitted" in text, \
        "blueprint.md must declare blueprint.rcrurdr_invariant_emitted telemetry event"
