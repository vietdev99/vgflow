"""Tests for scripts/runtime/recipe_capture.py — RFC v9 PR-A1 JSONPath capture."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.recipe_capture import capture_paths, CaptureError  # noqa: E402


PAYLOAD = {
    "data": {
        "id": "pending-7e9",
        "items": [
            {"id": "i1", "name": "alpha"},
            {"id": "i2", "name": "beta"},
            {"id": "i3", "name": "gamma"},
        ],
    },
    "meta": {"count": 3},
    "token": "tok-xyz",
}


def test_scalar_capture_returns_value():
    out = capture_paths(PAYLOAD, {"pending_id": {"path": "$.data.id"}})
    assert out == {"pending_id": "pending-7e9"}


def test_scalar_capture_missing_default_fails():
    with pytest.raises(CaptureError, match="returned no matches"):
        capture_paths(PAYLOAD, {"absent": {"path": "$.does.not.exist"}})


def test_scalar_capture_on_empty_skip():
    out = capture_paths(PAYLOAD, {
        "absent": {"path": "$.does.not.exist", "on_empty": "skip"}
    })
    assert out == {}


def test_scalar_capture_on_empty_null():
    out = capture_paths(PAYLOAD, {
        "absent": {"path": "$.does.not.exist", "on_empty": "null"}
    })
    assert out == {"absent": None}


def test_array_capture_returns_list():
    out = capture_paths(PAYLOAD, {
        "ids": {"path": "$.data.items[*].id", "cardinality": "array"}
    })
    assert out == {"ids": ["i1", "i2", "i3"]}


def test_array_capture_empty_with_skip():
    out = capture_paths(PAYLOAD, {
        "absent": {
            "path": "$.does.not.exist",
            "cardinality": "array",
            "on_empty": "skip",
        }
    })
    assert out == {}


def test_optional_scalar_present():
    out = capture_paths(PAYLOAD, {
        "tok": {"path": "$.token", "cardinality": "optional_scalar"}
    })
    assert out == {"tok": "tok-xyz"}


def test_optional_scalar_missing_with_null():
    out = capture_paths(PAYLOAD, {
        "tok": {
            "path": "$.no_token",
            "cardinality": "optional_scalar",
            "on_empty": "null",
        }
    })
    assert out == {"tok": None}


def test_scalar_with_multiple_matches_raises():
    with pytest.raises(CaptureError, match="expected scalar"):
        capture_paths(PAYLOAD, {
            "all_ids": {"path": "$.data.items[*].id"}  # 3 matches
        })


def test_optional_scalar_with_multiple_matches_raises():
    with pytest.raises(CaptureError, match="expected optional_scalar"):
        capture_paths(PAYLOAD, {
            "all_ids": {
                "path": "$.data.items[*].id",
                "cardinality": "optional_scalar",
            }
        })


def test_indexed_capture_picks_specific():
    out = capture_paths(PAYLOAD, {
        "first_id": {"path": "$.data.items[0].id"}
    })
    assert out == {"first_id": "i1"}


def test_unknown_cardinality_raises():
    with pytest.raises(CaptureError, match="unknown cardinality"):
        capture_paths(PAYLOAD, {
            "x": {"path": "$.token", "cardinality": "weird"}
        })


def test_unknown_on_empty_raises():
    with pytest.raises(CaptureError, match="unknown on_empty"):
        capture_paths(PAYLOAD, {
            "x": {"path": "$.no_path", "on_empty": "noisily"}
        })


def test_missing_path_raises():
    with pytest.raises(CaptureError, match="missing required 'path'"):
        capture_paths(PAYLOAD, {"x": {}})


def test_multi_capture_independence():
    """Failure of one capture must not contaminate others."""
    spec = {
        "id": {"path": "$.data.id"},
        "missing": {"path": "$.no", "on_empty": "skip"},
        "count": {"path": "$.meta.count"},
    }
    out = capture_paths(PAYLOAD, spec)
    assert out == {"id": "pending-7e9", "count": 3}
