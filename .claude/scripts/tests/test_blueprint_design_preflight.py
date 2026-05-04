from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "blueprint-design-preflight.py"
BLUEPRINT = REPO_ROOT / "commands" / "vg" / "blueprint.md"


def _write_config(repo: Path, pattern: str = "mockups/*.png") -> Path:
    cfg = repo / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "design_assets:\n"
        "  paths:\n"
        f"    - \"{pattern}\"\n"
        "  shared_dir: .vg/design-system\n"
        "  output_dir: .vg/design-normalized\n",
        encoding="utf-8",
    )
    return cfg


def _run(repo: Path, phase: Path, cfg: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--phase-dir",
            str(phase),
            "--repo-root",
            str(repo),
            "--config",
            str(cfg),
            "--apply",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_preflight_imports_existing_mockups_for_ui_phase(tmp_path: Path) -> None:
    repo = tmp_path
    cfg = _write_config(repo)
    phase = repo / ".vg" / "phases" / "02-ui"
    phase.mkdir(parents=True)
    (phase / "CONTEXT.md").write_text(
        "## UI Components\nBuild dashboard and settings screen.\n",
        encoding="utf-8",
    )
    (repo / "mockups").mkdir()
    (repo / "mockups" / "dashboard.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    payload = _run(repo, phase, cfg)

    imported = phase / "design" / "dashboard.png"
    assert payload["has_ui"] is True
    assert payload["imported_count"] == 1
    assert imported.exists()
    assert payload["needs_scaffold"] is False
    assert payload["needs_extract"] is True


def test_preflight_requests_scaffold_when_ui_phase_has_no_mockups(tmp_path: Path) -> None:
    repo = tmp_path
    cfg = _write_config(repo)
    phase = repo / ".vg" / "phases" / "02-ui"
    phase.mkdir(parents=True)
    (phase / "CONTEXT.md").write_text(
        "Frontend dashboard view with sidebar and modal.",
        encoding="utf-8",
    )

    payload = _run(repo, phase, cfg)

    assert payload["has_ui"] is True
    assert payload["phase_mockup_count"] == 0
    assert payload["needs_scaffold"] is True
    assert payload["verdict"] == "NEEDS_SCAFFOLD"


def test_blueprint_wires_proactive_design_scaffold_and_extract() -> None:
    text = BLUEPRINT.read_text(encoding="utf-8")

    assert "blueprint-design-preflight.py" in text
    assert "SlashCommand: /vg:design-scaffold --tool=pencil-mcp" in text
    assert "SlashCommand: /vg:design-extract --auto" in text
    assert "AskUserQuestion: \"Extract design assets now?" not in text
