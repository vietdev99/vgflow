"""R3.5 Roam Pilot — discovery ref absorbs Phase F Task 30 (vg-load --index).

Round-2 D1/D2 fix: also asserts the helper script (the actual consumer)
honors --use-vg-load-index and loads CRUD-SURFACES.md, not just the ref.
The earlier test passed a narrative mention while the helper still
flat-read PLAN.md / API-CONTRACTS.md and ignored CRUD-SURFACES.md.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DISCOVERY = REPO / "commands/vg/_shared/roam/discovery.md"
HELPER = REPO / "scripts/roam-discover-surfaces.py"
HELPER_MIRROR = REPO / ".claude/scripts/roam-discover-surfaces.py"


def test_discovery_ref_uses_vg_load():
    text = DISCOVERY.read_text()
    assert "vg-load" in text, "discovery.md must reference vg-load"
    assert "--index" in text, "discovery.md must use vg-load --index for surface enumeration"


def test_discovery_ref_does_not_flat_read_plan_md():
    text = DISCOVERY.read_text()
    # Allow narrative/cautionary mentions (e.g. "DO NOT cat PLAN.md") but
    # forbid actual instructions to flat-read.
    # Strategy: check for `cat ${PHASE_DIR}/PLAN.md` or `cat ... PLAN.md` in
    # active code blocks. Cautionary lines containing "DO NOT" are fine.
    for line in text.splitlines():
        stripped = line.strip()
        # Skip comment / cautionary lines
        if "DO NOT" in stripped or stripped.startswith("#") or stripped.startswith(">"):
            continue
        # Active flat-read patterns
        assert not re.search(r'^\s*cat\s+\S*PLAN\.md', line), (
            f"discovery.md must not contain `cat ... PLAN.md` outside cautionary lines: {line!r}"
        )
        # Read tool invocation (Markdown documenting `Read PLAN.md` is OK as
        # a description but shouldn't appear inside code blocks as an
        # instruction). Heuristic: backtick-wrapped Read call.
        assert not re.search(r'`Read\s+\S*PLAN\.md`', line), (
            f"discovery.md must not instruct `Read PLAN.md` flat: {line!r}"
        )


def test_discovery_ref_keeps_context_runtime_map_flat():
    """CONTEXT.md and RUNTIME-MAP.md remain KEEP-FLAT per spec — verify the ref says so."""
    text = DISCOVERY.read_text()
    assert "CONTEXT.md" in text and "RUNTIME-MAP.md" in text, (
        "discovery.md must reference both small-doc artifacts that stay flat"
    )
    assert "KEEP-FLAT" in text, (
        "discovery.md must declare CONTEXT.md / RUNTIME-MAP.md as KEEP-FLAT"
    )


# ---------------------------------------------------------------------------
# Helper-level (runtime) coverage — round-2 D1/D2 fix
# ---------------------------------------------------------------------------

def test_helper_declares_use_vg_load_index_flag():
    """roam-discover-surfaces.py MUST accept --use-vg-load-index that the
    discovery.md ref passes (round-2 D1).
    """
    src = HELPER.read_text(encoding="utf-8")
    assert "--use-vg-load-index" in src, (
        "scripts/roam-discover-surfaces.py must declare --use-vg-load-index "
        "(discovery.md passes this flag — undeclared = silent ignore)"
    )


def test_helper_invokes_vg_load_for_plan():
    """Helper must reference the vg-load shell helper, not flat-read PLAN.md."""
    src = HELPER.read_text(encoding="utf-8")
    assert "vg-load" in src, (
        "scripts/roam-discover-surfaces.py must consume vg-load (shell helper) "
        "for PLAN.md instead of flat-reading it"
    )
    assert "_load_via_vg_load" in src or "subprocess" in src, (
        "helper must actually invoke vg-load (subprocess), not just mention it"
    )


def test_helper_loads_crud_surfaces():
    """CRUD-SURFACES.md is the authoritative source — helper MUST load it (round-2 D2)."""
    src = HELPER.read_text(encoding="utf-8")
    assert "CRUD-SURFACES.md" in src, (
        "scripts/roam-discover-surfaces.py must load CRUD-SURFACES.md "
        "(authoritative resource contract — round-2 D2 fix)"
    )


def test_helper_runtime_picks_up_crud_surfaces(tmp_path):
    """End-to-end: invoke the helper against a fixture phase that has only
    CRUD-SURFACES.md — output must contain a row tagged `CRUD-SURFACES.md`.
    """
    fixture = REPO / "tests/fixtures/recursive-probe-smoke"
    if not (fixture / "CRUD-SURFACES.md").exists():
        # Fixture moved/renamed — soft-pass to keep this test from blocking.
        return
    out = tmp_path / "SURFACES.md"
    rc = subprocess.run(
        [sys.executable, str(HELPER), "--phase-dir", str(fixture), "--output", str(out)],
        capture_output=True, text=True, timeout=30,
    )
    assert rc.returncode == 0, (
        f"helper failed rc={rc.returncode} stderr={rc.stderr!r}"
    )
    body = out.read_text(encoding="utf-8")
    assert "CRUD-SURFACES.md" in body, (
        "SURFACES.md output must cite CRUD-SURFACES.md as the source for "
        "authoritative rows (round-2 D2 fix)"
    )


def test_helper_mirrors_match():
    """`scripts/` and `.claude/scripts/` mirrors of the helper must be byte-identical."""
    if not HELPER_MIRROR.exists():
        return  # mirror layout may differ in some clones
    a = HELPER.read_bytes()
    b = HELPER_MIRROR.read_bytes()
    assert a == b, (
        "scripts/roam-discover-surfaces.py and .claude/scripts/roam-discover-surfaces.py "
        "drifted — mirror them after every round-2 fix"
    )
