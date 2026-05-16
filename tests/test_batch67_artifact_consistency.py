"""tests/test_batch67_artifact_consistency.py — B67 (codex MAJOR fix).

Codex audit MAJOR: B67 original plan said "every goal_id has variant".
False — verify-variants-json:81-83 already says VARIANTS.json optional
when no lifecycle variants. Validator must exclude goals without
edge_cases/negative_specs.

Also exempt goals with infra_deps tag (manual test).

Coverage:
  1. Validator skips when LIFECYCLE-SPECS absent (graceful skip)
  2. Goal with variants + matching VARIANTS.json + SEED-RECIPE → PASS
  3. Goal with variants but missing VARIANTS.json → gap
  4. Goal with variants but missing SEED-RECIPE → gap
  5. Goal WITHOUT variants → exempt from VARIANTS + SEED checks
  6. Goal with infra_deps tag → exempt entirely (manual test)
  7. CODEGEN-MANIFEST present → goal missing from manifest = gap
  8. CODEGEN-MANIFEST absent → manifest check skipped
  9. --strict mode: gaps → exit 1
  10. Default (warn-only): gaps → exit 0
  11. JSON output mode
  12. Preflight wiring (--strict-artifact-consistency flag)
  13. Mirror parity
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-test-artifact-consistency.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-test-artifact-consistency.py"
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "test" / "preflight.md"
PREFLIGHT_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "preflight.md"


def _run(phase_dir: Path, *extra: str):
    return subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _write_lifecycle(phase_dir: Path, goals: dict):
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": goals}), encoding="utf-8"
    )


def _write_variants_json(phase_dir: Path, goals: dict):
    (phase_dir / "EDGE-CASES").mkdir(parents=True, exist_ok=True)
    (phase_dir / "EDGE-CASES" / "VARIANTS.json").write_text(
        json.dumps({"phase": "7", "schema_version": "1.0", "source": "test",
                    "goals": goals}),
        encoding="utf-8",
    )


def _write_seed_recipe(phase_dir: Path, variant_ids: list):
    lines = ["# SEED-RECIPE\n"]
    for vid in variant_ids:
        lines.append(f"```yaml\nvariant_id: {vid}\n```\n")
    (phase_dir / "SEED-RECIPE.md").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(phase_dir: Path, goal_ids: list):
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [{"goal_id": g, "path": f"{g}.spec.ts"}
                                          for g in goal_ids]}),
        encoding="utf-8",
    )


def test_skip_when_lifecycle_absent(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    r = _run(pd, "--strict")
    assert r.returncode == 0  # skip gracefully


def test_pass_when_full_consistency(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {
        "edge_cases": [{"kind": "boundary"}],
        "negative_specs": [{"kind": "unauthorized_401"}],
    }})
    _write_variants_json(pd, {"G-01": [
        {"variant_id": "G-01-b1"}, {"variant_id": "G-01-n1"}
    ]})
    _write_seed_recipe(pd, ["G-01-b1", "G-01-n1"])
    r = _run(pd, "--strict")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_gap_when_variants_json_missing(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    # No VARIANTS.json
    r = _run(pd, "--strict")
    assert r.returncode != 0
    assert "VARIANTS.json" in (r.stderr + r.stdout)


def test_gap_when_seed_recipe_missing(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    _write_variants_json(pd, {"G-01": [{"variant_id": "G-01-b1"}]})
    # No SEED-RECIPE.md
    r = _run(pd, "--strict")
    assert r.returncode != 0
    assert "SEED-RECIPE" in (r.stderr + r.stdout)


def test_goal_without_variants_exempt(tmp_path):
    """Codex MAJOR fix: goal with no edge_cases/negative_specs → exempt
    from VARIANTS + SEED checks (VARIANTS.json optional per
    verify-variants-json:81-83)."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {
        "title": "Read-only goal with no variants",
        # No edge_cases, no negative_specs
    }})
    # No VARIANTS.json, no SEED-RECIPE → should still PASS
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_goal_with_infra_deps_exempt(tmp_path):
    """Goals with infra_deps tag are manual tests → exempt entirely."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {
        "edge_cases": [{"kind": "boundary"}],
        "source_assertions": {"infra_deps": "stripe-webhook-receiver"},
    }})
    # No VARIANTS, no SEED → would gap normally, but infra_deps exempts
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_manifest_gap_when_present(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    _write_variants_json(pd, {"G-01": [{"variant_id": "G-01-b1"}]})
    _write_seed_recipe(pd, ["G-01-b1"])
    # Manifest present but missing G-01
    _write_manifest(pd, ["G-99"])  # different goal
    r = _run(pd, "--strict")
    assert r.returncode != 0
    assert "CODEGEN-MANIFEST" in (r.stderr + r.stdout)


def test_manifest_absent_skips_check(tmp_path):
    """No CODEGEN-MANIFEST → don't gap on it (specs not yet generated)."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    _write_variants_json(pd, {"G-01": [{"variant_id": "G-01-b1"}]})
    _write_seed_recipe(pd, ["G-01-b1"])
    # No manifest at all
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_warn_mode_default(tmp_path):
    """Without --strict, gaps → exit 0 (advisory)."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    # Gap: no VARIANTS, no SEED
    r = _run(pd)  # NO --strict
    assert r.returncode == 0


def test_json_output_mode(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    _write_lifecycle(pd, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    r = _run(pd, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["phase"] == "7"
    assert "summary" in doc
    assert "gaps" in doc


def test_preflight_wires_strict_artifact_consistency():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "verify-test-artifact-consistency.py" in body
    assert "--strict-artifact-consistency" in body
    assert "B67" in body
    # Default warn (codex MAJOR)
    assert "ADVISORY" in body or "warn-only" in body.lower()


def test_mirrors_in_sync():
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    assert PREFLIGHT.read_text(encoding="utf-8") == PREFLIGHT_MIRROR.read_text(encoding="utf-8")
