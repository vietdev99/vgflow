"""
R7 Task 4 (G2) — Tests for workflow implementation audit validator.

Coverage:
  Validator (scripts/validators/verify-workflow-implementation.py):
    - test_validator_passes_no_workflow_id           — capsule.workflow_id null → PASS
    - test_validator_passes_when_state_literal_in_handler — workflow + state literal grep hit → PASS
    - test_validator_blocks_when_state_literal_missing  — workflow + no state in modified files → BLOCK rc=1
    - test_validator_warns_when_state_only_in_tests     — state in *.spec.ts only → WARN rc=0
    - test_validator_handles_malformed_workflow_spec    — WORKFLOW-SPECS parse fail → WARN rc=0

  Wiring:
    - test_post_execution_wires_validator             — waves-overview.md 8d.5d block exists
    - test_build_md_frontmatter_has_override_flag     — build.md lists --skip-workflow-implementation-audit

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  - rc 0 → PASS or WARN
  - rc 1 → BLOCK
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-workflow-implementation.py"
WAVES_OVERVIEW_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"
)
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "preflight.md"


# ─── Helpers ──────────────────────────────────────────────────────────


def _stage_phase(
    tmp_path: Path,
    *,
    workflow_yaml: str | None,
    workflow_id: str = "WF-01",
    workflow_step: int | None = 2,
    handler_files: dict[str, str] | None = None,
    test_files: dict[str, str] | None = None,
    other_files: dict[str, str] | None = None,
    task_id: str = "task-04",
) -> Path:
    """Stage a tmp phase dir with one capsule + WORKFLOW-SPECS/<wf>.md + files.

    workflow_yaml=None → capsule has no workflow_id (read-only test surface).
    handler_files: prod-code paths → contents (e.g. apps/api/...).
    test_files: test paths → contents (e.g. *.spec.ts).
    other_files: misc additional paths (e.g. constants.ts, schema.prisma).
    """
    phase_dir = tmp_path / "07.99-test"
    phase_dir.mkdir(parents=True)

    capsule_dir = phase_dir / ".task-capsules"
    capsule_dir.mkdir()

    artifacts: list[str] = []

    if workflow_yaml is not None:
        wf_dir = phase_dir / "WORKFLOW-SPECS"
        wf_dir.mkdir()
        # Wrap raw yaml in a fenced markdown block (parser expects fence).
        md_body = "# Workflow spec\n\n```yaml\n" + workflow_yaml + "\n```\n"
        (wf_dir / f"{workflow_id}.md").write_text(md_body, encoding="utf-8")

    for collection in (handler_files, test_files, other_files):
        if not collection:
            continue
        for rel, contents in collection.items():
            full = tmp_path / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(contents, encoding="utf-8")
            artifacts.append(rel)

    capsule = {
        "task_id": task_id,
        "task_context": {},
        "contract_context": {},
        "goals_context": {},
        "sibling_context": {},
        "downstream_callers": [],
        "build_config": {},
        "tdd_required": False,
    }
    if workflow_yaml is not None:
        capsule["workflow_id"] = workflow_id
        capsule["workflow_step"] = workflow_step

    (capsule_dir / f"{task_id}.capsule.json").write_text(
        json.dumps(capsule), encoding="utf-8",
    )

    if artifacts:
        bl_dir = phase_dir / "BUILD-LOG"
        bl_dir.mkdir()
        artifact_lines = "\n".join(
            f"- {p} (lines added: 5, removed: 0)" for p in artifacts
        )
        (bl_dir / f"{task_id}.md").write_text(
            f"# Task {task_id} — test stub\n\n"
            f"**Files modified**:\n{artifact_lines}\n",
            encoding="utf-8",
        )

    return phase_dir


def _run_validator(phase_dir: Path, repo_root: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if repo_root is not None:
        env["VG_REPO_ROOT"] = str(repo_root)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# Sample WORKFLOW-SPECS yaml — multi-actor approval flow with
# `pending_admin_review` state at step 2.
APPROVAL_WF_YAML = textwrap.dedent("""
    workflow_id: WF-01
    name: Approval flow
    goal_links: ["G-01"]
    actors:
      - role: editor
      - role: admin
    steps:
      - step_id: 1
        actor: editor
        action: submit
        state_after:
          db: pending_admin_review
      - step_id: 2
        actor: admin
        action: review
        cred_switch_marker: true
        state_after:
          db: approved
    state_machine:
      states: [draft, pending_admin_review, approved, rejected]
""").strip()


# ─── Validator behavioral tests ───────────────────────────────────────


def test_validator_passes_no_workflow_id(tmp_path):
    """Capsule with no workflow_id → PASS rc=0."""
    phase_dir = _stage_phase(tmp_path, workflow_yaml=None)
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out


def test_validator_passes_when_state_literal_in_handler(tmp_path):
    """workflow_id set + handler contains state literal → PASS rc=0.

    Capsule wf_step=1 expects `pending_admin_review`. Handler writes it.
    """
    handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          const submission = await db.submissions.create({
            data: { ...body, status: 'pending_admin_review' }
          });
          return Response.json({ id: submission.id }, { status: 201 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        workflow_yaml=APPROVAL_WF_YAML,
        workflow_step=1,
        handler_files={"apps/api/src/submissions/route.ts": handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] in ("PASS", "WARN"), out
    # No BLOCK evidence type.
    types = {e.get("type") for e in out["evidence"]}
    assert "workflow_state_literal_missing" not in types, types


def test_validator_blocks_when_state_literal_missing(tmp_path):
    """workflow_id set + state literal absent from all modified files → BLOCK rc=1.

    Codex audit failure mode: handler implements `approved` while WF
    declares `pending_admin_review` for that step.
    """
    # Step 1 expects `pending_admin_review` but handler writes `approved`.
    bug_handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          const submission = await db.submissions.create({
            data: { ...body, status: 'approved' }  // BUG: skips review
          });
          return Response.json({ id: submission.id }, { status: 201 });
        }
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        workflow_yaml=APPROVAL_WF_YAML,
        workflow_step=1,
        handler_files={"apps/api/src/submissions/route.ts": bug_handler},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK", out
    types = {e.get("type") for e in out["evidence"]}
    assert "workflow_state_literal_missing" in types, types


def test_validator_warns_when_state_only_in_tests(tmp_path):
    """State literal in *.spec.ts only (not in handler) → WARN rc=0."""
    # Handler doesn't reference the state literal at all.
    bare_handler = textwrap.dedent("""
        export async function POST(req) {
          const body = await req.json();
          const submission = await db.submissions.create({ data: body });
          return Response.json({ id: submission.id }, { status: 201 });
        }
    """).strip()
    spec_file = textwrap.dedent("""
        import { test, expect } from '@playwright/test';
        test('submission goes to pending_admin_review', async ({ page }) => {
          // assertion only — implementation lacks the literal
          expect(submission.status).toBe('pending_admin_review');
        });
    """).strip()
    phase_dir = _stage_phase(
        tmp_path,
        workflow_yaml=APPROVAL_WF_YAML,
        workflow_step=1,
        handler_files={"apps/api/src/submissions/route.ts": bare_handler},
        test_files={"apps/api/src/submissions/route.spec.ts": spec_file},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0 (test-only hit), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "workflow_state_only_in_tests" in types, types


def test_validator_handles_malformed_workflow_spec(tmp_path):
    """Malformed WORKFLOW-SPECS yaml → WARN with malformed_spec evidence (not crash)."""
    bad_yaml = "this is: : : not yaml ::: [garbage"
    phase_dir = _stage_phase(
        tmp_path,
        workflow_yaml=bad_yaml,
        workflow_step=1,
        handler_files={"apps/api/src/submissions/route.ts": "export async function POST() {}"},
    )
    proc = _run_validator(phase_dir, repo_root=tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0 (graceful degradation), got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "workflow_malformed_spec" in types, types


# ─── Wiring tests ─────────────────────────────────────────────────────


def test_post_execution_wires_validator():
    """waves-overview.md must wire verify-workflow-implementation.py at 8d.5d."""
    text = WAVES_OVERVIEW_MD.read_text(encoding="utf-8")
    assert "verify-workflow-implementation.py" in text, (
        "waves-overview.md does not invoke verify-workflow-implementation.py "
        "— gate not wired."
    )
    assert "8d.5d" in text, (
        "Section header `8d.5d` not found — workflow audit must be "
        "labeled as sibling of 8d.5c RCRURD audit."
    )
    assert "--skip-workflow-implementation-audit" in text, (
        "waves-overview.md 8d.5d block must reference "
        "--skip-workflow-implementation-audit override flag."
    )


def test_build_md_frontmatter_has_override_flag():
    """build.md `forbidden_without_override` must list --skip-workflow-implementation-audit."""
    text = BUILD_MD.read_text(encoding="utf-8")
    assert "--skip-workflow-implementation-audit" in text, (
        "build.md frontmatter missing `--skip-workflow-implementation-audit`."
    )
    m = re.search(
        r"forbidden_without_override:\s*\n((?:\s+(?:-\s+.+|#.+)\n)+)",
        text,
    )
    assert m is not None, "forbidden_without_override block not found in build.md"
    assert "--skip-workflow-implementation-audit" in m.group(1), (
        "Override flag not under `forbidden_without_override:` block."
    )


def test_preflight_md_allowlists_override_flag():
    """preflight.md VALID_FLAGS_PATTERN must include skip-workflow-implementation-audit."""
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "skip-workflow-implementation-audit" in text, (
        "preflight.md VALID_FLAGS_PATTERN does not allow "
        "--skip-workflow-implementation-audit — flag would be rejected."
    )
