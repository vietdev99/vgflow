"""
Run state machine. current_run.json is a convenience cache — authoritative
state lives in .vg/events.db (runs + events tables).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from _repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
CURRENT_RUN_FILE = REPO_ROOT / ".vg" / "current-run.json"


def write_current_run(run: dict) -> None:
    """Atomic write via tmp + rename."""
    CURRENT_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CURRENT_RUN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(CURRENT_RUN_FILE))


def read_current_run() -> dict | None:
    if not CURRENT_RUN_FILE.exists():
        return None
    try:
        return json.loads(CURRENT_RUN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_current_run() -> None:
    try:
        CURRENT_RUN_FILE.unlink()
    except FileNotFoundError:
        pass


def mark_step(phase_dir: Path, namespace: str, step_name: str) -> Path:
    """Touch a step marker file. Namespaced to avoid cross-command conflicts."""
    if namespace == "shared":
        marker_dir = phase_dir / ".step-markers"
    else:
        marker_dir = phase_dir / ".step-markers" / namespace
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{step_name}.done"
    marker.touch()
    return marker


def check_markers(phase_dir: Path, markers: list[dict],
                  fallback_namespaces: list[str] | None = None) -> list[str]:
    """
    Returns list of missing marker names.
    A marker is considered present if found in its declared namespace OR any
    fallback namespace. This makes frontmatter declarations forgiving across
    v1 (shared) and v2 (per-command) marker layouts.
    """
    fallbacks = fallback_namespaces or []
    missing = []
    for m in markers:
        ns = m.get("namespace", "shared")
        name = m["name"]
        # Candidate paths (declared + fallbacks + shared root always as last resort)
        candidates = []
        if ns == "shared":
            candidates.append(phase_dir / ".step-markers" / f"{name}.done")
        else:
            candidates.append(phase_dir / ".step-markers" / ns / f"{name}.done")

        for fb in fallbacks:
            if fb == ns:
                continue
            if fb == "shared":
                candidates.append(phase_dir / ".step-markers" / f"{name}.done")
            else:
                candidates.append(phase_dir / ".step-markers" / fb / f"{name}.done")

        # Always also check shared as final fallback
        shared_path = phase_dir / ".step-markers" / f"{name}.done"
        if shared_path not in candidates:
            candidates.append(shared_path)

        if not any(c.exists() for c in candidates):
            label = f"{ns}/{name}" if ns != "shared" else name
            missing.append(label)
    return missing
