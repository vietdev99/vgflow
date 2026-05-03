"""phase_ownership — auto-fix scope guard.

Per Codex review (2026-05-03) blind-spot #6: auto-fix subagent MUST NOT
modify files outside the current phase's stated ownership. Ownership is
extracted from PLAN/task-*.md files via two patterns:

  Pattern A (single file):    "File: <path>" or "Edits: <path>"
  Pattern B (directory):      "Edits dir: <path>/"

A path is OWNED when:
  - exact match against any pattern A
  - prefix match against any pattern B (directory)
"""
from __future__ import annotations

import re
from pathlib import Path

FILE_RE = re.compile(r"(?:^|\b)(?:File|Edits)\s*:\s*(\S+)", re.MULTILINE)
DIR_RE = re.compile(r"(?:^|\b)Edits\s+dir\s*:\s*(\S+/)", re.MULTILINE)


def _extract(phase_dir: Path) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    dirs: list[str] = []
    plan_dir = phase_dir / "PLAN"
    if not plan_dir.exists():
        return files, dirs
    for tp in plan_dir.glob("task-*.md"):
        try:
            text = tp.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in FILE_RE.finditer(text):
            files.add(m.group(1))
        for m in DIR_RE.finditer(text):
            dirs.append(m.group(1))
    return files, dirs


def owned_paths(phase_dir: Path) -> set[str]:
    """Return set of explicit file paths owned by this phase."""
    files, _ = _extract(phase_dir)
    return files


def is_owned(path: str, phase_dir: Path) -> bool:
    """Check if the given path is within this phase's ownership."""
    files, dirs = _extract(phase_dir)
    if path in files:
        return True
    return any(path.startswith(d) for d in dirs)
