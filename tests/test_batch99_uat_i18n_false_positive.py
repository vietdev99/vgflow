"""B99 v4.69.2 — issue #199 UAT VN i18n false-positive.

User report:
> "/vg:accept STEP 4b auto-narrative for <phase>. Validator
> verify-uat-strings-no-hardcode.py (D-18 strict mode). Reproduce: any
> phase with TEST-GOALS.md containing goals → /vg:accept <phase> →
> step 4b emits UAT-NARRATIVE.md → D-18 validator finds 30+ VN literal
> strings outside {{...}} interpolation → BLOCK exit 1.
> Examples: L12 'Truy' 'cập' 'vai' 'trò' 'tài' 'khoản', L14 'Điều'
> 'hướng', L16 'Tiền' 'điều' 'kiện', L18 'Hành' 'mong' 'đợi'"

## Root cause

Validator scans the RENDERED UAT-NARRATIVE.md (after {{uat_*}}
interpolation), not the template. After render, `{{uat_entry_label}}`
becomes literal "Truy cập" (VN value from narration-strings.yaml).
Pre-B99 backward scan caught those as hardcode violations even though
they came via legitimate interpolation.

## Fix

`_collect_narration_values(narration)` flattens all locale values
(vi+en+ja+ko+fr+de+es+zh) from narration-strings.yaml into a list.
`_strip_for_backward(text, narration_values=...)` subtracts those known
values from cleaned text BEFORE the natural-text regex scan. Anything
left = actual hardcoded literal (true violation).

Longer values processed first so "Tiền điều kiện" subtracted before
"điều kiện" — avoids partial-shadow gaps.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-uat-strings-no-hardcode.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-uat-strings-no-hardcode.py"


@pytest.fixture(scope="module")
def vd():
    # Load validator module with hyphen-safe spec
    spec = importlib.util.spec_from_file_location("uat_validator", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    # Validator imports _common from same dir; add to sys.path so it resolves
    sys.path.insert(0, str(VALIDATOR.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


# ---------------------------------------------------------------------------
# _collect_narration_values
# ---------------------------------------------------------------------------

def test_b99_collect_narration_values_flattens_locales(vd) -> None:
    narration = {
        "uat_entry_label": {"vi": "Truy cập", "en": "Open"},
        "uat_role_label": {"vi": "vai trò", "en": "role"},
    }
    vals = vd._collect_narration_values(narration)
    assert "Truy cập" in vals
    assert "Open" in vals
    assert "vai trò" in vals
    assert "role" in vals


def test_b99_collect_handles_empty(vd) -> None:
    assert vd._collect_narration_values({}) == []


def test_b99_collect_skips_non_dict_bodies(vd) -> None:
    narration = {
        "uat_entry_label": {"vi": "Truy cập"},
        "metadata_section": "this is not a dict-of-locales",
    }
    vals = vd._collect_narration_values(narration)
    assert "Truy cập" in vals
    assert "this is not a dict-of-locales" not in vals


# ---------------------------------------------------------------------------
# _strip_for_backward with narration_values subtraction
# ---------------------------------------------------------------------------

def test_b99_strip_subtracts_narration_values(vd) -> None:
    """Rendered VN labels should be removed before backward scan."""
    rendered = "Truy cập: http://localhost vai trò: admin"
    cleaned = vd._strip_for_backward(
        rendered,
        narration_values=["Truy cập", "vai trò"],
    )
    assert "Truy" not in cleaned
    assert "trò" not in cleaned
    # `admin` is data (DATA per validator) — backward scan may flag it but
    # we test that the INTERPOLATED VN gets subtracted regardless
    assert "Truy cập" not in cleaned


def test_b99_strip_handles_overlapping_substrings(vd) -> None:
    """'Tiền điều kiện dữ liệu' must be subtracted as a unit so internal
    'điều kiện' substring is gone too — not partially exposed."""
    rendered = "Tiền điều kiện dữ liệu: foo"
    cleaned = vd._strip_for_backward(
        rendered,
        narration_values=["Tiền điều kiện dữ liệu"],
    )
    # All VN tokens subtracted
    assert "Tiền" not in cleaned
    assert "điều" not in cleaned
    assert "kiện" not in cleaned


def test_b99_strip_long_value_first_avoids_partial_shadow(vd) -> None:
    """Even when both 'Tiền điều kiện dữ liệu' AND 'điều kiện' are in the
    narration list, the longer one is subtracted first so the shorter
    one doesn't leave a gap."""
    rendered = "Tiền điều kiện dữ liệu: foo"
    cleaned = vd._strip_for_backward(
        rendered,
        narration_values=["điều kiện", "Tiền điều kiện dữ liệu"],
    )
    assert "Tiền" not in cleaned


def test_b99_strip_preserves_hardcoded_literals_outside_narration(vd) -> None:
    """A literal NOT from narration-strings.yaml MUST remain in cleaned
    output — backward scan will catch it."""
    rendered = "Truy cập: http://localhost\n\nHardcoded notice here"
    cleaned = vd._strip_for_backward(
        rendered,
        narration_values=["Truy cập"],
    )
    # Legit narration stripped
    assert "Truy cập" not in cleaned
    # Hardcoded prose preserved
    assert "Hardcoded notice" in cleaned


def test_b99_strip_empty_narration_values_unchanged(vd) -> None:
    """Backward compat — passing empty list behaves like pre-B99."""
    rendered = "Some text\n\n```code```"
    cleaned_no_subtract = vd._strip_for_backward(rendered, narration_values=[])
    cleaned_pre_b99 = vd._strip_for_backward(rendered)
    # Both should produce identical output when no subtraction requested
    assert cleaned_no_subtract == cleaned_pre_b99


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b99_validator_mirror_parity() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()
