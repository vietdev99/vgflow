"""
R7 Task 5 (G9) — Tests for multi-actor workflow replay engine + validator.

Coverage:
  Layer 1 — parse_workflow_spec (yaml fence + required keys + state checks)
  Layer 2 — build_replay_plan (ordering, cred_switch derivation,
            visibility & authz probe derivation)
  Layer 4 — execute_replay (mock executor end-to-end, evidence shape)
  Layer 5 — verify-workflow-replay.py validator (PASS/WARN/BLOCK paths)
  Layer 6 — review verdict integration md exists with override flag
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "lib"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-workflow-replay.py"
SCHEMA = REPO_ROOT / "schemas" / "workflow-replay.v1.schema.json"
INTEGRATION_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "verdict"
    / "multi-actor-workflow.md"
)
SESSION_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "verdict"
    / "multi-actor-session.md"
)

sys.path.insert(0, str(LIB))
import workflow_replay as wr  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────


APPROVAL_WF_YAML = textwrap.dedent("""
    workflow_id: WF-01
    name: Approval flow
    goal_links: ["G-01", "G-02"]
    actors:
      - role: editor
        cred_fixture: EDITOR_USER
      - role: admin
        cred_fixture: ADMIN_USER
    steps:
      - step_id: 1
        actor: editor
        action: submit
        view: /editor/submit
        api: POST /api/submissions
        state_after:
          db: pending_admin_review
        goals: ["G-01"]
      - step_id: 2
        actor: admin
        cred_switch_marker: true
        action: review
        view: /admin/queue
        api: POST /api/submissions/:id/approve
        state_after:
          db: approved
        goals: ["G-02"]
    state_machine:
      states: [draft, pending_admin_review, approved, rejected]
      transitions:
        - {from: draft, to: pending_admin_review, by: editor}
        - {from: pending_admin_review, to: approved, by: admin}
    ui_assertions_per_step:
      - step_id: 1
        rcrurd_invariant_ref: G-01
      - step_id: 2
        rcrurd_invariant_ref: G-02
""").strip()


def _write_workflow_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Workflow\n\n```yaml\n{body}\n```\n", encoding="utf-8")


def _stage_phase_with_workflow(
    tmp_path: Path,
    *,
    workflow_yaml: str = APPROVAL_WF_YAML,
    workflow_id: str = "WF-01",
    write_index: bool = True,
) -> Path:
    phase_dir = tmp_path / "07.99-test"
    phase_dir.mkdir(parents=True)
    _write_workflow_md(phase_dir / "WORKFLOW-SPECS" / f"{workflow_id}.md", workflow_yaml)
    if write_index:
        (phase_dir / "WORKFLOW-SPECS" / "index.md").write_text(
            f"# WORKFLOW-SPECS index\n\n- {workflow_id}\n", encoding="utf-8"
        )
    return phase_dir


def _run_validator(phase_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_validator_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# ─── Layer 1: parse_workflow_spec ────────────────────────────────────────


def test_parse_workflow_spec_extracts_actors(tmp_path):
    """parse_workflow_spec returns dict with actors[] and steps[] populated."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    assert spec["workflow_id"] == "WF-01"
    actor_roles = [a["role"] for a in spec["actors"]]
    assert actor_roles == ["editor", "admin"]
    assert len(spec["steps"]) == 2
    assert "pending_admin_review" in spec["state_machine"]["states"]


def test_parse_workflow_spec_rejects_missing_yaml_fence(tmp_path):
    """No yaml fence → WorkflowReplayError."""
    phase_dir = tmp_path / "07.99-test"
    (phase_dir / "WORKFLOW-SPECS").mkdir(parents=True)
    (phase_dir / "WORKFLOW-SPECS" / "WF-01.md").write_text(
        "# Just markdown, no yaml fence", encoding="utf-8",
    )
    with pytest.raises(wr.WorkflowReplayError):
        wr.parse_workflow_spec(phase_dir / "WORKFLOW-SPECS" / "WF-01.md")


def test_parse_workflow_spec_rejects_missing_required_keys(tmp_path):
    """Missing state_machine → WorkflowReplayError."""
    bad = textwrap.dedent("""
        workflow_id: WF-01
        actors: [{role: a}]
        steps: [{step_id: 1, actor: a, action: x}]
    """).strip()
    phase = _stage_phase_with_workflow(tmp_path, workflow_yaml=bad)
    with pytest.raises(wr.WorkflowReplayError):
        wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")


# ─── Layer 2: build_replay_plan ──────────────────────────────────────────


def test_build_replay_plan_orders_steps(tmp_path):
    """Plan steps are 1-indexed monotonic, in spec order."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    assert [p["step_index"] for p in plan] == [1, 2]
    assert plan[0]["actor"] == "editor"
    assert plan[1]["actor"] == "admin"


def test_build_replay_plan_marks_cred_switch(tmp_path):
    """When actor changes between steps, cred_switch=True."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    assert plan[0]["cred_switch"] is False  # first step matches bootstrap actor
    assert plan[1]["cred_switch"] is True   # editor → admin


def test_build_replay_plan_threads_state_before(tmp_path):
    """Step N's state_before == step N-1's state_after."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    assert plan[0]["state_before"] is None
    assert plan[1]["state_before"] == {"db": "pending_admin_review"}
    assert plan[1]["state_after"] == {"db": "approved"}


def test_build_replay_plan_rejects_unknown_state(tmp_path):
    """state_after value not in state_machine.states → error."""
    # Replace only the state_after value (under steps:), leaving the
    # state_machine.states list unchanged, so the value is genuinely undeclared.
    # `db: approved` appears once inside steps; the states[] uses bare YAML
    # flow syntax (no `db:` prefix) so the targeted replace is unambiguous.
    bad = APPROVAL_WF_YAML.replace("db: approved", "db: obliterated")
    phase = _stage_phase_with_workflow(tmp_path, workflow_yaml=bad)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    with pytest.raises(wr.WorkflowReplayError):
        wr.build_replay_plan(spec)


def test_derive_authz_negative_probes_covers_other_actors(tmp_path):
    """For each step with api, every OTHER actor becomes a probe."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    probes = wr.derive_authz_negative_probes(spec, plan)
    # 2 actors × 2 step.api = 2 probes (each actor probes the other's api once)
    assert len(probes) == 2
    actors = {p["attempted_by"] for p in probes}
    assert actors == {"editor", "admin"}
    for p in probes:
        assert p["expected_status"] == 403


def test_derive_visibility_checks_emits_on_cred_switch(tmp_path):
    """Cross-role visibility check emitted when cred_switch=True."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    checks = wr.derive_visibility_checks(spec, plan)
    assert len(checks) == 1
    assert checks[0]["from_role"] == "admin"
    assert "pending_admin_review" in checks[0]["checked"]


# ─── Layer 4: execute_replay (with mock executor) ───────────────────────


def test_execute_replay_mock_mode_emits_partial(tmp_path):
    """mode='mock' (no executors) → overall_verdict=PARTIAL with TODO notes."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    result = wr.execute_replay(
        plan, phase_dir=phase, deployed_url=None,
        mode="mock", workflow_id="WF-01", spec=spec,
    )
    assert result["overall_verdict"] == "PARTIAL"
    assert result["execution_mode"] == "mock"
    assert all(s["verdict"] == "SKIPPED" for s in result["steps"])
    assert result["actors_used"] == ["editor", "admin"]
    assert len(result["notes"]) >= 1


def test_execute_replay_writes_evidence_json(tmp_path):
    """Result dict + write_replay_evidence → readable JSON file."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)
    result = wr.execute_replay(
        plan, phase_dir=phase, deployed_url=None,
        mode="mock", workflow_id="WF-01", spec=spec,
    )
    out = phase / ".runs" / "WF-01.replay.json"
    wr.write_replay_evidence(result, out)
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["workflow_id"] == "WF-01"
    assert parsed["schema_version"] == "1.0"
    assert "steps" in parsed
    assert "cross_role_visibility" in parsed
    assert "authz_negative_paths" in parsed


def test_execute_replay_with_passing_executor(tmp_path):
    """Live-style executor → all steps PASSED → overall=PASSED."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)

    def step_exec(entry, ctx):
        return {"verdict": "PASSED", "evidence": {
            "screenshot_path": f"step-{entry['step_index']}.png",
            "console_logs": [],
            "network_requests": [],
            "ui_assertions": ["state matched"],
        }}

    def vis_exec(check, ctx):
        return {"verdict": "VISIBLE", "actual": check["expected"]}

    def authz_exec(probe, ctx):
        return {"verdict": "PASSED", "actual_status": 403}

    result = wr.execute_replay(
        plan, phase_dir=phase, deployed_url="https://staging.example.com",
        mode="live", workflow_id="WF-01", spec=spec,
        step_executor=step_exec,
        visibility_executor=vis_exec,
        authz_executor=authz_exec,
    )
    assert result["overall_verdict"] == "PASSED"
    assert all(s["verdict"] == "PASSED" for s in result["steps"])
    assert result["cross_role_visibility"][0]["verdict"] == "VISIBLE"
    assert all(a["verdict"] == "PASSED" for a in result["authz_negative_paths"])


def test_execute_replay_with_failing_step_emits_blocking_failure(tmp_path):
    """Step executor returns FAILED → overall=FAILED with blocking_failures populated."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)

    def bad_exec(entry, ctx):
        if entry["step_index"] == 2:
            return {"verdict": "FAILED",
                    "failure_reason": "admin approve handler returned 500"}
        return {"verdict": "PASSED", "evidence": {}}

    result = wr.execute_replay(
        plan, phase_dir=phase, deployed_url="https://staging.example.com",
        mode="live", workflow_id="WF-01", spec=spec,
        step_executor=bad_exec,
    )
    assert result["overall_verdict"] == "FAILED"
    assert any("step 2" in f for f in result["blocking_failures"])


def test_execute_replay_authz_failure_blocks(tmp_path):
    """Wrong-role action succeeds → authz check FAILED → overall=FAILED."""
    phase = _stage_phase_with_workflow(tmp_path)
    spec = wr.parse_workflow_spec(phase / "WORKFLOW-SPECS" / "WF-01.md")
    plan = wr.build_replay_plan(spec)

    def step_exec(entry, ctx):
        return {"verdict": "PASSED", "evidence": {}}

    def authz_exec(probe, ctx):
        # Editor probing admin-only api gets 200 (BUG!)
        if probe["attempted_by"] == "editor":
            return {"verdict": "FAILED", "actual_status": 200}
        return {"verdict": "PASSED", "actual_status": 403}

    result = wr.execute_replay(
        plan, phase_dir=phase, deployed_url="https://staging.example.com",
        mode="live", workflow_id="WF-01", spec=spec,
        step_executor=step_exec, authz_executor=authz_exec,
    )
    assert result["overall_verdict"] == "FAILED"
    assert any("authz" in f for f in result["blocking_failures"])


# ─── Layer 5: validator ───────────────────────────────────────────────────


def test_validator_passes_on_complete_replay(tmp_path):
    """All workflows have replay JSON with overall_verdict=PASSED → PASS rc=0."""
    phase = _stage_phase_with_workflow(tmp_path)
    runs = phase / ".runs"
    runs.mkdir()
    (runs / "WF-01.replay.json").write_text(json.dumps({
        "workflow_id": "WF-01",
        "schema_version": "1.0",
        "replay_started_at": "2026-05-05T10:00:00Z",
        "replay_completed_at": "2026-05-05T10:00:30Z",
        "actors_used": ["editor", "admin"],
        "steps": [],
        "cross_role_visibility": [],
        "authz_negative_paths": [],
        "overall_verdict": "PASSED",
        "blocking_failures": [],
        "notes": [],
    }), encoding="utf-8")

    proc = _run_validator(phase)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_validator_output(proc)
    assert out["verdict"] == "PASS", out


def test_validator_blocks_on_missing_replay_json(tmp_path):
    """WORKFLOW-SPECS exists but no .runs/<WF>.replay.json → BLOCK rc=1."""
    phase = _stage_phase_with_workflow(tmp_path)
    proc = _run_validator(phase)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_validator_output(proc)
    assert out["verdict"] == "BLOCK", out
    types = {e.get("type") for e in out["evidence"]}
    assert "missing_file" in types, types


def test_validator_blocks_on_failed_overall_verdict(tmp_path):
    """Replay JSON exists with overall_verdict=FAILED → BLOCK rc=1."""
    phase = _stage_phase_with_workflow(tmp_path)
    runs = phase / ".runs"
    runs.mkdir()
    (runs / "WF-01.replay.json").write_text(json.dumps({
        "workflow_id": "WF-01",
        "schema_version": "1.0",
        "replay_started_at": "2026-05-05T10:00:00Z",
        "replay_completed_at": "2026-05-05T10:00:30Z",
        "actors_used": ["editor", "admin"],
        "steps": [],
        "cross_role_visibility": [],
        "authz_negative_paths": [],
        "overall_verdict": "FAILED",
        "blocking_failures": ["step 2 (admin/review) failed: handler 500"],
        "notes": [],
    }), encoding="utf-8")

    proc = _run_validator(phase)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_validator_output(proc)
    assert out["verdict"] == "BLOCK", out
    types = {e.get("type") for e in out["evidence"]}
    assert "semantic_check_failed" in types, types


def test_validator_warns_on_partial_overall_verdict(tmp_path):
    """Replay JSON with overall_verdict=PARTIAL → WARN rc=0."""
    phase = _stage_phase_with_workflow(tmp_path)
    runs = phase / ".runs"
    runs.mkdir()
    (runs / "WF-01.replay.json").write_text(json.dumps({
        "workflow_id": "WF-01",
        "schema_version": "1.0",
        "replay_started_at": "2026-05-05T10:00:00Z",
        "replay_completed_at": "2026-05-05T10:00:30Z",
        "actors_used": ["editor", "admin"],
        "execution_mode": "mock",
        "steps": [],
        "cross_role_visibility": [],
        "authz_negative_paths": [],
        "overall_verdict": "PARTIAL",
        "blocking_failures": [],
        "notes": ["live MCP unavailable"],
    }), encoding="utf-8")

    proc = _run_validator(phase)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_validator_output(proc)
    assert out["verdict"] == "WARN", out


def test_validator_passes_when_no_workflows_declared(tmp_path):
    """Empty index.md (flows: []) → PASS rc=0."""
    phase_dir = tmp_path / "07.99-test"
    (phase_dir / "WORKFLOW-SPECS").mkdir(parents=True)
    (phase_dir / "WORKFLOW-SPECS" / "index.md").write_text(
        "# WORKFLOW-SPECS index\n\nflows: []\n", encoding="utf-8",
    )
    proc = _run_validator(phase_dir)
    assert proc.returncode == 0
    out = _parse_validator_output(proc)
    assert out["verdict"] == "PASS"


def test_validator_warns_on_schema_version_mismatch(tmp_path):
    """Wrong schema_version → WARN (still permits PASS verdict overall)."""
    phase = _stage_phase_with_workflow(tmp_path)
    runs = phase / ".runs"
    runs.mkdir()
    (runs / "WF-01.replay.json").write_text(json.dumps({
        "workflow_id": "WF-01",
        "schema_version": "0.9",  # mismatch
        "replay_started_at": "2026-05-05T10:00:00Z",
        "replay_completed_at": "2026-05-05T10:00:30Z",
        "actors_used": ["editor", "admin"],
        "steps": [],
        "cross_role_visibility": [],
        "authz_negative_paths": [],
        "overall_verdict": "PASSED",
        "blocking_failures": [],
        "notes": [],
    }), encoding="utf-8")

    proc = _run_validator(phase)
    out = _parse_validator_output(proc)
    assert proc.returncode == 0
    types = {e.get("type") for e in out["evidence"]}
    assert "schema_violation" in types, out


# ─── Layer 6: review verdict integration md ──────────────────────────────


def test_review_verdict_md_documents_workflow_replay():
    """multi-actor-workflow.md exists, references key plumbing pieces."""
    assert INTEGRATION_MD.exists(), INTEGRATION_MD
    body = INTEGRATION_MD.read_text(encoding="utf-8")
    # Wires the validator
    assert "verify-workflow-replay.py" in body
    # References the engine
    assert "workflow_replay" in body
    # References the schema
    assert "workflow-replay.v1" in body or "workflow-replay" in body
    # References per-actor session sub-ref
    assert "multi-actor-session" in body


def test_review_md_frontmatter_has_override_flag():
    """Override flag --skip-multi-actor-replay documented + paired with --override-reason."""
    body = INTEGRATION_MD.read_text(encoding="utf-8")
    assert "--skip-multi-actor-replay" in body
    assert "--override-reason" in body
    # Sibling reference
    session_body = SESSION_MD.read_text(encoding="utf-8")
    assert "cred_fixture" in session_body or "credentials" in session_body


def test_evidence_schema_loads_as_valid_json():
    """schemas/workflow-replay.v1.schema.json parses + declares required keys."""
    body = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert body["title"].startswith("VGFlow Workflow Replay")
    required = body["required"]
    assert "workflow_id" in required
    assert "overall_verdict" in required
    assert "steps" in required
