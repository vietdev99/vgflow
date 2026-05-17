"""tests/test_batch70c_legacy_pipeline_state_migration.py

B70c — verdict-aware migration backfill for legacy phases pre-v4.61.0.

Closes B69 fix gap: phases whose review was closed under v4.40.0 carry
REVIEW.md + RUNTIME-MAP.json on disk but PIPELINE-STATE.json missing
steps.review subkey and (often) next_command. This script scans
.vg/phases/*/, parses GOAL-COVERAGE-MATRIX.{json,md} for verdict, and
writes the schema that B70a now emits.

Codex audit fixes addressed:
  - B-3 schema parity     : test schema matches review/close.md write keys
  - B-4 race avoidance    : skip phase without review/complete.done marker
                            when no fallback artifact pair present
  - B-5 verdict awareness : BLOCK verdict → next_command=None
  - B-6 semver compare    : version gate uses Python tuple compare
  - M-1/M-2 false-positives: artifact pair guard tested

Test coverage:
  1. Skip — phase with no REVIEW.md (review not closed).
  2. Backfill — phase with REVIEW.md + RUNTIME-MAP.json + no PIPELINE-STATE.
  3. Backfill — phase with PIPELINE-STATE.json but no steps.review.
  4. Skip — phase with steps.review already present.
  5. Verdict PASS from matrix.json → next_command=/vg:test-spec NN.
  6. Verdict BLOCK from matrix.md → next_command=None.
  7. Verdict STATIC-READY mapped to TEST_PENDING (legacy strings).
  8. Verdict UNKNOWN → next_command=/vg:test-spec (forward motion).
  9. --dry-run does not write file.
 10. --phase filter only touches matching dir.
 11. Idempotent — second run = no backfill.
 12. Phase number unparseable → graceful skip.
 13. State file unparseable (corrupted JSON) → backfilled.
 14. Migration writes backfilled_at / backfilled_by provenance.
 15. .step-markers/review/complete.done sentinel preferred over artifact pair.
 16. Script importable + main() exit 0 on empty planning dir = 1 (not exists).
 17. Schema matches review/close.md write contract (steps.review keys).
 18. Mirror: script lives in scripts/migrations/ (no .claude/ mirror needed).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "migrations" / "v4.61.0_backfill_pipeline_state.py"

# Load the migration module so we can call its functions directly.
spec = importlib.util.spec_from_file_location("v4_61_backfill", SCRIPT)
mig = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(mig)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


def _make_phase(tmp_path: Path, name: str, *,
                review_md: bool = False,
                runtime_map: bool = False,
                pipeline_state: dict | None = None,
                matrix_md_verdict: str | None = None,
                matrix_json_gate: str | None = None,
                review_complete_marker: bool = False,
                corrupt_state: bool = False) -> Path:
    phase = tmp_path / name
    phase.mkdir(parents=True, exist_ok=True)
    if review_md:
        (phase / "REVIEW.md").write_text("# REVIEW\n", encoding="utf-8")
    if runtime_map:
        (phase / "RUNTIME-MAP.json").write_text("{}", encoding="utf-8")
    if pipeline_state is not None:
        (phase / "PIPELINE-STATE.json").write_text(json.dumps(pipeline_state), encoding="utf-8")
    if corrupt_state:
        (phase / "PIPELINE-STATE.json").write_text("{not-json", encoding="utf-8")
    if matrix_md_verdict is not None:
        (phase / "GOAL-COVERAGE-MATRIX.md").write_text(
            f"# Matrix\n\n**Phase {name.split('-')[0]} review verdict: {matrix_md_verdict}**\n",
            encoding="utf-8",
        )
    if matrix_json_gate is not None:
        (phase / "GOAL-COVERAGE-MATRIX.json").write_text(
            json.dumps({"gate": matrix_json_gate}),
            encoding="utf-8",
        )
    if review_complete_marker:
        marker_dir = phase / ".step-markers" / "review"
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "complete.done").write_text("done", encoding="utf-8")
    return phase


# ---------------------------------------------------------------------------
# 1-2 — basic skip + basic backfill.
# ---------------------------------------------------------------------------


def test_b70c_skip_phase_without_review(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    _make_phase(planning, "1-empty")
    rc = mig.main(["--planning-dir", str(planning), "--quiet"])
    assert rc == 0
    assert not (planning / "1-empty" / "PIPELINE-STATE.json").exists()


def test_b70c_backfill_missing_state(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "7.16-foo",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="PASS",
    )
    rc = mig.main(["--planning-dir", str(planning), "--quiet"])
    assert rc == 0
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["status"] == "done"
    assert state["steps"]["review"]["verdict"] == "PASS"
    assert state["next_command"] == "/vg:test-spec 7.16"


# ---------------------------------------------------------------------------
# 3-4 — incremental backfill + idempotency.
# ---------------------------------------------------------------------------


def test_b70c_backfill_state_without_steps_review(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "5-existing",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="PASS",
        pipeline_state={"steps": {"test-spec": {"status": "done"}}, "next_command": None},
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert "review" in state["steps"]
    assert state["steps"]["review"]["verdict"] == "PASS"
    # Existing test-spec key preserved.
    assert state["steps"]["test-spec"]["status"] == "done"


def test_b70c_idempotent_skip_when_steps_review_present(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    pre_state = {
        "steps": {"review": {"status": "done", "verdict": "PASS", "finished_at": "2026-05-17"}},
        "next_command": "/vg:test-spec 5",
    }
    phase = _make_phase(
        planning,
        "5-done",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="PASS",
        pipeline_state=pre_state,
    )
    before_mtime = (phase / "PIPELINE-STATE.json").stat().st_mtime
    mig.main(["--planning-dir", str(planning), "--quiet"])
    after_mtime = (phase / "PIPELINE-STATE.json").stat().st_mtime
    # Idempotent — file unchanged.
    assert before_mtime == after_mtime


# ---------------------------------------------------------------------------
# 5-8 — verdict parsing variants.
# ---------------------------------------------------------------------------


def test_b70c_verdict_pass_from_matrix_json(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "3-jsonpass",
        review_md=True,
        runtime_map=True,
        matrix_json_gate="PASS",
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "PASS"
    assert state["next_command"] == "/vg:test-spec 3"
    assert state["backfilled_verdict_source"] == "matrix.json"


def test_b70c_verdict_block_disables_next_command(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "4-block",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="BLOCK",
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "BLOCK"
    assert state["next_command"] is None
    assert "next_command_blocked_reason" in state


def test_b70c_verdict_static_ready_maps_to_test_pending(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "6-static",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="STATIC-READY",
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "TEST_PENDING"
    assert state["next_command"] == "/vg:test-spec 6"


def test_b70c_verdict_unknown_still_emits_test_spec(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "8-noverdict",
        review_md=True,
        runtime_map=True,
        # No matrix.json or matrix.md → verdict UNKNOWN
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "UNKNOWN"
    # UNKNOWN errs toward forward motion (matches B70a behavior).
    assert state["next_command"] == "/vg:test-spec 8"


# ---------------------------------------------------------------------------
# 9-12 — CLI behaviors.
# ---------------------------------------------------------------------------


def test_b70c_dry_run_does_not_write(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(planning, "9-dry", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    mig.main(["--planning-dir", str(planning), "--quiet", "--dry-run"])
    assert not (phase / "PIPELINE-STATE.json").exists()


def test_b70c_phase_filter(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    p1 = _make_phase(planning, "7.16-target", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    p2 = _make_phase(planning, "8-skip", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    mig.main(["--planning-dir", str(planning), "--quiet", "--phase", "7.16"])
    assert (p1 / "PIPELINE-STATE.json").exists()
    assert not (p2 / "PIPELINE-STATE.json").exists()


def test_b70c_phase_number_unparseable_skipped(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(planning, "weird-no-number", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    rc = mig.main(["--planning-dir", str(planning), "--quiet"])
    assert rc == 0
    assert not (phase / "PIPELINE-STATE.json").exists()


def test_b70c_corrupt_state_recovered(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(
        planning,
        "5-corrupt",
        review_md=True,
        runtime_map=True,
        matrix_md_verdict="PASS",
        corrupt_state=True,
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    # After backfill, file should be valid JSON.
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 13-15 — schema + provenance + sentinel preference.
# ---------------------------------------------------------------------------


def test_b70c_provenance_keys_present(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(planning, "5-prov", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["backfilled_by"] == "v4.61.0_backfill_pipeline_state.py"
    assert "backfilled_at" in state
    assert state["backfilled_verdict_source"] in ("matrix.json", "matrix.md")


def test_b70c_schema_matches_review_close_contract(tmp_path: Path):
    """Schema parity: backfill writes the SAME steps.review keys that
    commands/vg/_shared/review/close.md B70a fix block writes."""
    planning = tmp_path / "phases"
    planning.mkdir()
    phase = _make_phase(planning, "5-schema", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    sr = state["steps"]["review"]
    # Required keys (must match B70a block in review/close.md).
    assert "status" in sr and sr["status"] == "done"
    assert "verdict" in sr
    assert "finished_at" in sr
    # PASS-class verdicts also embed next_command in steps.review.
    assert sr.get("next_command") == "/vg:test-spec 5"


def test_b70c_review_complete_marker_preferred_over_artifact_pair(tmp_path: Path):
    """When .step-markers/review/complete.done exists, that's the
    authoritative review-closed signal (B70c audit B-4 fix). Even if
    REVIEW.md or RUNTIME-MAP.json is absent (legacy migration window),
    the marker still proves closure."""
    planning = tmp_path / "phases"
    planning.mkdir()
    # Phase with ONLY the marker (no REVIEW.md/RUNTIME-MAP.json).
    phase = _make_phase(
        planning,
        "11-marker-only",
        review_complete_marker=True,
        matrix_md_verdict="PASS",
    )
    mig.main(["--planning-dir", str(planning), "--quiet"])
    state = json.loads((phase / "PIPELINE-STATE.json").read_text(encoding="utf-8"))
    assert state["steps"]["review"]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 16-18 — CLI exit + script presence + script invocability.
# ---------------------------------------------------------------------------


def test_b70c_planning_dir_not_found_exits_1(tmp_path: Path):
    rc = mig.main(["--planning-dir", str(tmp_path / "nonexistent"), "--quiet"])
    assert rc == 1


def test_b70c_script_present_and_executable():
    assert SCRIPT.is_file()
    body = SCRIPT.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env python3")
    assert "B70c" in body or "v4.61.0_backfill" in body


def test_b70c_subprocess_invocation(tmp_path: Path):
    planning = tmp_path / "phases"
    planning.mkdir()
    _make_phase(planning, "12-sub", review_md=True, runtime_map=True, matrix_md_verdict="PASS")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--planning-dir", str(planning), "--quiet"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


# ---------------------------------------------------------------------------
# 19-20 — session-start hook auto-invoke wiring (text inspection only).
# ---------------------------------------------------------------------------


def test_b70c_session_start_hook_invokes_migration():
    hook = REPO / "scripts" / "hooks" / "vg-session-start.sh"
    body = hook.read_text(encoding="utf-8")
    assert "v4.61.0_backfill_pipeline_state.py" in body
    assert "B70c" in body


def test_b70c_session_start_hook_uses_python_semver_compare():
    hook = REPO / "scripts" / "hooks" / "vg-session-start.sh"
    body = hook.read_text(encoding="utf-8")
    # Python tuple parse + compare (NOT bash `>` string compare per B-6).
    assert "tuple(int(p) for p in parts" in body
    # Insert position is BEFORE the printf JSON output (per audit m-7).
    printf_idx = body.find('printf \'{\\n  "hookSpecificOutput"')
    mig_idx = body.find("v4.61.0_backfill_pipeline_state.py")
    assert mig_idx > 0 and printf_idx > 0
    assert mig_idx < printf_idx, "migration block must precede JSON printf to avoid stdout contamination"
