from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "crossai-runner.py"


def _run(tmp_path: Path, command: str) -> dict:
    context_file = tmp_path / "ctx.md"
    context_file.write_text("# context\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env["VG_RUNTIME"] = "codex"
    env["VG_REPO_ROOT"] = str(REPO_ROOT)

    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--name",
            "Codex",
            "--command",
            command,
            "--prompt",
            "hello",
            "--context-file",
            str(context_file),
            "--output-dir",
            str(output_dir),
            "--timeout",
            "10",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_runner_executes_outside_repo_and_scrubs_runtime_vars(tmp_path: Path) -> None:
    report = _run(
        tmp_path,
        "python3 - <<'PY'\nimport os\nprint(os.getcwd())\nprint(os.environ.get('CLAUDE_PROJECT_DIR',''))\nprint(os.environ.get('VG_RUNTIME',''))\nPY",
    )

    stdout = Path(report["result_file"]).read_text(encoding="utf-8").splitlines()
    assert Path(stdout[0]).resolve() == Path(report["cwd"]).resolve()
    assert Path(stdout[0]).resolve() != REPO_ROOT.resolve()
    assert stdout[1] == ""
    assert stdout[2] == ""


def test_runner_writes_exit_and_meta_files(tmp_path: Path) -> None:
    report = _run(tmp_path, "printf '<crossai_review/>'")
    meta = json.loads(Path(report["meta_file"]).read_text(encoding="utf-8"))
    assert meta["isolated"] is True
    assert Path(report["result_file"]).exists()
    assert Path(report["err_file"]).exists()
    assert Path(tmp_path / "out" / "result-Codex.exit").read_text(encoding="utf-8").strip() == "0"


def test_runner_quotes_context_placeholder_with_spaces(tmp_path: Path) -> None:
    spaced = tmp_path / "dir with spaces"
    spaced.mkdir()
    context_file = spaced / "ctx file.md"
    context_file.write_text("context ok\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--name",
            "Gemini",
            "--command",
            "cat {context}; printf '%s' \"|{prompt}\"",
            "--prompt",
            "hello world",
            "--context-file",
            str(context_file),
            "--output-dir",
            str(output_dir),
            "--timeout",
            "10",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    stdout = Path(report["result_file"]).read_text(encoding="utf-8")
    assert stdout == "context ok\n|hello world"
