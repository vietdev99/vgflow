"""F5 v2.64.0: verify-workflow-evidence.py — workflow tracer validator."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-workflow-evidence.py"


def _setup(tmp_path: Path, phase: str, workflows: list[str], fe_files: dict[str, str], be_files: dict[str, str] | None = None):
    """Create test phase + workflow specs + FE/BE source trees."""
    phase_dir = tmp_path / ".vg" / "phases" / phase
    wf_dir = phase_dir / "WORKFLOW-SPECS"
    wf_dir.mkdir(parents=True)

    for i, body in enumerate(workflows, 1):
        wf_id = f"WF-{i:03d}"
        (wf_dir / f"{wf_id}.md").write_text(
            f"```yaml\n{body.strip()}\n```\n", encoding="utf-8",
        )

    fe_root = tmp_path / "fe"
    fe_root.mkdir(exist_ok=True)
    for path, content in fe_files.items():
        full = fe_root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    be_root = tmp_path / "be"
    be_root.mkdir(exist_ok=True)
    if be_files:
        for path, content in be_files.items():
            full = be_root / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")

    return phase_dir, fe_root, be_root


def test_clean_match(tmp_path):
    phase_dir, fe_root, be_root = _setup(
        tmp_path, "1.0",
        workflows=[textwrap.dedent("""
            id: WF-001
            name: User saves form
            actors: [user, FE, BE]
            steps:
              - actor: user
                action: click submit
                selector: button[type=submit]
              - actor: FE
                action: POST /api/users
              - actor: BE
                action: persist
        """)],
        fe_files={
            "Form.tsx": textwrap.dedent("""
                function UserForm() {
                  const handleSubmit = async () => {
                    await fetch('/api/users', { method: 'POST' });
                  };
                  return <button type="submit" onClick={handleSubmit}>Save</button>;
                }
            """).strip(),
        },
        be_files={
            "users.ts": "router.post('/users', async (req, res) => { await db.save(req.body); });",
        },
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "1.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(be_root)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    evidence = phase_dir / "WORKFLOW-EVIDENCE" / "WF-001.json"
    assert evidence.exists()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["workflow_id"] == "WF-001"
    assert data["summary"]["total_steps"] == 3
    statuses = [s["status"] for s in data["steps"]]
    # All 3 steps should be found
    assert all(s in ("found", "ambiguous") for s in statuses), (
        f"Expected all found, got {statuses}"
    )


def test_missing_step_warn_default(tmp_path):
    """Missing handler → WARN by default (rc=0), evidence written."""
    phase_dir, fe_root, be_root = _setup(
        tmp_path, "2.0",
        workflows=[textwrap.dedent("""
            id: WF-001
            name: Login
            actors: [user, FE]
            steps:
              - actor: FE
                action: POST /api/login
              - actor: FE
                action: handle response
              - actor: FE
                action: navigate
        """)],
        fe_files={
            # Only POST is implemented; no .then(), no navigate
            "Login.tsx": "fetch('/api/login', { method: 'POST' });",
        },
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "2.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(be_root)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0, "warn-only default — drift does not BLOCK"
    data = json.loads((phase_dir / "WORKFLOW-EVIDENCE" / "WF-001.json").read_text(encoding="utf-8"))
    statuses = [s["status"] for s in data["steps"]]
    # Should detect 2 missing (handle response + navigate)
    assert "missing" in statuses


def test_strict_blocks_on_missing(tmp_path):
    """--strict + missing step → BLOCK (rc=1)."""
    phase_dir, fe_root, _ = _setup(
        tmp_path, "3.0",
        workflows=[textwrap.dedent("""
            id: WF-001
            actors: [FE]
            steps:
              - actor: FE
                action: POST /api/x
              - actor: FE
                action: handle response
        """)],
        fe_files={"app.tsx": "fetch('/api/x', { method: 'POST' });"},
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "3.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(tmp_path), "--strict"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 1, "strict mode must BLOCK on missing step"


def test_strict_blocks_on_divergent_url(tmp_path):
    """FE calls /api/v2/users but workflow says /api/users → divergent → BLOCK in strict."""
    phase_dir, fe_root, _ = _setup(
        tmp_path, "4.0",
        workflows=[textwrap.dedent("""
            id: WF-001
            actors: [FE]
            steps:
              - actor: FE
                action: POST /api/users
        """)],
        fe_files={"x.tsx": "fetch('/api/v2/users', { method: 'POST' });"},
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "4.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(tmp_path), "--strict"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 1
    data = json.loads((phase_dir / "WORKFLOW-EVIDENCE" / "WF-001.json").read_text(encoding="utf-8"))
    # Divergent or missing — both should BLOCK in strict
    statuses = [s["status"] for s in data["steps"]]
    assert any(s in ("divergent", "missing") for s in statuses)


def test_no_workflows_returns_2(tmp_path):
    """No WORKFLOW-SPECS dir → rc=2 (invocation error)."""
    phase_dir = tmp_path / ".vg" / "phases" / "5.0"
    phase_dir.mkdir(parents=True)
    fe_root = tmp_path / "fe"
    fe_root.mkdir()

    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "5.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    # No workflows → rc=2 (per design §3a) — gate skipped silently in delegation
    assert r.returncode == 2


def test_evidence_summary_path_writes(tmp_path):
    phase_dir, fe_root, be_root = _setup(
        tmp_path, "6.0",
        workflows=[textwrap.dedent("""
            id: WF-001
            actors: [FE]
            steps:
              - actor: FE
                action: POST /api/x
        """)],
        fe_files={"x.tsx": "fetch('/api/x', { method: 'POST' });"},
    )
    summary_path = tmp_path / "summary.json"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "6.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(be_root),
         "--evidence-out", str(summary_path)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "workflows" in summary or "summary" in summary or len(summary) > 0


def test_workflow_id_filter(tmp_path):
    phase_dir, fe_root, _ = _setup(
        tmp_path, "7.0",
        workflows=[
            "id: WF-001\nactors: [FE]\nsteps:\n  - actor: FE\n    action: POST /a\n",
            "id: WF-002\nactors: [FE]\nsteps:\n  - actor: FE\n    action: POST /b\n",
        ],
        fe_files={"x.tsx": "fetch('/a', { method: 'POST' });"},
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.0",
         "--phase-dir", str(phase_dir),
         "--fe-root", str(fe_root), "--be-root", str(tmp_path),
         "--workflow-id", "WF-001"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    # Only WF-001 evidence written
    assert (phase_dir / "WORKFLOW-EVIDENCE" / "WF-001.json").exists()
    assert not (phase_dir / "WORKFLOW-EVIDENCE" / "WF-002.json").exists()


def test_validator_mirror():
    canonical = REPO_ROOT / "scripts" / "validators" / "verify-workflow-evidence.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-workflow-evidence.py"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()
