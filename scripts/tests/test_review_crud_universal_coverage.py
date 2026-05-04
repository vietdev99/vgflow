"""R8-B — Universal CRUD round-trip coverage tests.

Codex audit (2026-05-05) found that the review layer's CRUD round-trip
dispatch was conditional on CRUD-SURFACES.md + `kit: crud-roundtrip`,
allowing mutation goals tagged `goal_class: crud-roundtrip` or
`lifecycle: rcrurdr` to slip through without lifecycle proof.

Coverage:

  Validator (scripts/validators/verify-crud-runs-coverage.py):
    1. test_dispatches_for_kit_crud_roundtrip — kit-declared path with
       valid run artifacts → PASS (back-compat preserved).
    2. test_dispatches_for_goal_class_crud_roundtrip — universal path 1:
       goal_class: crud-roundtrip + matching run artifact → PASS.
    3. test_dispatches_for_lifecycle_rcrurdr — universal path 2:
       lifecycle: rcrurdr inline yaml-rcrurd fence + matching run
       artifact → PASS.
    4. test_no_dispatch_for_non_mutation — read-only goal (no
       qualifying class/lifecycle) + no CRUD-SURFACES → PASS (no work
       expected, validator skips silently).
    5. test_blocks_when_qualifying_goal_has_no_run — qualifying mutation
       goal + empty runs/ dir → BLOCK (rc=1).
    6. test_collect_md_documents_universal_dispatch — assert
       commands/vg/_shared/review/findings/collect.md mentions all 3
       conditions (kit, goal_class, lifecycle).

Severity semantics (per validator main()):
  rc 0 → PASS (no gaps OR severity=warn)
  rc 1 → BLOCK (gap + severity=block)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-crud-runs-coverage.py"
COLLECT_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "findings" / "collect.md"
)


# ─── Helpers ──────────────────────────────────────────────────────────


def _run_validator(phase_dir: Path, *, severity: str = "block") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--phase-dir",
            str(phase_dir),
            "--severity",
            severity,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def _stage_phase(tmp_path: Path) -> Path:
    phase = tmp_path / "07.99-r8b-test"
    phase.mkdir(parents=True)
    (phase / "TEST-GOALS").mkdir()
    (phase / "runs").mkdir()
    return phase


def _write_test_goal(
    phase: Path,
    goal_id: str,
    *,
    goal_class: str | None = None,
    lifecycle: str | None = None,
    extra_body: str = "",
) -> Path:
    """Author a TEST-GOALS/G-NN.md with optional goal_class + yaml-rcrurd fence."""
    parts = [f"# {goal_id} — fixture\n\n"]
    if goal_class:
        parts.append(f"**goal_class:** {goal_class}\n\n")
    parts.append("**goal_type:** mutation\n\n")
    if lifecycle:
        parts.append(
            "## Read-after-write invariant\n\n"
            "```yaml-rcrurd\n"
            f"goal_id: {goal_id}\n"
            f"lifecycle: {lifecycle}\n"
            "lifecycle_phases:\n"
            "  - read_empty\n"
            "  - create\n"
            "  - read_populated\n"
            "  - update\n"
            "  - read_updated\n"
            "  - delete\n"
            "  - read_after_delete\n"
            "```\n\n"
        )
    if extra_body:
        parts.append(extra_body + "\n")
    target = phase / "TEST-GOALS" / f"{goal_id}.md"
    target.write_text("".join(parts), encoding="utf-8")
    return target


def _write_kit_run(phase: Path, resource: str, role: str) -> Path:
    """Stage a populated runs/<resource>-<role>.json that satisfies Path A."""
    body = {
        "resource": resource,
        "role": role,
        "coverage": {"attempted": 8, "completed": 8},
        "steps": [
            {"name": "read_empty",       "status": "pass", "evidence_ref": "ev/1.png"},
            {"name": "create",           "status": "pass", "evidence_ref": "ev/2.png"},
            {"name": "read_populated",   "status": "pass", "evidence_ref": "ev/3.png"},
            {"name": "update",           "status": "pass", "evidence_ref": "ev/4.png"},
            {"name": "read_updated",     "status": "pass", "evidence_ref": "ev/5.png"},
            {"name": "delete",           "status": "pass", "evidence_ref": "ev/6.png"},
            {"name": "read_after_delete","status": "pass", "evidence_ref": "ev/7.png"},
        ],
    }
    p = phase / "runs" / f"{resource}-{role}.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _write_crud_surfaces_kit(phase: Path, *, resource: str, roles: list[str]) -> Path:
    """Author CRUD-SURFACES.md with one resource declaring kit: crud-roundtrip."""
    surfaces = {
        "version": 1,
        "resources": [
            {
                "name": resource,
                "kit": "crud-roundtrip",
                "base": {"roles": roles},
            }
        ],
    }
    body = (
        "# CRUD Surfaces\n\n"
        "```json\n" + json.dumps(surfaces, indent=2) + "\n```\n"
    )
    p = phase / "CRUD-SURFACES.md"
    p.write_text(body, encoding="utf-8")
    return p


def _write_per_goal_run(phase: Path, goal_id: str) -> Path:
    """Stage a per-goal runs/<goal_id>.json artifact (Path B match)."""
    body = {
        "goal_id": goal_id,
        "coverage": {"attempted": 7, "completed": 7},
        "steps": [
            {"name": "read_empty", "status": "pass", "evidence_ref": "ev/a.png"},
        ],
    }
    p = phase / "runs" / f"{goal_id}.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _parse_payload(proc: subprocess.CompletedProcess) -> dict:
    # --json prints exactly one JSON document on stdout
    return json.loads(proc.stdout.strip())


# ─── Tests ────────────────────────────────────────────────────────────


def test_dispatches_for_kit_crud_roundtrip(tmp_path: Path) -> None:
    """Path A back-compat: kit-declared resource with valid run artifact PASSes."""
    phase = _stage_phase(tmp_path)
    _write_crud_surfaces_kit(phase, resource="campaign", roles=["admin"])
    _write_kit_run(phase, resource="campaign", role="admin")

    proc = _run_validator(phase)
    assert proc.returncode == 0, f"expected PASS, got rc={proc.returncode}: {proc.stdout}"
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is True
    assert payload["expected_runs"] == 1
    assert payload["gaps"] == []


def test_dispatches_for_goal_class_crud_roundtrip(tmp_path: Path) -> None:
    """Path B (R8-B path 1): goal_class: crud-roundtrip qualifies, run artifact PASSes."""
    phase = _stage_phase(tmp_path)
    # No CRUD-SURFACES.md — universal path must still detect this.
    _write_test_goal(phase, "G-07", goal_class="crud-roundtrip")
    _write_per_goal_run(phase, "G-07")

    proc = _run_validator(phase)
    assert proc.returncode == 0, f"expected PASS, got rc={proc.returncode}: {proc.stdout}"
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is True
    assert payload["universal_qualifying"] == 1
    assert payload["gaps"] == []


def test_dispatches_for_lifecycle_rcrurdr(tmp_path: Path) -> None:
    """Path B (R8-B path 2): lifecycle: rcrurdr in yaml-rcrurd fence qualifies."""
    phase = _stage_phase(tmp_path)
    _write_test_goal(phase, "G-12", lifecycle="rcrurdr")
    _write_per_goal_run(phase, "G-12")

    proc = _run_validator(phase)
    assert proc.returncode == 0, f"expected PASS, got rc={proc.returncode}: {proc.stdout}"
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is True
    assert payload["universal_qualifying"] == 1


def test_no_dispatch_for_non_mutation(tmp_path: Path) -> None:
    """Read-only goal (no goal_class / no lifecycle) — validator silently passes.

    No CRUD-SURFACES, no qualifying universal goals → no expected work,
    no gaps. This protects against false positives for read-only phases.
    """
    phase = _stage_phase(tmp_path)
    # Author a goal that does NOT qualify (no goal_class, no rcrurdr).
    _write_test_goal(phase, "G-01", extra_body="**goal_type:** readonly\n")

    proc = _run_validator(phase)
    assert proc.returncode == 0, f"expected PASS, got rc={proc.returncode}: {proc.stdout}"
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is True
    assert payload["universal_qualifying"] == 0
    assert payload["expected_runs"] == 0


def test_blocks_when_qualifying_goal_has_no_run(tmp_path: Path) -> None:
    """Qualifying mutation goal + empty runs/ dir → BLOCK (rc=1)."""
    phase = _stage_phase(tmp_path)
    _write_test_goal(phase, "G-21", goal_class="crud-roundtrip")
    # Deliberately do NOT write any run artifact for G-21.

    proc = _run_validator(phase, severity="block")
    assert proc.returncode == 1, (
        f"expected BLOCK (rc=1), got rc={proc.returncode}: {proc.stdout}"
    )
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is False
    gaps = payload["gaps"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["path_kind"] == "universal"
    assert gap["goal_id"] == "G-21"
    assert gap["reason"] == "universal_run_artifact_missing"
    assert "goal_class:crud-roundtrip" in gap["qualifies_via"]


def test_blocks_lifecycle_rcrurdr_without_run(tmp_path: Path) -> None:
    """lifecycle: rcrurdr without coverage also BLOCKs (path 2)."""
    phase = _stage_phase(tmp_path)
    _write_test_goal(phase, "G-30", lifecycle="rcrurdr")

    proc = _run_validator(phase, severity="block")
    assert proc.returncode == 1, (
        f"expected BLOCK (rc=1), got rc={proc.returncode}: {proc.stdout}"
    )
    payload = _parse_payload(proc)
    assert payload["gate_pass"] is False
    gap = payload["gaps"][0]
    assert "lifecycle:rcrurdr" in gap["qualifies_via"]


def test_collect_md_documents_universal_dispatch() -> None:
    """The dispatch logic in collect.md must mention all 3 conditions.

    R8-B (codex audit 2026-05-05): the universal CRUD round-trip
    dispatch broadens the condition. The user-readable doc must enumerate
    all 3 paths so reviewers and on-call don't misread the gate.
    """
    text = COLLECT_MD.read_text(encoding="utf-8")
    assert "R8-B" in text, "collect.md must cite R8-B for the audit trail"
    # Path 1 — kit-declared
    assert "kit: crud-roundtrip" in text
    # Path 2 — goal_class
    assert "goal_class: crud-roundtrip" in text
    # Path 3 — lifecycle: rcrurdr
    assert "lifecycle: rcrurdr" in text
    # Sanity: the runtime dispatch block sets all 3 flags
    assert "GOAL_CLASS_DECLARED" in text
    assert "LIFECYCLE_DECLARED" in text


def test_review_md_frontmatter_has_override_flag() -> None:
    """commands/vg/review.md frontmatter must list --skip-crud-coverage-universal."""
    review_md = REPO_ROOT / "commands" / "vg" / "review.md"
    text = review_md.read_text(encoding="utf-8")
    assert "--skip-crud-coverage-universal" in text, (
        "Override flag must be allowlisted in review.md forbidden_without_override"
    )


# ─── Sanity: validator file is wired into verdict overview (no logic change) ──


def test_verdict_overview_includes_validator() -> None:
    """The validator was already wired in 2.35.0; this guards against accidental removal."""
    overview = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "verdict" / "overview.md"
    text = overview.read_text(encoding="utf-8")
    assert "verify-crud-runs-coverage" in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
