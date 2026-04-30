import subprocess
from pathlib import Path


def test_debug_flag_writes_log(tmp_path):
    phase = tmp_path / "phase"
    phase.mkdir()
    (phase / "CRUD-SURFACES.md").write_text("# resources: []\n")
    (phase / "runs").mkdir()
    result = subprocess.run(
        ["python", "scripts/spawn-crud-roundtrip.py",
         "--phase-dir", str(phase), "--debug", "--dry-run"],
        capture_output=True, text=True
    )
    debug_logs = list((phase / "runs").glob(".debug-*.log"))
    assert result.returncode == 0
    # Dry-run with no resources still emits debug log header
    assert "DEBUG MODE" in result.stdout or any(debug_logs)
