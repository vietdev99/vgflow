"""
B11.2 — build-telemetry-surface.py tests.

Cross-step feedback: review entry reads recent build telemetry and
WARN-surfaces any BLOCK/FAIL events so phase 3 fix-loop seeds its
candidate list.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "build-telemetry-surface.py"


def _setup(tmp_path: Path, events: list[dict]) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    tele = tmp_path / ".vg" / "telemetry.jsonl"
    with tele.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    return tmp_path


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _hours_ago(h: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=h)).isoformat().replace(
        "+00:00", "Z",
    )


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=repo, capture_output=True, text=True, timeout=15, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line.strip())
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

def test_no_build_events_passes(tmp_path):
    repo = _setup(tmp_path, [
        {"ts": _now(), "phase": "9", "command": "vg:scope",
         "step": "scope.start", "outcome": "PASS", "event_type": "gate_hit"},
    ])
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_build_block_surfaces_as_warn(tmp_path):
    repo = _setup(tmp_path, [
        {"ts": _now(), "phase": "9", "command": "vg:build",
         "step": "build.wave-complete", "outcome": "BLOCK",
         "event_type": "gate_hit", "gate_id": "typecheck"},
    ])
    r = _run(repo)
    out = _parse(r.stdout)
    # Always exit 0 (non-blocking), verdict WARN
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "build_telemetry_surfaced"
               for e in out["evidence"])


def test_old_events_excluded_by_window(tmp_path):
    repo = _setup(tmp_path, [
        {"ts": _hours_ago(48), "phase": "9", "command": "vg:build",
         "step": "build.wave-complete", "outcome": "BLOCK",
         "event_type": "gate_hit"},
    ])
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_different_phase_excluded(tmp_path):
    repo = _setup(tmp_path, [
        {"ts": _now(), "phase": "8", "command": "vg:build",
         "step": "build.wave-complete", "outcome": "BLOCK",
         "event_type": "gate_hit"},
    ])
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_dedup_same_gate(tmp_path):
    """5 events for same (step, outcome, gate_id) → 1 surfaced finding."""
    events = []
    for _ in range(5):
        events.append({
            "ts": _now(), "phase": "9", "command": "vg:build",
            "step": "build.wave-complete", "outcome": "FAIL",
            "event_type": "gate_hit", "gate_id": "typecheck",
        })
    repo = _setup(tmp_path, events)
    r = _run(repo)
    out = _parse(r.stdout)
    ev = out["evidence"][0]
    # Actual should contain 1 entry not 5
    assert ev["actual"].count(";") == 0  # single-item list → no separator


def test_no_telemetry_file_passes(tmp_path):
    """Missing .vg/telemetry.jsonl → skip (nothing to surface)."""
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_registered_in_review_dispatcher():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "build-telemetry-surface" in mod.COMMAND_VALIDATORS.get("vg:review", [])
