from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build-continuation.py"
ENTRY = REPO_ROOT / "scripts" / "vg-entry-hook.py"


def _run(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or REPO_ROOT),
        env=env or os.environ.copy(),
    )


def _install_continuation_scripts(root: Path) -> None:
    target = root / "scripts"
    (target / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "scripts" / "build-continuation.py", target / "build-continuation.py")
    shutil.copyfile(REPO_ROOT / "scripts" / "lib" / "build_continuation.py", target / "lib" / "build_continuation.py")


def test_write_resolve_and_clear_build_continuation(tmp_path: Path) -> None:
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)

    result = _run([
        "write",
        "--phase-dir", str(phase_dir),
        "--phase", "4.2",
        "--current-wave", "1",
        "--max-wave", "3",
        "--run-id", "run-1",
        "--session-id", "sess-1",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/vg:build 4.2 --wave 2 --resume"

    token = json.loads((phase_dir / ".build-continuation.json").read_text(encoding="utf-8"))
    assert token["next_wave"] == 2
    assert token["max_wave"] == 3
    assert token["canonical_command"] == "/vg:build 4.2 --wave 2 --resume"

    resolved = _run(["resolve", "--root", str(tmp_path), "--prompt", "tiếp tục", "--adapter", "codex"])
    assert resolved.returncode == 0, resolved.stderr
    assert "Canonical command: /vg:build 4.2 --wave 2 --resume" in resolved.stdout
    assert "tasklist-projected --adapter codex" in resolved.stdout

    ignored = _run(["resolve", "--root", str(tmp_path), "--prompt", "tiếp tục nhưng xem thêm log"])
    assert ignored.returncode == 1

    cleared = _run(["clear", "--phase-dir", str(phase_dir)])
    assert cleared.returncode == 0
    assert not (phase_dir / ".build-continuation.json").exists()


def test_final_wave_write_clears_stale_token(tmp_path: Path) -> None:
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)
    _run([
        "write", "--phase-dir", str(phase_dir), "--phase", "4.2",
        "--current-wave", "1", "--max-wave", "2",
    ])
    assert (phase_dir / ".build-continuation.json").exists()

    result = _run([
        "write", "--phase-dir", str(phase_dir), "--phase", "4.2",
        "--current-wave", "2", "--max-wave", "2",
    ])
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert not (phase_dir / ".build-continuation.json").exists()


def test_entry_hook_maps_continue_to_build_continuation_context(tmp_path: Path) -> None:
    _install_continuation_scripts(tmp_path)
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)
    _run([
        "write",
        "--phase-dir", str(phase_dir),
        "--phase", "4.2",
        "--current-wave", "1",
        "--max-wave", "2",
    ])

    result = subprocess.run(
        [sys.executable, str(ENTRY)],
        input=json.dumps({"session_id": "sess-1", "prompt": "continue"}),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "VG_REPO_ROOT": str(tmp_path), "VG_RUNTIME": "codex"},
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["continue"] is True
    context = payload["systemMessage"]
    assert "Canonical command: /vg:build 4.2 --wave 2 --resume" in context
    assert "tasklist-projected --adapter codex" in context
