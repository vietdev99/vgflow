from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ensure-graphify.py"
INSTALL_SH = REPO_ROOT / "install.sh"
SYNC_SH = REPO_ROOT / "sync.sh"


def _load_module():
    spec = importlib.util.spec_from_file_location("ensure_graphify", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_helper_repairs_project_graphify_files(tmp_path: Path) -> None:
    mod = _load_module()
    target = tmp_path / "repo"
    target.mkdir()
    (target / ".claude").mkdir()
    (target / ".claude" / "vg.config.md").write_text(
        "graphify:\n  enabled: true\n",
        encoding="utf-8",
    )
    (target / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    assert mod.ensure_graphifyignore(target, repair=True) is True
    assert mod.ensure_gitignore(target, repair=True) is True
    assert mod.ensure_mcp(target, repair=True) is True

    assert "graphify-out/" in (target / ".graphifyignore").read_text(encoding="utf-8")
    assert "graphify-out/" in (target / ".gitignore").read_text(encoding="utf-8")
    data = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["graphify"]["args"] == [
        "-m",
        "graphify.serve",
        "graphify-out/graph.json",
    ]


def test_helper_respects_graphify_disabled(tmp_path: Path) -> None:
    mod = _load_module()
    target = tmp_path / "repo"
    (target / ".claude").mkdir(parents=True)
    (target / ".claude" / "vg.config.md").write_text(
        "graphify:\n  enabled: false\n",
        encoding="utf-8",
    )

    assert mod.graphify_enabled(target) is False


def test_helper_skip_env_exits_cleanly(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["VGFLOW_SKIP_GRAPHIFY_INSTALL"] = "true"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(tmp_path), "--repair"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "skipped" in result.stdout.lower()


def test_helper_check_mode_detects_repair_needed(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / ".claude").mkdir(parents=True)
    (target / ".claude" / "vg.config.md").write_text(
        "graphify:\n  enabled: true\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["VGFLOW_GRAPHIFY_ASSUME_IMPORTABLE"] = "true"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "repair needed" in result.stdout.lower()


def test_install_sync_update_wire_graphify_helper() -> None:
    install = INSTALL_SH.read_text(encoding="utf-8")
    sync = SYNC_SH.read_text(encoding="utf-8")
    update = (REPO_ROOT / "commands" / "vg" / "update.md").read_text(encoding="utf-8")

    assert "scripts/ensure-graphify.py" in install
    assert "2d. Ensure Graphify" in sync
    assert "ensure-graphify.py" in sync
    assert '<step name="8c_ensure_graphify">' in update
    assert "graphifyy[mcp]" in update
