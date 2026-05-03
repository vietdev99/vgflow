from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from design_ref_resolver import (  # noqa: E402
    extract_design_ref_entries,
    first_screenshot,
    resolve_design_assets,
)

PRE_EXECUTOR = REPO_ROOT / "scripts" / "pre-executor-check.py"
DESIGN_CHECK = REPO_ROOT / "scripts" / "design-ref-check.py"
READ_EVIDENCE = REPO_ROOT / "scripts" / "validators" / "verify-read-evidence.py"
DESIGN_HONORED = REPO_ROOT / "scripts" / "validators" / "verify-design-ref-honored.py"


def _write_config(repo: Path) -> Path:
    cfg = repo / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "design_assets:\n"
        "  shared_dir: .vg/design-system\n"
        "  output_dir: .vg/design-normalized\n",
        encoding="utf-8",
    )
    return cfg


def test_resolver_prefers_phase_designs_png_over_shared(tmp_path: Path) -> None:
    repo = tmp_path
    phase = repo / ".vg" / "phases" / "01-ui"
    (phase / "designs").mkdir(parents=True)
    (repo / ".vg" / "design-system" / "screenshots").mkdir(parents=True)
    phase_png = phase / "designs" / "home-dashboard.png"
    shared_png = repo / ".vg" / "design-system" / "screenshots" / "home-dashboard.default.png"
    phase_png.write_bytes(b"\x89PNG\r\n\x1a\nphase")
    shared_png.write_bytes(b"\x89PNG\r\n\x1a\nshared")

    assets = resolve_design_assets(
        "home-dashboard",
        repo_root=repo,
        phase_dir=phase,
        config={"design_assets.shared_dir": ".vg/design-system"},
    )

    assert first_screenshot(assets) == phase_png.resolve()
    assert assets.tier == "phase-legacy-designs"


def test_design_ref_classification_skips_form_b_and_descriptive_phrases() -> None:
    entries = extract_design_ref_entries(
        "<design-ref>home-dashboard, settings-panel</design-ref>\n"
        "<design-ref>no-asset:greenfield-explicit-skip</design-ref>\n"
        "<design-ref>Phase 7.13 AdvCampaignWizard pattern</design-ref>\n"
    )

    assert [(e.value, e.kind) for e in entries] == [
        ("home-dashboard", "slug"),
        ("settings-panel", "slug"),
        ("no-asset:greenfield-explicit-skip", "no_asset"),
        ("Phase 7.13 AdvCampaignWizard pattern", "descriptive"),
    ]


def test_pre_executor_injects_phase_local_designs_png(tmp_path: Path) -> None:
    repo = tmp_path
    cfg = _write_config(repo)
    phase = repo / ".vg" / "phases" / "01-ui"
    (phase / "designs").mkdir(parents=True)
    png = phase / "designs" / "home-dashboard.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    (phase / "PLAN.md").write_text(
        "## Task 1: Home dashboard\n\n"
        "<file-path>apps/web/src/Home.tsx</file-path>\n"
        "<design-ref>home-dashboard</design-ref>\n"
        "Build the dashboard.\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(PRE_EXECUTOR),
            "--phase-dir",
            str(phase),
            "--task-num",
            "1",
            "--config",
            str(cfg),
            "--repo-root",
            str(repo),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["design_image_required"] is True
    assert payload["design_image_paths"] == [str(png.resolve())]
    assert f"Read: {png.resolve()}" in payload["design_context"]


def test_design_ref_check_detects_stale_wave_tasks(tmp_path: Path) -> None:
    repo = tmp_path
    cfg = _write_config(repo)
    phase = repo / ".vg" / "phases" / "01-ui"
    (phase / "designs").mkdir(parents=True)
    (phase / ".wave-tasks").mkdir(parents=True)
    (phase / "designs" / "home-dashboard.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (phase / "PLAN.md").write_text(
        "## Task 1\n<design-ref>home-dashboard</design-ref>\n",
        encoding="utf-8",
    )
    (phase / ".wave-tasks" / "task-1.md").write_text(
        "## Task 1\n<design-ref>no-asset:old-gap</design-ref>\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(DESIGN_CHECK),
            "--phase-dir",
            str(phase),
            "--repo-root",
            str(repo),
            "--config",
            str(cfg),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["missing"] == []
    assert payload["wave_tasks_stale"] is True
    assert payload["plan_slug_signature"] == "home-dashboard"
    assert payload["wave_slug_signature"] == ""


def test_read_evidence_validator_accepts_phase_designs_png(tmp_path: Path) -> None:
    repo = tmp_path
    phase = repo / ".vg" / "phases" / "01-ui"
    (phase / "designs").mkdir(parents=True)
    (phase / ".read-evidence").mkdir(parents=True)
    png = phase / "designs" / "home-dashboard.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nphase")
    import hashlib

    (phase / ".read-evidence" / "task-1.json").write_text(
        json.dumps({
            "task": 1,
            "slug": "home-dashboard",
            "read_paths": [{
                "path": str(png.resolve()),
                "sha256_at_read": hashlib.sha256(png.read_bytes()).hexdigest(),
            }],
            "read_at": "2026-04-29T00:00:00Z",
        }),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(READ_EVIDENCE),
            "--phase-dir",
            str(phase),
            "--task-num",
            "1",
            "--slug",
            "home-dashboard",
            "--design-dir",
            ".vg/design-normalized",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["expected_png"] == str(png.resolve())


def test_design_ref_honored_accepts_phase_designs_png(tmp_path: Path) -> None:
    repo = tmp_path
    phase = repo / ".vg" / "phases" / "01-ui"
    (phase / "designs").mkdir(parents=True)
    (phase / "designs" / "home-dashboard.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (phase / "PLAN.md").write_text(
        "## Task 1\n<design-ref>home-dashboard</design-ref>\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(DESIGN_HONORED), "--phase", "01"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] in {"PASS", "WARN"}
