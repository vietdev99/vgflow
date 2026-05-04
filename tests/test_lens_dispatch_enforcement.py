"""Tests for Task 26 lens dispatch enforcement (core deliverables)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EMITTER = REPO / "scripts" / "lens-dispatch" / "emit-dispatch-plan.py"
COVERAGE_GATE = REPO / "scripts" / "validators" / "verify-lens-runs-coverage.py"
TRACE_GATE = REPO / "scripts" / "validators" / "verify-lens-action-trace.py"
MATRIX = REPO / "scripts" / "aggregators" / "lens-coverage-matrix.py"


def _make_phase(tmp_path: Path) -> Path:
    """Create a phase dir with TEST-GOALS/G-04.md (mutation goal)."""
    phase = tmp_path / "phase"
    goals = phase / "TEST-GOALS"
    goals.mkdir(parents=True)
    (goals / "G-04.md").write_text(textwrap.dedent("""
        # G-04
        **goal_type:** mutation
        **element_class:** form
    """).strip(), encoding="utf-8")
    return phase


def _make_lens_dir(tmp_path: Path) -> Path:
    """Create a synthetic lens-prompts dir with one form-lifecycle lens."""
    ld = tmp_path / "lens-prompts"
    ld.mkdir()
    (ld / "lens-form-lifecycle.md").write_text(textwrap.dedent("""
        ---
        name: lens-form-lifecycle
        bug_class: state-coherence
        applies_to_element_classes: [form]
        applies_to_phase_profiles: [web-fullstack]
        recommended_worker_tier: sonnet
        worker_complexity_score: 4
        fallback_on_inconclusive: opus
        estimated_action_budget: 25
        min_actions_floor: 8
        min_evidence_steps: 5
        required_probe_kinds: [create_then_read, update_then_read]
        ---

        Lens body unused in tests.
    """).strip(), encoding="utf-8")
    return ld


def test_emit_plan_produces_canonical_hash(tmp_path: Path) -> None:
    """emit-dispatch-plan output validates + has stable plan_hash."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    out = phase / "LENS-DISPATCH-PLAN.json"
    result = subprocess.run([
        "python3", str(EMITTER),
        "--phase-dir", str(phase),
        "--phase", "test-1.0",
        "--profile", "web-fullstack",
        "--review-run-id", "review-test-1",
        "--lens-dir", str(lens_dir),
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["review_run_id"] == "review-test-1"
    assert plan["phase"] == "test-1.0"
    assert len(plan["plan_hash"]) >= 16
    assert len(plan["dispatches"]) == 1
    d = plan["dispatches"][0]
    assert d["lens"] == "lens-form-lifecycle"
    assert d["goal_id"] == "G-04"
    assert d["applicability_status"] == "APPLICABLE"
    assert d["worker_tier"] == "sonnet"
    assert d["min_actions_floor"] == 8


def test_emit_plan_hash_deterministic(tmp_path: Path) -> None:
    """Same input produces same plan_hash (round-trip stability)."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    out1 = tmp_path / "p1.json"
    out2 = tmp_path / "p2.json"
    for o in (out1, out2):
        subprocess.run([
            "python3", str(EMITTER),
            "--phase-dir", str(phase),
            "--phase", "test-1.0",
            "--profile", "web-fullstack",
            "--review-run-id", "review-x",
            "--lens-dir", str(lens_dir),
            "--output", str(o),
        ], capture_output=True, text=True, check=True)
    h1 = json.loads(out1.read_text(encoding="utf-8"))["plan_hash"]
    h2 = json.loads(out2.read_text(encoding="utf-8"))["plan_hash"]
    assert h1 == h2


def test_coverage_gate_blocks_missing_artifact(tmp_path: Path) -> None:
    """APPLICABLE dispatch without artifact → BLOCK."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    plan_path = phase / "LENS-DISPATCH-PLAN.json"
    subprocess.run([
        "python3", str(EMITTER),
        "--phase-dir", str(phase),
        "--phase", "test-1.0",
        "--profile", "web-fullstack",
        "--review-run-id", "review-block",
        "--lens-dir", str(lens_dir),
        "--output", str(plan_path),
    ], check=True, capture_output=True, text=True)
    runs_dir = phase / "runs"
    runs_dir.mkdir()
    ev = phase / "coverage-evidence.json"
    result = subprocess.run([
        "python3", str(COVERAGE_GATE),
        "--dispatch-plan", str(plan_path),
        "--runs-dir", str(runs_dir),
        "--phase", "test-1.0",
        "--evidence-out", str(ev),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    summary = json.loads(ev.read_text(encoding="utf-8"))
    assert summary["totals"]["block"] == 1
    assert any("missing" in i.lower() for r in summary["results"] for i in r["issues"])


def test_coverage_gate_passes_with_valid_artifact(tmp_path: Path) -> None:
    """All structural checks pass when artifact matches plan."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    plan_path = phase / "LENS-DISPATCH-PLAN.json"
    subprocess.run([
        "python3", str(EMITTER),
        "--phase-dir", str(phase),
        "--phase", "test-1.0",
        "--profile", "web-fullstack",
        "--review-run-id", "review-pass",
        "--lens-dir", str(lens_dir),
        "--output", str(plan_path),
    ], check=True, capture_output=True, text=True)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_hash = plan["plan_hash"]
    runs_dir = phase / "runs" / "lens-form-lifecycle"
    runs_dir.mkdir(parents=True)
    artifact_path = runs_dir / "G-04.json"
    artifact_path.write_text(json.dumps({
        "plan_hash": plan_hash,
        "lens": "lens-form-lifecycle",
        "goal_id": "G-04",
        "actions_taken": 12,
        "steps": [
            {"name": "create_then_read", "evidence_ref": "ev-1"},
            {"name": "update_then_read", "evidence_ref": "ev-2"},
            {"name": "delete_then_read", "evidence_ref": "ev-3"},
            {"name": "verify_state", "evidence_ref": "ev-4"},
            {"name": "audit_log_check", "evidence_ref": "ev-5"},
        ],
    }), encoding="utf-8")
    result = subprocess.run([
        "python3", str(COVERAGE_GATE),
        "--dispatch-plan", str(plan_path),
        "--runs-dir", str(phase / "runs"),
        "--phase", "test-1.0",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_coverage_gate_detects_plan_hash_reuse(tmp_path: Path) -> None:
    """Artifact with stale plan_hash (reused from prior run) → BLOCK."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    plan_path = phase / "LENS-DISPATCH-PLAN.json"
    subprocess.run([
        "python3", str(EMITTER),
        "--phase-dir", str(phase),
        "--phase", "test-1.0",
        "--profile", "web-fullstack",
        "--review-run-id", "review-pass",
        "--lens-dir", str(lens_dir),
        "--output", str(plan_path),
    ], check=True, capture_output=True, text=True)
    runs_dir = phase / "runs" / "lens-form-lifecycle"
    runs_dir.mkdir(parents=True)
    (runs_dir / "G-04.json").write_text(json.dumps({
        "plan_hash": "deadbeef" * 4,
        "lens": "lens-form-lifecycle",
        "goal_id": "G-04",
        "actions_taken": 12,
        "steps": [{"name": "x", "evidence_ref": "e"}] * 6,
    }), encoding="utf-8")
    result = subprocess.run([
        "python3", str(COVERAGE_GATE),
        "--dispatch-plan", str(plan_path),
        "--runs-dir", str(phase / "runs"),
        "--phase", "test-1.0",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "plan_hash" in result.stderr


def test_tier_dispatcher_complexity_4_blocks_haiku() -> None:
    """complexity_score=4 with recommended haiku → upgraded to sonnet."""
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from lens_tier_dispatcher import select_tier  # type: ignore

    fm = {"recommended_worker_tier": "haiku", "worker_complexity_score": 4}
    t = select_tier(fm, project_cost_caps={})
    assert t.tier == "sonnet"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_tier_dispatcher_complexity_5_forces_opus() -> None:
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from lens_tier_dispatcher import select_tier  # type: ignore

    fm = {"recommended_worker_tier": "sonnet", "worker_complexity_score": 5}
    t = select_tier(fm, project_cost_caps={})
    assert t.tier == "opus"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_tier_dispatcher_cost_cap_triggers_override(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from lens_tier_dispatcher import select_tier  # type: ignore

    fm = {"recommended_worker_tier": "opus", "worker_complexity_score": 5}
    caps = {"used_opus": 5, "max_opus_per_phase": 5}
    t = select_tier(fm, project_cost_caps=caps)
    assert t.override_required is True
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_action_trace_blocks_on_drift(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps({
        "run_id": "run-X",
        "actions_taken": 8,
    }), encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("\n".join(json.dumps({
        "run_id": "run-X", "tool": "browser_click",
    }) for _ in range(2)), encoding="utf-8")
    ev_out = tmp_path / "ev.json"
    result = subprocess.run([
        "python3", str(TRACE_GATE),
        "--artifact", str(artifact_path),
        "--mcp-trace", str(trace_path),
        "--tolerance", "2",
        "--evidence-out", str(ev_out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    ev = json.loads(ev_out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert ev["category"] == "lens_action_trace_mismatch"


def test_action_trace_passes_within_tolerance(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps({
        "run_id": "run-Y", "actions_taken": 8,
    }), encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("\n".join(json.dumps({
        "run_id": "run-Y", "tool": "browser_click",
    }) for _ in range(9)), encoding="utf-8")
    result = subprocess.run([
        "python3", str(TRACE_GATE),
        "--artifact", str(artifact_path),
        "--mcp-trace", str(trace_path),
        "--tolerance", "2",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0


def test_action_trace_missing_default_advisory(tmp_path: Path) -> None:
    """Missing trace + mcp_trace_required=false → exit 0 (advisory)."""
    artifact_path = tmp_path / "a.json"
    artifact_path.write_text(json.dumps({"run_id": "z", "actions_taken": 5}), encoding="utf-8")
    result = subprocess.run([
        "python3", str(TRACE_GATE),
        "--artifact", str(artifact_path),
        "--mcp-trace", str(tmp_path / "absent.jsonl"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0


def test_matrix_renders_all_status_columns(tmp_path: Path) -> None:
    """Matrix renderer produces table + footnotes for non-PASS cells."""
    phase = _make_phase(tmp_path)
    lens_dir = _make_lens_dir(tmp_path)
    plan_path = phase / "LENS-DISPATCH-PLAN.json"
    subprocess.run([
        "python3", str(EMITTER),
        "--phase-dir", str(phase),
        "--phase", "test-1.0",
        "--profile", "web-fullstack",
        "--review-run-id", "review-mat",
        "--lens-dir", str(lens_dir),
        "--output", str(plan_path),
    ], check=True, capture_output=True, text=True)
    out = phase / "LENS-COVERAGE-MATRIX.md"
    result = subprocess.run([
        "python3", str(MATRIX),
        "--dispatch-plan", str(plan_path),
        "--runs-dir", str(phase / "runs"),
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    md = out.read_text(encoding="utf-8")
    assert "Lens Coverage Matrix" in md
    assert "lens-form-lifecycle" in md
    assert "G-04" in md
    assert "MISSING" in md  # APPLICABLE dispatch without artifact
