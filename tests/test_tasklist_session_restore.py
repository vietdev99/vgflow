"""F1 v2.60.0: SessionStart auto-restores tasklist projection on resume/compact."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EMIT_TASKLIST = REPO_ROOT / "scripts" / "emit-tasklist.py"


def _make_contract(tmp_path: Path, run_id: str, items: list[dict]) -> Path:
    contract_dir = tmp_path / ".vg" / "runs" / run_id
    contract_dir.mkdir(parents=True)
    contract = contract_dir / "tasklist-contract.json"
    contract.write_text(json.dumps({
        "run_id": run_id,
        "command": "vg:build",
        "phase": "7.14",
        "projection_items": items,
    }, indent=2), encoding="utf-8")
    return contract_dir


def test_restore_mode_with_contract(tmp_path):
    items = [
        {"kind": "group", "id": "build", "title": "Build preflight", "status": "pending"},
        {"kind": "step", "id": "1_setup", "parent": "build",
         "title": "  ↳ 1 Setup capsule", "status": "in_progress"},
        {"kind": "step", "id": "2_load", "parent": "build",
         "title": "  ↳ 2 Load contracts", "status": "pending"},
    ]
    _make_contract(tmp_path, "test-run-001", items)
    r = subprocess.run(
        [sys.executable, str(EMIT_TASKLIST),
         "--restore-mode", "--run-id", "test-run-001"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "Tasklist restore" in out, "must include restore section header"
    assert "TodoWrite" in out, "must instruct AI to call TodoWrite"
    assert "1 Setup capsule" in out, "must include first item title"
    assert "in_progress" in out, "must surface status"


def test_restore_mode_no_contract(tmp_path):
    """Missing contract → exit 0 with informative empty marker."""
    r = subprocess.run(
        [sys.executable, str(EMIT_TASKLIST),
         "--restore-mode", "--run-id", "missing"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    # Either empty output or a clear "no contract" marker is acceptable
    assert ("no tasklist contract" in out.lower()
            or out.strip() == ""
            or "nothing to restore" in out.lower())


def test_restore_uses_snapshot_status_when_present(tmp_path):
    """If .todowrite-snapshot.json exists, use those statuses (more recent than contract)."""
    contract_items = [
        {"kind": "step", "id": "step1", "title": "  ↳ Step 1", "status": "pending"},
    ]
    contract_dir = _make_contract(tmp_path, "rid-snap", contract_items)
    # Snapshot says step1 actually completed
    snapshot = contract_dir / ".todowrite-snapshot.json"
    snapshot.write_text(json.dumps({
        "items": [{"id": "step1", "status": "completed"}],
    }), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(EMIT_TASKLIST),
         "--restore-mode", "--run-id", "rid-snap"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    # Should show completed (from snapshot), not pending (from contract)
    out = r.stdout
    assert "completed" in out, "snapshot status should override contract default"


def test_emit_tasklist_mirror_byte_identical():
    canonical = REPO_ROOT / "scripts" / "emit-tasklist.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "emit-tasklist.py"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_session_start_hook_invokes_restore():
    body = (REPO_ROOT / "scripts" / "hooks" / "vg-session-start.sh").read_text(encoding="utf-8")
    assert "--restore-mode" in body, (
        "vg-session-start.sh must invoke emit-tasklist --restore-mode for F1 fix"
    )


def test_session_start_hook_mirror():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-session-start.sh"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-session-start.sh"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_tasklist_snapshot_helper_exists():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    assert canonical.exists(), "snapshot helper must exist for F2 wiring"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
    if mirror.exists():
        assert canonical.read_bytes() == mirror.read_bytes()
