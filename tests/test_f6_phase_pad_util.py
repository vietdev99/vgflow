"""tests/test_f6_phase_pad_util.py — F6 shared phase_pad utility."""
from __future__ import annotations
import importlib.util
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
UTIL = REPO / "scripts" / "lib" / "phase_pad.py"


def _load_util():
    spec = importlib.util.spec_from_file_location("phase_pad", UTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_util_exists():
    assert UTIL.is_file(), "F6: scripts/lib/phase_pad.py must ship"


def test_util_handles_single_digit():
    mod = _load_util()
    assert mod.phase_pad(7) == "07"
    assert mod.phase_pad("7") == "07"


def test_util_handles_three_digit_no_truncate():
    mod = _load_util()
    # Critical: phase 100+ must NOT be truncated
    assert mod.phase_pad(100) == "100", "F6: phase 100 must NOT be zero-truncated"
    assert mod.phase_pad(123) == "123"


def test_util_handles_sub_phase_notation():
    mod = _load_util()
    # Sub-phase like 07.10.1 must preserve dot-notation
    assert mod.phase_pad("07.10.1") == "07.10.1"
    assert mod.phase_pad("5.2") == "05.2"  # leading zero applied to top-level only


def test_util_env_override_width():
    mod = _load_util()
    import os
    # Config-driven width via VG_PHASE_PAD_WIDTH env
    os.environ["VG_PHASE_PAD_WIDTH"] = "3"
    try:
        assert mod.phase_pad(7) == "007"
    finally:
        os.environ.pop("VG_PHASE_PAD_WIDTH", None)


def test_at_least_one_script_imports_phase_pad():
    """At least one production script must use the new util (not zfill(2) hardcode)."""
    found = False
    for p in (REPO / "scripts").rglob("*.py"):
        if p == UTIL:
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        if "from phase_pad" in body or "phase_pad(" in body or "phase_pad import" in body:
            found = True
            break
    assert found, (
        "F6: at least one script must import + use phase_pad() (not bare zfill(2)). "
        "Migrate the heaviest-traffic scripts first (vg-orchestrator, evidence-manifest)."
    )
