"""v2.75.2 — shared test helpers for slim/_shared command structure.

After v2.71+ refactors split `commands/vg/<cmd>.md` into slim parent +
`commands/vg/_shared/<cmd>/*.md` sub-files, tests that scan parent only miss
extracted content. This conftest exposes `read_command_full(cmd)` which returns
parent text concatenated with all `_shared/<cmd>/*.md` sub-files (sorted), so
content checks remain valid post-split without per-test fixup.

v3.6.3 — Windows bash path normalization. Tests across this tree use
`subprocess.run(["bash", str(Path)], ...)` to exercise hook + sync scripts.
On Windows, `str(WindowsPath)` produces `D:\\repo\\file.sh`. Git Bash
interprets backslashes as escape characters, so the script path collapses
to `D:repofile.sh` → "No such file or directory". 43 tests fail locally
on Windows; same code passes on Linux CI.

Fix: autouse fixture wraps `subprocess.run` and `subprocess.Popen` so that
when args[0] == "bash" on Windows, args[1] is converted to POSIX form
(forward slashes). Linux/macOS pass-through.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
SHARED_DIR = COMMANDS_DIR / "_shared"


def read_command_full(cmd: str) -> str:
    """Return slim parent + all _shared/<cmd>/*.md sub-files concatenated.

    Use for content scans (regex, substring) that need to find text regardless
    of whether it lives in slim parent or extracted sub-file. Do NOT use for
    structural checks where location matters (e.g., frontmatter parse).
    """
    parent = (COMMANDS_DIR / f"{cmd}.md").read_text(encoding="utf-8")
    shared = SHARED_DIR / cmd
    if not shared.is_dir():
        return parent
    chunks = [parent]
    for sub in sorted(shared.rglob("*.md")):
        chunks.append(sub.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)


def _bash_path(p: str) -> str:
    """Return a Git-Bash-safe form of a path. On Windows convert backslashes
    to forward slashes so bash does not interpret them as escape chars.
    Also resolves 8.3 short-names (LIONEL~1 → Lionel Messi) so that
    Git Bash tools like `tail -F` can locate the file.
    """
    if os.name != "nt":
        return p
    path_obj = Path(p)
    # Resolve expands 8.3 short names and normalises separators; only call
    # when the path looks like a Windows path (has backslash or is absolute).
    if "\\" in p or path_obj.is_absolute():
        try:
            resolved = path_obj.resolve()
            return resolved.as_posix()
        except (OSError, ValueError):
            pass
    if "\\" not in p:
        return p
    return path_obj.as_posix()


def _find_git_bash() -> str | None:
    """Locate Git Bash on Windows. Default `bash` may resolve to WSL launcher,
    which interprets `D:/path/...` as a non-existent WSL path. Git Bash at
    `C:/Program Files/Git/bin/bash.exe` accepts Windows-style paths.
    """
    if os.name != "nt":
        return None
    program_files = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LocalAppData", ""),
    ]
    candidates = []
    for root in program_files:
        if not root:
            continue
        candidates.extend(
            [
                str(Path(root) / "Git" / "bin" / "bash.exe"),
                str(Path(root) / "Git" / "usr" / "bin" / "bash.exe"),
                str(Path(root) / "Programs" / "Git" / "bin" / "bash.exe"),
            ]
        )
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


_GIT_BASH = _find_git_bash() if os.name == "nt" else None


def _normalize_bash_args(args):
    """If args invokes bash, rewrite to use Git Bash (Windows) and convert
    script path to POSIX form. Pass-through on Unix.
    """
    if not isinstance(args, (list, tuple)) or not args:
        return args
    first_str = str(args[0]).lower()
    if not (first_str == "bash" or first_str.endswith(("bash", "bash.exe"))):
        return args
    out = list(args)
    # Replace `bash` with explicit Git Bash if available (avoids WSL launcher)
    if os.name == "nt" and _GIT_BASH and first_str == "bash":
        out[0] = _GIT_BASH
    # Convert subsequent path-like args to forward-slash form
    for i in range(1, len(out)):
        if isinstance(out[i], (str, Path)):
            s = str(out[i])
            if "\\" in s:
                out[i] = _bash_path(s)
    return out


@pytest.fixture(autouse=True)
def _patch_bash_path_for_windows(monkeypatch):
    """Autouse fixture: rewrite bash invocations on Windows so script paths
    use forward slashes. No-op on Unix.
    """
    if os.name != "nt":
        return
    original_run = subprocess.run
    original_popen = subprocess.Popen

    def patched_run(args, *a, **kw):
        return original_run(_normalize_bash_args(args), *a, **kw)

    def patched_popen(args, *a, **kw):
        return original_popen(_normalize_bash_args(args), *a, **kw)

    monkeypatch.setattr(subprocess, "run", patched_run)
    monkeypatch.setattr(subprocess, "Popen", patched_popen)
