"""v2.66.0 Task 5 (#152) — Prereq verifier strict default ON (BREAKING).

Tests verify the lenient/strict default flip and the --lenient-prereqs opt-out.
"""
import re
from pathlib import Path


def test_completeness_validation_strict_default():
    """v2.66.0 BREAKING: prereq fidelity default → BLOCK (was WARN since prior versions)."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Old: "default (~0.85) → WARN"
    # New: "default → BLOCK; lenient (--lenient-prereqs flag) → WARN"
    bad = re.search(r"default\s*\(~0\.85\)\s*→\s*WARN", body)
    assert not bad, f"Found stale default→WARN text: {bad.group(0) if bad else ''}"
    # Must mention strict-by-default
    assert re.search(
        r"strict.{0,40}default|default.{0,40}strict|default.{0,40}BLOCK|BREAKING",
        body,
        re.IGNORECASE,
    ), "completeness-validation.md must declare strict default"


def test_warn_count_blocks_in_strict():
    """Exit code 1 when WARN_COUNT > 0 in strict default mode."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # In strict, both WARN and BLOCK trigger exit 1
    assert (
        re.search(r"WARN_COUNT.*-gt\s+0", body)
        or re.search(r"VIOLATION_COUNT.*-gt\s+0", body)
        or re.search(r"strict.*exit\s+1", body, re.IGNORECASE)
    ), "Strict mode must exit 1 when warnings present"
    # Lenient branch must still gate on BLOCK_COUNT only
    assert re.search(r"LENIENT_PREREQS", body), \
        "Must reference LENIENT_PREREQS env var to support legacy lenient mode"


def test_lenient_opt_out_flag_documented():
    body = Path("commands/vg/scope.md").read_text(encoding="utf-8")
    assert "--lenient-prereqs" in body, "Must provide --lenient-prereqs opt-out flag"
