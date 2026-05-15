"""tests/test_batch48_derive_edge_cases.py — Batch 48 F7 closure.

If blueprint skipped EDGE-CASES gen, test-spec auto-derives from
LIFECYCLE-SPECS edge_cases[] (Batch 37 first-class).
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "derive-edge-cases-from-lifecycle.py"
SCRIPT_MIRROR = REPO / ".claude" / "scripts" / "derive-edge-cases-from-lifecycle.py"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"


def test_script_exists_mirrored():
    assert SCRIPT.is_file() and SCRIPT_MIRROR.is_file()
    assert SCRIPT.read_text(encoding="utf-8") == SCRIPT_MIRROR.read_text(encoding="utf-8")


def test_script_derives_files_from_lifecycle(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    lifecycle = {
        "goals": {
            "G-01": {
                "title": "Create site",
                "edge_cases": [
                    {"kind": "boundary", "label": "min", "input_hint": "0", "expected": "accept"},
                    {"kind": "unicode_special", "label": "unicode", "input_hint": "🎉", "expected": "stored"},
                ],
            },
            "G-02": {"title": "Delete site", "edge_cases": []},
        }
    }
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    r = subprocess.run(
        ["python", str(SCRIPT), "--phase", "7", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out_file = phase_dir / "EDGE-CASES" / "G-01.md"
    assert out_file.is_file()
    body = out_file.read_text(encoding="utf-8")
    assert "G-01-b1" in body  # boundary variant_id
    assert "G-01-u2" in body  # unicode variant_id
    assert "variant_id:" in body  # yaml fence
    # G-02 has no edge_cases → no file
    assert not (phase_dir / "EDGE-CASES" / "G-02.md").exists()


def test_script_skips_existing_without_force(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {"title": "X", "edge_cases": [{"kind": "boundary", "label": "y"}]}}}),
        encoding="utf-8",
    )
    edge_dir = phase_dir / "EDGE-CASES"
    edge_dir.mkdir()
    existing = edge_dir / "G-01.md"
    existing.write_text("# EXISTING — do not overwrite\n", encoding="utf-8")
    r = subprocess.run(
        ["python", str(SCRIPT), "--phase", "7", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "EXISTING — do not overwrite" in existing.read_text(encoding="utf-8")


def test_script_force_overwrites(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {"title": "X", "edge_cases": [{"kind": "boundary", "label": "new"}]}}}),
        encoding="utf-8",
    )
    edge_dir = phase_dir / "EDGE-CASES"
    edge_dir.mkdir()
    (edge_dir / "G-01.md").write_text("# OLD\n", encoding="utf-8")
    r = subprocess.run(
        ["python", str(SCRIPT), "--phase", "7", "--phase-dir", str(phase_dir), "--force"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    body = (edge_dir / "G-01.md").read_text(encoding="utf-8")
    assert "OLD" not in body
    assert "G-01-b1" in body


def test_test_spec_invokes_derive_when_missing():
    body = TEST_SPEC.read_text(encoding="utf-8")
    assert "derive-edge-cases-from-lifecycle.py" in body, (
        "Batch 48 F7: test-spec.md must invoke derive script when EDGE-CASES absent"
    )
    assert '! -d "${PHASE_DIR}/EDGE-CASES"' in body or "EDGE-CASES/" in body, (
        "must condition derivation on missing dir"
    )


def test_mirror_in_sync():
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
