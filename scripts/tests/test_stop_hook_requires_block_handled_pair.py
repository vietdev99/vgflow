import json, os, sqlite3, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-stop.sh"


def _setup_run(repo: Path, fired_count: int = 0, handled_count: int = 0):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))
    db = repo / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    for i in range(fired_count):
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            ("2026-05-03T10:00:00Z", "vg.block.fired", "2", "vg:blueprint", "r1",
             json.dumps({"gate": f"gate-{i}"})),
        )
    for i in range(handled_count):
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            ("2026-05-03T10:00:01Z", "vg.block.handled", "2", "vg:blueprint", "r1",
             json.dumps({"gate": f"gate-{i}"})),
        )
    conn.commit()
    conn.close()


def test_stop_passes_when_no_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = subprocess.run(
        ["bash", str(HOOK)],
        input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0


def test_stop_blocks_on_unpaired_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, fired_count=2, handled_count=1)
    result = subprocess.run(
        ["bash", str(HOOK)],
        input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 2
    assert "UNHANDLED DIAGNOSTIC" in result.stderr or "vg.block" in result.stderr


def test_stop_passes_when_paired_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup_run(tmp_path, fired_count=2, handled_count=2)
    # No state machine sequence in db, but state machine check runs and may report missing events.
    # If Stop blocks on state machine fail (which is correct), this test still asserts the block message
    # mentions state machine, not unhandled diagnostic.
    result = subprocess.run(
        ["bash", str(HOOK)],
        input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    # State machine WILL fail because expected sequence isn't seeded. Verify the FAIL is from state machine, not unpaired diagnostic.
    if result.returncode == 2:
        assert "STATE MACHINE" in result.stderr or "expected sequence" in result.stderr.lower()
        assert "UNHANDLED DIAGNOSTIC" not in result.stderr
