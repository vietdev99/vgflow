"""tests/test_c11_url_runtime_status.py — C11 canonical URL status."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
EMITTER = REPO / "scripts" / "emit-url-runtime-status.py"
URL_MD = REPO / "commands" / "vg" / "_shared" / "review" / "url-and-error.md"


def test_emitter_exists():
    assert EMITTER.is_file(), "C11: scripts/emit-url-runtime-status.py must ship"


def test_emitter_writes_canonical_state(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(EMITTER), "--phase-dir", str(phase_dir),
         "--state", "skipped", "--reason", "--skip-runtime flag set"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    status_file = phase_dir / "url-runtime-status.json"
    assert status_file.is_file()
    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["state"] == "skipped"
    assert data["reason"]


def test_emitter_rejects_invalid_state(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(EMITTER), "--phase-dir", str(phase_dir),
         "--state", "BOGUS"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "invalid" in r.stderr.lower() or "choices" in r.stderr.lower()


def test_url_md_emits_canonical_status():
    body = URL_MD.read_text(encoding="utf-8")
    assert "emit-url-runtime-status.py" in body, (
        "C11: url-and-error.md must invoke emit-url-runtime-status.py at end "
        "of phase 2.8 to produce canonical url-runtime-status.json"
    )
    # Must emit state in {passed, drift, skipped, unexecuted, waived}
    for st in ("passed", "drift", "skipped", "unexecuted", "waived"):
        assert st in body, f"C11: url-and-error.md must reference state '{st}'"
