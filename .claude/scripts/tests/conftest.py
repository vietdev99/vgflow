"""
Shared pytest fixtures for VG regression tests.

Central rule: BLOCK (rc=2) is an EXPECTED outcome for many regression
scenarios — bypass attempts, negative gates, contract violations. The
regression harness treats expected BLOCK as green; unexpected BLOCK as red.

`assert_expected_block(result, reason)` is the canonical way to assert
BLOCK. It:
- Fails loudly if result.returncode != 2 (gate weakened or broken)
- Logs the block event to `.vg/block-log/regression.jsonl` for observability
- Never raises on the BLOCK itself — continuation is the whole point

Block-log summary prints at end of pytest session so ops can see which
gates fired, how often, and whether any unexpected ones appeared.

Phase R (v2.7) — platform compatibility:
`BASH_AVAILABLE` detects whether subprocess.run(["bash", ...]) actually
works in this environment. Windows machines with broken WSL distros
return False, allowing tests that shell out to bash to skip with a
clear reason instead of failing on environment noise.
See PLATFORM-COMPAT.md for the full matrix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ─── Phase R — bash subprocess availability probe ─────────────────────
# Tests that invoke `subprocess.run(["bash", ...])` rely on a working
# bash executable resolved by the OS PATH. Windows installs may surface
# the WSL `bash.exe` shim (System32) which fails when no default
# distro is installed, producing rc=1 with a "CreateProcessCommon"
# stderr blob — NOT a real test failure. Skip such tests on platforms
# where the probe fails so CI noise stays bounded to genuine issues.
def _probe_bash() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["bash", "-c", "echo OK"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and "OK" in r.stdout:
            return True, ""
        return False, f"bash probe rc={r.returncode}, stderr={(r.stderr or '')[:200]!r}"
    except FileNotFoundError:
        return False, "bash not found on PATH"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"bash probe failed: {exc}"


_BASH_OK, _BASH_REASON = _probe_bash()
BASH_AVAILABLE: bool = _BASH_OK
BASH_UNAVAILABLE_REASON: str = _BASH_REASON or "bash subprocess unavailable on this platform"

# Convenience pytest marker — usage:
#   @needs_bash
#   def test_x(...): ...
# or
#   pytestmark = needs_bash   # at module top
needs_bash = pytest.mark.skipif(
    not BASH_AVAILABLE,
    reason=(
        "Phase R: bash subprocess unavailable on this platform "
        f"(probe: {BASH_UNAVAILABLE_REASON}). "
        "See .claude/scripts/tests/PLATFORM-COMPAT.md."
    ),
)

# Convenience platform marker
on_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Phase R: skipped on Windows — see PLATFORM-COMPAT.md",
)


# ─── Phase R — UTF-8 subprocess helper (defense in depth) ─────────────
# Windows Python defaults `subprocess.run(text=True)` to the system
# legacy codec (cp1258 / cp1252 / cp437 depending on locale), which
# raises UnicodeDecodeError on any byte ≥0x80 in subprocess stdout
# (validator emoji, narration glyphs, BOMs from PowerShell). The
# canonical fix is `encoding="utf-8", errors="replace"` on every
# subprocess.run invocation that captures output.
#
# New tests SHOULD use this helper. Existing tests that already pass
# do so because they (a) don't decode output, (b) explicitly set
# PYTHONIOENCODING=utf-8 in env, or (c) consume bytes only.
def run_utf8(args, **kwargs):
    """Drop-in subprocess.run wrapper with UTF-8 stdout/stderr decoding.

    Use instead of subprocess.run when capturing text output cross-platform.
    Forces text mode + UTF-8 decoding + replacement for undecodable bytes.
    """
    kwargs.setdefault("capture_output", True)
    kwargs["text"] = True
    kwargs["encoding"] = "utf-8"
    kwargs.setdefault("errors", "replace")
    env = kwargs.get("env") or os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs["env"] = env
    return subprocess.run(args, **kwargs)


_BLOCK_LOG_DIR = Path(".vg") / "block-log"
_BLOCK_LOG_FILE = _BLOCK_LOG_DIR / "regression.jsonl"
_SESSION_BLOCKS: list[dict] = []


def _log_block(entry: dict) -> None:
    _SESSION_BLOCKS.append(entry)
    try:
        _BLOCK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _BLOCK_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Logging must never break the test — observability is best-effort.
        pass


def assert_expected_block(result, reason: str = "", *, test_id: str | None = None) -> None:
    """Assert subprocess result is a BLOCK (rc=2); log for observability.

    Use in tests where BLOCK is the correct green outcome (bypass tests,
    negative gate tests, contract-violation tests).

    Args:
        result: subprocess.CompletedProcess
        reason: short human explanation — why we expected this BLOCK
        test_id: optional override; defaults to PYTEST_CURRENT_TEST
    """
    tid = test_id or os.environ.get("PYTEST_CURRENT_TEST", "unknown")
    stderr_tail = (result.stderr or "")[-400:]
    stdout_tail = (result.stdout or "")[-200:]

    if result.returncode != 2:
        # Unexpected — regression FAIL. Log as unexpected so summary flags it.
        _log_block({
            "ts": datetime.now(timezone.utc).isoformat(),
            "test": tid,
            "reason": reason,
            "expected_rc": 2,
            "actual_rc": result.returncode,
            "outcome": "UNEXPECTED",
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
        })
        pytest.fail(
            f"Expected BLOCK (rc=2), got rc={result.returncode}\n"
            f"reason: {reason}\n"
            f"stderr: {stderr_tail}\n"
            f"stdout: {stdout_tail}"
        )

    _log_block({
        "ts": datetime.now(timezone.utc).isoformat(),
        "test": tid,
        "reason": reason,
        "expected_rc": 2,
        "actual_rc": 2,
        "outcome": "EXPECTED_BLOCK",
        "stderr_tail": stderr_tail,
    })


def assert_nonzero(result, reason: str = "", *, test_id: str | None = None) -> None:
    """Assert rc != 0 — catch-all for 'must not succeed' checks (BV-9, BV-10).

    Used when either rc=1 or rc=2 is acceptable; only PASS (rc=0) would be
    regression. Still logs for observability.
    """
    tid = test_id or os.environ.get("PYTEST_CURRENT_TEST", "unknown")

    if result.returncode == 0:
        _log_block({
            "ts": datetime.now(timezone.utc).isoformat(),
            "test": tid,
            "reason": reason,
            "expected_rc": "!=0",
            "actual_rc": 0,
            "outcome": "UNEXPECTED_PASS",
            "stderr_tail": (result.stderr or "")[-400:],
            "stdout_tail": (result.stdout or "")[-400:],
        })
        pytest.fail(
            f"Expected non-zero exit, got rc=0 (PASS)\n"
            f"reason: {reason}\n"
            f"stdout: {(result.stdout or '')[-400:]}"
        )

    _log_block({
        "ts": datetime.now(timezone.utc).isoformat(),
        "test": tid,
        "reason": reason,
        "expected_rc": "!=0",
        "actual_rc": result.returncode,
        "outcome": "EXPECTED_NONZERO",
    })


def pytest_sessionstart(session):
    """Rotate block-log at session start so each run is isolated."""
    _SESSION_BLOCKS.clear()
    if _BLOCK_LOG_FILE.exists():
        try:
            rotated = _BLOCK_LOG_FILE.with_suffix(".prev.jsonl")
            _BLOCK_LOG_FILE.replace(rotated)
        except OSError:
            pass


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print block-log summary after pytest finishes."""
    if not _SESSION_BLOCKS:
        return
    counts = {"EXPECTED_BLOCK": 0, "EXPECTED_NONZERO": 0,
              "UNEXPECTED": 0, "UNEXPECTED_PASS": 0}
    for entry in _SESSION_BLOCKS:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1

    tr = terminalreporter
    tr.write_sep("=", "VG block-log summary")
    for k, v in counts.items():
        if v:
            tr.write_line(f"  {k:20s}: {v}")
    tr.write_line(f"  log file: {_BLOCK_LOG_FILE}")

    unexpected = [e for e in _SESSION_BLOCKS
                  if e["outcome"].startswith("UNEXPECTED")]
    if unexpected:
        tr.write_sep("!", "Unexpected outcomes")
        for e in unexpected[:5]:
            tr.write_line(
                f"  {e['test']}: rc={e['actual_rc']} "
                f"(expected {e['expected_rc']}) — {e['reason']}"
            )
