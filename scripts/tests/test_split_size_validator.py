import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
VAL = REPO / "scripts/validators/verify-blueprint-split-size.py"


def test_warns_when_flat_large_and_split_missing(tmp_path):
    pdir = tmp_path / "phase-9"
    pdir.mkdir()
    (pdir / "API-CONTRACTS.md").write_text("X" * 35_000)  # > 30 KB
    out = subprocess.run(
        ["python3", str(VAL), "--phase-dir", str(pdir)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0  # WARN, not BLOCK
    assert "WARN" in out.stderr
    assert "split files missing" in out.stderr


def test_silent_when_split_present(tmp_path):
    pdir = tmp_path / "phase-10"
    pdir.mkdir()
    (pdir / "API-CONTRACTS.md").write_text("X" * 35_000)
    sub = pdir / "API-CONTRACTS"
    sub.mkdir()
    (sub / "index.md").write_text("ok\n")
    (sub / "ep1.md").write_text("ep1\n")
    out = subprocess.run(
        ["python3", str(VAL), "--phase-dir", str(pdir)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert "WARN" not in out.stderr


def test_silent_when_flat_under_threshold(tmp_path):
    pdir = tmp_path / "phase-11"
    pdir.mkdir()
    (pdir / "API-CONTRACTS.md").write_text("X" * 5_000)  # < 30 KB
    out = subprocess.run(
        ["python3", str(VAL), "--phase-dir", str(pdir)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert "WARN" not in out.stderr
