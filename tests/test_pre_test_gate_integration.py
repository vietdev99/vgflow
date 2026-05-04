"""End-to-end: T1+T2 runner produces report, deploy decision picks env, writer
emits readable PRE-TEST-REPORT.md."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_full_pipeline_no_deploy(tmp_path: Path) -> None:
    """T1+T2 runner → JSON → writer → PRE-TEST-REPORT.md, with no-deploy."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "Page.tsx").write_text(
        "export function Page() { return <div>ok</div>; }\n", encoding="utf-8",
    )

    t12_report = tmp_path / "t12.json"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "verify-pre-test-tier-1-2.py"),
        "--source-root", str(src),
        "--phase", "intg-1.0",
        "--report-out", str(t12_report),
        "--repo-root", str(tmp_path),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(REPO / "scripts" / "validators" / "write-pre-test-report.py"),
        "--phase", "intg-1.0",
        "--t12-report", str(t12_report),
        "--no-deploy",
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    md = out.read_text(encoding="utf-8")
    assert "intg-1.0" in md
    assert "Tier 1" in md
    assert "Tier 2" in md
    assert "SKIPPED" in md
    assert "Deploy: SKIPPED" in md


def test_deploy_decision_reads_env_baseline(tmp_path: Path) -> None:
    """Synthesize ENV-BASELINE.md, run deploy_decision, verify proposal."""
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | LTS |

        ## Environment matrix
        | Env | Purpose | Hosting | Run | Deploy | DB | Secrets | Auto |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | AI test | vps | pm2 | rsync | postgres | vault | yes |
        | staging | UAT | staging | (cdn) | git push | postgres | vercel | manual |
        | prod | prod | app.com | (cdn) | git push | postgres | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: Stack chosen
        **Reasoning:** match the foundation pick
        **Reverse cost:** LOW
        **Sources cited:** https://example.com
    """).strip(), encoding="utf-8")

    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore
    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": True})
    assert proposal["recommended_env"] == "sandbox"
    assert "sandbox" in proposal["available_envs"]
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_health_check_total_deadline_pattern(tmp_path: Path) -> None:
    """Codex fix #7: health_check must respect total_deadline, not per-request × retries."""
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from post_deploy_smoke import health_check  # type: ignore
    import time as _time

    started = _time.monotonic()
    result = health_check("http://192.0.2.1:7777", path="/health",
                          total_deadline_s=5, poll_interval_s=2)
    elapsed = _time.monotonic() - started
    assert result["status"] == "BLOCK"
    assert elapsed < 7, f"health_check ran {elapsed:.1f}s, expected ≤6s (5s deadline + slack)"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_deploy_state_path_is_phase_dir(tmp_path: Path) -> None:
    """Codex fix #3: DEPLOY-STATE.json lives at PHASE_DIR/, not PLANNING_DIR/."""
    pd = tmp_path / ".vg" / "phases" / "test-1.0"
    pd.mkdir(parents=True)
    (pd / "DEPLOY-STATE.json").write_text(json.dumps({
        "deployed": {"sandbox": {"url": "https://sandbox.example.com", "deployed_at": "2026-05-03"}}
    }), encoding="utf-8")

    assert (pd / "DEPLOY-STATE.json").exists()
    assert not (tmp_path / ".vg" / "DEPLOY-STATE.json").exists()


def test_secret_scan_redacts_match() -> None:
    """Codex fix #6: secret-scan evidence must NOT echo the matched secret."""
    import sys
    import tempfile
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from pre_test_runner import grep_secrets  # type: ignore

    with tempfile.TemporaryDirectory() as td:
        Path(td, "config.ts").write_text(
            'const k = "AKIAIOSFODNN7EXAMPLE";\n', encoding="utf-8",
        )
        result = grep_secrets(Path(td))

    assert result["status"] == "BLOCK"
    for ev in result["evidence"]:
        assert "AKIA" not in ev.get("snippet", ""), "secret leaked into evidence snippet"
        assert "redacted" in ev.get("snippet", "").lower()
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_phase_change_detection_classifies_schema(tmp_path: Path) -> None:
    """Codex fix #3: detect_phase_changes finds 'schema' from migration files."""
    pd = tmp_path / ".vg" / "phases" / "test-1.0"
    (pd / ".task-capsules").mkdir(parents=True)
    (pd / ".task-capsules" / "task-01.capsule.json").write_text(json.dumps({
        "task_id": "task-01",
        "edits_files": ["apps/api/src/db/migrations/0042_add_invoices.sql"],
        "edits_endpoint": "POST /api/invoices",
    }), encoding="utf-8")

    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import detect_phase_changes  # type: ignore
    flags = detect_phase_changes(pd, repo_root=tmp_path)
    assert flags["schema"] is True
    assert flags["backend"] is True
    sys.path.remove(str(REPO / "scripts" / "lib"))
