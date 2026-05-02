import json, sqlite3, subprocess
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "vg-state-machine-validator.py"


def _seed_events(db_path: Path, events: list) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    for ev in events:
        conn.execute(
            "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
            (ev["ts"], ev["event_type"], ev["phase"], "vg:blueprint", ev["run_id"], "{}"),
        )
    conn.commit()
    conn.close()


def test_blueprint_events_in_order_passes(tmp_path):
    db = tmp_path / "events.db"
    events = [
        {"ts": "2026-05-03T10:00:00Z", "event_type": "blueprint.tasklist_shown", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:01Z", "event_type": "blueprint.native_tasklist_projected", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:02Z", "event_type": "blueprint.plan_written", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:03Z", "event_type": "blueprint.contracts_generated", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:04Z", "event_type": "crossai.verdict", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:05Z", "event_type": "blueprint.completed", "phase": "2", "run_id": "r1"},
    ]
    _seed_events(db, events)
    result = subprocess.run(
        ["python3", str(VALIDATOR),
         "--db", str(db), "--command", "vg:blueprint", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_blueprint_events_out_of_order_fails(tmp_path):
    db = tmp_path / "events.db"
    events = [
        {"ts": "2026-05-03T10:00:00Z", "event_type": "blueprint.native_tasklist_projected", "phase": "2", "run_id": "r1"},
        {"ts": "2026-05-03T10:00:01Z", "event_type": "blueprint.tasklist_shown", "phase": "2", "run_id": "r1"},
    ]
    _seed_events(db, events)
    result = subprocess.run(
        ["python3", str(VALIDATOR),
         "--db", str(db), "--command", "vg:blueprint", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "out of order" in result.stderr.lower() or "expected" in result.stderr.lower()


def test_unknown_command_returns_error(tmp_path):
    db = tmp_path / "events.db"
    _seed_events(db, [])
    result = subprocess.run(
        ["python3", str(VALIDATOR),
         "--db", str(db), "--command", "vg:nonexistent", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "no state machine" in result.stderr.lower() or "unknown" in result.stderr.lower()


def test_missing_db_handled_gracefully(tmp_path):
    result = subprocess.run(
        ["python3", str(VALIDATOR),
         "--db", str(tmp_path / "nonexistent.db"),
         "--command", "vg:blueprint", "--run-id", "r1"],
        capture_output=True, text=True,
    )
    # Either exits non-zero with clear stderr, or treats as empty event list (then fails ordering)
    assert result.returncode != 0
