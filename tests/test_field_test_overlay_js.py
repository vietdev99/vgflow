"""tests/test_field_test_overlay_js.py"""
from __future__ import annotations

import os, shutil, subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY = REPO_ROOT / "scripts" / "field-test" / "overlay.js"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "overlay.js"
RUNNER = REPO_ROOT / "scripts" / "field-test" / "_test-jsdom-runner.js"


def test_overlay_exists():
    assert OVERLAY.is_file()


def test_overlay_no_eval_no_cross_origin():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "eval(" not in body
    assert "new Function(" not in body
    assert "fetch('http" not in body and 'fetch("http' not in body


def test_overlay_state_shape():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "window.__VG_FT_STATE" in body
    assert "reload_epoch" in body, "v2 must track reload epoch for orchestrator dedupe"
    assert "marks:" in body
    assert "status:" in body


def test_overlay_console_emit_is_notification_only():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "state.marks.push" in body or "marks.push" in body, (
        "v2 overlay must push mark entries into state.marks (orchestrator polls state, not console)"
    )


def test_overlay_idempotent_init():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "if (window.__VG_FT_STATE) return" in body or "if (window.__VG_FT_INIT)" in body or "window.__VG_FT_STATE) {" in body, (
        "overlay must be idempotent on re-injection (post-reload)"
    )


def test_mirror_byte_identity():
    assert OVERLAY.read_bytes() == MIRROR.read_bytes()


_node = pytest.mark.skipif(not shutil.which("node"), reason="node required")


@_node
def test_overlay_syntax_via_node_check():
    r = subprocess.run(["node", "--check", str(OVERLAY)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@_node
def test_overlay_mark_flow_via_jsdom(tmp_path):
    """v2.1 round-2 SHOULD-6: functional smoke is DEFAULT.

    Runs overlay in jsdom: click Start → click Mark → fill note → submit.
    Assert state.marks.length === 1, status === 'recording', user_note captured.
    """
    if not RUNNER.is_file():
        pytest.fail(
            "v2.1: jsdom runner must ship at scripts/field-test/_test-jsdom-runner.js"
        )
    # The runner auto-installs jsdom via npm if absent — be patient.
    r = subprocess.run(["node", str(RUNNER), str(OVERLAY)],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(REPO_ROOT))
    if r.returncode != 0 and "Cannot find module 'jsdom'" in (r.stderr + r.stdout):
        pytest.skip("jsdom not installed and auto-install failed — install manually with: npm i --no-save jsdom (from scripts/field-test/)")
    assert r.returncode == 0, f"runner failed: stderr={r.stderr}\nstdout={r.stdout}"
    assert "marks.length=1" in r.stdout
    assert "status=recording" in r.stdout
    assert 'user_note="found bug"' in r.stdout
