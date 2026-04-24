"""
Tests for verify-log-hygiene.py — Phase M Batch 2 of v2.5.2.

Covers:
  - Sanitization middleware present → 0
  - console.log(req.body) on mutation route → 1
  - logger.info with Authorization header → 1
  - Runtime log with "password":"plaintext" → 1
  - Email redaction present (runtime) → 0
  - JSON output parseable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (REPO_ROOT / ".claude" / "scripts" / "validators"
             / "verify-log-hygiene.py")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace",
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestLogHygiene:
    def test_sanitizer_middleware_passes(self, tmp_path):
        _write(tmp_path / "app.js", """
const pino = require('pino');
const logger = pino({
  redact: {
    paths: ['req.headers.authorization', 'req.body.password', '*.token'],
    censor: '[REDACTED]',
  },
});
function handle(req) {
  logger.info({ userId: req.user.id }, 'login');
}
""")
        r = _run(["--project-root", str(tmp_path), "--quiet"])
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_console_log_req_body_blocks(self, tmp_path):
        _write(tmp_path / "handler.js", """
app.post('/users', (req, res) => {
  console.log(req.body);   // LEAK: logs password/email/etc
  return res.send('ok');
});
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        assert "req.body" in r.stdout.lower() or "sensitive" in r.stdout.lower()

    def test_logger_authorization_blocks(self, tmp_path):
        _write(tmp_path / "middleware.js", """
function auth(req, res, next) {
  logger.info({ Authorization: req.headers.authorization });
  next();
}
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        assert "authorization" in r.stdout.lower()

    def test_runtime_password_plaintext_blocks(self, tmp_path):
        log = tmp_path / "app.log"
        log.write_text(
            '2026-04-24 10:00:00 INFO user login body='
            '{"email":"alice@example.com","password":"hunter2secret"}\n'
            '2026-04-24 10:00:01 INFO token issued\n',
            encoding="utf-8",
        )
        r = _run([
            "--log-file", str(log),
            "--mode", "runtime",
        ])
        assert r.returncode == 1
        assert "password" in r.stdout.lower()

    def test_runtime_redacted_email_passes(self, tmp_path):
        log = tmp_path / "app.log"
        # masked local part
        log.write_text(
            '2026-04-24 10:00:00 INFO user a****@example.com logged in\n'
            '2026-04-24 10:00:01 INFO b******@example.org requested reset\n',
            encoding="utf-8",
        )
        r = _run([
            "--log-file", str(log),
            "--mode", "runtime",
            "--quiet",
        ])
        # No raw email (all masked), no bearer, no password — should pass
        assert r.returncode == 0

    def test_json_output_parseable(self, tmp_path):
        _write(tmp_path / "h.js", "function ok() { return 1; }")
        r = _run([
            "--project-root", str(tmp_path),
            "--json",
        ])
        data = json.loads(r.stdout)
        assert data["validator"] == "verify-log-hygiene"
        assert "verdict" in data
        assert "mode" in data
        assert data["mode"] == "sast"
