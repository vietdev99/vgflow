from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-matrix-evidence-link.py"


def test_test_pending_status_does_not_require_runtime_sequence(tmp_path: Path) -> None:
    phase = tmp_path / ".vg" / "phases" / "06-fixture"
    phase.mkdir(parents=True)
    phase.joinpath("GOAL-COVERAGE-MATRIX.md").write_text(
        "\n".join(
            [
                "# Goal Coverage Matrix",
                "",
                "| Goal | Priority | Surface | Status | Evidence |",
                "|------|----------|---------|--------|----------|",
                "| G-01 | important | ui | TEST_PENDING | lifecycle proof not exercised |",
                "",
                "## Gate: 🧪 **TEST_PENDING**",
                "",
            ]
        ),
        encoding="utf-8",
    )
    phase.joinpath("RUNTIME-MAP.json").write_text(
        json.dumps({"goal_sequences": {}}, indent=2),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)

    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "6", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "PASS"
