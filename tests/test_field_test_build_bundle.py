"""tests/test_field_test_build_bundle.py — Stop-time bundle assembler."""
from __future__ import annotations

import json, subprocess, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILDER = REPO_ROOT / "scripts" / "field-test" / "build-bundle.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "build-bundle.py"


def _seed_minimal(tmp_path: Path) -> Path:
    """Build a minimal-but-valid field-test session directory."""
    session = tmp_path / "ft-2026-05-11T10-00-00Z"
    session.mkdir()
    (session / "session.json").write_text(json.dumps({
        "version": "1",
        "sid": "ft-2026-05-11T10-00-00Z",
        "phase": None,
        "base_url": "http://localhost:3000",
        "ts_started": "2026-05-11T10:00:00Z",
        "sources": [{"type": "file", "target": "/tmp/api.log", "label": "test"}],
        "redaction": "password|token",
    }), encoding="utf-8")
    (session / "marks.raw.jsonl").write_text(
        json.dumps({"n": 0, "ts": "2026-05-11T10:00:05.000Z", "url": "http://localhost:3000/",
                    "user_note": "first mark"}) + "\n" +
        json.dumps({"n": 1, "ts": "2026-05-11T10:00:10.000Z", "url": "http://localhost:3000/page2",
                    "user_note": "second"}) + "\n",
        encoding="utf-8",
    )
    return session


def _seed_empty(tmp_path: Path) -> Path:
    """Build a session with NO marks recorded."""
    session = tmp_path / "ft-empty"
    session.mkdir()
    (session / "session.json").write_text(json.dumps({
        "version": "1",
        "sid": "ft-empty",
        "phase": None,
        "base_url": "http://x",
        "ts_started": "2026-05-11T10:00:00Z",
        "sources": [],
        "redaction": "password",
    }), encoding="utf-8")
    return session


def test_scripts_exist():
    assert BUILDER.is_file()


def test_mirror_byte_identity():
    assert BUILDER.read_bytes() == MIRROR.read_bytes()


def test_happy_path_writes_manifest_and_marks(tmp_path):
    session = _seed_minimal(tmp_path)
    r = subprocess.run([sys.executable, str(BUILDER), "--session-dir", str(session)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mark_count"] == 2
    assert manifest["sid"] == "ft-2026-05-11T10-00-00Z"
    assert manifest["partial"] is False
    assert manifest["redaction_locations"] == ["capture", "build"]
    bundle_marks = (session / "marks.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(bundle_marks) == 2


def test_naive_timestamp_logged_to_errors(tmp_path):
    """v2.1: naive (non-Z) timestamps in API logs go to errors.jsonl, NOT silent."""
    session = _seed_minimal(tmp_path)
    (session / "api-test.log").write_text(
        "2026-05-11T10:00:05.000Z password=hunter2 first line\n"
        "2026-05-11 10:00:06 second line naive: no T+Z\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(BUILDER), "--session-dir", str(session), "--mark-window-sec", "30"],
        capture_output=True, text=True, check=True,
    )
    errors_path = session / "errors.jsonl"
    assert errors_path.exists(), "naive ts must be logged, not silently dropped"
    errors = errors_path.read_text(encoding="utf-8")
    assert "naive: no T+Z" in errors


def test_partial_marks_raw_recovered(tmp_path):
    """v2.1: truncated mid-line in marks.raw.jsonl → partial=true, no crash."""
    session = _seed_minimal(tmp_path)
    raw = session / "marks.raw.jsonl"
    raw.write_text(raw.read_text(encoding="utf-8") + '{"n": 99, "ts": "2026', encoding="utf-8")
    r = subprocess.run([sys.executable, str(BUILDER), "--session-dir", str(session)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["partial"] is True
    assert manifest["mark_count"] < 99
    assert manifest["mark_count"] == 2  # the two clean marks recovered


def test_zero_marks_session_valid_manifest(tmp_path):
    """v2.1: 0-marks session must still produce valid manifest, no crash."""
    session = _seed_empty(tmp_path)
    r = subprocess.run([sys.executable, str(BUILDER), "--session-dir", str(session)],
                       capture_output=True, text=True, check=True)
    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mark_count"] == 0
    assert manifest["partial"] is False


def test_redaction_applied_both_capture_and_build(tmp_path):
    """user_note that leaked a password must be redacted at build time."""
    session = _seed_minimal(tmp_path)
    # Overwrite marks.raw.jsonl with a mark whose user_note contains "password=hunter2"
    (session / "marks.raw.jsonl").write_text(
        json.dumps({"n": 0, "ts": "2026-05-11T10:00:05.000Z", "url": "http://x",
                    "user_note": "session expired password=hunter2 then OK"}) + "\n",
        encoding="utf-8",
    )
    r = subprocess.run([sys.executable, str(BUILDER), "--session-dir", str(session)],
                       capture_output=True, text=True, check=True)
    bundle = (session / "marks.jsonl").read_text(encoding="utf-8")
    assert "hunter2" not in bundle, "user_note must be redacted at build time"


def test_api_log_window_correlation(tmp_path):
    """API log lines within ±window of mark ts must be correlated."""
    session = _seed_minimal(tmp_path)
    # Override marks: single mark at 10:00:30
    (session / "marks.raw.jsonl").write_text(
        json.dumps({"n": 0, "ts": "2026-05-11T10:00:30.000Z", "url": "http://x",
                    "user_note": "test"}) + "\n",
        encoding="utf-8",
    )
    # API log: 3 lines, only middle one within ±30s window of 10:00:30
    (session / "api-test.log").write_text(
        "2026-05-11T09:59:55.000Z too_early\n"
        "2026-05-11T10:00:25.000Z within_window\n"
        "2026-05-11T10:01:05.000Z too_late\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(BUILDER), "--session-dir", str(session), "--mark-window-sec", "30"],
        capture_output=True, text=True, check=True,
    )
    bundle = json.loads((session / "marks.jsonl").read_text(encoding="utf-8").strip())
    api_correlated = bundle["api_log_correlated"]["test"]
    assert any("within_window" in ln for ln in api_correlated)
    assert not any("too_early" in ln for ln in api_correlated)
    assert not any("too_late" in ln for ln in api_correlated)
