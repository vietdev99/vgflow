"""R8-H (Critical bug): complete-milestone.py + generate-milestone-summary.py
must accept ``${PHASE}-UAT.md`` as well as plain ``UAT.md``.

/vg:accept writes ``${PHASE_DIR}/${PHASE_NUMBER}-UAT.md`` (e.g. ``4.1-UAT.md``)
per ``commands/vg/accept.md:22``. Path mismatch in milestone closeout meant
the accept gate was structurally impossible to satisfy on modern phases.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLETE_MS = REPO_ROOT / "scripts" / "complete-milestone.py"
GEN_SUMMARY = REPO_ROOT / "scripts" / "generate-milestone-summary.py"


def _load(path: Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
    spec.loader.exec_module(mod)
    return mod


def _make_phase(tmp_path: Path, name: str, uat_filename: str | None) -> Path:
    p = tmp_path / name
    p.mkdir()
    if uat_filename:
        (p / uat_filename).write_text("# UAT\n\nVerdict: ACCEPTED\n")
    return p


def test_modern_phase_uat_recognized(tmp_path):
    """Phase with `${num}-UAT.md` (modern accept output) must count as accepted."""
    cm = _load(COMPLETE_MS, "complete_milestone")
    phase = _make_phase(tmp_path, "4.1-foo", "4.1-UAT.md")
    accepted, missing = cm.check_phase_acceptance([phase])
    assert accepted == ["4.1-foo"], (accepted, missing)
    assert missing == []


def test_legacy_plain_uat_still_recognized(tmp_path):
    """Plain `UAT.md` (legacy phases) must still count as accepted."""
    cm = _load(COMPLETE_MS, "complete_milestone_legacy")
    phase = _make_phase(tmp_path, "1-legacy", "UAT.md")
    accepted, missing = cm.check_phase_acceptance([phase])
    assert accepted == ["1-legacy"]
    assert missing == []


def test_missing_uat_blocks(tmp_path):
    """Phase without any UAT artifact must be reported as missing."""
    cm = _load(COMPLETE_MS, "complete_milestone_missing")
    phase = _make_phase(tmp_path, "5-noaccept", None)
    accepted, missing = cm.check_phase_acceptance([phase])
    assert accepted == []
    assert missing == ["5-noaccept"]


def test_summary_phase_status_modern_uat(tmp_path):
    """generate-milestone-summary.phase_status must mark accepted=True for ${num}-UAT.md."""
    gms = _load(GEN_SUMMARY, "generate_milestone_summary")
    phase = _make_phase(tmp_path, "4.2-bar", "4.2-UAT.md")
    status = gms.phase_status(phase)
    assert status["accepted"] is True


def test_summary_phase_status_legacy_uat(tmp_path):
    """generate-milestone-summary must accept plain UAT.md (legacy)."""
    gms = _load(GEN_SUMMARY, "generate_milestone_summary_legacy")
    phase = _make_phase(tmp_path, "2-legacy", "UAT.md")
    status = gms.phase_status(phase)
    assert status["accepted"] is True


def test_summary_phase_status_no_uat(tmp_path):
    """No UAT artifact → accepted=False."""
    gms = _load(GEN_SUMMARY, "generate_milestone_summary_none")
    phase = _make_phase(tmp_path, "3-none", None)
    status = gms.phase_status(phase)
    assert status["accepted"] is False


def test_mirror_parity():
    """Source and .claude/ mirror must stay byte-identical."""
    for src, mirror in [
        (COMPLETE_MS, REPO_ROOT / ".claude/scripts/complete-milestone.py"),
        (GEN_SUMMARY, REPO_ROOT / ".claude/scripts/generate-milestone-summary.py"),
    ]:
        assert mirror.is_file(), f"Mirror missing: {mirror}"
        assert src.read_bytes() == mirror.read_bytes(), f"Mirror drift: {mirror}"
