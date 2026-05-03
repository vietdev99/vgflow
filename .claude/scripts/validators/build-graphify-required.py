#!/usr/bin/env python3
"""Enforce post-build Graphify refresh evidence.

When graphify.enabled=true, /vg:build must refresh graphify during the current
run and leave a usable graph.json behind. This closes the docs-only gap where
build promised fresh graph context but could finish without creating/updating
graphify-out/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer, read_active_run_id  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"


def _section_value(config: str, section: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(section)}:\s*$", config, re.MULTILINE)
    if not match:
        return default
    tail = config[match.end():]
    next_section = re.search(r"^[a-zA-Z_][\w-]*:\s*$", tail, re.MULTILINE)
    block = tail[: next_section.start()] if next_section else tail
    value = re.search(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", block, re.MULTILINE)
    if not value:
        return default
    return value.group(1).strip().strip("\"'")


def _load_graphify_config() -> dict[str, str]:
    path = REPO_ROOT / ".claude" / "vg.config.md"
    if not path.exists():
        return {
            "enabled": "false",
            "fallback_to_grep": "true",
            "graph_path": "graphify-out/graph.json",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "enabled": _section_value(text, "graphify", "enabled", "false").lower(),
        "fallback_to_grep": _section_value(text, "graphify", "fallback_to_grep", "true").lower(),
        "graph_path": _section_value(text, "graphify", "graph_path", "graphify-out/graph.json"),
    }


def _graph_path(raw: str) -> Path:
    path = Path(os.path.expandvars(raw)).expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _graphify_importable() -> bool:
    override = os.environ.get("VG_GRAPHIFY_REQUIRED_ASSUME_IMPORTABLE")
    if override is not None:
        return override.lower() in {"1", "true", "yes"}
    proc = subprocess.run(
        [sys.executable, "-c", "import graphify"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _read_current_run_id() -> str | None:
    """Resolve current /vg:build run_id with multi-session safety.

    See _common.read_active_run_id for the 4-tier resolution; closes the
    .vg/current-run.json overwrite race when concurrent sessions run /vg:*.
    """
    return read_active_run_id(repo_root=REPO_ROOT, command_filter="vg:build")


def _count_graphify_events(run_id: str) -> int:
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE run_id = ? AND event_type = 'graphify_auto_rebuild'",
            [run_id],
        ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="build-graphify-required")
    with timer(out):
        if not find_phase_dir(args.phase):
            emit_and_exit(out)

        cfg = _load_graphify_config()
        if cfg["enabled"] != "true":
            emit_and_exit(out)

        graph_path = _graph_path(cfg["graph_path"])
        fallback = cfg["fallback_to_grep"] != "false"
        importable = _graphify_importable()

        if not importable:
            evidence = Evidence(
                type="graphify_package_missing",
                message=(
                    "graphify.enabled=true but Python cannot import graphify. "
                    "Build cannot maintain a fresh knowledge graph in this environment."
                ),
                expected="Python import graphify succeeds",
                actual="import graphify failed",
                fix_hint="Install graphifyy[mcp], then rerun /vg:build or /vg:map.",
            )
            if fallback:
                out.warn(evidence)
            else:
                out.add(evidence)
            emit_and_exit(out)

        if not graph_path.exists():
            out.add(Evidence(
                type="graphify_graph_missing_after_build",
                message=(
                    "graphify.enabled=true and graphify is installed, but graph.json "
                    "does not exist after /vg:build. First build should cold-create it."
                ),
                expected=f"graph file exists at {graph_path}",
                actual="missing",
                fix_hint=(
                    "Run: python -m graphify update .\n"
                    "Then rerun /vg:build so build emits graphify_auto_rebuild evidence."
                ),
            ))
            emit_and_exit(out)

        run_id = _read_current_run_id()
        if not run_id:
            emit_and_exit(out)

        events = _count_graphify_events(run_id)
        if events == 0:
            out.add(Evidence(
                type="graphify_rebuild_event_missing",
                message=(
                    "/vg:build completed with graphify.enabled=true but no "
                    "graphify_auto_rebuild event exists in the current run. "
                    "This means the workflow did not actually refresh graphify."
                ),
                expected=">=1 graphify_auto_rebuild event in .vg/events.db for current run",
                actual="0 events",
                fix_hint=(
                    "Source graphify-safe.sh and run "
                    "vg_graphify_rebuild_safe \"$GRAPHIFY_GRAPH_PATH\" \"build-final\", "
                    "then retry vg-orchestrator run-complete."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
