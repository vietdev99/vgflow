"""Tests for scripts/identify_interesting_clickables.py.

Verifies Tier 1 element class detection from a sample scan-*.json fixture.
"""
import subprocess
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "identify_interesting_clickables.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sample-scan.json"


def test_classifies_all_categories():
    """End-to-end: sample fixture must produce all 7 Tier-1 element classes."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--scan-files", str(FIXTURE), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = json.loads(r.stdout)
    assert "clickables" in out and "count" in out
    assert out["count"] == len(out["clickables"])
    classes = {c["element_class"] for c in out["clickables"]}
    expected = {
        "mutation_button",
        "form_trigger",
        "tab",
        "row_action",
        "bulk_action",
        "sub_view_link",
        "modal_trigger",
    }
    assert expected.issubset(classes), f"Missing: {expected - classes}"


def test_selector_hash_is_deterministic_8_hex():
    """Hash must be deterministic + exactly 8 lowercase hex chars (sha256[:8])."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--scan-files", str(FIXTURE), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = json.loads(r.stdout)
    for c in out["clickables"]:
        h = c["selector_hash"]
        assert len(h) == 8, f"hash not 8 chars: {h!r}"
        assert all(ch in "0123456789abcdef" for ch in h), f"non-hex hash: {h!r}"

    # Determinism: re-run, identical hashes for identical selectors.
    r2 = subprocess.run(
        [sys.executable, str(SCRIPT), "--scan-files", str(FIXTURE), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    out2 = json.loads(r2.stdout)
    pairs1 = sorted((c["selector"], c["selector_hash"]) for c in out["clickables"])
    pairs2 = sorted((c["selector"], c["selector_hash"]) for c in out2["clickables"])
    assert pairs1 == pairs2


def test_missing_file_returns_nonzero():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--scan-files", "tests/fixtures/_does_not_exist.json", "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode != 0
    assert "not found" in r.stderr.lower()


def test_output_flag_writes_file(tmp_path):
    """--output writes a JSON file with the same payload shape."""
    out_file = tmp_path / "recursive-classification.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--scan-files", str(FIXTURE), "--output", str(out_file)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert out_file.is_file()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert "clickables" in payload and "count" in payload
    assert payload["count"] >= 7  # at least one of each Tier-1 class
