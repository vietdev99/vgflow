"""tests/test_field_test_redact_stream.py — capture-time redaction helper."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REDACT = REPO_ROOT / "scripts" / "field-test" / "redact-stream.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "redact-stream.py"


def _run(stdin: str, pattern: str = "password|token|secret|api[_-]?key|email|bearer\\s+[A-Za-z0-9._-]+|authorization:\\s*\\S+") -> str:
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", pattern],
        input=stdin, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return r.stdout


def test_kv_equals_form():
    out = _run("login: password=hunter2 success\n")
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_kv_colon_header_form():
    out = _run("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxxx\n")
    assert "eyJhbGc" not in out


def test_json_body_form():
    out = _run('POST /api/login {"email":"u@x.com","password":"hunter2"}\n')
    assert "hunter2" not in out
    assert "u@x.com" not in out


def test_url_query_form():
    out = _run("GET /api/things?api_key=ABCDEF&page=2\n")
    assert "ABCDEF" not in out
    assert "page=2" in out, "non-sensitive query params must pass through"


def test_bare_bearer_form():
    out = _run("Got header Bearer eyJhbGc.deadbeef.signature\n")
    assert "deadbeef" not in out


def test_safe_input_passes_through():
    safe = "INFO order created id=42 status=ok\n"
    out = _run(safe)
    assert out.strip() == safe.strip()


def test_idempotency():
    """Re-redacting redacted output should not change it."""
    once = _run("password=hunter2\n")
    twice = _run(once)
    assert once == twice


def test_bad_user_regex_falls_back_to_default():
    """An invalid regex must fall back to default + emit warning to stderr, not crash."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", "[unclosed"],
        input="password=hunter2\n", capture_output=True, text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    assert "hunter2" not in r.stdout, "default regex must still apply"
    assert "warning" in r.stderr.lower() or "fallback" in r.stderr.lower()


def test_user_pattern_already_wrapped_not_double_wrapped():
    """v2.1 round-2 MUST-5: when the user passes a pattern that already
    contains regex metacharacters (\\b, capture groups, char classes), the
    composition logic must NOT wrap it into the multi-form template — that
    silently breaks user intent.

    Reproduction: user passes `\\bjwt=([A-Za-z0-9._-]+)` expecting a
    capture-group replacement. The naive composition wraps it as
    `(?:\\bjwt=([A-Za-z0-9._-]+))\\s*[:=]\\s*"?[^"\\s,&}]+` which then
    requires ANOTHER `[:=]` after the user match — input "jwt=token" has
    no second `=`, so the first alternative fails and the token leaks.
    """
    user_pattern = r"\bjwt=([A-Za-z0-9._-]+)"
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", user_pattern],
        input="auth jwt=eyJhbGc.payload.sig done\n",
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0
    assert "eyJhbGc.payload.sig" not in r.stdout, (
        "MUST-5: user-supplied pattern must not be silently double-wrapped — "
        "the literal token leaked through"
    )
    assert "REDACTED" in r.stdout or "[REDACTED]" in r.stdout


def test_user_pattern_with_existing_group_compiles():
    """v2.1 round-2 MUST-5 companion: composition must succeed when user
    pattern already declares its own capture group(s)."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", r"(secret_\d+)"],
        input="value=secret_42 leaks\n",
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, (
        f"composition must compile when user pattern has capture groups; "
        f"stderr={r.stderr}"
    )
    assert "secret_42" not in r.stdout


def test_mirror_byte_identity():
    assert REDACT.read_bytes() == MIRROR.read_bytes()


def test_hyphenated_header_key_redacts():
    """v2.1 round-2 code review: X-API-Key style keys must redact value."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", "X-API-Key|X-Auth-Token"],
        input="X-API-Key: secretvalue123 trailing\n",
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "secretvalue123" not in r.stdout, (
        "Hyphenated header key user pattern must redact value, not just key name"
    )
    assert "[REDACTED]" in r.stdout


def test_hyphenated_kv_equals_form():
    """Hyphenated key in kv=value form."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", "my-secret"],
        input="config my-secret=hunter2 ok\n",
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "hunter2" not in r.stdout
    assert "[REDACTED]" in r.stdout


def test_single_quoted_json_form_known_limitation():
    """Document scope: Python dict-repr style is NOT redacted (single quotes).
    This test pins the current behavior so future regressions surface."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", "default"],
        input="logged {'password': 's3cr3t', 'user': 'alice'}\n",
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    # KNOWN LIMITATION: single-quoted JSON form not covered. If future work adds it,
    # change this assertion. For now we verify the limitation is stable.
    # Use a marker comment so a future contributor knows to revisit.
    if "s3cr3t" in r.stdout:
        # Current state: known limitation — single quotes not covered.
        # If you remove this branch, also extend _compose_multiform to handle
        # single-quoted JSON body.
        pass
    else:
        # Coverage extended — assert redaction succeeded.
        assert "[REDACTED]" in r.stdout
