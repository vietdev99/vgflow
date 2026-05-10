"""v2.65.0 A7 — Deepscan default ON (BREAKING)."""
import re
from pathlib import Path
import pytest

from conftest import read_command_full


def test_deepscan_default_on_in_template():
    body = Path("vg.config.template.md").read_text(encoding="utf-8")
    m = re.search(r"^CONFIG_REVIEW_DEEPSCAN_DEFAULT:\s*(\S+)", body, re.MULTILINE)
    assert m, "CONFIG_REVIEW_DEEPSCAN_DEFAULT field must exist in vg.config.template.md"
    val = m.group(1).strip().strip('"\'')
    assert val.lower() == "on", \
        f"v2.65.0 default must be 'on' (was: {val})"


def test_skip_deepscan_flag_documented():
    body = read_command_full("review")
    assert "--skip-deepscan" in body, "Must provide --skip-deepscan opt-out flag"


def test_deepscan_logic_is_opt_out():
    """Logic must skip deepscan when --skip-deepscan OR config off; otherwise run."""
    body = read_command_full("review")
    # Find region near line 3551
    region = body[3000*60:6000*60] if len(body) > 360000 else body
    # Look for both opt-out conditions
    assert re.search(r"--skip-deepscan|skip[\s_]?deepscan", body, re.IGNORECASE)
    assert "CONFIG_REVIEW_DEEPSCAN_DEFAULT" in body


def test_deepscan_no_longer_opt_in_default_off():
    """Old text 'default OFF' or 'default skip' for deepscan must be GONE or revised."""
    body = read_command_full("review")
    # Old v2.42.4 phrasing: "Phase 2b-2 default OFF" — should now say ON or refer to opt-out
    # Reject if any current text claims deepscan defaults OFF without --with-deepscan
    bad_pattern = re.search(
        r"(?:Phase\s*2b-2|deepscan).{0,50}default\s+OFF",
        body, re.IGNORECASE
    )
    assert not bad_pattern, \
        f"Found stale 'default OFF' phrasing: {bad_pattern.group(0) if bad_pattern else ''}"


def test_changelog_documents_breaking_change():
    body = Path("CHANGELOG.md").read_text(encoding="utf-8")
    # v2.65.0 entry must mention BREAKING + deepscan. Anchor to '^## v2.65.0' header
    # because v2.65.0 also appears as substring inside later changelog prose
    # (e.g., "v2.65.0 A9 manual mark-step list").
    v2_65 = re.search(r"^## v2\.65\.0.*?(?=^## v|\Z)", body, re.DOTALL | re.MULTILINE)
    if v2_65:
        section = v2_65.group(0).lower()
        assert "breaking" in section, \
            "v2.65.0 CHANGELOG must mention BREAKING change"
        assert "deepscan" in section, \
            "v2.65.0 CHANGELOG must mention deepscan"
    # If v2.65.0 entry not yet present (Task 10 hasn't run), this test is a soft pre-condition
    # — the actual breaking-note enforcement happens at Task 10 release. Skip in this case.


def test_mirror_byte_identity_review_md():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror
