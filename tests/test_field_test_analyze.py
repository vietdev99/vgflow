"""tests/test_field_test_analyze.py — analyzer severity + KNOWN-ISSUES append."""
from __future__ import annotations

import json, subprocess, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYZER = REPO_ROOT / "scripts" / "field-test" / "analyze.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "analyze.py"
AGENT_SKILL = REPO_ROOT / "agents" / "vg-field-test-analyzer" / "SKILL.md"
AGENT_MIRROR = REPO_ROOT / ".claude" / "agents" / "vg-field-test-analyzer" / "SKILL.md"


def _seed_session(tmp_path: Path, marks: list[dict] | None = None) -> Path:
    """Build a complete bundled session (manifest.json + marks.jsonl)."""
    session = tmp_path / "ft-test-session"
    session.mkdir()
    if marks is None:
        marks = [{
            "n": 0, "ts": "2026-05-11T10:00:05.000Z",
            "url": "http://localhost:3000/checkout",
            "user_note": "5xx error after submit",
            "console_window": [
                '{"ts":"2026-05-11T10:00:04.500Z","level":"error","args":["Uncaught TypeError: x is undefined"]}',
            ],
            "network_window": [
                '{"ts":"2026-05-11T10:00:05.000Z","kind":"fetch","method":"POST","url":"/api/order","status":500}',
            ],
            "api_log_correlated": {},
        }]
    (session / "manifest.json").write_text(json.dumps({
        "version": "1", "sid": "ft-test-session", "phase": None,
        "mark_count": len(marks), "partial": False,
        "redaction_applied": "default",
        "redaction_locations": ["capture", "build"],
        "generated_at": "2026-05-11T10:01:00Z",
    }), encoding="utf-8")
    (session / "marks.jsonl").write_text(
        "\n".join(json.dumps(m) for m in marks),
        encoding="utf-8",
    )
    return session


def test_scripts_exist():
    assert ANALYZER.is_file()
    assert AGENT_SKILL.is_file()


def test_mirror_byte_identity():
    assert ANALYZER.read_bytes() == MIRROR.read_bytes()
    assert AGENT_SKILL.read_bytes() == AGENT_MIRROR.read_bytes()


def test_severity_5xx_is_high(tmp_path):
    """5xx network response → HIGH severity."""
    session = _seed_session(tmp_path)
    known = tmp_path / "KNOWN-ISSUES.json"
    r = subprocess.run(
        [sys.executable, str(ANALYZER), "--session-dir", str(session),
         "--known-issues", str(known)],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert len(payload["issues"]) == 1
    assert payload["issues"][0]["severity"] == "HIGH"


def test_severity_4xx_is_medium(tmp_path):
    """4xx network response → MEDIUM severity."""
    session = _seed_session(tmp_path, marks=[{
        "n": 0, "ts": "2026-05-11T10:00:05.000Z",
        "url": "http://localhost:3000/login",
        "user_note": "login refused",
        "console_window": [],
        "network_window": [
            '{"ts":"2026-05-11T10:00:05.000Z","kind":"fetch","method":"POST","url":"/api/login","status":401}',
        ],
        "api_log_correlated": {},
    }])
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "MEDIUM"


def test_severity_visual_only_is_low(tmp_path):
    """No errors / 5xx / unhandled exceptions → LOW severity (visual-only feedback)."""
    session = _seed_session(tmp_path, marks=[{
        "n": 0, "ts": "2026-05-11T10:00:05.000Z",
        "url": "http://localhost:3000/",
        "user_note": "button color wrong",
        "console_window": [],
        "network_window": [
            '{"ts":"2026-05-11T10:00:05.000Z","kind":"fetch","method":"GET","url":"/api/me","status":200}',
        ],
        "api_log_correlated": {},
    }])
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "LOW"


def test_severity_unhandled_exception_is_high(tmp_path):
    """Console error / 'Uncaught' / 'Traceback' → HIGH severity."""
    session = _seed_session(tmp_path, marks=[{
        "n": 0, "ts": "2026-05-11T10:00:05.000Z",
        "url": "http://localhost:3000/dashboard",
        "user_note": "blank page",
        "console_window": [
            '{"ts":"2026-05-11T10:00:04.500Z","level":"error","args":["Uncaught ReferenceError: app is not defined"]}',
        ],
        "network_window": [],
        "api_log_correlated": {},
    }])
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "HIGH"


def test_severity_mixed_5xx_and_4xx_picks_high(tmp_path):
    """When a mark has both 5xx and 4xx → HIGH wins."""
    session = _seed_session(tmp_path, marks=[{
        "n": 0, "ts": "2026-05-11T10:00:05.000Z",
        "url": "http://x",
        "user_note": "mixed",
        "console_window": [],
        "network_window": [
            '{"status":500}',
            '{"status":401}',
        ],
        "api_log_correlated": {},
    }])
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "HIGH"


def test_corrupt_known_issues_preserved_not_wiped(tmp_path):
    """v2.1: KNOWN-ISSUES.json corrupted → backup + refuse append, NEVER silently wipe."""
    session = _seed_session(tmp_path)
    known = tmp_path / "KNOWN-ISSUES.json"
    known.write_text("not valid json {", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(ANALYZER), "--session-dir", str(session),
         "--known-issues", str(known)],
        capture_output=True, text=True,
    )
    # Analyzer aborts the append (exit non-zero or prints 'corrupted')
    assert r.returncode != 0, "must NOT silently wipe corrupt KNOWN-ISSUES.json"
    assert "corrupt" in (r.stdout + r.stderr).lower()
    # Original corrupt file backed up (sidecar)
    backups = list(tmp_path.glob("KNOWN-ISSUES.corrupt-*.json.bak"))
    assert len(backups) == 1, "must back up corrupt file before refusing"
    # Corrupt content preserved AT BACKUP (and original may stay or move — either is OK)
    assert "not valid json" in backups[0].read_text(encoding="utf-8")


def test_idempotent_rerun_does_not_duplicate(tmp_path):
    """Re-run analyzer on same session → no duplicate entries (dedupe by sid+n)."""
    session = _seed_session(tmp_path)
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert len(payload["issues"]) == 1, (
        f"dedupe by (sid, n) — got {len(payload['issues'])} entries"
    )


def test_field_report_written(tmp_path):
    """analyze.py also writes FIELD-REPORT.md to session dir."""
    session = _seed_session(tmp_path)
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    report = session / "FIELD-REPORT.md"
    assert report.exists()
    body = report.read_text(encoding="utf-8")
    assert "FIELD-REPORT" in body or "Field Test Report" in body
    assert "ft-test-session" in body  # sid
    assert "HIGH" in body  # severity tag


def test_severity_high_on_spaced_json_level_error(tmp_path):
    """Critical regression: build-bundle.py emits json.dumps with default
    separators (space after colon). analyze.py must classify spaced JSON
    'level: "error"' as HIGH, not silently miss it."""
    session = _seed_session(tmp_path, marks=[{
        "n": 0, "ts": "2026-05-11T10:00:05.000Z",
        "url": "http://localhost:3000/x",
        "user_note": "blank screen",
        # NOTE the space between : and " — this is what build-bundle.py emits.
        "console_window": [
            '{"ts": "2026-05-11T10:00:04.500Z", "level": "error", "args": ["Failed to load resource"]}',
        ],
        "network_window": [],
        "api_log_correlated": {},
    }])
    known = tmp_path / "KNOWN-ISSUES.json"
    subprocess.run([sys.executable, str(ANALYZER), "--session-dir", str(session),
                    "--known-issues", str(known)], check=True)
    payload = json.loads(known.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "HIGH", (
        "spaced JSON level=error must be classified HIGH (default json.dumps separators)"
    )
