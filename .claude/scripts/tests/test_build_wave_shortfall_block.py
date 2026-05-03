"""R2 round-2 (E1 critical-2) — wave-complete shortfall hard-block test.

Asserts cmd_wave_complete refuses to emit `wave.completed` when
.spawn-count.json shows remaining[] non-empty. Closes the gap where
`waves-overview.md` HARD-GATE promised the Stop hook would catch
shortfalls but the Stop hook only delegated `--check-contract` and
never read .spawn-count.json.

The fix lives in scripts/vg-orchestrator/__main__.py (cmd_wave_complete)
and reads `.vg/runs/<run_id>/.spawn-count.json` written by
vg-agent-spawn-guard.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ORCH = REPO / "scripts" / "vg-orchestrator" / "__main__.py"


def _setup_run(tmp_path: Path, run_id: str, phase: str = "7.42") -> None:
    """Stage minimal files for vg-orchestrator wave-complete to find a run."""
    (tmp_path / ".vg").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg" / "current-run.json").write_text(
        json.dumps({
            "run_id": run_id,
            "command": "vg:build",
            "phase": phase,
            "args": "",
        })
    )
    (tmp_path / ".vg" / "runs" / run_id).mkdir(parents=True, exist_ok=True)


def _wave_complete(tmp_path: Path, wave_n: int, evidence: dict) -> tuple[int, str]:
    """Invoke `vg-orchestrator wave-complete <wave_n>` with evidence on stdin."""
    proc = subprocess.run(
        [sys.executable, str(ORCH), "wave-complete", str(wave_n)],
        input=json.dumps(evidence),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
        timeout=30,
    )
    return proc.returncode, proc.stderr


def test_wave_complete_blocks_when_remaining_nonempty(tmp_path):
    """spawn-count shows 1/3 spawned → wave-complete must BLOCK with rc=2."""
    run_id = "run-shortfall-1"
    _setup_run(tmp_path, run_id)
    spawn_count_path = tmp_path / ".vg" / "runs" / run_id / ".spawn-count.json"
    spawn_count_path.write_text(json.dumps({
        "wave_id": 2,
        "expected": ["task-01", "task-02", "task-03"],
        "spawned": ["task-01"],
        "remaining": ["task-02", "task-03"],
    }))
    evidence = {
        "wave": 2,
        "outcome": "passed",
        "retries": 0,
        "tasks": [{"task_num": 1}],
        "wave_tag": "vg-build-7.42-wave-2-start",
    }
    rc, stderr = _wave_complete(tmp_path, 2, evidence)
    assert rc == 2, f"expected hard-block (rc=2), got rc={rc}; stderr={stderr!r}"
    assert "shortfall" in stderr.lower() or "missing" in stderr.lower()
    assert "task-02" in stderr or "remaining" in stderr.lower()


def test_wave_complete_blocks_when_spawn_count_wave_id_mismatches(tmp_path):
    """Stale spawn-count from prior wave → wave-complete BLOCKs new wave."""
    run_id = "run-shortfall-2"
    _setup_run(tmp_path, run_id)
    spawn_count_path = tmp_path / ".vg" / "runs" / run_id / ".spawn-count.json"
    # Stale wave-1 count present, but operator calls wave-complete 2.
    spawn_count_path.write_text(json.dumps({
        "wave_id": 1,
        "expected": ["task-01"],
        "spawned": ["task-01"],
        "remaining": [],
    }))
    evidence = {"wave": 2, "outcome": "passed", "tasks": [], "wave_tag": "tag"}
    rc, stderr = _wave_complete(tmp_path, 2, evidence)
    assert rc == 2, f"expected BLOCK on stale spawn-count, got rc={rc}"
    assert "wave_id" in stderr.lower() or "stale" in stderr.lower()


def test_wave_complete_passes_through_when_no_spawn_count(tmp_path):
    """No .spawn-count.json (older install / wave with no spawns) → no
    shortfall check; downstream validator (wave-attribution) decides."""
    run_id = "run-no-count"
    _setup_run(tmp_path, run_id)
    # Don't write spawn-count.json. cmd_wave_complete should fall through
    # to wave-attribution.py invocation (which will fail in this minimal
    # tmp repo), but the failure must NOT be the spawn-count gate.
    evidence = {"wave": 1, "outcome": "passed", "tasks": [], "wave_tag": "tag"}
    rc, stderr = _wave_complete(tmp_path, 1, evidence)
    # We only assert the spawn-count gate did NOT fire; wave-attribution
    # itself may fail for other reasons in this minimal fixture.
    assert "shortfall" not in stderr.lower(), \
        f"spawn-count gate fired without a .spawn-count.json; stderr={stderr!r}"
