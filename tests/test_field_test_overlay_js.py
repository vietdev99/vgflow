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


def test_overlay_no_innerhtml_for_location_href():
    """v2.1 fix I-1: modal URL must use textContent not innerHTML."""
    body = OVERLAY.read_text(encoding="utf-8")
    # Forbidden pattern: 'URL: ' concatenated directly into innerHTML
    forbidden = "'URL: ' + location.href"
    assert forbidden not in body, (
        "I-1 regression: location.href must be set via textContent, not innerHTML"
    )
    # Required pattern: textContent with URL
    assert ".textContent" in body, "URL div must use .textContent"
    assert "URL: " in body and "location.href" in body, "URL string still composed"


def test_overlay_zindex_modal_above_overlay():
    """v2.1 fix I-2: modal must sit ABOVE overlay buttons."""
    body = OVERLAY.read_text(encoding="utf-8")
    # Both z-index values must be present
    assert "z-index:2147483647" in body, "modal must use max z-index"
    assert "z-index:2147483646" in body, "overlay must use modal-minus-1"
    # The MAX z-index must be on the modal block (heuristic: appears after 'modal-id' assignment)
    modal_start = body.index("__vg-ft-modal")
    overlay_start = body.index("__vg-ft-overlay")
    # Find first z-index mention after each id assignment
    modal_zindex = body.index("z-index", modal_start)
    overlay_zindex = body.index("z-index", overlay_start)
    # Modal's z-index line must be the MAX (2147483647)
    assert "2147483647" in body[modal_zindex:modal_zindex + 30], (
        "I-2 regression: modal must declare z-index:2147483647"
    )
    assert "2147483646" in body[overlay_zindex:overlay_zindex + 30], (
        "I-2 regression: overlay must declare z-index:2147483646 (below modal)"
    )


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
