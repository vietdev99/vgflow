"""Verify vg-load works on 3 phase shapes: flat-only (legacy), split-only, both."""
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
VG_LOAD = REPO / "scripts/vg-load.sh"


def _make_phase(tmp: Path, *, flat=False, split=False):
    pdir = tmp / "phase-7"
    pdir.mkdir()
    if flat:
        (pdir / "API-CONTRACTS.md").write_text("# Flat API\n## POST /api/x\nfoo flat\n## GET /api/y\nbar flat\n")
    if split:
        sub = pdir / "API-CONTRACTS"
        sub.mkdir()
        (sub / "index.md").write_text("- post-api-x\n- get-api-y\n")
        (sub / "post-api-x.md").write_text("# POST /api/x\nfoo split\n")
        (sub / "get-api-y.md").write_text("# GET /api/y\nbar split\n")
    return pdir


def test_legacy_flat_only_phase_full_load(tmp_path):
    pdir = _make_phase(tmp_path, flat=True)
    out = subprocess.run(
        ["bash", str(VG_LOAD), "--phase", str(pdir), "--artifact", "contracts", "--full", "--quiet"],
        capture_output=True, text=True, check=True,
    )
    assert "Flat API" in out.stdout


def test_split_only_phase_endpoint_load(tmp_path):
    pdir = _make_phase(tmp_path, split=True)
    out = subprocess.run(
        ["bash", str(VG_LOAD), "--phase", str(pdir), "--artifact", "contracts", "--endpoint", "post-api-x", "--quiet"],
        capture_output=True, text=True, check=True,
    )
    assert "foo split" in out.stdout


def test_both_present_endpoint_filter_uses_split(tmp_path):
    pdir = _make_phase(tmp_path, flat=True, split=True)
    out = subprocess.run(
        ["bash", str(VG_LOAD), "--phase", str(pdir), "--artifact", "contracts", "--endpoint", "post-api-x", "--quiet"],
        capture_output=True, text=True, check=True,
    )
    # Endpoint filter must hit split file, not flat
    assert "foo split" in out.stdout
    assert "Flat API" not in out.stdout
