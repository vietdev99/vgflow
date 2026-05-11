"""tests/test_field_test_tail_source.py"""
from __future__ import annotations

import shutil, signal, subprocess, sys, time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TAIL = REPO_ROOT / "scripts" / "field-test" / "tail-source.sh"
PREFIX = REPO_ROOT / "scripts" / "field-test" / "prefix-iso.py"
MIRROR_TAIL = REPO_ROOT / ".claude" / "scripts" / "field-test" / "tail-source.sh"
MIRROR_PREFIX = REPO_ROOT / ".claude" / "scripts" / "field-test" / "prefix-iso.py"


def test_scripts_exist():
    assert TAIL.is_file()
    assert PREFIX.is_file()


def test_tail_uses_python_timestamp_not_gnu_date():
    body = TAIL.read_text(encoding="utf-8")
    assert "%3N" not in body, "v2 forbids date %3N (macOS BSD date breaks silently)"
    assert "prefix-iso.py" in body


def test_tail_pipes_through_redactor():
    body = TAIL.read_text(encoding="utf-8")
    assert "redact-stream.py" in body, "v2 mandates capture-time redaction before disk write"


def test_tail_takes_redaction_pattern_arg():
    body = TAIL.read_text(encoding="utf-8")
    assert "--redact" in body, "tail must accept --redact pattern for per-session regex"


def test_tail_has_respawn_loop():
    """v2.1 round-2 MUST-1: tail-source must respawn up to 3 times on
    transient pipe death, then log tail.dead and give up."""
    body = TAIL.read_text(encoding="utf-8")
    assert "respawn" in body.lower(), "tail-source must contain a respawn loop"
    # Verify a counter limit (3) is present somewhere
    assert "3" in body, "respawn counter limit must be configured"


def test_mirror_byte_identity():
    assert TAIL.read_bytes() == MIRROR_TAIL.read_bytes()
    assert PREFIX.read_bytes() == MIRROR_PREFIX.read_bytes()


_bash = pytest.mark.skipif(
    not shutil.which("bash"),
    reason="POSIX bash required (Git Bash on Windows is fine)",
)


@_bash
def test_tail_file_mode_redacts_inline(tmp_path):
    target = tmp_path / "src.log"
    out = tmp_path / "out.log"
    target.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(TAIL), "--type", "file", "--target", str(target),
         "--out", str(out), "--redact", "password|token"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        with target.open("a", encoding="utf-8") as f:
            f.write("login password=hunter2 success\n")
        time.sleep(1.5)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    text = out.read_text(encoding="utf-8")
    assert "hunter2" not in text, "tail must redact at capture, not leave to build-time"
    assert "[REDACTED]" in text


_bash_not_win = pytest.mark.skipif(
    not shutil.which("bash") or sys.platform == "win32",
    reason=(
        "Skipped on Windows: Git Bash subprocess pipe-inheritance causes proc.wait() "
        "to hang when tail -F child holds the stderr pipe after parent termination. "
        "This test MUST pass on Linux/macOS CI."
    ),
)


@_bash_not_win
def test_tail_handles_path_with_spaces(tmp_path):
    """v2.1 round-2 SHOULD-7: real installs live under paths like
    'Vibe Code/Code/PrintwayV3/' — tail-source must not split on
    whitespace when quoting its target/out args."""
    spaced = tmp_path / "with spaces" / "ft session"
    spaced.mkdir(parents=True)
    target = spaced / "src.log"
    out = spaced / "out.log"
    target.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(TAIL), "--type", "file", "--target", str(target),
         "--out", str(out), "--redact", "password|token"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.5)
        with target.open("a", encoding="utf-8") as f:
            f.write("login password=hunter2 success\n")
        time.sleep(1.5)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    err = proc.stderr.read().decode("utf-8") if proc.stderr else ""
    assert out.is_file(), f"path-with-spaces output not written; stderr={err}"
    text = out.read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert "[REDACTED]" in text


@_bash
def test_tail_iso_prefix_works_on_any_unix(tmp_path):
    """Verifies prefix-iso.py emits parseable ISO timestamps."""
    target = tmp_path / "src.log"
    out = tmp_path / "out.log"
    target.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(TAIL), "--type", "file", "--target", str(target),
         "--out", str(out), "--redact", "default"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        with target.open("a", encoding="utf-8") as f:
            f.write("hello world\n")
        time.sleep(1.5)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    text = out.read_text(encoding="utf-8")
    for line in text.strip().splitlines():
        assert line[:4].isdigit() and "T" in line[:20] and "Z" in line[:35], (
            f"line missing ISO timestamp: {line!r}"
        )
