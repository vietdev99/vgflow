"""tests/test_batch58_scan_goal_coverage.py — Batch 58.

verify-scan-goal-coverage.py: every scan filter/sort/pagination/
search/state_observation/a11y signal must have a matching goal id
in TEST-GOALS.md / TEST-GOALS-DISCOVERED.md / LIFECYCLE-SPECS.

Existing enrich --validate-only checks view-level coverage (any
elements scanned must have any goals derived). This deeper validator
checks per-signal: scan saw filter X, goal id must contain
`-filter-{slug}` OR `interactive_controls.filters[].name` matches.

Coverage:
  1. Pass: filter Status + matching G-AUTO-*-filter-status goal
  2. Fail strict: filter Status + no matching goal
  3. Pass: sort Name + matching G-AUTO-*-sort-name goal
  4. Pass: pagination present + any -pagination-* goal
  5. Fail strict: pagination present + no pagination goal
  6. Pass: state_observations.empty_state + -empty-state goal
  7. Pass: a11y findings + -a11y-* goal
  8. Pass via interactive_controls.filters name match
  9. No scans → exit 0 (skip)
  10. No goals + scans present → exit 1 strict
  11. Threshold: warn-mode below threshold, fail above
  12. Review lens-and-findings.md wires validator
  13. Mirror parity
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-scan-goal-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-scan-goal-coverage.py"
LENS = REPO / "commands" / "vg" / "_shared" / "review" / "lens-and-findings.md"
LENS_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "lens-and-findings.md"


def _setup(tmp_path: Path, scan: dict, goals_md: str = "",
           lifecycle: dict | None = None) -> Path:
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "scan-x.json").write_text(
        json.dumps({"view": "/x", **scan}), encoding="utf-8"
    )
    if goals_md:
        (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    if lifecycle:
        (phase_dir / "LIFECYCLE-SPECS.json").write_text(
            json.dumps(lifecycle), encoding="utf-8"
        )
    return phase_dir


def _run(phase_dir: Path, *extra: str):
    return subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), *extra],
        capture_output=True, text=True,
    )


def test_filter_matched_by_goal_id(tmp_path):
    pd = _setup(tmp_path,
                {"filters": [{"name": "Status", "options": ["a"]}]},
                "## G-AUTO-x-filter-status\nFilter status\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_filter_unmatched_fails_strict(tmp_path):
    pd = _setup(tmp_path,
                {"filters": [{"name": "Status", "options": ["a"]}]},
                "## G-01\nUnrelated\n")
    r = _run(pd, "--strict")
    assert r.returncode != 0
    assert "Status" in (r.stderr + r.stdout)


def test_sort_matched_by_goal_id(tmp_path):
    pd = _setup(tmp_path,
                {"sort_headers": [{"column": "Name"}]},
                "## G-AUTO-x-sort-name\nSort name\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_pagination_matched(tmp_path):
    pd = _setup(tmp_path,
                {"pagination": {"present": True, "total_pages": 3}},
                "## G-AUTO-x-pagination-full\nPagination\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_pagination_unmatched_fails_strict(tmp_path):
    pd = _setup(tmp_path,
                {"pagination": {"present": True, "total_pages": 3}},
                "## G-01\nUnrelated\n")
    r = _run(pd, "--strict")
    assert r.returncode != 0
    assert "pagination" in (r.stderr + r.stdout).lower()


def test_empty_state_matched(tmp_path):
    pd = _setup(tmp_path,
                {"state_observations": {"empty_state": {"observed": True}}},
                "## G-AUTO-x-empty-state\nEmpty\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_a11y_matched(tmp_path):
    pd = _setup(tmp_path,
                {"accessibility_findings": [{"rule": "color-contrast"}]},
                "## G-AUTO-x-a11y-color-contrast\nA11y\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_filter_matched_by_interactive_controls(tmp_path):
    """Goal declares interactive_controls.filters[].name even if id mismatches."""
    pd = _setup(tmp_path,
                {"filters": [{"name": "Owner", "options": None}]},
                "## G-01 — Manage\n\n```yaml\ninteractive_controls:\n"
                "  filters:\n    - name: Owner\n      kind: combobox\n```\n")
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_no_scans_skip_clean(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    r = _run(phase_dir, "--strict")
    assert r.returncode == 0


def test_no_goals_with_scans_fails_strict(tmp_path):
    pd = _setup(tmp_path, {"filters": [{"name": "X"}]}, "")
    r = _run(pd, "--strict")
    assert r.returncode != 0


def test_threshold_warn_mode_below(tmp_path):
    """Below threshold gaps → warn-mode (exit 0)."""
    pd = _setup(tmp_path,
                {"filters": [{"name": "X"}, {"name": "Y"}]},
                "## G-01\nNo match\n")
    # threshold=5, 2 gaps → warn
    r = _run(pd, "--strict", "--threshold", "5")
    assert r.returncode == 0


def test_threshold_strict_above(tmp_path):
    pd = _setup(tmp_path,
                {"filters": [{"name": "X"}, {"name": "Y"}]},
                "## G-01\nNo match\n")
    # threshold=1, 2 gaps → fail (gaps > threshold)
    r = _run(pd, "--strict", "--threshold", "1")
    assert r.returncode != 0


def test_review_wires_validator():
    body = LENS.read_text(encoding="utf-8")
    assert "verify-scan-goal-coverage.py" in body
    assert "--strict-scan-goal-coverage" in body
    assert "review_phase2c_scan_goal_gap" in body


def test_lifecycle_goals_count_too(tmp_path):
    """LIFECYCLE-SPECS goals counted as coverage source."""
    pd = _setup(tmp_path,
                {"filters": [{"name": "Status"}]},
                "",
                lifecycle={"goals": {"G-AUTO-x-filter-status": {"title": "f"}}})
    r = _run(pd, "--strict")
    assert r.returncode == 0


def test_mirrors_in_sync():
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    assert LENS.read_text(encoding="utf-8") == LENS_MIRROR.read_text(encoding="utf-8")
