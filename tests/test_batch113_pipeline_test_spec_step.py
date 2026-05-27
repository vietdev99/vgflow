"""B113 v4.72.2 — fix review→test pipeline drift, add test-spec step.

User report (2026-05-28): /vg:next suggested /vg:test directly after
/vg:review, skipping /vg:test-spec. Orchestrator _PIPELINE_FLIP_MAP
(scripts/vg-orchestrator/__main__.py:1424-1425) correctly lists
test-spec between review and test, but vg-progress.py + phase.md +
vg-meta-skill.md + verify-command-contract-coverage.py + vg-planner.md
all carried stale 7-element step arrays that omitted test-spec → next
command + step counters wrong.

Fix: add `test-spec` to every step array. vg-progress.py also gains a
dedicated `test-spec` result with LIFECYCLE-SPECS.json +
CODEGEN-MANIFEST.json detection, and a `test-spec` slot in the
next_cmd_map.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def progress():
    spec = importlib.util.spec_from_file_location(
        "vg_progress", REPO_ROOT / "scripts" / "vg-progress.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# vg-progress.py
# ---------------------------------------------------------------------------

def test_b113_progress_step_order_includes_test_spec(progress) -> None:
    """All step_order arrays must include 'test-spec' between review + test."""
    body = (REPO_ROOT / "scripts" / "vg-progress.py").read_text(encoding="utf-8")
    # Should appear in every step array — count occurrences
    pattern = (
        r'\["specs", "scope", "blueprint", "build", "review", '
        r'"test-spec", "test", "accept"\]'
    )
    matches = re.findall(pattern, body)
    assert len(matches) >= 4, (
        f"Expected ≥4 step_order arrays with test-spec, got {len(matches)}"
    )
    # Old form must be gone
    old_pattern = (
        r'\["specs", "scope", "blueprint", "build", "review", '
        r'"test", "accept"\]'
    )
    assert not re.search(old_pattern, body), (
        "Old 7-element step_order (without test-spec) still present"
    )


def test_b113_progress_next_cmd_map_has_test_spec(progress) -> None:
    body = (REPO_ROOT / "scripts" / "vg-progress.py").read_text(encoding="utf-8")
    assert '"test-spec": f"/vg:test-spec {phase_num}"' in body


def test_b113_progress_emits_test_spec_step_when_artifacts_present(
    progress, tmp_path: Path
) -> None:
    """Phase with LIFECYCLE-SPECS.json + CODEGEN-MANIFEST.json → test-spec=done."""
    phase = tmp_path / "08.2-x"
    phase.mkdir()
    (phase / "SPECS.md").write_text("x", encoding="utf-8")
    (phase / "CONTEXT.md").write_text("x", encoding="utf-8")
    (phase / "PLAN.md").write_text("x", encoding="utf-8")
    (phase / "API-CONTRACTS.md").write_text("x", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text("x", encoding="utf-8")
    (phase / "SUMMARY.md").write_text("x", encoding="utf-8")
    (phase / "RUNTIME-MAP.json").write_text(
        json.dumps({"routes": []}), encoding="utf-8"
    )
    (phase / "GOAL-COVERAGE-MATRIX.md").write_text(
        "Ready: 5 | Blocked: 0 | Unreachable: 0\n", encoding="utf-8"
    )
    (phase / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {}}), encoding="utf-8"
    )
    (phase / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": []}), encoding="utf-8"
    )
    summary = progress.scan_phase(phase)
    steps = summary["steps"]
    assert "test-spec" in steps, "test-spec step missing from progress output"
    assert steps["test-spec"]["status"] == "done", (
        f"Expected done with both artifacts, got {steps['test-spec']}"
    )


def test_b113_progress_test_spec_pending_when_missing(
    progress, tmp_path: Path
) -> None:
    phase = tmp_path / "08.2-x"
    phase.mkdir()
    (phase / "SPECS.md").write_text("x", encoding="utf-8")
    summary = progress.scan_phase(phase)
    assert summary["steps"]["test-spec"]["status"] == "pending"


def test_b113_progress_test_spec_partial_when_one_artifact(
    progress, tmp_path: Path
) -> None:
    phase = tmp_path / "08.2-x"
    phase.mkdir()
    (phase / "SPECS.md").write_text("x", encoding="utf-8")
    (phase / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {}}), encoding="utf-8"
    )
    # No CODEGEN-MANIFEST.json
    summary = progress.scan_phase(phase)
    assert summary["steps"]["test-spec"]["status"] == "in_progress"


def test_b113_progress_next_cmd_after_review_is_test_spec(
    progress, tmp_path: Path
) -> None:
    """When review done but test-spec missing, next_cmd should be /vg:test-spec."""
    phase = tmp_path / "08.2-x"
    phase.mkdir()
    (phase / "SPECS.md").write_text("x", encoding="utf-8")
    (phase / "CONTEXT.md").write_text("x", encoding="utf-8")
    (phase / "PLAN.md").write_text("x", encoding="utf-8")
    (phase / "API-CONTRACTS.md").write_text("x", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text("x", encoding="utf-8")
    (phase / "SUMMARY.md").write_text("x", encoding="utf-8")
    (phase / "RUNTIME-MAP.json").write_text("{}", encoding="utf-8")
    (phase / "GOAL-COVERAGE-MATRIX.md").write_text(
        "Ready: 5 | Blocked: 0 | Unreachable: 0\n", encoding="utf-8"
    )
    # NO LIFECYCLE-SPECS.json — test-spec is the current step
    summary = progress.scan_phase(phase)
    assert "/vg:test-spec" in summary["next_command"], (
        f"Expected next=/vg:test-spec, got {summary['next_command']}"
    )


# ---------------------------------------------------------------------------
# Other surfaces
# ---------------------------------------------------------------------------

def test_b113_phase_md_valid_steps_includes_test_spec() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "phase.md").read_text(encoding="utf-8")
    assert "Valid step names: `specs`, `scope`, `blueprint`, `build`, `review`, `test-spec`, `test`, `accept`" in body


def test_b113_vg_meta_skill_pipeline_string_has_test_spec() -> None:
    body = (REPO_ROOT / "scripts" / "hooks" / "vg-meta-skill.md").read_text(encoding="utf-8")
    assert "test-spec, test, accept" in body


def test_b113_validator_known_mutating_includes_test_spec() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "verify-command-contract-coverage.py").read_text(encoding="utf-8")
    assert '"specs", "scope", "blueprint", "build", "review", "test-spec", "test", "accept"' in body


def test_b113_vg_planner_pipeline_string_has_test_spec() -> None:
    body = (REPO_ROOT / "agents" / "vg-planner.md").read_text(encoding="utf-8")
    assert "review → test-spec → test → accept" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "scripts/vg-progress.py",
    "commands/vg/phase.md",
    "agents/vg-planner.md",
    "scripts/hooks/vg-meta-skill.md",
    "scripts/validators/verify-command-contract-coverage.py",
])
def test_b113_mirror_parity(rel: str) -> None:
    a = (REPO_ROOT / rel).read_bytes()
    b = (REPO_ROOT / ".claude" / rel).read_bytes()
    assert a == b, f"Mirror drift on {rel}"
