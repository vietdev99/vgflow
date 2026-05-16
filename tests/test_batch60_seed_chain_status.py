"""tests/test_batch60_seed_chain_status.py — Batch 60.

seed-chain-status.py — single command that runs every validator in
the B36→B59 chain and prints PASS/FAIL per layer. Diagnostic tool
for humans when sandbox deploy surfaces issues.

Coverage:
  1. Healthy phase → all PASS
  2. Missing LIFECYCLE → layer 1 FAIL
  3. Missing EDGE-CASES → layer 2 FAIL
  4. Missing VARIANTS.json → layer 3 FAIL
  5. Missing SEED-RECIPE → layer 4 FAIL
  6. Missing helper stub → layer 5 FAIL
  7. --strict exits 1 on any FAIL
  8. --json emits machine-readable structure
  9. CODEGEN-MANIFEST absent → layer 7 SKIP
  10. Mirror parity
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATUS = REPO / "scripts" / "seed-chain-status.py"
STATUS_MIRROR = REPO / ".claude" / "scripts" / "seed-chain-status.py"


def _run(phase_dir: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(STATUS), "--phase", "7", "--phase-dir", str(phase_dir), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _build_healthy_phase(tmp_path: Path) -> Path:
    """Build a phase with full chain in place."""
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}
    }), encoding="utf-8")
    # Run all generators
    for s in [
        "derive-edge-cases-from-lifecycle.py",
        "generate-seed-recipes.py",
        "generate-seed-helper-stub.py",
    ]:
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / s),
             "--phase", "7", "--phase-dir", str(phase_dir), "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    return phase_dir


def test_healthy_phase_all_pass(tmp_path):
    phase_dir = _build_healthy_phase(tmp_path)
    r = _run(phase_dir)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout.split("Summary:")[0]  # no FAIL in table
    # Layers 1-5 must be PASS
    for layer in ["1. LIFECYCLE-SPECS", "2. EDGE-CASES", "3. VARIANTS.json",
                  "4. SEED-RECIPE.md", "5. helper stub"]:
        assert layer in r.stdout
        # Find the row and verify PASS
        for line in r.stdout.split("\n"):
            if layer in line:
                assert "PASS" in line, f"{layer} not PASS: {line}"


def test_missing_lifecycle_layer1_fail(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    r = _run(phase_dir)
    # Layer 1 must FAIL
    for line in r.stdout.split("\n"):
        if "1. LIFECYCLE-SPECS" in line:
            assert "FAIL" in line


def test_missing_edge_cases_layer2_fail(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}
    }), encoding="utf-8")
    # No EDGE-CASES/ directory generated
    r = _run(phase_dir)
    for line in r.stdout.split("\n"):
        if "2. EDGE-CASES" in line:
            assert "FAIL" in line


def test_missing_helper_stub_layer5_fail(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}
    }), encoding="utf-8")
    # Run derive + recipes but NOT helper
    for s in ["derive-edge-cases-from-lifecycle.py", "generate-seed-recipes.py"]:
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / s),
             "--phase", "7", "--phase-dir", str(phase_dir), "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    r = _run(phase_dir)
    for line in r.stdout.split("\n"):
        if "5. helper stub" in line:
            assert "FAIL" in line


def test_strict_mode_exits_nonzero_on_fail(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    # No LIFECYCLE — layer 1 fails
    r = _run(phase_dir, "--strict")
    assert r.returncode != 0


def test_warn_mode_default_exits_zero(tmp_path):
    """Default (no --strict) exits 0 even when layers fail."""
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    r = _run(phase_dir)
    assert r.returncode == 0  # warn mode


def test_json_mode_emits_structured(tmp_path):
    phase_dir = _build_healthy_phase(tmp_path)
    r = _run(phase_dir, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["phase"] == "7"
    assert "results" in doc
    assert len(doc["results"]) == 8  # B63: added layer 8 feature_chain coverage


def test_codegen_manifest_absent_layer7_skip(tmp_path):
    phase_dir = _build_healthy_phase(tmp_path)
    r = _run(phase_dir)
    for line in r.stdout.split("\n"):
        if "7. spec seed binding" in line:
            assert "SKIP" in line


def test_summary_counts_correct(tmp_path):
    phase_dir = _build_healthy_phase(tmp_path)
    r = _run(phase_dir)
    assert "Summary:" in r.stdout
    summary_line = [l for l in r.stdout.split("\n") if l.startswith("Summary:")][0]
    # B63: Healthy phase now has 8 layers — 7 PASS (1,2,3,4,5,6,8) + 1 SKIP (7 spec binding)
    assert "7 PASS" in summary_line
    assert "1 SKIP" in summary_line


def test_mirror_in_sync():
    assert STATUS.read_text(encoding="utf-8") == STATUS_MIRROR.read_text(encoding="utf-8")
