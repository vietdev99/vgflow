"""Shared repo-root resolver for orchestrator + validators.

Earlier bug: `Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())` fallback
used `cwd` when env unset. A subprocess spawned from a subdirectory would
compute `.vg/events.db` relative to that subdir, creating rogue empty DBs.
Observed in practice at `.claude/scripts/.vg/` and
`.claude/scripts/vg-orchestrator/.vg/`.

Resolution priority:
  1. `VG_REPO_ROOT` env var — explicit, trusted (tests use monkeypatch).
  2. Walk up from `__file__` of the caller looking for `.git/` — stable
     regardless of cwd because script location is anchored.
  3. Fallback: `os.getcwd()` with stderr warning — signals likely rogue DB.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def find_repo_root(start_file: str | None = None) -> Path:
    """Return the repo root as an absolute Path.

    Args:
        start_file: Optional `__file__` of the caller. If provided, walks
          upward from its directory looking for `.git/`. Defaults to this
          helper's own location (works for orchestrator + validators since
          both live under `.claude/scripts/`).
    """
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()

    anchor = Path(start_file).resolve().parent if start_file \
        else Path(__file__).resolve().parent
    for candidate in [anchor, *anchor.parents]:
        if (candidate / ".git").exists():
            return candidate

    print(
        "WARN: vg helper could not locate repo root "
        "(no VG_REPO_ROOT, no .git/ upward from "
        f"{anchor}). Falling back to cwd={Path.cwd()} — this likely "
        "creates rogue .vg/ artifacts.",
        file=sys.stderr,
    )
    return Path.cwd().resolve()
